"""
扫描 + 提特征 Worker。

在 QThread 中运行扫描和 CLIP 推理，
通过信号向主线程报告进度和结果。
"""
from __future__ import annotations

from PyQt6.QtCore import QThread, pyqtSignal

from app.core.embedder import Embedder
from app.core import scanner
from app.models.image_record import ImageRecord


class ScanWorker(QThread):
    # ── 信号定义 ─────────────────────────────────────────────────────────────────
    file_found = pyqtSignal(int)
    embed_progress = pyqtSignal(int, int)
    stage_changed = pyqtSignal(str)
    scan_complete = pyqtSignal(list)
    error_occurred = pyqtSignal(str)

    def __init__(
        self,
        dirs: list[str],
        embedder: Embedder,          # 由主线程创建并传入，模型常驻
        *,
        recursive: bool = True,
        include_video: bool = False,
        min_size_kb: int = 50,
        parent=None,
    ) -> None:
        super().__init__(parent)
        self._dirs = dirs
        self._embedder = embedder
        self._recursive = recursive
        self._include_video = include_video
        self._min_size_kb = min_size_kb

    def run(self) -> None:
        try:
            # ── 阶段 1：扫描文件 ────────────────────────────────────────────────
            self.stage_changed.emit("正在扫描文件...")
            file_infos = []
            for info in scanner.scan(
                self._dirs,
                recursive=self._recursive,
                include_video=self._include_video,
                min_size_kb=self._min_size_kb,
            ):
                if self.isInterruptionRequested():
                    return
                file_infos.append(info)
                self.file_found.emit(len(file_infos))

            if not file_infos:
                self.scan_complete.emit([])
                return

            # ── 阶段 2：提取 CLIP 特征 ──────────────────────────────────────────
            self.stage_changed.emit("正在提取图像特征...")

            def on_progress(done: int, total: int) -> None:
                self.embed_progress.emit(done, total)

            def is_interrupted() -> bool:
                return self.isInterruptionRequested()

            records: list[ImageRecord] = self._embedder.process(
                file_infos,
                progress_callback=on_progress,
                interrupt_check=is_interrupted,
            )

            if self.isInterruptionRequested():
                return

            self.scan_complete.emit(records)

        except Exception as e:
            import traceback
            self.error_occurred.emit(f"{e}\n{traceback.format_exc()}")
