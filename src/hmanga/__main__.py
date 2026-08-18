import argparse
import os
import sys
from ctypes.util import find_library

from hmanga import __version__
from hmanga.i18n import tr


def configure_linux_window_positioning() -> None:
    """Use XWayland when available because Wayland forbids client window placement."""
    if (
        sys.platform.startswith("linux")
        and os.environ.get("XDG_SESSION_TYPE", "").casefold() == "wayland"
        and os.environ.get("DISPLAY")
        and "QT_QPA_PLATFORM" not in os.environ
        and find_library("xcb-cursor") is not None
    ):
        os.environ["QT_QPA_PLATFORM"] = "xcb"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="hmanga", description=f"HManガ {__version__}")
    parser.add_argument("--version", action="store_true", help=tr("confirm.smoke_test"))
    args = parser.parse_args(argv)
    if args.version:
        return 0

    configure_linux_window_positioning()
    # Delay importing Qt so Windows CI can smoke-test the build without a display.
    from hmanga.app import RESTART_EXIT_CODE, run

    exit_code = run()
    if exit_code == RESTART_EXIT_CODE:
        # Replace the fully stopped process instead of spawning the replacement
        # while Qt, the instance socket, and the API port are still shutting down.
        if getattr(sys, "frozen", False):
            arguments = [sys.executable, *sys.argv[1:]]
        else:
            arguments = [sys.executable, sys.argv[0], *sys.argv[1:]]
        os.execv(sys.executable, arguments)
    # run() returns only after the database, watcher, scanner, uploads, local
    # socket, tray, and API server have completed their orderly shutdown. Some
    # Qt/watchdog combinations still keep an internal non-daemon thread alive
    # during Python's interpreter teardown. Bypass that unbounded final wait so
    # the tray Exit action reliably returns control to the launching terminal.
    for stream in (sys.stdout, sys.stderr):
        if stream is not None:
            try:
                stream.flush()
            except (OSError, ValueError):
                pass
    os._exit(exit_code)


if __name__ == "__main__":
    raise SystemExit(main())
