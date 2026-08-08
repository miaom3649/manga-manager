from __future__ import annotations

import sys
from importlib.resources import files
from pathlib import Path

from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QApplication

from hmanga import __version__
from hmanga.appearance import AppearanceService, apply_theme
from hmanga.backup import BackupService
from hmanga.cache import CacheService
from hmanga.catalog import CatalogService
from hmanga.config import APP_ID, APP_NAME, Settings
from hmanga.controller import LibraryController
from hmanga.database import Database
from hmanga.desktop.main_window import MainWindow, create_tray
from hmanga.desktop.windowing import install_dialog_centering
from hmanga.library import LibraryService
from hmanga.media import MediaService
from hmanga.migration import MigrationService
from hmanga.notifications import NotificationService
from hmanga.pairing import PairingService
from hmanga.server import ApiServer
from hmanga.upload import UploadService


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

    web_root = Path(str(files("hmanga").joinpath("web")))
    server = ApiServer(
        settings.api_host,
        settings.api_port,
        web_root,
        library,
        catalog,
        media,
        pairing,
    )
    server.start()

    app = QApplication(sys.argv)
    app.setApplicationName(APP_NAME)
    app.setApplicationDisplayName(APP_NAME)
    app.setOrganizationName(APP_ID)
    app.setQuitOnLastWindowClosed(False)
    dialog_centering = install_dialog_centering(app)
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
        server,
    )
    tray = create_tray(app, window)
    app._dialog_centering = dialog_centering  # type: ignore[attr-defined]

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
