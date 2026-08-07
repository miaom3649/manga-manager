from __future__ import annotations

import json
from pathlib import Path

from PySide6.QtCore import QSize, Qt, QTimer, Signal
from PySide6.QtGui import QAction, QCloseEvent, QColor, QIcon, QMovie, QPainter, QPixmap
from PySide6.QtWidgets import (
    QApplication,
    QComboBox,
    QFileDialog,
    QFrame,
    QGraphicsDropShadowEffect,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMainWindow,
    QMessageBox,
    QPushButton,
    QRadioButton,
    QScrollArea,
    QSpinBox,
    QStackedWidget,
    QStyle,
    QSystemTrayIcon,
    QVBoxLayout,
    QWidget,
)

from hlibrary import __version__
from hlibrary.appearance import AppearanceService, apply_theme
from hlibrary.backup import BackupService
from hlibrary.cache import CacheService
from hlibrary.catalog import CatalogQuery, CatalogService
from hlibrary.config import APP_NAME
from hlibrary.controller import LibraryController
from hlibrary.desktop.dialogs import TagManagerDialog, WorkDetailDialog
from hlibrary.desktop.pairing_dialog import PairingDialog
from hlibrary.desktop.upload_dialog import UploadDialog
from hlibrary.library import LibraryService, ScanResult
from hlibrary.media import MediaService
from hlibrary.migration import MigrationService
from hlibrary.notifications import NotificationService
from hlibrary.pairing import PairingService
from hlibrary.upload import UploadService


