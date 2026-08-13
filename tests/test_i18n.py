import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication

from hmanga.database import Database
from hmanga.i18n import (
    active_language,
    available_languages,
    catalog,
    configure_localization,
    set_language,
    tr,
    trf,
)


def test_chinese_catalog_and_dynamic_text() -> None:
    messages = catalog()
    assert messages["action.cancel"] == "取消"
    assert tr("action.cancel") == "取消"
    assert trf("upload.active_tasks", count=3) == "当前有 3 个上传任务。"
    assert trf("migration.confirm", files=2, size_mb="12.5").startswith(
        "将迁移 2 个已收录作品（12.5 MB）"
    )


def test_localization_filter_does_not_queue_deleted_widgets() -> None:
    from PySide6.QtCore import QEvent
    from PySide6.QtWidgets import QMenu

    from hmanga.i18n import LocalizationFilter

    app = QApplication.instance() or QApplication([])
    menu = QMenu()
    localization = LocalizationFilter()
    assert localization.eventFilter(menu, QEvent(QEvent.Type.Polish)) is False
    app.processEvents()


def test_external_language_pack_can_be_selected(tmp_path) -> None:
    database = Database(tmp_path / "hmanga.db")
    database.initialize("test")
    locale_directory = tmp_path / "locales"
    locale_directory.mkdir()
    (locale_directory / "en-US.json").write_text(
        '{"language.name":"English","action.cancel":"Cancel"}', encoding="utf-8"
    )
    configure_localization(database, locale_directory)

    assert ("en-US", "English") in available_languages()
    set_language(database, "en-US")
    assert active_language() == "en-US"
    assert tr("action.cancel") == "Cancel"
    assert tr("action.save") == "保存"  # Missing English entry falls back to Chinese.

    set_language(database, "zh-CN")
    database.close()
