from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from datetime import UTC, date, datetime
from pathlib import Path

from hlibrary import __version__
from hlibrary.database import AppMeta, Database
from hlibrary.library import LibraryService

LAST_AUTO_BACKUP = "last_auto_backup_date"


@dataclass(frozen=True, slots=True)
class BackupInfo:
    path: Path
    kind: str
    created_at: datetime


class BackupService:
    def __init__(self, database: Database, library: LibraryService) -> None:
        self.database = database
        self.library = library

    def backup_directory(self) -> Path:
        root = self.library.library_root()
        if root is None:
            raise ValueError("尚未设置作品目录")
        directory = root / "备份"
        directory.mkdir(exist_ok=True)
        return directory

    def create(self, kind: str = "手动", *, automatic_day: date | None = None) -> Path:
        if kind not in {"自动", "手动", "恢复前"}:
            raise ValueError("未知备份类型")
        now = datetime.now()
        target = self.backup_directory() / f"H库-{kind}-{now:%Y%m%d-%H%M%S-%f}.sqlite"
        temporary = target.with_suffix(".tmp")
        source = sqlite3.connect(self.database.path)
        destination = sqlite3.connect(temporary)
        try:
            source.backup(destination)
        finally:
            destination.close()
            source.close()
        self.validate(temporary)
        temporary.replace(target)
        if kind == "自动":
            # `automatic_if_due` may be checking a supplied/local calendar day.
            # Record that exact day instead of deriving it again from the clock,
            # otherwise a timezone/day-boundary can immediately create a duplicate.
            self._record_auto_backup(automatic_day or now.date())
            self._trim_automatic()
        return target

    @staticmethod
    def validate(path: Path) -> None:
        if not path.is_file():
            raise ValueError("备份文件不存在")
        connection = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
        try:
            integrity = connection.execute("PRAGMA integrity_check").fetchone()[0]
            tables = {
                row[0]
                for row in connection.execute("SELECT name FROM sqlite_master WHERE type='table'")
            }
        finally:
            connection.close()
        if integrity != "ok" or not {"works", "app_meta", "tags"}.issubset(tables):
            raise ValueError("备份文件损坏或不是 H库 备份")

    def list_backups(self) -> list[BackupInfo]:
        results = []
        for path in self.backup_directory().glob("H库-*.sqlite"):
            parts = path.stem.split("-")
            if len(parts) < 4:
                continue
            try:
                created = datetime.strptime(f"{parts[2]}-{parts[3]}", "%Y%m%d-%H%M%S")
            except ValueError:
                created = datetime.fromtimestamp(path.stat().st_mtime)
            results.append(BackupInfo(path, parts[1], created))
        return sorted(results, key=lambda item: item.path.stat().st_mtime, reverse=True)

    def delete_all(self) -> int:
        directory = self.backup_directory()
        targets = {
            *directory.glob("H库-*.sqlite"),
            *directory.glob("H库-*.tmp"),
        }
        removed = 0
        for path in targets:
            if path.is_file():
                path.unlink()
                removed += 1
        return removed

    def automatic_if_due(self, today: date | None = None) -> Path | None:
        today = today or datetime.now().date()
        with self.database.session() as session:
            value = session.get(AppMeta, LAST_AUTO_BACKUP)
            if value and value.value == today.isoformat():
                return None
        return self.create("自动", automatic_day=today)

    def scheduled_if_due(self, now: datetime | None = None) -> Path | None:
        now = now or datetime.now()
        if now.hour < 2:
            return None
        return self.automatic_if_due(now.date())

    def restore(self, path: Path) -> Path:
        self.validate(path)
        protection = self.create("恢复前")
        source = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
        self.database.close()
        destination = sqlite3.connect(self.database.path)
        try:
            source.backup(destination)
        finally:
            destination.close()
            source.close()
        self.database.initialize(__version__)
        return protection

    def _record_auto_backup(self, day: date) -> None:
        with self.database.session() as session:
            value = session.get(AppMeta, LAST_AUTO_BACKUP)
            if value is None:
                session.add(AppMeta(key=LAST_AUTO_BACKUP, value=day.isoformat()))
            else:
                value.value = day.isoformat()
                value.updated_at = datetime.now(UTC)

    def _trim_automatic(self) -> None:
        automatic = sorted(
            self.backup_directory().glob("H库-自动-*.sqlite"),
            key=lambda path: path.stat().st_mtime,
            reverse=True,
        )
        for path in automatic[5:]:
            path.unlink()
