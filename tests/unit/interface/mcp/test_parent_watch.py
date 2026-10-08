"""An MCP server whose client is gone ends itself instead of living on as an orphan."""

from __future__ import annotations

import os
import signal
import subprocess
import sys
import textwrap
import time

import pytest

from design_graph.interface.mcp.parent_watch import ParentWatch


class _Clock:
    """Stands in for time.sleep: counts naps and lets the parent change after a few."""

    def __init__(self, parents: list[int]):
        self.parents = parents
        self.naps = 0

    def getppid(self) -> int:
        return self.parents[min(self.naps, len(self.parents) - 1)]

    def sleep(self, _: float) -> None:
        self.naps += 1


def test_the_parent_it_started_under_is_not_gone():
    clock = _Clock([100])
    assert ParentWatch(getppid=clock.getppid).orphaned() is False


def test_a_parent_other_than_the_one_it_started_under_means_it_was_orphaned():
    clock = _Clock([100, 1])
    watch = ParentWatch(getppid=clock.getppid)
    clock.naps = 1
    assert watch.orphaned() is True


def test_a_subreaper_taking_it_over_counts_as_orphaned_too():
    clock = _Clock([100, 4242])
    watch = ParentWatch(getppid=clock.getppid)
    clock.naps = 1
    assert watch.orphaned() is True


def test_watching_ends_the_server_once_when_the_parent_goes():
    clock = _Clock([100, 100, 100, 1])
    ended: list[str] = []
    watch = ParentWatch(getppid=clock.getppid, sleep=clock.sleep, on_orphaned=lambda: ended.append("bye"))
    watch.watch()
    assert ended == ["bye"] and clock.naps == 3


def test_nothing_is_watched_where_orphans_are_not_reparented():
    watch = ParentWatch(os_name="nt")
    assert watch.start() is None


def test_the_watch_runs_in_a_daemon_thread_that_never_holds_the_server_open():
    clock = _Clock([100])
    watch = ParentWatch(getppid=clock.getppid, sleep=lambda _: time.sleep(0.01), os_name="posix")
    thread = watch.start()
    assert thread is not None and thread.daemon and thread.is_alive()


@pytest.mark.skipif(os.name != "posix", reason="orphans are reparented only on POSIX")
def test_a_real_server_whose_client_is_killed_ends_itself(tmp_path):
    child = textwrap.dedent("""
        import time
        from design_graph.interface.mcp.parent_watch import ParentWatch
        ParentWatch(interval=0.05).start()
        time.sleep(60)
    """)
    client = textwrap.dedent(f"""
        import subprocess, sys, time
        server = subprocess.Popen([sys.executable, "-c", {child!r}], stdin=subprocess.PIPE)
        print(server.pid, flush=True)
        time.sleep(60)
    """)
    env = {**os.environ, "PYTHONPATH": os.pathsep.join(p for p in sys.path if p)}
    parent = subprocess.Popen([sys.executable, "-c", client], stdout=subprocess.PIPE, text=True, env=env)
    server_pid = int(parent.stdout.readline())
    time.sleep(0.5)  # the server is up and watching
    os.kill(parent.pid, signal.SIGKILL)
    parent.wait()
    deadline = time.monotonic() + 5
    while time.monotonic() < deadline and _alive(server_pid):
        time.sleep(0.05)
    alive = _alive(server_pid)
    if alive:
        os.kill(server_pid, signal.SIGKILL)
    assert not alive


def _alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    return True


def test_the_server_watches_its_client_before_serving(monkeypatch, tmp_path):
    from design_graph.interface.mcp import server

    events: list[str] = []

    class _Watch:
        def start(self):
            events.append("watch")

    async def _serve(_):
        events.append("serve")

    monkeypatch.setattr(server, "ParentWatch", _Watch)
    monkeypatch.setattr(server, "run_stdio", _serve)
    monkeypatch.setattr(sys, "argv", ["design-mcp"])
    monkeypatch.setenv("GRAPH_DIR", str(tmp_path))
    server.main()
    assert events == ["watch", "serve"]
