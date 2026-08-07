from __future__ import annotations

from functools import partial

from PySide6.QtCore import QSize, Qt, QTimer, Signal
from PySide6.QtGui import QCloseEvent, QColor, QMouseEvent, QMovie, QPixmap
from PySide6.QtWidgets import (
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QFrame,
    QGraphicsDropShadowEffect,
    QGridLayout,
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
from hlibrary.desktop.tag_widgets import (
    AUTHOR_TAG_COLOR,
    is_long_tag_category,
    tag_chip_text,
    tag_sort_category,
)
from hlibrary.desktop.windowing import FloatingCardDialog, ScreenCenteredDialog
from hlibrary.media import MediaService


def _clear_layout(layout) -> None:
    while layout.count():
        item = layout.takeAt(0)
        if item.widget():
            item.widget().deleteLater()
        elif item.layout():
            _clear_layout(item.layout())
            item.layout().deleteLater()


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


class ResponsiveTagGrid(QWidget):
    resized = Signal(int)

    def resizeEvent(self, event) -> None:  # noqa: N802
        super().resizeEvent(event)
        self.resized.emit(event.size().width())


class ClickableTagLabel(QLabel):
    clicked = Signal()

    def __init__(self, text: str, parent=None) -> None:
        super().__init__(text, parent)
        self.setCursor(Qt.PointingHandCursor)

    def mouseReleaseEvent(self, event: QMouseEvent) -> None:  # noqa: N802
        if event.button() == Qt.LeftButton:
            self.clicked.emit()
        super().mouseReleaseEvent(event)


class CoverSelectorDialog(ScreenCenteredDialog):
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


class TagManagerDialog(FloatingCardDialog):
    tag_created = Signal(int)

    def __init__(self, catalog: CatalogService, parent=None, *, mode: str = "tags") -> None:
        super().__init__(parent, card_size=QSize(560, 520))
        self.catalog = catalog
        self.mode = mode
        self.setWindowTitle("管理 Tag 分组" if mode == "groups" else "管理 Tag")
        root = self.card_layout
        group_row = QHBoxLayout()
        self.group_name = QLineEdit()
        self.group_name.setMaxLength(5)
        self.group_name.setPlaceholderText("新分组名称")
        group_add = QPushButton("创建分组")
        group_add.clicked.connect(self.create_group)
        group_row.addWidget(self.group_name)
        group_row.addWidget(group_add)
        tag_row = QHBoxLayout()
        self.tag_name = QLineEdit()
        self.tag_name.setMaxLength(5)
        self.tag_name.setPlaceholderText("新 Tag 名称")
        tag_add = QPushButton("创建新 Tag")
        tag_add.clicked.connect(self.create_tag)
        tag_row.addWidget(self.tag_name)
        tag_row.addWidget(tag_add)
        self.items = QVBoxLayout()
        content = QWidget()
        content.setLayout(self.items)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setWidget(content)
        if mode == "groups":
            root.addLayout(group_row)
        else:
            root.addLayout(tag_row)
        root.addWidget(scroll, 1)
        self.refresh()

    def refresh(self) -> None:
        groups = self.catalog.list_groups()
        tags = self.catalog.list_tags()
        _clear_layout(self.items)
        if self.mode == "groups":
            for group in groups:
                row = QWidget()
                layout = QHBoxLayout(row)
                layout.setContentsMargins(4, 2, 4, 2)
                name = QLineEdit(group.name)
                name.setMaxLength(5)
                remove = QPushButton("删除分组")
                if self.catalog.is_author_group(group):
                    name.setReadOnly(True)
                    remove.setText("系统分组")
                    remove.setEnabled(False)
                else:
                    name.editingFinished.connect(partial(self.rename_group, group.id, name))
                    remove.clicked.connect(partial(self.delete_group, group.id, group.name))
                layout.addWidget(name, 1)
                layout.addWidget(remove)
                self.items.addWidget(row)
        else:
            for tag in tags:
                row = QWidget()
                layout = QHBoxLayout(row)
                layout.setContentsMargins(4, 2, 4, 2)
                name = QLineEdit(tag.name)
                name.setMaxLength(200 if self.catalog.is_author_tag(tag) else 5)
                group_box = QComboBox()
                group_box.addItem("未分组", None)
                for group in groups:
                    group_box.addItem(group.name, group.id)
                group_box.setCurrentIndex(max(0, group_box.findData(tag.group_id)))
                name.editingFinished.connect(partial(self.rename_tag, tag.id, name))
                group_box.currentIndexChanged.connect(partial(self.move_tag, tag.id, group_box))
                layout.addWidget(name, 1)
                layout.addWidget(group_box)
                layout.addWidget(QLabel(f"{len(tag.works)} 部作品"))
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
            self.refresh()
            return

    def rename_tag(self, tag_id: int, editor: QLineEdit) -> None:
        try:
            self.catalog.rename_tag(tag_id, editor.text())
        except ValueError as exc:
            QMessageBox.warning(self, "无法改名", str(exc))
            self.refresh()
            return

    def move_tag(self, tag_id: int, group_box: QComboBox, _index: int) -> None:
        try:
            self.catalog.move_tag(tag_id, group_box.currentData())
        except ValueError as exc:
            QMessageBox.warning(self, "无法移动", str(exc))
            self.refresh()
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
            tag = self.catalog.create_tag(self.tag_name.text(), None)
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
        pending = self.group_name.text() if self.mode == "groups" else self.tag_name.text()
        if pending.strip():
            if (
                QMessageBox.question(
                    self, "放弃未提交输入？", "新分组或新 Tag 尚未创建，确认关闭？"
                )
                != QMessageBox.Yes
            ):
                return
        super().reject()


def open_tag_management(catalog: CatalogService, parent=None) -> list[int]:
    chooser = TagManagementChooserDialog(parent)
    chooser.exec()
    if chooser.choice == "groups":
        TagManagerDialog(catalog, parent, mode="groups").exec()
        return []
    if chooser.choice == "tags":
        created: list[int] = []
        dialog = TagManagerDialog(catalog, parent, mode="tags")
        dialog.tag_created.connect(created.append)
        dialog.exec()
        return created
    return []


class TagManagementChooserDialog(FloatingCardDialog):
    """Full-screen dimmed chooser; clicking outside its card dismisses it."""

    def __init__(self, parent=None) -> None:
        super().__init__(parent, card_size=QSize(540, 206))
        self.choice: str | None = None
        card_layout = QHBoxLayout()
        card_layout.setSpacing(22)
        self.card_layout.addLayout(card_layout)
        for label, choice in (("管理 Tag 分组", "groups"), ("管理 Tag", "tags")):
            button = QPushButton(label)
            button.setFixedSize(220, 150)
            button.setStyleSheet(
                "QPushButton { background: transparent; color: palette(button-text); "
                "border: 2px solid #6750a4; border-radius: 18px; "
                "font-size: 20px; font-weight: 700; } "
                "QPushButton:hover { background: palette(midlight); }"
            )
            button.clicked.connect(partial(self.choose, choice))
            card_layout.addWidget(button)

    def choose(self, choice: str) -> None:
        self.choice = choice
        self.accept()


class ResetSettingsDialog(FloatingCardDialog):
    def __init__(self, parent=None) -> None:
        super().__init__(parent, card_size=QSize(560, 360))
        title = QLabel("恢复所有设置")
        title.setAlignment(Qt.AlignCenter)
        title.setStyleSheet("font-size: 25px; font-weight: 700; color: #d93025;")
        warning = QLabel(
            "该操作不可恢复。\n\n"
            "软件数据库将被彻底重建，所有管理资料和设置都会恢复默认，"
            "包括标题、Tag、分组、星级、封面、阅读进度、通知、配对设备和主题。\n\n"
            "全部备份和缓存也会删除。\n\n"
            "只保留漫画、插画原文件和当前作品目录位置，随后重新扫描作品。"
        )
        warning.setWordWrap(True)
        warning.setAlignment(Qt.AlignLeft | Qt.AlignVCenter)
        cancel = QPushButton("取消")
        cancel.clicked.connect(self.reject)
        confirm = QPushButton("确认恢复所有设置")
        cancel.setFixedHeight(46)
        confirm.setFixedHeight(46)
        confirm.setStyleSheet(
            "QPushButton { background: #d93025; color: white; "
            "border: 2px solid #d93025; border-radius: 10px; "
            "font-weight: 700; padding: 10px 14px; } "
            "QPushButton:hover { background: #b3261e; }"
        )
        confirm.clicked.connect(self.accept)
        buttons = QHBoxLayout()
        buttons.addWidget(cancel, 1)
        buttons.addWidget(confirm, 1)
        self.card_layout.addWidget(title)
        self.card_layout.addWidget(warning, 1)
        self.card_layout.addLayout(buttons)


class UploadResultDialog(FloatingCardDialog):
    """Show a batch upload rejection or request one overwrite decision."""

    def __init__(self, title: str, message: str, parent=None, *, overwrite: bool = False) -> None:
        super().__init__(parent, card_size=QSize(560, 360))
        heading = QLabel(title)
        heading.setAlignment(Qt.AlignCenter)
        heading.setStyleSheet("font-size: 24px; font-weight: 700;")
        details = QLabel(message)
        details.setWordWrap(True)
        details.setAlignment(Qt.AlignLeft | Qt.AlignVCenter)
        self.card_layout.addWidget(heading)
        self.card_layout.addWidget(details, 1)
        buttons = QHBoxLayout()
        cancel = QPushButton("取消" if overwrite else "知道了")
        cancel.setFixedHeight(46)
        cancel.clicked.connect(self.reject)
        buttons.addWidget(cancel, 1)
        if overwrite:
            confirm = QPushButton("覆盖")
            confirm.setFixedHeight(46)
            confirm.setStyleSheet(
                "QPushButton { background: #d93025; color: white; "
                "border: 2px solid #d93025; border-radius: 10px; "
                "font-weight: 700; padding: 10px 14px; } "
                "QPushButton:hover { background: #b3261e; }"
            )
            confirm.clicked.connect(self.accept)
            buttons.addWidget(confirm, 1)
        self.card_layout.addLayout(buttons)


class WorkDetailDialog(FloatingCardDialog):
    saved = Signal()
    reading_requested = Signal(int)
    kind_filter_requested = Signal(str)
    tag_filter_requested = Signal(int, str)

    def __init__(self, work_id: int, catalog: CatalogService, media: MediaService, parent=None):
        super().__init__(parent, card_size=QSize(760, 760))
        self.work_id = work_id
        self.catalog = catalog
        self.media = media
        self.work: Work | None = None
        self.editing = False
        self.selected_tags: set[int] = set()
        self.setWindowTitle("作品详情")
        detail_content = QWidget()
        self.root = QVBoxLayout(detail_content)
        detail_scroll = QScrollArea()
        detail_scroll.setWidgetResizable(True)
        detail_scroll.setFrameShape(QFrame.NoFrame)
        detail_scroll.setWidget(detail_content)
        self.card_layout.addWidget(detail_scroll)
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
        tag_widget = ResponsiveTagGrid()
        tag_layout = QGridLayout(tag_widget)
        tag_layout.setContentsMargins(0, 2, 0, 2)
        tag_layout.setHorizontalSpacing(7)
        tag_layout.setVerticalSpacing(6)
        tag_layout.setAlignment(Qt.AlignTop | Qt.AlignLeft)
        custom_tag_entries = [
            (
                self.catalog.tag_display_name(tag, tags),
                AUTHOR_TAG_COLOR
                if self.catalog.is_author_tag(tag)
                else "#6750a4"
                if tag.group_id is not None
                else "#777",
                tag_sort_category(
                    self.catalog.tag_display_name(tag, tags),
                    self.fontMetrics(),
                    author=self.catalog.is_author_tag(tag),
                ),
                tag.id,
            )
            for tag in work.tags
        ]
        custom_tag_entries.sort(key=lambda entry: entry[2])
        tag_entries = [
            ("漫画" if work.kind == "comic" else "插画", "#006a6a", 3, None),
            *custom_tag_entries,
        ]
        tag_items: list[tuple[QLabel, int]] = []
        for name, color, category, tag_id in tag_entries:
            label = ClickableTagLabel(tag_chip_text(name))
            label.setObjectName("detailTag")
            label.setAlignment(Qt.AlignCenter)
            label.setToolTip(name)
            label.setFixedHeight(26)
            span = 3 if is_long_tag_category(category) else 1
            label.setFixedWidth(48 * span + 7 * (span - 1))
            label.setStyleSheet(
                f"background: {color}; color: white; border-radius: 9px; padding: 3px 8px;"
            )
            if tag_id is None:
                label.clicked.connect(
                    lambda checked_kind=work.kind: self.filter_by_kind(checked_kind)
                )
            else:
                label.clicked.connect(partial(self.filter_by_tag, tag_id))
            tag_items.append((label, span))
        tag_widget.resized.connect(
            lambda _width: QTimer.singleShot(
                0,
                lambda: self._layout_detail_tags(tag_widget, tag_layout, tag_items),
            )
        )
        self._layout_detail_tags(tag_widget, tag_layout, tag_items)
        self.root.addWidget(tag_widget)
        QTimer.singleShot(
            0,
            lambda: self._layout_detail_tags(tag_widget, tag_layout, tag_items),
        )
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
            read.setStyleSheet(
                "QPushButton { background: #6750a4; color: white; "
                "border: 2px solid #6750a4; border-radius: 10px; "
                "font-weight: 700; padding: 8px 12px; }"
            )
            read.clicked.connect(self.start_reading)
            self.root.addWidget(read)
        edit = QPushButton("编辑")
        edit.clicked.connect(self.render_edit)
        self.root.addWidget(edit)
        self.root.addStretch(1)

    def filter_by_kind(self, kind: str) -> None:
        self.kind_filter_requested.emit(kind)
        self.accept()

    def filter_by_tag(self, tag_id: int) -> None:
        assert self.work is not None
        self.tag_filter_requested.emit(tag_id, self.work.kind)
        self.accept()

    @staticmethod
    def _layout_detail_tags(
        container: QWidget,
        layout: QGridLayout,
        items: list[tuple[QLabel, int]],
    ) -> None:
        spacing = 7
        short_width = 48
        columns = max(3, (max(short_width, container.width()) + spacing) // 55)
        previous_columns = container.property("tagGridColumns") or 0
        for index in range(max(previous_columns, columns)):
            layout.setColumnMinimumWidth(index, short_width if index < columns else 0)
            layout.setColumnStretch(index, 0)
        container.setProperty("tagGridColumns", columns)
        for label, _span in items:
            layout.removeWidget(label)
        row = 0
        column = 0
        for label, span in items:
            if column + span > columns:
                row += 1
                column = 0
            layout.addWidget(label, row, column, 1, span, Qt.AlignLeft)
            column += span
            if column == columns:
                row += 1
                column = 0

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
        self.tag_search_edit = QLineEdit()
        self.tag_search_edit.setPlaceholderText("搜索 Tag 或隐藏分组")
        self.tag_search_edit.textChanged.connect(self.refresh_tag_choices)
        self.root.addWidget(self.tag_search_edit)
        self.tag_content = ResponsiveTagGrid()
        self.tag_content.resized.connect(self._tag_grid_resized)
        self.tag_area = QGridLayout(self.tag_content)
        self.tag_area.setContentsMargins(0, 0, 0, 0)
        self.tag_area.setHorizontalSpacing(7)
        self.tag_area.setVerticalSpacing(6)
        self.tag_area.setAlignment(Qt.AlignTop | Qt.AlignLeft)
        tag_scroll = QScrollArea()
        tag_scroll.setWidgetResizable(True)
        tag_scroll.setFrameShape(QFrame.NoFrame)
        tag_scroll.setMinimumHeight(250)
        tag_scroll.setWidget(self.tag_content)
        self.selected_tags = {tag.id for tag in self.work.tags}
        self.pending_cover = self.work.cover_member
        self.refresh_tag_choices()
        self.root.addWidget(tag_scroll, 1)
        QTimer.singleShot(0, self._layout_tag_choices)
        manage = QPushButton("管理")
        manage.clicked.connect(self.manage_tags)
        self.root.addWidget(manage)
        if self.work.kind == "comic":
            cover = QPushButton("更改封面")
            cover.clicked.connect(self.choose_cover)
            self.root.addWidget(cover)
        save = QPushButton("保存")
        save.setStyleSheet(
            "QPushButton { background: #6750a4; color: white; "
            "border: 2px solid #6750a4; border-radius: 10px; "
            "font-weight: 700; padding: 8px 12px; }"
        )
        save.clicked.connect(self.save)
        self.root.addWidget(save)

    def refresh_tag_choices(self) -> None:
        _clear_layout(self.tag_area)
        tags = self.catalog.list_tags(self.tag_search_edit.text())
        all_tags = self.catalog.list_tags()
        tag_choices = [
            (
                tag,
                self.catalog.tag_display_name(tag, all_tags),
                tag_sort_category(
                    self.catalog.tag_display_name(tag, all_tags),
                    self.fontMetrics(),
                    author=self.catalog.is_author_tag(tag),
                ),
            )
            for tag in tags
        ]
        tag_choices.sort(key=lambda entry: entry[2])
        self.tag_choice_widgets: list[tuple[QPushButton, int]] = []
        self._tag_grid_columns = 0
        for tag, display_name, category in tag_choices:
            long_tag = is_long_tag_category(category)
            span = 3 if long_tag else 1
            button = QPushButton(display_name, self.tag_content)
            button.setCheckable(True)
            button.setChecked(tag.id in self.selected_tags)
            button.setFixedHeight(26)
            button.setFixedWidth(48 * span + 7 * (span - 1))
            button.setToolTip(display_name)
            color = (
                AUTHOR_TAG_COLOR
                if self.catalog.is_author_tag(tag)
                else "#6750a4"
                if tag.group_id is not None
                else "#777"
            )
            button.setStyleSheet(
                "QPushButton { background: transparent; color: palette(text); "
                f"border: 1px solid {color}; border-radius: 9px; padding: 0 8px; }} "
                f"QPushButton:checked {{ background: {color}; color: white; font-weight: 700; }}"
            )
            button.toggled.connect(partial(self.toggle_tag, tag.id))
            self.tag_choice_widgets.append((button, span))
        self._layout_tag_choices()

    def _tag_grid_resized(self, _width: int) -> None:
        QTimer.singleShot(0, self._layout_tag_choices)

    def _layout_tag_choices(self) -> None:
        if not hasattr(self, "tag_choice_widgets"):
            return
        spacing = 7
        short_width = 48
        available = max(short_width, self.tag_content.width())
        columns = max(3, (available + spacing) // (short_width + spacing))
        if columns == self._tag_grid_columns and self.tag_area.count():
            return
        self._tag_grid_columns = columns
        for button, _span in self.tag_choice_widgets:
            self.tag_area.removeWidget(button)
        row = 0
        column = 0
        for button, span in self.tag_choice_widgets:
            if column + span > columns:
                row += 1
                column = 0
            self.tag_area.addWidget(button, row, column, 1, span, Qt.AlignLeft)
            column += span
            if column == columns:
                row += 1
                column = 0

    def toggle_tag(self, tag_id: int, checked: bool) -> None:
        if checked:
            self.selected_tags.add(tag_id)
        else:
            self.selected_tags.discard(tag_id)

    def manage_tags(self) -> None:
        self.selected_tags.update(open_tag_management(self.catalog, self))
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

    def _has_unsaved_edits(self) -> bool:
        if not self.editing or self.work is None:
            return False
        return any(
            (
                self.title_edit.text() != (self.work.title or ""),
                self.rating_edit.value() != self.work.rating,
                self.selected_tags != {tag.id for tag in self.work.tags},
                self.pending_cover != self.work.cover_member,
            )
        )

    def _confirm_discard_edits(self) -> bool:
        if not self._has_unsaved_edits():
            return True
        return (
            QMessageBox.question(
                self,
                "放弃未保存修改？",
                "标题、星级、封面或 Tag 已被修改。确认放弃本次修改？",
            )
            == QMessageBox.Yes
        )

    def closeEvent(self, event: QCloseEvent) -> None:  # noqa: N802
        if self.editing and not self._confirm_discard_edits():
            event.ignore()
            return
        event.accept()

    def reject(self) -> None:
        if self.editing:
            if not self._confirm_discard_edits():
                return
            self.render_view()
            return
        super().reject()
