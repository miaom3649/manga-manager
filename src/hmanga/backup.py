from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from pathlib import Path

from hmanga import __version__
from hmanga.database import AppMeta, Database
from hmanga.i18n import tr
from hmanga.library import BACKUP_DIRECTORY, LibraryService

LAST_AUTO_BACKUP = "last_auto_backup_date"
BACKUP_KIND_NAMES = {"自动": "auto", "手动": "manual", "恢复前": "restore"}
BACKUP_KIND_LABELS = {value: key for key, value in BACKUP_KIND_NAMES.items()}


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
            raise ValueError(tr("label.library_root_unset"))
        directory = root / BACKUP_DIRECTORY
        directory.mkdir(exist_ok=True)
        self._cleanup_temporary_files(directory)
        return directory

    @staticmethod
    def _cleanup_temporary_files(directory: Path) -> None:
        for pattern in (
            "hmanga-*.tmp",
            "hmanga-*.tmp-wal",
            "hmanga-*.tmp-shm",
            "H库-*.tmp",
            "H库-*.tmp-wal",
            "H库-*.tmp-shm",
        ):
            for path in directory.glob(pattern):
                path.unlink(missing_ok=True)

    def create(self, kind: str = "手动", *, automatic_day: date | None = None) -> Path:
        if kind not in {"自动", "手动", "恢复前"}:
            raise ValueError(tr("label.unknown_backup_type"))
        now = datetime.now()
        directory = self.backup_directory()
        kind_name = BACKUP_KIND_NAMES[kind]
        target = directory / f"hmanga-{kind_name}-{now:%Y%m%d-%H%M%S}.sqlite"
        # A second manual click within the same second must not overwrite the
        # first backup. Keep the required filename shape and advance to the
        # next free timestamp instead of adding a random suffix.
        while target.exists():
            now += timedelta(seconds=1)
            target = directory / f"hmanga-{kind_name}-{now:%Y%m%d-%H%M%S}.sqlite"
        temporary = target.with_suffix(".tmp")
        source = sqlite3.connect(self.database.path)
        destination = sqlite3.connect(temporary)
        try:
            source.backup(destination)
            destination.commit()
            # The backup copies the source database's WAL setting.  Merge any
            # journal content and switch the finished copy back to a standalone
            # SQLite file before it is renamed into place.
            destination.execute("PRAGMA wal_checkpoint(TRUNCATE)")
            destination.execute("PRAGMA journal_mode=DELETE").fetchone()
        finally:
            destination.close()
            source.close()
        try:
            self.validate(temporary)
            temporary.replace(target)
        finally:
            temporary.unlink(missing_ok=True)
            temporary.with_name(temporary.name + "-wal").unlink(missing_ok=True)
            temporary.with_name(temporary.name + "-shm").unlink(missing_ok=True)
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
            raise ValueError(tr("error.backup_file_missing"))
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
            raise ValueError(tr("message.invalid_backup_file"))

    def list_backups(self) -> list[BackupInfo]:
        results = []
        directory = self.backup_directory()
        for path in (*directory.glob("hmanga-*.sqlite"), *directory.glob("H库-*.sqlite")):
            parts = path.stem.split("-")
            if len(parts) < 4:
                continue
            try:
                created = datetime.strptime(f"{parts[2]}-{parts[3]}", "%Y%m%d-%H%M%S")
            except ValueError:
                created = datetime.fromtimestamp(path.stat().st_mtime)
            kind = BACKUP_KIND_LABELS.get(parts[1], parts[1])
            results.append(BackupInfo(path, kind, created))
        return sorted(results, key=lambda item: item.path.stat().st_mtime, reverse=True)

    def delete_all(self) -> int:
        directory = self.backup_directory()
        targets = {
            *directory.glob("hmanga-*.sqlite"),
            *directory.glob("hmanga-*.tmp"),
            *directory.glob("hmanga-*.tmp-wal"),
            *directory.glob("hmanga-*.tmp-shm"),
            *directory.glob("H库-*.sqlite"),
            *directory.glob("H库-*.tmp"),
            *directory.glob("H库-*.tmp-wal"),
            *directory.glob("H库-*.tmp-shm"),
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
            (
                *self.backup_directory().glob("hmanga-auto-*.sqlite"),
                *self.backup_directory().glob("H库-自动-*.sqlite"),
            ),
            key=lambda path: path.stat().st_mtime,
            reverse=True,
        )
        for path in automatic[5:]:
            path.unlink()
