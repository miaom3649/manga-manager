from __future__ import annotations

import sys
import threading
from pathlib import Path

import uvicorn

from hmanga.api import create_api
from hmanga.catalog import CatalogService
from hmanga.library import LibraryService
from hmanga.media import MediaService
from hmanga.pairing import PairingService


class ApiServer:
    def __init__(
        self,
        host: str,
        port: int,
        web_root: Path | None = None,
        library: LibraryService | None = None,
        catalog: CatalogService | None = None,
        media: MediaService | None = None,
        pairing: PairingService | None = None,
    ) -> None:
        options: dict[str, object] = {
            "host": host,
            "port": port,
            "log_level": "info",
            "access_log": False,
            # Desktop exit owns the server lifecycle. Close browser requests
            # immediately instead of waiting for clients to leave.
            # Zero always triggers Uvicorn's timeout branch after its mandatory
            # 100 ms connection-close pause, even when no request is running.
            "timeout_graceful_shutdown": 0.5,
        }
        # Disable console logging in windowed builds; keep it in diagnostic builds.
        if sys.stdout is None or sys.stderr is None:
            options["log_config"] = None
        config = uvicorn.Config(create_api(web_root, library, catalog, media, pairing), **options)
        self._server = uvicorn.Server(config)
        self._thread: threading.Thread | None = None
        self._lifecycle_lock = threading.Lock()

    def start(self) -> None:
        with self._lifecycle_lock:
            if self._thread and self._thread.is_alive():
                return
            self._server.should_exit = False
            self._server.force_exit = False
            self._thread = threading.Thread(target=self._server.run, name="hmanga-api", daemon=True)
            self._thread.start()

    def stop(self, timeout: float = 2.0) -> None:
        with self._lifecycle_lock:
            thread = self._thread
            if thread is None:
                return
            self._server.should_exit = True
            thread.join(timeout=timeout)
            if thread.is_alive():
                self._server.force_exit = True
                # A restart must never launch the replacement while the old
                # API thread still owns the port. Uvicorn exits after force_exit.
                thread.join()
            self._thread = None
