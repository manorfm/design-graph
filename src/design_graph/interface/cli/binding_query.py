"""Normal design-query binding-context command; graph-only, fail-closed."""

from __future__ import annotations

import json
import sys

import kuzu

from design_graph.model.binding_public_context import project_binding_context
from design_graph.model.graph.binding_context import read_binding_context


def run_binding_query(args):
    if args.db_path is None:
        raise ValueError("binding-context requires explicit --db")
    database = kuzu.Database(
        str(args.db_path),
        read_only=True,
        buffer_pool_size=128 * 1024 * 1024,
        max_num_threads=2,
    )
    try:
        connection = kuzu.Connection(database)
        try:
            snapshot = read_binding_context(
                connection, args.snapshot, expected_sha256=args.expected_sha256
            )
            result = project_binding_context(
                snapshot, unit=args.unit, region=args.region
            )
            print(json.dumps(result, sort_keys=True))
        finally:
            connection.close()
    finally:
        database.close()


def binding_query_main(args):
    try:
        run_binding_query(args)
    except (ValueError, RuntimeError, OSError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        raise SystemExit(1) from exc
