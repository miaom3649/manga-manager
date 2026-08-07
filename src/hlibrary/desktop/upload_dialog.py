from __future__ import annotations

import zipfile
from pathlib import Path

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMessageBox,
    QPushButton,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

from hlibrary.catalog import CatalogService
from hlibrary.desktop.dialogs import TagManagerDialog
from hlibrary.desktop.reader_dialog import pixmap_from_bytes
from hlibrary.media import IMAGE_SUFFIXES
from hlibrary.text import natural_key
from hlibrary.upload import UploadService, UploadTask


class StagedCoverDialog(QDialog):
    def __init__(self, archive_path: Path, current: str | None, parent=None) -> None:
        super().__init__(parent)
        self.archive_path = archive_path
        with zipfile.ZipFile(archive_path) as archive:
            self.members = sorted(
                [
                    info.filename
                    for info in archive.infolist()
                    if not info.is_dir() and Path(info.filename).suffix.casefold() in IMAGE_SUFFIXES
                ],
                key=natural_key,
            )
        self.index = self.members.index(current) if current in self.members else 0
        self.selected = current
        self.resize(650, 650)
        self.setWindowTitle("选择上传作品封面")
        root = QVBoxLayout(self)
        self.image = QLabel()
        self.image.setAlignment(Qt.AlignCenter)
        root.addWidget(self.image, 1)
        row = QHBoxLayout()
        previous = QPushButton("上一张")
        previous.clicked.connect(lambda: self.move(-1))
        self.position = QLabel()
        following = QPushButton("下一张")
        following.clicked.connect(lambda: self.move(1))
        row.addWidget(previous)
        row.addWidget(self.position, 1, Qt.AlignCenter)
        row.addWidget(following)
        root.addLayout(row)
        buttons = QDialogButtonBox(QDialogButtonBox.Save | QDialogButtonBox.Cancel)
        buttons.button(QDialogButtonBox.Save).setText("设为封面")
        buttons.accepted.connect(self.select)
        buttons.rejected.connect(self.reject)
        root.addWidget(buttons)
        self.render()

    def render(self) -> None:
        if not self.members:
            return
        with zipfile.ZipFile(self.archive_path) as archive:
            pixmap = pixmap_from_bytes(archive.read(self.members[self.index]))
        self.image.setPixmap(pixmap.scaled(560, 520, Qt.KeepAspectRatio, Qt.SmoothTransformation))
        self.position.setText(f"{self.index + 1}/{len(self.members)} · {self.members[self.index]}")

    def move(self, offset: int) -> None:
        self.index = min(max(0, self.index + offset), len(self.members) - 1)
        self.render()

    def select(self) -> None:
        self.selected = self.members[self.index]
        self.accept()


