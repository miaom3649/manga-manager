from __future__ import annotations

import re
import socket
from io import BytesIO
from ipaddress import IPv4Address, ip_address, ip_network

import qrcode
from PySide6.QtCore import QSize, Qt, QTimer, Signal
from PySide6.QtGui import QPixmap
from PySide6.QtNetwork import QNetworkInterface
from PySide6.QtWidgets import QFrame, QLabel, QListWidget, QListWidgetItem, QPushButton

from hmanga.config import DEFAULT_API_PORT
from hmanga.desktop.dialogs import confirm_action
from hmanga.desktop.windowing import FloatingCardDialog
from hmanga.i18n import tr, trf
from hmanga.pairing import PairingService


def _phone_model(user_agent: str) -> str:
    if not user_agent:
        return tr("label.unknown")
    android = re.search(r"Android[^;)]*;\s*([^;)]+?)(?:\s+Build[/;]|[;)])", user_agent, re.I)
    if android:
        return android.group(1).strip()
    if re.search(r"iPhone", user_agent, re.I):
        return "iPhone"
    if re.search(r"iPad", user_agent, re.I):
        return "iPad"
    return tr("label.unknown_phone")


class DeviceListWidget(QListWidget):
    resized = Signal()

    def resizeEvent(self, event) -> None:  # noqa: N802
        super().resizeEvent(event)
        self.resized.emit()


class DeviceDetailDialog(FloatingCardDialog):
    def __init__(self, pairing: PairingService, device_id: str, parent=None) -> None:
        super().__init__(parent, card_size=QSize(520, 430))
        self.pairing = pairing
        self.device_id = device_id
        device = pairing.device(device_id)
        if device is None:
            QTimer.singleShot(0, self.reject)
            return
        title = QLabel(device.name)
        title.setAlignment(Qt.AlignCenter)
        title.setStyleSheet("font-size: 25px; font-weight: 700;")
        details = QLabel(
            trf(
                "device.details",
                paired_at=f"{device.paired_at:%Y-%m-%d %H:%M:%S}",
                last_seen_at=f"{device.last_seen_at:%Y-%m-%d %H:%M:%S}",
                model=_phone_model(device.user_agent),
            )
        )
        details.setWordWrap(True)
        details.setTextInteractionFlags(Qt.TextSelectableByMouse)
        remove = QPushButton(tr("action.delete_device"))
        remove.setFixedHeight(46)
        remove.setStyleSheet(
            "QPushButton { background: transparent; color: #ff746c; "
            "border: 2px solid #d93025; border-radius: 10px; font-weight: 700; }"
        )
        remove.clicked.connect(self.remove_device)
        self.card_layout.addWidget(title)
        self.card_layout.addWidget(details, 1)
        self.card_layout.addWidget(remove)

    def remove_device(self) -> None:
        if not confirm_action(
            self,
            tr("confirm.delete_device_title"),
            tr("message.device_delete_effect"),
            confirm_text=tr("confirm.confirm_delete"),
            danger=True,
        ):
            return
        self.pairing.revoke(self.device_id)
        self.accept()


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
        self.setWindowTitle(tr("label.phone_pairing"))
        root = self.card_layout
        title = QLabel(tr("label.phone_pairing"))
        title.setAlignment(Qt.AlignCenter)
        title.setStyleSheet("font-size: 25px; font-weight: 700")
        root.addWidget(title)
        root.addWidget(QLabel(tr("message.same_wifi_hint")))
        address_label = QLabel(trf("pairing.address", address=self.base_address))
        address_label.setTextInteractionFlags(Qt.TextSelectableByMouse)
        root.addWidget(address_label)
        self.code = QLabel()
        self.code.setAlignment(Qt.AlignCenter)
        self.code.setStyleSheet("font-size: 34px; font-weight: 700; letter-spacing: 8px")
        root.addWidget(self.code)
        self.qr = QLabel()
        self.qr.setAlignment(Qt.AlignCenter)
        root.addWidget(self.qr)
        root.addWidget(QLabel(tr("status.paired_devices")))
        self.devices = DeviceListWidget()
        self.devices.setSpacing(0)
        self.devices.setStyleSheet(
            "QListWidget { background: transparent; border: 1px solid #9a6f7b; "
            "border-radius: 10px; padding: 0; } "
            "QListWidget::item, QListWidget::item:selected { "
            "background: transparent; border: none; }"
        )
        self.devices.itemClicked.connect(self.open_device)
        self.devices.resized.connect(lambda: QTimer.singleShot(0, self._fill_empty_device_rows))
        root.addWidget(self.devices, 1)
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
            item = QListWidgetItem()
            item.setSizeHint(QSize(0, 54))
            item.setData(256, device.id)
            self.devices.addItem(item)
            row = QLabel(device.name)
            row.setAlignment(Qt.AlignCenter)
            row.setContentsMargins(14, 0, 14, 0)
            self._style_device_row(row)
            self.devices.setItemWidget(item, row)
            if device.id == selected:
                self.devices.setCurrentItem(item)
        self._fill_empty_device_rows()

    @staticmethod
    def _style_device_row(widget) -> None:
        widget.setStyleSheet(
            "background: transparent; border: none; "
            "border-bottom: 1px solid #57474f; border-radius: 0;"
        )

    def _fill_empty_device_rows(self) -> None:
        height = self.devices.viewport().height()
        if height <= 0:
            return
        for index in range(self.devices.count() - 1, -1, -1):
            item = self.devices.item(index)
            if item.data(256) is None:
                widget = self.devices.itemWidget(item)
                self.devices.takeItem(index)
                if widget is not None:
                    widget.deleteLater()
        occupied = sum(
            self.devices.item(index).sizeHint().height() for index in range(self.devices.count())
        )
        remaining = max(0, height - occupied)
        for index in range((remaining + 53) // 54):
            placeholder = QListWidgetItem()
            placeholder.setSizeHint(QSize(0, max(1, min(54, remaining - index * 54))))
            self.devices.addItem(placeholder)
            row = QFrame()
            self._style_device_row(row)
            self.devices.setItemWidget(placeholder, row)

    def open_device(self, item: QListWidgetItem) -> None:
        device_id = item.data(256)
        if device_id is None:
            return
        DeviceDetailDialog(self.pairing, device_id, self).exec()
        self.refresh_devices(force=True)

    def done(self, result: int) -> None:
        self.timer.stop()
        self.pairing.close_session()
        super().done(result)
