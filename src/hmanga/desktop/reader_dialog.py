from __future__ import annotations

from io import BytesIO

from PIL import Image
from PySide6.QtCore import QEasingCurve, QEvent, QPoint, QPropertyAnimation, Qt, QTimer, Signal
from PySide6.QtGui import QCursor, QImage, QKeyEvent, QMouseEvent, QPixmap, QResizeEvent
from PySide6.QtWidgets import (
    QAbstractSpinBox,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QScrollArea,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

from hmanga.database import Work
from hmanga.desktop.windowing import ScreenCenteredDialog
from hmanga.i18n import tr, trf
from hmanga.reader import ReaderService


def pixmap_from_bytes(data: bytes) -> QPixmap:
    with Image.open(BytesIO(data)) as source:
        image = source.convert("RGBA")
        raw = image.tobytes("raw", "RGBA")
        qimage = QImage(raw, image.width, image.height, QImage.Format_RGBA8888).copy()
    return QPixmap.fromImage(qimage)


class PanLabel(QLabel):
    clicked = Signal()

    def __init__(self, scroll: QScrollArea) -> None:
        super().__init__()
        self.scroll = scroll
        self.last_position: QPoint | None = None
        self.press_position: QPoint | None = None
        self.dragged = False
        self.setCursor(Qt.OpenHandCursor)

    def mousePressEvent(self, event: QMouseEvent) -> None:  # noqa: N802
        if event.button() == Qt.LeftButton:
            self.last_position = event.globalPosition().toPoint()
            self.press_position = self.last_position
            self.dragged = False
            self.setCursor(Qt.ClosedHandCursor)

    def mouseMoveEvent(self, event: QMouseEvent) -> None:  # noqa: N802
        if self.last_position is None:
            return
        current = event.globalPosition().toPoint()
        if self.press_position is not None:
            self.dragged = (current - self.press_position).manhattanLength() > 5
        delta = current - self.last_position
        self.scroll.horizontalScrollBar().setValue(
            self.scroll.horizontalScrollBar().value() - delta.x()
        )
        self.scroll.verticalScrollBar().setValue(
            self.scroll.verticalScrollBar().value() - delta.y()
        )
        self.last_position = current

    def mouseReleaseEvent(self, event: QMouseEvent) -> None:  # noqa: N802
        clicked = event.button() == Qt.LeftButton and not self.dragged
        self.last_position = None
        self.press_position = None
        self.dragged = False
        self.setCursor(Qt.OpenHandCursor)
        if clicked:
            self.clicked.emit()


class ReaderTitleBar(QWidget):
    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.drag_offset: QPoint | None = None
        self.setCursor(Qt.SizeAllCursor)

    def mousePressEvent(self, event: QMouseEvent) -> None:  # noqa: N802
        if event.button() == Qt.LeftButton:
            handle = self.window().windowHandle()
            if handle is None or not handle.startSystemMove():
                self.drag_offset = (
                    event.globalPosition().toPoint() - self.window().frameGeometry().topLeft()
                )

    def mouseMoveEvent(self, event: QMouseEvent) -> None:  # noqa: N802
        if self.drag_offset is not None and not self.window().isMaximized():
            self.window().move(event.globalPosition().toPoint() - self.drag_offset)

    def mouseReleaseEvent(self, event: QMouseEvent) -> None:  # noqa: N802
        self.drag_offset = None

    def mouseDoubleClickEvent(self, event: QMouseEvent) -> None:  # noqa: N802
        if event.button() == Qt.LeftButton:
            if self.window().isMaximized():
                self.window().showNormal()
            else:
                self.window().showMaximized()


class ReaderDialog(ScreenCenteredDialog):
    TITLE_BAR_HEIGHT = 68
    TOOLBAR_HEIGHT = 72

    def __init__(self, work: Work, reader: ReaderService, parent=None) -> None:
        super().__init__(parent)
        self.work = work
        self.reader = reader
        self.members = reader.members(work)
        saved_progress = reader.progress(work)
        self.resume_page_index = saved_progress.page_index if saved_progress else None
        self.resume_page_offset = saved_progress.page_offset if saved_progress else 0
        self.page_index = 0
        self.zoom = 1.0
        self.wheel_delta = 0
        self._progress_saved = False
        self.continuous_labels: list[QLabel] = []
        self.setWindowTitle(work.title or work.file_name)
        self.setWindowFlags(Qt.Dialog | Qt.FramelessWindowHint)
        self.setObjectName("readerDialog")
        self.setStyleSheet(
            "#readerDialog { border: 1px solid palette(mid); background: palette(window); }"
        )
        self.resize(1050, 800)
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        self.title_bar = ReaderTitleBar(self)
        self.title_bar.setObjectName("readerTitleBar")
        self.title_bar.setFixedHeight(self.TITLE_BAR_HEIGHT)
        self.title_bar.setStyleSheet(
            "QWidget#readerTitleBar { background: transparent; border: none; } "
            "QPushButton#readerBackBlock, QLabel#readerTitleBlock { "
            "background: rgba(17, 17, 17, 150); color: white; border: none; "
            "border-radius: 10px; padding: 0 12px; } "
            "QPushButton#readerBackBlock:hover { background: rgba(17, 17, 17, 205); }"
        )
        title_layout = QHBoxLayout(self.title_bar)
        title_layout.setContentsMargins(12, 8, 12, 8)
        back = QPushButton("←")
        back.setObjectName("readerBackBlock")
        back.setToolTip(tr("action.back_to_detail"))
        back.setFixedSize(46, 42)
        back.clicked.connect(self.accept)
        title = QLabel(work.title or work.file_name.rsplit(".", 1)[0])
        title.setObjectName("readerTitleBlock")
        title.setAlignment(Qt.AlignCenter)
        title.setMinimumSize(240, 42)
        title.setMaximumWidth(600)
        title.setStyleSheet("font-size: 17px; font-weight: 700;")
        title.setAttribute(Qt.WA_TransparentForMouseEvents)
        title_layout.addWidget(back)
        title_layout.addStretch(1)
        title_layout.addWidget(title)
        title_layout.addStretch(1)
        title_layout.addSpacing(46)

        self.toolbar_bar = QWidget(self)
        self.toolbar_bar.setObjectName("readerToolbarBar")
        self.toolbar_bar.setFixedHeight(self.TOOLBAR_HEIGHT)
        self.toolbar_bar.setStyleSheet(
            "QWidget#readerToolbarBar { background: transparent; border: none; } "
            'QLabel#readerInfoBlock, QPushButton[readerBlock="true"], '
            "QSpinBox#readerJumpBlock { "
            "background: rgba(17, 17, 17, 150); color: white; border: none; "
            "border-radius: 10px; padding: 0 12px; } "
            'QPushButton[readerBlock="true"]:hover, '
            "QSpinBox#readerJumpBlock:hover, QSpinBox#readerJumpBlock:focus { "
            "background: rgba(17, 17, 17, 205); color: white; border: none; } "
        )
        toolbar = QHBoxLayout(self.toolbar_bar)
        toolbar.setContentsMargins(12, 8, 12, 8)
        toolbar.setSpacing(8)
        self.position = QLabel()
        self.position.setObjectName("readerInfoBlock")
        self.position.setFixedSize(70, 40)
        self.position.setAlignment(Qt.AlignCenter)
        self.active_mode = self.reader.preferred_mode()
        if self.active_mode not in {"single", "continuous"}:
            self.active_mode = "continuous"
        self.mode = QPushButton()
        self.mode.setProperty("readerBlock", True)
        self.mode.setFixedSize(124, 40)
        self._update_mode_button_text()
        self.mode.clicked.connect(self.toggle_mode)
        smaller = QPushButton("−")
        smaller.setProperty("readerBlock", True)
        smaller.setFixedSize(44, 40)
        smaller.clicked.connect(lambda: self.change_zoom(0.9))
        larger = QPushButton("＋")
        larger.setProperty("readerBlock", True)
        larger.setFixedSize(44, 40)
        larger.clicked.connect(lambda: self.change_zoom(1.1))
        fit = QPushButton(tr("label.fit_to_size"))
        fit.setProperty("readerBlock", True)
        fit.setMinimumSize(112, 40)
        fit.clicked.connect(self.fit_size)
        self.jump = QSpinBox()
        self.jump.setObjectName("readerJumpBlock")
        self.jump.setMinimumSize(78, 40)
        self.jump.setRange(1, max(1, len(self.members)))
        self.jump.setButtonSymbols(QAbstractSpinBox.ButtonSymbols.NoButtons)
        self.jump.valueChanged.connect(lambda value: self.go_page(value - 1))
        self.jump.editingFinished.connect(self._page_input_finished)
        toolbar.addStretch(1)
        for widget in (
            self.position,
            self.mode,
            smaller,
            larger,
            fit,
            self.jump,
        ):
            toolbar.addWidget(widget)
        toolbar.addStretch(1)
        self.scroll = QScrollArea()
        self.scroll.setWidgetResizable(True)
        self.scroll.viewport().installEventFilter(self)
        self._content_press_position: QPoint | None = None
        self.image = PanLabel(self.scroll)
        self.image.clicked.connect(self._toggle_chrome_from_content)
        self.image.setAlignment(Qt.AlignCenter)
        self.scroll.setWidget(self.image)
        self.scroll.verticalScrollBar().valueChanged.connect(self.continuous_scrolled)
        root.addWidget(self.scroll, 1)

        self._chrome_visible = True
        self.title_animation = QPropertyAnimation(self.title_bar, b"pos", self)
        self.toolbar_animation = QPropertyAnimation(self.toolbar_bar, b"pos", self)
        for animation in (self.title_animation, self.toolbar_animation):
            animation.setDuration(220)
            animation.setEasingCurve(QEasingCurve.Type.InOutCubic)
        self.chrome_hide_timer = QTimer(self)
        self.chrome_hide_timer.setSingleShot(True)
        self.chrome_hide_timer.setInterval(5000)
        self.chrome_hide_timer.timeout.connect(self._hide_chrome_if_idle)
        self.proximity_timer = QTimer(self)
        self.proximity_timer.setInterval(100)
        self.proximity_timer.timeout.connect(self._check_panel_proximity)
        self.proximity_timer.start()
        self.chrome_hide_timer.start()
        self.resume = QPushButton(tr("label.resume_last_position"), self)
        self.resume.setStyleSheet(
            "QPushButton { background: rgba(17, 17, 17, 150); color: white; "
            "border: none; border-radius: 10px; padding: 8px 14px; } "
            "QPushButton:hover { background: rgba(17, 17, 17, 205); }"
        )
        self.resume.setMinimumWidth(self.resume.sizeHint().width() + 24)
        self.resume.setMinimumHeight(self.resume.sizeHint().height() + 8)
        self.resume.clicked.connect(self.resume_progress)
        self.resume.hide()
        QTimer.singleShot(0, self._layout_chrome)
        QTimer.singleShot(0, self._initial_render)

    def _initial_render(self) -> None:
        self.mode_changed()
        if self.resume_page_index is not None and self.resume_page_index > 0:
            self.resume.show()
            self.resume.move(24, self.TITLE_BAR_HEIGHT + 10)
            QTimer.singleShot(5000, self.resume.hide)

    def resume_progress(self) -> None:
        if self.resume_page_index is not None:
            self.go_page(self.resume_page_index)
            if self.active_mode == "continuous" and self.continuous_labels:
                # 图片懒加载会改变前面页面的高度，连续校正几次，确保从当前页
                # 向前或向后跳转都能稳定落在启动时保存的位置。
                for delay in (0, 50, 150):
                    QTimer.singleShot(delay, self._scroll_to_resume_position)
        self.resume.hide()

    def _scroll_to_resume_position(self) -> None:
        if self.resume_page_index is None or not self.continuous_labels:
            return
        index = min(self.resume_page_index, len(self.continuous_labels) - 1)
        label = self.continuous_labels[index]
        offset = int(label.height() * min(self.resume_page_offset, 10_000) / 10_000)
        self.scroll.verticalScrollBar().setValue(label.y() + offset)

    def render(self) -> None:
        if not self.members:
            self.image.setText(tr("label.archive_has_no_readable_images"))
            return
        try:
            data = self.reader.page(self.work, self.members[self.page_index])
            pixmap = pixmap_from_bytes(data)
        except Exception as exc:
            self.image.setText(trf("reader.page_unreadable", page=self.page_index + 1, error=exc))
            self.position.setText(f"{self.page_index + 1}/{len(self.members)}")
            return
        pixmap = self._scaled_to_viewport(pixmap)
        self.image.setPixmap(pixmap)
        self._update_position_controls()

    def _update_mode_button_text(self) -> None:
        self.mode.setText(
            tr("label.vertical_continuous")
            if self.active_mode == "continuous"
            else tr("label.single_page_reading")
        )

    def toggle_mode(self) -> None:
        next_mode = "single" if self.active_mode == "continuous" else "continuous"
        self.mode_changed(next_mode)

    def mode_changed(self, next_mode: str | None = None) -> None:
        if self.active_mode == "continuous" and self.continuous_labels:
            self.page_index = self._detect_continuous_page()
        if next_mode is not None:
            self.active_mode = next_mode
        self._update_mode_button_text()
        self.reader.set_preferred_mode(self.active_mode)
        if self.active_mode == "continuous":
            self.build_continuous()
        else:
            self.scroll.takeWidget()
            self.image = PanLabel(self.scroll)
            self.image.clicked.connect(self._toggle_chrome_from_content)
            self.image.setAlignment(Qt.AlignCenter)
            self.scroll.setWidget(self.image)
            self.render()

    def build_continuous(self) -> None:
        self.scroll.takeWidget()
        container = QWidget()
        layout = QVBoxLayout(container)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(8)
        self.continuous_labels = []
        for index, member in enumerate(self.members):
            label = PanLabel(self.scroll)
            label.clicked.connect(self._toggle_chrome_from_content)
            label.setText(trf("reader.preparing_page", page=index + 1, member=member))
            label.setAlignment(Qt.AlignCenter)
            label.setMinimumHeight(700)
            label.setProperty("page_index", index)
            label.setProperty("loaded", False)
            layout.addWidget(label)
            self.continuous_labels.append(label)
        self.scroll.setWidget(container)
        QTimer.singleShot(0, self._position_continuous_at_current_page)

    def _position_continuous_at_current_page(self) -> None:
        if self.continuous_labels:
            label = self.continuous_labels[self.page_index]
            self.scroll.verticalScrollBar().setValue(label.y())
        self.update_continuous_pages()

    def continuous_scrolled(self) -> None:
        if self.active_mode != "continuous":
            return
        self.update_continuous_pages()

    def update_continuous_pages(self) -> None:
        if not self.continuous_labels:
            return
        top = self.scroll.verticalScrollBar().value()
        height = self.scroll.viewport().height()
        for label in self.continuous_labels:
            label_top = label.y()
            label_bottom = label_top + label.height()
            visible_nearby = label_bottom >= top - height and label_top <= top + height * 2
            if visible_nearby and not label.property("loaded"):
                index = int(label.property("page_index"))
                try:
                    pixmap = self._scaled_to_viewport(
                        pixmap_from_bytes(self.reader.page(self.work, self.members[index]))
                    )
                    label.setPixmap(pixmap)
                    label.setFixedHeight(pixmap.height())
                    label.setProperty("loaded", True)
                except Exception as exc:
                    label.setText(trf("reader.page_failed", page=index + 1, error=exc))
            elif not visible_nearby and label.property("loaded"):
                label.clear()
                label.setText(trf("reader.page_number", page=int(label.property("page_index")) + 1))
                label.setFixedHeight(700)
                label.setProperty("loaded", False)
        self.page_index = self._detect_continuous_page()
        self._update_position_controls()

    def _detect_continuous_page(self) -> int:
        if not self.continuous_labels:
            return self.page_index
        center = self.scroll.verticalScrollBar().value() + self.scroll.viewport().height() // 2
        return min(
            range(len(self.continuous_labels)),
            key=lambda index: abs(
                self.continuous_labels[index].y()
                + self.continuous_labels[index].height() // 2
                - center
            ),
        )

    def _update_position_controls(self) -> None:
        self.position.setText(f"{self.page_index + 1}/{len(self.members)}")
        self.jump.blockSignals(True)
        self.jump.setValue(self.page_index + 1)
        self.jump.blockSignals(False)

    def go_page(self, index: int) -> None:
        if not self.members:
            return
        self.page_index = min(max(index, 0), len(self.members) - 1)
        if self.active_mode == "continuous" and self.continuous_labels:
            self.scroll.verticalScrollBar().setValue(self.continuous_labels[self.page_index].y())
        else:
            self.render()

    def previous_page(self) -> None:
        self.go_page(self.page_index - 1)

    def next_page(self) -> None:
        self.go_page(self.page_index + 1)

    def change_zoom(self, multiplier: float) -> None:
        self.zoom = min(4.0, max(0.2, self.zoom * multiplier))
        if self.active_mode == "continuous":
            for label in self.continuous_labels:
                label.setProperty("loaded", False)
            self.update_continuous_pages()
        else:
            self.render()

    def _scaled_to_viewport(self, pixmap: QPixmap) -> QPixmap:
        viewport = self.scroll.viewport().size()
        fitted = pixmap.scaled(
            max(1, viewport.width()),
            max(1, viewport.height()),
            Qt.KeepAspectRatio,
            Qt.SmoothTransformation,
        )
        if self.zoom == 1.0:
            return fitted
        return fitted.scaled(
            max(1, int(fitted.width() * self.zoom)),
            max(1, int(fitted.height() * self.zoom)),
            Qt.KeepAspectRatio,
            Qt.SmoothTransformation,
        )

    def fit_size(self) -> None:
        self.zoom = 1.0
        if self.active_mode == "continuous":
            for label in self.continuous_labels:
                label.setProperty("loaded", False)
            self.update_continuous_pages()
        else:
            self.render()

    def _animate_panel(self, panel: str, visible: bool) -> None:
        if panel == "title":
            widget, animation, target = (
                self.title_bar,
                self.title_animation,
                QPoint(0, 0 if visible else -self.TITLE_BAR_HEIGHT),
            )
        else:
            widget, animation, target = (
                self.toolbar_bar,
                self.toolbar_animation,
                QPoint(
                    0,
                    self.height() - self.TOOLBAR_HEIGHT if visible else self.height(),
                ),
            )
        if widget.pos() == target:
            return
        animation.stop()
        animation.setStartValue(widget.pos())
        animation.setEndValue(target)
        animation.start()

    def _animate_chrome(self, visible: bool) -> None:
        self._chrome_visible = visible
        self._animate_panel("title", visible)
        self._animate_panel("toolbar", visible)

    def _toggle_chrome_from_content(self) -> None:
        self.scroll.setFocus()
        if self._chrome_visible:
            self.chrome_hide_timer.stop()
            self._animate_chrome(False)
        else:
            self._animate_chrome(True)
            self.chrome_hide_timer.start()

    def _layout_chrome(self) -> None:
        if hasattr(self, "title_animation"):
            self.title_animation.stop()
            self.toolbar_animation.stop()
        self.title_bar.resize(self.width(), self.TITLE_BAR_HEIGHT)
        self.toolbar_bar.resize(self.width(), self.TOOLBAR_HEIGHT)
        self.title_bar.move(0, 0 if self._chrome_visible else -self.TITLE_BAR_HEIGHT)
        self.toolbar_bar.move(
            0,
            self.height() - self.TOOLBAR_HEIGHT if self._chrome_visible else self.height(),
        )
        self.title_bar.raise_()
        self.toolbar_bar.raise_()
        if hasattr(self, "resume"):
            self.resume.raise_()

    def _page_input_active(self) -> bool:
        editor = self.jump.lineEdit()
        return self.jump.hasFocus() or (editor is not None and editor.hasFocus())

    def _page_input_finished(self) -> None:
        # 回车可能触发 editingFinished 但焦点仍在输入框；超时回调会继续
        # 保持栏显示。真正失焦时从这里重新计算完整的五秒等待。
        self.chrome_hide_timer.start()

    def _hide_chrome_if_idle(self) -> None:
        if self._page_input_active():
            return
        self._animate_chrome(False)

    def _check_panel_proximity(self) -> None:
        cursor = self.mapFromGlobal(QCursor.pos())
        if not (0 <= cursor.x() < self.width() and 0 <= cursor.y() < self.height()):
            return
        edge_zone = max(self.TITLE_BAR_HEIGHT, self.TOOLBAR_HEIGHT) + 12
        if not self._chrome_visible:
            edge_zone = 24
        if cursor.y() <= edge_zone or cursor.y() >= self.height() - edge_zone:
            self._animate_chrome(True)
            self.chrome_hide_timer.start()

    def eventFilter(self, watched, event) -> bool:  # noqa: N802
        if watched is self.scroll.viewport() and event.type() == QEvent.Type.MouseButtonPress:
            if event.button() == Qt.LeftButton:
                self._content_press_position = event.position().toPoint()
        if watched is self.scroll.viewport() and event.type() == QEvent.Type.MouseButtonRelease:
            if event.button() == Qt.LeftButton and self._content_press_position is not None:
                distance = (
                    event.position().toPoint() - self._content_press_position
                ).manhattanLength()
                self._content_press_position = None
                if distance <= 5:
                    self._toggle_chrome_from_content()
        if watched is self.scroll.viewport() and event.type() == QEvent.Type.Wheel:
            if self.active_mode == "single":
                delta = event.angleDelta().y() or event.pixelDelta().y()
                self.wheel_delta += delta
                threshold = 120 if event.angleDelta().y() else 80
                if abs(self.wheel_delta) >= threshold:
                    self.previous_page() if self.wheel_delta > 0 else self.next_page()
                    self.wheel_delta = 0
                event.accept()
                return True
        return super().eventFilter(watched, event)

    def resizeEvent(self, event: QResizeEvent) -> None:  # noqa: N802
        super().resizeEvent(event)
        if hasattr(self, "scroll"):
            self._layout_chrome()
            QTimer.singleShot(0, self._refit_after_resize)

    def _refit_after_resize(self) -> None:
        if self.active_mode == "continuous":
            for label in self.continuous_labels:
                label.setProperty("loaded", False)
            self.update_continuous_pages()
        else:
            self.render()

    def keyPressEvent(self, event: QKeyEvent) -> None:  # noqa: N802
        if self.active_mode == "single":
            if event.key() in {Qt.Key_Right, Qt.Key_Down}:
                self.next_page()
                return
            if event.key() in {Qt.Key_Left, Qt.Key_Up}:
                self.previous_page()
                return
        super().keyPressEvent(event)

    def done(self, result: int) -> None:
        if not self._progress_saved and self.members:
            offset = 0
            if self.active_mode == "continuous" and self.continuous_labels:
                self.page_index = self._detect_continuous_page()
                label = self.continuous_labels[self.page_index]
                relative = max(0, self.scroll.verticalScrollBar().value() - label.y())
                offset = min(10_000, int(relative * 10_000 / max(1, label.height())))
            self.reader.save_progress(self.work, self.page_index, offset)
            self._progress_saved = True
        super().done(result)
