from __future__ import annotations

from io import BytesIO
from pathlib import Path
from zipfile import ZIP_DEFLATED, ZipFile

from PIL import Image

from hmanga.database import Database, Work
from hmanga.library import LibraryService


def image_bytes(color: str = "red") -> bytes:
    output = BytesIO()
    Image.new("RGB", (8, 12), color).save(output, format="PNG")
    return output.getvalue()


def write_comic(path: Path, color: str = "red") -> None:
    with ZipFile(path, "w", ZIP_DEFLATED) as archive:
        archive.writestr("001.webp", image_bytes(color))
        archive.writestr("002.webp", image_bytes("blue"))


def write_padded_comic_out_of_order(path: Path) -> None:
    with ZipFile(path, "w", ZIP_DEFLATED) as archive:
        archive.writestr("00007.webp", image_bytes("red"))
        archive.writestr("00001.webp", image_bytes("blue"))


def build_library(tmp_path: Path) -> tuple[Database, LibraryService, Path]:
    database = Database(tmp_path / "data.db")
    database.initialize("test")
    library = LibraryService(database)
    root = library.configure_root(tmp_path / "library")
    return database, library, root


def test_scan_collects_comics_and_illustrations(tmp_path: Path) -> None:
    database, library, root = build_library(tmp_path)
    write_comic(root / "001234.zip")
    write_comic(root / "named-work.zip")
    Image.new("RGB", (10, 10), "green").save(root / "illustration" / "画.png")
    (root / "broken.zip").write_bytes(b"not a zip")
    (root / "illustration" / "not-image.mp3").write_bytes(b"not an image")

    first = library.scan()
    assert (first.comics, first.illustrations) == (2, 1)
    assert len(first.added) == 3
    assert sorted(first.invalid) == ["broken.zip", "illustration/not-image.mp3"]

    works = {work.file_name: work for work in library.list_works()}
    assert works["001234.zip"].number == "001234"
    assert works["named-work.zip"].number is None
    assert works["画.png"].kind == "illustration"

    second = library.scan()
    assert second.added == []
    assert second.invalid == []  # unchanged invalid files do not notify repeatedly
    database.close()


def test_configure_root_migrates_legacy_chinese_directories(tmp_path: Path) -> None:
    root = tmp_path / "library"
    (root / "插画").mkdir(parents=True)
    (root / "备份").mkdir()
    (root / "插画" / "legacy.png").write_bytes(b"image")
    (root / "备份" / "legacy.sqlite").write_bytes(b"backup")
    database = Database(tmp_path / "data.db")
    database.initialize("test")

    LibraryService(database).configure_root(root)

    assert (root / "illustration" / "legacy.png").is_file()
    assert (root / "config-backup" / "legacy.sqlite").is_file()
    assert not (root / "插画").exists()
    assert not (root / "备份").exists()
    database.close()


def test_scan_uses_naturally_first_image_and_repairs_legacy_default(tmp_path: Path) -> None:
    database, library, root = build_library(tmp_path)
    write_padded_comic_out_of_order(root / "123.zip")

    library.scan()
    work = library.list_works()[0]
    assert work.cover_member == "00001.webp"

    # 模拟旧版本按 ZIP 内部存储顺序选择了第一张图。
    with database.session() as session:
        session.get(Work, work.id).cover_member = "00007.webp"
    library.scan()
    assert library.list_works()[0].cover_member == "00001.webp"
    database.close()


def test_external_rename_preserves_metadata(tmp_path: Path) -> None:
    database, library, root = build_library(tmp_path)
    original = root / "459808.zip"
    write_comic(original)
    library.scan()
    work = library.list_works()[0]
    original_id = work.id
    with database.session() as session:
        stored = session.get(Work, original_id)
        assert stored is not None
        stored.title = "保留标题"

    original.rename(root / "888888.zip")
    result = library.scan()
    renamed = library.list_works()[0]
    assert result.renamed == [("459808.zip", "888888.zip")]
    assert renamed.id == original_id
    assert renamed.title == "保留标题"
    assert renamed.number == "888888"
    database.close()


def test_replacement_waits_for_confirmation(tmp_path: Path) -> None:
    database, library, root = build_library(tmp_path)
    comic = root / "459808.zip"
    write_comic(comic, "red")
    library.scan()

    write_comic(comic, "green")
    result = library.scan()
    work = library.list_works()[0]
    assert result.replacements == ["459808.zip"]
    assert work.status == "replacement_pending"
    library.resolve_replacement(work.id, preserve_metadata=False)
    resolved = library.list_works()[0]
    assert resolved.status == "ready"
    assert resolved.title is None
    database.close()


def test_missing_file_removes_work(tmp_path: Path) -> None:
    database, library, root = build_library(tmp_path)
    comic = root / "459808.zip"
    write_comic(comic)
    library.scan()
    comic.unlink()

    result = library.scan()
    assert result.missing == ["459808.zip"]
    assert library.list_works() == []
    database.close()
