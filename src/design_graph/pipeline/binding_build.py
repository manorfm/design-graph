"""Opt-in binding stage of the normal build, with new-destination-only sealing.

The ordinary capture and GraphWriter remain responsible for the general model.
This session only adds the reviewed snapshot and strict failure/seal policy.
"""

from __future__ import annotations

import fcntl
import json
import os
from dataclasses import dataclass
from hashlib import sha256
from pathlib import Path
from uuid import uuid4

import kuzu

from design_graph.capture import binding_capture, binding_units
from design_graph.capture.binding_capture import BindingCapture
from design_graph.capture.binding_units import enumerate_units
from design_graph.model.graph.binding_context import (
    LOGICAL_VERSION,
    PHYSICAL_VERSION,
    BindingRoot,
    BindingSnapshot,
    read_binding_context,
    write_binding_context,
)
from design_graph.model.graph.schema import MODEL_VERSION, initialize_schema
from design_graph.model.graph.writer import GraphWriter

CONTRACT = "binding-build/1"


@dataclass(frozen=True)
class BindingBuildOptions:
    node: Path
    engine: Path
    fingerprint: str


class BindingStage:
    def __init__(self, document, options):
        self.producer = BindingCapture(
            node=options.node, toolchain=options.engine, fingerprint=options.fingerprint
        )
        self.units, self.coverage = enumerate_units(document)
        assets = self.producer.assets
        adaptor = {
            p.name: sha256(p.read_bytes()).hexdigest()
            for p in sorted(assets.glob("*.mjs"))
        }
        for module in (binding_capture, binding_units):
            adaptor[Path(module.__file__).name] = sha256(
                Path(module.__file__).read_bytes()
            ).hexdigest()
        raw = document.path.read_bytes()
        if raw.decode("utf8", errors="strict") != document.text:
            raise ValueError("source changed during capture")
        self.manifest = {
            "contract": CONTRACT,
            "logical": LOGICAL_VERSION,
            "physical": PHYSICAL_VERSION,
            "source_sha256": sha256(raw).hexdigest(),
            "source_path": str(document.path.resolve()),
            "engine": options.fingerprint,
            "adaptor": adaptor,
            "model": MODEL_VERSION,
            "units": [u.metadata() for u in self.units],
            "coverage": self.coverage,
            "linkage": "independent-static-units; runtime multi-script linkage unknown",
        }
        self.fingerprint = sha256(
            json.dumps(self.manifest, sort_keys=True).encode()
        ).hexdigest()
        self.snapshot = None

    @staticmethod
    def manifest_path(db):
        return Path(str(db) + ".binding.json")

    def unchanged(self, db):
        path = self.manifest_path(db)
        if not path.exists():
            return False
        previous = json.loads(path.read_text())
        if previous.get("build_fingerprint") != self.fingerprint:
            return False
        database = kuzu.Database(
            str(db),
            read_only=True,
            buffer_pool_size=128 * 1024 * 1024,
            max_num_threads=2,
        )
        try:
            connection = kuzu.Connection(database)
            try:
                snapshot = read_binding_context(connection, previous["snapshot"])
                return (
                    snapshot is not None and snapshot.digest() == previous["snapshot"]
                )
            finally:
                connection.close()
        finally:
            database.close()

    def capture(self, community):
        captures, roots = [], []
        for unit in self.units:
            try:
                captured = self.producer.capture(
                    unit.source,
                    locator=unit.locator,
                    source_type=unit.source_type,
                    syntax=unit.syntax,
                )
            except ValueError as exc:
                raise ValueError(f"binding unit {unit.locator}: {exc}") from exc
            captures.append(captured)
            roots.extend(
                BindingRoot(captured.ir.units[0].id, region.id)
                for region in captured.ir.regions
                if region.slot.value in ("root", "function-creation")
            )
        self.snapshot = BindingSnapshot.create(community, captures, roots)
        for record in self.coverage:
            if record["status"] == "selected":
                record["status"] = "captured"
        self.manifest.update(
            snapshot=self.snapshot.digest(),
            build_fingerprint=self.fingerprint,
            roots=[{"unit": r.unit, "region": r.region} for r in self.snapshot.roots],
        )

    def seal(self, db):
        path = self.manifest_path(db)
        # A manifest is the completion seal, not a promotion protocol or trust anchor.
        temporary = path.with_name("." + path.name + "." + uuid4().hex + ".tmp")
        with temporary.open("x") as stream:
            json.dump(self.manifest, stream, indent=2)
            stream.flush()
            os.fsync(stream.fileno())
        os.link(temporary, path)
        temporary.unlink()


class BindingWriteSession:
    """Own a fresh DB; never call legacy delete-before-rename promotion.

    GraphWriter's general writes and the reviewed extension each use their
    existing transactions. A closed DB is linked to a NEW name only after both
    succeed; an error never exposes the destination or writes a completion seal.
    """

    def __init__(self, final, stage):
        self.final, self.stage = final, stage
        self.temp = final.with_name("." + final.name + "." + uuid4().hex + ".building")
        self.db = self.conn = self.lock = None

    def __enter__(self):
        self.final.parent.mkdir(parents=True, exist_ok=True)
        self.lock = self.final.with_name("." + self.final.name + ".lock").open("a")
        fcntl.flock(self.lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        try:
            if self.final.exists() or self.stage.manifest_path(self.final).exists():
                raise ValueError(
                    "binding build requires a new destination; baseline preserved"
                )
            self.db = kuzu.Database(
                str(self.temp), buffer_pool_size=128 * 1024 * 1024, max_num_threads=2
            )
            self.conn = kuzu.Connection(self.db)
            initialize_schema(self.conn)
            self.writer = GraphWriter(self.conn)
            return self.writer
        except BaseException:
            self.close()
            raise

    def __exit__(self, kind, value, trace):
        try:
            if kind is None:
                self.writer.commit()
                if self.writer.get_stats()["write_errors"]:
                    raise ValueError(
                        "critical general graph writes failed; binding build not sealed"
                    )
                write_binding_context(self.conn, self.stage.snapshot)
                self.conn.close()
                self.conn = None
                self.db.close()
                self.db = None
                # Kuzu 0.11 is a single file. link is atomic and refuses an existing name.
                os.link(self.temp, self.final)
                self.temp.unlink()
        finally:
            self.close()
        return False

    def close(self):
        try:
            if self.conn is not None:
                self.conn.close()
                self.conn = None
        finally:
            try:
                if self.db is not None:
                    self.db.close()
                    self.db = None
            finally:
                if self.lock is not None:
                    self.lock.close()
                    self.lock = None
