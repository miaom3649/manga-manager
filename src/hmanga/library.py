from __future__ import annotations

import hashlib
import json
import re
import zipfile
from dataclasses import dataclass, field
from datetime import UTC, datetime
from io import BytesIO
from pathlib import Path
from threading import RLock

from PIL import Image, UnidentifiedImageError
from pillow_heif import register_heif_opener
from sqlalchemy import delete, func, select

from hmanga.database import (
    AppMeta,
    Database,
    FileObservation,
    Notification,
    ReadingProgress,
    Work,
)
from hmanga.i18n import tr, trf
from hmanga.text import natural_key, normalize_text

register_heif_opener()

NUMBER_PATTERN = re.compile(r"[0-9]+")
LIBRARY_ROOT_KEY = "library_root"
ILLUSTRATION_DIRECTORY = "illustration"
BACKUP_DIRECTORY = "config-backup"


@dataclass(frozen=True, slots=True)
class Candidate:
    kind: str
    path: Path
    relative_path: str
    file_name: str
    number: str | None
    file_size: int
    modified_ns: int
    cover_member: str | None = None


@dataclass(slots=True)
class ScanResult:
    comics: int = 0
    illustrations: int = 0
    added: list[str] = field(default_factory=list)
    missing: list[str] = field(default_factory=list)
    renamed: list[tuple[str, str]] = field(default_factory=list)
    replacements: list[str] = field(default_factory=list)
    invalid: list[str] = field(default_factory=list)
    invalid_observations: list[tuple[str, int, int]] = field(default_factory=list, repr=False)

    @property
    def total(self) -> int:
        return self.comics + self.illustrations


