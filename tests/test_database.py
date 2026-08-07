from pathlib import Path

from sqlalchemy import select

from hlibrary.database import AppMeta, Database


def test_database_initialization(tmp_path: Path) -> None:
    database = Database(tmp_path / "test.db")
    database.initialize("test-version")
    with database.session() as session:
        version = session.scalar(select(AppMeta).where(AppMeta.key == "app_version"))
        assert version is not None
        assert version.value == "test-version"
    database.close()
