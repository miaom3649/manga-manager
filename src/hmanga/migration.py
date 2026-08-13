from __future__ import annotations

import os
import shutil
from dataclasses import dataclass
from pathlib import Path

from sqlalchemy import select

from hmanga.database import AppMeta, Database, Work
from hmanga.i18n import tr, trf
from hmanga.library import (
    BACKUP_DIRECTORY,
    ILLUSTRATION_DIRECTORY,
    LIBRARY_ROOT_KEY,
    LibraryService,
    file_fingerprint,
)


@dataclass(frozen=True, slots=True)
class MigrationPreview:
    files: int
    bytes: int
    conflicts: tuple[str, ...]
    missing: tuple[str, ...]
    same_disk: bool


@dataclass(frozen=True, slots=True)
class MigrationResult:
    files: int
    old_root_removed: bool


class MigrationService:
    def __init__(self, database: Database, library: LibraryService) -> None:
        self.database = database
        self.library = library

    def preview(self, target_root: Path) -> MigrationPreview:
        source_root = self.library.library_root()
        if source_root is None:
            raise ValueError(tr("label.library_root_unset"))
        target_root = target_root.expanduser().resolve()
        if target_root == source_root:
            raise ValueError(tr("label.same_library_directory"))
        target_root.mkdir(parents=True, exist_ok=True)
        with self.database.session() as session:
            works = list(session.scalars(select(Work)))
        conflicts = []
        missing = []
        total = 0
        for work in works:
            source = source_root / Path(work.relative_path)
            target = target_root / Path(work.relative_path)
            if not source.is_file():
                missing.append(work.relative_path)
            else:
                total += source.stat().st_size
            if target.exists():
                conflicts.append(work.relative_path)
        same_disk = source_root.stat().st_dev == target_root.stat().st_dev
        if not same_disk and shutil.disk_usage(target_root).free < total:
            raise ValueError(tr("error.destination_space_insufficient"))
        return MigrationPreview(len(works), total, tuple(conflicts), tuple(missing), same_disk)

    def migrate(self, target_root: Path) -> MigrationResult:
        source_root = self.library.library_root()
        if source_root is None:
            raise ValueError(tr("label.library_root_unset"))
        target_root = target_root.expanduser().resolve()
        preview = self.preview(target_root)
        if preview.conflicts:
            raise FileExistsError(
                tr("label.destination_duplicate_files") + "、".join(preview.conflicts)
            )
        if preview.missing:
            raise FileNotFoundError(
                tr("label.missing_file") + "、".join(preview.missing)
            )
        (target_root / ILLUSTRATION_DIRECTORY).mkdir(exist_ok=True)
        (target_root / BACKUP_DIRECTORY).mkdir(exist_ok=True)
        with self.database.session() as session:
            relative_paths = list(session.scalars(select(Work.relative_path)))
        completed: list[tuple[Path, Path]] = []
        try:
            for relative in relative_paths:
                source = source_root / Path(relative)
                target = target_root / Path(relative)
                target.parent.mkdir(parents=True, exist_ok=True)
                if preview.same_disk:
                    os.replace(source, target)
                else:
                    temporary = target.with_name(target.name + ".hmanga-migrate")
                    shutil.copy2(source, temporary)
                    if file_fingerprint(source) != file_fingerprint(temporary):
                        temporary.unlink(missing_ok=True)
                        raise OSError(trf("migration.copy_failed", path=relative))
                    os.replace(temporary, target)
                completed.append((source, target))
            with self.database.session() as session:
                setting = session.get(AppMeta, LIBRARY_ROOT_KEY)
                if setting is None:
                    raise ValueError(tr("error.library_root_setting_missing"))
                setting.value = str(target_root)
        except Exception:
            for source, target in reversed(completed):
                if not target.exists():
                    continue
                if preview.same_disk:
                    source.parent.mkdir(parents=True, exist_ok=True)
                    os.replace(target, source)
                else:
                    target.unlink(missing_ok=True)
            raise
        if not preview.same_disk:
            for source, target in completed:
                if target.is_file() and file_fingerprint(target) == file_fingerprint(source):
                    source.unlink()
        self._remove_empty(source_root / ILLUSTRATION_DIRECTORY)
        self._remove_empty(source_root / BACKUP_DIRECTORY)
        old_removed = self._remove_empty(source_root)
        return MigrationResult(len(completed), old_removed)

    @staticmethod
    def _remove_empty(path: Path) -> bool:
        try:
            path.rmdir()
            return True
        except (FileNotFoundError, OSError):
            return False
