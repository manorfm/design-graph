"""Explicit read-only source syntax query; deliberately no MCP/assembly imports."""

import json
import sys
from dataclasses import asdict

import kuzu

from design_graph.model.graph.source_syntax_context import read_project_source_syntax


def source_syntax_query_main(args):
    try:
        if args.db_path is None:
            raise ValueError("source-candidate requires explicit --db")
        database = kuzu.Database(
            str(args.db_path),
            read_only=True,
            buffer_pool_size=128 * 1024 * 1024,
            max_num_threads=2,
        )
        try:
            connection = kuzu.Connection(database)
            try:
                result = read_project_source_syntax(
                    connection,
                    args.snapshot,
                    input_artifact=args.input_artifact,
                    units=args.inventory_units,
                    unit=args.unit,
                    use=args.use,
                    expected_sha256=args.expected_sha256,
                )
                print(
                    json.dumps(
                        asdict(result) if result is not None else {"status": "unknown"},
                        sort_keys=True,
                    )
                )
            finally:
                connection.close()
        finally:
            database.close()
    except (ValueError, RuntimeError, OSError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        raise SystemExit(1) from exc
