from __future__ import annotations

from pathlib import Path

from hmanga.database import AppMeta, Database
from hmanga.i18n import tr

CACHE_LIMIT_KEY = "cache_limit_bytes"
DEFAULT_CACHE_LIMIT = 1024**3


class CacheService:
    def __init__(self, database: Database, cache_dir: Path) -> None:
        self.database = database
        self.cache_dir = cache_dir
        self.thumbnail_dir = cache_dir / "thumbnails"
        self.thumbnail_dir.mkdir(parents=True, exist_ok=True)

    def limit(self) -> int | None:
        with self.database.session() as session:
            value = session.get(AppMeta, CACHE_LIMIT_KEY)
            if value is None:
                return DEFAULT_CACHE_LIMIT
            return None if value.value == "unlimited" else int(value.value)

    def set_limit(self, value: int | None) -> None:
        if value is not None and value <= 0:
            raise ValueError(tr("label.cache_limit_positive"))
        text = "unlimited" if value is None else str(value)
        with self.database.session() as session:
            setting = session.get(AppMeta, CACHE_LIMIT_KEY)
            if setting is None:
                session.add(AppMeta(key=CACHE_LIMIT_KEY, value=text))
            else:
                setting.value = text
        self.enforce_limit()

    def usage(self) -> int:
        return sum(path.stat().st_size for path in self.thumbnail_dir.glob("*") if path.is_file())

    def enforce_limit(self) -> int:
        limit = self.limit()
        if limit is None:
            return 0
        files = sorted(
            (path for path in self.thumbnail_dir.glob("*") if path.is_file()),
            key=lambda path: path.stat().st_mtime,
        )
        usage = sum(path.stat().st_size for path in files)
        removed = 0
        for path in files:
            if usage <= limit:
                break
            size = path.stat().st_size
            path.unlink(missing_ok=True)
            usage -= size
            removed += 1
        return removed

    def clear(self) -> int:
        removed = 0
        for path in self.thumbnail_dir.glob("*"):
            if path.is_file():
                path.unlink()
                removed += 1
        return removed
