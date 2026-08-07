from __future__ import annotations

from datetime import UTC, datetime, timedelta

from sqlalchemy import delete, func, select, update

from hlibrary.database import Database, Notification


class NotificationService:
    def __init__(self, database: Database) -> None:
        self.database = database

    def unread_count(self) -> int:
        with self.database.session() as session:
            return (
                session.scalar(
                    select(func.count())
                    .select_from(Notification)
                    .where(Notification.read_at.is_(None))
                )
                or 0
            )

    def mark_all_read(self) -> None:
        with self.database.session() as session:
            session.execute(
                update(Notification)
                .where(Notification.read_at.is_(None))
                .values(read_at=datetime.now(UTC))
            )

    def mark_read(self, notification_id: int) -> None:
        with self.database.session() as session:
            session.execute(
                update(Notification)
                .where(Notification.id == notification_id, Notification.read_at.is_(None))
                .values(read_at=datetime.now(UTC))
            )

    def delete(self, notification_id: int) -> None:
        with self.database.session() as session:
            session.execute(delete(Notification).where(Notification.id == notification_id))

    def clear(self) -> None:
        with self.database.session() as session:
            session.execute(delete(Notification))

    def prune(self, now: datetime | None = None) -> int:
        cutoff = (now or datetime.now(UTC)) - timedelta(days=30)
        with self.database.session() as session:
            result = session.execute(delete(Notification).where(Notification.created_at < cutoff))
            return result.rowcount
