from __future__ import annotations

import json
import math
import shutil
import sys
from functools import partial
from pathlib import Path

from PySide6.QtCore import QByteArray, QEvent, QSize, Qt, QTimer, Signal
from PySide6.QtGui import (
    QAction,
    QActionGroup,
    QCloseEvent,
    QColor,
    QCursor,
    QIcon,
    QMovie,
    QPainter,
    QPixmap,
)
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
    QMenu,
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

from hmanga import __version__
from hmanga.appearance import AppearanceService, apply_theme
from hmanga.backup import BackupService
from hmanga.cache import CacheService
from hmanga.catalog import CatalogQuery, CatalogService
from hmanga.config import APP_NAME
from hmanga.controller import LibraryController
from hmanga.desktop.dialogs import (
    ResetSettingsDialog,
    UploadResultDialog,
    WorkDetailDialog,
    choose_action,
    confirm_action,
    open_tag_management,
    show_message,
)
from hmanga.desktop.pairing_dialog import PairingDialog
from hmanga.desktop.reader_dialog import ReaderDialog
from hmanga.desktop.tag_widgets import (
    AUTHOR_TAG_COLOR,
    is_long_tag_category,
    tag_chip_text,
    tag_sort_category,
)
from hmanga.i18n import (
    active_language,
    available_languages,
    localize_tree,
    set_language,
    tr,
    trf,
)
from hmanga.library import LibraryService, ScanResult
from hmanga.media import MediaService
from hmanga.migration import MigrationService
from hmanga.notifications import NotificationService
from hmanga.pairing import PairingService
from hmanga.reader import ReaderService
from hmanga.upload import UploadService

INITIAL_LIBRARY_PROMPT_SHOWN = "initial_library_prompt_shown"


