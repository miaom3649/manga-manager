from __future__ import annotations

import hashlib
import secrets
import threading
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime

from sqlalchemy import delete, select

from hmanga.database import Database, Device, DevicePreference


def token_hash(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


@dataclass(frozen=True, slots=True)
class PairingSession:
    code: str


class PairingService:
    def __init__(self, database: Database) -> None:
        self.database = database
        self._lock = threading.Lock()
        self._session: PairingSession | None = None
        self._last_code = ""
        self._failed_attempts: dict[str, int] = {}

    def _new_session(self) -> PairingSession:
        while True:
            code = f"{secrets.randbelow(1_000_000):06d}"
            if code != self._last_code:
                self._last_code = code
                return PairingSession(code=code)

    def open_session(self) -> PairingSession:
        with self._lock:
            if self._session is None:
                self._session = self._new_session()
            return self._session

    def close_session(self) -> None:
        with self._lock:
            self._session = None
            self._failed_attempts.clear()

    def pair(self, code: str, name: str, user_agent: str, client: str) -> str:
        with self._lock:
            attempts = self._failed_attempts.get(client, 0)
            if attempts >= 10:
                raise PermissionError("尝试次数过多，请重新打开配对页面")
            session = self._session
            if session is None or not secrets.compare_digest(session.code, code):
                self._failed_attempts[client] = attempts + 1
                raise PermissionError("配对码无效")
            # Each successful pairing rotates the short code immediately. The
            # open desktop card notices this session change and redraws its QR.
            self._session = self._new_session()
            self._failed_attempts.clear()
        token = secrets.token_urlsafe(48)
        with self.database.session() as database_session:
            database_session.add(
                Device(
                    id=uuid.uuid4().hex,
                    name=name.strip() or "未命名设备",
                    user_agent=user_agent[:1000],
                    token_hash=token_hash(token),
                )
            )
        return token

    def authenticate(self, token: str) -> Device | None:
        if not token:
            return None
        with self.database.session() as session:
            device = session.scalar(select(Device).where(Device.token_hash == token_hash(token)))
            if device is None or device.revoked_at is not None:
                return None
            device.last_seen_at = datetime.now(UTC)
            return device

    def devices(self) -> list[Device]:
        with self.database.session() as session:
            return list(
                session.scalars(
                    select(Device)
                    .where(Device.revoked_at.is_(None))
                    .order_by(Device.paired_at.desc())
                )
            )

    def revoke(self, device_id: str) -> None:
        with self.database.session() as session:
            device = session.get(Device, device_id)
            if device is not None:
                session.execute(delete(DevicePreference).where(DevicePreference.device_id == device_id))
                session.delete(device)

    def revoke_token(self, token: str) -> None:
        with self.database.session() as session:
            device = session.scalar(select(Device).where(Device.token_hash == token_hash(token)))
            if device is not None:
                session.execute(
                    delete(DevicePreference).where(DevicePreference.device_id == device.id)
                )
                session.delete(device)
