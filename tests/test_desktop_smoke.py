# ruff: noqa: E402
from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication

from hlibrary.appearance import AppearanceService
from hlibrary.backup import BackupService
from hlibrary.cache import CacheService
from hlibrary.catalog import CatalogService
from hlibrary.controller import LibraryController
from hlibrary.database import Database
from hlibrary.desktop.main_window import MainWindow
from hlibrary.library import LibraryService
from hlibrary.media import MediaService
from hlibrary.migration import MigrationService
from hlibrary.notifications import NotificationService
from hlibrary.pairing import PairingService
from hlibrary.upload import UploadService


def test_full_desktop_window_constructs(tmp_path) -> None:
    app = QApplication.instance() or QApplication([])
    database = Database(tmp_path / "main.db")
    database.initialize("test")
    library = LibraryService(database)
    library.configure_root(tmp_path / "library")
    media = MediaService(library, tmp_path / "cache")
    controller = LibraryController(library)
    window = MainWindow(
        controller,
        library,
        CatalogService(database),
        media,
        UploadService(database, library, tmp_path / "cache"),
        PairingService(database),
        BackupService(database, library),
        MigrationService(database, library),
        CacheService(database, tmp_path / "cache"),
        NotificationService(database),
        AppearanceService(database),
    )
    window.show()
    app.processEvents()
    assert window.windowTitle().startswith("H库")
    assert window.navigation.count() == 3
    window.close()
    controller.stop()
