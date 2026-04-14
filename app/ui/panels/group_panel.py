"""
左侧分组列表面板。

每行显示：3 张代表图缩略图 + 组名 + 数量。
特殊组：近重复（置顶）、未分类（置底）。
点击行触发 group_selected 信号。
"""
from __future__ import annotations

from PyQt6.QtCore import Qt, pyqtSignal, QSize, QRunnable, QThreadPool, QObject
from PyQt6.QtGui import QPixmap, QColor, QImage
from PyQt6.QtWidgets import (
    QHBoxLayout, QLabel, QListWidget, QListWidgetItem,
    QVBoxLayout, QWidget, QFrame,
)
from PIL import Image

from app.config import GROUP_COVER_COUNT, GROUP_COVER_SIZE
from app.core.debug_log import log_debug
from app.models.image_record import ImageRecord

CLUSTER_ID_DUPLICATES = -2   # 近重复虚拟组


class _CoverLoader(QRunnable):
    """后台加载分组代表图。"""

    class Signals(QObject):
        loaded = pyqtSignal(int, int, QImage)  # (cluster_id, slot_index, image)

    def __init__(self, cluster_id: int, slot: int, path: str) -> None:
        super().__init__()
        self.cluster_id = cluster_id
        self.slot = slot
        self.path = path
        self.signals = _CoverLoader.Signals()
        self.cancelled = False

    def run(self) -> None:
        if self.cancelled:
            return
        try:
            img = Image.open(self.path)
            img.draft("RGB", GROUP_COVER_SIZE)
            img.load()
            img = img.convert("RGB").resize(GROUP_COVER_SIZE)
            data = img.tobytes("raw", "RGB")
            qimg = QImage(data, img.width, img.height, img.width * 3,
                          QImage.Format.Format_RGB888)
            image = qimg.copy()
        except Exception:
            image = QImage()
        if not self.cancelled:
            self.signals.loaded.emit(self.cluster_id, self.slot, image)


class GroupRowWidget(QWidget):
    """分组列表中的单行 Widget。"""

    def __init__(self, cluster_id: int, label: str, count: int, parent=None) -> None:
        super().__init__(parent)
        self.cluster_id = cluster_id
        self._cover_labels: list[QLabel] = []
        self._build_ui(label, count)

    def _build_ui(self, label: str, count: int) -> None:
        layout = QHBoxLayout(self)
        layout.setContentsMargins(8, 6, 8, 6)
        layout.setSpacing(6)

        # 代表图
        covers_widget = QWidget()
        covers_layout = QHBoxLayout(covers_widget)
        covers_layout.setContentsMargins(0, 0, 0, 0)
        covers_layout.setSpacing(2)
        w, h = GROUP_COVER_SIZE
        for _ in range(GROUP_COVER_COUNT):
            lbl = QLabel()
            lbl.setFixedSize(QSize(w, h))
            lbl.setStyleSheet("background: #2a2a2a; border-radius: 3px;")
            covers_layout.addWidget(lbl)
            self._cover_labels.append(lbl)
        layout.addWidget(covers_widget)

        # 文字
        text_widget = QWidget()
        text_layout = QVBoxLayout(text_widget)
        text_layout.setContentsMargins(4, 0, 0, 0)
        text_layout.setSpacing(2)

        name_lbl = QLabel(label)
        name_lbl.setStyleSheet("font-weight: bold; font-size: 12px;")
        text_layout.addWidget(name_lbl)

        count_lbl = QLabel(f"{count} 张")
        count_lbl.setStyleSheet("color: #888; font-size: 11px;")
        text_layout.addWidget(count_lbl)

        layout.addWidget(text_widget, 1)

    def set_cover(self, slot: int, pixmap: QPixmap) -> None:
        if slot < len(self._cover_labels) and not pixmap.isNull():
            w, h = GROUP_COVER_SIZE
            scaled = pixmap.scaled(QSize(w, h),
                                   Qt.AspectRatioMode.KeepAspectRatio,
                                   Qt.TransformationMode.SmoothTransformation)
            self._cover_labels[slot].setPixmap(scaled)


