"""
粒度滑杆组件。

左=粗（组少，组内差异大）→ 右=细（组多，组内更相似）
滑杆值与 HDBSCAN min_cluster_size 反向映射：
    slider 最左（SLIDER_MIN）→ min_cluster_size 最大（SLIDER_MAX）→ 组最少
    slider 最右（SLIDER_MAX）→ min_cluster_size 最小（SLIDER_MIN）→ 组最多

valueChanged 有 400ms 防抖，避免拖动时频繁触发聚类。
"""
from __future__ import annotations

from PyQt6.QtCore import QTimer, pyqtSignal
from PyQt6.QtWidgets import QHBoxLayout, QLabel, QSlider, QWidget
from PyQt6.QtCore import Qt

from app.config import SLIDER_DEBOUNCE_MS, SLIDER_DEFAULT, SLIDER_MAX, SLIDER_MIN


class GranularitySlider(QWidget):
    granularity_changed = pyqtSignal(int)   # 发出 min_cluster_size 值

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._debounce = QTimer(self)
        self._debounce.setSingleShot(True)
        self._debounce.setInterval(SLIDER_DEBOUNCE_MS)
        self._debounce.timeout.connect(self._emit)

        self._build_ui()

    def _build_ui(self) -> None:
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(6)

        layout.addWidget(QLabel("分组粒度:"))

        coarse_label = QLabel("粗")
        coarse_label.setStyleSheet("color: #888;")
        layout.addWidget(coarse_label)

        self._slider = QSlider(Qt.Orientation.Horizontal)
        self._slider.setRange(SLIDER_MIN, SLIDER_MAX)
        self._slider.setValue(SLIDER_DEFAULT)
        self._slider.setFixedWidth(160)
        self._slider.setToolTip("向左：组更少（粗分）\n向右：组更多（细分）")
        self._slider.valueChanged.connect(self._on_value_changed)
        layout.addWidget(self._slider)

        fine_label = QLabel("细")
        fine_label.setStyleSheet("color: #888;")
        layout.addWidget(fine_label)

        self._value_label = QLabel(self._format_label(SLIDER_DEFAULT))
        self._value_label.setMinimumWidth(60)
        layout.addWidget(self._value_label)

    def _on_value_changed(self, value: int) -> None:
        self._value_label.setText(self._format_label(value))
        self._debounce.start()

    def _emit(self) -> None:
        self.granularity_changed.emit(self._map_to_cluster_size(self._slider.value()))

    def _map_to_cluster_size(self, slider_val: int) -> int:
        """反向映射：slider 左=粗=大 cluster_size，右=细=小 cluster_size。"""
        return SLIDER_MAX - slider_val + SLIDER_MIN

    def _format_label(self, slider_val: int) -> str:
        cs = self._map_to_cluster_size(slider_val)
        return f"(min={cs})"

    def current_cluster_size(self) -> int:
        return self._map_to_cluster_size(self._slider.value())

    def set_enabled(self, enabled: bool) -> None:
        self._slider.setEnabled(enabled)