class UploadDialog(QDialog):
    committed = Signal()

    def __init__(
        self,
        sources: list[Path],
        uploads: UploadService,
        catalog: CatalogService,
        parent=None,
    ) -> None:
        super().__init__(parent)
        self.uploads = uploads
        self.catalog = catalog
        self.task: UploadTask = uploads.prepare(sources)
        self.current_index = -1
        self.setWindowTitle("上传作品")
        self.resize(820, 650)
        root = QVBoxLayout(self)
        valid = len(self.task.items) - len(self.task.invalid)
        root.addWidget(
            QLabel(
                f"共 {len(self.task.items)} 个文件 · 有效 {valid} · "
                f"异常 {len(self.task.invalid)} · 同名 {len(self.task.conflicts)}"
            )
        )
        root.addWidget(QLabel("整批公共 Tag（单项中仍可取消）"))
        common_row = QHBoxLayout()
        all_tags = self.catalog.list_tags()
        for tag in all_tags:
            button = QPushButton(self.catalog.tag_display_name(tag, all_tags))
            button.setCheckable(True)
            button.toggled.connect(
                lambda checked, tag_id=tag.id: self.toggle_common_tag(tag_id, checked)
            )
            common_row.addWidget(button)
        common_row.addStretch(1)
        root.addLayout(common_row)
        content = QHBoxLayout()
        self.files = QListWidget()
        self.populate_files()
        remove_file = QPushButton("从任务中移除所选文件")
        remove_file.clicked.connect(self.remove_selected)
        file_column = QVBoxLayout()
        file_column.addWidget(self.files, 1)
        file_column.addWidget(remove_file)
        content.addLayout(file_column, 1)
        self.files.currentItemChanged.connect(self.change_item)
        editor = QWidget()
        editor_layout = QVBoxLayout(editor)
        form = QFormLayout()
        self.title_edit = QLineEdit()
        self.rating_edit = QSpinBox()
        self.rating_edit.setRange(0, 3)
        form.addRow("标题", self.title_edit)
        form.addRow("星级", self.rating_edit)
        editor_layout.addLayout(form)
        self.cover_button = QPushButton("更改封面")
        self.cover_button.clicked.connect(self.choose_cover)
        editor_layout.addWidget(self.cover_button)
        editor_layout.addWidget(QLabel("Tag（点击切换）"))
        self.tag_layout = QVBoxLayout()
        editor_layout.addLayout(self.tag_layout)
        manage = QPushButton("管理 Tag")
        manage.clicked.connect(self.manage_tags)
        editor_layout.addWidget(manage)
        editor_layout.addStretch(1)
        content.addWidget(editor, 1)
        root.addLayout(content, 1)
        buttons = QDialogButtonBox(QDialogButtonBox.Save | QDialogButtonBox.Cancel)
        buttons.button(QDialogButtonBox.Save).setText("确定上传")
        buttons.accepted.connect(self.commit)
        buttons.rejected.connect(self.reject)
        root.addWidget(buttons)
        if self.task.items:
            self.files.setCurrentRow(0)

    def populate_files(self) -> None:
        self.files.clear()
        for index, item in enumerate(self.task.items):
            status = "可上传" if item.valid else f"不可上传：{item.error}"
            if item.conflict:
                status += " · 将覆盖同名作品"
            row = QListWidgetItem(f"{item.source.name}\n{status}")
            row.setData(Qt.UserRole, index)
            self.files.addItem(row)

    def remove_selected(self) -> None:
        row = self.files.currentRow()
        if row < 0:
            return
        self.save_current()
        item = self.task.items.pop(row)
        item.staged.unlink(missing_ok=True)
        self.current_index = -1
        self.populate_files()
        if self.task.items:
            self.files.setCurrentRow(min(row, len(self.task.items) - 1))

    def save_current(self) -> None:
        if self.current_index < 0:
            return
        item = self.task.items[self.current_index]
        item.title = self.title_edit.text()
        item.rating = self.rating_edit.value()

    def change_item(self, current, _previous) -> None:
        self.save_current()
        if current is None:
            self.current_index = -1
            return
        self.current_index = current.data(Qt.UserRole)
        item = self.task.items[self.current_index]
        self.title_edit.setText(item.title)
        self.rating_edit.setValue(item.rating)
        self.title_edit.setEnabled(item.valid)
        self.rating_edit.setEnabled(item.valid)
        self.cover_button.setVisible(item.kind == "comic" and item.valid)
        self.refresh_tags()

    def refresh_tags(self) -> None:
        while self.tag_layout.count():
            child = self.tag_layout.takeAt(0)
            if child.widget():
                child.widget().deleteLater()
        if self.current_index < 0:
            return
        item = self.task.items[self.current_index]
        tags = self.catalog.list_tags()
        for tag in tags:
            button = QPushButton(self.catalog.tag_display_name(tag, tags))
            button.setCheckable(True)
            button.setChecked(tag.id in item.tag_ids)
            button.toggled.connect(lambda checked, tag_id=tag.id: self.toggle_tag(tag_id, checked))
            self.tag_layout.addWidget(button)

    def toggle_tag(self, tag_id: int, checked: bool) -> None:
        item = self.task.items[self.current_index]
        item.tag_ids.add(tag_id) if checked else item.tag_ids.discard(tag_id)

    def toggle_common_tag(self, tag_id: int, checked: bool) -> None:
        for item in self.task.items:
            if checked:
                item.tag_ids.add(tag_id)
            else:
                item.tag_ids.discard(tag_id)
        self.refresh_tags()

    def manage_tags(self) -> None:
        TagManagerDialog(self.catalog, self).exec()
        self.refresh_tags()

    def choose_cover(self) -> None:
        if self.current_index < 0:
            return
        item = self.task.items[self.current_index]
        dialog = StagedCoverDialog(item.staged, item.cover_member, self)
        if dialog.exec() == QDialog.Accepted:
            item.cover_member = dialog.selected

    def commit(self) -> None:
        self.save_current()
        if self.task.invalid:
            QMessageBox.warning(self, "无法上传", "请先取消任务；当前任务包含不合格文件。")
            return
        allow_overwrite = False
        if self.task.conflicts:
            names = "\n".join(item.source.name for item in self.task.conflicts)
            answer = QMessageBox.question(
                self,
                "同名文件",
                f"以下文件已存在：\n{names}\n\n覆盖会使用本页面填写的新资料。是否覆盖整批重名文件？",
            )
            if answer != QMessageBox.Yes:
                return
            allow_overwrite = True
            final = QMessageBox.question(
                self,
                "最终确认",
                f"即将上传 {len(self.task.items)} 个文件，其中覆盖 "
                f"{len(self.task.conflicts)} 个。确认后才会真正写入。",
            )
            if final != QMessageBox.Yes:
                return
        try:
            self.uploads.commit(self.task, allow_overwrite)
        except Exception as exc:
            QMessageBox.critical(self, "上传失败", f"文件和资料已回滚。\n{exc}")
            return
        self.committed.emit()
        self.accept()

    def reject(self) -> None:
        self.uploads.cancel(self.task)
        super().reject()
