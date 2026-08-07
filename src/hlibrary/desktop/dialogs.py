from __future__ import annotations

from functools import partial

from PySide6.QtCore import QSize, Qt, Signal
from PySide6.QtGui import QCloseEvent, QColor, QMouseEvent, QMovie, QPixmap
from PySide6.QtWidgets import (
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QGraphicsDropShadowEffect,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

from hlibrary.catalog import CatalogService
from hlibrary.database import Tag, Work
from hlibrary.desktop.reader_dialog import pixmap_from_bytes
from hlibrary.media import MediaService


def _clear_layout(layout) -> None:
    while layout.count():
        item = layout.takeAt(0)
        if item.widget():
            item.widget().deleteLater()


class PressPreviewLabel(QLabel):
    pressed = Signal()
    released = Signal()

    def mousePressEvent(self, event: QMouseEvent) -> None:  # noqa: N802
        if event.button() == Qt.LeftButton:
            self.pressed.emit()
        super().mousePressEvent(event)

    def mouseReleaseEvent(self, event: QMouseEvent) -> None:  # noqa: N802
        self.released.emit()
        super().mouseReleaseEvent(event)


class CoverSelectorDialog(QDialog):
    def __init__(self, work: Work, media: MediaService, current: str | None, parent=None):
        super().__init__(parent)
        self.work = work
        self.media = media
        self.members = media.comic_members(work)
        initial = current or "001.webp"
        self.index = self.members.index(initial) if initial in self.members else 0
        self.selected_member: str | None = current
        self.setWindowTitle("选择封面")
        self.resize(720, 720)
        root = QVBoxLayout(self)
        self.image = QLabel()
        self.image.setAlignment(Qt.AlignCenter)
        root.addWidget(self.image, 1)
        controls = QHBoxLayout()
        previous = QPushButton("上一张")
        previous.clicked.connect(lambda: self.move_page(-1))
        self.position = QLabel()
        following = QPushButton("下一张")
        following.clicked.connect(lambda: self.move_page(1))
        controls.addWidget(previous)
        controls.addWidget(self.position, 1, Qt.AlignCenter)
        controls.addWidget(following)
        root.addLayout(controls)
        buttons = QDialogButtonBox(QDialogButtonBox.Save | QDialogButtonBox.Cancel)
        buttons.button(QDialogButtonBox.Save).setText("设为封面")
        buttons.accepted.connect(self.choose)
        buttons.rejected.connect(self.reject)
        root.addWidget(buttons)
        self.render()

    def render(self) -> None:
        if not self.members:
            self.image.setText("没有可选图片")
            return
        try:
            pixmap = pixmap_from_bytes(
                self.media.read_original(self.work, self.members[self.index])
            )
            self.image.setPixmap(
                pixmap.scaled(620, 570, Qt.KeepAspectRatio, Qt.SmoothTransformation)
            )
            self.position.setText(
                f"{self.index + 1}/{len(self.members)} · {self.members[self.index]}"
            )
        except Exception as exc:
            self.image.setText(f"图片无法读取：{exc}")

    def move_page(self, offset: int) -> None:
        if self.members:
            self.index = min(max(0, self.index + offset), len(self.members) - 1)
            self.render()

    def choose(self) -> None:
        if self.members:
            self.selected_member = self.members[self.index]
            self.accept()


class TagManagerDialog(QDialog):
    tag_created = Signal(int)

    def __init__(self, catalog: CatalogService, parent=None) -> None:
        super().__init__(parent)
        self.catalog = catalog
        self.setWindowTitle("管理 Tag")
        self.resize(560, 520)
        root = QVBoxLayout(self)
        group_row = QHBoxLayout()
        self.group_name = QLineEdit()
        self.group_name.setPlaceholderText("新分组名称")
        group_add = QPushButton("创建分组")
        group_add.clicked.connect(self.create_group)
        group_row.addWidget(self.group_name)
        group_row.addWidget(group_add)
        tag_row = QHBoxLayout()
        self.tag_name = QLineEdit()
        self.tag_name.setPlaceholderText("新 Tag 名称")
        self.group_box = QComboBox()
        tag_add = QPushButton("创建 Tag")
        tag_add.clicked.connect(self.create_tag)
        tag_row.addWidget(self.tag_name)
        tag_row.addWidget(self.group_box)
        tag_row.addWidget(tag_add)
        self.items = QVBoxLayout()
        content = QWidget()
        content.setLayout(self.items)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setWidget(content)
        root.addLayout(group_row)
        root.addLayout(tag_row)
        root.addWidget(scroll, 1)
        close_buttons = QDialogButtonBox(QDialogButtonBox.Close)
        close_buttons.rejected.connect(self.reject)
        root.addWidget(close_buttons)
        self.refresh()

    def refresh(self) -> None:
        groups = self.catalog.list_groups()
        self.group_box.clear()
        self.group_box.addItem("未分组", None)
        for group in groups:
            self.group_box.addItem(group.name, group.id)
        tags = self.catalog.list_tags()
        _clear_layout(self.items)
        if groups:
            self.items.addWidget(QLabel("分组（隐藏属性）"))
        for group in groups:
            row = QWidget()
            layout = QHBoxLayout(row)
            layout.setContentsMargins(4, 2, 4, 2)
            name = QLineEdit(group.name)
            rename = QPushButton("改名")
            rename.clicked.connect(partial(self.rename_group, group.id, name))
            remove = QPushButton("删除分组")
            remove.clicked.connect(partial(self.delete_group, group.id, group.name))
            layout.addWidget(name, 1)
            layout.addWidget(rename)
            layout.addWidget(remove)
            self.items.addWidget(row)
        if tags:
            self.items.addWidget(QLabel("Tag"))
        for tag in tags:
            row = QWidget()
            layout = QHBoxLayout(row)
            layout.setContentsMargins(4, 2, 4, 2)
            name = QLineEdit(tag.name)
            group_box = QComboBox()
            group_box.addItem("未分组", None)
            for group in groups:
                group_box.addItem(group.name, group.id)
            group_box.setCurrentIndex(max(0, group_box.findData(tag.group_id)))
            save = QPushButton("保存")
            save.clicked.connect(partial(self.save_tag, tag.id, name, group_box))
            layout.addWidget(name, 1)
            layout.addWidget(group_box)
            layout.addWidget(QLabel(f"{len(tag.works)} 部作品"))
            layout.addWidget(save)
            remove = QPushButton("删除")
            remove.clicked.connect(partial(self.delete_tag, tag))
            layout.addWidget(remove)
            self.items.addWidget(row)
        self.items.addStretch(1)

    def rename_group(self, group_id: int, editor: QLineEdit) -> None:
        try:
            self.catalog.rename_group(group_id, editor.text())
        except ValueError as exc:
            QMessageBox.warning(self, "无法改名", str(exc))
            return
        self.refresh()

    def save_tag(self, tag_id: int, editor: QLineEdit, group_box: QComboBox) -> None:
        try:
            self.catalog.rename_tag(tag_id, editor.text())
            self.catalog.move_tag(tag_id, group_box.currentData())
        except ValueError as exc:
            QMessageBox.warning(self, "无法保存", str(exc))
            return
        self.refresh()

    def delete_group(self, group_id: int, name: str) -> None:
        comics, illustrations = self.catalog.group_impact(group_id)
        box = QMessageBox(self)
        box.setWindowTitle("删除 Tag 分组")
        box.setText(
            f"分组“{name}”影响漫画 {comics} 部、插画 {illustrations} 部。\n请选择如何处理组内 Tag。"
        )
        only_group = box.addButton("只删除分组", QMessageBox.AcceptRole)
        all_tags = box.addButton("删除分组及 Tag", QMessageBox.DestructiveRole)
        box.addButton(QMessageBox.Cancel)
        box.exec()
        clicked = box.clickedButton()
        if clicked not in {only_group, all_tags}:
            return
        if clicked is all_tags:
            answer = QMessageBox.question(
                self,
                "再次确认",
                "只会删除 Tag 和作品的 Tag 关联，不会删除任何作品文件。确认继续？",
            )
            if answer != QMessageBox.Yes:
                return
        try:
            self.catalog.delete_group(group_id, delete_tags=clicked is all_tags)
        except ValueError as exc:
            QMessageBox.warning(self, "无法删除", str(exc))
            return
        self.refresh()

    def create_group(self) -> None:
        try:
            self.catalog.create_group(self.group_name.text())
        except ValueError as exc:
            QMessageBox.warning(self, "无法创建", str(exc))
            return
        self.group_name.clear()
        self.refresh()

    def create_tag(self) -> None:
        try:
            tag = self.catalog.create_tag(self.tag_name.text(), self.group_box.currentData())
        except ValueError as exc:
            QMessageBox.warning(self, "无法创建", str(exc))
            return
        self.tag_name.clear()
        self.refresh()
        self.tag_created.emit(tag.id)

    def delete_tag(self, tag: Tag) -> None:
        count = len(tag.works)
        answer = QMessageBox.question(
            self,
            "确认删除 Tag",
            f"“{tag.name}”用于 {count} 部作品。确认后只删除 Tag 和关联资料，不删除作品文件。",
        )
        if answer != QMessageBox.Yes:
            return
        self.catalog.delete_tag(tag.id)
        self.refresh()

    def reject(self) -> None:
        if self.group_name.text().strip() or self.tag_name.text().strip():
            if (
                QMessageBox.question(
                    self, "放弃未提交输入？", "新分组或新 Tag 尚未创建，确认关闭？"
                )
                != QMessageBox.Yes
            ):
                return
        super().reject()


class WorkDetailDialog(QDialog):
    saved = Signal()
    reading_requested = Signal(int)

    def __init__(self, work_id: int, catalog: CatalogService, media: MediaService, parent=None):
        super().__init__(parent)
        self.work_id = work_id
        self.catalog = catalog
        self.media = media
        self.work: Work | None = None
        self.editing = False
        self.selected_tags: set[int] = set()
        self.setWindowTitle("作品详情")
        self.resize(760, 760)
        self.root = QVBoxLayout(self)
        self.large_preview = QLabel(self)
        self.large_preview.setAlignment(Qt.AlignCenter)
        self.large_preview.setStyleSheet("background: rgba(0,0,0,210); padding: 20px")
        self.large_preview.hide()
        self.render_view()

    def render_view(self) -> None:
        self.editing = False
        _clear_layout(self.root)
        self.work = self.catalog.get_work(self.work_id)
        if self.work is None:
            self.reject()
            return
        work = self.work
        top = QHBoxLayout()
        top.addWidget(QLabel("漫画详情" if work.kind == "comic" else "插画详情"), 1)
        edit = QPushButton("编辑")
        edit.clicked.connect(self.render_edit)
        top.addWidget(edit)
        self.root.addLayout(top)
        cover = QLabel()
        cover.setAlignment(Qt.AlignCenter)
        cover.setMinimumHeight(330)
        shadow = QGraphicsDropShadowEffect(cover)
        shadow.setBlurRadius(22)
        shadow.setOffset(0, 8)
        shadow.setColor(QColor(0, 0, 0, 130))
        cover.setGraphicsEffect(shadow)
        try:
            thumbnail = self.media.thumbnail(work, 520, 330)
            if work.kind == "illustration" and thumbnail.suffix == ".gif":
                self._detail_movie = QMovie(str(thumbnail))
                self._detail_movie.setScaledSize(QSize(520, 330))
                cover.setMovie(self._detail_movie)
                self._detail_movie.start()
            else:
                cover.setPixmap(QPixmap(str(thumbnail)))
        except Exception as exc:
            cover.setText(f"封面无法读取：{exc}")
        self.root.addWidget(cover)
        title = QLabel(work.title or work.file_name.rsplit(".", 1)[0])
        title.setStyleSheet("font-size: 25px; font-weight: 700")
        self.root.addWidget(title)
        self.root.addWidget(
            QLabel(work.number or (work.file_name if work.kind == "illustration" else ""))
        )
        self.root.addWidget(QLabel("★" * work.rating + "☆" * (3 - work.rating)))
        tags = self.catalog.list_tags()
        names = [self.catalog.tag_display_name(tag, tags) for tag in work.tags]
        self.root.addWidget(QLabel("  ".join(names) or "暂无 Tag"))
        if work.kind == "comic":
            previews = self.media.preview_members(work)
            if previews:
                preview_content = QWidget()
                preview_layout = QHBoxLayout(preview_content)
                for member in previews:
                    label = PressPreviewLabel()
                    label.setAlignment(Qt.AlignCenter)
                    try:
                        pixmap = pixmap_from_bytes(self.media.read_original(work, member))
                        label.setPixmap(pixmap.scaledToHeight(150, Qt.SmoothTransformation))
                        label.pressed.connect(partial(self.show_large_preview, work, member))
                        label.released.connect(self.hide_large_preview)
                    except Exception as exc:
                        label.setText(f"{member}\n{exc}")
                    preview_layout.addWidget(label)
                preview_scroll = QScrollArea()
                preview_scroll.setWidgetResizable(True)
                preview_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAsNeeded)
                preview_scroll.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
                preview_scroll.setFixedHeight(190)
                preview_scroll.setStyleSheet(
                    "QScrollArea { border: 1px solid palette(mid); border-radius: 14px; }"
                )
                preview_scroll.setWidget(preview_content)
                self.root.addWidget(preview_scroll)
            else:
                self.root.addWidget(QLabel("暂无预览图"))
            read = QPushButton("开始阅读")
            read.clicked.connect(self.start_reading)
            self.root.addWidget(read)
        self.root.addStretch(1)

    def start_reading(self) -> None:
        assert self.work is not None
        self.reading_requested.emit(self.work.id)
        self.accept()

    def show_large_preview(self, work: Work, member: str) -> None:
        try:
            pixmap = pixmap_from_bytes(self.media.read_original(work, member))
            self.large_preview.setGeometry(self.rect())
            self.large_preview.setPixmap(
                pixmap.scaled(
                    max(1, self.width() - 50),
                    max(1, self.height() - 50),
                    Qt.KeepAspectRatio,
                    Qt.SmoothTransformation,
                )
            )
            self.large_preview.raise_()
            self.large_preview.show()
        except Exception:
            self.large_preview.hide()

    def hide_large_preview(self) -> None:
        self.large_preview.hide()

    def render_edit(self) -> None:
        assert self.work is not None
        self.editing = True
        _clear_layout(self.root)
        form = QFormLayout()
        self.title_edit = QLineEdit(self.work.title or "")
        self.rating_edit = QSpinBox()
        self.rating_edit.setRange(0, 3)
        self.rating_edit.setValue(self.work.rating)
        form.addRow("标题", self.title_edit)
        form.addRow("星级（0～3）", self.rating_edit)
        self.root.addLayout(form)
        self.root.addWidget(QLabel("Tag"))
        self.tag_search_edit = QLineEdit()
        self.tag_search_edit.setPlaceholderText("搜索 Tag 或隐藏分组")
        self.tag_search_edit.textChanged.connect(self.refresh_tag_choices)
        self.root.addWidget(self.tag_search_edit)
        self.tag_area = QVBoxLayout()
        self.selected_tags = {tag.id for tag in self.work.tags}
        self.pending_cover = self.work.cover_member
        self.refresh_tag_choices()
        self.root.addLayout(self.tag_area)
        manage = QPushButton("管理 Tag")
        manage.clicked.connect(self.manage_tags)
        self.root.addWidget(manage)
        if self.work.kind == "comic":
            cover = QPushButton("更改封面")
            cover.clicked.connect(self.choose_cover)
            self.root.addWidget(cover)
        buttons = QDialogButtonBox(QDialogButtonBox.Save | QDialogButtonBox.Cancel)
        buttons.accepted.connect(self.save)
        buttons.rejected.connect(self.render_view)
        self.root.addWidget(buttons)

    def refresh_tag_choices(self) -> None:
        _clear_layout(self.tag_area)
        tags = self.catalog.list_tags(self.tag_search_edit.text())
        all_tags = self.catalog.list_tags()
        for tag in tags:
            button = QPushButton(self.catalog.tag_display_name(tag, all_tags))
            button.setCheckable(True)
            button.setChecked(tag.id in self.selected_tags)
            button.toggled.connect(partial(self.toggle_tag, tag.id))
            self.tag_area.addWidget(button)

    def toggle_tag(self, tag_id: int, checked: bool) -> None:
        if checked:
            self.selected_tags.add(tag_id)
        else:
            self.selected_tags.discard(tag_id)

    def manage_tags(self) -> None:
        dialog = TagManagerDialog(self.catalog, self)
        dialog.tag_created.connect(self.selected_tags.add)
        dialog.exec()
        self.refresh_tag_choices()

    def choose_cover(self) -> None:
        assert self.work is not None
        dialog = CoverSelectorDialog(self.work, self.media, self.pending_cover, self)
        if dialog.exec() == QDialog.Accepted:
            self.pending_cover = dialog.selected_member

    def save(self) -> None:
        assert self.work is not None
        self.catalog.update_work(
            self.work.id,
            title=self.title_edit.text(),
            rating=self.rating_edit.value(),
            tag_ids=list(self.selected_tags),
            cover_member=self.pending_cover,
        )
        self.saved.emit()
        self.render_view()

    def closeEvent(self, event: QCloseEvent) -> None:  # noqa: N802
        if self.editing:
            answer = QMessageBox.question(
                self,
                "放弃未保存修改？",
                "当前标题、星级、封面或 Tag 选择尚未保存。确认关闭并放弃这些修改？",
            )
            if answer != QMessageBox.Yes:
                event.ignore()
                return
        event.accept()
