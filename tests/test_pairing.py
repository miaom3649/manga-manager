from __future__ import annotations

import pytest

from hmanga.database import Database
from hmanga.pairing import PairingService


def test_pair_authenticate_and_revoke(tmp_path) -> None:
    database = Database(tmp_path / "pairing.db")
    database.initialize("test")
    pairing = PairingService(database)
    session = pairing.open_session()

    with pytest.raises(PermissionError):
        pairing.pair("000000", "错误设备", "browser", "client")
    token = pairing.pair(session.code, "我的 iPhone", "Safari", "client")
    assert pairing.open_session().code != session.code
    device = pairing.authenticate(token)
    assert device is not None
    assert device.name == "我的 iPhone"
    pairing.revoke(device.id)
    assert pairing.authenticate(token) is None
    assert pairing.devices() == []


def test_closing_pair_page_invalidates_code(tmp_path) -> None:
    database = Database(tmp_path / "pairing.db")
    database.initialize("test")
    pairing = PairingService(database)
    old = pairing.open_session()
    pairing.close_session()
    new = pairing.open_session()
    assert old != new
    with pytest.raises(PermissionError):
        pairing.pair(old.code, "旧页面", "Safari", "client")
