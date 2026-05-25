"""Background, debounced persistence of the project workspace.

Calling ``save_projects()`` synchronously from GTK signal handlers can stall
the main loop on slow / encrypted / networked filesystems. This module wraps
the sync save behind a debouncing scheduler that snapshots the workspace on
the calling (GTK) thread and performs JSON encoding plus disk I/O on a
background worker thread.

Usage::

    saver = ProjectSaver(ws, default_path())
    saver.schedule()  # debounced; coalesces with nearby schedule() calls
    ...
    saver.flush()     # blocks until any pending write completes
"""

from __future__ import annotations

import logging
import threading
import time
from collections.abc import Callable
from pathlib import Path

from jfterm.models import Workspace
from jfterm.persistence import build_payload, write_payload

logger = logging.getLogger(__name__)


class ProjectSaver:
    """Debounce + offload ``save_projects`` to a worker thread.

    Design notes:

    * One dedicated worker thread (``daemon=True``) consumes save requests.
    * The producer (GTK thread) builds the JSON payload synchronously — this
      reads the ``Workspace`` dataclass tree which is owned by the GTK thread
      and is not thread-safe. Then it hands the plain dict to the worker.
    * Multiple ``schedule()`` calls within ``debounce`` coalesce: only the
      most recent payload is written.
    * ``flush()`` blocks the caller until any pending or in-flight write has
      completed. It's safe to call from the GTK thread at shutdown.
    * Construction does not require a running GLib main loop, so tests can
      build one with just a ``Workspace``.
    """

    def __init__(
        self,
        ws: Workspace,
        path: Path,
        *,
        debounce: float = 0.25,
        build_payload_fn: Callable[[Workspace], dict] = build_payload,
        write_fn: Callable[[dict, Path], None] = write_payload,
    ) -> None:
        self._ws = ws
        self._path = path
        self._debounce = debounce
        self._build_payload = build_payload_fn
        self._write = write_fn

        # ``_lock`` guards every mutable field below.
        self._lock = threading.Lock()
        # ``_cond`` notifies the worker of new work or shutdown.
        self._cond = threading.Condition(self._lock)
        # ``_idle`` is set whenever there is no pending and no in-flight write.
        self._idle = threading.Event()
        self._idle.set()

        # The pending payload to write, plus the (monotonic) time it was queued.
        self._pending: dict | None = None
        self._pending_at: float = 0.0
        self._shutdown = False

        self._thread = threading.Thread(
            target=self._run,
            name="jfterm-project-saver",
            daemon=True,
        )
        self._thread.start()

    # ------------------------------------------------------------------ API

    def schedule(self) -> None:
        """Snapshot the workspace and queue a debounced write.

        Must be called from the GTK main thread (which owns ``ws``).
        """
        payload = self._build_payload(self._ws)
        with self._cond:
            if self._shutdown:
                return
            self._pending = payload
            self._pending_at = time.monotonic()
            self._idle.clear()
            self._cond.notify_all()

    def flush(self, timeout: float | None = None) -> bool:
        """Block until no write is pending or in-flight.

        Returns True if the saver became idle, False on timeout.
        """
        # Coalesce: writer immediately drains pending when it wakes.
        with self._cond:
            if self._pending is not None:
                # Force the worker to stop debouncing and write now.
                self._pending_at = 0.0
                self._cond.notify_all()
        return self._idle.wait(timeout)

    def stop(self, timeout: float | None = None) -> None:
        """Flush then terminate the worker thread."""
        self.flush(timeout)
        with self._cond:
            self._shutdown = True
            self._cond.notify_all()
        self._thread.join(timeout)

    # ----------------------------------------------------------------- impl

    def _run(self) -> None:
        while True:
            with self._cond:
                # Wait for work or shutdown.
                while not self._shutdown and self._pending is None:
                    self._cond.wait()
                if self._shutdown and self._pending is None:
                    return

                # Debounce: wait until the most-recent schedule() is at least
                # ``debounce`` seconds old. If another schedule() arrives in
                # the meantime it refreshes ``_pending_at`` and we keep
                # waiting.
                while not self._shutdown:
                    assert self._pending is not None
                    elapsed = time.monotonic() - self._pending_at
                    remaining = self._debounce - elapsed
                    if remaining <= 0:
                        break
                    self._cond.wait(timeout=remaining)

                # Take the snapshot.
                payload = self._pending
                self._pending = None

            # Write outside the lock so producers can keep scheduling.
            try:
                if payload is not None:
                    self._write(payload, self._path)
            except Exception:
                logger.exception("Failed to persist projects to %s", self._path)
            finally:
                with self._cond:
                    # Only mark idle if no new pending arrived during the write.
                    if self._pending is None:
                        self._idle.set()
