from __future__ import annotations

from collections.abc import Callable


class DoubleTapDetector:
    """Fires a callback when target_keyval is pressed twice within
    interval_ms with no intervening non-target press."""

    def __init__(
        self,
        *,
        target_keyval: int,
        interval_ms: int,
        callback: Callable[[], None],
    ) -> None:
        self._target = target_keyval
        self._interval = interval_ms
        self._callback = callback
        self._pending_time: int | None = None

    def on_press(self, keyval: int, time_ms: int) -> None:
        if keyval != self._target:
            self._pending_time = None
            return
        if self._pending_time is not None and time_ms - self._pending_time <= self._interval:
            self._pending_time = None
            self._callback()
            return
        self._pending_time = time_ms

    def reset(self) -> None:
        self._pending_time = None
