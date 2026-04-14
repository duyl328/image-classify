"""
右侧操作面板。

分两区：
1. 整组操作（始终可用，作用于当前组全部图片）
2. 选中操作（多选后激活，作用于选中图片）

底部常驻暂存队列汇总 + "执行所有"按钮。
"""
from __future__ import annotations

from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtWidgets import (
    QFileDialog, QFrame, QGroupBox, QHBoxLayout,
    QLabel, QPushButton, QVBoxLayout, QWidget,
)

from app.models.action import ActionType
from app.models.image_record import ImageRecord


class ActionPanel(QWidget):
    action_requested = pyqtSignal(object, list, object)  # (ActionType, [ImageRecord], target_dir|None)
    execute_requested = pyqtSignal()

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._current_group: list[ImageRecord] = []
        self._selected: list[ImageRecord] = []
        self.setMinimumWidth(180)
        self.setMaximumWidth(240)
        self._build_ui()

    def _build_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.setSpacing(10)

        # ── 整组操作 ────────────────────────────────────────────────────────────
        group_box = QGroupBox("整组操作")
        group_box.setStyleSheet("QGroupBox { font-weight: bold; color: #ccc; }")
        gb_layout = QVBoxLayout(group_box)
        gb_layout.setSpacing(6)

        self._keep_all_btn   = self._make_btn("✅ 整组保留",   "#27ae60")
        self._delete_all_btn = self._make_btn("🗑 整组删除",   "#c0392b")
        self._move_all_btn   = self._make_btn("📂 整组移动...", "#2980b9")
        self._review_all_btn = self._make_btn("🏷 整组待复查", "#8e44ad")

        self._keep_all_btn.clicked.connect(
            lambda: self._emit(ActionType.DELETE, use_selected=False, keep=True))
        self._delete_all_btn.clicked.connect(
            lambda: self._emit(ActionType.DELETE, use_selected=False))
        self._move_all_btn.clicked.connect(
            lambda: self._emit(ActionType.MOVE, use_selected=False))
        self._review_all_btn.clicked.connect(
            lambda: self._emit(ActionType.REVIEW, use_selected=False))

        for btn in [self._keep_all_btn, self._delete_all_btn,
                    self._move_all_btn, self._review_all_btn]:
            gb_layout.addWidget(btn)
        layout.addWidget(group_box)

        # ── 选中操作 ────────────────────────────────────────────────────────────
        sel_box = QGroupBox("选中操作")
        sel_box.setStyleSheet("QGroupBox { font-weight: bold; color: #ccc; }")
        sb_layout = QVBoxLayout(sel_box)
        sb_layout.setSpacing(6)

        self._sel_label = QLabel("未选中任何图片")
        self._sel_label.setStyleSheet("color: #888; font-size: 11px;")
        self._sel_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        sb_layout.addWidget(self._sel_label)

        self._del_sel_btn    = self._make_btn("🗑 删除选中",   "#c0392b")
        self._move_sel_btn   = self._make_btn("📂 移动选中...", "#2980b9")
        self._review_sel_btn = self._make_btn("🏷 标记待复查", "#8e44ad")

        self._del_sel_btn.clicked.connect(
            lambda: self._emit(ActionType.DELETE, use_selected=True))
        self._move_sel_btn.clicked.connect(
            lambda: self._emit(ActionType.MOVE, use_selected=True))
        self._review_sel_btn.clicked.connect(
            lambda: self._emit(ActionType.REVIEW, use_selected=True))

        for btn in [self._del_sel_btn, self._move_sel_btn, self._review_sel_btn]:
            btn.setEnabled(False)
            sb_layout.addWidget(btn)
        layout.addWidget(sel_box)

        layout.addStretch()

        # ── 暂存汇总 ────────────────────────────────────────────────────────────
        sep = QFrame()
        sep.setFrameShape(QFrame.Shape.HLine)
        sep.setStyleSheet("color: #333;")
        layout.addWidget(sep)

        self._summary_delete = QLabel("删除：0 张")
        self._summary_move   = QLabel("移动：0 张")
        self._summary_review = QLabel("待复查：0 张")
        for lbl in [self._summary_delete, self._summary_move, self._summary_review]:
            lbl.setStyleSheet("color: #888; font-size: 11px;")
            layout.addWidget(lbl)

        self._execute_btn = QPushButton("⚡ 执行所有操作")
        self._execute_btn.setEnabled(False)
        self._execute_btn.setFixedHeight(36)
        self._execute_btn.setStyleSheet(
            "QPushButton { background: #e67e22; color: white; border-radius: 6px; "
            "font-weight: bold; }"
            "QPushButton:hover { background: #d35400; }"
            "QPushButton:disabled { background: #444; color: #666; }"
        )
        self._execute_btn.clicked.connect(self.execute_requested)
        layout.addWidget(self._execute_btn)

    # ── 公共接口 ──────────────────────────────────────────────────────────────────

    def set_current_group(self, records: list[ImageRecord]) -> None:
        self._current_group = records
        has_group = bool(records)
        for btn in [self._delete_all_btn, self._move_all_btn, self._review_all_btn]:
            btn.setEnabled(has_group)

    def update_selection(self, records: list[ImageRecord]) -> None:
        self._selected = records
        n = len(records)
        has_sel = n > 0
        self._sel_label.setText(f"已选 {n} 张" if has_sel else "未选中任何图片")
        for btn in [self._del_sel_btn, self._move_sel_btn, self._review_sel_btn]:
            btn.setEnabled(has_sel)

    def update_queue_summary(self, summary: dict[str, int]) -> None:
        self._summary_delete.setText(f"删除：{summary.get('delete', 0)} 张")
        self._summary_move.setText(f"移动：{summary.get('move', 0)} 张")
        self._summary_review.setText(f"待复查：{summary.get('review', 0)} 张")
        total = sum(summary.values())
        self._execute_btn.setEnabled(total > 0)
        if total > 0:
            self._execute_btn.setText(f"⚡ 执行所有操作（{total} 张）")
        else:
            self._execute_btn.setText("⚡ 执行所有操作")

    # ── 内部逻辑 ──────────────────────────────────────────────────────────────────

    def _emit(self, action_type: ActionType, *, use_selected: bool, keep: bool = False) -> None:
        if keep:
            # "保留"不加入队列，只是不做任何操作（未来可扩展为标记）
            return

        targets = self._selected if use_selected else self._current_group
        if not targets:
            return

        target_dir = None
        if action_type == ActionType.MOVE:
            target_dir = QFileDialog.getExistingDirectory(self, "选择目标目录")
            if not target_dir:
                return

        self.action_requested.emit(action_type, list(targets), target_dir)

    @staticmethod
    def _make_btn(text: str, color: str) -> QPushButton:
        btn = QPushButton(text)
        btn.setFixedHeight(30)
        btn.setStyleSheet(
            f"QPushButton {{ background: {color}; color: white; border-radius: 5px; "
            f"font-size: 12px; }}"
            f"QPushButton:hover {{ background: {color}cc; }}"
            f"QPushButton:disabled {{ background: #3a3a3a; color: #666; }}"
        )
        return btn
