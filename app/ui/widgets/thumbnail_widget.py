"""
单张图片缩略图组件。

用于近重复对话框的横向排列小图，不用于主网格
（主网格用 QListView + QStandardItemModel 做虚拟化）。

三种视觉状态：normal / hover / selected（蓝色边框高亮）。
"""
from __future__ import annotations

from PyQt6.QtCore import Qt, pyqtSignal, QSize
from PyQt6.QtGui import QColor, QPainter, QPen, QPixmap, QImage
from PyQt6.QtWidgets import QLabel, QVBoxLayout, QWidget

from app.config import THUMBNAIL_SIZE
from app.models.image_record import ImageRecord

_BORDER_NORMAL = QColor("#cccccc")
_BORDER_HOVER = QColor("#4a9eff")
_BORDER_SELECTED = QColor("#1a7fe8")
_BORDER_WIDTH_NORMAL = 1
_BORDER_WIDTH_SELECTED = 3


class ThumbnailWidget(QWidget):
    clicked = pyqtSignal(object)         # ImageRecord
    double_clicked = pyqtSignal(object)  # ImageRecord

    def __init__(self, record: ImageRecord, size: tuple[int, int] = THUMBNAIL_SIZE, parent=None) -> None:
        super().__init__(parent)
        self.record = record
        self._size = size
        self._selected = False
        self._hovered = False
        self._pixmap: QPixmap | None = None

        self.setFixedSize(QSize(size[0] + 8, size[1] + 36))
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setMouseTracking(True)
        self._build_ui()

    def _build_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(4, 4, 4, 4)
        layout.setSpacing(2)

        self._img_label = QLabel()
        self._img_label.setFixedSize(QSize(*self._size))
        self._img_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._img_label.setStyleSheet("background: #2a2a2a;")
        layout.addWidget(self._img_label)

        self._name_label = QLabel(self.record.display_name())
        self._name_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._name_label.setMaximumWidth(self._size[0])
        self._name_label.setStyleSheet("font-size: 10px; color: #aaa;")
        # 文件名过长时省略
        metrics = self._name_label.fontMetrics()
        elided = metrics.elidedText(
            self.record.display_name(),
            Qt.TextElideMode.ElideMiddle,
            self._size[0],
        )
        self._name_label.setText(elided)
        layout.addWidget(self._name_label)

    def set_pixmap(self, pixmap: QPixmap) -> None:
        self._pixmap = pixmap
        scaled = pixmap.scaled(
            QSize(*self._size),
            Qt.AspectRatioMode.KeepAspectRatio,
            Qt.TransformationMode.SmoothTransformation,
        )
        self._img_label.setPixmap(scaled)

    def set_image(self, image: QImage) -> None:
        if image.isNull():
            self._img_label.clear()
            return
        self.set_pixmap(QPixmap.fromImage(image))

    @property
    def selected(self) -> bool:
        return self._selected

    @selected.setter
    def selected(self, value: bool) -> None:
        self._selected = value
        self.update()

    # ── 事件 ─────────────────────────────────────────────────────────────────────

    def mousePressEvent(self, event) -> None:
        self.clicked.emit(self.record)

    def mouseDoubleClickEvent(self, event) -> None:
        self.double_clicked.emit(self.record)

    def enterEvent(self, event) -> None:
        self._hovered = True
        self.update()

    def leaveEvent(self, event) -> None:
        self._hovered = False
        self.update()

    def paintEvent(self, event) -> None:
        super().paintEvent(event)
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)

        if self._selected:
            color = _BORDER_SELECTED
            width = _BORDER_WIDTH_SELECTED
        elif self._hovered:
            color = _BORDER_HOVER
            width = 2
        else:
            color = _BORDER_NORMAL
            width = _BORDER_WIDTH_NORMAL

        pen = QPen(color, width)
        painter.setPen(pen)
        rect = self.rect().adjusted(width // 2, width // 2, -(width // 2), -(width // 2))
        painter.drawRoundedRect(rect, 4, 4)
