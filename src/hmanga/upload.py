from __future__ import annotations

import os
import shutil
import threading
import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path

from sqlalchemy import delete, select

from hmanga.database import Database, ReadingProgress, Tag, Work
from hmanga.i18n import tr
from hmanga.library import (
    ILLUSTRATION_DIRECTORY,
    LibraryService,
    file_fingerprint,
    inspect_comic,
    inspect_illustration,
)
from hmanga.text import normalize_text


@dataclass(slots=True)
class UploadItem:
    source: Path
    staged: Path
    kind: str | None
    valid: bool
    error: str | None = None
    conflict: bool = False
    title: str = ""
    rating: int = 0
    tag_ids: set[int] = field(default_factory=set)
    cover_member: str | None = None


@dataclass(slots=True)
class UploadTask:
    id: str
    directory: Path
    items: list[UploadItem]

    @property
    def conflicts(self) -> list[UploadItem]:
        return [item for item in self.items if item.conflict]

    @property
    def invalid(self) -> list[UploadItem]:
        return [item for item in self.items if not item.valid]


class UploadService:
    def __init__(self, database: Database, library: LibraryService, temp_root: Path) -> None:
        self.database = database
        self.library = library
        self.temp_root = temp_root / "uploads"
        self.temp_root.mkdir(parents=True, exist_ok=True)
        for abandoned in self.temp_root.iterdir():
            if abandoned.is_dir():
                shutil.rmtree(abandoned, ignore_errors=True)
        self.active_tasks: dict[str, UploadTask] = {}
        self._expiry_timers: dict[str, threading.Timer] = {}

    def prepare(self, sources: list[Path]) -> UploadTask:
        task_id = uuid.uuid4().hex
        directory = self.temp_root / task_id
        directory.mkdir()
        items: list[UploadItem] = []
        seen: set[tuple[str, str]] = set()
        root = self.library.library_root()
        if root is None:
            raise ValueError(tr("label.library_root_unset"))
        try:
            for index, source in enumerate(sources):
                source = source.resolve()
                staged = directory / f"{index:04d}-{source.name}"
                shutil.copy2(source, staged)
                kind, cover = self._classify(staged)
                key = (kind or "invalid", source.name.casefold())
                duplicate = key in seen
                seen.add(key)
                target = (
                    root / source.name
                    if kind == "comic"
                    else root / ILLUSTRATION_DIRECTORY / source.name
                )
                valid = kind is not None and not duplicate
                error = tr("label.duplicate_in_batch") if duplicate else None
                if kind is None:
                    error = tr("message.invalid_work_file")
                items.append(
                    UploadItem(
                        source=source,
                        staged=staged,
                        kind=kind,
                        valid=valid,
                        error=error,
                        conflict=valid and target.exists(),
                        title=source.stem,
                        cover_member=cover,
                    )
                )
        except Exception:
            shutil.rmtree(directory, ignore_errors=True)
            raise
        task = UploadTask(task_id, directory, items)
        self.active_tasks[task.id] = task
        timer = threading.Timer(3600, lambda: self.cancel(task))
        timer.daemon = True
        timer.start()
        self._expiry_timers[task.id] = timer
        return task

    @staticmethod
    def _classify(path: Path) -> tuple[str | None, str | None]:
        if path.suffix.casefold() == ".zip":
            valid, cover = inspect_comic(path)
            return ("comic", cover) if valid else (None, None)
        return ("illustration", None) if inspect_illustration(path) else (None, None)

    def cancel(self, task: UploadTask) -> None:
        shutil.rmtree(task.directory, ignore_errors=True)
        self.active_tasks.pop(task.id, None)
        if timer := self._expiry_timers.pop(task.id, None):
            timer.cancel()

    def commit(self, task: UploadTask, allow_overwrite: bool) -> list[int]:
        if task.invalid:
            raise ValueError(tr("error.upload_has_invalid_files"))
        if task.conflicts and not allow_overwrite:
            raise FileExistsError(tr("label.duplicate_file_exists"))
        root = self.library.library_root()
        if root is None:
            raise ValueError(tr("label.library_root_unset"))
        backup_dir = task.directory / "rollback"
        backup_dir.mkdir()
        installed: list[Path] = []
        backups: list[tuple[Path, Path]] = []
        work_ids: list[int] = []
        try:
            with self.database.session() as session:
                for index, item in enumerate(task.items):
                    assert item.kind is not None
                    relative = item.source.name
                    if item.kind == "illustration":
                        relative = f"{ILLUSTRATION_DIRECTORY}/{item.source.name}"
                    target = root / Path(relative)
                    target.parent.mkdir(exist_ok=True)
                    existing = session.scalar(select(Work).where(Work.relative_path == relative))
                    if target.exists():
                        backup = backup_dir / f"{index:04d}-{target.name}"
                        os.replace(target, backup)
                        backups.append((backup, target))
                    incoming = target.with_name(target.name + ".hmanga-new")
                    shutil.copy2(item.staged, incoming)
                    os.replace(incoming, target)
                    installed.append(target)
                    stat = target.stat()
                    fingerprint = file_fingerprint(target)
                    tags = list(session.scalars(select(Tag).where(Tag.id.in_(item.tag_ids))))
                    if len(tags) != len(item.tag_ids):
                        raise ValueError(tr("error.upload_tag_not_found"))
                    if existing is None:
                        existing = Work(relative_path=relative)
                        session.add(existing)
                    else:
                        session.execute(
                            delete(ReadingProgress).where(ReadingProgress.work_id == existing.id)
                        )
                    existing.kind = item.kind
                    existing.file_name = item.source.name
                    existing.normalized_file_name = normalize_text(item.source.name)
                    existing.number = (
                        item.source.stem
                        if item.kind == "comic"
                        and item.source.stem.isascii()
                        and item.source.stem.isdigit()
                        else None
                    )
                    existing.title = item.title.strip() or None
                    existing.normalized_title = normalize_text(existing.title)
                    existing.rating = item.rating
                    existing.tags = tags
                    existing.cover_member = item.cover_member
                    existing.fingerprint = fingerprint
                    existing.file_size = stat.st_size
                    existing.modified_ns = stat.st_mtime_ns
                    existing.status = "ready"
                    existing.added_at = datetime.now(UTC)
                    existing.updated_at = datetime.now(UTC)
                    session.flush()
                    work_ids.append(existing.id)
        except Exception:
            for target in reversed(installed):
                target.unlink(missing_ok=True)
            for backup, target in reversed(backups):
                if backup.exists():
                    os.replace(backup, target)
            raise
        shutil.rmtree(task.directory, ignore_errors=True)
        self.active_tasks.pop(task.id, None)
        if timer := self._expiry_timers.pop(task.id, None):
            timer.cancel()
        return work_ids

    def active_count(self) -> int:
        return len(self.active_tasks)

    def cancel_all(self) -> None:
        for task in list(self.active_tasks.values()):
            self.cancel(task)
