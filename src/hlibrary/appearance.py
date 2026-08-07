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
    if theme == "dark":
        app.setStyleSheet(
            "QWidget { background: #17141c; color: #eeeaf2; } "
            "QLineEdit, QListWidget, QComboBox, QScrollArea { background: #211d27; "
            "border: 1px solid #51465f; } QPushButton { padding: 7px 12px; }"
        )
    elif theme == "light":
        app.setStyleSheet(
            "QWidget { background: #f8f5fb; color: #25232a; } "
            "QLineEdit, QListWidget, QComboBox, QScrollArea { background: white; "
            "border: 1px solid #d8d0df; } QPushButton { padding: 7px 12px; }"
        )
    else:
        app.setStyleSheet("")
