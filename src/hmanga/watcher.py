from __future__ import annotations

import threading
from collections.abc import Callable
from pathlib import Path

from watchdog.events import FileSystemEvent, FileSystemEventHandler
from watchdog.observers import Observer

from hmanga.library import ILLUSTRATION_DIRECTORY


class _DebouncedHandler(FileSystemEventHandler):
    def __init__(self, callback: Callable[[], None], delay: float) -> None:
        self.callback = callback
        self.delay = delay
        self._lock = threading.Lock()
        self._timer: threading.Timer | None = None

    def on_any_event(self, event: FileSystemEvent) -> None:
        # Reading a file produces opened/closed events on Linux. The scanner itself
        # reads every archive, so reacting to those events creates an endless scan
        # loop. Only changes that can alter the library should schedule a scan.
        if event.event_type not in {"created", "modified", "deleted", "moved"}:
            return
        if event.is_directory and event.event_type not in {"created", "deleted", "moved"}:
            return
        with self._lock:
            if self._timer is not None:
                self._timer.cancel()
            self._timer = threading.Timer(self.delay, self.callback)
            self._timer.daemon = True
            self._timer.start()

    def cancel(self) -> None:
        with self._lock:
            if self._timer is not None:
                self._timer.cancel()
                self._timer = None


class LibraryWatcher:
    def __init__(self, callback: Callable[[], None], delay: float = 1.0) -> None:
        self._handler = _DebouncedHandler(callback, delay)
        self._observer: Observer | None = None

    def start(self, root: Path) -> None:
        self.stop()
        observer = Observer()
        observer.schedule(self._handler, str(root), recursive=False)
        illustration_root = root / ILLUSTRATION_DIRECTORY
        if illustration_root.is_dir():
            observer.schedule(self._handler, str(illustration_root), recursive=False)
        observer.start()
        self._observer = observer

    def stop(self) -> None:
        self._handler.cancel()
        if self._observer is not None:
            self._observer.stop()
            # Watchdog threads are non-daemon threads. Dropping the reference
            # after a timed join can leave Python alive after every window and
            # the API server have already closed, so wait for a real shutdown.
            self._observer.join()
            self._observer = None
