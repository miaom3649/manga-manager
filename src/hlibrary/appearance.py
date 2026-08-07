from __future__ import annotations

from hlibrary.database import AppMeta, Database

THEME_KEY = "theme"


class AppearanceService:
    def __init__(self, database: Database) -> None:
        self.database = database

    def theme(self) -> str:
        with self.database.session() as session:
            value = session.get(AppMeta, THEME_KEY)
            return value.value if value and value.value in {"system", "light", "dark"} else "system"

    def set_theme(self, theme: str) -> None:
        if theme not in {"system", "light", "dark"}:
            raise ValueError("未知主题")
        with self.database.session() as session:
            value = session.get(AppMeta, THEME_KEY)
            if value is None:
                session.add(AppMeta(key=THEME_KEY, value=theme))
            else:
                value.value = theme


def apply_theme(app, theme: str) -> None:
    button_style = (
        "QPushButton { background: transparent; border: 2px solid #6750a4; "
        "border-radius: 10px; padding: 7px 12px; } "
        "QPushButton:hover { background: rgba(103, 80, 164, 35); } "
        "QPushButton:disabled { border-color: #888; color: #888; }"
    )
    field_style = (
        "QLineEdit, QComboBox, QSpinBox { background: transparent; "
        "border: 2px solid #6750a4; border-radius: 10px; padding: 6px 10px; } "
        "QLineEdit:focus, QComboBox:focus, QSpinBox:focus { border-width: 3px; } "
        "QComboBox QAbstractItemView { background: palette(base); color: palette(text); "
        "border: 2px solid #6750a4; border-radius: 8px; outline: none; "
        "selection-background-color: #6750a4; selection-color: white; padding: 4px; } "
        "QComboBox QAbstractItemView::item { min-height: 34px; padding: 2px 10px; "
        "border: none; } "
        "QComboBox QAbstractItemView::item:selected { background: #6750a4; color: white; } "
        "QRadioButton { spacing: 7px; } "
        "QRadioButton::indicator { width: 16px; height: 16px; "
        "border: 2px solid #6750a4; border-radius: 9px; background: transparent; } "
        "QRadioButton::indicator:checked { background: #6750a4; "
        "border: 2px solid #6750a4; }"
    )
    if theme == "dark":
        app.setStyleSheet(
            "QWidget { background: #17141c; color: #eeeaf2; } "
            "QLineEdit, QListWidget, QComboBox, QScrollArea { background: #211d27; "
            "border: 1px solid #51465f; } " + button_style + field_style
        )
    elif theme == "light":
        app.setStyleSheet(
            "QWidget { background: #f8f5fb; color: #25232a; } "
            "QLineEdit, QListWidget, QComboBox, QScrollArea { background: white; "
            "border: 1px solid #d8d0df; } " + button_style + field_style
        )
    else:
        app.setStyleSheet(button_style + field_style)
