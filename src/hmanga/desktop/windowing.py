from __future__ import annotations

from PySide6.QtCore import QEvent, QObject, QPoint, QPropertyAnimation, QSize, Qt, QTimer
from PySide6.QtGui import (
    QColor,
    QCursor,
    QGuiApplication,
    QMouseEvent,
    QPainter,
    QPaintEvent,
    QShowEvent,
)
from PySide6.QtWidgets import (
    QApplication,
    QDialog,
    QFrame,
    QGraphicsDropShadowEffect,
    QVBoxLayout,
    QWidget,
)


def center_on_screen(widget: QWidget) -> None:
    parent = widget.parentWidget()
    screen = getattr(widget, "_center_screen_hint", None)
    if screen is None and parent is not None and parent.screen() is not None:
        screen = parent.screen()
    screen = screen or QGuiApplication.screenAt(QCursor.pos()) or QGuiApplication.primaryScreen()
    if screen is None:
        return
    frame = widget.frameGeometry()
    frame.moveCenter(screen.availableGeometry().center())
    widget.move(frame.topLeft())


class ScreenCenteredDialog(QDialog):
    """Center a dialog in the usable area of the relevant physical screen."""

    def __init__(self, parent=None) -> None:
        # Remember which monitor the caller belongs to, but do not create a native
        # owner/child relationship. Some window managers otherwise override the
        # requested screen-center position and move related dialogs as a group.
        self._center_screen_hint = parent.screen() if parent is not None else None
        super().__init__(None)

    def showEvent(self, event: QShowEvent) -> None:  # noqa: N802
        super().showEvent(event)
        QTimer.singleShot(0, self.center_on_screen)

    def center_on_screen(self) -> None:
        center_on_screen(self)


class FloatingCardDialog(QDialog):
    """Reusable dimmed overlay containing a centered card inside its owner window."""

    def __init__(
        self,
        parent=None,
        *,
        card_size: QSize | None = None,
        backdrop_alpha: int = 190,
    ) -> None:
        self._overlay_parent = parent
        self._preferred_card_size = card_size or QSize(560, 520)
        self._backdrop_color = QColor(0, 0, 0, backdrop_alpha)
        # A captured owner background gives the same dimmed-overlay appearance
        # without relying on native translucent windows. Enabling
        # WA_TranslucentBackground on a QDialog subclass can make PySide lose
        # the Python wrapper after Windows recreates the native window.
        self._backdrop_snapshot = parent.grab() if parent is not None else None
        self.warning_shake = False
        self._shake_animation: QPropertyAnimation | None = None
        super().__init__(parent)
        if parent is not None:
            parent.installEventFilter(self)
        self.setProperty("skipScreenCentering", True)
        self.setWindowFlags(Qt.SubWindow | Qt.FramelessWindowHint)
        self.setAttribute(Qt.WA_StyledBackground, True)
        self.setObjectName("floatingCardOverlay")
        # Keep the native surface transparent and paint the dimming layer
        # ourselves. Qt's stylesheet alpha is handled differently by the
        # Windows and X11 compositors when this dialog is a native subwindow.
        self.setStyleSheet("QDialog#floatingCardOverlay { background: transparent; }")

        overlay = QVBoxLayout(self)
        overlay.setContentsMargins(24, 24, 24, 24)
        self.card = QFrame()
        self.card.setObjectName("floatingCard")
        self.card.setFixedSize(self._preferred_card_size)
        self.card.setStyleSheet(
            # Do not use palette(base) here: under a Qt stylesheet it can still
            # be the operating system's grey palette.  Let the card inherit the
            # same application background as all of its child widgets.
            "QFrame#floatingCard { border: 1px solid #57474f; border-radius: 22px; }"
        )
        shadow = QGraphicsDropShadowEffect(self.card)
        shadow.setBlurRadius(36)
        shadow.setOffset(0, 12)
        shadow.setColor(QColor(0, 0, 0, 190))
        self.card.setGraphicsEffect(shadow)
        overlay.addWidget(self.card, 0, Qt.AlignCenter)
        self.card_layout = QVBoxLayout(self.card)
        self.card_layout.setContentsMargins(26, 26, 26, 22)

    def showEvent(self, event: QShowEvent) -> None:  # noqa: N802
        super().showEvent(event)
        self._sync_to_parent()
        if self.warning_shake:
            QTimer.singleShot(40, self._start_warning_shake)

    def _start_warning_shake(self) -> None:
        origin = self.card.pos()
        animation = QPropertyAnimation(self.card, b"pos", self)
        animation.setDuration(360)
        for progress, offset in (
            (0.0, 0),
            (0.14, -11),
            (0.28, 10),
            (0.43, -8),
            (0.58, 7),
            (0.73, -4),
            (0.86, 3),
            (1.0, 0),
        ):
            animation.setKeyValueAt(progress, origin + QPoint(offset, 0))
        animation.start()
        self._shake_animation = animation

    def resizeEvent(self, event) -> None:  # noqa: N802
        super().resizeEvent(event)
        self._resize_card_to_overlay()

    def paintEvent(self, event: QPaintEvent) -> None:  # noqa: N802
        super().paintEvent(event)
        painter = QPainter(self)
        if self._backdrop_snapshot is not None and not self._backdrop_snapshot.isNull():
            painter.drawPixmap(self.rect(), self._backdrop_snapshot)
        else:
            painter.fillRect(self.rect(), self.palette().window())
        painter.fillRect(self.rect(), self._backdrop_color)

    def eventFilter(self, watched, event) -> bool:  # noqa: N802
        if watched is self._overlay_parent and event.type() in {
            QEvent.Type.Resize,
            QEvent.Type.Show,
        }:
            self._sync_to_parent()
        return super().eventFilter(watched, event)

    def _sync_to_parent(self) -> None:
        if self._overlay_parent is not None:
            self.setGeometry(self._overlay_parent.rect())
            self._resize_card_to_overlay()
            self.raise_()
            return
        screen = self.screen()
        if screen is not None:
            self.setGeometry(screen.availableGeometry())

    def _resize_card_to_overlay(self) -> None:
        margins = self.layout().contentsMargins()
        available_width = max(1, self.width() - margins.left() - margins.right())
        available_height = max(1, self.height() - margins.top() - margins.bottom())
        self.card.setFixedSize(
            min(self._preferred_card_size.width(), available_width),
            min(self._preferred_card_size.height(), available_height),
        )

    def mousePressEvent(self, event: QMouseEvent) -> None:  # noqa: N802
        # Some child widgets (notably preview labels) deliberately leave a
        # mouse event unaccepted, so Qt propagates it to the dialog. Treat the
        # event as a backdrop click only when its position is truly outside
        # the visible card, rather than merely because it reached this parent.
        if not self.card.geometry().contains(event.position().toPoint()):
            self.reject()
            event.accept()
            return
        super().mousePressEvent(event)


class DialogCenteringFilter(QObject):
    def eventFilter(self, watched, event) -> bool:  # noqa: N802
        if (
            isinstance(watched, QDialog)
            and event.type() == QEvent.Type.Show
            and not watched.property("skipScreenCentering")
        ):
            QTimer.singleShot(0, lambda dialog=watched: center_on_screen(dialog))
        return super().eventFilter(watched, event)


def install_dialog_centering(app: QApplication) -> DialogCenteringFilter:
    event_filter = DialogCenteringFilter(app)
    app.installEventFilter(event_filter)
    return event_filter
