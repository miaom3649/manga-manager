from __future__ import annotations

from datetime import UTC, date, datetime

from hmanga.backup import BackupService
from hmanga.database import Database, Work
from hmanga.library import LibraryService


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
    saved = backups.create("manual")
    with database.session() as session:
        session.get(Work, work_id).title = "后来修改"

    protection = backups.restore(saved)

    with database.session() as session:
        assert session.get(Work, work_id).title == "备份标题"
    assert protection.name.startswith("hmanga-restore-")


def test_daily_backup_once_and_retention(tmp_path) -> None:
    database = Database(tmp_path / "main.db")
    database.initialize("test")
    library = LibraryService(database)
    library.configure_root(tmp_path / "library")
    backups = BackupService(database, library)
    assert backups.automatic_if_due(date(2026, 8, 6)) is not None
    assert backups.automatic_if_due(date(2026, 8, 6)) is None
    manual = backups.create("manual")
    for _ in range(6):
        backups.create("auto")
    assert len(list((tmp_path / "library" / "config-backup").glob("hmanga-auto-*.sqlite"))) == 5
    assert manual.exists()
    assert manual.name.startswith("hmanga-manual-")
    assert len(manual.stem.split("-")) == 4


def test_backup_leaves_no_temporary_wal_files(tmp_path) -> None:
    database = Database(tmp_path / "main.db")
    database.initialize("test")
    library = LibraryService(database)
    library.configure_root(tmp_path / "library")
    backups = BackupService(database, library)

    backups.create("manual")

    names = {path.name for path in (tmp_path / "library" / "config-backup").iterdir()}
    assert not any(name.endswith((".tmp", ".tmp-wal", ".tmp-shm")) for name in names)


def test_delete_all_backups_removes_manual_and_automatic(tmp_path) -> None:
    database = Database(tmp_path / "main.db")
    database.initialize("test")
    library = LibraryService(database)
    library.configure_root(tmp_path / "library")
    backups = BackupService(database, library)
    backups.create("manual")
    backups.create("auto")

    assert backups.delete_all() == 2
    assert backups.list_backups() == []
