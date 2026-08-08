from __future__ import annotations

import zipfile
from io import BytesIO

import pytest
from PIL import Image

from hmanga.database import Database
from hmanga.library import LibraryService
from hmanga.migration import MigrationService


def comic(path) -> None:
    data = BytesIO()
    Image.new("RGB", (8, 8), "green").save(data, "WEBP")
    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr("001.webp", data.getvalue())


def test_migrate_only_collected_files_and_keep_special_content(tmp_path) -> None:
    database = Database(tmp_path / "main.db")
    database.initialize("test")
    library = LibraryService(database)
    old = library.configure_root(tmp_path / "old")
    comic(old / "123.zip")
    (old / "unknown.txt").write_text("keep", encoding="utf-8")
    library.scan()
    target = tmp_path / "new"
    service = MigrationService(database, library)

    result = service.migrate(target)

    assert result.files == 1
    assert not result.old_root_removed
    assert (target / "123.zip").is_file()
    assert (old / "unknown.txt").is_file()
    assert library.library_root() == target.resolve()


def test_migration_conflict_causes_zero_changes(tmp_path) -> None:
    database = Database(tmp_path / "main.db")
    database.initialize("test")
    library = LibraryService(database)
    old = library.configure_root(tmp_path / "old")
    comic(old / "123.zip")
    library.scan()
    target = tmp_path / "new"
    target.mkdir()
    (target / "123.zip").write_bytes(b"conflict")

    with pytest.raises(FileExistsError):
        MigrationService(database, library).migrate(target)

    assert (old / "123.zip").is_file()
    assert (target / "123.zip").read_bytes() == b"conflict"
    assert library.library_root() == old.resolve()


def test_migrate_into_child_directory_keeps_outer_directory(tmp_path) -> None:
    database = Database(tmp_path / "main.db")
    database.initialize("test")
    library = LibraryService(database)
    old = library.configure_root(tmp_path / "old")
    comic(old / "123.zip")
    library.scan()
    target = old / "新目录"

    result = MigrationService(database, library).migrate(target)

    assert result.files == 1
    assert not result.old_root_removed
    assert not (old / "123.zip").exists()
    assert (target / "123.zip").is_file()
    assert old.is_dir()
    assert library.library_root() == target.resolve()


def test_migration_still_rejects_current_directory(tmp_path) -> None:
    database = Database(tmp_path / "main.db")
    database.initialize("test")
    library = LibraryService(database)
    old = library.configure_root(tmp_path / "old")

    with pytest.raises(ValueError, match="不能与当前目录相同"):
        MigrationService(database, library).preview(old)