def file_fingerprint(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _readable_image(data: bytes) -> bool:
    try:
        with Image.open(BytesIO(data)) as image:
            image.verify()
        return True
    except (OSError, UnidentifiedImageError, ValueError):
        return False


def inspect_comic(path: Path) -> tuple[bool, str | None]:
    try:
        with zipfile.ZipFile(path) as archive:
            if any(info.flag_bits & 0x1 for info in archive.infolist()):
                return False, None
            members = sorted(
                (info for info in archive.infolist() if not info.is_dir()),
                key=lambda item: natural_key(item.filename),
            )
            # Use the first readable image in natural filename order as the cover.
            for info in members:
                try:
                    if _readable_image(archive.read(info)):
                        return True, info.filename
                except (OSError, RuntimeError, zipfile.BadZipFile):
                    continue
    except (OSError, zipfile.BadZipFile, zipfile.LargeZipFile):
        return False, None
    return False, None


def inspect_illustration(path: Path) -> bool:
    try:
        with Image.open(path) as image:
            image.verify()
        return True
    except (OSError, UnidentifiedImageError, ValueError):
        return False


class LibraryService:
    def __init__(self, database: Database) -> None:
        self.database = database
        self.operation_lock = RLock()

    def library_root(self) -> Path | None:
        with self.database.session() as session:
            row = session.get(AppMeta, LIBRARY_ROOT_KEY)
            return Path(row.value) if row and row.value else None

    def configure_root(self, root: Path) -> Path:
        root = root.expanduser().resolve()
        root.mkdir(parents=True, exist_ok=True)
        (root / ILLUSTRATION_DIRECTORY).mkdir(exist_ok=True)
        (root / BACKUP_DIRECTORY).mkdir(exist_ok=True)
        with self.database.session() as session:
            row = session.get(AppMeta, LIBRARY_ROOT_KEY)
            if row is None:
                session.add(AppMeta(key=LIBRARY_ROOT_KEY, value=str(root)))
            else:
                row.value = str(root)
                row.updated_at = datetime.now(UTC)
        return root

    def list_works(self, limit: int = 50) -> list[Work]:
        with self.database.session() as session:
            return list(session.scalars(select(Work).order_by(Work.added_at.desc()).limit(limit)))

    def count_works(self) -> int:
        with self.database.session() as session:
            return session.scalar(select(func.count()).select_from(Work)) or 0

    def list_notifications(self, limit: int = 100) -> list[Notification]:
        with self.database.session() as session:
            return list(
                session.scalars(
                    select(Notification).order_by(Notification.created_at.desc()).limit(limit)
                )
            )

    def pending_replacements(self) -> list[Work]:
        with self.database.session() as session:
            return list(session.scalars(select(Work).where(Work.status == "replacement_pending")))

    def resolve_replacement(self, work_id: int, preserve_metadata: bool) -> None:
        root = self.library_root()
        if root is None:
            raise ValueError(tr("label.library_root_unset"))
        with self.database.session() as session:
            work = session.get(Work, work_id)
            if work is None or work.status != "replacement_pending":
                raise ValueError(tr("error.pending_replacement_missing"))
            path = root / Path(work.relative_path)
            valid, default_cover = inspect_comic(path) if work.kind == "comic" else (True, None)
            if not valid:
                raise ValueError(tr("error.replacement_file_unreadable"))
            if preserve_metadata and work.kind == "comic" and work.cover_member:
                with zipfile.ZipFile(path) as archive:
                    if work.cover_member not in archive.namelist():
                        work.cover_member = default_cover
                        session.add(
                            Notification(
                                kind="cover_fallback",
                                title=trf("cover.fallback", file_name=work.file_name),
                                details_json=json.dumps([work.file_name], ensure_ascii=False),
                            )
                        )
            if not preserve_metadata:
                work.title = None
                work.normalized_title = ""
                work.rating = 0
                work.tags = []
                work.cover_member = default_cover
                session.execute(delete(ReadingProgress).where(ReadingProgress.work_id == work.id))
            elif work.kind == "comic":
                with zipfile.ZipFile(path) as archive:
                    page_count = sum(
                        1
                        for info in archive.infolist()
                        if not info.is_dir() and _readable_image(archive.read(info))
                    )
                progress = session.get(ReadingProgress, work.id)
                if progress and page_count:
                    progress.page_index = min(progress.page_index, page_count - 1)
                    progress.content_fingerprint = work.fingerprint or ""
            work.status = "ready"
            work.updated_at = datetime.now(UTC)

    def scan(self) -> ScanResult:
        with self.operation_lock:
            return self._scan_unlocked()

    def _scan_unlocked(self) -> ScanResult:
        root = self.library_root()
        result = ScanResult()
        if root is None or not root.is_dir():
            return result

        candidates = self._discover(root, result)
        candidate_paths = {candidate.relative_path for candidate in candidates}
        now = datetime.now(UTC)

        with self.database.session() as session:
            existing = list(session.scalars(select(Work)))
            by_path = {work.relative_path: work for work in existing}
            unmatched_ids = {work.id for work in existing}
            rename_ids = {work.id for work in existing if work.relative_path not in candidate_paths}

            for candidate in candidates:
                work = by_path.get(candidate.relative_path)
                if work is not None:
                    unmatched_ids.discard(work.id)
                    if (
                        work.file_size == candidate.file_size
                        and work.modified_ns == candidate.modified_ns
                    ):
                        continue
                    fingerprint = file_fingerprint(candidate.path)
                    if work.fingerprint and work.fingerprint != fingerprint:
                        work.status = "replacement_pending"
                        work.fingerprint = fingerprint
                        result.replacements.append(candidate.file_name)
                    work.file_size = candidate.file_size
                    work.modified_ns = candidate.modified_ns
                    work.updated_at = now
                    continue

                fingerprint = file_fingerprint(candidate.path)
                renamed = next(
                    (
                        old
                        for old in existing
                        if old.id in unmatched_ids
                        and old.id in rename_ids
                        and old.fingerprint == fingerprint
                    ),
                    None,
                )
                if renamed is not None:
                    old_name = renamed.file_name
                    unmatched_ids.discard(renamed.id)
                    renamed.kind = candidate.kind
                    renamed.relative_path = candidate.relative_path
                    renamed.file_name = candidate.file_name
                    renamed.normalized_file_name = normalize_text(candidate.file_name)
                    renamed.number = candidate.number
                    renamed.file_size = candidate.file_size
                    renamed.modified_ns = candidate.modified_ns
                    if renamed.cover_member is None:
                        renamed.cover_member = candidate.cover_member
                    renamed.updated_at = now
                    result.renamed.append((old_name, candidate.file_name))
                    continue

                session.add(
                    Work(
                        kind=candidate.kind,
                        relative_path=candidate.relative_path,
                        file_name=candidate.file_name,
                        normalized_file_name=normalize_text(candidate.file_name),
                        normalized_title="",
                        number=candidate.number,
                        rating=0,
                        fingerprint=fingerprint,
                        file_size=candidate.file_size,
                        modified_ns=candidate.modified_ns,
                        status="ready",
                        cover_member=candidate.cover_member,
                        added_at=now,
                        updated_at=now,
                    )
                )
                result.added.append(candidate.file_name)

            missing = [work for work in existing if work.id in unmatched_ids]
            for work in missing:
                result.missing.append(work.file_name)
                session.execute(delete(Work).where(Work.id == work.id))

            self._update_invalid_observations(session, result, now)
            self._add_scan_notifications(session, result)

        return result

    def _discover(self, root: Path, result: ScanResult) -> list[Candidate]:
        candidates: list[Candidate] = []
        for path in sorted(root.iterdir(), key=lambda item: item.name.casefold()):
            if not path.is_file() or path.suffix.casefold() != ".zip":
                continue
            valid, cover = inspect_comic(path)
            if not valid:
                stat = path.stat()
                result.invalid_observations.append((path.name, stat.st_size, stat.st_mtime_ns))
                continue
            stat = path.stat()
            stem = path.stem
            candidates.append(
                Candidate(
                    kind="comic",
                    path=path,
                    relative_path=path.name,
                    file_name=path.name,
                    number=stem if NUMBER_PATTERN.fullmatch(stem) else None,
                    file_size=stat.st_size,
                    modified_ns=stat.st_mtime_ns,
                    cover_member=cover,
                )
            )
            result.comics += 1

        illustration_root = root / ILLUSTRATION_DIRECTORY
        if illustration_root.is_dir():
            for path in sorted(illustration_root.iterdir(), key=lambda item: item.name.casefold()):
                if not path.is_file():
                    continue
                if not inspect_illustration(path):
                    stat = path.stat()
                    result.invalid_observations.append(
                        (f"{ILLUSTRATION_DIRECTORY}/{path.name}", stat.st_size, stat.st_mtime_ns)
                    )
                    continue
                stat = path.stat()
                candidates.append(
                    Candidate(
                        kind="illustration",
                        path=path,
                        relative_path=f"{ILLUSTRATION_DIRECTORY}/{path.name}",
                        file_name=path.name,
                        number=None,
                        file_size=stat.st_size,
                        modified_ns=stat.st_mtime_ns,
                    )
                )
                result.illustrations += 1
        return candidates

    @staticmethod
    def _update_invalid_observations(session, result: ScanResult, now: datetime) -> None:
        current_invalid = {item[0] for item in result.invalid_observations}
        observations = {row.relative_path: row for row in session.scalars(select(FileObservation))}
        for relative_path, file_size, modified_ns in result.invalid_observations:
            previous = observations.get(relative_path)
            if (
                previous is None
                or previous.file_size != file_size
                or previous.modified_ns != modified_ns
            ):
                result.invalid.append(relative_path)
            if previous is None:
                session.add(
                    FileObservation(
                        relative_path=relative_path,
                        file_size=file_size,
                        modified_ns=modified_ns,
                        last_seen_at=now,
                    )
                )
            else:
                previous.file_size = file_size
                previous.modified_ns = modified_ns
                previous.last_seen_at = now
        for relative_path, observation in observations.items():
            if relative_path not in current_invalid:
                session.delete(observation)

    @staticmethod
    def _add_scan_notifications(session, result: ScanResult) -> None:
        events = (
            ("files_added", trf("scan.new_files", count=len(result.added)), result.added),
            ("files_missing", trf("scan.missing_files", count=len(result.missing)), result.missing),
            (
                "files_renamed",
                trf("scan.renamed_files", count=len(result.renamed)),
                [{"old": old, "new": new} for old, new in result.renamed],
            ),
            (
                "replacement_pending",
                trf("scan.replaced_files", count=len(result.replacements)),
                result.replacements,
            ),
            ("invalid_files", trf("scan.invalid_files", count=len(result.invalid)), result.invalid),
        )
        for kind, title, details in events:
            if details:
                session.add(
                    Notification(
                        kind=kind,
                        title=title,
                        details_json=json.dumps(details, ensure_ascii=False),
                    )
                )
