from __future__ import annotations

from datetime import UTC, datetime

from hmanga.database import AppMeta, Database, ReadingProgress, Work
from hmanga.i18n import tr
from hmanga.media import MediaService


class ReaderService:
    def __init__(self, database: Database, media: MediaService) -> None:
        self.database = database
        self.media = media

    def members(self, work: Work) -> list[str]:
        return self.media.comic_members(work)

    def page(self, work: Work, member: str) -> bytes:
        return self.media.read_original(work, member)

    def preferred_mode(self) -> str:
        with self.database.session() as session:
            value = session.get(AppMeta, "windows_reader_mode")
            return (
                value.value if value and value.value in {"single", "continuous"} else "continuous"
            )

    def set_preferred_mode(self, mode: str) -> None:
        if mode not in {"single", "continuous"}:
            raise ValueError(tr("label.unknown_reading_mode"))
        with self.database.session() as session:
            value = session.get(AppMeta, "windows_reader_mode")
            if value is None:
                session.add(AppMeta(key="windows_reader_mode", value=mode))
            else:
                value.value = mode
                value.updated_at = datetime.now(UTC)

    def progress(self, work: Work) -> ReadingProgress | None:
        with self.database.session() as session:
            value = session.get(ReadingProgress, work.id)
            if value is None or value.content_fingerprint != (work.fingerprint or ""):
                return None
            return value

    def save_progress(self, work: Work, page_index: int, page_offset: int = 0) -> None:
        with self.database.session() as session:
            value = session.get(ReadingProgress, work.id)
            if value is None:
                session.add(
                    ReadingProgress(
                        work_id=work.id,
                        page_index=max(0, page_index),
                        page_offset=max(0, page_offset),
                        content_fingerprint=work.fingerprint or "",
                    )
                )
            else:
                value.page_index = max(0, page_index)
                value.page_offset = max(0, page_offset)
                value.content_fingerprint = work.fingerprint or ""
                value.updated_at = datetime.now(UTC)
