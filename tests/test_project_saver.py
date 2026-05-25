import json
import threading
import time
from pathlib import Path

from jfterm.models import Workspace
from jfterm.persistence import load_projects
from jfterm.project_saver import ProjectSaver


def test_constructs_without_main_loop():
    """ProjectSaver must be safe to build with no GLib main loop running."""
    ws = Workspace()
    saver = ProjectSaver(ws, Path("/tmp/jfterm-saver-construct.json"))
    saver.stop(timeout=2.0)


def test_schedule_writes_to_disk(tmp_path: Path):
    ws = Workspace()
    ws.add_project(name="A", directory="/tmp/a")
    path = tmp_path / "projects.json"

    saver = ProjectSaver(ws, path, debounce=0.05)
    try:
        saver.schedule()
        assert saver.flush(timeout=2.0)
        assert path.exists()
        ws2 = Workspace()
        load_projects(ws2, path)
        assert [p.name for p in ws2.projects] == ["A"]
    finally:
        saver.stop(timeout=2.0)


def test_rapid_schedules_coalesce(tmp_path: Path):
    """Many rapid schedule() calls should result in far fewer writes."""
    ws = Workspace()
    ws.add_project(name="A", directory="/tmp/a")
    path = tmp_path / "projects.json"

    write_count = 0
    write_lock = threading.Lock()
    real_write = __import__("jfterm.persistence", fromlist=["write_payload"]).write_payload

    def counting_write(payload: dict, p: Path) -> None:
        nonlocal write_count
        with write_lock:
            write_count += 1
        real_write(payload, p)

    saver = ProjectSaver(ws, path, debounce=0.2, write_fn=counting_write)
    try:
        # Mutate + schedule 50 times in quick succession.
        for i in range(50):
            ws.projects[0].name = f"A{i}"
            saver.schedule()
        assert saver.flush(timeout=5.0)
    finally:
        saver.stop(timeout=2.0)

    # Most of those schedules must have been coalesced. Allow a tiny upper
    # bound to absorb any scheduling jitter on slow CI hosts.
    assert write_count <= 3, f"expected coalescing, got {write_count} writes"

    # Final on-disk content reflects the LAST snapshot.
    data = json.loads(path.read_text())
    assert data["projects"][0]["name"] == "A49"


def test_flush_waits_for_in_flight_write(tmp_path: Path):
    """flush() must block until a slow write completes."""
    ws = Workspace()
    ws.add_project(name="A", directory="/tmp/a")
    path = tmp_path / "projects.json"

    started = threading.Event()
    release = threading.Event()

    def slow_write(payload: dict, p: Path) -> None:
        started.set()
        release.wait(timeout=5.0)
        # Now actually write so we can verify content below.
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(json.dumps(payload))

    saver = ProjectSaver(ws, path, debounce=0.0, write_fn=slow_write)
    try:
        saver.schedule()
        # Wait until the worker is inside the write.
        assert started.wait(timeout=2.0)

        # flush() in another thread must NOT return until we release.
        done = threading.Event()

        def _flush():
            saver.flush(timeout=5.0)
            done.set()

        t = threading.Thread(target=_flush, daemon=True)
        t.start()
        # Give the flush thread a chance to wait.
        time.sleep(0.1)
        assert not done.is_set(), "flush() returned before write finished"

        release.set()
        assert done.wait(timeout=2.0)
        t.join(timeout=1.0)
        assert path.exists()
    finally:
        release.set()
        saver.stop(timeout=2.0)


def test_payload_snapshotted_on_calling_thread(tmp_path: Path):
    """The payload is built on the GTK/calling thread, not the worker.

    We verify this by mutating ``ws`` *after* schedule() returns; the on-disk
    content must reflect the pre-mutation snapshot.
    """
    ws = Workspace()
    ws.add_project(name="ORIGINAL", directory="/tmp/a")
    path = tmp_path / "projects.json"

    gate = threading.Event()

    def gated_write(payload: dict, p: Path) -> None:
        gate.wait(timeout=5.0)
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(json.dumps(payload))

    saver = ProjectSaver(ws, path, debounce=0.0, write_fn=gated_write)
    try:
        saver.schedule()
        # Mutate workspace after scheduling but before write proceeds.
        # If snapshot happened in the worker, it could observe this mutation.
        ws.projects[0].name = "MUTATED"
        # Give worker time to enter write; then release.
        time.sleep(0.1)
        gate.set()
        assert saver.flush(timeout=2.0)
        data = json.loads(path.read_text())
        assert data["projects"][0]["name"] == "ORIGINAL"
    finally:
        gate.set()
        saver.stop(timeout=2.0)


def test_flush_with_no_pending_returns_immediately():
    ws = Workspace()
    saver = ProjectSaver(ws, Path("/tmp/jfterm-saver-noop.json"))
    try:
        assert saver.flush(timeout=1.0)
    finally:
        saver.stop(timeout=2.0)
