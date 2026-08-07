from __future__ import annotations

import zipfile
from io import BytesIO

import pytest
from PIL import Image

from hlibrary.catalog import CatalogQuery, CatalogService
from hlibrary.database import Database
from hlibrary.library import LibraryService
from hlibrary.upload import UploadService


def make_zip(path, color: str) -> None:
    output = BytesIO()
    Image.new("RGB", (10, 10), color).save(output, "WEBP")
    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr("001.webp", output.getvalue())


def test_upload_and_explicit_overwrite(tmp_path) -> None:
    database = Database(tmp_path / "upload.db")
    database.initialize("test")
    library = LibraryService(database)
    root = library.configure_root(tmp_path / "library")
    service = UploadService(database, library, tmp_path / "cache")
    source = tmp_path / "123.zip"
    make_zip(source, "red")
    task = service.prepare([source])
    task.items[0].title = "第一版"
    service.commit(task, allow_overwrite=False)
    assert (root / "123.zip").exists()
    assert CatalogService(database).query(CatalogQuery()).items[0].title == "第一版"

    make_zip(source, "blue")
    replacement = service.prepare([source])
    assert replacement.conflicts
    replacement.items[0].title = "第二版"
    with pytest.raises(FileExistsError):
        service.commit(replacement, allow_overwrite=False)
    service.commit(replacement, allow_overwrite=True)
    page = CatalogService(database).query(CatalogQuery())
    assert page.total == 1
    assert page.items[0].title == "第二版"


def test_invalid_upload_cannot_commit(tmp_path) -> None:
    database = Database(tmp_path / "upload.db")
    database.initialize("test")
    library = LibraryService(database)
    library.configure_root(tmp_path / "library")
    source = tmp_path / "audio.mp3"
    source.write_bytes(b"not an image")
    service = UploadService(database, library, tmp_path / "cache")
    task = service.prepare([source])
    assert task.invalid
    with pytest.raises(ValueError):
        service.commit(task, allow_overwrite=False)
