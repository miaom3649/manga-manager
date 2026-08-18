from __future__ import annotations

import hashlib
import zipfile
from collections import OrderedDict
from io import BytesIO
from pathlib import Path
from threading import RLock

from PIL import Image, ImageOps, ImageSequence

from hmanga.database import Work
from hmanga.i18n import tr
from hmanga.library import LibraryService
from hmanga.text import natural_key

IMAGE_SUFFIXES = {
    ".avif",
    ".bmp",
    ".gif",
    ".heic",
    ".heif",
    ".jpeg",
    ".jpg",
    ".png",
    ".tif",
    ".tiff",
    ".webp",
}


class MediaService:
    def __init__(self, library: LibraryService, cache_dir: Path) -> None:
        self.library = library
        self.cache_dir = cache_dir
        self.thumbnail_dir = cache_dir / "thumbnails"
        self.thumbnail_dir.mkdir(parents=True, exist_ok=True)
        self._member_cache: OrderedDict[tuple[object, ...], tuple[str, ...]] = OrderedDict()
        self._member_cache_lock = RLock()

    def work_path(self, work: Work) -> Path:
        root = self.library.library_root()
        if root is None:
            raise FileNotFoundError(tr("label.library_root_unset"))
        return root / Path(work.relative_path)

    def clear_thumbnail_cache(self) -> None:
        for path in self.thumbnail_dir.glob("*"):
            if path.is_file():
                path.unlink(missing_ok=True)

    def comic_members(self, work: Work) -> list[str]:
        if work.kind != "comic":
            return []
        cache_key = (
            work.relative_path,
            work.fingerprint,
            work.file_size,
            work.modified_ns,
        )
        with self._member_cache_lock:
            cached = self._member_cache.pop(cache_key, None)
            if cached is not None:
                self._member_cache[cache_key] = cached
                return list(cached)
        with zipfile.ZipFile(self.work_path(work)) as archive:
            names = [
                info.filename
                for info in archive.infolist()
                if not info.is_dir() and Path(info.filename).suffix.casefold() in IMAGE_SUFFIXES
            ]
        members = tuple(sorted(names, key=natural_key))
        with self._member_cache_lock:
            self._member_cache[cache_key] = members
            while len(self._member_cache) > 64:
                self._member_cache.popitem(last=False)
        return list(members)

    def preview_members(self, work: Work) -> list[str]:
        members = self.comic_members(work)
        return [members[index] for index in (3, 6, 9, 12, 15) if index < len(members)]

    def read_original(self, work: Work, member: str | None = None) -> bytes:
        path = self.work_path(work)
        if work.kind == "illustration":
            return path.read_bytes()
        selected = member or work.cover_member
        if selected is None:
            members = self.comic_members(work)
            if not members:
                raise FileNotFoundError(tr("label.comic_has_no_readable_images"))
            selected = members[0]
        with zipfile.ZipFile(path) as archive:
            return archive.read(selected)

    def thumbnail(self, work: Work, width: int = 220, height: int = 220) -> Path:
        identity = f"{work.fingerprint}:{work.cover_member}:{width}:{height}:v1"
        animated_gif = work.kind == "illustration" and work.file_name.casefold().endswith(".gif")
        suffix = ".gif" if animated_gif else ".webp"
        target = self.thumbnail_dir / f"{hashlib.sha256(identity.encode()).hexdigest()}{suffix}"
        if target.exists():
            target.touch()
            return target
        data = self.read_original(work)
        with Image.open(BytesIO(data)) as source:
            if animated_gif and getattr(source, "n_frames", 1) > 1:
                frames = []
                durations = []
                for frame in ImageSequence.Iterator(source):
                    value = ImageOps.exif_transpose(frame).convert("RGBA")
                    value.thumbnail((width, height), Image.Resampling.LANCZOS)
                    frames.append(value)
                    durations.append(frame.info.get("duration", 100))
                frames[0].save(
                    target,
                    "GIF",
                    save_all=True,
                    append_images=frames[1:],
                    duration=durations,
                    loop=source.info.get("loop", 0),
                    disposal=2,
                )
                return target
            source.seek(0)
            image = ImageOps.exif_transpose(source).convert("RGBA")
            image.thumbnail((width, height), Image.Resampling.LANCZOS)
            background = Image.new("RGBA", image.size, (0, 0, 0, 0))
            background.alpha_composite(image)
            background.save(target, "WEBP", quality=85, method=4)
        return target
