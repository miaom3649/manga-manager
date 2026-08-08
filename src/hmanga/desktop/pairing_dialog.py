from __future__ import annotations

import socket
from io import BytesIO
from ipaddress import IPv4Address, ip_address, ip_network

import qrcode
from PySide6.QtCore import QSize, Qt, QTimer
from PySide6.QtGui import QPixmap
from PySide6.QtNetwork import QNetworkInterface
from PySide6.QtWidgets import (
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QPushButton,
    QVBoxLayout,
)

from hmanga.config import DEFAULT_API_PORT
from hmanga.desktop.windowing import FloatingCardDialog
from hmanga.pairing import PairingService


def _pairing_ip_score(value: str) -> int:
    try:
        address = ip_address(value)
    except ValueError:
        return -1
    if not isinstance(address, IPv4Address):
        return -1
    if address.is_loopback or address.is_link_local or address.is_multicast:
        return -1
    if address in ip_network("198.18.0.0/15"):
        return -1
    if address in ip_network("192.168.0.0/16"):
        return 400
    if address in ip_network("172.16.0.0/12"):
        return 300
    if address in ip_network("10.0.0.0/8"):
        return 10 if address in ip_network("10.0.2.0/24") else 200
    return 100


def choose_pairing_ip(candidates: list[str]) -> str:
    usable = [(value, _pairing_ip_score(value)) for value in candidates]
    usable = [(value, score) for value, score in usable if score >= 0]
    return max(usable, key=lambda item: (item[1], item[0]))[0] if usable else "127.0.0.1"


def local_ip() -> str:
    candidates = [address.toString() for address in QNetworkInterface.allAddresses()]
    try:
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    except OSError:
        sock = None
    if sock is not None:
        try:
            sock.connect(("10.255.255.255", 1))
            candidates.append(sock.getsockname()[0])
        except OSError:
            pass
        finally:
            sock.close()
    return choose_pairing_ip(candidates)


class PairingDialog(FloatingCardDialog):
    def __init__(self, pairing: PairingService, parent=None) -> None:
        super().__init__(parent, card_size=QSize(620, 680))
        self.pairing = pairing
        self.base_address = f"http://{local_ip()}:{DEFAULT_API_PORT}/"
        self._shown_code = ""
        self._device_signature: tuple[tuple[str, str], ...] = ()
        self.setWindowTitle("手机配对")
        root = self.card_layout
        title = QLabel("手机配对")
        title.setAlignment(Qt.AlignCenter)
        title.setStyleSheet("font-size: 25px; font-weight: 700")
        root.addWidget(title)
        root.addWidget(QLabel("请确保手机和电脑连接同一个可信 Wi-Fi。"))
        address_label = QLabel(f"访问地址：{self.base_address}")
        address_label.setTextInteractionFlags(Qt.TextSelectableByMouse)
        root.addWidget(address_label)
        self.code = QLabel()
        self.code.setAlignment(Qt.AlignCenter)
        self.code.setStyleSheet("font-size: 34px; font-weight: 700; letter-spacing: 8px")
        root.addWidget(self.code)
        self.qr = QLabel()
        self.qr.setAlignment(Qt.AlignCenter)
        root.addWidget(self.qr)
        root.addWidget(QLabel("已配对设备"))
        self.devices = QListWidget()
        root.addWidget(self.devices, 1)
        row = QHBoxLayout()
        revoke = QPushButton("撤销所选设备")
        revoke.clicked.connect(self.revoke_selected)
        close = QPushButton("关闭配对页面")
        close.clicked.connect(self.accept)
        row.addWidget(revoke)
        row.addStretch(1)
        row.addWidget(close)
        root.addLayout(row)
        self.refresh_session()
        self.refresh_devices(force=True)
        self.timer = QTimer(self)
        self.timer.setInterval(500)
        self.timer.timeout.connect(self.refresh_live_state)
        self.timer.start()

    def refresh_live_state(self) -> None:
        self.refresh_session()
        self.refresh_devices()

    def refresh_session(self) -> None:
        session = self.pairing.open_session()
        if session.code == self._shown_code:
            return
        self._shown_code = session.code
        self.code.setText(session.code)
        output = BytesIO()
        qrcode.make(f"{self.base_address}?code={session.code}").save(output, "PNG")
        pixmap = QPixmap()
        pixmap.loadFromData(output.getvalue())
        self.qr.setPixmap(pixmap.scaled(230, 230, Qt.KeepAspectRatio, Qt.SmoothTransformation))

    def refresh_devices(self, *, force: bool = False) -> None:
        devices = self.pairing.devices()
        signature = tuple((device.id, device.last_seen_at.isoformat()) for device in devices)
        if not force and signature == self._device_signature:
            return
        self._device_signature = signature
        selected = self.devices.currentItem().data(256) if self.devices.currentItem() else None
        self.devices.clear()
        for device in devices:
            item = QListWidgetItem(
                f"{device.name} · 最近访问 {device.last_seen_at:%Y-%m-%d %H:%M}\n"
                f"{device.user_agent}"
            )
            item.setData(256, device.id)
            self.devices.addItem(item)
            if device.id == selected:
                self.devices.setCurrentItem(item)

    def revoke_selected(self) -> None:
        if item := self.devices.currentItem():
            self.pairing.revoke(item.data(256))
            self.refresh_devices(force=True)

    def done(self, result: int) -> None:
        self.timer.stop()
        self.pairing.close_session()
        super().done(result)
