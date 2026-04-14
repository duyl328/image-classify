"""
近重复图片查看对话框。

逐组展示近重复图（横向排列 ThumbnailWidget）。
自动高亮清晰度最高的图为"推荐保留"。
操作：保留最佳/保留选中/跳过，结果通过 action_requested 信号传出。
"""
from __future__ import annotations

from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtWidgets import (
    QDialog, QDialogButtonBox, QHBoxLayout, QLabel,
    QPushButton, QScrollArea, QVBoxLayout, QWidget,
)

from app.models.action import ActionType
from app.models.image_record import ImageRecord
from app.ui.widgets.thumbnail_widget import ThumbnailWidget
from app.core.sorter import sort_by_sharpness


class DuplicateDialog(QDialog):
    action_requested = pyqtSignal(object, list, object)  # (ActionType, [ImageRecord], target)

    def __init__(self, dup_groups: list[list[ImageRecord]], parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle("近重复图片处理")
        self.setMinimumSize(700, 480)
        self._groups = dup_groups
        self._current_idx = 0
        self._thumb_widgets: list[ThumbnailWidget] = []
        self._selected_rec: ImageRecord | None = None
        self._build_ui()
        self._show_group(0)

    def _build_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setSpacing(10)

        # ── 导航栏 ──────────────────────────────────────────────────────────────
        nav_bar = QHBoxLayout()
        self._prev_btn = QPushButton("◀ 上一组")
        self._prev_btn.clicked.connect(lambda: self._show_group(self._current_idx - 1))
        nav_bar.addWidget(self._prev_btn)

        self._group_label = QLabel()
        self._group_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._group_label.setStyleSheet("font-size: 13px; font-weight: bold;")
        nav_bar.addWidget(self._group_label, 1)

        self._next_btn = QPushButton("下一组 ▶")
        self._next_btn.clicked.connect(lambda: self._show_group(self._current_idx + 1))
        nav_bar.addWidget(self._next_btn)
        layout.addLayout(nav_bar)

        # ── 提示 ────────────────────────────────────────────────────────────────
        hint = QLabel("蓝色边框 = 清晰度最高（推荐保留）。点击图片可切换选中。")
        hint.setStyleSheet("color: #888; font-size: 11px;")
        hint.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(hint)

        # ── 缩略图区域 ──────────────────────────────────────────────────────────
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        scroll.setFixedHeight(300)
        self._thumb_container = QWidget()
        self._thumb_layout = QHBoxLayout(self._thumb_container)
        self._thumb_layout.setAlignment(Qt.AlignmentFlag.AlignLeft)
        self._thumb_layout.setSpacing(8)
        scroll.setWidget(self._thumb_container)
        layout.addWidget(scroll)

        # ── 操作按钮 ────────────────────────────────────────────────────────────
        action_bar = QHBoxLayout()
        action_bar.addStretch()

        keep_best_btn = QPushButton("✅ 保留最佳，删除其余")
        keep_best_btn.setStyleSheet(
            "QPushButton { background: #27ae60; color: white; border-radius: 5px; "
            "padding: 6px 16px; } QPushButton:hover { background: #219a52; }"
        )
        keep_best_btn.clicked.connect(self._keep_best)
        action_bar.addWidget(keep_best_btn)

        keep_sel_btn = QPushButton("☑ 保留选中，删除其余")
        keep_sel_btn.setStyleSheet(
            "QPushButton { background: #2980b9; color: white; border-radius: 5px; "
            "padding: 6px 16px; } QPushButton:hover { background: #2471a3; }"
        )
        keep_sel_btn.clicked.connect(self._keep_selected)
        action_bar.addWidget(keep_sel_btn)

        skip_btn = QPushButton("跳过此组")
        skip_btn.clicked.connect(lambda: self._show_group(self._current_idx + 1))
        action_bar.addWidget(skip_btn)

        action_bar.addStretch()
        layout.addLayout(action_bar)

        # ── 关闭按钮 ────────────────────────────────────────────────────────────
        close_box = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        close_box.rejected.connect(self.reject)
        layout.addWidget(close_box)

    # ── 内部逻辑 ──────────────────────────────────────────────────────────────────

    def _show_group(self, idx: int) -> None:
        if not self._groups:
            return
        idx = max(0, min(idx, len(self._groups) - 1))
        self._current_idx = idx
        group = self._groups[idx]

        self._group_label.setText(f"第 {idx + 1} 组 / 共 {len(self._groups)} 组  ({len(group)} 张)")
        self._prev_btn.setEnabled(idx > 0)
        self._next_btn.setEnabled(idx < len(self._groups) - 1)

        # 清空缩略图区
        for w in self._thumb_widgets:
            self._thumb_layout.removeWidget(w)
            w.deleteLater()
        self._thumb_widgets.clear()
        self._selected_rec = None

        # 按清晰度降序，最清晰的为推荐
        sorted_group = sort_by_sharpness(group)
        best = sorted_group[0] if sorted_group else None

        for rec in sorted_group:
            thumb = ThumbnailWidget(rec, size=(180, 180))
            if rec is best:
                thumb.selected = True
                self._selected_rec = rec
            thumb.clicked.connect(self._on_thumb_clicked)
            self._thumb_layout.addWidget(thumb)
            self._thumb_widgets.append(thumb)
            # 异步加载缩略图
            self._load_thumb(thumb, rec)

    def _load_thumb(self, thumb: ThumbnailWidget, rec: ImageRecord) -> None:
        from PyQt6.QtCore import QRunnable, QThreadPool, QObject
        from PyQt6.QtGui import QImage
        from PIL import Image

        class Loader(QRunnable):
            class Sig(QObject):
                done = pyqtSignal(QImage)
            def __init__(self_, path):
                super().__init__()
                self_.path = path
                self_.signals = Loader.Sig()
            def run(self_):
                try:
                    img = Image.open(self_.path)
                    img.draft("RGB", (180, 180))
                    img.load()
                    img = img.convert("RGB")
                    img.thumbnail((180, 180))
                    data = img.tobytes("raw", "RGB")
                    qimg = QImage(data, img.width, img.height,
                                  img.width * 3, QImage.Format.Format_RGB888)
                    self_.signals.done.emit(qimg.copy())
                except Exception:
                    self_.signals.done.emit(QImage())

        loader = Loader(rec.path)
        loader.signals.done.connect(thumb.set_image)
        QThreadPool.globalInstance().start(loader)

    def _on_thumb_clicked(self, record: ImageRecord) -> None:
        self._selected_rec = record
        for w in self._thumb_widgets:
            w.selected = (w.record is record)

    def _keep_best(self) -> None:
        if not self._groups:
            return
        group = self._groups[self._current_idx]
        sorted_group = sort_by_sharpness(group)
        if not sorted_group:
            return
        to_delete = sorted_group[1:]  # 删除清晰度较低的
        if to_delete:
            self.action_requested.emit(ActionType.DELETE, to_delete, None)
        self._show_group(self._current_idx + 1)

    def _keep_selected(self) -> None:
        if not self._selected_rec or not self._groups:
            return
        group = self._groups[self._current_idx]
        to_delete = [r for r in group if r is not self._selected_rec]
        if to_delete:
            self.action_requested.emit(ActionType.DELETE, to_delete, None)
        self._show_group(self._current_idx + 1)
