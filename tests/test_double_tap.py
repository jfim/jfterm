from jfterm.double_tap import DoubleTapDetector


def test_two_presses_within_window_fires():
    fired = []
    d = DoubleTapDetector(
        target_keyval=42, interval_ms=300, callback=lambda: fired.append(True)
    )
    d.on_press(42, 1000)
    d.on_press(42, 1100)
    assert fired == [True]


def test_two_presses_outside_window_does_not_fire():
    fired = []
    d = DoubleTapDetector(
        target_keyval=42, interval_ms=300, callback=lambda: fired.append(True)
    )
    d.on_press(42, 1000)
    d.on_press(42, 1500)
    assert fired == []


def test_intervening_other_key_resets():
    fired = []
    d = DoubleTapDetector(
        target_keyval=42, interval_ms=300, callback=lambda: fired.append(True)
    )
    d.on_press(42, 1000)
    d.on_press(99, 1050)
    d.on_press(42, 1100)
    assert fired == []


def test_third_press_does_not_re_fire():
    fired = []
    d = DoubleTapDetector(
        target_keyval=42, interval_ms=300, callback=lambda: fired.append(True)
    )
    d.on_press(42, 1000)
    d.on_press(42, 1100)  # fires
    d.on_press(42, 1200)  # this is now a fresh first press
    d.on_press(42, 1300)  # this completes a new pair
    assert fired == [True, True]


def test_reset_clears_pending():
    fired = []
    d = DoubleTapDetector(
        target_keyval=42, interval_ms=300, callback=lambda: fired.append(True)
    )
    d.on_press(42, 1000)
    d.reset()
    d.on_press(42, 1100)  # no pending -> becomes fresh first press
    assert fired == []


def test_non_target_first_press_does_nothing():
    fired = []
    d = DoubleTapDetector(
        target_keyval=42, interval_ms=300, callback=lambda: fired.append(True)
    )
    d.on_press(99, 1000)
    d.on_press(99, 1100)
    assert fired == []