class MainWindow(QMainWindow):
    request_exit = Signal()
    notification_count_changed = Signal(int)

    def __init__(
        self,
        controller: LibraryController,
        library: LibraryService,
        catalog: CatalogService,
        media: MediaService,
        uploads: UploadService,
        pairing: PairingService,
        backups: BackupService,
        migrations: MigrationService,
        cache: CacheService,
        notifications: NotificationService,
        appearance: AppearanceService,
    ) -> None:
        super().__init__()
        self.controller = controller
        self.library = library
        self.catalog = catalog
        self.media = media
        self.uploads = uploads
        self.pairing = pairing
        self.backups = backups
        self.migrations = migrations
        self.cache = cache
        self.notifications = notifications
        self.appearance = appearance
        self._startup_backup_checked = False
        self.current_page = 1
        self.selected_kinds: set[str] = set()
        self.selected_tag_ids: set[int] = set()
        self.search_timer = QTimer(self)
        self.search_timer.setSingleShot(True)
        self.search_timer.setInterval(400)
        self.search_timer.timeout.connect(self.refresh_works)
        self.setWindowTitle(f"{APP_NAME} {__version__}")
        self.setAcceptDrops(True)
        self.resize(1100, 720)
        self._allow_close = False

        root = QWidget(self)
        layout = QHBoxLayout(root)
        layout.setContentsMargins(0, 0, 0, 0)

        self.navigation = QListWidget()
        self.navigation.setFixedWidth(120)
        self.navigation.addItems(["作品", "通知", "设置"])
        self.navigation.setCurrentRow(0)

        self.pages = QStackedWidget()
        self.pages.addWidget(self._build_home_page())
        self.pages.addWidget(self._build_notifications_page())
        self.pages.addWidget(self._build_settings_page())
        self.navigation.currentRowChanged.connect(self._navigation_changed)

        layout.addWidget(self.navigation)
        layout.addWidget(self.pages, 1)
        self.setCentralWidget(root)
        controller.scan_started.connect(self._scan_started)
        controller.scan_finished.connect(self._scan_finished)
        controller.scan_failed.connect(self._scan_failed)
        self.refresh()

    def _build_home_page(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        title = QLabel("作品")
        title.setStyleSheet("font-size: 32px; font-weight: 700;")
        actions = QHBoxLayout()
        self.root_label = QLabel("尚未设置漫画目录")
        self.root_label.setTextInteractionFlags(Qt.TextSelectableByMouse)
        self.choose_button = QPushButton("选择漫画目录")
        self.choose_button.clicked.connect(self.choose_root)
        self.scan_button = QPushButton("重新扫描")
        self.scan_button.clicked.connect(self.controller.request_scan)
        actions.addWidget(self.root_label, 1)
        actions.addWidget(self.choose_button)
        actions.addWidget(self.scan_button)

        search_row = QHBoxLayout()
        self.search_edit = QLineEdit()
        self.search_edit.setPlaceholderText("搜索编号或标题，多个关键词用英文逗号分隔")
        self.search_edit.textChanged.connect(self._search_changed)
        self.search_edit.returnPressed.connect(self._search_now)
        self.sort_box = QComboBox()
        self.sort_box.addItem("最近添加", "added")
        self.sort_box.addItem("文件名/编号", "file_name")
        self.sort_box.addItem("标题", "title")
        self.sort_box.addItem("星级", "rating")
        saved_sort = self.catalog.setting("windows_sort_field", "added")
        self.sort_box.setCurrentIndex(max(0, self.sort_box.findData(saved_sort)))
        self.direction_button = QPushButton("降序 ↓")
        self.direction_button.setCheckable(True)
        ascending = self.catalog.setting("windows_sort_direction", "desc") == "asc"
        self.direction_button.setChecked(ascending)
        self.direction_button.setText("升序 ↑" if ascending else "降序 ↓")
        self.sort_box.currentIndexChanged.connect(self._filters_changed)
        self.direction_button.clicked.connect(self._direction_changed)
        manage_tags = QPushButton("管理 Tag")
        manage_tags.clicked.connect(self.open_tag_manager)
        upload = QPushButton("上传")
        upload.clicked.connect(self.choose_uploads)
        search_row.addWidget(self.search_edit, 1)
        search_row.addWidget(self.sort_box)
        search_row.addWidget(self.direction_button)
        search_row.addWidget(manage_tags)
        search_row.addWidget(upload)

        self.scan_status = QLabel("等待扫描")
        content_row = QHBoxLayout()
        filters = self._build_filter_panel()
        self.work_list = QListWidget()
        self.work_list.itemActivated.connect(self.open_work)
        self.work_list.itemClicked.connect(self.open_work)
        page_row = QHBoxLayout()
        self.first_page = QPushButton("首页")
        self.previous_page = QPushButton("上一页")
        self.page_label = QLabel("第 1 / 1 页")
        self.next_page = QPushButton("下一页")
        self.last_page = QPushButton("末页")
        self.page_jump = QSpinBox()
        self.page_jump.setMinimum(1)
        jump_button = QPushButton("跳转")
        jump_button.clicked.connect(lambda: self.go_page(self.page_jump.value()))
        self.first_page.clicked.connect(lambda: self.go_page(1))
        self.previous_page.clicked.connect(lambda: self.go_page(self.current_page - 1))
        self.next_page.clicked.connect(lambda: self.go_page(self.current_page + 1))
        self.last_page.clicked.connect(lambda: self.go_page(self.total_pages))
        for widget in (
            self.first_page,
            self.previous_page,
            self.page_label,
            self.next_page,
            self.last_page,
            self.page_jump,
            jump_button,
        ):
            page_row.addWidget(widget)
        page_row.addStretch(1)
        layout.addWidget(title)
        layout.addLayout(actions)
        layout.addLayout(search_row)
        layout.addWidget(self.scan_status)
        content_row.addWidget(filters)
        content_row.addWidget(self.work_list, 1)
        layout.addLayout(content_row, 1)
        layout.addLayout(page_row)
        return page

    def _build_filter_panel(self) -> QWidget:
        panel = QGroupBox("Tag 筛选")
        panel.setFixedWidth(210)
        layout = QVBoxLayout(panel)
        self.tag_search = QLineEdit()
        self.tag_search.setPlaceholderText("搜索 Tag 或分组")
        self.tag_search.textChanged.connect(self._refresh_filter_tags)
        layout.addWidget(self.tag_search)
        kind_row = QHBoxLayout()
        self.comic_filter = QPushButton("漫画")
        self.illustration_filter = QPushButton("插画")
        for button, kind in (
            (self.comic_filter, "comic"),
            (self.illustration_filter, "illustration"),
        ):
            button.setCheckable(True)
            button.setStyleSheet(
                "QPushButton { background: #006a6a; color: white; border-radius: 10px; } "
                "QPushButton:checked { background: #004f4f; }"
            )
            button.toggled.connect(lambda checked, value=kind: self._kind_toggled(value, checked))
            kind_row.addWidget(button)
        layout.addLayout(kind_row)
        self.rating_filter = QComboBox()
        self.rating_filter.addItem("全部星级", ("any", 0))
        self.rating_filter.addItem("未评价", ("unrated", 0))
        for rating in range(1, 4):
            self.rating_filter.addItem("★" * rating, ("exact", rating))
        for rating in range(1, 4):
            self.rating_filter.addItem("★" * rating + " 及以上", ("at_least", rating))
        self.rating_filter.currentIndexChanged.connect(self._filters_changed)
        layout.addWidget(self.rating_filter)
        mode_row = QHBoxLayout()
        self.any_tags = QRadioButton("任意匹配")
        self.all_tags = QRadioButton("全部匹配")
        self.any_tags.setChecked(True)
        self.any_tags.toggled.connect(self._filters_changed)
        mode_row.addWidget(self.any_tags)
        mode_row.addWidget(self.all_tags)
        layout.addLayout(mode_row)
        tag_content = QWidget()
        self.tag_filter_layout = QVBoxLayout(tag_content)
        self.tag_filter_layout.setContentsMargins(0, 0, 0, 0)
        tag_scroll = QScrollArea()
        tag_scroll.setWidgetResizable(True)
        tag_scroll.setWidget(tag_content)
        layout.addWidget(tag_scroll, 1)
        clear = QPushButton("清除全部筛选")
        clear.clicked.connect(self.clear_filters)
        layout.addWidget(clear)
        self._refresh_filter_tags()
        return panel

    def _refresh_filter_tags(self) -> None:
        while self.tag_filter_layout.count():
            item = self.tag_filter_layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()
        all_tags = self.catalog.list_tags()
        for tag in self.catalog.list_tags(self.tag_search.text()):
            button = QPushButton(self.catalog.tag_display_name(tag, all_tags))
            button.setCheckable(True)
            button.setChecked(tag.id in self.selected_tag_ids)
            button.setProperty("grouped", tag.group_id is not None)
            button.setStyleSheet(
                "QPushButton { background: #6750a4; color: white; border-radius: 10px; }"
                if tag.group_id is not None
                else "QPushButton { background: #777; color: white; border-radius: 10px; }"
            )
            button.toggled.connect(
                lambda checked, tag_id=tag.id: self._tag_filter_toggled(tag_id, checked)
            )
            self.tag_filter_layout.addWidget(button)
        self.tag_filter_layout.addStretch(1)

    def _kind_toggled(self, kind: str, checked: bool) -> None:
        if checked:
            self.selected_kinds.add(kind)
        else:
            self.selected_kinds.discard(kind)
        self._filters_changed()

    def _tag_filter_toggled(self, tag_id: int, checked: bool) -> None:
        if checked:
            self.selected_tag_ids.add(tag_id)
        else:
            self.selected_tag_ids.discard(tag_id)
        self._filters_changed()

    def clear_filters(self) -> None:
        self.selected_kinds.clear()
        self.selected_tag_ids.clear()
        self.comic_filter.setChecked(False)
        self.illustration_filter.setChecked(False)
        self.rating_filter.setCurrentIndex(0)
        self.any_tags.setChecked(True)
        self.tag_search.clear()
        self._refresh_filter_tags()
        self._filters_changed()

    def _build_notifications_page(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        title = QLabel("通知")
        title.setStyleSheet("font-size: 32px; font-weight: 700;")
        self.notification_list = QListWidget()
        self.notification_list.itemActivated.connect(self.open_notification)
        notification_actions = QHBoxLayout()
        delete_selected = QPushButton("删除所选通知")
        delete_selected.clicked.connect(self.delete_notification)
        clear = QPushButton("清空通知")
        clear.clicked.connect(self.clear_notifications)
        notification_actions.addWidget(delete_selected)
        notification_actions.addWidget(clear)
        notification_actions.addStretch(1)
        layout.addWidget(title)
        layout.addLayout(notification_actions)
        layout.addWidget(self.notification_list, 1)
        return page

    def _build_settings_page(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        title = QLabel("设置")
        title.setStyleSheet("font-size: 32px; font-weight: 700;")
        self.settings_root = QLabel()
        self.settings_root.setTextInteractionFlags(Qt.TextSelectableByMouse)
        choose = QPushButton("更换并迁移作品目录")
        choose.clicked.connect(self.migrate_root)
        pair = QPushButton("手机配对与设备管理")
        pair.clicked.connect(self.open_pairing)
        manual_backup = QPushButton("立即手动备份")
        manual_backup.clicked.connect(self.create_manual_backup)
        restore_backup = QPushButton("恢复备份")
        restore_backup.clicked.connect(self.restore_backup)
        cache_row = QHBoxLayout()
        self.cache_usage = QLabel()
        self.cache_limit = QComboBox()
        for label, value in (
            ("1 GB", 1024**3),
            ("2 GB", 2 * 1024**3),
            ("5 GB", 5 * 1024**3),
            ("不限", None),
        ):
            self.cache_limit.addItem(label, value)
        self.cache_limit.setCurrentIndex(max(0, self.cache_limit.findData(self.cache.limit())))
        self.cache_limit.currentIndexChanged.connect(self.change_cache_limit)
        clear_cache = QPushButton("清理缩略图缓存")
        clear_cache.clicked.connect(self.clear_cache)
        cache_row.addWidget(self.cache_usage)
        cache_row.addWidget(self.cache_limit)
        cache_row.addWidget(clear_cache)
        theme_row = QHBoxLayout()
        theme_row.addWidget(QLabel("外观主题"))
        self.theme_box = QComboBox()
        self.theme_box.addItem("跟随系统", "system")
        self.theme_box.addItem("浅色", "light")
        self.theme_box.addItem("深色", "dark")
        self.theme_box.setCurrentIndex(max(0, self.theme_box.findData(self.appearance.theme())))
        self.theme_box.currentIndexChanged.connect(self.change_theme)
        theme_row.addWidget(self.theme_box)
        theme_row.addStretch(1)
        layout.addWidget(title)
        layout.addWidget(self.settings_root)
        layout.addWidget(choose, alignment=Qt.AlignLeft)
        layout.addWidget(pair, alignment=Qt.AlignLeft)
        layout.addWidget(manual_backup, alignment=Qt.AlignLeft)
        layout.addWidget(restore_backup, alignment=Qt.AlignLeft)
        layout.addLayout(cache_row)
        layout.addLayout(theme_row)
        layout.addStretch(1)
        return page

    def choose_root(self) -> None:
        current = self.library.library_root()
        selected = QFileDialog.getExistingDirectory(
            self,
            "选择 H库 漫画主目录",
            str(current or ""),
        )
        if selected:
            self.controller.configure_root(Path(selected))
            self.refresh()

    def open_pairing(self) -> None:
        PairingDialog(self.pairing, self).exec()

    def migrate_root(self) -> None:
        current = self.library.library_root()
        selected = QFileDialog.getExistingDirectory(
            self, "选择新的 H库 主目录", str(current.parent if current else "")
        )
        if not selected:
            return
        try:
            preview = self.migrations.preview(Path(selected))
        except Exception as exc:
            QMessageBox.critical(self, "无法迁移", str(exc))
            return
        if preview.conflicts or preview.missing:
            details = ""
            if preview.conflicts:
                details += "同名冲突：\n" + "\n".join(preview.conflicts) + "\n"
            if preview.missing:
                details += "文件丢失：\n" + "\n".join(preview.missing)
            QMessageBox.warning(self, "迁移预检未通过", details)
            return
        answer = QMessageBox.question(
            self,
            "确认迁移作品目录",
            f"将迁移 {preview.files} 个已收录作品（{preview.bytes / 1024 / 1024:.1f} MB）。"
            "异常文件、未知目录和旧备份不会迁移。是否继续？",
        )
        if answer != QMessageBox.Yes:
            return
        self.controller.pause_watching()
        self.controller.wait_until_idle()
        try:
            result = self.migrations.migrate(Path(selected))
            self.controller.start()
        except Exception as exc:
            self.controller.start()
            QMessageBox.critical(self, "迁移失败", f"迁移已回滚。\n{exc}")
            return
        QMessageBox.information(
            self,
            "迁移完成",
            f"已迁移 {result.files} 个作品。"
            + ("旧目录已为空并删除。" if result.old_root_removed else "旧目录含其他内容，已保留。"),
        )
        self.refresh()

    def create_manual_backup(self) -> None:
        try:
            path = self.backups.create("手动")
        except Exception as exc:
            QMessageBox.critical(self, "备份失败", str(exc))
            return
        QMessageBox.information(self, "备份完成", f"备份已保存：\n{path}")

    def change_cache_limit(self) -> None:
        self.cache.set_limit(self.cache_limit.currentData())
        self.cache_usage.setText(f"缩略图缓存：{self.cache.usage() / 1024 / 1024:.1f} MB")

    def clear_cache(self) -> None:
        removed = self.cache.clear()
        self.cache_usage.setText("缩略图缓存：0.0 MB")
        QMessageBox.information(self, "缓存已清理", f"已删除 {removed} 个缓存文件。")

    def change_theme(self) -> None:
        theme = self.theme_box.currentData()
        self.appearance.set_theme(theme)
        app = QApplication.instance()
        if app:
            apply_theme(app, theme)

    def restore_backup(self) -> None:
        selected, _ = QFileDialog.getOpenFileName(
            self,
            "选择 H库 备份",
            str(self.backups.backup_directory()),
            "H库备份 (*.sqlite)",
        )
        if not selected:
            return
        answer = QMessageBox.question(
            self,
            "确认恢复备份",
            "恢复会覆盖当前管理资料，但不会修改漫画 ZIP 或插画原文件。"
            "恢复前会先创建保护备份。是否继续？",
        )
        if answer != QMessageBox.Yes:
            return
        try:
            protection = self.backups.restore(Path(selected))
            self.controller.request_scan()
            self._refresh_filter_tags()
            self.refresh()
        except Exception as exc:
            QMessageBox.critical(self, "恢复失败", str(exc))
            return
        QMessageBox.information(self, "恢复完成", f"恢复前保护备份：\n{protection}")

    def refresh(self) -> None:
        root = self.library.library_root()
        root_text = str(root) if root else "尚未设置漫画目录"
        self.root_label.setText(root_text)
        self.settings_root.setText(f"当前漫画目录：{root_text}")
        self.cache_usage.setText(f"缩略图缓存：{self.cache.usage() / 1024 / 1024:.1f} MB")
        self.choose_button.setEnabled(root is None)
        self.scan_button.setEnabled(root is not None)

        self.refresh_works()

        self.notification_list.clear()
        notifications = self.library.list_notifications()
        for item in notifications:
            row = QListWidgetItem(f"{item.title}  ·  {item.created_at:%Y-%m-%d %H:%M}")
            row.setData(Qt.UserRole, item.id)
            row.setData(Qt.UserRole + 1, item.details_json)
            row.setData(Qt.UserRole + 2, item.kind)
            self.notification_list.addItem(row)
        if not notifications:
            self.notification_list.addItem("暂无通知")
        unread = self.notifications.unread_count()
        self.navigation.item(1).setText(f"通知 {unread}" if unread else "通知")
        self.notification_count_changed.emit(unread)

    def _navigation_changed(self, index: int) -> None:
        self.pages.setCurrentIndex(index)
        if index == 1:
            self.notifications.mark_all_read()
            self.refresh()

    def delete_notification(self) -> None:
        item = self.notification_list.currentItem()
        if item and item.data(Qt.UserRole) is not None:
            self.notifications.delete(item.data(Qt.UserRole))
            self.refresh()

    def clear_notifications(self) -> None:
        if QMessageBox.question(self, "清空通知", "确认删除全部通知？") == QMessageBox.Yes:
            self.notifications.clear()
            self.refresh()

    def open_notification(self, item: QListWidgetItem) -> None:
        if item.data(Qt.UserRole) is None:
            return
        try:
            details = json.loads(item.data(Qt.UserRole + 1))
        except (TypeError, json.JSONDecodeError):
            details = []
        kind = item.data(Qt.UserRole + 2)
        if kind == "files_renamed":
            text = "\n".join(f"{value['old']} → {value['new']}" for value in details)
        else:
            text = "\n".join(str(value) for value in details)
        if kind == "files_added" and details:
            answer = QMessageBox.question(
                self,
                "新增文件列表",
                text + "\n\n是否依次编辑这些作品的标题、封面、Tag 和星级？",
            )
            if answer == QMessageBox.Yes:
                for work in self.catalog.find_by_file_names(details):
                    dialog = WorkDetailDialog(work.id, self.catalog, self.media, self)
                    dialog.saved.connect(self.refresh_works)
                    dialog.exec()
            return
        QMessageBox.information(self, "通知详情", text or "没有详细文件列表")

    def refresh_works(self) -> None:
        page = self.catalog.query(
            CatalogQuery(
                text=self.search_edit.text(),
                kinds=tuple(sorted(self.selected_kinds)),
                tag_ids=tuple(sorted(self.selected_tag_ids)),
                tag_mode="any" if self.any_tags.isChecked() else "all",
                rating_mode=self.rating_filter.currentData()[0],
                rating=self.rating_filter.currentData()[1],
                sort_by=self.sort_box.currentData(),
                descending=not self.direction_button.isChecked(),
                page=self.current_page,
            )
        )
        self.current_page = page.page
        self.total_pages = page.pages
        self.work_list.clear()
        self._animated_movies: list[QMovie] = []
        all_tags = self.catalog.list_tags()
        for work in page.items:
            kind = "漫画" if work.kind == "comic" else "插画"
            display_title = work.title or Path(work.file_name).stem
            identity = work.number if work.kind == "comic" else work.file_name
            pending = " · 内容已替换，待确认" if work.status == "replacement_pending" else ""
            tag_names = [self.catalog.tag_display_name(tag, all_tags) for tag in work.tags]
            item = QListWidgetItem(
                f"{display_title}\n{identity or ''}\n{'  '.join(tag_names)}\n"
                f"{'★' * work.rating}{pending}  [{kind}]"
            )
            item.setData(Qt.UserRole, work.id)
            item.setSizeHint(QSize(0, 132))
            row_widget = QWidget()
            row_layout = QHBoxLayout(row_widget)
            row_layout.setContentsMargins(12, 7, 12, 7)
            image = QLabel()
            image.setFixedSize(108, 116)
            image.setAlignment(Qt.AlignCenter)
            shadow = QGraphicsDropShadowEffect(image)
            shadow.setBlurRadius(16)
            shadow.setOffset(0, 6)
            shadow.setColor(QColor(0, 0, 0, 120))
            image.setGraphicsEffect(shadow)
            try:
                thumbnail = self.media.thumbnail(work, 102, 108)
                if work.kind == "illustration" and thumbnail.suffix == ".gif":
                    movie = QMovie(str(thumbnail))
                    image.setMovie(movie)
                    self._animated_movies.append(movie)
                    movie.start()
                else:
                    image.setPixmap(QPixmap(str(thumbnail)))
            except Exception:
                image.setText("无封面")
            row_layout.addWidget(image)
            text_widget = QWidget()
            text_layout = QVBoxLayout(text_widget)
            text_layout.setContentsMargins(8, 3, 0, 3)
            title = QLabel(display_title)
            title.setStyleSheet("font-size: 18px; font-weight: 700")
            text_layout.addWidget(title)
            text_layout.addWidget(QLabel(identity or ""))
            chips = QWidget()
            chip_layout = QHBoxLayout(chips)
            chip_layout.setContentsMargins(0, 0, 0, 0)
            for name in [kind, *tag_names]:
                chip = QLabel(name)
                chip.setStyleSheet(
                    "padding: 3px 8px; border-radius: 9px; background: palette(midlight)"
                )
                chip_layout.addWidget(chip)
            chip_layout.addStretch(1)
            tag_scroll = QScrollArea()
            tag_scroll.setWidgetResizable(True)
            tag_scroll.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
            tag_scroll.setFixedHeight(31)
            tag_scroll.setFrameShape(QFrame.NoFrame)
            tag_scroll.setWidget(chips)
            text_layout.addWidget(tag_scroll)
            text_layout.addWidget(QLabel("★" * work.rating + pending))
            row_layout.addWidget(text_widget, 1)
            self.work_list.addItem(item)
            self.work_list.setItemWidget(item, row_widget)
        if not page.items:
            self.work_list.addItem("尚无作品。选择目录后，H库 会扫描有效 ZIP 和插画。")
        self.page_label.setText(f"共 {page.total} 部 · 第 {page.page} / {page.pages} 页")
        self.page_jump.setMaximum(page.pages)
        self.page_jump.setValue(page.page)
        self.first_page.setEnabled(page.page > 1)
        self.previous_page.setEnabled(page.page > 1)
        self.next_page.setEnabled(page.page < page.pages)
        self.last_page.setEnabled(page.page < page.pages)

    def _search_changed(self) -> None:
        self.current_page = 1
        self.search_timer.start()

    def _search_now(self) -> None:
        self.search_timer.stop()
        self.current_page = 1
        self.refresh_works()

    def _filters_changed(self) -> None:
        self.catalog.set_setting("windows_sort_field", self.sort_box.currentData())
        self.current_page = 1
        self.refresh_works()

    def _direction_changed(self, ascending: bool) -> None:
        self.direction_button.setText("升序 ↑" if ascending else "降序 ↓")
        self.catalog.set_setting("windows_sort_direction", "asc" if ascending else "desc")
        self._filters_changed()

    def go_page(self, page: int) -> None:
        self.current_page = page
        self.refresh_works()

    def open_work(self, item) -> None:
        work_id = item.data(Qt.UserRole)
        if work_id is None:
            return
        dialog = WorkDetailDialog(work_id, self.catalog, self.media, self)
        dialog.saved.connect(self.refresh_works)
        dialog.exec()

    def open_tag_manager(self) -> None:
        TagManagerDialog(self.catalog, self).exec()
        self._refresh_filter_tags()
        self.refresh_works()

    def choose_uploads(self) -> None:
        selected, _ = QFileDialog.getOpenFileNames(self, "选择要上传的作品")
        if selected:
            self.open_uploads([Path(path) for path in selected])

    def open_uploads(self, paths: list[Path]) -> None:
        dialog = UploadDialog(paths, self.uploads, self.catalog, self)
        dialog.committed.connect(self.controller.request_scan)
        dialog.committed.connect(self.refresh_works)
        dialog.exec()

    def dragEnterEvent(self, event) -> None:  # noqa: N802
        if event.mimeData().hasUrls() and any(url.isLocalFile() for url in event.mimeData().urls()):
            event.acceptProposedAction()

    def dropEvent(self, event) -> None:  # noqa: N802
        paths = [Path(url.toLocalFile()) for url in event.mimeData().urls() if url.isLocalFile()]
        if paths:
            self.open_uploads(paths)
            event.acceptProposedAction()

    def _scan_started(self) -> None:
        self.scan_button.setEnabled(False)
        self.scan_status.setText("正在扫描并校验作品…")

    def _scan_finished(self, result: ScanResult) -> None:
        self.scan_status.setText(
            f"扫描完成：漫画 {result.comics}，插画 {result.illustrations}，"
            f"新增 {len(result.added)}，异常 {len(result.invalid)}"
        )
        self.refresh()
        if result.replacements:
            self.resolve_replacements()
        if not self._startup_backup_checked:
            self._startup_backup_checked = True
            try:
                self.backups.automatic_if_due()
            except Exception as exc:
                self.scan_status.setText(self.scan_status.text() + f" · 自动备份失败：{exc}")

    def resolve_replacements(self) -> None:
        for work in self.library.pending_replacements():
            box = QMessageBox(self)
            box.setWindowTitle("作品文件已被替换")
            box.setText(
                f"“{work.file_name}”已被新的同名文件替换。\n"
                "请选择保留原标题、Tag、星级和封面选择，或将其当作全新作品。"
            )
            preserve = box.addButton("保留原资料", QMessageBox.AcceptRole)
            fresh = box.addButton("当作新作品", QMessageBox.DestructiveRole)
            box.addButton("稍后处理", QMessageBox.RejectRole)
            box.exec()
            if box.clickedButton() not in {preserve, fresh}:
                continue
            try:
                self.library.resolve_replacement(
                    work.id, preserve_metadata=box.clickedButton() is preserve
                )
            except Exception as exc:
                QMessageBox.critical(self, "处理失败", str(exc))
        self.refresh()

    def _scan_failed(self, message: str) -> None:
        self.scan_status.setText(f"扫描失败：{message}")
        self.scan_button.setEnabled(True)

    def bind_tray(self, tray: QSystemTrayIcon) -> None:
        self._tray = tray

    def closeEvent(self, event: QCloseEvent) -> None:  # noqa: N802 - Qt API
        if self._allow_close:
            event.accept()
            return
        event.ignore()
        self.hide()
        if hasattr(self, "_tray"):
            self._tray.showMessage(APP_NAME, "H库 已缩小到系统托盘，手机连接服务继续运行。")

    def exit_application(self) -> None:
        if self.uploads.active_count():
            box = QMessageBox(self)
            box.setWindowTitle("上传任务尚未完成")
            box.setText(f"当前有 {self.uploads.active_count()} 个上传任务。")
            wait = box.addButton("等待任务完成后退出", QMessageBox.AcceptRole)
            cancel = box.addButton("取消当前任务并退出", QMessageBox.DestructiveRole)
            box.addButton(QMessageBox.Cancel)
            box.exec()
            if box.clickedButton() is wait:
                self.hide()
                timer = QTimer(self)
                timer.setInterval(500)

                def exit_when_ready() -> None:
                    if not self.uploads.active_count():
                        timer.stop()
                        self._finish_exit()

                timer.timeout.connect(exit_when_ready)
                timer.start()
                self._exit_timer = timer
                return
            if box.clickedButton() is cancel:
                self.uploads.cancel_all()
            else:
                return
        self._finish_exit()

    def _finish_exit(self) -> None:
        self._allow_close = True
        self.request_exit.emit()


def create_tray(app: QApplication, window: MainWindow) -> QSystemTrayIcon:
    base_icon = app.style().standardIcon(QStyle.StandardPixmap.SP_DirHomeIcon)
    icon = base_icon
    window.setWindowIcon(icon)
    tray = QSystemTrayIcon(icon)
    tray.setToolTip(APP_NAME)
    menu = tray.contextMenu()
    if menu is None:
        from PySide6.QtWidgets import QMenu

        menu = QMenu()
        tray.setContextMenu(menu)
    show_action = QAction("打开 H库", tray)
    exit_action = QAction("退出", tray)
    show_action.triggered.connect(window.showNormal)
    show_action.triggered.connect(window.activateWindow)
    exit_action.triggered.connect(window.exit_application)
    menu.addAction(show_action)
    menu.addSeparator()
    menu.addAction(exit_action)
    tray.activated.connect(
        lambda reason: (
            window.showNormal() if reason == QSystemTrayIcon.ActivationReason.DoubleClick else None
        )
    )
    tray.show()
    window.bind_tray(tray)

    def update_badge(count: int) -> None:
        pixmap = base_icon.pixmap(32, 32)
        if count:
            painter = QPainter(pixmap)
            painter.setBrush(Qt.red)
            painter.setPen(Qt.NoPen)
            painter.drawEllipse(20, 0, 12, 12)
            painter.end()
        tray.setIcon(QIcon(pixmap))
        tray.setToolTip(f"{APP_NAME} · {count} 条未读通知" if count else APP_NAME)

    window.notification_count_changed.connect(update_badge)
    update_badge(window.notifications.unread_count())
    return tray
