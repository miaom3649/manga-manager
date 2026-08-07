from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

from sqlalchemy import (
    DateTime,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
    create_engine,
    event,
    inspect,
    select,
    text,
)
from sqlalchemy.orm import (
    DeclarativeBase,
    Mapped,
    Session,
    mapped_column,
    relationship,
    sessionmaker,
)


class Base(DeclarativeBase):
    pass


class AppMeta(Base):
    __tablename__ = "app_meta"

    key: Mapped[str] = mapped_column(String(100), primary_key=True)
    value: Mapped[str] = mapped_column(String(500), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(UTC), nullable=False
    )


class Work(Base):
    __tablename__ = "works"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    stable_id: Mapped[str] = mapped_column(
        String(32), unique=True, default=lambda: uuid4().hex, nullable=False
    )
    kind: Mapped[str] = mapped_column(String(20), nullable=False)
    relative_path: Mapped[str] = mapped_column(String(1024), unique=True, nullable=False)
    file_name: Mapped[str] = mapped_column(String(500), nullable=False)
    number: Mapped[str | None] = mapped_column(String(100))
    title: Mapped[str | None] = mapped_column(String(1000))
    normalized_file_name: Mapped[str] = mapped_column(String(1000), default="", nullable=False)
    normalized_title: Mapped[str] = mapped_column(String(1000), default="", nullable=False)
    rating: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    fingerprint: Mapped[str | None] = mapped_column(String(64), index=True)
    file_size: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    modified_ns: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    status: Mapped[str] = mapped_column(String(30), default="ready", nullable=False)
    cover_member: Mapped[str | None] = mapped_column(String(1024))
    added_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    updated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    tags: Mapped[list[Tag]] = relationship(secondary="work_tags", back_populates="works")


class TagGroup(Base):
    __tablename__ = "tag_groups"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    normalized_name: Mapped[str] = mapped_column(String(200), unique=True, nullable=False)
    tags: Mapped[list[Tag]] = relationship(back_populates="group")


class Tag(Base):
    __tablename__ = "tags"
    __table_args__ = (UniqueConstraint("group_key", "normalized_name"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    normalized_name: Mapped[str] = mapped_column(String(200), nullable=False)
    group_id: Mapped[int | None] = mapped_column(ForeignKey("tag_groups.id", ondelete="RESTRICT"))
    # SQLite NULL values do not collide in UNIQUE constraints, so ungrouped tags
    # use zero here while grouped tags use their group id.
    group_key: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    group: Mapped[TagGroup | None] = relationship(back_populates="tags")
    works: Mapped[list[Work]] = relationship(secondary="work_tags", back_populates="tags")


class WorkTag(Base):
    __tablename__ = "work_tags"

    work_id: Mapped[int] = mapped_column(
        ForeignKey("works.id", ondelete="CASCADE"), primary_key=True
    )
    tag_id: Mapped[int] = mapped_column(ForeignKey("tags.id", ondelete="CASCADE"), primary_key=True)


class ReadingProgress(Base):
    __tablename__ = "reading_progress"

    work_id: Mapped[int] = mapped_column(
        ForeignKey("works.id", ondelete="CASCADE"), primary_key=True
    )
    page_index: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    page_offset: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    content_fingerprint: Mapped[str] = mapped_column(String(64), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(UTC), nullable=False
    )


class Device(Base):
    __tablename__ = "devices"

    id: Mapped[str] = mapped_column(String(32), primary_key=True)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    user_agent: Mapped[str] = mapped_column(String(1000), default="", nullable=False)
    token_hash: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    paired_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(UTC), nullable=False
    )
    last_seen_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(UTC), nullable=False
    )
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class DevicePreference(Base):
    __tablename__ = "device_preferences"

    device_id: Mapped[str] = mapped_column(String(32), primary_key=True)
    theme: Mapped[str] = mapped_column(String(20), default="system", nullable=False)
    reader_mode: Mapped[str] = mapped_column(String(20), default="continuous", nullable=False)
    sort_field: Mapped[str] = mapped_column(String(30), default="added", nullable=False)
    sort_descending: Mapped[int] = mapped_column(Integer, default=1, nullable=False)


class CacheEntry(Base):
    __tablename__ = "cache_entries"

    key: Mapped[str] = mapped_column(String(128), primary_key=True)
    relative_path: Mapped[str] = mapped_column(String(1024), nullable=False)
    size: Mapped[int] = mapped_column(Integer, nullable=False)
    accessed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    in_use: Mapped[int] = mapped_column(Integer, default=0, nullable=False)


