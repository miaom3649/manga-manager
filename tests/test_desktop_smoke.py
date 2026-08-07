# ruff: noqa: E402
from __future__ import annotations

import os
from io import BytesIO
from types import SimpleNamespace

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PIL import Image
from PySide6.QtWidgets import QApplication

from hlibrary.appearance import AppearanceService
from hlibrary.backup import BackupService
from hlibrary.cache import CacheService
from hlibrary.catalog import CatalogService
from hlibrary.controller import LibraryController
from hlibrary.database import Database
from hlibrary.desktop.main_window import MainWindow
from hlibrary.desktop.reader_dialog import ReaderDialog
from hlibrary.library import LibraryService
from hlibrary.media import MediaService
from hlibrary.migration import MigrationService
from hlibrary.notifications import NotificationService
from hlibrary.pairing import PairingService
from hlibrary.upload import UploadService


class FakeReader:
    def __init__(self) -> None:
        output = BytesIO()
        Image.new("RGB", (12, 18), "navy").save(output, "PNG")
        self.image = output.getvalue()
        self.saved: list[tuple[int, int]] = []

    def members(self, work) -> list[str]:
        return ["1.webp", "2.webp", "3.webp"]

    def progress(self, work):
        return None

    def preferred_mode(self) -> str:
        return "single"

    def set_preferred_mode(self, mode: str) -> None:
        pass

    def page(self, work, member: str) -> bytes:
        return self.image

    def save_progress(self, work, page_index: int, page_offset: int = 0) -> None:
        self.saved.append((page_index, page_offset))


def test_full_desktop_window_constructs(tmp_path) -> None:
    app = QApplication.instance() or QApplication([])
    database = Database(tmp_path / "main.db")
    database.initialize("test")
    library = LibraryService(database)
    root = library.configure_root(tmp_path / "library")
    Image.new("RGB", (12, 18), "navy").save(root / "插画" / "149672.png")
    library.scan()
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
    assert window.work_list.count() == 1
    assert window.work_list.item(0).text() == ""
    assert window.work_list.itemWidget(window.work_list.item(0)) is not None
    window.close()
    controller.stop()


def test_reader_saves_progress_only_when_done() -> None:
    app = QApplication.instance() or QApplication([])
    reader = FakeReader()
    work = SimpleNamespace(title="测试", file_name="1.zip", fingerprint="abc")
    dialog = ReaderDialog(work, reader)
    app.processEvents()

    dialog.go_page(2)
    assert reader.saved == []

    dialog.done(0)
    assert reader.saved == [(2, 0)]
