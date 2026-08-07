from __future__ import annotations

from datetime import UTC, date, datetime

from hlibrary.backup import BackupService
from hlibrary.database import Database, Work
from hlibrary.library import LibraryService


def add_work(database: Database, title: str) -> int:
    with database.session() as session:
        work = Work(
            kind="comic",
            relative_path="1.zip",
            file_name="1.zip",
            normalized_file_name="1.zip",
            normalized_title=title,
            title=title,
            rating=0,
            file_size=1,
            modified_ns=1,
            status="ready",
            added_at=datetime.now(UTC),
            updated_at=datetime.now(UTC),
        )
        session.add(work)
        session.flush()
        return work.id


def test_backup_restore_and_protection(tmp_path) -> None:
    database = Database(tmp_path / "main.db")
    database.initialize("test")
    library = LibraryService(database)
    library.configure_root(tmp_path / "library")
    work_id = add_work(database, "备份标题")
    backups = BackupService(database, library)
    saved = backups.create("手动")
    with database.session() as session:
        session.get(Work, work_id).title = "后来修改"

    protection = backups.restore(saved)

    with database.session() as session:
        assert session.get(Work, work_id).title == "备份标题"
    assert "恢复前" in protection.name


def test_daily_backup_once_and_retention(tmp_path) -> None:
    database = Database(tmp_path / "main.db")
    database.initialize("test")
    library = LibraryService(database)
    library.configure_root(tmp_path / "library")
    backups = BackupService(database, library)
    assert backups.automatic_if_due(date(2026, 8, 6)) is not None
    assert backups.automatic_if_due(date(2026, 8, 6)) is None
    manual = backups.create("手动")
    for _ in range(6):
        backups.create("自动")
    assert len(list((tmp_path / "library" / "备份").glob("H库-自动-*.sqlite"))) == 5
    assert manual.exists()


def test_delete_all_backups_removes_manual_and_automatic(tmp_path) -> None:
    database = Database(tmp_path / "main.db")
    database.initialize("test")
    library = LibraryService(database)
    library.configure_root(tmp_path / "library")
    backups = BackupService(database, library)
    backups.create("手动")
    backups.create("自动")

    assert backups.delete_all() == 2
    assert backups.list_backups() == []
