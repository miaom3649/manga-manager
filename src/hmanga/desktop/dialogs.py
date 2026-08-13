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
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

from hmanga.catalog import CatalogService
from hmanga.database import Tag, Work
from hmanga.desktop.reader_dialog import pixmap_from_bytes
from hmanga.desktop.tag_widgets import (
    AUTHOR_TAG_COLOR,
    tag_chip_text,
    tag_sort_category,
)
from hmanga.desktop.windowing import FloatingCardDialog, ScreenCenteredDialog
from hmanga.i18n import tr, trf
from hmanga.media import MediaService


def _clear_layout(layout) -> None:
    while layout.count():
        item = layout.takeAt(0)
        if item.widget():
            item.widget().deleteLater()
        elif item.layout():
            _clear_layout(item.layout())
            item.layout().deleteLater()


class MessageCardDialog(FloatingCardDialog):
    """Theme-consistent replacement for informational system message boxes."""

    def __init__(self, title: str, message: str, parent=None, *, danger: bool = False) -> None:
        super().__init__(parent, card_size=QSize(560, 330))
        self.warning_shake = danger
        heading = QLabel(title)
        heading.setAlignment(Qt.AlignCenter)
        heading.setStyleSheet(
            f"font-size: 24px; font-weight: 700; color: {'#ff746c' if danger else 'palette(text)'};"
        )
        details = QLabel(message)
        details.setWordWrap(True)
        details.setAlignment(Qt.AlignCenter)
        okay = QPushButton(tr("label.understood"))
        okay.setFixedHeight(46)
        okay.clicked.connect(self.accept)
        self.card_layout.addWidget(heading)
        self.card_layout.addWidget(details, 1)
        self.card_layout.addWidget(okay)


class ConfirmationCardDialog(FloatingCardDialog):
    def __init__(
        self,
        title: str,
        message: str,
        parent=None,
        *,
        confirm_text: str = tr("confirm.confirm"),
        danger: bool = False,
    ) -> None:
        super().__init__(parent, card_size=QSize(560, 330))
        self.warning_shake = danger
        heading = QLabel(title)
        heading.setAlignment(Qt.AlignCenter)
        heading.setStyleSheet(
            f"font-size: 24px; font-weight: 700; color: {'#ff746c' if danger else 'palette(text)'};"
        )
        details = QLabel(message)
        details.setWordWrap(True)
        details.setAlignment(Qt.AlignCenter)
        buttons = QHBoxLayout()
        cancel = QPushButton(tr("action.cancel"))
        confirm = QPushButton(confirm_text)
        cancel.setFixedHeight(46)
        confirm.setFixedHeight(46)
        if danger:
            confirm.setStyleSheet(
                "QPushButton { background: #d93025; color: white; "
                "border: 2px solid #d93025; border-radius: 10px; font-weight: 700; }"
            )
        cancel.clicked.connect(self.reject)
        confirm.clicked.connect(self.accept)
        buttons.addWidget(cancel, 1)
        buttons.addWidget(confirm, 1)
        self.card_layout.addWidget(heading)
        self.card_layout.addWidget(details, 1)
        self.card_layout.addLayout(buttons)


class ChoiceCardDialog(FloatingCardDialog):
    def __init__(self, title: str, message: str, choices: list[tuple[str, str]], parent=None):
        super().__init__(parent, card_size=QSize(620, 380))
        self.choice: str | None = None
        heading = QLabel(title)
        heading.setAlignment(Qt.AlignCenter)
        heading.setStyleSheet("font-size: 24px; font-weight: 700;")
        details = QLabel(message)
        details.setWordWrap(True)
        details.setAlignment(Qt.AlignCenter)
        self.card_layout.addWidget(heading)
        self.card_layout.addWidget(details, 1)
        for label, value in choices:
            button = QPushButton(label)
            button.setFixedHeight(44)
            button.clicked.connect(partial(self._choose, value))
            self.card_layout.addWidget(button)

    def _choose(self, value: str) -> None:
        self.choice = value
        self.accept()


def choose_action(
    parent,
    title: str,
    message: str,
    choices: list[tuple[str, str]],
) -> str | None:
    dialog = ChoiceCardDialog(title, message, choices, parent)
    dialog.exec()
    return dialog.choice


def show_message(parent, title: str, message: str, *, danger: bool = False) -> None:
    MessageCardDialog(title, message, parent, danger=danger).exec()


