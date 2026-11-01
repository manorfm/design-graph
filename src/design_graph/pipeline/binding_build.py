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

from design_graph.capture.registry import binding_capture_for
from design_graph.model.graph.binding_context import (
    LOGICAL_VERSION,
    PHYSICAL_VERSION,
    BindingRoot,
    BindingSnapshot,
    _prepare_snapshot,
    _write_checked_context,
)
from design_graph.model.graph.schema import MODEL_VERSION, initialize_schema
from design_graph.model.graph.source_build_ownership import (
    VERSION,
    _load_source_build_facts,
    _prepare_receipt,
    _read_owned_facts,
    receipt_key,
    selected_domain,
)
from design_graph.model.graph.source_build_ownership import (
    _append_admitted_receipt as append_receipt,
)
from design_graph.model.graph.source_build_ownership import (
    _create_receipt as create_receipt,
)
from design_graph.model.graph.source_syntax_context import (
    LOGICAL_VERSION as SYNTAX_VERSION,
)
from design_graph.model.graph.source_syntax_context import (
    SourceSyntaxSnapshot,
    _inventory,
    _prepare_syntax,
    _PreparedWrite,
)
from design_graph.model.graph.writer import GraphWriter
from design_graph.model.source_syntax import SourceInventory
from design_graph.model.graph.binding_completion import read_manifest, verify_snapshot
from design_graph.model.graph.binding_general_completion import (
    general_receipt,
)

CONTRACT = "binding-build/4"


@dataclass(frozen=True)
class BindingBuildOptions:
    node: Path
    engine: Path
    fingerprint: str


