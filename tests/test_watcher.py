from __future__ import annotations

import threading

from watchdog.events import FileClosedEvent, FileCreatedEvent, FileOpenedEvent

from hmanga.watcher import _DebouncedHandler


def test_read_only_events_do_not_schedule_scan() -> None:
    calls: list[str] = []
    handler = _DebouncedHandler(lambda: calls.append("scan"), delay=0)

    handler.on_any_event(FileOpenedEvent("459808.zip"))
    handler.on_any_event(FileClosedEvent("459808.zip"))

    assert calls == []


def test_change_event_schedules_scan() -> None:
    called = threading.Event()
    handler = _DebouncedHandler(called.set, delay=0)

    handler.on_any_event(FileCreatedEvent("459808.zip"))

    assert called.wait(timeout=1)
