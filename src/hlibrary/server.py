from __future__ import annotations

import threading
from pathlib import Path

import uvicorn

from hlibrary.api import create_api
from hlibrary.catalog import CatalogService
from hlibrary.library import LibraryService
from hlibrary.media import MediaService
from hlibrary.pairing import PairingService
from hlibrary.upload import UploadService


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
        uploads: UploadService | None = None,
    ) -> None:
        config = uvicorn.Config(
            create_api(web_root, library, catalog, media, pairing, uploads),
            host=host,
            port=port,
            log_level="info",
            access_log=False,
        )
        self._server = uvicorn.Server(config)
        self._thread: threading.Thread | None = None

    def start(self) -> None:
        if self._thread and self._thread.is_alive():
            return
        self._thread = threading.Thread(target=self._server.run, name="hlibrary-api", daemon=True)
        self._thread.start()

    def stop(self, timeout: float = 5.0) -> None:
        self._server.should_exit = True
        if self._thread:
            self._thread.join(timeout=timeout)