class BindingStage:
    def __init__(self, document, options):
        self.producer = binding_capture_for(
            document, node=options.node, toolchain=options.engine,
            fingerprint=options.fingerprint,
        )
        self.units, self.coverage = self.producer.units, self.producer.coverage
        self.document = document
        raw = document.path.read_bytes()
        self.input_bytes = len(raw)
        if len(raw) > 64 * 1024 * 1024 or raw.decode('utf8') != document.text:
            raise ValueError('bounded exact UTF8 document required for source ownership')
        if not 0 < len(self.units) <= 16 or len(self.coverage) > 4096:
            raise ValueError('source ownership whole-unit/coverage budget exceeded')
        if raw.decode("utf8", errors="strict") != document.text:
            raise ValueError("source changed during capture")
        self.manifest = {
            "contract": CONTRACT,
            "logical": LOGICAL_VERSION,
            "physical": PHYSICAL_VERSION,
            "source_sha256": sha256(raw).hexdigest(),
            "source_path": str(document.path.resolve()),
            "engine": options.fingerprint,
            "syntax_producer": self.producer.syntax_fingerprint,
            "options": {
                "node": str(options.node.resolve()),
                "engine": str(options.engine.resolve()),
            },
            "adaptor": self.producer.adaptor,
            "model": MODEL_VERSION,
            "units": [u.metadata() for u in self.units],
            "coverage": self.coverage,
            "linkage": "independent-static-units; runtime multi-script linkage unknown",
        }
        self.fingerprint = sha256(
            json.dumps(self.manifest, sort_keys=True).encode()
        ).hexdigest()
        self.snapshot = None
        self.owner_events = []
        self.general_capture = None

    @staticmethod
    def manifest_path(db):
        return Path(str(db) + ".binding.json")

    def unchanged(self, db):
        path = self.manifest_path(db)
        if not path.exists():
            return False
        previous = read_manifest(path, self.manifest, self.fingerprint)
        database = kuzu.Database(
            str(db),
            read_only=True,
            buffer_pool_size=128 * 1024 * 1024,
            max_num_threads=2,
        )
        try:
            connection = kuzu.Connection(database)
            try:
                from design_graph.model.graph.reader import GraphReader
                facts = _load_source_build_facts(GraphReader(connection, Path(str(db) + '.state.json')))
                verify_snapshot(facts.lexical.snapshot, previous, self.manifest)
                owned = facts.value
                if owned.build_fingerprint != self.fingerprint:
                    raise ValueError('ownership build fingerprint differs')
                return (
                    True  # read_binding_context already verified the selected digest.
                )
            finally:
                connection.close()
        finally:
            database.close()

    def capture(self, community):
        captures, syntax_captures, roots = [], [], []
        for unit in self.units:
            try:
                events = []
                captured = self.producer.capture_source_syntax(
                    unit.source, owner_events=events,
                    locator=unit.locator,
                    source_type=unit.source_type,
                    syntax=unit.syntax,
                )
            except ValueError as exc:
                raise ValueError(f"binding unit {unit.locator}: {exc}") from exc
            self.owner_events.append(tuple(events))
            syntax_captures.append(captured)
            captured = captured.lexical
            captures.append(captured)
            roots.extend(
                BindingRoot(captured.ir.units[0].id, region.id)
                for region in captured.ir.regions
                if region.slot.value in ("root", "function-creation")
            )
        self.snapshot = BindingSnapshot(
            LOGICAL_VERSION, community, tuple(captures), tuple(roots)
        )
        self._checked = _prepare_snapshot(self.snapshot)
        self.syntax = SourceSyntaxSnapshot(
            SYNTAX_VERSION,
            SourceInventory(self.fingerprint, self.manifest['source_path'], tuple(c.source_syntax.unit for c in syntax_captures)),
            _inventory(syntax_captures), tuple(syntax_captures),
        )
        self._syntax_admitted = _prepare_syntax(self.syntax)
        for record in self.coverage:
            if record["status"] == "selected":
                record["status"] = "captured"
        self.manifest.update(
            snapshot=self._checked.revision,
            build_fingerprint=self.fingerprint,
            roots=[{"unit": r.unit, "region": r.region} for r in self.snapshot.roots],
        )

    async def capture_general(self, **kwargs):
        if self.snapshot is None:
            raise ValueError('native capture must precede general capture')
        self.general_capture = await self.producer.capture_general(
            self.syntax.captures, self.owner_events, **kwargs
        )
        return self.general_capture

    def field_witnesses(self, owners):
        from design_graph.model.source_owner import VERSION, SourceOwnerWitness
        if self.general_capture is None:
            raise ValueError('owned general capture required before receipt')
        from design_graph.model.serialization import canonical
        emitted = {(table, canonical([entity.name]), 'source_code'): entity.source_owner
                   for table, entities in (('Component', self.general_capture.components), ('Screen', self.general_capture.screens)) for entity in entities}
        result = []
        for owner in owners:
            if owner.table not in ('Component', 'Screen') or owner.field != 'source_code':
                continue
            witness = emitted.get((owner.table, owner.key, owner.field))
            if witness is None or witness.payload_sha256 != owner.raw_sha256:
                witness = SourceOwnerWitness(VERSION, owner.table, owner.key, owner.field, owner.raw_sha256, 'unsupported-derivation', () if witness is None else witness.origins)
            result.append(witness)
        return tuple(result)

    def publish_state(self, path, state, save):
        temporary = path.with_name('.' + path.name + '.' + uuid4().hex + '.tmp')
        try:
            save(temporary, state)
            os.link(temporary, path)  # refuse preexisting/racing sidecars
        finally:
            temporary.unlink(missing_ok=True)

    def seal(self, db):
        path = self.manifest_path(db)
        # Independently retained local-builder completion, not cryptographic
        # authenticity. No seal is published if DB/state publication failed.
        temporary = path.with_name("." + path.name + "." + uuid4().hex + ".tmp")
        try:
            with temporary.open("x") as stream:
                json.dump(self.manifest, stream, indent=2)
                stream.flush()
                os.fsync(stream.fileno())
            os.link(temporary, path)
        finally:
            temporary.unlink(missing_ok=True)


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
            if self.final.exists() or self.stage.manifest_path(self.final).exists() or Path(str(self.final) + '.state.json').exists():
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
                _write_checked_context(self.conn, self.stage._checked)
                # Separate public writes, no nested transaction: this entire DB
                # remains private until one atomic link. Existing qualified CLI
                # can read retained syntax without claiming general ownership.
                admitted = self.stage._syntax_admitted
                _write_checked_context(self.conn, _PreparedWrite(admitted.payload, admitted.snapshot.scope.snapshot))
                if sha256(self.stage.document.path.read_bytes()).hexdigest() != self.stage.manifest['source_sha256']:
                    raise ValueError('source changed during general capture')
                if selected_domain(self.conn, self.final.stem) != self.stage.domain:
                    raise ValueError('persisted Screen domain differs from capture session')
                self.stage.manifest["general"] = general_receipt(self.conn)
                receipt = create_receipt(self.conn, self.stage, self.stage._syntax_admitted)
                admitted_receipt = _prepare_receipt(receipt, self.stage._syntax_admitted)
                append_receipt(self.conn, admitted_receipt)
                self.stage.manifest['ownership'] = {'version': VERSION, 'snapshot': receipt_key(receipt.domain), 'sha256': admitted_receipt.digest}
                self.conn.close()
                self.conn = None
                self.db.close()
                self.db = None
                self.verify_private()
                # Kuzu 0.11 is a single file. link is atomic and refuses an existing name.
                os.link(self.temp, self.final)
                self.temp.unlink()
        finally:
            self.close()
        return False

    def verify_private(self):
        database = kuzu.Database(str(self.temp), read_only=True, buffer_pool_size=128 * 1024 * 1024, max_num_threads=2)
        try:
            connection = kuzu.Connection(database)
            try:
                from design_graph.model.graph.binding_context import _rollback, _rows
                _rows(connection, 'BEGIN TRANSACTION READ ONLY')
                try:
                    facts = _read_owned_facts(connection, selected_domain(connection, self.final.stem), self.stage.manifest['ownership'])
                    verify_snapshot(facts.lexical.snapshot, self.stage.manifest, self.stage.manifest)
                    if facts.value.syntax != self.stage.syntax:
                        raise ValueError('private qualified syntax differs')
                    _rows(connection, 'COMMIT')
                except Exception:
                    _rollback(connection)
                    raise
            finally:
                connection.close()
        finally:
            database.close()

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
