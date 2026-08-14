from __future__ import annotations

import json
from functools import cache
from importlib.resources import files
from pathlib import Path

from PySide6.QtCore import QEvent, QObject
from PySide6.QtWidgets import (
    QAbstractButton,
    QApplication,
    QComboBox,
    QGroupBox,
    QLabel,
    QLineEdit,
    QWidget,
)

from hmanga.database import AppMeta, Database

LANGUAGE_KEY = "language"
DEFAULT_LANGUAGE = "zh-CN"
_active_language = DEFAULT_LANGUAGE
_user_locale_directory: Path | None = None


def _locale_path(code: str):
    if _user_locale_directory is not None:
        user_path = _user_locale_directory / f"{code}.json"
        if user_path.is_file():
            return user_path
    bundled = files("hmanga").joinpath("locales", f"{code}.json")
    return bundled if bundled.is_file() else None


@cache
def _read_catalog(code: str) -> dict[str, str]:
    path = _locale_path(code)
    if path is None:
        return {}
    raw = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(raw, dict) or not all(
        isinstance(key, str) and isinstance(value, str) for key, value in raw.items()
    ):
        raise ValueError(f"Invalid language pack: {code}")
    return raw


def catalog() -> dict[str, str]:
    chinese = _read_catalog(DEFAULT_LANGUAGE)
    if _active_language == DEFAULT_LANGUAGE:
        return chinese
    return chinese | _read_catalog(_active_language)


def available_languages() -> list[tuple[str, str]]:
    codes = {DEFAULT_LANGUAGE}
    bundled_directory = Path(str(files("hmanga").joinpath("locales")))
    if bundled_directory.is_dir():
        codes.update(path.stem for path in bundled_directory.glob("*.json"))
    if _user_locale_directory is not None and _user_locale_directory.is_dir():
        codes.update(path.stem for path in _user_locale_directory.glob("*.json"))
    results = []
    for code in sorted(codes):
        messages = _read_catalog(code)
        results.append((code, messages.get("language.name", code)))
    return results


def language_catalog(code: str) -> dict[str, str]:
    """Return one language merged over the complete Simplified Chinese catalog."""
    if _locale_path(code) is None:
        raise ValueError(f"Unknown language pack: {code}")
    chinese = _read_catalog(DEFAULT_LANGUAGE)
    return chinese if code == DEFAULT_LANGUAGE else chinese | _read_catalog(code)


def configure_localization(database: Database, user_directory: Path) -> None:
    global _active_language, _user_locale_directory
    _user_locale_directory = user_directory
    user_directory.mkdir(parents=True, exist_ok=True)
    _read_catalog.cache_clear()
    with database.session() as session:
        setting = session.get(AppMeta, LANGUAGE_KEY)
        requested = setting.value if setting else DEFAULT_LANGUAGE
    _active_language = requested if _locale_path(requested) is not None else DEFAULT_LANGUAGE


def active_language() -> str:
    return _active_language


def set_language(database: Database, code: str) -> None:
    global _active_language
    if _locale_path(code) is None:
        raise ValueError(f"Unknown language pack: {code}")
    with database.session() as session:
        setting = session.get(AppMeta, LANGUAGE_KEY)
        if setting is None:
            session.add(AppMeta(key=LANGUAGE_KEY, value=code))
        else:
            setting.value = code
    _active_language = code


def tr(source: str) -> str:
    """Resolve an English message key to the active language."""
    return catalog().get(source, source)


def trf(key: str, **values: object) -> str:
    """Format a complete catalog template with named runtime values."""
    return tr(key).format_map(values)


def _message_key(value: str) -> str:
    """Recover a stable message key from text already rendered in any locale."""
    if value in catalog():
        return value
    codes = [DEFAULT_LANGUAGE, *[code for code, _name in available_languages()]]
    for code in dict.fromkeys(codes):
        for key, translated in language_catalog(code).items():
            if translated == value:
                return key
    return value


def _translated_property(widget: QWidget, name: str, current: str) -> str:
    source_name = f"i18nSource_{name}"
    translated_name = f"i18nValue_{name}"
    previous_translation = widget.property(translated_name)
    source = widget.property(source_name)
    if source is None or (current != previous_translation and current != source):
        source = _message_key(current)
        widget.setProperty(source_name, source)
    else:
        normalized_source = _message_key(str(source))
        if normalized_source != source:
            source = normalized_source
            widget.setProperty(source_name, source)
    translated = tr(str(source))
    widget.setProperty(translated_name, translated)
    return translated


def localize_widget(widget: QWidget) -> None:
    if isinstance(widget, (QLabel, QAbstractButton)):
        current = widget.text()
        translated = _translated_property(widget, "text", current)
        if current != translated:
            widget.setText(translated)
    if isinstance(widget, QLineEdit):
        current = widget.placeholderText()
        translated = _translated_property(widget, "placeholder", current)
        if current != translated:
            widget.setPlaceholderText(translated)
    if isinstance(widget, QGroupBox):
        current = widget.title()
        translated = _translated_property(widget, "title", current)
        if current != translated:
            widget.setTitle(translated)
    tooltip = widget.toolTip()
    translated_tooltip = _translated_property(widget, "tooltip", tooltip)
    if tooltip != translated_tooltip:
        widget.setToolTip(translated_tooltip)
    if widget.isWindow():
        current = widget.windowTitle()
        translated = _translated_property(widget, "windowTitle", current)
        if current != translated:
            widget.setWindowTitle(translated)
    if isinstance(widget, QComboBox) and not widget.property("i18nKeepItemText"):
        for index in range(widget.count()):
            # Keep Qt.UserRole untouched: application code stores sort modes,
            # theme IDs and other behavior-critical values there.
            source = widget.itemData(index, 0x04E8)
            if source is None:
                source = _message_key(widget.itemText(index))
                widget.setItemData(index, source, 0x04E8)
            else:
                normalized_source = _message_key(str(source))
                if normalized_source != source:
                    source = normalized_source
                    widget.setItemData(index, source, 0x04E8)
            translated = tr(str(source))
            if widget.itemText(index) != translated:
                widget.setItemText(index, translated)


def localize_tree(root: QWidget) -> None:
    try:
        localize_widget(root)
        children = root.findChildren(QWidget)
    except RuntimeError:
        # Qt can destroy short-lived native menus while Python still holds the
        # wrapper. Such an object has no visible text left to translate.
        return
    for widget in children:
        try:
            localize_widget(widget)
        except RuntimeError:
            continue


class LocalizationFilter(QObject):
    def __init__(self, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._localizing = False

    def eventFilter(self, watched, event) -> bool:  # noqa: N802
        if not self._localizing and isinstance(watched, QWidget) and event.type() in {
            QEvent.Type.Show,
            QEvent.Type.Polish,
        }:
            # Translate synchronously. A queued callback could outlive a
            # temporary QMenu and then access an already deleted C++ object.
            # Setting text can synchronously generate another Polish event on
            # Windows, so prevent the nested event from translating again.
            self._localizing = True
            try:
                localize_tree(watched)
            finally:
                self._localizing = False
        return super().eventFilter(watched, event)


def install_localization(app: QApplication) -> LocalizationFilter:
    localization = LocalizationFilter(app)
    app.installEventFilter(localization)
    return localization
