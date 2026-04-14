"""Center panel that displays thumbnails for the selected group."""
from __future__ import annotations

from PyQt6.QtCore import QObject, QRunnable, QSize, Qt, QThreadPool, pyqtSignal
from PyQt6.QtGui import QIcon, QImage, QPixmap, QStandardItem, QStandardItemModel
from PyQt6.QtWidgets import (
    QAbstractItemView,
    QComboBox,
    QHBoxLayout,
    QLabel,
    QListView,
    QVBoxLayout,
    QWidget,
)
from PIL import Image

from app.config import THUMBNAIL_CACHE_MB, THUMBNAIL_LOAD_THREADS, THUMBNAIL_SIZE
from app.core.debug_log import log_debug
from app.core.sorter import sort_by_sharpness, sort_by_similarity, sort_by_time
from app.models.image_record import ImageRecord

_CACHE_KEY_ROLE = Qt.ItemDataRole.UserRole
_RECORD_ROLE = Qt.ItemDataRole.UserRole + 1


class _ThumbLoader(QRunnable):
    """Decode a thumbnail in the thread pool and emit a QImage back to the UI thread."""

    class Signals(QObject):
        loaded = pyqtSignal(str, QImage)

    def __init__(self, cache_key: str, path: str, size: tuple[int, int]) -> None:
        super().__init__()
        self.cache_key = cache_key
        self.path = path
        self.size = size
        self.signals = _ThumbLoader.Signals()
        self.cancelled = False

    def run(self) -> None:
        if self.cancelled:
            return

        try:
            img = Image.open(self.path)
            if img.format == "JPEG":
                img.draft("RGB", self.size)
            img.load()
            img = img.convert("RGB")
            img.thumbnail(self.size, Image.Resampling.LANCZOS)

            width, height = self.size
            canvas = Image.new("RGB", (width, height), (42, 42, 42))
            offset_x = (width - img.width) // 2
            offset_y = (height - img.height) // 2
            canvas.paste(img, (offset_x, offset_y))
            data = canvas.tobytes("raw", "RGB")
            image = QImage(
                data,
                width,
                height,
                width * 3,
                QImage.Format.Format_RGB888,
            ).copy()
        except Exception:
            image = QImage()

        if not self.cancelled:
            self.signals.loaded.emit(self.cache_key, image)


