from __future__ import annotations

from PySide6.QtCore import Qt

from hmanga.database import AppMeta, Database
from hmanga.i18n import tr

THEME_KEY = "theme"


class AppearanceService:
    def __init__(self, database: Database) -> None:
        self.database = database

    def theme(self) -> str:
        with self.database.session() as session:
            value = session.get(AppMeta, THEME_KEY)
            if value and value.value in {"system", "light", "dark"}:
                return value.value
            return "dark"

    def set_theme(self, theme: str) -> None:
        if theme not in {"system", "light", "dark"}:
            raise ValueError(tr("label.unknown_theme"))
        with self.database.session() as session:
            value = session.get(AppMeta, THEME_KEY)
            if value is None:
                session.add(AppMeta(key=THEME_KEY, value=theme))
            else:
                value.value = theme


def apply_theme(app, theme: str) -> None:
    if theme == "system":
        theme = "dark" if app.styleHints().colorScheme() == Qt.ColorScheme.Dark else "light"
    button_style = (
        "QPushButton { background: transparent; border: 2px solid #9a6f7b; "
        "border-radius: 10px; padding: 7px 12px; } "
        "QPushButton:hover { background: rgba(154, 111, 123, 40); } "
        "QPushButton:disabled { border-color: #888; color: #888; }"
    )
    field_style = (
        "QLineEdit, QComboBox, QSpinBox { background: transparent; "
        "border: 2px solid #9a6f7b; border-radius: 10px; padding: 6px 10px; } "
        "QLineEdit:focus, QComboBox:focus, QSpinBox:focus { border-width: 3px; } "
        "QComboBox QAbstractItemView { background: palette(base); color: palette(text); "
        "border: 2px solid #9a6f7b; border-radius: 8px; outline: none; "
        "selection-background-color: #9a6f7b; selection-color: white; padding: 4px; } "
        "QComboBox QAbstractItemView::item { min-height: 34px; padding: 2px 10px; "
        "border: none; } "
        "QComboBox QAbstractItemView::item:selected { background: #9a6f7b; color: white; } "
        "QRadioButton { spacing: 7px; } "
        "QRadioButton::indicator { width: 16px; height: 16px; "
        "border: 2px solid #9a6f7b; border-radius: 9px; background: transparent; } "
        "QRadioButton::indicator:checked { background: #9a6f7b; "
        "border: 2px solid #9a6f7b; }"
    )
    if theme == "dark":
        app.setStyleSheet(
            "QWidget { background: #171316; color: #f0e9ec; } "
            "QLineEdit, QListWidget, QComboBox, QScrollArea { background: #211b1f; "
            "border: 1px solid #57474f; } " + button_style + field_style
        )
    elif theme == "light":
        app.setStyleSheet(
            "QWidget { background: #eee7e9; color: #2b2427; } "
            "QLineEdit, QListWidget, QComboBox, QScrollArea { background: #f7f1f3; "
            "border: 1px solid #cfc3c7; } "
            'QLabel[tagChip="true"] { color: #2b2427; } '
            'QPushButton[tagChip="true"]:checked { color: #2b2427; } ' + button_style + field_style
        )
    else:
        app.setStyleSheet(button_style + field_style)
