"""GLib main-loop stall watchdog.

Detects intermittent UI freezes (window can't be dragged, terminal stops
repainting) by checking that the GTK main loop continues processing
timeouts at a steady rate. When the gap exceeds a threshold, dump a
traceback of every Python thread — including the main thread mid-stall —
to a log file so the culprit can be identified after the fact.

Enable by setting ``JFTERM_WATCHDOG_MS`` to a positive integer (the
stall threshold in milliseconds) before launching JFTerm. Unset, zero,
or invalid values disable the watchdog entirely (zero runtime cost).

Logs land at ``$XDG_CACHE_HOME/jfterm/watchdog.log`` (defaults to
``~/.cache/jfterm/watchdog.log``). Append mode — old dumps are retained
across runs.
"""

from __future__ import annotations

import faulthandler
import os
import threading
import time
from collections.abc import Callable
from typing import IO, Any

ENV_VAR = "JFTERM_WATCHDOG_MS"


def _log_path() -> str:
    base = os.environ.get("XDG_CACHE_HOME") or os.path.expanduser("~/.cache")
    return os.path.join(base, "jfterm", "watchdog.log")


def _parse_threshold(raw: str | None) -> int | None:
    if not raw:
        return None
    try:
        value = int(raw)
    except ValueError:
        return None
    if value <= 0:
        return None
    return value


def _monitor_loop(
    *,
    threshold_s: float,
    tick_interval_s: float,
    get_last_tick: Callable[[], float],
    log_file: IO[str],
    now: Callable[[], float] = time.monotonic,
    sleep: Callable[[float], None] = time.sleep,
    stop_event: threading.Event | None = None,
    dump_traceback: Callable[[IO[str]], None] = faulthandler.dump_traceback,
) -> None:
    """Watch ``get_last_tick`` and log a traceback whenever it stalls.

    Exposed at module level (rather than nested inside ``install_watchdog``)
    so the unit tests can drive it directly without a real GLib main loop.
    """
    reported = False
    stall_start = 0.0
    # Check at roughly half the tick interval so we notice stalls promptly
    # but don't busy-loop.
    poll_interval = max(tick_interval_s / 2.0, 0.005)
    while stop_event is None or not stop_event.is_set():
        sleep(poll_interval)
        last = get_last_tick()
        current = now()
        lag = current - last
        if lag >= threshold_s:
            if not reported:
                stall_start = last
                _write_stall(log_file, lag, dump_traceback)
                reported = True
            # else: still stalled; wait for recovery.
        elif reported:
            # The heartbeat advanced again — the loop recovered.
            recovery_lag = last - stall_start
            _write_recovery(log_file, recovery_lag)
            reported = False


def _write_stall(
    log_file: IO[str],
    lag_s: float,
    dump_traceback: Callable[[IO[str]], None],
) -> None:
    ts = time.strftime("%Y-%m-%d %H:%M:%S")
    log_file.write(f"\n=== {ts} GLib main loop stalled for {lag_s * 1000:.0f} ms ===\n")
    log_file.flush()
    try:
        dump_traceback(log_file)
    except Exception as exc:  # pragma: no cover — defensive
        log_file.write(f"(faulthandler.dump_traceback failed: {exc!r})\n")
    log_file.flush()


def _write_recovery(log_file: IO[str], stall_duration_s: float) -> None:
    ts = time.strftime("%Y-%m-%d %H:%M:%S")
    log_file.write(
        f"=== {ts} GLib main loop recovered after {stall_duration_s * 1000:.0f} ms ===\n"
    )
    log_file.flush()


def install_watchdog() -> bool:
    """Install the main-loop watchdog if ``JFTERM_WATCHDOG_MS`` is set.

    Returns True if the watchdog was installed, False otherwise (env var
    unset, invalid, or GLib unavailable). Safe to call exactly once at
    application startup, before the GTK main loop runs.
    """
    threshold_ms = _parse_threshold(os.environ.get(ENV_VAR))
    if threshold_ms is None:
        return False

    try:
        from gi.repository import GLib
    except (ImportError, ValueError):  # pragma: no cover — GTK absent
        return False

    threshold_s = threshold_ms / 1000.0
    # Tick often enough that we have multiple samples per threshold window,
    # capped at 50ms so we don't waste cycles on huge thresholds.
    tick_interval_ms = max(1, min(50, threshold_ms // 4 or 1))
    tick_interval_s = tick_interval_ms / 1000.0

    path = _log_path()
    os.makedirs(os.path.dirname(path), exist_ok=True)
    # Line-buffered so dumps reach disk even if we crash mid-stall.
    # Intentionally kept open for the lifetime of the process.
    log_file = open(path, "a", buffering=1, encoding="utf-8")  # noqa: SIM115
    log_file.write(
        f"\n=== watchdog armed: threshold={threshold_ms}ms tick={tick_interval_ms}ms"
        f" pid={os.getpid()} ===\n"
    )

    last_tick = time.monotonic()

    def _heartbeat() -> bool:
        nonlocal last_tick
        last_tick = time.monotonic()
        return True  # keep firing

    GLib.timeout_add(tick_interval_ms, _heartbeat)

    def _get_last_tick() -> float:
        return last_tick

    thread = threading.Thread(
        target=_monitor_loop,
        name="jfterm-watchdog",
        kwargs={
            "threshold_s": threshold_s,
            "tick_interval_s": tick_interval_s,
            "get_last_tick": _get_last_tick,
            "log_file": log_file,
        },
        daemon=True,
    )
    thread.start()
    return True


__all__ = ["ENV_VAR", "install_watchdog"]


# Keep ``Any`` imported for type checkers in case of future hooks.
_: Any = None
