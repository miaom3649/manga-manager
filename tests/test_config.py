from pathlib import Path

from hmanga.config import Settings


def test_settings_create_directories(tmp_path: Path) -> None:
    settings = Settings(
        data_dir=tmp_path / "data",
        database_path=tmp_path / "data" / "hmanga.db",
        cache_dir=tmp_path / "data" / "cache",
    )
    settings.ensure_directories()
    assert settings.data_dir.is_dir()
    assert settings.cache_dir.is_dir()