def _consume_library_prompt_message_key(catalog: CatalogService) -> str:
    """Return the appropriate unset-library prompt and remember first display."""
    if catalog.setting(INITIAL_LIBRARY_PROMPT_SHOWN, "0") == "1":
        return "confirm.library_directory_unset"
    catalog.set_setting(INITIAL_LIBRARY_PROMPT_SHOWN, "1")
    return "confirm.first_library_directory_setup"


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
        chip.setProperty("tagChip", True)
        chip.setProperty("authorTag", color.casefold() == AUTHOR_TAG_COLOR.casefold())
        chip.setFixedHeight(26)
        chip.setAlignment(Qt.AlignCenter)
        chip.setToolTip(name)
        chip.setStyleSheet(
            f"QLabel {{ padding: 0 8px; border-radius: 9px; "
            f"background: {color}; }} "
            f'QLabel[authorTag="true"] {{ background: {AUTHOR_TAG_COLOR}; }}'
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
        self.more.setToolTip(trf("tags.more", count=hidden))
        self.more.setVisible(hidden > 0)


class NotificationButton(QPushButton):
    """Square notification button with a compact unread badge."""

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._unread_count = 0

    def set_unread_count(self, count: int) -> None:
        self._unread_count = max(0, count)
        self.setToolTip(
            trf("notifications.unread", count=count) if count else tr("label.notifications")
        )
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
    request_restart = Signal()
    notification_count_changed = Signal(int)
    theme_changed = Signal(str)
    language_changed = Signal(str)

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
        self._catalog_revision = catalog.revision
        self._thumbnail_generation = 0
        self._retired_reader: ReaderDialog | None = None
        self.sync_timer = QTimer(self)
        self.sync_timer.setInterval(500)
        self.sync_timer.timeout.connect(self._sync_catalog_revision)
        self.sync_timer.start()
        self.setWindowTitle(f"{APP_NAME} {__version__}")
        self.setWindowFlag(Qt.FramelessWindowHint, True)
        self.setAcceptDrops(True)
        self.resize(1100, 720)
        self._allow_close = False
        self._restart_after_exit = False
        self._exit_started = False

        root = QWidget(self)
        layout = QVBoxLayout(root)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        self.pages = QStackedWidget()
        self.pages.addWidget(self._build_home_page())
        self.pages.addWidget(self._build_notifications_page())
        self.pages.addWidget(self._build_settings_page())

        self.theme_bar = self._build_theme_bar()
        layout.addWidget(self.theme_bar)
        layout.addWidget(self.pages, 1)
        self.setCentralWidget(root)
        self._install_window_gesture_filter(self)
        controller.scan_started.connect(self._scan_started)
        controller.scan_finished.connect(self._scan_finished)
        controller.scan_failed.connect(self._scan_failed)
        self._restore_window_geometry()
        self.refresh()

    def eventFilter(self, watched, event) -> bool:  # noqa: N802
        if event.type() == QEvent.ChildAdded:
            child = event.child()
            if isinstance(child, QWidget):
                # QListWidget rows and other page contents are created after the
                # main window.  Install after Qt finishes constructing the child.
                QTimer.singleShot(
                    0,
                    lambda widget=child: self._install_window_gesture_filter(widget),
                )
        if event.type() == QEvent.MouseMove and not self._has_visible_dialog():
            edges = self._resize_edges(event.globalPosition().toPoint())
            self.setCursor(self._resize_cursor(edges))
        if event.type() == QEvent.MouseButtonPress and event.button() == Qt.LeftButton:
            position = event.globalPosition().toPoint()
            edges = self._resize_edges(position)
            handle = self.windowHandle()
            if (
                edges
                and not self.isMaximized()
                and not self._has_visible_dialog()
                and handle is not None
            ):
                if handle.startSystemResize(edges):
                    event.accept()
                    return True
            if self._is_theme_bar_background(watched) and handle is not None:
                if handle.startSystemMove():
                    event.accept()
                    return True
        if (
            event.type() == QEvent.MouseButtonPress
            and event.button() == Qt.LeftButton
            and self.work_list.currentItem() is not None
            and self._is_main_window_blank_click(watched, event)
        ):
            self.work_list.clearSelection()
            self.work_list.setCurrentItem(None)
        return super().eventFilter(watched, event)

    def _install_window_gesture_filter(self, widget: QWidget) -> None:
        widget.setMouseTracking(True)
        widget.installEventFilter(self)
        for child in widget.findChildren(QWidget):
            child.setMouseTracking(True)
            child.installEventFilter(self)

    def _has_visible_dialog(self) -> bool:
        return any(dialog.isVisible() for dialog in self.findChildren(QDialog))

    def _resize_edges(self, global_position) -> Qt.Edges:
        local = self.mapFromGlobal(global_position)
        margin = 10
        edges = Qt.Edges()
        if local.x() <= margin:
            edges |= Qt.LeftEdge
        elif local.x() >= self.width() - margin:
            edges |= Qt.RightEdge
        if local.y() <= margin:
            edges |= Qt.TopEdge
        elif local.y() >= self.height() - margin:
            edges |= Qt.BottomEdge
        return edges

    @staticmethod
    def _resize_cursor(edges: Qt.Edges) -> Qt.CursorShape:
        if edges in (Qt.LeftEdge | Qt.TopEdge, Qt.RightEdge | Qt.BottomEdge):
            return Qt.SizeFDiagCursor
        if edges in (Qt.RightEdge | Qt.TopEdge, Qt.LeftEdge | Qt.BottomEdge):
            return Qt.SizeBDiagCursor
        if edges & (Qt.LeftEdge | Qt.RightEdge):
            return Qt.SizeHorCursor
        if edges & (Qt.TopEdge | Qt.BottomEdge):
            return Qt.SizeVerCursor
        return Qt.ArrowCursor

    def _is_theme_bar_background(self, watched) -> bool:
        widget = watched if isinstance(watched, QWidget) else None
        while widget is not None and widget is not self:
            if isinstance(widget, QAbstractButton):
                return False
            if widget is self.theme_bar:
                return True
            widget = widget.parentWidget()
        return False

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
            "QWidget#mainThemeBar { background: #704846; "
            "border-bottom: 3px solid #a86f68; } "
            "QPushButton#brandButton { border: none; padding: 4px 8px; "
            "font-size: 20px; font-weight: 700; text-align: left; color: #f5f1f8; }"
        )
        row = QHBoxLayout(bar)
        row.setContentsMargins(16, 10, 16, 10)
        row.setSpacing(10)
        self.brand_button = QPushButton(APP_NAME)
        self.brand_button.setObjectName("brandButton")
        self.brand_button.setIcon(self.style().standardIcon(QStyle.SP_DirHomeIcon))
        self.brand_button.setIconSize(QSize(30, 30))
        self.brand_button.setToolTip(tr("action.back_to_works"))
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
        self.settings_button.setToolTip(tr("label.settings"))
        self.settings_button.clicked.connect(lambda: self._show_page(2))
        self.close_button = QPushButton()
        self.close_button.setObjectName("mainCloseButton")
        self.close_button.setIcon(self.style().standardIcon(QStyle.SP_TitleBarCloseButton))
        self.close_button.setIconSize(QSize(22, 22))
        self.close_button.setFixedSize(44, 44)
        self.close_button.setToolTip(tr("label.minimize_to_tray"))
        self.close_button.setStyleSheet(
            "QPushButton#mainCloseButton:hover { background: #b94845; border-color: #d96a66; }"
        )
        self.close_button.clicked.connect(self.close)
        row.addWidget(self.brand_button)
        row.addStretch(1)
        row.addWidget(self.notification_button)
        row.addWidget(self.settings_button)
        row.addWidget(self.close_button)
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
        self.search_edit.setPlaceholderText(tr("message.search_all_fields_multiple_terms"))
        self.search_edit.textChanged.connect(self._search_changed)
        self.search_edit.returnPressed.connect(self._search_now)
        self.sort_box = CenteredComboBox()
        self.sort_box.addItem(tr("label.recently_added"), "added")
        self.sort_box.addItem(tr("label.file_name_or_number"), "file_name")
        self.sort_box.addItem(tr("label.title"), "title")
        self.sort_box.addItem(tr("label.rating"), "rating")
        saved_sort = self.catalog.setting("windows_sort_field", "added")
        self.sort_box.setCurrentIndex(max(0, self.sort_box.findData(saved_sort)))
        self.direction_button = QPushButton(tr("label.descending"))
        self.direction_button.setCheckable(True)
        ascending = self.catalog.setting("windows_sort_direction", "desc") == "asc"
        self.direction_button.setChecked(ascending)
        self.direction_button.setText(
            tr("label.ascending") if ascending else tr("label.descending")
        )
        self.sort_box.currentIndexChanged.connect(self._filters_changed)
        self.direction_button.clicked.connect(self._direction_changed)
        upload = QPushButton(tr("label.upload"))
        upload.clicked.connect(self.choose_uploads)
        self.refresh_button = QPushButton(tr("action.refresh"))
        self.refresh_button.clicked.connect(self.controller.request_scan)
        for control in (self.sort_box, self.direction_button, upload, self.refresh_button):
            control.setFixedHeight(40)
        control_row = QHBoxLayout()
        control_row.addWidget(self.sort_box)
        control_row.addWidget(self.direction_button)
        control_row.addWidget(upload)
        control_row.addWidget(self.refresh_button)
        control_row.addStretch(1)

        self.scan_status = QLabel(tr("label.waiting_for_scan"))
        content_row = QHBoxLayout()
        filters = self._build_filter_panel()
        self.work_list = WorkListWidget()
        self.work_list.setStyleSheet(
            "QListWidget::item:selected { background: transparent; color: palette(text); }"
        )
        self.work_list.currentItemChanged.connect(self._work_selection_changed)
        self.work_list.itemActivated.connect(self.open_work)
        page_row = QHBoxLayout()
        self.first_page = QPushButton(tr("label.home"))
        self.previous_page = QPushButton(tr("label.previous_page"))
        self.page_label = QLabel(tr("label.page_one_of_one"))
        self.next_page = QPushButton(tr("label.next_page"))
        self.last_page = QPushButton(tr("label.last_page"))
        self.page_jump = QSpinBox()
        self.page_jump.setMinimum(1)
        jump_button = QPushButton(tr("action.jump"))
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
        self.any_tags = QRadioButton(tr("label.match_any"))
        self.all_tags = QRadioButton(tr("label.match_all"))
        self.any_tags.setChecked(True)
        self.any_tags.toggled.connect(self._filters_changed)
        mode_row.addWidget(self.any_tags)
        mode_row.addWidget(self.all_tags)
        layout.addLayout(mode_row)
        self.tag_search = QLineEdit()
        self.tag_search.setPlaceholderText(tr("label.search_tags_or_groups"))
        self.tag_search.textChanged.connect(self._refresh_filter_tags)
        layout.addWidget(self.tag_search)
        tag_content = QWidget()
        self.tag_filter_layout = QGridLayout(tag_content)
        self.tag_filter_layout.setContentsMargins(0, 0, 0, 0)
        self.tag_filter_layout.setAlignment(Qt.AlignTop)
        self.comic_filter = QPushButton(tr("label.comic"))
        self.illustration_filter = QPushButton(tr("label.illustration"))
        self.kind_filter_group = QButtonGroup(self)
        self.kind_filter_group.setExclusive(True)
        for column, (button, kind) in enumerate(
            (
                (self.comic_filter, "comic"),
                (self.illustration_filter, "illustration"),
            )
        ):
            button.setProperty("tagChip", True)
            button.setCheckable(True)
            self.kind_filter_group.addButton(button)
            button.setChecked(kind in self.selected_kinds)
            button.setStyleSheet(self._tag_button_style("#4f7c78"))
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
        self.rating_filter.addItem(tr("label.all_ratings"), ("any", 0))
        self.rating_filter.addItem(tr("label.unrated"), ("unrated", 0))
        for rating in range(1, 4):
            self.rating_filter.addItem("★" * rating, ("exact", rating))
        for rating in range(1, 4):
            self.rating_filter.addItem(
                "★" * rating + " " + tr("label.rating_or_above"), ("at_least", rating)
            )
        self.rating_filter.currentIndexChanged.connect(self._filters_changed)
        layout.addWidget(self.rating_filter)
        clear = QPushButton(tr("action.clear_all_filters"))
        clear.clicked.connect(self.clear_filters)
        layout.addWidget(clear)
        manage_tags = QPushButton(tr("label.manage_tags"))
        manage_tags.clicked.connect(self.open_tag_manager)
        layout.addWidget(manage_tags)
        self._refresh_filter_tags()
        return panel

    @staticmethod
    def _tag_button_style(color: str) -> str:
        return (
            "QPushButton { background: transparent; "
            f"border: 1px solid {color}; border-radius: 15px; "
            "min-height: 30px; max-height: 30px; padding: 0 12px; } "
            f"QPushButton:checked {{ background: {color}; font-weight: 700; }}"
        )

    def _refresh_filter_tags(self) -> None:
        for button in self.custom_tag_buttons:
            self.tag_filter_layout.removeWidget(button)
            button.hide()
            button.deleteLater()
        self.custom_tag_buttons.clear()
        system_search = self.tag_search.text().strip().casefold()
        self.comic_filter.setVisible(
            not system_search or system_search in tr("label.comic").casefold()
        )
        self.illustration_filter.setVisible(
            not system_search or system_search in tr("label.illustration").casefold()
        )
        all_tags = self.catalog.list_tags()
        classified_tags = []
        show_all_authors = system_search == tr("label.author").casefold()
        for tag in self.catalog.list_tags(self.tag_search.text()):
            author = self.catalog.is_author_tag(tag)
            if author and not show_all_authors and tag.id not in self.selected_tag_ids:
                continue
            display_name = self.catalog.tag_display_name(tag, all_tags)
            category = tag_sort_category(
                display_name,
                self.tag_search.fontMetrics(),
                author=author,
            )
            long_tag = is_long_tag_category(category)
            classified_tags.append((category, tag, display_name, long_tag, author))
        classified_tags.sort(key=lambda entry: entry[0])
        row = 1
        column = 0
        for category, tag, display_name, full_row, author in classified_tags:
            button = QPushButton()
            button.setProperty("tagChip", True)
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
            button.setProperty("tagId", tag.id)
            button.setProperty("grouped", tag.group_id is not None)
            color = (
                AUTHOR_TAG_COLOR
                if self.catalog.is_author_tag(tag)
                else "#9a6f7b"
                if tag.group_id
                else "#777"
            )
            button.setStyleSheet(self._tag_button_style(color))
            button.toggled.connect(
                lambda checked, tag_id=tag.id, author_tag=author: self._tag_filter_toggled(
                    tag_id, checked, author_tag
                )
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

    def _tag_filter_toggled(self, tag_id: int, checked: bool, author_tag: bool = False) -> None:
        if checked:
            self.selected_tag_ids.add(tag_id)
        else:
            self.selected_tag_ids.discard(tag_id)
        self._filters_changed()
        if (
            author_tag
            and not checked
            and self.tag_search.text().strip().casefold() != tr("label.author").casefold()
        ):
            self._refresh_filter_tags()

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
        title = QLabel(tr("label.notifications"))
        title.setAlignment(Qt.AlignCenter)
        title.setStyleSheet("font-size: 32px; font-weight: 700;")
        self.notification_list = NotificationListWidget()
        self.notification_list.setSpacing(0)
        self.notification_list.setStyleSheet(
            "QListWidget { background: transparent; border: 1px solid #9a6f7b; "
            "border-radius: 10px; padding: 0; } "
            "QListWidget::item, QListWidget::item:selected { "
            "background: transparent; border: none; }"
        )
        self.notification_list.itemActivated.connect(self.open_notification)
        self.notification_list.resized.connect(
            lambda: QTimer.singleShot(0, self._fill_empty_notification_rows)
        )
        notification_actions = QHBoxLayout()
        delete_selected = QPushButton(tr("action.delete_selected_notifications"))
        delete_selected.clicked.connect(self.delete_notification)
        clear = QPushButton(tr("action.clear_notifications"))
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
        title = QLabel(tr("label.settings"))
        title.setAlignment(Qt.AlignCenter)
        title.setStyleSheet("font-size: 32px; font-weight: 700;")
        self.settings_root = QLabel()
        self.settings_root.setAlignment(Qt.AlignCenter)
        self.settings_root.setWordWrap(True)
        self.settings_root.setTextInteractionFlags(Qt.TextSelectableByMouse)
        choose = QPushButton(tr("label.migrate_library"))
        choose.clicked.connect(self.migrate_root)
        pair = QPushButton(tr("label.phone_pairing_and_devices"))
        pair.clicked.connect(self.open_pairing)
        manual_backup = QPushButton(tr("label.create_manual_backup"))
        manual_backup.clicked.connect(self.create_manual_backup)
        restore_backup = QPushButton(tr("action.restore_backup"))
        restore_backup.clicked.connect(self.restore_backup)
        self.cache_usage = QLabel()
        self.cache_usage.setAlignment(Qt.AlignCenter)
        self.cache_limit = CenteredComboBox()
        for label, value in (
            ("1 GB", 1024**3),
            ("2 GB", 2 * 1024**3),
            ("5 GB", 5 * 1024**3),
            (tr("label.unlimited"), None),
        ):
            self.cache_limit.addItem(label, value)
        self.cache_limit.setCurrentIndex(max(0, self.cache_limit.findData(self.cache.limit())))
        self.cache_limit.currentIndexChanged.connect(self.change_cache_limit)
        clear_cache = QPushButton(tr("label.clear_thumbnail_cache"))
        clear_cache.clicked.connect(self.clear_cache)
        theme_label = QLabel(tr("label.appearance_theme"))
        theme_label.setAlignment(Qt.AlignCenter)
        self.theme_box = CenteredComboBox()
        self.theme_box.addItem(tr("label.follow_system"), "system")
        self.theme_box.addItem(tr("label.light_theme"), "light")
        self.theme_box.addItem(tr("label.dark_theme"), "dark")
        self.theme_box.setCurrentIndex(max(0, self.theme_box.findData(self.appearance.theme())))
        self.theme_box.currentIndexChanged.connect(self.change_theme)
        self.language_box = CenteredComboBox()
        # Each entry is the self-name declared by that language pack. Unlike
        # ordinary combo-box labels, these names must not follow the active locale.
        self.language_box.setProperty("i18nKeepItemText", True)
        for code, name in available_languages():
            self.language_box.addItem(name, code)
        self.language_box.setCurrentIndex(max(0, self.language_box.findData(active_language())))
        self.language_box.currentIndexChanged.connect(self.change_language)
        for button in (choose, pair, manual_backup, restore_backup, clear_cache):
            button.setFixedHeight(42)
        layout.addWidget(title)
        layout.addWidget(self.settings_root)
        layout.addWidget(choose)
        layout.addWidget(pair)
        layout.addWidget(manual_backup)
        layout.addWidget(restore_backup)
        layout.addWidget(theme_label)
        layout.addWidget(self.theme_box)
        layout.addWidget(self.language_box)
        layout.addWidget(self.cache_usage)
        layout.addWidget(self.cache_limit)
        layout.addWidget(clear_cache)
        layout.addStretch(1)
        self.version_label = QLabel(trf("software.version", version=__version__))
        self.version_label.setAlignment(Qt.AlignCenter)
        self.version_label.setStyleSheet("color: palette(mid); padding: 4px;")
        layout.addWidget(self.version_label)
        reset = QPushButton(tr("action.reset_all_settings"))
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
            show_message(
                self, tr("error.reset_settings_failed"), tr("label.library_root_unset"), danger=True
            )
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
            show_message(self, tr("error.reset_settings_failed"), str(exc), danger=True)
            return
        rollback.unlink(missing_ok=True)
        self._startup_backup_checked = True
        self.controller.start()
        if self.server is not None:
            self.server.start()
        app = QApplication.instance()
        if app is not None:
            apply_theme(app, "dark")
        set_language(database, "zh-CN")
        self.selected_tag_ids.clear()
        self.selected_kinds = {"comic"}
        self.comic_filter.setChecked(True)
        self.search_edit.clear()
        self.tag_search.clear()
        self.rating_filter.setCurrentIndex(0)
        self.any_tags.setChecked(True)
        self.theme_box.setCurrentIndex(max(0, self.theme_box.findData("dark")))
        self.language_box.setCurrentIndex(max(0, self.language_box.findData("zh-CN")))
        self.cache_limit.setCurrentIndex(max(0, self.cache_limit.findData(self.cache.limit())))
        self._refresh_filter_tags()
        self.refresh()
        show_message(
            self,
            tr("status.restore_complete"),
            trf("reset.completed", cache_files=removed_cache),
        )

    def choose_root(self) -> None:
        current = self.library.library_root()
        selected = QFileDialog.getExistingDirectory(
            self,
            trf("dialog.choose_library", app_name=APP_NAME),
            str(current or ""),
        )
        if selected:
            self.controller.configure_root(Path(selected))
            self.refresh()

    def prompt_for_library_root(self) -> None:
        """Ask before opening the native directory picker on startup."""
        if self.library.library_root() is not None:
            return
        message_key = _consume_library_prompt_message_key(self.catalog)
        if confirm_action(
            self,
            tr("label.set_library_directory"),
            tr(message_key),
            confirm_text=tr("action.set_directory"),
        ):
            self.choose_root()

    def open_pairing(self) -> None:
        PairingDialog(self.pairing, self).exec()

    def show_main_window(self, page: int = 0) -> None:
        self._show_page(page)
        self.showNormal()
        self.raise_()
        self.activateWindow()

    def show_settings(self) -> None:
        self.show_main_window(2)

    def show_pairing(self) -> None:
        self.show_main_window(0)
        self.open_pairing()

    def migrate_root(self) -> None:
        current = self.library.library_root()
        selected = QFileDialog.getExistingDirectory(
            self,
            trf("dialog.choose_new_library", app_name=APP_NAME),
            str(current.parent if current else ""),
        )
        if not selected:
            return
        try:
            preview = self.migrations.preview(Path(selected))
        except Exception as exc:
            show_message(self, tr("error.migration_unavailable"), str(exc), danger=True)
            return
        if preview.conflicts or preview.missing:
            details = ""
            if preview.conflicts:
                details += (
                    tr("label.duplicate_conflict") + "\n" + "\n".join(preview.conflicts) + "\n"
                )
            if preview.missing:
                details += tr("label.missing_file") + "\n" + "\n".join(preview.missing)
            show_message(self, tr("label.migration_precheck_failed"), details, danger=True)
            return
        if not confirm_action(
            self,
            tr("confirm.confirm_library_migration"),
            trf(
                "migration.confirm",
                files=preview.files,
                size_mb=f"{preview.bytes / 1024 / 1024:.1f}",
            ),
            confirm_text=tr("label.start_migration"),
        ):
            return
        self.controller.pause_watching()
        self.controller.wait_until_idle()
        try:
            result = self.migrations.migrate(Path(selected))
            self.controller.start()
        except Exception as exc:
            self.controller.start()
            show_message(
                self,
                tr("error.migration_failed"),
                trf("migration.rolled_back", error=exc),
                danger=True,
            )
            return
        show_message(
            self,
            tr("status.migration_complete"),
            trf("migration.completed", files=result.files)
            + (
                tr("message.source_directory_deleted")
                if result.old_root_removed
                else tr("message.source_directory_retained")
            ),
        )
        self.refresh()

    def create_manual_backup(self) -> None:
        try:
            path = self.backups.create("manual")
        except Exception as exc:
            show_message(self, tr("error.backup_failed"), str(exc), danger=True)
            return
        show_message(self, tr("status.backup_complete"), trf("backup.saved", path=path))

    def change_cache_limit(self) -> None:
        self.cache.set_limit(self.cache_limit.currentData())
        self.cache_usage.setText(
            trf("cache.usage", size_mb=f"{self.cache.usage() / 1024 / 1024:.1f}")
        )

    def clear_cache(self) -> None:
        removed = self.cache.clear()
        self.cache_usage.setText(tr("label.thumbnail_cache_empty"))
        show_message(self, tr("label.cache_cleared"), trf("cache.cleared", files=removed))

    def change_theme(self) -> None:
        theme = self.theme_box.currentData()
        self.set_theme(theme)

    def set_theme(self, theme: str) -> None:
        if theme not in {"system", "light", "dark"}:
            return
        self.appearance.set_theme(theme)
        if self.theme_box.currentData() != theme:
            self.theme_box.blockSignals(True)
            self.theme_box.setCurrentIndex(max(0, self.theme_box.findData(theme)))
            self.theme_box.blockSignals(False)
        app = QApplication.instance()
        if app:
            apply_theme(app, theme)
        self.theme_changed.emit(theme)

    def change_language(self) -> None:
        code = self.language_box.currentData()
        if not code:
            return
        set_language(self.catalog.database, code)
        self.refresh()
        localize_tree(self)
        self.version_label.setText(trf("software.version", version=__version__))
        self.language_changed.emit(code)

    def restore_backup(self) -> None:
        selected, _ = QFileDialog.getOpenFileName(
            self,
            trf("dialog.choose_backup", app_name=APP_NAME),
            str(self.backups.backup_directory()),
            trf("dialog.backup_filter", app_name=APP_NAME),
        )
        if not selected:
            return
        if not confirm_action(
            self,
            tr("confirm.confirm_restore_backup"),
            tr("confirm.restore_backup_warning"),
            confirm_text=tr("action.restore_backup"),
        ):
            return
        try:
            protection = self.backups.restore(Path(selected))
            self.controller.request_scan()
            self._refresh_filter_tags()
            self.refresh()
        except Exception as exc:
            show_message(self, tr("error.restore_failed"), str(exc), danger=True)
            return
        show_message(self, tr("status.restore_complete"), trf("backup.protection", path=protection))

    def refresh(self) -> None:
        root = self.library.library_root()
        root_text = str(root) if root else tr("label.comic_root_unset")
        self.settings_root.setText(trf("library.current_root", root=root_text))
        self.cache_usage.setText(
            trf("cache.usage", size_mb=f"{self.cache.usage() / 1024 / 1024:.1f}")
        )
        self.refresh_button.setEnabled(root is not None)

        self._refresh_filter_tags()
        self.refresh_works()

        self.notification_list.clear()
        notifications = self.library.list_notifications()
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
        self._fill_empty_notification_rows()
        unread = self.notifications.unread_count()
        self.notification_button.set_unread_count(unread)
        self.notification_count_changed.emit(unread)
        self._catalog_revision = self.catalog.revision

    def _sync_catalog_revision(self) -> None:
        revision = self.catalog.revision
        if revision != self._catalog_revision:
            self.refresh()

    def _show_page(self, index: int) -> None:
        self.pages.setCurrentIndex(index)

    @staticmethod
    def _style_notification_row(widget: QWidget, read: bool) -> None:
        background = "#2b2328" if read else "transparent"
        widget.setStyleSheet(
            f"background: {background}; border: none; "
            "border-bottom: 1px solid #57474f; border-radius: 0;"
        )

    def _fill_empty_notification_rows(self) -> None:
        height = self.notification_list.viewport().height()
        if height <= 0:
            return

        # Remove only old empty slots; real notifications remain untouched.
        for index in range(self.notification_list.count() - 1, -1, -1):
            item = self.notification_list.item(index)
            if item.data(Qt.UserRole) is None:
                widget = self.notification_list.itemWidget(item)
                self.notification_list.takeItem(index)
                if widget is not None:
                    widget.deleteLater()

        occupied = sum(
            self.notification_list.item(index).sizeHint().height()
            for index in range(self.notification_list.count())
        )
        remaining = max(0, height - occupied)
        count = math.ceil(remaining / 54)
        for index in range(count):
            placeholder = QListWidgetItem()
            row_height = min(54, remaining - index * 54)
            placeholder.setSizeHint(QSize(0, max(1, row_height)))
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
        if confirm_action(
            self,
            tr("confirm.clear_notifications_title"),
            tr("confirm.clear_all_notifications_warning"),
            confirm_text=tr("confirm.confirm_clear"),
            danger=True,
        ):
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
            edit_added = confirm_action(
                self,
                tr("label.added_files_list"),
                text + "\n\n" + tr("confirm.edit_added_works_prompt"),
                confirm_text=tr("label.edit_sequentially"),
            )
            if edit_added:
                for work in self.catalog.find_by_file_names(details):
                    self.show_work_detail(work.id)
            return
        show_message(self, tr("label.notification_details"), text or tr("label.no_file_details"))

    def refresh_works(self) -> None:
        self._thumbnail_generation += 1
        thumbnail_generation = self._thumbnail_generation
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
        self.work_list.setUpdatesEnabled(False)
        self.work_list.clear()
        self._animated_movies: list[QMovie] = []
        all_tags = self.catalog.list_tags()
        for work_index, work in enumerate(page.items):
            kind = tr("label.comic") if work.kind == "comic" else tr("label.illustration")
            display_title = work.title or Path(work.file_name).stem
            identity = work.number if work.kind == "comic" else work.file_name
            pending = (
                f" {tr('confirm.replacement_pending')}"
                if work.status == "replacement_pending"
                else ""
            )
            custom_tag_entries = [
                (
                    self.catalog.tag_display_name(tag, all_tags),
                    AUTHOR_TAG_COLOR
                    if self.catalog.is_author_tag(tag)
                    else "#9a6f7b"
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
            tag_entries = [(kind, "#4f7c78"), *[entry[:2] for entry in custom_tag_entries]]
            # Work content is drawn entirely by the custom row widget. Do not set
            # list-item text, or some Windows styles draw it beside the cover.
            item = QListWidgetItem()
            item.setData(Qt.UserRole, work.id)
            item.setSizeHint(QSize(0, 132))
            row_widget = QWidget()
            row_widget.setObjectName("workRow")
            row_layout = QHBoxLayout(row_widget)
            row_layout.setContentsMargins(12, 7, 12, 7)
            image = QLabel()
            image.setObjectName("workCover")
            image.setProperty("thumbnailLoaded", False)
            image.setFixedSize(108, 116)
            image.setAlignment(Qt.AlignCenter)
            shadow = QGraphicsDropShadowEffect(image)
            shadow.setBlurRadius(16)
            shadow.setOffset(0, 6)
            shadow.setColor(QColor(0, 0, 0, 120))
            image.setGraphicsEffect(shadow)
            image.setText("…")
            QTimer.singleShot(
                work_index * 12,
                partial(
                    self._load_work_thumbnail,
                    work,
                    image,
                    thumbnail_generation,
                ),
            )
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
        self.work_list.setUpdatesEnabled(True)
        self.work_list.viewport().update()
        if not page.items:
            self.work_list.addItem(trf("works.empty", app_name=APP_NAME))
        self.page_label.setText(
            trf("works.page_summary", total=page.total, page=page.page, pages=page.pages)
        )
        self.page_jump.setMaximum(page.pages)
        self.page_jump.setValue(page.page)
        self.first_page.setEnabled(page.page > 1)
        self.previous_page.setEnabled(page.page > 1)
        self.next_page.setEnabled(page.page < page.pages)
        self.last_page.setEnabled(page.page < page.pages)

    def _load_work_thumbnail(
        self,
        work,
        image: QLabel,
        generation: int,
    ) -> None:
        if generation != self._thumbnail_generation:
            return
        if (
            not self.isVisible()
            or self.pages.currentIndex() != 0
            or self._has_visible_dialog()
            or self.windowOpacity() <= 0.01
        ):
            QTimer.singleShot(
                120,
                partial(self._load_work_thumbnail, work, image, generation),
            )
            return
        try:
            thumbnail = self.media.thumbnail(work, 102, 108)
            if generation != self._thumbnail_generation:
                return
            if work.kind == "illustration" and thumbnail.suffix == ".gif":
                movie = QMovie(str(thumbnail))
                image.setMovie(movie)
                self._animated_movies.append(movie)
                movie.start()
            else:
                image.setPixmap(QPixmap(str(thumbnail)))
            image.setProperty("thumbnailLoaded", True)
        except (OSError, RuntimeError, ValueError):
            if generation == self._thumbnail_generation:
                image.setText(tr("label.no_cover"))
                image.setProperty("thumbnailLoaded", True)

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
        self.direction_button.setText(
            tr("label.ascending") if ascending else tr("label.descending")
        )
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
                    "border: 2px solid #9a6f7b; border-radius: 12px; }"
                )

    def show_work_detail(self, work_id: int) -> None:
        """Run details and reader sequentially so no hidden modal blocks the main window."""
        dialog = WorkDetailDialog(work_id, self.catalog, self.media, self)
        while True:
            dialog.requested_action = None
            dialog.exec()
            if dialog.metadata_changed:
                self.refresh_works()
                dialog.metadata_changed = False
            action = dialog.requested_action
            if action is None:
                return
            action_name, value, kind = action
            if action_name == "delete":
                self._delete_work(int(value))
                dialog.deleteLater()
                return
            if action_name == "filter_kind":
                self._filter_kind_from_detail(str(value))
                return
            if action_name == "filter_tag":
                self._filter_tag_from_detail(int(value), str(kind))
                return
            if action_name != "read":
                return
            work = self.catalog.get_work(int(value))
            if work is None:
                return
            if self._retired_reader is not None:
                self._retired_reader.deleteLater()
                self._retired_reader = None
            reader_dialog: ReaderDialog | None = None
            try:
                reader_dialog = ReaderDialog(
                    work,
                    ReaderService(self.catalog.database, self.media),
                    self,
                )
                # Prepare the reader first. Member enumeration can touch a slow
                # ZIP on its first open; hiding the main window before this step
                # creates a visible blank pause.
                self.setWindowOpacity(0.0)
                self.setEnabled(False)
                reader_dialog.exec()
            finally:
                # Keep the hidden reader alive until the next reading session.
                # Destroying hundreds of page widgets here blocks restoration of
                # the main window and detail card on both Windows and Linux.
                if reader_dialog is not None:
                    self._retired_reader = reader_dialog
                self.setEnabled(True)
                self.setWindowOpacity(1.0)
                self.raise_()
                self.activateWindow()

    def _delete_work(self, work_id: int) -> None:
        """Delete after the nested detail dialogs have completely unwound."""
        work = self.catalog.get_work(work_id)
        if work is None:
            return
        try:
            root = self.library.library_root()
            if root is None:
                raise ValueError(tr("label.library_root_unset"))
            root = root.resolve()
            path = self.media.work_path(work).resolve()
            if not path.is_relative_to(root):
                raise ValueError(tr("label.work_outside_library"))
            if not path.is_file():
                raise FileNotFoundError(trf("error.file_missing", file_name=work.file_name))
            with self.library.operation_lock:
                path.unlink()
                self.catalog.delete_work(work.id)
                self.media.clear_thumbnail_cache()
        except (OSError, ValueError) as exc:
            show_message(self, tr("error.delete_failed"), str(exc), danger=True)
            return
        self.refresh_works()

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
        selected, _ = QFileDialog.getOpenFileNames(self, tr("action.select_upload_files"))
        if selected:
            self.open_uploads([Path(path) for path in selected])

    def open_uploads(self, paths: list[Path]) -> None:
        try:
            task = self.uploads.prepare(paths)
        except (OSError, ValueError) as exc:
            UploadResultDialog(tr("error.add_to_library_failed"), str(exc), self).exec()
            return
        if task.invalid:
            lines = [f"{item.source.name}：{item.error}" for item in task.invalid]
            self.uploads.cancel(task)
            UploadResultDialog(
                tr("label.invalid_file"),
                tr("message.invalid_upload_batch") + "\n\n" + "\n".join(lines),
                self,
            ).exec()
            return
        if task.conflicts:
            names = "\n".join(item.source.name for item in task.conflicts)
            decision = UploadResultDialog(
                tr("label.duplicate_files_found"),
                trf("upload.conflicts", count=len(task.conflicts), names=names),
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
            UploadResultDialog(tr("error.add_failed"), str(exc), self).exec()
            return
        # UploadService writes the Work rows before the follow-up scan.  The
        # scan therefore sees existing files and has no `added` entries from
        # which to publish a mobile refresh, so publish immediately here.
        self.catalog.notify_library_changed()
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
        self.scan_status.setText(tr("status.scanning_and_validating"))

    def _scan_finished(self, result: ScanResult) -> None:
        library_changed = bool(
            result.added or result.missing or result.renamed or result.replacements
        )
        if library_changed:
            self.catalog.notify_library_changed()
        self.scan_status.setText(
            trf(
                "scan.completed",
                comics=result.comics,
                illustrations=result.illustrations,
                added=len(result.added),
                invalid=len(result.invalid),
            )
        )
        self.refresh_button.setEnabled(self.library.library_root() is not None)
        if library_changed:
            self.refresh()
        if result.replacements:
            self.resolve_replacements()
        if not self._startup_backup_checked:
            self._startup_backup_checked = True
            try:
                self.backups.automatic_if_due()
            except Exception as exc:
                self.scan_status.setText(
                    self.scan_status.text() + trf("backup.automatic_failed", error=exc)
                )

    def resolve_replacements(self) -> None:
        for work in self.library.pending_replacements():
            choice = choose_action(
                self,
                tr("label.work_file_replaced"),
                trf("replacement.confirm", file_name=work.file_name),
                [
                    (tr("label.retain_original_metadata"), "preserve"),
                    (tr("label.import_as_new_work"), "fresh"),
                ],
            )
            if choice is None:
                continue
            try:
                self.library.resolve_replacement(work.id, preserve_metadata=choice == "preserve")
            except Exception as exc:
                show_message(self, tr("error.processing_failed"), str(exc), danger=True)
        self.refresh()

    def _scan_failed(self, message: str) -> None:
        self.scan_status.setText(trf("scan.failed", error=message))
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
            self._tray.showMessage(APP_NAME, trf("tray.minimized", app_name=APP_NAME))

    def exit_application(self) -> None:
        if self._exit_started:
            return
        if self.uploads.active_count():
            choice = choose_action(
                self,
                tr("status.upload_in_progress"),
                trf("upload.active_tasks", count=self.uploads.active_count()),
                [
                    (tr("status.wait_for_task_before_exit"), "wait"),
                    (tr("action.cancel_task_and_exit"), "cancel"),
                ],
            )
            if choice == "wait":
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
            if choice == "cancel":
                self.uploads.cancel_all()
            else:
                self._restart_after_exit = False
                return
        self._finish_exit()

    def quit_application(self) -> None:
        self._restart_after_exit = False
        self.exit_application()

    def restart_application(self) -> None:
        self._restart_after_exit = True
        self.exit_application()

    def _finish_exit(self) -> None:
        if self._exit_started:
            return
        self._exit_started = True
        self._save_window_geometry()
        self._allow_close = True
        if self._restart_after_exit:
            self.request_restart.emit()
        else:
            self.request_exit.emit()


def create_tray(app: QApplication, window: MainWindow) -> QSystemTrayIcon:
    base_icon = app.style().standardIcon(QStyle.StandardPixmap.SP_DirHomeIcon)
    icon = base_icon
    window.setWindowIcon(icon)
    tray = QSystemTrayIcon(icon)
    tray.setToolTip(APP_NAME)
    menu = QMenu()
    # Linux StatusNotifierItem hosts commonly require a bound context menu to
    # register and display the tray icon. Windows does not, so Windows can use
    # explicit primary/context dispatch and preserve the requested distinction.
    if sys.platform != "win32":
        tray.setContextMenu(menu)
    show_action = QAction(tr("tray.show_window"), tray)
    settings_action = QAction(tr("label.settings"), tray)
    pairing_action = QAction(tr("label.phone_pairing"), tray)
    show_action.triggered.connect(window.show_main_window)
    settings_action.triggered.connect(window.show_settings)
    pairing_action.triggered.connect(window.show_pairing)

    theme_menu = QMenu(tr("tray.theme"), menu)
    theme_group = QActionGroup(tray)
    theme_group.setExclusive(True)
    system_action = QAction(tr("label.follow_system"), tray, checkable=True)
    light_action = QAction(tr("label.light_theme"), tray, checkable=True)
    dark_action = QAction(tr("label.dark_theme"), tray, checkable=True)
    system_action.setData("system")
    light_action.setData("light")
    dark_action.setData("dark")
    theme_group.addAction(system_action)
    theme_group.addAction(light_action)
    theme_group.addAction(dark_action)
    theme_menu.addActions(theme_group.actions())
    current_theme = window.appearance.theme()
    system_action.setChecked(current_theme == "system")
    light_action.setChecked(current_theme == "light")
    dark_action.setChecked(current_theme == "dark")
    theme_group.triggered.connect(lambda action: window.set_theme(action.data()))

    def sync_theme(theme: str) -> None:
        system_action.setChecked(theme == "system")
        light_action.setChecked(theme == "light")
        dark_action.setChecked(theme == "dark")

    window.theme_changed.connect(sync_theme)

    def sync_language(_code: str) -> None:
        show_action.setText(tr("tray.show_window"))
        settings_action.setText(tr("label.settings"))
        pairing_action.setText(tr("label.phone_pairing"))
        theme_menu.setTitle(tr("tray.theme"))
        system_action.setText(tr("label.follow_system"))
        light_action.setText(tr("label.light_theme"))
        dark_action.setText(tr("label.dark_theme"))
        restart_action.setText(tr("tray.restart"))
        exit_action.setText(tr("tray.exit"))

    window.language_changed.connect(sync_language)

    restart_action = QAction(tr("tray.restart"), tray)
    restart_action.triggered.connect(window.restart_application)
    exit_action = QAction(tr("tray.exit"), tray)
    exit_action.triggered.connect(window.quit_application)
    menu.addAction(show_action)
    menu.addAction(settings_action)
    menu.addAction(pairing_action)
    menu.addSeparator()
    menu.addMenu(theme_menu)
    menu.addSeparator()
    menu.addAction(restart_action)
    menu.addAction(exit_action)

    def activate_tray(reason: QSystemTrayIcon.ActivationReason) -> None:
        if reason == QSystemTrayIcon.ActivationReason.Trigger:
            window.show_main_window()
        elif sys.platform == "win32" and reason == QSystemTrayIcon.ActivationReason.Context:
            menu.popup(QCursor.pos())

    tray.activated.connect(activate_tray)
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
        tray.setToolTip(
            trf("notifications.tray", app_name=APP_NAME, count=count) if count else APP_NAME
        )

    window.notification_count_changed.connect(update_badge)
    update_badge(window.notifications.unread_count())
    return tray
