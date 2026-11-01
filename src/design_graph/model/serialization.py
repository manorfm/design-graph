"""Canonical JSON identity for model keys and retained completion contracts."""
import json


def canonical(value):
    """Keep JSON types distinct (not Python's True == 1)."""
    return json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False)
