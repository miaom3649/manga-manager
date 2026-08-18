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
from hmanga.i18n import configure_localization, install_localization
from hmanga.library import LibraryService
from hmanga.media import MediaService
from hmanga.migration import MigrationService
from hmanga.notifications import NotificationService
from hmanga.pairing import PairingService
from hmanga.server import ApiServer
from hmanga.single_instance import close_instance_server, create_instance_server
from hmanga.upload import UploadService

RESTART_EXIT_CODE = 75


def run() -> int:
    settings = Settings.load()
    settings.ensure_directories()

    app = QApplication(sys.argv)
    app.setApplicationName(APP_NAME)
    app.setApplicationDisplayName(APP_NAME)
    app.setOrganizationName(APP_ID)
    app.setQuitOnLastWindowClosed(False)
    instance_server = create_instance_server(app)
    if instance_server is None:
        return 0

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
    configure_localization(database, settings.data_dir / "locales")

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

    dialog_centering = install_dialog_centering(app)
    localization = install_localization(app)
    apply_theme(app, appearance.theme())
    app.styleHints().colorSchemeChanged.connect(
        lambda _scheme: apply_theme(app, "system") if appearance.theme() == "system" else None
    )

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
    app._localization = localization  # type: ignore[attr-defined]
    app._instance_server = instance_server  # type: ignore[attr-defined]
    shutdown_started = False
    cleanup_finished = False

    def show_from_secondary_instance() -> None:
        while instance_server.hasPendingConnections():
            connection = instance_server.nextPendingConnection()
            if connection is not None:
                connection.readAll()
                connection.disconnectFromServer()
        window.show_main_window()

    instance_server.newConnection.connect(show_from_secondary_instance)
    if instance_server.hasPendingConnections():
        QTimer.singleShot(0, show_from_secondary_instance)

    def cleanup() -> None:
        nonlocal cleanup_finished
        if cleanup_finished:
            return
        cleanup_finished = True
        controller.stop()
        uploads.cancel_all()
        server.stop()
        database.close()
        tray.hide()
        close_instance_server(instance_server)

    def shutdown(restart: bool = False) -> None:
        nonlocal shutdown_started
        if shutdown_started:
            return
        shutdown_started = True
        cleanup()
        # Do not tear down Qt from inside the action signal that initiated the
        # shutdown. Returning to the event loop first avoids a Linux/Qt case in
        # which all services stop but QApplication never leaves app.exec().
        exit_code = RESTART_EXIT_CODE if restart else 0
        QTimer.singleShot(0, lambda: app.exit(exit_code))

    window.request_exit.connect(lambda: shutdown(False))
    window.request_restart.connect(lambda: shutdown(True))
    app.aboutToQuit.connect(cleanup)
    window.show()
    if library.library_root() is None:
        QTimer.singleShot(0, window.choose_root)
    else:
        controller.start()
    backup_timer = QTimer(app)
    backup_timer.setInterval(60_000)
    backup_timer.timeout.connect(backups.scheduled_if_due)
    backup_timer.start()
    try:
        return app.exec()
    finally:
        # Covers Ctrl+C, session shutdown and any future exit path that does not
        # originate from the tray/window actions.
        cleanup()