class Job(Base):
    __tablename__ = "jobs"

    id: Mapped[str] = mapped_column(String(32), primary_key=True)
    kind: Mapped[str] = mapped_column(String(30), nullable=False)
    status: Mapped[str] = mapped_column(String(30), nullable=False)
    progress: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    details_json: Mapped[str] = mapped_column(Text, default="{}", nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class Notification(Base):
    __tablename__ = "notifications"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    kind: Mapped[str] = mapped_column(String(50), nullable=False, index=True)
    title: Mapped[str] = mapped_column(String(500), nullable=False)
    details_json: Mapped[str] = mapped_column(Text, default="{}", nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(UTC), nullable=False
    )
    read_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class FileObservation(Base):
    __tablename__ = "file_observations"

    relative_path: Mapped[str] = mapped_column(String(1024), primary_key=True)
    file_size: Mapped[int] = mapped_column(Integer, nullable=False)
    modified_ns: Mapped[int] = mapped_column(Integer, nullable=False)
    last_seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


def build_engine(database_path: Path):
    engine = create_engine(
        f"sqlite:///{database_path.as_posix()}",
        future=True,
        connect_args={"check_same_thread": False},
    )

    @event.listens_for(engine, "connect")
    def set_sqlite_pragmas(dbapi_connection, _connection_record) -> None:
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA journal_mode=WAL")
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.execute("PRAGMA busy_timeout=5000")
        cursor.close()

    return engine


class Database:
    def __init__(self, database_path: Path) -> None:
        self.path = database_path
        self.engine = build_engine(database_path)
        self.sessions = sessionmaker(bind=self.engine, expire_on_commit=False, class_=Session)

    def initialize(self, version: str) -> None:
        Base.metadata.create_all(self.engine)
        self._upgrade_schema()
        self._backfill_search_columns()
        with self.session() as session:
            row = session.scalar(select(AppMeta).where(AppMeta.key == "app_version"))
            if row is None:
                session.add(AppMeta(key="app_version", value=version))
            else:
                row.value = version
                row.updated_at = datetime.now(UTC)

    def _upgrade_schema(self) -> None:
        """Add compatible columns for databases created by earlier prototypes."""
        existing = {column["name"] for column in inspect(self.engine).get_columns("works")}
        additions = {
            "fingerprint": "VARCHAR(64)",
            "file_size": "INTEGER NOT NULL DEFAULT 0",
            "modified_ns": "INTEGER NOT NULL DEFAULT 0",
            "status": "VARCHAR(30) NOT NULL DEFAULT 'ready'",
            "cover_member": "VARCHAR(1024)",
            "added_at": "DATETIME",
            "updated_at": "DATETIME",
            "normalized_file_name": "VARCHAR(1000) NOT NULL DEFAULT ''",
            "normalized_title": "VARCHAR(1000) NOT NULL DEFAULT ''",
            "stable_id": "VARCHAR(32)",
        }
        with self.engine.begin() as connection:
            for name, definition in additions.items():
                if name not in existing:
                    connection.execute(text(f"ALTER TABLE works ADD COLUMN {name} {definition}"))
            connection.execute(
                text("CREATE INDEX IF NOT EXISTS ix_works_fingerprint ON works (fingerprint)")
            )
            connection.execute(
                text(
                    "CREATE INDEX IF NOT EXISTS ix_works_normalized_file_name "
                    "ON works (normalized_file_name)"
                )
            )
            connection.execute(
                text("CREATE UNIQUE INDEX IF NOT EXISTS ix_works_stable_id ON works (stable_id)")
            )
            connection.execute(
                text(
                    "CREATE INDEX IF NOT EXISTS ix_works_normalized_title "
                    "ON works (normalized_title)"
                )
            )

    def _backfill_search_columns(self) -> None:
        from hlibrary.text import normalize_text

        with self.session() as session:
            for work in session.scalars(select(Work)):
                if not work.stable_id:
                    work.stable_id = uuid4().hex
                expected_file = normalize_text(work.file_name)
                expected_title = normalize_text(work.title)
                if work.normalized_file_name != expected_file:
                    work.normalized_file_name = expected_file
                if work.normalized_title != expected_title:
                    work.normalized_title = expected_title

    @contextmanager
    def session(self) -> Iterator[Session]:
        session = self.sessions()
        try:
            yield session
            session.commit()
        except Exception:
            session.rollback()
            raise
        finally:
            session.close()

    def close(self) -> None:
        self.engine.dispose()

    def reopen(self) -> None:
        self.engine = build_engine(self.path)
        self.sessions = sessionmaker(bind=self.engine, expire_on_commit=False, class_=Session)