class GroupPanel(QWidget):
    group_selected = pyqtSignal(int)    # cluster_id（-1 = 未分类，-2 = 近重复）

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._row_widgets: dict[int, GroupRowWidget] = {}
        self._dup_records: list[list[ImageRecord]] = []
        self._build_ui()

    def _build_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        self._list = QListWidget()
        self._list.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self._list.setStyleSheet("""
            QListWidget { border: none; background: #1e1e1e; }
            QListWidget::item { border-bottom: 1px solid #2a2a2a; }
            QListWidget::item:selected { background: #2d4a6e; }
            QListWidget::item:hover { background: #252525; }
        """)
        self._list.currentItemChanged.connect(self._on_item_changed)
        layout.addWidget(self._list)

    def populate(
        self,
        groups: dict[int, list[ImageRecord]],
        dup_groups: list[list[ImageRecord]] | None = None,
    ) -> None:
        """填充分组列表。groups: {cluster_id: [records]}"""
        # 取消旧的加载任务
        QThreadPool.globalInstance().clear()
        self._list.clear()
        self._row_widgets.clear()
        self._dup_records = dup_groups or []

        # ── 近重复组（置顶）─────────────────────────────────────────────────────
        if self._dup_records:
            total_dup = sum(len(g) for g in self._dup_records)
            self._add_row(CLUSTER_ID_DUPLICATES, f"🔁 近重复", total_dup,
                          self._dup_records[0] if self._dup_records else [])

        # ── 普通组（按大小降序）────────────────────────────────────────────────
        sorted_ids = sorted(
            (cid for cid in groups if cid != -1),
            key=lambda cid: -len(groups[cid]),
        )
        for i, cid in enumerate(sorted_ids):
            recs = groups[cid]
            self._add_row(cid, f"组 {i + 1}", len(recs), recs)

        # ── 未分类（置底）───────────────────────────────────────────────────────
        if -1 in groups and groups[-1]:
            recs = groups[-1]
            self._add_row(-1, "📋 未分类", len(recs), recs)

        # 自动选中第一项
        if self._list.count() > 0:
            self._list.setCurrentRow(0)

    def _add_row(self, cluster_id: int, label: str, count: int,
                 sample_records: list[ImageRecord]) -> None:
        row_widget = GroupRowWidget(cluster_id, label, count)
        self._row_widgets[cluster_id] = row_widget

        item = QListWidgetItem()
        item.setData(Qt.ItemDataRole.UserRole, cluster_id)
        item.setSizeHint(row_widget.sizeHint())
        self._list.addItem(item)
        self._list.setItemWidget(item, row_widget)

        # 异步加载代表图
        for slot, rec in enumerate(sample_records[:GROUP_COVER_COUNT]):
            loader = _CoverLoader(cluster_id, slot, rec.path)
            loader.signals.loaded.connect(self._on_cover_loaded)
            QThreadPool.globalInstance().start(loader)

    def _on_cover_loaded(self, cluster_id: int, slot: int, image: QImage) -> None:
        row = self._row_widgets.get(cluster_id)
        if row and not image.isNull():
            row.set_cover(slot, QPixmap.fromImage(image))

    def _on_item_changed(self, current: QListWidgetItem, _) -> None:
        if current is None:
            return
        cluster_id = current.data(Qt.ItemDataRole.UserRole)
        if cluster_id is not None:
            self.group_selected.emit(cluster_id)

    def select_cluster(self, cluster_id: int) -> None:
        """从外部指定选中某个 cluster_id。"""
        for i in range(self._list.count()):
            item = self._list.item(i)
            if item.data(Qt.ItemDataRole.UserRole) == cluster_id:
                self._list.setCurrentRow(i)
                break

    def populate(
        self,
        groups: dict[int, list[ImageRecord]],
        dup_groups: list[list[ImageRecord]] | None = None,
    ) -> None:
        log_debug(
            "group_panel_populate_enter",
            group_count=len(groups),
            duplicate_group_count=len(dup_groups or []),
        )
        QThreadPool.globalInstance().clear()
        self._list.clear()
        self._row_widgets.clear()
        self._dup_records = dup_groups or []

        if self._dup_records:
            total_dup = sum(len(group) for group in self._dup_records)
            self._add_row(
                CLUSTER_ID_DUPLICATES,
                "Near Duplicates",
                total_dup,
                self._dup_records[0] if self._dup_records else [],
            )

        sorted_ids = sorted(
            (cluster_id for cluster_id in groups if cluster_id != -1),
            key=lambda cluster_id: -len(groups[cluster_id]),
        )
        for index, cluster_id in enumerate(sorted_ids, start=1):
            records = groups[cluster_id]
            self._add_row(cluster_id, f"Group {index}", len(records), records)

        if -1 in groups and groups[-1]:
            self._add_row(-1, "Unclustered", len(groups[-1]), groups[-1])

        item_count = self._list.count()
        if item_count > 0:
            log_debug("group_panel_populate_select_first_row_start", item_count=item_count)
            self._list.setCurrentRow(0)
            log_debug("group_panel_populate_select_first_row_done")
        log_debug("group_panel_populate_done", item_count=item_count)

    def _on_item_changed(self, current: QListWidgetItem, _) -> None:
        if current is None:
            return
        cluster_id = current.data(Qt.ItemDataRole.UserRole)
        if cluster_id is not None:
            log_debug("group_panel_item_changed", cluster_id=cluster_id)
            self.group_selected.emit(cluster_id)
