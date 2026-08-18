from __future__ import annotations

import os

from hmanga.cache import CacheService
from hmanga.database import Database


def test_cache_lru_limit_and_clear(tmp_path) -> None:
    database = Database(tmp_path / "main.db")
    database.initialize("test")
    cache = CacheService(database, tmp_path / "cache")
    old = cache.thumbnail_dir / "old.webp"
    new = cache.thumbnail_dir / "new.webp"
    old.write_bytes(b"a" * 10)
    new.write_bytes(b"b" * 10)
    os.utime(old, (1, 1))
    os.utime(new, (2, 2))

    cache.set_limit(10)

    assert not old.exists()
    assert new.exists()
    assert cache.usage() == 10
    assert cache.clear() == 1