def confirm_action(
    parent,
    title: str,
    message: str,
    *,
    confirm_text: str = tr("confirm.confirm"),
    danger: bool = False,
) -> bool:
    return (
        ConfirmationCardDialog(
            title,
            message,
            parent,
            confirm_text=confirm_text,
            danger=danger,
        ).exec()
        == QDialog.Accepted
    )


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


class FlowTagWidget(QWidget):
    """Position naturally sized Tag widgets left-to-right with wrapping."""

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.widgets: list[QWidget] = []
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Minimum)

    def add_tag(self, widget: QWidget) -> None:
        widget.setParent(self)
        self.widgets.append(widget)
        widget.show()
        self._arrange()

    def clear_tags(self) -> None:
        for widget in self.widgets:
            widget.deleteLater()
        self.widgets.clear()
        self.setMinimumHeight(0)

    def resizeEvent(self, event) -> None:  # noqa: N802
        super().resizeEvent(event)
        self._arrange()

    def _arrange(self) -> None:
        spacing = 7
        available = max(1, self.width())
        x, y, row_height = 0, 0, 0
        for widget in self.widgets:
            hint = widget.sizeHint()
            if x and x + hint.width() > available:
                x = 0
                y += row_height + spacing
                row_height = 0
            widget.setGeometry(x, y, hint.width(), hint.height())
            x += hint.width() + spacing
            row_height = max(row_height, hint.height())
        self.setMinimumHeight(y + row_height)


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
        self.setWindowTitle(tr("action.select_cover"))
        self.resize(720, 720)
        root = QVBoxLayout(self)
        self.image = QLabel()
        self.image.setAlignment(Qt.AlignCenter)
        root.addWidget(self.image, 1)
        controls = QHBoxLayout()
        previous = QPushButton(tr("label.previous_image"))
        previous.clicked.connect(lambda: self.move_page(-1))
        self.position = QLabel()
        following = QPushButton(tr("label.next_image"))
        following.clicked.connect(lambda: self.move_page(1))
        controls.addWidget(previous)
        controls.addWidget(self.position, 1, Qt.AlignCenter)
        controls.addWidget(following)
        root.addLayout(controls)
        buttons = QDialogButtonBox(QDialogButtonBox.Save | QDialogButtonBox.Cancel)
        buttons.button(QDialogButtonBox.Save).setText(tr("label.set_as_cover"))
        buttons.accepted.connect(self.choose)
        buttons.rejected.connect(self.reject)
        root.addWidget(buttons)
        self.render()

    def render(self) -> None:
        if not self.members:
            self.image.setText(tr("label.no_selectable_images"))
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
            self.image.setText(trf("error.image_read", error=exc))

    def move_page(self, offset: int) -> None:
        if self.members:
            self.index = min(max(0, self.index + offset), len(self.members) - 1)
            self.render()

    def choose(self) -> None:
        if self.members:
            self.selected_member = self.members[self.index]
            self.accept()


class TagEditDialog(FloatingCardDialog):
    def __init__(self, tag: Tag, catalog: CatalogService, parent=None) -> None:
        super().__init__(parent, card_size=QSize(460, 300))
        self.tag_id = tag.id
        self.catalog = catalog
        title = QLabel(tr("action.edit_tag"))
        title.setAlignment(Qt.AlignCenter)
        title.setStyleSheet("font-size: 23px; font-weight: 700;")
        self.name_edit = QLineEdit(tag.name)
        self.group_box = QComboBox()
        for group in catalog.list_groups():
            self.group_box.addItem(group.name, group.id)
        self.group_box.setCurrentIndex(max(0, self.group_box.findData(tag.group_id)))
        self.group_box.currentIndexChanged.connect(self._group_changed)
        self._group_changed()
        form = QFormLayout()
        form.addRow(tr("label.name"), self.name_edit)
        form.addRow(tr("label.group"), self.group_box)
        save = QPushButton(tr("action.save"))
        save.setStyleSheet(
            "QPushButton { background: #9a6f7b; color: white; "
            "border: 2px solid #9a6f7b; border-radius: 10px; "
            "font-weight: 700; padding: 8px 12px; }"
        )
        save.clicked.connect(self.save)
        self.card_layout.addWidget(title)
        self.card_layout.addLayout(form)
        self.card_layout.addStretch(1)
        self.card_layout.addWidget(save)

    def _group_changed(self) -> None:
        group_name = self.group_box.currentText()
        self.name_edit.setMaxLength(200 if group_name == "作者" else 5)

    def save(self) -> None:
        try:
            self.catalog.edit_tag(
                self.tag_id,
                self.name_edit.text(),
                self.group_box.currentData(),
            )
        except ValueError as exc:
            show_message(self, tr("error.save_failed"), str(exc), danger=True)
            return
        self.accept()


