# ruff: noqa: E402
from __future__ import annotations

import os
import zipfile
from io import BytesIO
from types import SimpleNamespace

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PIL import Image
from PySide6.QtCore import QPoint, QSize, Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QLabel, QWidget

from hmanga.appearance import AppearanceService
from hmanga.backup import BackupService
from hmanga.cache import CacheService
from hmanga.catalog import CatalogQuery, CatalogService
from hmanga.controller import LibraryController
from hmanga.database import Database, Notification
from hmanga.desktop.dialogs import WorkDetailDialog
from hmanga.desktop.main_window import (
    MainWindow,
    TagSummaryWidget,
    _consume_library_prompt_message_key,
)
from hmanga.desktop.reader_dialog import ReaderDialog
from hmanga.desktop.tag_widgets import AUTHOR_TAG_COLOR
from hmanga.desktop.windowing import FloatingCardDialog, ScreenCenteredDialog
from hmanga.library import LibraryService
from hmanga.media import MediaService
from hmanga.migration import MigrationService
from hmanga.notifications import NotificationService
from hmanga.pairing import PairingService
from hmanga.upload import UploadService


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


def test_library_prompt_uses_first_run_copy_only_once(tmp_path) -> None:
    database = Database(tmp_path / "main.db")
    database.initialize("test")
    catalog = CatalogService(database)

    assert (
        _consume_library_prompt_message_key(catalog)
        == "confirm.first_library_directory_setup"
    )
    assert _consume_library_prompt_message_key(catalog) == "confirm.library_directory_unset"


def test_floating_card_uses_owner_snapshot_without_native_transparency() -> None:
    _app = QApplication.instance() or QApplication([])
    parent = QWidget()
    dialog = FloatingCardDialog(parent)

    assert not dialog.testAttribute(Qt.WA_TranslucentBackground)
    assert dialog._backdrop_snapshot is not None
    assert not dialog._backdrop_snapshot.isNull()
    assert dialog._backdrop_color.alpha() == 190
    dialog.close()
    parent.close()