class GridPanel(QWidget):
    thumbnail_clicked = pyqtSignal(object, list)
    selection_changed = pyqtSignal(list)

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._records: list[ImageRecord] = []
        self._cache_key_to_row: dict[str, int] = {}
        self._pixmap_cache: dict[str, QPixmap] = {}
        self._active_loaders: list[_ThumbLoader] = []

        pool = QThreadPool.globalInstance()
        pool.setMaxThreadCount(THUMBNAIL_LOAD_THREADS)

        from PyQt6.QtGui import QPixmapCache

        QPixmapCache.setCacheLimit(THUMBNAIL_CACHE_MB * 1024)
        self._build_ui()

    def _build_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        sort_bar = QWidget()
        sort_bar.setFixedHeight(36)
        sort_bar.setStyleSheet("background: #1a1a1a; border-bottom: 1px solid #333;")
        sort_layout = QHBoxLayout(sort_bar)
        sort_layout.setContentsMargins(10, 0, 10, 0)
        sort_layout.setSpacing(8)

        sort_layout.addWidget(QLabel("排序:"))
        self._sort_combo = QComboBox()
        self._sort_combo.addItems(["时间", "相似度", "清晰度"])
        self._sort_combo.currentIndexChanged.connect(self._apply_sort)
        sort_layout.addWidget(self._sort_combo)
        sort_layout.addStretch()

        self._count_label = QLabel("0 张")
        self._count_label.setStyleSheet("color: #888; font-size: 11px;")
        sort_layout.addWidget(self._count_label)

        self._sel_label = QLabel("")
        self._sel_label.setStyleSheet("color: #4a9eff; font-size: 11px;")
        sort_layout.addWidget(self._sel_label)

        layout.addWidget(sort_bar)

        self._model = QStandardItemModel()
        self._view = QListView()
        self._view.setModel(self._model)
        self._view.setViewMode(QListView.ViewMode.IconMode)
        self._view.setResizeMode(QListView.ResizeMode.Adjust)
        self._view.setGridSize(QSize(THUMBNAIL_SIZE[0] + 10, THUMBNAIL_SIZE[1] + 10))
        self._view.setIconSize(QSize(*THUMBNAIL_SIZE))
        self._view.setUniformItemSizes(True)
        self._view.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        self._view.setStyleSheet("QListView { background: #181818; border: none; }")
        self._view.clicked.connect(self._on_clicked)
        self._view.selectionModel().selectionChanged.connect(self._on_selection_changed)
        layout.addWidget(self._view, 1)

    def load_group(self, records: list[ImageRecord]) -> None:
        log_debug("grid_panel_load_group_enter", record_count=len(records))
        self._cancel_active_loaders()
        self._records = list(records)
        self._apply_sort()
        log_debug("grid_panel_load_group_done", record_count=len(self._records))

    def get_selected_records(self) -> list[ImageRecord]:
        rows = [index.row() for index in self._view.selectionModel().selectedIndexes()]
        return [self._records[row] for row in rows if 0 <= row < len(self._records)]

    def get_all_records(self) -> list[ImageRecord]:
        return list(self._records)

    def _apply_sort(self) -> None:
        sort_index = self._sort_combo.currentIndex()
        if sort_index == 0:
            self._records = sort_by_time(self._records)
        elif sort_index == 1:
            self._records = sort_by_similarity(self._records)
        elif sort_index == 2:
            self._records = sort_by_sharpness(self._records)
        self._populate()

    def _populate(self) -> None:
        log_debug("grid_panel_populate_enter", record_count=len(self._records))
        self._cancel_active_loaders()
        self._model.clear()
        self._cache_key_to_row.clear()

        self._count_label.setText(f"{len(self._records)} 张")
        self._sel_label.setText("")

        thumb_width, thumb_height = THUMBNAIL_SIZE
        placeholder = QPixmap(thumb_width, thumb_height)
        placeholder.fill(Qt.GlobalColor.darkGray)
        placeholder_icon = QIcon(placeholder)

        for row, record in enumerate(self._records):
            item = QStandardItem()
            item.setData(record.cache_key, _CACHE_KEY_ROLE)
            item.setData(record, _RECORD_ROLE)
            item.setIcon(
                placeholder_icon
                if record.cache_key not in self._pixmap_cache
                else QIcon(self._pixmap_cache[record.cache_key])
            )
            item.setText(record.display_name())
            item.setToolTip(f"{record.path}\n{record.size_mb()} MB")
            self._model.appendRow(item)
            self._cache_key_to_row[record.cache_key] = row

        scheduled = 0
        for record in self._records:
            if record.cache_key in self._pixmap_cache:
                continue
            loader = _ThumbLoader(record.cache_key, record.path, THUMBNAIL_SIZE)
            loader.signals.loaded.connect(self._on_thumb_loaded)
            self._active_loaders.append(loader)
            QThreadPool.globalInstance().start(loader)
            scheduled += 1

        log_debug(
            "grid_panel_populate_done",
            record_count=len(self._records),
            loader_count=scheduled,
            cached_count=len(self._records) - scheduled,
        )

    def _on_thumb_loaded(self, cache_key: str, image: QImage) -> None:
        if image.isNull():
            return

        pixmap = QPixmap.fromImage(image)
        self._pixmap_cache[cache_key] = pixmap
        row = self._cache_key_to_row.get(cache_key)
        if row is None:
            return

        item = self._model.item(row)
        if item and item.data(_CACHE_KEY_ROLE) == cache_key:
            item.setIcon(QIcon(pixmap))

    def _cancel_active_loaders(self) -> None:
        for loader in self._active_loaders:
            loader.cancelled = True
        self._active_loaders.clear()

    def _on_clicked(self, index) -> None:
        row = index.row()
        if 0 <= row < len(self._records):
            self.thumbnail_clicked.emit(self._records[row], self._records)

    def _on_selection_changed(self, selected, deselected) -> None:
        selected_records = self.get_selected_records()
        count = len(selected_records)
        self._sel_label.setText(f"已选 {count} 张" if count > 0 else "")
        self.selection_changed.emit(selected_records)
