from __future__ import annotations

import socket
from io import BytesIO

import qrcode
from PySide6.QtGui import QPixmap
from PySide6.QtWidgets import (
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QPushButton,
    QVBoxLayout,
)

from hlibrary.config import DEFAULT_API_PORT
from hlibrary.desktop.windowing import ScreenCenteredDialog
from hlibrary.pairing import PairingService


def local_ip() -> str:
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        sock.connect(("10.255.255.255", 1))
        return sock.getsockname()[0]
    except OSError:
        return "127.0.0.1"
    finally:
        sock.close()


class PairingDialog(ScreenCenteredDialog):
    def __init__(self, pairing: PairingService, parent=None) -> None:
        super().__init__(parent)
        self.pairing = pairing
        session = pairing.open_session()
        address = f"http://{local_ip()}:{DEFAULT_API_PORT}/?pair={session.nonce}"
        self.setWindowTitle("手机配对")
        self.resize(620, 650)
        root = QVBoxLayout(self)
        root.addWidget(QLabel("请确保手机和电脑连接同一个可信 Wi-Fi。"))
        root.addWidget(QLabel(f"访问地址：{address}"))
        code = QLabel(session.code)
        code.setStyleSheet("font-size: 34px; font-weight: 700; letter-spacing: 8px")
        root.addWidget(code)
        output = BytesIO()
        qrcode.make(address).save(output, "PNG")
        qr = QLabel()
        pixmap = QPixmap()
        pixmap.loadFromData(output.getvalue())
        qr.setPixmap(pixmap.scaled(260, 260))
        root.addWidget(qr)
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
        self.refresh()

    def refresh(self) -> None:
        self.devices.clear()
        for device in self.pairing.devices():
            status = (
                "已撤销" if device.revoked_at else f"最近访问 {device.last_seen_at:%Y-%m-%d %H:%M}"
            )
            item = QListWidgetItem(f"{device.name} · {status}\n{device.user_agent}")
            item.setData(256, device.id)
            self.devices.addItem(item)

    def revoke_selected(self) -> None:
        if item := self.devices.currentItem():
            self.pairing.revoke(item.data(256))
            self.refresh()

    def done(self, result: int) -> None:
        self.pairing.close_session()
        super().done(result)
