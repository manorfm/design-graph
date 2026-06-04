import sys
import pytest
from pathlib import Path

# Ensure project root is on the path when running without pip install
sys.path.insert(0, str(Path(__file__).parent.parent))

import mcp_server


@pytest.fixture(autouse=True)
def reset_active_prototype():
    """Isolate ACTIVE_PROTOTYPE state between tests."""
    original = mcp_server.ACTIVE_PROTOTYPE
    yield
    mcp_server.ACTIVE_PROTOTYPE = original


def make_conns(*names):
    """Create fake (name, conn) pairs using plain strings as mock connections."""
    return [(name, f"conn:{name}") for name in names]
