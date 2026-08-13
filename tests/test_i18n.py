import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication, QComboBox, QLabel, QWidget

from hmanga.database import Database
from hmanga.i18n import (
    active_language,
    available_languages,
    catalog,
    configure_localization,
    localize_tree,
    set_language,
    tr,
    trf,
)


def test_chinese_catalog_and_dynamic_text() -> None:
    messages = catalog()
    assert messages["action.cancel"] == "取消"
    assert tr("action.cancel") == "取消"
    assert "3" in trf("upload.active_tasks", count=3)
    migration_message = trf("migration.confirm", files=2, size_mb="12.5")
    assert "2" in migration_message
    assert "12.5" in migration_message


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


def test_existing_desktop_widgets_switch_language_immediately(tmp_path) -> None:
    app = QApplication.instance() or QApplication([])
    database = Database(tmp_path / "hmanga.db")
    database.initialize("test")
    locale_directory = tmp_path / "locales"
    locale_directory.mkdir()
    (locale_directory / "en-US.json").write_text(
        '{"language.name":"English","action.cancel":"Cancel",'
        '"label.dark_theme":"Dark"}',
        encoding="utf-8",
    )
    configure_localization(database, locale_directory)
    root = QWidget()
    label = QLabel(tr("action.cancel"), root)
    choices = QComboBox(root)
    choices.addItem(tr("label.dark_theme"), "dark")
    localize_tree(root)

    set_language(database, "en-US")
    localize_tree(root)

    assert label.text() == "Cancel"
    assert choices.itemText(0) == "Dark"
    assert choices.itemData(0) == "dark"
    set_language(database, "zh-CN")
    database.close()
    app.processEvents()


def test_language_selector_keeps_each_pack_self_name(tmp_path) -> None:
    app = QApplication.instance() or QApplication([])
    database = Database(tmp_path / "hmanga.db")
    database.initialize("test")
    locale_directory = tmp_path / "locales"
    locale_directory.mkdir()
    (locale_directory / "en-US.json").write_text(
        '{"language.name":"English"}', encoding="utf-8"
    )
    configure_localization(database, locale_directory)
    selector = QComboBox()
    selector.setProperty("i18nKeepItemText", True)
    selector.addItem("Simplified Chinese", "zh-CN")
    selector.addItem("English", "en-US")

    set_language(database, "en-US")
    localize_tree(selector)

    assert [selector.itemText(index) for index in range(selector.count())] == [
        "Simplified Chinese",
        "English",
    ]
    set_language(database, "zh-CN")
    database.close()
    app.processEvents()
