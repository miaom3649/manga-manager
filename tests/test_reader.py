from __future__ import annotations

import zipfile
from datetime import UTC, datetime
from io import BytesIO

from PIL import Image

from hmanga.database import Database, Work
from hmanga.library import LibraryService, file_fingerprint
from hmanga.media import MediaService
from hmanga.reader import ReaderService


def image_bytes() -> bytes:
    output = BytesIO()
    Image.new("RGB", (12, 18), "navy").save(output, "WEBP")
    return output.getvalue()


def test_reader_natural_order_progress_and_mode(tmp_path) -> None:
    database = Database(tmp_path / "reader.db")
    database.initialize("test")
    library = LibraryService(database)
    root = library.configure_root(tmp_path / "library")
    path = root / "123.zip"
    with zipfile.ZipFile(path, "w") as archive:
        for name in ("10.webp", "2.webp", "1.webp"):
            archive.writestr(name, image_bytes())
    with database.session() as session:
        work = Work(
            kind="comic",
            relative_path=path.name,
            file_name=path.name,
            normalized_file_name=path.name,
            normalized_title="",
            rating=0,
            fingerprint=file_fingerprint(path),
            file_size=path.stat().st_size,
            modified_ns=path.stat().st_mtime_ns,
            status="ready",
            cover_member="1.webp",
            added_at=datetime.now(UTC),
            updated_at=datetime.now(UTC),
        )
        session.add(work)
        session.flush()
        work_id = work.id
    media = MediaService(library, tmp_path / "cache")
    reader = ReaderService(database, media)
    with database.session() as session:
        work = session.get(Work, work_id)
    assert reader.members(work) == ["1.webp", "2.webp", "10.webp"]
    reader.save_progress(work, 2, 99)
    assert reader.progress(work).page_index == 2
    reader.set_preferred_mode("single")
    assert reader.preferred_mode() == "single"


def test_previews_use_every_third_sorted_image(tmp_path) -> None:
    database = Database(tmp_path / "preview.db")
    database.initialize("test")
    library = LibraryService(database)
    root = library.configure_root(tmp_path / "library")
    path = root / "456.zip"
    with zipfile.ZipFile(path, "w") as archive:
        for number in range(16, 0, -1):
            archive.writestr(f"{number:05}.webp", image_bytes())
    library.scan()
    work = library.list_works()[0]
    media = MediaService(library, tmp_path / "cache")

    assert work.cover_member == "00001.webp"
    assert media.preview_members(work) == [
        "00004.webp",
        "00007.webp",
        "00010.webp",
        "00013.webp",
        "00016.webp",
    ]
