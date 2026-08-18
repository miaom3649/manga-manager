from __future__ import annotations

from concurrent.futures import Future, ThreadPoolExecutor
from pathlib import Path
from threading import Lock

from PySide6.QtCore import QObject, Signal

from hmanga.library import LibraryService, ScanResult
from hmanga.watcher import LibraryWatcher


class LibraryController(QObject):
    scan_started = Signal()
    scan_finished = Signal(object)
    scan_failed = Signal(str)

    def __init__(self, service: LibraryService) -> None:
        super().__init__()
        self.service = service
        self._executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="hmanga-scan")
        self._scan_lock = Lock()
        self._scanning = False
        self._rescan_requested = False
        self._current_future: Future[ScanResult] | None = None
        self._watcher = LibraryWatcher(self.request_scan)
        self._stopping = False

    def configure_root(self, root: Path) -> None:
        configured = self.service.configure_root(root)
        self._watcher.start(configured)
        self.request_scan()

    def start(self) -> None:
        root = self.service.library_root()
        if root is not None and root.is_dir():
            self._watcher.start(root)
            self.request_scan()

    def pause_watching(self) -> None:
        self._watcher.stop()

    def wait_until_idle(self) -> None:
        with self._scan_lock:
            future = self._current_future
        if future is not None:
            future.result()

    def request_scan(self) -> None:
        with self._scan_lock:
            if self._stopping:
                return
            if self._scanning:
                self._rescan_requested = True
                return
            self._scanning = True
        self.scan_started.emit()
        future = self._executor.submit(self.service.scan)
        self._current_future = future
        future.add_done_callback(self._scan_done)

    def _scan_done(self, future: Future[ScanResult]) -> None:
        try:
            self.scan_finished.emit(future.result())
        except Exception as exc:  # surfaced to UI; scanner remains alive for next event
            self.scan_failed.emit(str(exc))
        with self._scan_lock:
            self._scanning = False
            self._current_future = None
            rescan = self._rescan_requested and not self._stopping
            self._rescan_requested = False
        if rescan:
            self.request_scan()

    def stop(self) -> None:
        with self._scan_lock:
            if self._stopping:
                return
            self._stopping = True
            self._rescan_requested = False
        self._watcher.stop()
        self._executor.shutdown(wait=True, cancel_futures=True)