class TagManagerDialog(FloatingCardDialog):
    tag_created = Signal(int)

    def __init__(self, catalog: CatalogService, parent=None) -> None:
        super().__init__(parent, card_size=QSize(560, 520))
        self.catalog = catalog
        self.setWindowTitle(tr("label.manage_tags"))
        root = self.card_layout
        title = QLabel(tr("label.manage_tags"))
        title.setAlignment(Qt.AlignCenter)
        title.setStyleSheet("font-size: 23px; font-weight: 700;")
        root.addWidget(title)
        tag_row = QHBoxLayout()
        self.tag_name = QLineEdit()
        self.tag_name.setMaxLength(5)
        self.tag_name.setPlaceholderText(tr("label.new_tag_name"))
        self.new_tag_group = QComboBox()
        for group in self.catalog.list_groups():
            self.new_tag_group.addItem(group.name, group.id)
        category_index = self.new_tag_group.findText("类别")
        self.new_tag_group.setCurrentIndex(max(0, category_index))
        self.new_tag_group.currentTextChanged.connect(
            lambda name: self.tag_name.setMaxLength(200 if name == "作者" else 5)
        )
        tag_add = QPushButton(tr("action.create_tag"))
        tag_add.clicked.connect(self.create_tag)
        tag_row.addWidget(self.tag_name)
        tag_row.addWidget(self.new_tag_group)
        tag_row.addWidget(tag_add)
        self.items = QVBoxLayout()
        content = QWidget()
        content.setLayout(self.items)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setWidget(content)
        root.addLayout(tag_row)
        root.addWidget(scroll, 1)
        self.refresh()

    def refresh(self) -> None:
        tags = self.catalog.list_tags()
        _clear_layout(self.items)
        for tag in tags:
            row = QWidget()
            layout = QHBoxLayout(row)
            layout.setContentsMargins(4, 2, 4, 2)
            name = QLabel(tag.name)
            name.setToolTip(tag.name)
            name.setAlignment(Qt.AlignCenter)
            name.setStyleSheet(
                "background: "
                + (AUTHOR_TAG_COLOR if self.catalog.is_author_tag(tag) else "#9a6f7b")
                + "; color: white; border-radius: 9px; padding: 4px 9px;"
            )
            layout.addWidget(name, 1)
            work_count = QLabel(trf("works.count", count=len(tag.works)))
            work_count.setFixedWidth(76)
            work_count.setAlignment(Qt.AlignCenter)
            layout.addWidget(work_count)
            edit = QPushButton(tr("action.edit"))
            edit.clicked.connect(partial(self.edit_tag, tag))
            layout.addWidget(edit)
            remove = QPushButton(tr("action.delete"))
            remove.clicked.connect(partial(self.delete_tag, tag))
            layout.addWidget(remove)
            self.items.addWidget(row)
        self.items.addStretch(1)

    def edit_tag(self, tag: Tag) -> None:
        if TagEditDialog(tag, self.catalog, self).exec() == QDialog.Accepted:
            self.refresh()

    def create_tag(self) -> None:
        try:
            tag = self.catalog.create_tag(
                self.tag_name.text(),
                self.new_tag_group.currentData(),
            )
        except ValueError as exc:
            show_message(self, tr("error.create_failed"), str(exc), danger=True)
            return
        self.tag_name.clear()
        self.refresh()
        self.tag_created.emit(tag.id)

    def delete_tag(self, tag: Tag) -> None:
        count = len(tag.works)
        if not confirm_action(
            self,
            tr("confirm.confirm_delete_tag"),
            trf("tag.delete_confirm", name=tag.name, count=count),
            confirm_text=tr("action.delete_tag"),
            danger=True,
        ):
            return
        self.catalog.delete_tag(tag.id)
        self.refresh()

    def reject(self) -> None:
        pending = self.tag_name.text()
        if pending.strip():
            if not confirm_action(
                self,
                tr("confirm.discard_unsubmitted_input_title"),
                tr("confirm.close_with_uncreated_tag"),
                confirm_text=tr("label.discard_and_close"),
                danger=True,
            ):
                return
        super().reject()