def test_full_desktop_window_constructs(tmp_path) -> None:
    app = QApplication.instance() or QApplication([])
    database = Database(tmp_path / "main.db")
    database.initialize("test")
    library = LibraryService(database)
    root = library.configure_root(tmp_path / "library")
    Image.new("RGB", (12, 18), "navy").save(root / "illustration" / "149672.png")
    library.scan()
    media = MediaService(library, tmp_path / "cache")
    catalog = CatalogService(database)
    author_group = catalog.list_groups()[0]
    author_tag = catalog.create_tag("很长的作者名称", author_group.id)
    second_author_tag = catalog.create_tag("另一位作者", author_group.id)
    ordinary_tag = catalog.create_tag("普通")
    illustration = catalog.query(CatalogQuery(kinds=("illustration",))).items[0]
    catalog.update_work(
        illustration.id,
        title=illustration.title or "",
        rating=illustration.rating,
        tag_ids=[author_tag.id],
        cover_member=illustration.cover_member,
    )
    with database.session() as session:
        session.add(Notification(kind="test", title="可见通知", details_json="[]"))
    controller = LibraryController(library)
    window = MainWindow(
        controller,
        library,
        catalog,
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
    QTest.qWait(20)
    assert any(
        window.notification_list.item(index).data(Qt.UserRole) is not None
        for index in range(window.notification_list.count())
    )
    assert any(
        window.notification_list.item(index).data(Qt.UserRole) is None
        for index in range(window.notification_list.count())
    )

    detail = WorkDetailDialog(illustration.id, catalog, media, window)
    detail.show()
    app.processEvents()
    assert not any(label.text() == "普通" for label in detail.findChildren(QLabel))
    catalog.update_work(
        illustration.id,
        title=illustration.title or "",
        rating=illustration.rating,
        tag_ids=[author_tag.id, ordinary_tag.id],
        cover_member=illustration.cover_member,
    )
    QTest.qWait(600)
    assert any(label.text() == "普通" for label in detail.findChildren(QLabel))
    detail.close()
    read_detail = WorkDetailDialog(illustration.id, catalog, media, window)
    read_detail.start_reading()
    assert read_detail.requested_action == ("read", illustration.id, None)
    assert all(
        button.property("tagId") not in {author_tag.id, second_author_tag.id}
        for button in window.custom_tag_buttons
    )
    window.tag_search.setText("作者")
    app.processEvents()
    assert {
        button.property("tagId")
        for button in window.custom_tag_buttons
        if button.property("tagLayoutClass") == "author"
    } == {author_tag.id, second_author_tag.id}
    window.tag_search.clear()
    app.processEvents()
    window._filter_tag_from_detail(author_tag.id, "illustration")
    app.processEvents()
    assert [
        button.property("tagId")
        for button in window.custom_tag_buttons
        if button.property("tagLayoutClass") == "author"
    ] == [author_tag.id]
    visible_author = next(
        button for button in window.custom_tag_buttons if button.property("tagId") == author_tag.id
    )
    visible_author.click()
    app.processEvents()
    assert not visible_author.isVisible()
    assert all(
        button.property("tagLayoutClass") != "author" for button in window.custom_tag_buttons
    )
    window.illustration_filter.click()
    app.processEvents()
    assert window.windowTitle().startswith("HManガ")
    assert window.pages.count() == 3
    assert window.brand_button.text() == "HManガ"
    assert window.notification_button.size() == QSize(44, 44)
    assert window.settings_button.size() == QSize(44, 44)
    assert window.close_button.size() == QSize(44, 44)
    assert window.windowFlags() & Qt.FramelessWindowHint
    assert window.work_list.count() == 1
    assert window.work_list.item(0).text() == ""
    assert window.work_list.itemWidget(window.work_list.item(0)) is not None
    window.work_list.setCurrentRow(0)
    selected_row = window.work_list.itemWidget(window.work_list.item(0))
    tag_summary = selected_row.findChild(TagSummaryWidget)
    author_chips = [chip for chip in tag_summary.chips if chip.property("authorTag")]
    assert len(author_chips) == 1
    assert AUTHOR_TAG_COLOR in author_chips[0].styleSheet()
    assert "border: 2px solid #9a6f7b" in selected_row.styleSheet()
    assert "background: transparent" in window.work_list.styleSheet()
    QTest.mouseClick(
        window.work_list.viewport(),
        Qt.LeftButton,
        pos=QPoint(10, window.work_list.viewport().height() - 5),
    )
    assert window.work_list.currentItem() is None
    assert "border: none" in selected_row.styleSheet()
    window.work_list.setCurrentRow(0)
    theme_bar = window.brand_button.parentWidget()
    QTest.mouseClick(
        theme_bar,
        Qt.LeftButton,
        pos=QPoint(theme_bar.width() // 2, theme_bar.height() // 2),
    )
    assert window.work_list.currentItem() is None
    summary = TagSummaryWidget([(f"Tag {index}", "#777") for index in range(8)], window)
    summary.resize(180, 31)
    summary.show()
    app.processEvents()
    assert summary.more.isVisible()
    assert summary.more.text().startswith("+")
    assert summary.testAttribute(Qt.WA_TransparentForMouseEvents)
    summary.deleteLater()
    independent_dialog = ScreenCenteredDialog(window)
    assert independent_dialog.parentWidget() is None
    assert independent_dialog._center_screen_hint is window.screen()
    floating_card = FloatingCardDialog(window)
    floating_card.show()
    app.processEvents()
    assert floating_card.parentWidget() is window
    assert floating_card.geometry() == window.rect()
    assert floating_card.card.parentWidget() is floating_card
    window.resize(430, 360)
    app.processEvents()
    assert floating_card.geometry() == window.rect()
    assert floating_card.card.size() == QSize(
        min(560, window.width() - 48), min(520, window.height() - 48)
    )
    QTest.mouseClick(floating_card, Qt.LeftButton, pos=floating_card.card.geometry().center())
    assert floating_card.isVisible()
    QTest.mouseClick(floating_card, Qt.LeftButton, pos=QPoint(2, 2))
    assert not floating_card.isVisible()
    window.close()
    assert catalog.setting("windows_main_geometry", "")
    controller.stop()


def test_desktop_kind_filters_match_their_visible_selection(tmp_path) -> None:
    app = QApplication.instance() or QApplication([])
    database = Database(tmp_path / "main.db")
    database.initialize("test")
    library = LibraryService(database)
    root = library.configure_root(tmp_path / "library")
    image = BytesIO()
    Image.new("RGB", (12, 18), "navy").save(image, "WEBP")
    with zipfile.ZipFile(root / "123456.zip", "w") as archive:
        archive.writestr("00001.webp", image.getvalue())
    Image.new("RGB", (12, 18), "green").save(root / "illustration" / "picture.png")
    library.scan()
    catalog = CatalogService(database)
    controller = LibraryController(library)
    window = MainWindow(
        controller,
        library,
        catalog,
        MediaService(library, tmp_path / "cache"),
        UploadService(database, library, tmp_path / "cache"),
        PairingService(database),
        BackupService(database, library),
        MigrationService(database, library),
        CacheService(database, tmp_path / "cache"),
        NotificationService(database),
        AppearanceService(database),
    )

    assert window.work_list.count() == 1
    assert window.comic_filter.text() == "漫画"
    assert window.illustration_filter.text() == "插画"
    assert catalog.get_work(window.work_list.item(0).data(256)).kind == "comic"

    window.tag_search.setText("漫画")
    app.processEvents()
    assert not window.comic_filter.isHidden()
    assert window.illustration_filter.isHidden()
    window.tag_search.clear()
    app.processEvents()

    # Clicking the other system tag switches the required exclusive choice.
    window.illustration_filter.click()
    app.processEvents()
    assert window.comic_filter.text() == "漫画"
    assert window.illustration_filter.text() == "插画"
    assert window.work_list.count() == 1
    assert catalog.get_work(window.work_list.item(0).data(256)).kind == "illustration"

    # Clicking the already selected choice cannot leave both choices empty.
    window.illustration_filter.click()
    app.processEvents()
    assert window.work_list.count() == 1
    assert window.illustration_filter.text() == "插画"

    window.clear_filters()
    app.processEvents()
    assert window.comic_filter.text() == "漫画"
    assert window.illustration_filter.text() == "插画"
    assert window.work_list.count() == 1

    window.close()
    controller.stop()


def test_deleting_work_keeps_desktop_alive(tmp_path) -> None:
    app = QApplication.instance() or QApplication([])
    database = Database(tmp_path / "main.db")
    database.initialize("test")
    library = LibraryService(database)
    root = library.configure_root(tmp_path / "library")
    image_path = root / "illustration" / "delete-me.png"
    Image.new("RGB", (12, 18), "navy").save(image_path)
    library.scan()
    catalog = CatalogService(database)
    media = MediaService(library, tmp_path / "cache")
    controller = LibraryController(library)
    window = MainWindow(
        controller,
        library,
        catalog,
        media,
        UploadService(database, library, tmp_path / "cache"),
        PairingService(database),
        BackupService(database, library),
        MigrationService(database, library),
        CacheService(database, tmp_path / "cache"),
        NotificationService(database),
        AppearanceService(database),
    )
    work = catalog.query(CatalogQuery(kinds=("illustration",))).items[0]
    window.show()
    app.processEvents()

    window._delete_work(work.id)
    app.processEvents()

    assert not image_path.exists()
    assert catalog.get_work(work.id) is None
    assert not window.isHidden()
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
