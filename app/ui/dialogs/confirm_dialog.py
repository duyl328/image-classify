"""
最终确认弹窗。

汇总展示所有待执行操作（删除/移动/待复查）。
有删除操作时必须勾选确认复选框才能点执行。
"""
from __future__ import annotations

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import (
    QCheckBox, QDialog, QDialogButtonBox, QLabel,
    QScrollArea, QTextEdit, QVBoxLayout, QWidget,
)

from app.core.action_queue import ActionQueue
from app.models.action import ActionType


class ConfirmDialog(QDialog):
    def __init__(self, queue: ActionQueue, parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle("确认执行操作")
        self.setMinimumWidth(460)
        self.setMinimumHeight(320)
        self._queue = queue
        self._build_ui()

    def _build_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setSpacing(12)

        summary = self._queue.get_summary()
        n_delete = summary.get("delete", 0)
        n_move   = summary.get("move",   0)
        n_review = summary.get("review", 0)

        # ── 汇总标题 ────────────────────────────────────────────────────────────
        lines = []
        if n_delete:
            lines.append(f"🗑  删除     {n_delete} 张")
        if n_move:
            lines.append(f"📂  移动     {n_move} 张")
        if n_review:
            lines.append(f"🏷  待复查   {n_review} 张")

        summary_text = "\n".join(lines) if lines else "没有待执行的操作。"
        summary_lbl = QLabel(summary_text)
        summary_lbl.setStyleSheet("font-size: 13px; line-height: 1.8;")
        layout.addWidget(summary_lbl)

        # ── 路径预览（前 30 条）────────────────────────────────────────────────
        all_paths: list[str] = []
        for action_type in ActionType:
            all_paths.extend(self._queue.get_paths(action_type))

        if all_paths:
            preview_paths = all_paths[:30]
            remainder = len(all_paths) - len(preview_paths)
            preview_text = "\n".join(preview_paths)
            if remainder > 0:
                preview_text += f"\n... 还有 {remainder} 个文件"

            text_edit = QTextEdit()
            text_edit.setReadOnly(True)
            text_edit.setPlainText(preview_text)
            text_edit.setFixedHeight(140)
            text_edit.setStyleSheet("background: #1a1a1a; color: #aaa; font-size: 11px;")
            layout.addWidget(text_edit)

        # ── 删除确认复选框 ──────────────────────────────────────────────────────
        self._confirm_cb: QCheckBox | None = None
        if n_delete > 0:
            self._confirm_cb = QCheckBox(
                f"我已确认，将 {n_delete} 张图片移入回收站（可从回收站恢复）"
            )
            self._confirm_cb.setStyleSheet("color: #e67e22;")
            self._confirm_cb.stateChanged.connect(self._update_ok_button)
            layout.addWidget(self._confirm_cb)

        # ── 按钮 ────────────────────────────────────────────────────────────────
        self._btn_box = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        ok_btn = self._btn_box.button(QDialogButtonBox.StandardButton.Ok)
        ok_btn.setText("确认执行")
        ok_btn.setStyleSheet(
            "QPushButton { background: #e67e22; color: white; border-radius: 5px; "
            "padding: 6px 18px; font-weight: bold; }"
        )
        cancel_btn = self._btn_box.button(QDialogButtonBox.StandardButton.Cancel)
        cancel_btn.setText("取消")
        self._btn_box.accepted.connect(self.accept)
        self._btn_box.rejected.connect(self.reject)
        layout.addWidget(self._btn_box)

        # 有删除时初始禁用 OK
        self._update_ok_button()

    def _update_ok_button(self) -> None:
        ok_btn = self._btn_box.button(QDialogButtonBox.StandardButton.Ok)
        if self._confirm_cb is not None:
            ok_btn.setEnabled(self._confirm_cb.isChecked())
        else:
            ok_btn.setEnabled(True)
