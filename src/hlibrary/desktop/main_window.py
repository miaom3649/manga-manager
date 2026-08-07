from __future__ import annotations

import json
import math
import shutil
from pathlib import Path

from PySide6.QtCore import QByteArray, QEvent, QSize, Qt, QTimer, Signal
from PySide6.QtGui import QAction, QCloseEvent, QColor, QIcon, QMovie, QPainter, QPixmap
from PySide6.QtWidgets import (
    QAbstractButton,
    QApplication,
    QButtonGroup,
    QComboBox,
    QDialog,
    QFileDialog,
    QFrame,
    QGraphicsDropShadowEffect,
    QGridLayout,
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
    QSizePolicy,
    QSpinBox,
    QStackedWidget,
    QStyle,
    QStyledItemDelegate,
    QStyleOptionComboBox,
    QStylePainter,
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
from hlibrary.desktop.dialogs import (
    ResetSettingsDialog,
    UploadResultDialog,
    WorkDetailDialog,
    open_tag_management,
)
from hlibrary.desktop.pairing_dialog import PairingDialog
from hlibrary.desktop.reader_dialog import ReaderDialog
from hlibrary.desktop.tag_widgets import (
    AUTHOR_TAG_COLOR,
    TAG_PREFIX_COLOR,
    is_long_tag_category,
    tag_chip_text,
    tag_sort_category,
)
from hlibrary.library import LibraryService, ScanResult
from hlibrary.media import MediaService
from hlibrary.migration import MigrationService
from hlibrary.notifications import NotificationService
from hlibrary.pairing import PairingService
from hlibrary.reader import ReaderService
from hlibrary.upload import UploadService


class TagSummaryWidget(QWidget):
    """Show as many chips as fit, followed by a compact +N summary."""

    def __init__(self, entries: list[tuple[str, str]], parent=None) -> None:
        super().__init__(parent)
        self.setFixedHeight(31)
        self.setAttribute(Qt.WA_TransparentForMouseEvents, True)
        self.chip_layout = QHBoxLayout(self)
        self.chip_layout.setContentsMargins(0, 0, 0, 0)
        self.chip_layout.setSpacing(6)
        self.chips: list[QLabel] = []
        for name, color in entries:
            chip = self._chip(name, color)
            self.chips.append(chip)
            self.chip_layout.addWidget(chip)
        self.more = self._chip("", "#777")
        self.more.hide()
        self.chip_layout.addWidget(self.more)
        self.chip_layout.addStretch(1)
        QTimer.singleShot(0, self._update_visible_chips)

    @staticmethod
    def _chip(name: str, color: str) -> QLabel:
        chip = QLabel(tag_chip_text(name))
        chip.setProperty("authorTag", color.casefold() == AUTHOR_TAG_COLOR.casefold())
        chip.setFixedHeight(26)
        chip.setAlignment(Qt.AlignCenter)
        chip.setToolTip(name)
        chip.setStyleSheet(
            f"QLabel {{ padding: 0 8px; border-radius: 9px; "
            f"background: {color}; color: white; }} "
            f'QLabel[authorTag="true"] {{ background: {AUTHOR_TAG_COLOR}; color: white; }}'
        )
        return chip

    def resizeEvent(self, event) -> None:  # noqa: N802
        super().resizeEvent(event)
        self._update_visible_chips()

    def _update_visible_chips(self) -> None:
        available = self.width()
        spacing = self.chip_layout.spacing()
        widths = [chip.sizeHint().width() for chip in self.chips]
        if sum(widths) + spacing * max(0, len(widths) - 1) <= available:
            for chip in self.chips:
                chip.show()
            self.more.hide()
            return
        shown = 0
        used = 0
        for index, (_chip, width) in enumerate(zip(self.chips, widths, strict=True)):
            hidden = len(self.chips) - index - 1
            self.more.setText(f"+{hidden}")
            required = used + (spacing if index else 0) + width
            if hidden:
                required += spacing + self.more.sizeHint().width()
            if required > available:
                break
            used += (spacing if index else 0) + width
            shown = index + 1
        hidden = len(self.chips) - shown
        for index, chip in enumerate(self.chips):
            chip.setVisible(index < shown)
        self.more.setText(f"+{hidden}")
        self.more.setToolTip(f"还有 {hidden} 个 Tag")
        self.more.setVisible(hidden > 0)


class GroupedTagButton(QPushButton):
    """Render a disambiguating group prefix separately from the Tag name."""

    def __init__(self, display_name: str, parent=None) -> None:
        super().__init__(parent)
        prefix, separator, name = display_name.partition("：")
        self.prefix_text = prefix + separator
        self.name_text = name
        self.setText("")
        self.setAccessibleName(display_name)

    def paintEvent(self, event) -> None:  # noqa: N802
        super().paintEvent(event)
        painter = QPainter(self)
        painter.setRenderHint(QPainter.TextAntialiasing)
        metrics = painter.fontMetrics()
        available = max(1, self.contentsRect().width() - 24)
        full_prefix_width = metrics.horizontalAdvance(self.prefix_text)
        full_name_width = metrics.horizontalAdvance(self.name_text)
        full_text_fits = full_prefix_width + full_name_width <= available
        if full_text_fits:
            prefix_limit = full_prefix_width
        else:
            reserved_name_width = min(full_name_width, max(35, available // 2))
            prefix_limit = max(1, available - reserved_name_width)
        prefix = (
            self.prefix_text
            if full_text_fits
            else metrics.elidedText(self.prefix_text, Qt.ElideRight, prefix_limit)
        )
        prefix_width = metrics.horizontalAdvance(prefix)
        name = metrics.elidedText(
            self.name_text,
            Qt.ElideRight,
            max(1, available - prefix_width),
        )
        name_width = metrics.horizontalAdvance(name)
        left = self.contentsRect().center().x() - (prefix_width + name_width) // 2
        painter.setPen(QColor(TAG_PREFIX_COLOR))
        painter.drawText(
            left,
            self.contentsRect().top(),
            prefix_width,
            self.contentsRect().height(),
            Qt.AlignVCenter,
            prefix,
        )
        painter.setPen(QColor("white") if self.isChecked() else self.palette().text().color())
        painter.drawText(
            left + prefix_width,
            self.contentsRect().top(),
            name_width,
            self.contentsRect().height(),
            Qt.AlignVCenter,
            name,
        )


class NotificationButton(QPushButton):
    """Square notification button with a compact unread badge."""

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._unread_count = 0

    def set_unread_count(self, count: int) -> None:
        self._unread_count = max(0, count)
        self.setToolTip(f"通知（{count} 条未读）" if count else "通知")
        self.update()

    def paintEvent(self, event) -> None:  # noqa: N802
        super().paintEvent(event)
        if not self._unread_count:
            return
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        diameter = 18
        badge = self.rect().adjusted(
            self.width() - diameter - 2,
            2,
            -2,
            2 + diameter - self.height(),
        )
        painter.setPen(Qt.NoPen)
        painter.setBrush(QColor("#d93025"))
        painter.drawEllipse(badge)
        painter.setPen(Qt.white)
        font = painter.font()
        font.setPixelSize(10)
        font.setBold(True)
        painter.setFont(font)
        text = "99+" if self._unread_count > 99 else str(self._unread_count)
        painter.drawText(badge, Qt.AlignCenter, text)


class NotificationListWidget(QListWidget):
    resized = Signal()

    def resizeEvent(self, event) -> None:  # noqa: N802
        super().resizeEvent(event)
        self.resized.emit()


class WorkListWidget(QListWidget):
    def mousePressEvent(self, event) -> None:  # noqa: N802
        if self.itemAt(event.position().toPoint()) is None:
            self.clearSelection()
            self.setCurrentItem(None)
        super().mousePressEvent(event)


class CenteredComboDelegate(QStyledItemDelegate):
    def initStyleOption(self, option, index) -> None:  # noqa: N802
        super().initStyleOption(option, index)
        option.displayAlignment = Qt.AlignCenter


class CenteredComboBox(QComboBox):
    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setItemDelegate(CenteredComboDelegate(self))

    def paintEvent(self, event) -> None:  # noqa: N802
        painter = QStylePainter(self)
        option = QStyleOptionComboBox()
        self.initStyleOption(option)
        painter.drawComplexControl(QStyle.CC_ComboBox, option)
        text_rect = self.style().subControlRect(
            QStyle.CC_ComboBox,
            option,
            QStyle.SC_ComboBoxEditField,
            self,
        )
        painter.setPen(option.palette.text().color())
        painter.drawText(text_rect.adjusted(2, 0, -2, 0), Qt.AlignCenter, self.currentText())


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
        server=None,
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
        self.server = server
        self._startup_backup_checked = False
        self.current_page = 1
        self.selected_kinds: set[str] = {"comic"}
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
        layout = QVBoxLayout(root)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        self.pages = QStackedWidget()
        self.pages.addWidget(self._build_home_page())
        self.pages.addWidget(self._build_notifications_page())
        self.pages.addWidget(self._build_settings_page())

        layout.addWidget(self._build_theme_bar())
        layout.addWidget(self.pages, 1)
        self.setCentralWidget(root)
        for widget in (root, *root.findChildren(QWidget)):
            widget.installEventFilter(self)
        controller.scan_started.connect(self._scan_started)
        controller.scan_finished.connect(self._scan_finished)
        controller.scan_failed.connect(self._scan_failed)
        self._restore_window_geometry()
        self.refresh()

    def eventFilter(self, watched, event) -> bool:  # noqa: N802
        if (
            event.type() == QEvent.MouseButtonPress
            and event.button() == Qt.LeftButton
            and self.work_list.currentItem() is not None
            and self._is_main_window_blank_click(watched, event)
        ):
            self.work_list.clearSelection()
            self.work_list.setCurrentItem(None)
        return super().eventFilter(watched, event)

    def _is_main_window_blank_click(self, watched, event) -> bool:
        widget = watched if isinstance(watched, QWidget) else None
        while widget is not None and widget is not self:
            if isinstance(widget, WorkListWidget):
                point = widget.viewport().mapFromGlobal(event.globalPosition().toPoint())
                return widget.itemAt(point) is None
            if isinstance(
                widget,
                (QAbstractButton, QLineEdit, QComboBox, QSpinBox, QListWidget),
            ):
                return False
            widget = widget.parentWidget()
        return True

    def _build_theme_bar(self) -> QWidget:
        bar = QWidget()
        bar.setObjectName("mainThemeBar")
        bar.setFixedHeight(66)
        bar.setStyleSheet(
            "QWidget#mainThemeBar { background: #25212b; "
            "border-bottom: 3px solid #00a6a6; } "
            "QPushButton#brandButton { border: none; padding: 4px 8px; "
            "font-size: 20px; font-weight: 700; text-align: left; color: #f5f1f8; }"
        )
        row = QHBoxLayout(bar)
        row.setContentsMargins(16, 10, 16, 10)
        row.setSpacing(10)
        self.brand_button = QPushButton("H库")
        self.brand_button.setObjectName("brandButton")
        self.brand_button.setIcon(self.style().standardIcon(QStyle.SP_DirHomeIcon))
        self.brand_button.setIconSize(QSize(30, 30))
        self.brand_button.setToolTip("返回作品")
        self.brand_button.clicked.connect(lambda: self._show_page(0))
        self.notification_button = NotificationButton()
        self.notification_button.setIcon(self.style().standardIcon(QStyle.SP_MessageBoxInformation))
        self.notification_button.setIconSize(QSize(22, 22))
        self.notification_button.setFixedSize(44, 44)
        self.notification_button.clicked.connect(lambda: self._show_page(1))
        self.settings_button = QPushButton()
        self.settings_button.setIcon(self.style().standardIcon(QStyle.SP_FileDialogDetailedView))
        self.settings_button.setIconSize(QSize(22, 22))
        self.settings_button.setFixedSize(44, 44)
        self.settings_button.setToolTip("设置")
        self.settings_button.clicked.connect(lambda: self._show_page(2))
        row.addWidget(self.brand_button)
        row.addStretch(1)
        row.addWidget(self.notification_button)
        row.addWidget(self.settings_button)
        return bar

    def _restore_window_geometry(self) -> None:
        encoded = self.catalog.setting("windows_main_geometry", "")
        if encoded:
            self.restoreGeometry(QByteArray.fromBase64(encoded.encode("ascii")))
        QTimer.singleShot(0, self._ensure_window_on_screen)

    def _ensure_window_on_screen(self) -> None:
        frame = self.frameGeometry()
        if any(screen.availableGeometry().intersects(frame) for screen in QApplication.screens()):
            return
        screen = QApplication.primaryScreen()
        if screen is not None:
            frame.moveCenter(screen.availableGeometry().center())
            self.move(frame.topLeft())

    def _save_window_geometry(self) -> None:
        encoded = bytes(self.saveGeometry().toBase64()).decode("ascii")
        self.catalog.set_setting("windows_main_geometry", encoded)

    def _build_home_page(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        self.search_edit = QLineEdit()
        self.search_edit.setFixedHeight(48)
        self.search_edit.setPlaceholderText("搜索编号或标题，多个关键词用英文逗号分隔")
        self.search_edit.textChanged.connect(self._search_changed)
        self.search_edit.returnPressed.connect(self._search_now)
        self.sort_box = CenteredComboBox()
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
        upload = QPushButton("上传")
        upload.clicked.connect(self.choose_uploads)
        self.refresh_button = QPushButton("刷新")
        self.refresh_button.clicked.connect(self.controller.request_scan)
        for control in (self.sort_box, self.direction_button, upload, self.refresh_button):
            control.setFixedHeight(40)
        control_row = QHBoxLayout()
        control_row.addWidget(self.sort_box)
        control_row.addWidget(self.direction_button)
        control_row.addWidget(upload)
        control_row.addWidget(self.refresh_button)
        control_row.addStretch(1)

        self.scan_status = QLabel("等待扫描")
        content_row = QHBoxLayout()
        filters = self._build_filter_panel()
        self.work_list = WorkListWidget()
        self.work_list.setStyleSheet(
            "QListWidget::item:selected { background: transparent; color: palette(text); }"
        )
        self.work_list.currentItemChanged.connect(self._work_selection_changed)
        self.work_list.itemActivated.connect(self.open_work)
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
        layout.addWidget(self.search_edit)
        layout.addLayout(control_row)
        layout.addWidget(self.scan_status)
        content_row.addWidget(filters)
        content_row.addWidget(self.work_list, 1)
        layout.addLayout(content_row, 1)
        layout.addLayout(page_row)
        return page

    def _build_filter_panel(self) -> QWidget:
        panel = QGroupBox()
        panel.setFixedWidth(210)
        layout = QVBoxLayout(panel)
        mode_row = QHBoxLayout()
        self.any_tags = QRadioButton("任意匹配")
        self.all_tags = QRadioButton("全部匹配")
        self.any_tags.setChecked(True)
        self.any_tags.toggled.connect(self._filters_changed)
        mode_row.addWidget(self.any_tags)
        mode_row.addWidget(self.all_tags)
        layout.addLayout(mode_row)
        self.tag_search = QLineEdit()
        self.tag_search.setPlaceholderText("搜索 Tag 或分组")
        self.tag_search.textChanged.connect(self._refresh_filter_tags)
        layout.addWidget(self.tag_search)
        tag_content = QWidget()
        self.tag_filter_layout = QGridLayout(tag_content)
        self.tag_filter_layout.setContentsMargins(0, 0, 0, 0)
        self.tag_filter_layout.setAlignment(Qt.AlignTop)
        self.comic_filter = QPushButton("漫画")
        self.illustration_filter = QPushButton("插画")
        self.kind_filter_group = QButtonGroup(self)
        self.kind_filter_group.setExclusive(True)
        for column, (button, kind) in enumerate(
            (
                (self.comic_filter, "comic"),
                (self.illustration_filter, "illustration"),
            )
        ):
            button.setCheckable(True)
            self.kind_filter_group.addButton(button)
            button.setChecked(kind in self.selected_kinds)
            button.setStyleSheet(self._tag_button_style("#006a6a"))
            button.toggled.connect(lambda checked, value=kind: self._kind_toggled(value, checked))
            self.tag_filter_layout.addWidget(button, 0, column)
        self.custom_tag_buttons: list[QPushButton] = []
        tag_scroll = QScrollArea()
        tag_scroll.setWidgetResizable(True)
        tag_scroll.setFrameShape(QFrame.NoFrame)
        tag_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        tag_scroll.setWidget(tag_content)
        layout.addWidget(tag_scroll, 1)
        self.rating_filter = CenteredComboBox()
        self.rating_filter.addItem("全部星级", ("any", 0))
        self.rating_filter.addItem("未评价", ("unrated", 0))
        for rating in range(1, 4):
            self.rating_filter.addItem("★" * rating, ("exact", rating))
        for rating in range(1, 4):
            self.rating_filter.addItem("★" * rating + " 及以上", ("at_least", rating))
        self.rating_filter.currentIndexChanged.connect(self._filters_changed)
        layout.addWidget(self.rating_filter)
        clear = QPushButton("清除全部筛选")
        clear.clicked.connect(self.clear_filters)
        layout.addWidget(clear)
        manage_tags = QPushButton("管理")
        manage_tags.clicked.connect(self.open_tag_manager)
        layout.addWidget(manage_tags)
        self._refresh_filter_tags()
        return panel

    @staticmethod
    def _tag_button_style(color: str) -> str:
        return (
            "QPushButton { background: transparent; color: palette(text); "
            f"border: 1px solid {color}; border-radius: 15px; "
            "min-height: 30px; max-height: 30px; padding: 0 12px; } "
            f"QPushButton:checked {{ background: {color}; color: white; font-weight: 700; }}"
        )

    def _refresh_filter_tags(self) -> None:
        for button in self.custom_tag_buttons:
            self.tag_filter_layout.removeWidget(button)
            button.deleteLater()
        self.custom_tag_buttons.clear()
        system_search = self.tag_search.text().strip().casefold()
        self.comic_filter.setVisible(not system_search or system_search in "漫画".casefold())
        self.illustration_filter.setVisible(not system_search or system_search in "插画".casefold())
        all_tags = self.catalog.list_tags()
        classified_tags = []
        for tag in self.catalog.list_tags(self.tag_search.text()):
            display_name = self.catalog.tag_display_name(tag, all_tags)
            author = self.catalog.is_author_tag(tag)
            category = tag_sort_category(
                display_name,
                self.tag_search.fontMetrics(),
                author=author,
            )
            long_tag = is_long_tag_category(category)
            classified_tags.append((category, tag, display_name, long_tag))
        classified_tags.sort(key=lambda entry: entry[0])
        row = 1
        column = 0
        for category, tag, display_name, full_row in classified_tags:
            button = GroupedTagButton(display_name) if "：" in display_name else QPushButton()
            button.setToolTip(display_name)
            button.setProperty(
                "tagLayoutClass",
                (
                    "author"
                    if category == 0
                    else "prefixed"
                    if category == 1
                    else "long"
                    if category == 2
                    else "short"
                ),
            )
            available_text_width = 158 if full_row else 68
            if not isinstance(button, GroupedTagButton):
                button.setText(
                    button.fontMetrics().elidedText(
                        display_name,
                        Qt.ElideRight,
                        available_text_width,
                    )
                )
            button.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Fixed)
            button.setCheckable(True)
            button.setChecked(tag.id in self.selected_tag_ids)
            button.setProperty("grouped", tag.group_id is not None)
            color = (
                AUTHOR_TAG_COLOR
                if self.catalog.is_author_tag(tag)
                else "#6750a4"
                if tag.group_id
                else "#777"
            )
            button.setStyleSheet(self._tag_button_style(color))
            button.toggled.connect(
                lambda checked, tag_id=tag.id: self._tag_filter_toggled(tag_id, checked)
            )
            if full_row:
                if column:
                    row += 1
                    column = 0
                self.tag_filter_layout.addWidget(button, row, 0, 1, 2)
                row += 1
            else:
                self.tag_filter_layout.addWidget(button, row, column)
                column += 1
                if column == 2:
                    row += 1
                    column = 0
            self.custom_tag_buttons.append(button)

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
        self.selected_tag_ids.clear()
        self.comic_filter.setChecked(True)
        self.rating_filter.setCurrentIndex(0)
        self.any_tags.setChecked(True)
        self.tag_search.clear()
        self._refresh_filter_tags()
        self._filters_changed()

    def _build_notifications_page(self) -> QWidget:
        page = QWidget()
        page_layout = QVBoxLayout(page)
        content = QWidget()
        content.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        layout = QVBoxLayout(content)
        title = QLabel("通知")
        title.setAlignment(Qt.AlignCenter)
        title.setStyleSheet("font-size: 32px; font-weight: 700;")
        self.notification_list = NotificationListWidget()
        self.notification_list.setSpacing(0)
        self.notification_list.setStyleSheet(
            "QListWidget { background: transparent; border: 1px solid #6750a4; "
            "border-radius: 10px; padding: 0; } "
            "QListWidget::item, QListWidget::item:selected { "
            "background: transparent; border: none; }"
        )
        self.notification_list.itemActivated.connect(self.open_notification)
        self.notification_list.resized.connect(
            lambda: QTimer.singleShot(0, self._fill_empty_notification_rows)
        )
        notification_actions = QHBoxLayout()
        delete_selected = QPushButton("删除所选通知")
        delete_selected.clicked.connect(self.delete_notification)
        clear = QPushButton("清空通知")
        clear.clicked.connect(self.clear_notifications)
        delete_selected.setFixedHeight(42)
        clear.setFixedHeight(42)
        notification_actions.addWidget(delete_selected, 1)
        notification_actions.addWidget(clear, 1)
        layout.addWidget(title)
        layout.addLayout(notification_actions)
        layout.addWidget(self.notification_list, 1)
        page_layout.addWidget(content, 1)
        return page

    def _build_settings_page(self) -> QWidget:
        page = QWidget()
        page_layout = QHBoxLayout(page)
        content = QWidget()
        content.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        layout = QVBoxLayout(content)
        title = QLabel("设置")
        title.setAlignment(Qt.AlignCenter)
        title.setStyleSheet("font-size: 32px; font-weight: 700;")
        self.settings_root = QLabel()
        self.settings_root.setAlignment(Qt.AlignCenter)
        self.settings_root.setWordWrap(True)
        self.settings_root.setTextInteractionFlags(Qt.TextSelectableByMouse)
        choose = QPushButton("更换并迁移作品目录")
        choose.clicked.connect(self.migrate_root)
        pair = QPushButton("手机配对与设备管理")
        pair.clicked.connect(self.open_pairing)
        manual_backup = QPushButton("立即手动备份")
        manual_backup.clicked.connect(self.create_manual_backup)
        restore_backup = QPushButton("恢复备份")
        restore_backup.clicked.connect(self.restore_backup)
        self.cache_usage = QLabel()
        self.cache_usage.setAlignment(Qt.AlignCenter)
        self.cache_limit = CenteredComboBox()
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
        theme_label = QLabel("外观主题")
        theme_label.setAlignment(Qt.AlignCenter)
        self.theme_box = CenteredComboBox()
        self.theme_box.addItem("跟随系统", "system")
        self.theme_box.addItem("浅色", "light")
        self.theme_box.addItem("深色", "dark")
        self.theme_box.setCurrentIndex(max(0, self.theme_box.findData(self.appearance.theme())))
        self.theme_box.currentIndexChanged.connect(self.change_theme)
        for button in (choose, pair, manual_backup, restore_backup, clear_cache):
            button.setFixedHeight(42)
        layout.addWidget(title)
        layout.addWidget(self.settings_root)
        layout.addWidget(choose)
        layout.addWidget(pair)
        layout.addWidget(manual_backup)
        layout.addWidget(restore_backup)
        layout.addWidget(self.cache_usage)
        layout.addWidget(self.cache_limit)
        layout.addWidget(clear_cache)
        layout.addWidget(theme_label)
        layout.addWidget(self.theme_box)
        layout.addStretch(1)
        reset = QPushButton("恢复所有设置")
        reset.setFixedHeight(46)
        reset.setStyleSheet(
            "QPushButton { background: #d93025; color: white; "
            "border: 2px solid #d93025; border-radius: 10px; "
            "font-weight: 700; padding: 8px 12px; } "
            "QPushButton:hover { background: #b3261e; }"
        )
        reset.clicked.connect(self.reset_all_settings)
        layout.addWidget(reset)
        page_layout.addWidget(content, 1)
        return page

    def reset_all_settings(self) -> None:
        if ResetSettingsDialog(self).exec() != QDialog.Accepted:
            return
        root = self.library.library_root()
        if root is None:
            QMessageBox.critical(self, "恢复设置失败", "尚未设置作品目录")
            return
        database = self.catalog.database
        rollback = database.path.with_name(database.path.name + ".reset-rollback")
        self.controller.pause_watching()
        self.controller.wait_until_idle()
        if self.server is not None:
            self.server.stop()
        try:
            database.close()
            rollback.unlink(missing_ok=True)
            shutil.copy2(database.path, rollback)
            database.path.unlink()
            for suffix in ("-wal", "-shm"):
                Path(str(database.path) + suffix).unlink(missing_ok=True)
            database.reopen()
            database.initialize(__version__)
            self.library.configure_root(root)
            CatalogService(database)
            self.library.scan()
            self.notifications.clear()
            removed_backups = self.backups.delete_all()
            removed_cache = self.cache.clear()
        except Exception as exc:
            database.close()
            if rollback.exists():
                database.path.unlink(missing_ok=True)
                for suffix in ("-wal", "-shm"):
                    Path(str(database.path) + suffix).unlink(missing_ok=True)
                rollback.replace(database.path)
            database.reopen()
            database.initialize(__version__)
            self.controller.start()
            if self.server is not None:
                self.server.start()
            QMessageBox.critical(self, "恢复设置失败", str(exc))
            return
        rollback.unlink(missing_ok=True)
        self._startup_backup_checked = True
        self.controller.start()
        if self.server is not None:
            self.server.start()
        app = QApplication.instance()
        if app is not None:
            apply_theme(app, "system")
        self.selected_tag_ids.clear()
        self.selected_kinds = {"comic"}
        self.comic_filter.setChecked(True)
        self.search_edit.clear()
        self.tag_search.clear()
        self.rating_filter.setCurrentIndex(0)
        self.any_tags.setChecked(True)
        self.theme_box.setCurrentIndex(max(0, self.theme_box.findData("system")))
        self.cache_limit.setCurrentIndex(max(0, self.cache_limit.findData(self.cache.limit())))
        self._refresh_filter_tags()
        self.refresh()
        QMessageBox.information(
            self,
            "恢复完成",
            f"数据库已重建，删除 {removed_backups} 个备份文件和 "
            f"{removed_cache} 个缓存文件。作品已重新扫描。",
        )

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
        self.settings_root.setText(f"当前漫画目录：{root_text}")
        self.cache_usage.setText(f"缩略图缓存：{self.cache.usage() / 1024 / 1024:.1f} MB")
        self.refresh_button.setEnabled(root is not None)

        self.refresh_works()

        self.notification_list.clear()
        notifications = self.library.list_notifications()
        self._notifications_empty = not notifications
        for item in notifications:
            row = QListWidgetItem()
            row.setData(Qt.UserRole, item.id)
            row.setData(Qt.UserRole + 1, item.details_json)
            row.setData(Qt.UserRole + 2, item.kind)
            row.setData(Qt.UserRole + 3, item.read_at is not None)
            row.setSizeHint(QSize(0, 54))
            self.notification_list.addItem(row)
            notification_row = QLabel(f"{item.title}  ·  {item.created_at:%Y-%m-%d %H:%M}")
            notification_row.setAlignment(Qt.AlignCenter)
            notification_row.setContentsMargins(14, 0, 14, 0)
            self._style_notification_row(notification_row, item.read_at is not None)
            self.notification_list.setItemWidget(row, notification_row)
        if not notifications:
            self._fill_empty_notification_rows()
        unread = self.notifications.unread_count()
        self.notification_button.set_unread_count(unread)
        self.notification_count_changed.emit(unread)

    def _show_page(self, index: int) -> None:
        self.pages.setCurrentIndex(index)

    @staticmethod
    def _style_notification_row(widget: QWidget, read: bool) -> None:
        background = "#25212b" if read else "transparent"
        widget.setStyleSheet(
            f"background: {background}; border: none; "
            "border-bottom: 1px solid #51465f; border-radius: 0;"
        )

    def _fill_empty_notification_rows(self) -> None:
        if not getattr(self, "_notifications_empty", False):
            return
        height = self.notification_list.viewport().height()
        if height <= 0:
            return
        count = max(1, math.ceil(height / 54))
        base_height, remainder = divmod(height, count)
        current_height = sum(
            self.notification_list.item(index).sizeHint().height()
            for index in range(self.notification_list.count())
        )
        if self.notification_list.count() == count and current_height == height:
            return
        self.notification_list.clear()
        for index in range(count):
            placeholder = QListWidgetItem()
            placeholder.setSizeHint(QSize(0, base_height + (1 if index < remainder else 0)))
            self.notification_list.addItem(placeholder)
            placeholder_row = QFrame()
            self._style_notification_row(placeholder_row, False)
            self.notification_list.setItemWidget(placeholder, placeholder_row)

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
        notification_id = item.data(Qt.UserRole)
        if notification_id is None:
            return
        details_json = item.data(Qt.UserRole + 1)
        kind = item.data(Qt.UserRole + 2)
        if not item.data(Qt.UserRole + 3):
            self.notifications.mark_read(notification_id)
            item.setData(Qt.UserRole + 3, True)
            row_widget = self.notification_list.itemWidget(item)
            if row_widget is not None:
                self._style_notification_row(row_widget, True)
            unread = self.notifications.unread_count()
            self.notification_button.set_unread_count(unread)
            self.notification_count_changed.emit(unread)
        try:
            details = json.loads(details_json)
        except (TypeError, json.JSONDecodeError):
            details = []
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
                    self.show_work_detail(work.id)
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
            custom_tag_entries = [
                (
                    self.catalog.tag_display_name(tag, all_tags),
                    AUTHOR_TAG_COLOR
                    if self.catalog.is_author_tag(tag)
                    else "#6750a4"
                    if tag.group_id is not None
                    else "#777",
                    tag_sort_category(
                        self.catalog.tag_display_name(tag, all_tags),
                        self.fontMetrics(),
                        author=self.catalog.is_author_tag(tag),
                    ),
                )
                for tag in work.tags
            ]
            custom_tag_entries.sort(key=lambda entry: entry[2])
            tag_entries = [(kind, "#006a6a"), *[entry[:2] for entry in custom_tag_entries]]
            # 作品内容完全由自定义 row_widget 绘制。列表项自身不能再带
            # 旧版文本，否则部分 Windows 样式会把文字画在封面左侧。
            item = QListWidgetItem()
            item.setData(Qt.UserRole, work.id)
            item.setSizeHint(QSize(0, 132))
            row_widget = QWidget()
            row_widget.setObjectName("workRow")
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
            text_layout.addWidget(TagSummaryWidget(tag_entries))
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
        self.show_work_detail(work_id)

    def _work_selection_changed(self, current, previous) -> None:
        if previous is not None:
            previous_widget = self.work_list.itemWidget(previous)
            if previous_widget is not None:
                previous_widget.setStyleSheet(
                    "QWidget#workRow { background: transparent; border: none; }"
                )
        if current is not None:
            current_widget = self.work_list.itemWidget(current)
            if current_widget is not None:
                current_widget.setStyleSheet(
                    "QWidget#workRow { background: transparent; "
                    "border: 2px solid #6750a4; border-radius: 12px; }"
                )

    def show_work_detail(self, work_id: int) -> None:
        """Run details and reader sequentially so no hidden modal blocks the main window."""
        while True:
            requested: list[int] = []
            dialog = WorkDetailDialog(work_id, self.catalog, self.media, self)
            dialog.saved.connect(self.refresh_works)
            dialog.reading_requested.connect(requested.append)
            dialog.kind_filter_requested.connect(self._filter_kind_from_detail)
            dialog.tag_filter_requested.connect(self._filter_tag_from_detail)
            dialog.exec()
            if not requested:
                return
            work = self.catalog.get_work(requested[0])
            if work is None:
                return
            self.hide()
            try:
                ReaderDialog(work, ReaderService(self.catalog.database, self.media), self).exec()
            finally:
                self.show()
                self.raise_()
                self.activateWindow()

    def _filter_kind_from_detail(self, kind: str) -> None:
        self._show_page(0)
        self.search_edit.clear()
        self.selected_kinds = {kind}
        self.selected_tag_ids.clear()
        target = self.comic_filter if kind == "comic" else self.illustration_filter
        target.setChecked(True)
        self.rating_filter.setCurrentIndex(0)
        self.tag_search.clear()
        self.all_tags.setChecked(True)
        self.current_page = 1
        self._refresh_filter_tags()
        self.refresh_works()

    def _filter_tag_from_detail(self, tag_id: int, kind: str) -> None:
        self._show_page(0)
        self.search_edit.clear()
        self.selected_kinds = {kind}
        self.selected_tag_ids = {tag_id}
        target = self.comic_filter if kind == "comic" else self.illustration_filter
        target.setChecked(True)
        self.rating_filter.setCurrentIndex(0)
        self.tag_search.clear()
        self.all_tags.setChecked(True)
        self.current_page = 1
        self._refresh_filter_tags()
        self.refresh_works()

    def open_tag_manager(self) -> None:
        open_tag_management(self.catalog, self)
        self._refresh_filter_tags()
        self.refresh_works()

    def choose_uploads(self) -> None:
        selected, _ = QFileDialog.getOpenFileNames(self, "选择要上传的作品")
        if selected:
            self.open_uploads([Path(path) for path in selected])

    def open_uploads(self, paths: list[Path]) -> None:
        try:
            task = self.uploads.prepare(paths)
        except (OSError, ValueError) as exc:
            UploadResultDialog("无法加入作品库", str(exc), self).exec()
            return
        if task.invalid:
            lines = [f"{item.source.name}：{item.error}" for item in task.invalid]
            self.uploads.cancel(task)
            UploadResultDialog(
                "文件不合法",
                "本次选择包含不能加入作品库的文件，因此整批均未加入。\n\n" + "\n".join(lines),
                self,
            ).exec()
            return
        if task.conflicts:
            names = "\n".join(item.source.name for item in task.conflicts)
            decision = UploadResultDialog(
                "发现同名文件",
                f"有 {len(task.conflicts)} 个文件与作品库重名：\n\n{names}\n\n"
                "覆盖后将使用新文件的默认标题、空 Tag、未评价和默认封面，"
                "旧阅读进度会被清除。",
                self,
                overwrite=True,
            )
            if decision.exec() != QDialog.Accepted:
                self.uploads.cancel(task)
                return
        try:
            self.uploads.commit(task, allow_overwrite=bool(task.conflicts))
        except (OSError, ValueError) as exc:
            if task.id in self.uploads.active_tasks:
                self.uploads.cancel(task)
            UploadResultDialog("加入失败", str(exc), self).exec()
            return
        self.controller.request_scan()
        self.refresh_works()

    def dragEnterEvent(self, event) -> None:  # noqa: N802
        if event.mimeData().hasUrls() and any(url.isLocalFile() for url in event.mimeData().urls()):
            event.acceptProposedAction()

    def dropEvent(self, event) -> None:  # noqa: N802
        paths = [Path(url.toLocalFile()) for url in event.mimeData().urls() if url.isLocalFile()]
        if paths:
            self.open_uploads(paths)
            event.acceptProposedAction()

    def _scan_started(self) -> None:
        self.refresh_button.setEnabled(False)
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
        self.refresh_button.setEnabled(True)

    def bind_tray(self, tray: QSystemTrayIcon) -> None:
        self._tray = tray

    def closeEvent(self, event: QCloseEvent) -> None:  # noqa: N802 - Qt API
        self._save_window_geometry()
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
        self._save_window_geometry()
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
