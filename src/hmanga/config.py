from __future__ import annotations

import os
import sys
from dataclasses import dataclass
from pathlib import Path

APP_NAME = "HManガ"
APP_ID = "hmanga"
LEGACY_APP_ID = "HLibrary"
DATABASE_NAME = "hmanga.db"
LEGACY_DATABASE_NAME = "hlibrary.db"
DEFAULT_API_HOST = "0.0.0.0"
DEFAULT_API_PORT = 18459


def user_data_dir() -> Path:
    """Return a per-user writable directory without requiring platformdirs."""
    if sys.platform == "win32":
        root = Path(os.environ.get("LOCALAPPDATA", Path.home() / "AppData" / "Local"))
    else:
        root = Path(os.environ.get("XDG_DATA_HOME", Path.home() / ".local" / "share"))

    data_dir = root / APP_ID
    legacy_dir = root / LEGACY_APP_ID
    if not data_dir.exists() and legacy_dir.exists():
        legacy_dir.rename(data_dir)

    if data_dir.exists():
        for suffix in ("", "-wal", "-shm"):
            legacy_database = data_dir / f"{LEGACY_DATABASE_NAME}{suffix}"
            database = data_dir / f"{DATABASE_NAME}{suffix}"
            if legacy_database.exists() and not database.exists():
                legacy_database.rename(database)
    return data_dir


@dataclass(frozen=True, slots=True)
class Settings:
    data_dir: Path
    database_path: Path
    cache_dir: Path
    api_host: str = DEFAULT_API_HOST
    api_port: int = DEFAULT_API_PORT

    @classmethod
    def load(cls) -> Settings:
        data_dir = user_data_dir()
        return cls(
            data_dir=data_dir,
            database_path=data_dir / DATABASE_NAME,
            cache_dir=data_dir / "cache",
        )

    def ensure_directories(self) -> None:
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self.cache_dir.mkdir(parents=True, exist_ok=True)
