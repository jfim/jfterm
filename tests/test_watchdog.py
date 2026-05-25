"""Unit tests for the main-loop watchdog.

We drive :func:`jfterm.watchdog._monitor_loop` directly using a fake
clock and a stoppable event so we never touch a real GLib main loop or
real wall-clock sleeps. This keeps the tests fast and lets us assert
the cooldown behaviour deterministically.
"""

from __future__ import annotations

import io
import os
import threading
from collections.abc import Callable
from typing import IO

from jfterm import watchdog


class _FakeClock:
    """Monotonic clock that advances only when the test calls ``advance``."""

    def __init__(self) -> None:
        self.t = 0.0
        # Reading "now" or "last_tick" — see usage below.

    def now(self) -> float:
        return self.t

    def advance(self, seconds: float) -> None:
        self.t += seconds


def _drive(
    *,
    threshold_s: float,
    tick_interval_s: float,
    last_tick_getter: Callable[[], float],
    clock: _FakeClock,
    log: IO[str],
    dump: Callable[[IO[str]], None],
    iterations: int,
) -> None:
    """Run ``_monitor_loop`` for exactly ``iterations`` poll cycles.

    The fake ``sleep`` is a no-op; the test advances the clock between
    iterations via the stop_event side-channel. To bound iterations we
    set the event after a counter trips.
    """
    stop = threading.Event()
    counter = {"n": 0}

    def fake_sleep(_dt: float) -> None:
        counter["n"] += 1
        if counter["n"] >= iterations:
            stop.set()

    watchdog._monitor_loop(
        threshold_s=threshold_s,
        tick_interval_s=tick_interval_s,
        get_last_tick=last_tick_getter,
        log_file=log,
        now=clock.now,
        sleep=fake_sleep,
        stop_event=stop,
        dump_traceback=dump,
    )


def test_dumps_once_when_stalled_and_recovers():
    """A single stall produces one dump + one recovery line."""
    clock = _FakeClock()
    last_tick = [0.0]
    log = io.StringIO()
    dumps: list[str] = []

    def dump(file: IO[str]) -> None:
        file.write("<traceback>\n")
        dumps.append("dump")

    # We need to advance the clock between poll cycles. Wrap the getter
    # so each read advances time by one tick_interval first; this models
    # the watchdog noticing time passing while the main loop is stuck.
    state = {"step": 0}

    def get_last_tick() -> float:
        state["step"] += 1
        # Step 1..N: main loop is frozen, time keeps moving.
        if state["step"] <= 5:
            clock.advance(0.030)  # 30ms per poll; threshold is 100ms
        elif state["step"] == 6:
            # Loop recovers: bump last_tick to "now".
            last_tick[0] = clock.now()
        else:
            # Keep last_tick fresh; keep moving time slightly.
            last_tick[0] = clock.now()
            clock.advance(0.005)
        return last_tick[0]

    _drive(
        threshold_s=0.100,
        tick_interval_s=0.050,
        last_tick_getter=get_last_tick,
        clock=clock,
        log=log,
        dump=dump,
        iterations=10,
    )

    output = log.getvalue()
    assert dumps == ["dump"], f"expected exactly one dump, got {dumps}"
    assert "stalled for" in output
    assert "<traceback>" in output
    assert "recovered after" in output


def test_no_dump_when_loop_is_healthy():
    """If last_tick keeps up with now, nothing should be logged."""
    clock = _FakeClock()
    last_tick = [0.0]
    log = io.StringIO()
    dumps: list[str] = []

    def dump(file: IO[str]) -> None:
        dumps.append("dump")

    def get_last_tick() -> float:
        # Each iteration: advance time a tiny bit AND bump last_tick.
        clock.advance(0.010)
        last_tick[0] = clock.now()
        return last_tick[0]

    _drive(
        threshold_s=0.100,
        tick_interval_s=0.050,
        last_tick_getter=get_last_tick,
        clock=clock,
        log=log,
        dump=dump,
        iterations=20,
    )

    assert dumps == []
    assert log.getvalue() == ""


def test_cooldown_suppresses_repeat_dumps_during_same_stall():
    """A multi-second freeze must produce exactly one dump, not one per poll."""
    clock = _FakeClock()
    last_tick = [0.0]
    log = io.StringIO()
    dumps: list[str] = []

    def dump(file: IO[str]) -> None:
        dumps.append("dump")

    def get_last_tick() -> float:
        # Time advances every poll; last_tick never updates → permanent stall.
        clock.advance(0.060)
        return last_tick[0]

    _drive(
        threshold_s=0.100,
        tick_interval_s=0.050,
        last_tick_getter=get_last_tick,
        clock=clock,
        log=log,
        dump=dump,
        iterations=30,
    )

    assert dumps == ["dump"], f"expected one dump despite long stall, got {dumps}"
    # Recovery should NOT have been written (the loop never came back).
    assert "recovered after" not in log.getvalue()


def test_install_watchdog_disabled_without_env(monkeypatch):
    monkeypatch.delenv(watchdog.ENV_VAR, raising=False)
    assert watchdog.install_watchdog() is False


def test_install_watchdog_disabled_for_invalid_env(monkeypatch):
    monkeypatch.setenv(watchdog.ENV_VAR, "not-a-number")
    assert watchdog.install_watchdog() is False


def test_install_watchdog_disabled_for_zero(monkeypatch):
    monkeypatch.setenv(watchdog.ENV_VAR, "0")
    assert watchdog.install_watchdog() is False


def test_log_path_honours_xdg_cache_home(monkeypatch, tmp_path):
    monkeypatch.setenv("XDG_CACHE_HOME", str(tmp_path))
    expected = os.path.join(str(tmp_path), "jfterm", "watchdog.log")
    assert watchdog._log_path() == expected
