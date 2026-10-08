"""
Ends an MCP server whose client is gone.

A stdio server normally ends when its client closes the pipe. When the
client dies but something else still holds that pipe open, end-of-file
never arrives, and the server would live on as an orphan holding its
graphs open. The operating system then hands the orphan to another parent
(launchd, init or a subreaper), so a parent other than the one the server
started under means its client is gone.

Only os.getppid() is asked — no signal sent, no file or network touched —
so the watch works on any machine the server runs on, however restricted.
Where orphans keep their old parent id (Windows), nothing is watched and
end-of-file stays the only way out.
"""

from __future__ import annotations

import os
import sys
import threading
import time
from typing import Callable

# Seconds between checks: an orphan lingers this long at most, for one cheap system call per check.
CHECK_INTERVAL = 5.0


def _end_server() -> None:
    """
    Leave at once. The server reads stdin in a worker thread that end-of-file
    will never release, so a graceful shutdown would wait on it forever; the
    graphs are open read-only and no client is listening.
    """
    sys.stderr.write("[design-graph] client is gone — ending this server\n")
    sys.stderr.flush()
    os._exit(0)


class ParentWatch:
    def __init__(
        self,
        interval: float = CHECK_INTERVAL,
        getppid: Callable[[], int] = os.getppid,
        sleep: Callable[[float], None] = time.sleep,
        on_orphaned: Callable[[], None] = _end_server,
        os_name: str = os.name,
    ) -> None:
        self._interval = interval
        self._getppid = getppid
        self._sleep = sleep
        self._on_orphaned = on_orphaned
        self._os_name = os_name
        self._parent = getppid()  # the client that started this server

    def orphaned(self) -> bool:
        """Whether the server now has a parent other than the client it started under."""
        return self._getppid() != self._parent

    def watch(self) -> None:
        """Check every interval; once orphaned, end the server."""
        while not self.orphaned():
            self._sleep(self._interval)
        self._on_orphaned()

    def start(self) -> threading.Thread | None:
        """Watch in a daemon thread, which never keeps the server alive; None where orphans keep their parent id."""
        if self._os_name != "posix":
            return None
        thread = threading.Thread(target=self.watch, name="design-graph-parent-watch", daemon=True)
        thread.start()
        return thread
