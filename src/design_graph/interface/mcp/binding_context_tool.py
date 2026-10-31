"""Graph-only qualified binding companion, separate from legacy owner context."""

from __future__ import annotations

import json
import re
from pathlib import Path

MAX_SELECTOR_CHARS = 4096
_REQUIRED = frozenset(("db", "snapshot", "unit", "region"))
_ALLOWED = _REQUIRED | {"expected_sha256"}

TOOL_DEFINITION = {
    "name": "get_binding_context",
    "description": (
        "Read qualified IR_ONLY binding context from an explicit absolute local Kuzu db. "
        "Supply snapshot, unit and region from the normal build's .binding.json manifest; "
        "never infer them from component/screen names. Returns the same JSON as "
        "design-query binding-context. Optional expected_sha256 must be independently "
        "trusted to anchor capture custody. No initialization/value certainty, source "
        "body, runtime linkage or legacy assembly certification is implied."
    ),
    "inputSchema": {
        "type": "object",
        "properties": {
            key: {"type": "string", "minLength": 1, "maxLength": MAX_SELECTOR_CHARS}
            for key in sorted(_REQUIRED)
        }
        | {
            "expected_sha256": {"type": "string", "pattern": "^[0-9a-f]{64}$"},
        },
        "required": sorted(_REQUIRED),
        "additionalProperties": False,
    },
}


def _validate_arguments(args: dict) -> Path:
    if not isinstance(args, dict) or not _REQUIRED <= args.keys() <= _ALLOWED:
        raise ValueError(
            "invalid binding context arguments: require db/snapshot/unit/region only, plus optional expected_sha256"
        )
    for key in _REQUIRED:
        value = args[key]
        if (
            not isinstance(value, str)
            or not 1 <= len(value) <= MAX_SELECTOR_CHARS
            or "\x00" in value
        ):
            raise ValueError(
                f"invalid binding context arguments: {key} must be a nonempty bounded string without NUL"
            )
    if "expected_sha256" in args:
        digest = args["expected_sha256"]
        if not isinstance(digest, str) or re.fullmatch(r"[0-9a-f]{64}", digest) is None:
            raise ValueError(
                "invalid binding context arguments: expected_sha256 must be 64 lowercase hex characters"
            )
    path = Path(args["db"])
    if not path.is_absolute():
        raise ValueError(
            "invalid binding context arguments: db must be an absolute local file path"
        )
    return path


def get_binding_context(args: dict) -> str:
    """Open only the supplied existing DB, admit the snapshot and close both handles."""
    path = _validate_arguments(args)
    if not path.is_file():
        raise ValueError("binding context database must be an existing file")

    import kuzu

    from design_graph.model.binding_public_context import read_project_binding_context

    database = kuzu.Database(
        str(path),
        read_only=True,
        buffer_pool_size=128 * 1024 * 1024,
        max_num_threads=2,
    )
    try:
        connection = kuzu.Connection(database)
        try:
            result = read_project_binding_context(
                connection,
                args["snapshot"],
                unit=args["unit"],
                region=args["region"],
                expected_sha256=args.get("expected_sha256"),
            )
            return json.dumps(result, sort_keys=True)
        finally:
            connection.close()
    finally:
        database.close()
