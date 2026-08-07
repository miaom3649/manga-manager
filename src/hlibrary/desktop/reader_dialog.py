from __future__ import annotations

from io import BytesIO

from PIL import Image
from PySide6.QtCore import QPoint, Qt, QTimer
from PySide6.QtGui import QImage, QKeyEvent, QMouseEvent, QPixmap
from PySide6.QtWidgets import (
    QComboBox,
    QDialog,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QScrollArea,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

from hlibrary.database import Work
from hlibrary.reader import ReaderService


def pixmap_from_bytes(data: bytes) -> QPixmap:
    with Image.open(BytesIO(data)) as source:
        image = source.convert("RGBA")
        raw = image.tobytes("raw", "RGBA")
        qimage = QImage(raw, image.width, image.height, QImage.Format_RGBA8888).copy()
    return QPixmap.fromImage(qimage)


class PanLabel(QLabel):
    def __init__(self, scroll: QScrollArea) -> None:
        super().__init__()
        self.scroll = scroll
        self.last_position: QPoint | None = None
        self.setCursor(Qt.OpenHandCursor)

    def mousePressEvent(self, event: QMouseEvent) -> None:  # noqa: N802
        if event.button() == Qt.LeftButton:
            self.last_position = event.position().toPoint()
            self.setCursor(Qt.ClosedHandCursor)

    def mouseMoveEvent(self, event: QMouseEvent) -> None:  # noqa: N802
        if self.last_position is None:
            return
        current = event.position().toPoint()
        delta = current - self.last_position
        self.scroll.horizontalScrollBar().setValue(
            self.scroll.horizontalScrollBar().value() - delta.x()
        )
        self.scroll.verticalScrollBar().setValue(
            self.scroll.verticalScrollBar().value() - delta.y()
        )
        self.last_position = current

    def mouseReleaseEvent(self, event: QMouseEvent) -> None:  # noqa: N802
        self.last_position = None
        self.setCursor(Qt.OpenHandCursor)


class ReaderDialog(QDialog):
    def __init__(self, work: Work, reader: ReaderService, parent=None) -> None:
        super().__init__(parent)
        self.work = work
        self.reader = reader
        self.members = reader.members(work)
        self.page_index = 0
        self.zoom = 1.0
        self.continuous_labels: list[QLabel] = []
        self.progress_timer = QTimer(self)
        self.progress_timer.setSingleShot(True)
        self.progress_timer.setInterval(1000)
        self.progress_timer.timeout.connect(self.save_continuous_progress)
        self.setWindowTitle(work.title or work.file_name)
        self.resize(1050, 800)
        root = QVBoxLayout(self)
        toolbar = QHBoxLayout()
        back = QPushButton("返回详情")
        back.clicked.connect(self.accept)
        self.position = QLabel()
        self.mode = QComboBox()
        self.mode.addItem("单页", "single")
        self.mode.addItem("纵向连续", "continuous")
        preferred = self.mode.findData(self.reader.preferred_mode())
        self.mode.setCurrentIndex(max(0, preferred))
        self.mode.currentIndexChanged.connect(self.mode_changed)
        previous = QPushButton("上一页")
        previous.clicked.connect(self.previous_page)
        following = QPushButton("下一页")
        following.clicked.connect(self.next_page)
        smaller = QPushButton("−")
        smaller.clicked.connect(lambda: self.change_zoom(0.9))
        larger = QPushButton("＋")
        larger.clicked.connect(lambda: self.change_zoom(1.1))
        fit = QPushButton("适配宽度")
        fit.clicked.connect(self.fit_width)
        self.jump = QSpinBox()
        self.jump.setRange(1, max(1, len(self.members)))
        self.jump.valueChanged.connect(lambda value: self.go_page(value - 1))
        fullscreen = QPushButton("全屏")
        fullscreen.clicked.connect(self.toggle_fullscreen)
        for widget in (
            back,
            self.position,
            self.mode,
            previous,
            following,
            smaller,
            larger,
            fit,
            self.jump,
            fullscreen,
        ):
            toolbar.addWidget(widget)
        root.addLayout(toolbar)
        self.scroll = QScrollArea()
        self.scroll.setWidgetResizable(True)
        self.image = PanLabel(self.scroll)
        self.image.setAlignment(Qt.AlignCenter)
        self.scroll.setWidget(self.image)
        self.scroll.verticalScrollBar().valueChanged.connect(self.continuous_scrolled)
        root.addWidget(self.scroll, 1)
        self.resume = QPushButton("回到上次观看位置", self)
        self.resume.clicked.connect(self.resume_progress)
        self.resume.hide()
        QTimer.singleShot(0, self._initial_render)

    def _initial_render(self) -> None:
        self.mode_changed()
        progress = self.reader.progress(self.work)
        if progress and progress.page_index > 0:
            self.resume.show()
            self.resume.move(24, 64)
            QTimer.singleShot(5000, self.resume.hide)

    def resume_progress(self) -> None:
        progress = self.reader.progress(self.work)
        if progress:
            self.go_page(progress.page_index)
            if self.mode.currentData() == "continuous" and self.continuous_labels:
                label = self.continuous_labels[self.page_index]
                offset = int(label.height() * min(progress.page_offset, 10_000) / 10_000)
                QTimer.singleShot(
                    0,
                    lambda: self.scroll.verticalScrollBar().setValue(label.y() + offset),
                )
        self.resume.hide()

    def render(self) -> None:
        if not self.members:
            self.image.setText("压缩包内没有可读取的图片")
            return
        try:
            data = self.reader.page(self.work, self.members[self.page_index])
            pixmap = pixmap_from_bytes(data)
        except Exception as exc:
            self.image.setText(f"第 {self.page_index + 1} 页无法读取：{exc}")
            self.position.setText(f"{self.page_index + 1}/{len(self.members)}")
            return
        target_width = max(1, int(self.scroll.viewport().width() * self.zoom))
        pixmap = pixmap.scaledToWidth(target_width, Qt.SmoothTransformation)
        self.image.setPixmap(pixmap)
        self.position.setText(f"{self.page_index + 1}/{len(self.members)}")
        self.jump.blockSignals(True)
        self.jump.setValue(self.page_index + 1)
        self.jump.blockSignals(False)

    def mode_changed(self) -> None:
        self.reader.set_preferred_mode(self.mode.currentData())
        if self.mode.currentData() == "continuous":
            self.build_continuous()
        else:
            self.scroll.takeWidget()
            self.image = PanLabel(self.scroll)
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
            label.setText(f"正在准备第 {index + 1} 页 · {member}")
            label.setAlignment(Qt.AlignCenter)
            label.setMinimumHeight(700)
            label.setProperty("page_index", index)
            label.setProperty("loaded", False)
            layout.addWidget(label)
            self.continuous_labels.append(label)
        self.scroll.setWidget(container)
        QTimer.singleShot(0, self.update_continuous_pages)

    def continuous_scrolled(self) -> None:
        if self.mode.currentData() != "continuous":
            return
        self.update_continuous_pages()
        self.progress_timer.start()

    def update_continuous_pages(self) -> None:
        if not self.continuous_labels:
            return
        top = self.scroll.verticalScrollBar().value()
        height = self.scroll.viewport().height()
        center = top + height // 2
        nearest = 0
        nearest_distance = float("inf")
        for label in self.continuous_labels:
            label_top = label.y()
            label_bottom = label_top + label.height()
            distance = abs((label_top + label_bottom) // 2 - center)
            if distance < nearest_distance:
                nearest = int(label.property("page_index"))
                nearest_distance = distance
            visible_nearby = label_bottom >= top - height and label_top <= top + height * 2
            if visible_nearby and not label.property("loaded"):
                index = int(label.property("page_index"))
                try:
                    pixmap = pixmap_from_bytes(
                        self.reader.page(self.work, self.members[index])
                    ).scaledToWidth(
                        max(1, int(self.scroll.viewport().width() * self.zoom)),
                        Qt.SmoothTransformation,
                    )
                    label.setPixmap(pixmap)
                    label.setFixedHeight(pixmap.height())
                    label.setProperty("loaded", True)
                except Exception as exc:
                    label.setText(f"第 {index + 1} 页读取失败：{exc}")
            elif not visible_nearby and label.property("loaded"):
                label.clear()
                label.setText(f"第 {int(label.property('page_index')) + 1} 页")
                label.setFixedHeight(700)
                label.setProperty("loaded", False)
        self.page_index = nearest
        self.position.setText(f"{nearest + 1}/{len(self.members)}")

    def save_continuous_progress(self) -> None:
        if self.mode.currentData() == "continuous":
            label = self.continuous_labels[self.page_index]
            relative = max(0, self.scroll.verticalScrollBar().value() - label.y())
            offset = min(10_000, int(relative * 10_000 / max(1, label.height())))
            self.reader.save_progress(
                self.work,
                self.page_index,
                offset,
            )

    def go_page(self, index: int) -> None:
        if not self.members:
            return
        self.page_index = min(max(index, 0), len(self.members) - 1)
        if self.mode.currentData() == "continuous" and self.continuous_labels:
            self.scroll.verticalScrollBar().setValue(self.continuous_labels[self.page_index].y())
        else:
            self.render()
        self.reader.save_progress(self.work, self.page_index)

    def previous_page(self) -> None:
        self.go_page(self.page_index - 1)

    def next_page(self) -> None:
        self.go_page(self.page_index + 1)

    def change_zoom(self, multiplier: float) -> None:
        self.zoom = min(4.0, max(0.2, self.zoom * multiplier))
        if self.mode.currentData() == "continuous":
            for label in self.continuous_labels:
                label.setProperty("loaded", False)
            self.update_continuous_pages()
        else:
            self.render()

    def fit_width(self) -> None:
        self.zoom = 1.0
        if self.mode.currentData() == "continuous":
            for label in self.continuous_labels:
                label.setProperty("loaded", False)
            self.update_continuous_pages()
        else:
            self.render()

    def toggle_fullscreen(self) -> None:
        self.showNormal() if self.isFullScreen() else self.showFullScreen()

    def keyPressEvent(self, event: QKeyEvent) -> None:  # noqa: N802
        if self.mode.currentData() == "single":
            if event.key() in {Qt.Key_Right, Qt.Key_Down}:
                self.next_page()
                return
            if event.key() in {Qt.Key_Left, Qt.Key_Up}:
                self.previous_page()
                return
        super().keyPressEvent(event)
