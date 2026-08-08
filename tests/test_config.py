from pathlib import Path

from hmanga.config import Settings, user_data_dir


def test_settings_create_directories(tmp_path: Path) -> None:
    settings = Settings(
        data_dir=tmp_path / "data",
        database_path=tmp_path / "data" / "hmanga.db",
        cache_dir=tmp_path / "data" / "cache",
    )
    settings.ensure_directories()
    assert settings.data_dir.is_dir()
    assert settings.cache_dir.is_dir()


def test_legacy_data_directory_and_database_are_migrated(
    tmp_path: Path, monkeypatch
) -> None:
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path))
    legacy_dir = tmp_path / "HLibrary"
    legacy_dir.mkdir()
    (legacy_dir / "hlibrary.db").write_bytes(b"database")
    (legacy_dir / "hlibrary.db-wal").write_bytes(b"wal")

    data_dir = user_data_dir()

    assert data_dir == tmp_path / "hmanga"
    assert not legacy_dir.exists()
    assert (data_dir / "hmanga.db").read_bytes() == b"database"
    assert (data_dir / "hmanga.db-wal").read_bytes() == b"wal"