def open_tag_management(catalog: CatalogService, parent=None) -> list[int]:
    created: list[int] = []
    dialog = TagManagerDialog(catalog, parent)
    dialog.tag_created.connect(created.append)
    dialog.exec()
    return created


class ResetSettingsDialog(FloatingCardDialog):
    def __init__(self, parent=None) -> None:
        super().__init__(parent, card_size=QSize(560, 360))
        self.warning_shake = True
        title = QLabel(tr("action.reset_all_settings"))
        title.setAlignment(Qt.AlignCenter)
        title.setStyleSheet("font-size: 25px; font-weight: 700; color: #d93025;")
        warning = QLabel(tr("confirm.reset_all_settings_warning"))
        warning.setWordWrap(True)
        warning.setAlignment(Qt.AlignLeft | Qt.AlignVCenter)
        cancel = QPushButton(tr("action.cancel"))
        cancel.clicked.connect(self.reject)
        confirm = QPushButton(tr("confirm.confirm_reset_all_settings"))
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


class DeleteWorkDialog(FloatingCardDialog):
    def __init__(self, file_name: str, parent=None) -> None:
        super().__init__(parent, card_size=QSize(560, 320))
        self.warning_shake = True
        title = QLabel(tr("action.delete_work"))
        title.setAlignment(Qt.AlignCenter)
        title.setStyleSheet("font-size: 25px; font-weight: 700; color: #e53935;")
        warning = QLabel(trf("work.delete_confirm", file_name=file_name))
        warning.setWordWrap(True)
        warning.setAlignment(Qt.AlignCenter)
        buttons = QHBoxLayout()
        cancel = QPushButton(tr("action.cancel"))
        confirm = QPushButton(tr("confirm.confirm_delete"))
        cancel.setFixedHeight(46)
        confirm.setFixedHeight(46)
        confirm.setStyleSheet(
            "QPushButton { background: #e53935; color: white; "
            "border: 2px solid #e53935; border-radius: 10px; "
            "font-weight: 700; padding: 10px 14px; }"
        )
        cancel.clicked.connect(self.reject)
        confirm.clicked.connect(self.accept)
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
        cancel = QPushButton(tr("action.cancel") if overwrite else tr("label.understood"))
        cancel.setFixedHeight(46)
        cancel.clicked.connect(self.reject)
        buttons.addWidget(cancel, 1)
        if overwrite:
            confirm = QPushButton(tr("action.overwrite"))
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
    deletion_requested = Signal(int)
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
        self._catalog_revision = catalog.revision
        self.setWindowTitle(tr("label.work_detail"))
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
        self.sync_timer = QTimer(self)
        self.sync_timer.setInterval(500)
        self.sync_timer.timeout.connect(self._sync_catalog_revision)
        self.sync_timer.start()

    def render_view(self) -> None:
        self.editing = False
        self._catalog_revision = self.catalog.revision
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
            cover.setText(trf("error.cover_read", error=exc))
        self.root.addWidget(cover)
        title = QLabel(work.title or work.file_name.rsplit(".", 1)[0])
        title.setStyleSheet("font-size: 25px; font-weight: 700")
        self.root.addWidget(title)
        self.root.addWidget(
            QLabel(work.number or (work.file_name if work.kind == "illustration" else ""))
        )
        self.root.addWidget(QLabel("★" * work.rating + "☆" * (3 - work.rating)))
        tags = self.catalog.list_tags()
        tag_widget = FlowTagWidget()
        custom_tag_entries = [
            (
                self.catalog.tag_display_name(tag, tags),
                AUTHOR_TAG_COLOR
                if self.catalog.is_author_tag(tag)
                else "#9a6f7b"
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
            (
                tr("label.comic") if work.kind == "comic" else tr("label.illustration"),
                "#4f7c78",
                3,
                None,
            ),
            *custom_tag_entries,
        ]
        for name, color, _category, tag_id in tag_entries:
            label = ClickableTagLabel(tag_chip_text(name))
            label.setObjectName("detailTag")
            label.setAlignment(Qt.AlignCenter)
            label.setToolTip(name)
            label.setFixedHeight(26)
            label.setStyleSheet(
                f"background: {color}; color: white; border-radius: 9px; padding: 3px 8px;"
            )
            if tag_id is None:
                label.clicked.connect(
                    lambda checked_kind=work.kind: self.filter_by_kind(checked_kind)
                )
            else:
                label.clicked.connect(partial(self.filter_by_tag, tag_id))
            tag_widget.add_tag(label)
        self.root.addWidget(tag_widget)
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
                self.root.addWidget(QLabel(tr("label.no_previews")))
            read = QPushButton(tr("label.start_reading"))
            read.setStyleSheet(
                "QPushButton { background: #9a6f7b; color: white; "
                "border: 2px solid #9a6f7b; border-radius: 10px; "
                "font-weight: 700; padding: 8px 12px; }"
            )
            read.clicked.connect(self.start_reading)
            self.root.addWidget(read)
        edit = QPushButton(tr("action.edit"))
        edit.clicked.connect(self.render_edit)
        self.root.addWidget(edit)
        remove = QPushButton(tr("action.delete_work"))
        remove.setStyleSheet(
            "QPushButton { background: transparent; color: #ff746c; "
            "border: 2px solid #e53935; border-radius: 10px; "
            "font-weight: 700; padding: 8px 12px; } "
            "QPushButton:hover { background: rgba(229, 57, 53, 35); }"
        )
        remove.clicked.connect(self.delete_work)
        self.root.addWidget(remove)
        self.root.addStretch(1)

    def _sync_catalog_revision(self) -> None:
        if self.editing or self.catalog.revision == self._catalog_revision:
            return
        self.render_view()

    def delete_work(self) -> None:
        assert self.work is not None
        if DeleteWorkDialog(self.work.file_name, self).exec() != QDialog.Accepted:
            return
        self.deletion_requested.emit(self.work.id)
        self.accept()

    def filter_by_kind(self, kind: str) -> None:
        self.kind_filter_requested.emit(kind)
        self.accept()

    def filter_by_tag(self, tag_id: int) -> None:
        assert self.work is not None
        self.tag_filter_requested.emit(tag_id, self.work.kind)
        self.accept()

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
        form.addRow(tr("label.title"), self.title_edit)
        form.addRow(tr("label.rating_zero_to_three"), self.rating_edit)
        self.root.addLayout(form)
        self.tag_search_edit = QLineEdit()
        self.tag_search_edit.setPlaceholderText(tr("label.search_tags_or_hidden_groups"))
        self.tag_search_edit.textChanged.connect(self.refresh_tag_choices)
        self.root.addWidget(self.tag_search_edit)
        self.tag_content = FlowTagWidget()
        tag_scroll = QScrollArea()
        tag_scroll.setWidgetResizable(True)
        tag_scroll.setFrameShape(QFrame.NoFrame)
        tag_scroll.setMinimumHeight(250)
        tag_scroll.setWidget(self.tag_content)
        self.selected_tags = {tag.id for tag in self.work.tags}
        self.pending_cover = self.work.cover_member
        self.refresh_tag_choices()
        self.root.addWidget(tag_scroll, 1)
        manage = QPushButton(tr("label.manage_tags"))
        manage.clicked.connect(self.manage_tags)
        self.root.addWidget(manage)
        if self.work.kind == "comic":
            cover = QPushButton(tr("label.change_cover"))
            cover.clicked.connect(self.choose_cover)
            self.root.addWidget(cover)
        save = QPushButton(tr("action.save"))
        save.setStyleSheet(
            "QPushButton { background: #9a6f7b; color: white; "
            "border: 2px solid #9a6f7b; border-radius: 10px; "
            "font-weight: 700; padding: 8px 12px; }"
        )
        save.clicked.connect(self.save)
        self.root.addWidget(save)

    def refresh_tag_choices(self) -> None:
        self.tag_content.clear_tags()
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
        for tag, display_name, _category in tag_choices:
            button = QPushButton(display_name, self.tag_content)
            button.setCheckable(True)
            button.setChecked(tag.id in self.selected_tags)
            button.setFixedHeight(26)
            button.setToolTip(display_name)
            color = (
                AUTHOR_TAG_COLOR
                if self.catalog.is_author_tag(tag)
                else "#9a6f7b"
                if tag.group_id is not None
                else "#777"
            )
            button.setStyleSheet(
                "QPushButton { background: transparent; color: palette(text); "
                f"border: 1px solid {color}; border-radius: 9px; padding: 0 8px; }} "
                f"QPushButton:checked {{ background: {color}; color: white; font-weight: 700; }}"
            )
            button.toggled.connect(partial(self.toggle_tag, tag.id))
            self.tag_content.add_tag(button)

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
        return confirm_action(
            self,
            tr("confirm.discard_unsaved_changes_title"),
            tr("confirm.discard_work_edits_message"),
            confirm_text=tr("label.discard_changes"),
            danger=True,
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
