"""Image preview overlay shown above the grid panel."""
from __future__ import annotations

from PyQt6.QtCore import QObject, QRunnable, QThreadPool, Qt, pyqtSignal
from PyQt6.QtGui import QImage, QKeyEvent, QPixmap
from PyQt6.QtWidgets import (
    QHBoxLayout,
    QLabel,
    QPushButton,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from app.models.action import ActionType
from app.models.image_record import ImageRecord


class _ImageLoader(QRunnable):
    class Signals(QObject):
        loaded = pyqtSignal(str, QImage)

    def __init__(self, path: str) -> None:
        super().__init__()
        self.path = path
        self.signals = _ImageLoader.Signals()
        self.cancelled = False

    def run(self) -> None:
        if self.cancelled:
            return

        from PIL import Image

        try:
            img = Image.open(self.path)
            img.load()
            img = img.convert("RGB")
            img.thumbnail((2400, 2400))
            data = img.tobytes("raw", "RGB")
            image = QImage(
                data,
                img.width,
                img.height,
                img.width * 3,
                QImage.Format.Format_RGB888,
            ).copy()
        except Exception:
            image = QImage()

        if not self.cancelled:
            self.signals.loaded.emit(self.path, image)


class PreviewOverlay(QWidget):
    action_requested = pyqtSignal(object, object)  # (ActionType, ImageRecord)
    closed = pyqtSignal()

    def __init__(self, parent: QWidget) -> None:
        super().__init__(parent)
        self._records: list[ImageRecord] = []
        self._index = 0
        self._current_loader: _ImageLoader | None = None

        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self.setStyleSheet("background: rgba(0, 0, 0, 200);")
        self.hide()
        self._build_ui()

    def _build_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        top_bar = QWidget()
        top_layout = QHBoxLayout(top_bar)
        top_layout.setContentsMargins(8, 8, 8, 4)
        top_layout.addStretch()

        close_btn = QPushButton("x")
        close_btn.setFixedSize(32, 32)
        close_btn.setStyleSheet(
            "QPushButton { background: #444; color: white; border-radius: 16px; font-size: 14px; }"
            "QPushButton:hover { background: #666; }"
        )
        close_btn.clicked.connect(self.hide_overlay)
        top_layout.addWidget(close_btn)
        root.addWidget(top_bar)

        center = QWidget()
        center_layout = QHBoxLayout(center)
        center_layout.setContentsMargins(12, 0, 12, 0)
        center_layout.setSpacing(8)

        self._prev_btn = self._nav_button("<")
        self._prev_btn.clicked.connect(lambda: self._navigate(-1))
        center_layout.addWidget(self._prev_btn, 0, Qt.AlignmentFlag.AlignVCenter)

        self._image_label = QLabel()
        self._image_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._image_label.setSizePolicy(
            QSizePolicy.Policy.Expanding,
            QSizePolicy.Policy.Expanding,
        )
        self._image_label.setStyleSheet("background: transparent; color: #666;")
        center_layout.addWidget(self._image_label, 1)

        self._next_btn = self._nav_button(">")
        self._next_btn.clicked.connect(lambda: self._navigate(1))
        center_layout.addWidget(self._next_btn, 0, Qt.AlignmentFlag.AlignVCenter)
        root.addWidget(center, 1)

        bottom = QWidget()
        bottom.setFixedHeight(90)
        bottom.setStyleSheet("background: rgba(0, 0, 0, 160);")
        bottom_layout = QVBoxLayout(bottom)
        bottom_layout.setContentsMargins(16, 8, 16, 8)
        bottom_layout.setSpacing(6)

        self._meta_label = QLabel()
        self._meta_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._meta_label.setStyleSheet("color: #ccc; font-size: 12px;")
        bottom_layout.addWidget(self._meta_label)

        action_row = QHBoxLayout()
        action_row.setSpacing(8)
        action_row.addStretch()

        self._del_btn = self._action_button("删除", "#c0392b")
        self._del_btn.clicked.connect(lambda: self._emit_action(ActionType.DELETE))
        action_row.addWidget(self._del_btn)

        self._move_btn = self._action_button("移动", "#2980b9")
        self._move_btn.clicked.connect(lambda: self._emit_action(ActionType.MOVE))
        action_row.addWidget(self._move_btn)

        self._review_btn = self._action_button("待复查", "#8e44ad")
        self._review_btn.clicked.connect(lambda: self._emit_action(ActionType.REVIEW))
        action_row.addWidget(self._review_btn)

        action_row.addStretch()
        bottom_layout.addLayout(action_row)
        root.addWidget(bottom)

    def show_for(self, record: ImageRecord, group_records: list[ImageRecord]) -> None:
        self._records = list(group_records)
        try:
            self._index = self._records.index(record)
        except ValueError:
            self._index = 0

        self.setGeometry(self.parent().rect())
        self.raise_()
        self.show()
        self.setFocus()
        self._display_current()

    def hide_overlay(self) -> None:
        if self._current_loader is not None:
            self._current_loader.cancelled = True
        self.hide()
        self.closed.emit()

    def _display_current(self) -> None:
        if not self._records:
            return

        record = self._records[self._index]
        self._image_label.clear()
        self._image_label.setText("加载中...")
        self._update_meta(record)
        self._update_nav_buttons()

        if self._current_loader is not None:
            self._current_loader.cancelled = True

        loader = _ImageLoader(record.path)
        loader.signals.loaded.connect(self._on_image_loaded)
        self._current_loader = loader
        QThreadPool.globalInstance().start(loader)

    def _on_image_loaded(self, path: str, image: QImage) -> None:
        if not self._records or path != self._records[self._index].path:
            return

        pixmap = QPixmap.fromImage(image)
        if pixmap.isNull():
            self._image_label.setText("无法加载图片")
            return

        available = self._image_label.size()
        scaled = pixmap.scaled(
            available,
            Qt.AspectRatioMode.KeepAspectRatio,
            Qt.TransformationMode.SmoothTransformation,
        )
        self._image_label.setText("")
        self._image_label.setPixmap(scaled)

    def _update_meta(self, record: ImageRecord) -> None:
        parts = [record.display_name()]
        if record.exif_datetime:
            parts.append(record.exif_datetime[:10])
        parts.append(f"{record.size_mb()} MB")
        if record.width and record.height:
            parts.append(f"{record.width}x{record.height}")
        if record.sharpness is not None:
            parts.append(f"清晰度 {record.sharpness:.0f}")
        parts.append(f"[{self._index + 1}/{len(self._records)}]")
        self._meta_label.setText(" | ".join(parts))

    def _update_nav_buttons(self) -> None:
        enabled = len(self._records) > 1
        self._prev_btn.setEnabled(enabled)
        self._next_btn.setEnabled(enabled)

    def _navigate(self, delta: int) -> None:
        if not self._records:
            return
        self._index = (self._index + delta) % len(self._records)
        self._display_current()

    def _emit_action(self, action_type: ActionType) -> None:
        if self._records:
            self.action_requested.emit(action_type, self._records[self._index])

    def keyPressEvent(self, event: QKeyEvent) -> None:
        key = event.key()
        if key == Qt.Key.Key_Escape:
            self.hide_overlay()
        elif key == Qt.Key.Key_Left:
            self._navigate(-1)
        elif key == Qt.Key.Key_Right:
            self._navigate(1)
        elif key == Qt.Key.Key_Delete:
            self._emit_action(ActionType.DELETE)
        else:
            super().keyPressEvent(event)

    def mousePressEvent(self, event) -> None:
        child = self.childAt(event.pos())
        if child is None or child is self:
            self.hide_overlay()
        else:
            super().mousePressEvent(event)

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        if self.isVisible() and self._records:
            self._display_current()

    @staticmethod
    def _nav_button(text: str) -> QPushButton:
        btn = QPushButton(text)
        btn.setFixedSize(40, 80)
        btn.setStyleSheet(
            "QPushButton { background: rgba(255, 255, 255, 30); color: white; "
            "border-radius: 8px; font-size: 18px; }"
            "QPushButton:hover { background: rgba(255, 255, 255, 60); }"
            "QPushButton:disabled { color: #444; }"
        )
        return btn

    @staticmethod
    def _action_button(text: str, color: str) -> QPushButton:
        btn = QPushButton(text)
        btn.setFixedHeight(30)
        btn.setStyleSheet(
            f"QPushButton {{ background: {color}; color: white; border-radius: 6px; "
            f"padding: 0 14px; font-size: 12px; }}"
            f"QPushButton:hover {{ background: {color}cc; }}"
        )
        return btn
