import pytest

gi = pytest.importorskip("gi")
gi.require_version("Gtk", "4.0")
from gi.repository import Gtk  # noqa: E402

# Headless GTK init — same pattern as test_window.py uses.
if not Gtk.init_check():
    pytest.skip("GTK cannot initialize", allow_module_level=True)

from jfterm.progress_bar import TabProgressBar  # noqa: E402


def test_initial_state_hidden():
    bar = TabProgressBar()
    assert bar.get_visible() is False


def test_state_1_makes_visible():
    bar = TabProgressBar()
    bar.set_progress(1, 50)
    assert bar.get_visible() is True
    assert bar.has_css_class("progress-normal")


def test_state_0_hides():
    bar = TabProgressBar()
    bar.set_progress(1, 50)
    bar.set_progress(0, 0)
    assert bar.get_visible() is False


def test_state_2_error_class():
    bar = TabProgressBar()
    bar.set_progress(2, 0)
    assert bar.has_css_class("progress-error")
    assert bar.get_visible() is True


def test_state_4_paused_class():
    bar = TabProgressBar()
    bar.set_progress(4, 30)
    assert bar.has_css_class("progress-paused")


def test_changing_state_swaps_css_class():
    bar = TabProgressBar()
    bar.set_progress(1, 50)
    bar.set_progress(2, 100)
    assert not bar.has_css_class("progress-normal")
    assert bar.has_css_class("progress-error")
