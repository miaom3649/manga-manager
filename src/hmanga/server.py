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
            "timeout_graceful_shutdown": 0,
        }
        # 正式版无控制台时禁用控制台日志；调试版有控制台时保留日志。
        if sys.stdout is None or sys.stderr is None:
            options["log_config"] = None
        config = uvicorn.Config(create_api(web_root, library, catalog, media, pairing), **options)
        self._server = uvicorn.Server(config)
        self._thread: threading.Thread | None = None

    def start(self) -> None:
        if self._thread and self._thread.is_alive():
            return
        self._server.should_exit = False
        self._thread = threading.Thread(target=self._server.run, name="hmanga-api", daemon=True)
        self._thread.start()

    def stop(self, timeout: float = 2.0) -> None:
        self._server.should_exit = True
        if self._thread:
            self._thread.join(timeout=timeout)
            if self._thread.is_alive():
                self._server.force_exit = True
                self._thread.join(timeout=timeout)
