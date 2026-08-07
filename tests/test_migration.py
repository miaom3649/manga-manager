from __future__ import annotations

import zipfile
from io import BytesIO

import pytest
from PIL import Image

from hlibrary.database import Database
from hlibrary.library import LibraryService
from hlibrary.migration import MigrationService


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
