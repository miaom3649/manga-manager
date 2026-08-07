from __future__ import annotations

from datetime import UTC, datetime, timedelta

from hlibrary.database import Database, Notification
from hlibrary.notifications import NotificationService


def test_notification_read_delete_and_retention(tmp_path) -> None:
    database = Database(tmp_path / "main.db")
    database.initialize("test")
    with database.session() as session:
        session.add(Notification(kind="new", title="新通知", details_json="[]"))
        session.add(
            Notification(
                kind="old",
                title="旧通知",
                details_json="[]",
                created_at=datetime.now(UTC) - timedelta(days=31),
            )
        )
    service = NotificationService(database)
    assert service.unread_count() == 2
    assert service.prune() == 1
    service.mark_read(1)
    assert service.unread_count() == 0
    service.mark_all_read()
    assert service.unread_count() == 0
    service.clear()
