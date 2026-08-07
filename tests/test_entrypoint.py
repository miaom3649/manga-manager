import os

from hlibrary import __version__
from hlibrary.__main__ import configure_linux_window_positioning, main


def test_version_smoke_path_does_not_start_gui() -> None:
    assert __version__ == "1.0.0"
    assert main(["--version"]) == 0


def test_wayland_development_run_uses_xwayland_for_window_positioning(monkeypatch) -> None:
    monkeypatch.setattr("sys.platform", "linux")
    monkeypatch.setenv("XDG_SESSION_TYPE", "wayland")
    monkeypatch.setenv("DISPLAY", ":0")
    monkeypatch.delenv("QT_QPA_PLATFORM", raising=False)
    monkeypatch.setattr("hlibrary.__main__.find_library", lambda name: "libxcb-cursor.so.0")

    configure_linux_window_positioning()

    assert os.environ["QT_QPA_PLATFORM"] == "xcb"


def test_wayland_keeps_working_when_xcb_cursor_is_missing(monkeypatch) -> None:
    monkeypatch.setattr("sys.platform", "linux")
    monkeypatch.setenv("XDG_SESSION_TYPE", "wayland")
    monkeypatch.setenv("DISPLAY", ":0")
    monkeypatch.delenv("QT_QPA_PLATFORM", raising=False)
    monkeypatch.setattr("hlibrary.__main__.find_library", lambda name: None)

    configure_linux_window_positioning()

    assert "QT_QPA_PLATFORM" not in os.environ
