from __future__ import annotations

import sys
from importlib.resources import files
from pathlib import Path

from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QApplication

from hlibrary import __version__
from hlibrary.appearance import AppearanceService, apply_theme
from hlibrary.backup import BackupService
from hlibrary.cache import CacheService
from hlibrary.catalog import CatalogService
from hlibrary.config import APP_ID, APP_NAME, Settings
from hlibrary.controller import LibraryController
from hlibrary.database import Database
from hlibrary.desktop.main_window import MainWindow, create_tray
from hlibrary.library import LibraryService
from hlibrary.media import MediaService
from hlibrary.migration import MigrationService
from hlibrary.notifications import NotificationService
from hlibrary.pairing import PairingService
from hlibrary.server import ApiServer
from hlibrary.upload import UploadService


def run() -> int:
    settings = Settings.load()
    settings.ensure_directories()

    database = Database(settings.database_path)
    database.initialize(__version__)
    library = LibraryService(database)
    catalog = CatalogService(database)
    media = MediaService(library, settings.cache_dir)
    uploads = UploadService(database, library, settings.cache_dir)
    pairing = PairingService(database)
    backups = BackupService(database, library)
    migrations = MigrationService(database, library)
    cache = CacheService(database, settings.cache_dir)
    notifications = NotificationService(database)
    notifications.prune()
    appearance = AppearanceService(database)
    controller = LibraryController(library)

    web_root = Path(str(files("hlibrary").joinpath("web")))
    server = ApiServer(
        settings.api_host,
        settings.api_port,
        web_root,
        library,
        catalog,
        media,
        pairing,
        uploads,
    )
    server.start()

    app = QApplication(sys.argv)
    app.setApplicationName(APP_NAME)
    app.setApplicationDisplayName(APP_NAME)
    app.setOrganizationName(APP_ID)
    app.setQuitOnLastWindowClosed(False)
    apply_theme(app, appearance.theme())

    window = MainWindow(
        controller,
        library,
        catalog,
        media,
        uploads,
        pairing,
        backups,
        migrations,
        cache,
        notifications,
        appearance,
    )
    tray = create_tray(app, window)

    def shutdown() -> None:
        controller.stop()
        server.stop()
        database.close()
        tray.hide()
        app.quit()

    window.request_exit.connect(shutdown)
    app.aboutToQuit.connect(server.stop)
    window.show()
    if library.library_root() is None:
        QTimer.singleShot(0, window.choose_root)
    else:
        controller.start()
    backup_timer = QTimer(app)
    backup_timer.setInterval(60_000)
    backup_timer.timeout.connect(backups.scheduled_if_due)
    backup_timer.start()
    return app.exec()
