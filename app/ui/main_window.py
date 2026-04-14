"""
主窗口 — 三阶段状态机 + 所有信号/槽连接。

阶段：
  LAUNCH(0)    → 目录选择页
  ANALYZING(1) → 分析进度页
  WORKING(2)   → 三栏工作区
"""
from __future__ import annotations

from enum import Enum, auto

from PyQt6.QtCore import Qt, QThread
from PyQt6.QtWidgets import (
    QCheckBox, QFileDialog, QHBoxLayout, QLabel,
    QListWidget, QListWidgetItem, QMainWindow,
    QMessageBox, QProgressBar, QPushButton,
    QSplitter, QStackedWidget, QStatusBar,
    QToolBar, QVBoxLayout, QWidget,
)

from app.config import DB_PATH, SLIDER_DEFAULT
from app.core.action_queue import ActionQueue
from app.core.cache import Cache
from app.core.clusterer import Clusterer
from app.core.debug_log import log_debug
from app.core.deduplicator import find_duplicates
from app.core.embedder import Embedder
from app.models.action import ActionType, StagedAction
from app.models.image_record import ImageRecord
from app.workers.cluster_worker import ClusterWorker
from app.workers.scan_worker import ScanWorker
from app.ui.panels.group_panel import GroupPanel, CLUSTER_ID_DUPLICATES
from app.ui.panels.grid_panel import GridPanel
from app.ui.panels.action_panel import ActionPanel
from app.ui.widgets.granularity_slider import GranularitySlider
from app.ui.widgets.preview_overlay import PreviewOverlay


class AppState(Enum):
    LAUNCH = auto()
    ANALYZING = auto()
    WORKING = auto()


class MainWindow(QMainWindow):
    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle("照片整理工具")
        self.resize(1280, 800)
        self.setStyleSheet("background: #1a1a1a; color: #ddd;")

        # ── 核心状态 ─────────────────────────────────────────────────────────────
        self._cache = Cache(DB_PATH)
        self._clusterer = Clusterer()
        self._action_queue = ActionQueue()
        # Embedder 在主线程创建，模型常驻内存，避免 QThread 退出时 CUDA context 崩溃
        self._embedder = Embedder(self._cache)
        self._records: list[ImageRecord] = []
        self._groups: dict[int, list[ImageRecord]] = {}
        self._dup_groups: list[list[ImageRecord]] = []
        self._current_cluster_id: int | None = None
        self._scan_worker: ScanWorker | None = None
        self._cluster_worker: ClusterWorker | None = None
        self._selected_dirs: list[str] = []

        # ── UI 搭建 ──────────────────────────────────────────────────────────────
        self._stack = QStackedWidget()
        self.setCentralWidget(self._stack)

        self._stack.addWidget(self._build_launch_page())    # index 0
        self._stack.addWidget(self._build_analysis_page())  # index 1
        self._stack.addWidget(self._build_work_page())      # index 2

        self._stack.setCurrentIndex(0)
        self._set_state(AppState.LAUNCH)

    # ══════════════════════════════════════════════════════════════════════════════
    # 页面构建
    # ══════════════════════════════════════════════════════════════════════════════

    def _build_launch_page(self) -> QWidget:
        page = QWidget()
        page.setStyleSheet("background: #1a1a1a;")
        layout = QVBoxLayout(page)
        layout.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.setSpacing(20)

        title = QLabel("📷 照片整理工具")
        title.setStyleSheet("font-size: 28px; font-weight: bold; color: #eee;")
        title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(title)

        sub = QLabel("选择目录后自动分析并按视觉内容分组")
        sub.setStyleSheet("font-size: 13px; color: #888;")
        sub.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(sub)

        # 目录列表
        self._dir_list = QListWidget()
        self._dir_list.setMaximumWidth(600)
        self._dir_list.setMaximumHeight(160)
        self._dir_list.setStyleSheet(
            "QListWidget { background: #252525; border: 1px solid #3a3a3a; "
            "border-radius: 6px; color: #ccc; }"
        )
        layout.addWidget(self._dir_list, 0, Qt.AlignmentFlag.AlignCenter)

        btn_row = QHBoxLayout()
        btn_row.setSpacing(10)

        add_dir_btn = QPushButton("➕ 添加目录")
        add_dir_btn.setFixedSize(130, 34)
        add_dir_btn.setStyleSheet(self._btn_style("#2980b9"))
        add_dir_btn.clicked.connect(self._add_directory)
        btn_row.addWidget(add_dir_btn)

        remove_dir_btn = QPushButton("➖ 移除选中")
        remove_dir_btn.setFixedSize(130, 34)
        remove_dir_btn.setStyleSheet(self._btn_style("#555"))
        remove_dir_btn.clicked.connect(self._remove_directory)
        btn_row.addWidget(remove_dir_btn)

        layout.addLayout(btn_row)

        # 选项
        options_row = QHBoxLayout()
        self._recursive_cb = QCheckBox("递归子目录")
        self._recursive_cb.setChecked(True)
        self._video_cb = QCheckBox("包含视频")
        for cb in [self._recursive_cb, self._video_cb]:
            cb.setStyleSheet("color: #aaa;")
            options_row.addWidget(cb)
        layout.addLayout(options_row)

        # 开始按钮
        self._start_btn = QPushButton("🚀 开始分析")
        self._start_btn.setFixedSize(160, 44)
        self._start_btn.setStyleSheet(self._btn_style("#27ae60", font_size=14))
        self._start_btn.setEnabled(False)
        self._start_btn.clicked.connect(self._on_start_analysis)
        layout.addWidget(self._start_btn, 0, Qt.AlignmentFlag.AlignCenter)

        return page

    def _build_analysis_page(self) -> QWidget:
        page = QWidget()
        page.setStyleSheet("background: #1a1a1a;")
        layout = QVBoxLayout(page)
        layout.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.setSpacing(18)

        self._analysis_title = QLabel("正在分析...")
        self._analysis_title.setStyleSheet("font-size: 18px; color: #eee;")
        self._analysis_title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(self._analysis_title)

        # 步骤状态
        self._step1_label = QLabel("① 扫描文件       ⏳")
        self._step2_label = QLabel("② 提取特征       等待中")
        self._step3_label = QLabel("③ 自动分组       等待中")
        for lbl in [self._step1_label, self._step2_label, self._step3_label]:
            lbl.setStyleSheet("font-size: 13px; color: #bbb;")
            lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
            layout.addWidget(lbl)

        self._progress_bar = QProgressBar()
        self._progress_bar.setMaximumWidth(460)
        self._progress_bar.setFixedHeight(16)
        self._progress_bar.setRange(0, 100)
        self._progress_bar.setValue(0)
        self._progress_bar.setStyleSheet("""
            QProgressBar { border-radius: 8px; background: #2a2a2a; text-align: center; color: #aaa; }
            QProgressBar::chunk { background: #2980b9; border-radius: 8px; }
        """)
        layout.addWidget(self._progress_bar, 0, Qt.AlignmentFlag.AlignCenter)

        self._progress_label = QLabel("")
        self._progress_label.setStyleSheet("color: #777; font-size: 11px;")
        self._progress_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(self._progress_label)

        cancel_btn = QPushButton("取消")
        cancel_btn.setFixedSize(100, 32)
        cancel_btn.setStyleSheet(self._btn_style("#555"))
        cancel_btn.clicked.connect(self._on_cancel_analysis)
        layout.addWidget(cancel_btn, 0, Qt.AlignmentFlag.AlignCenter)

        return page

    def _build_work_page(self) -> QWidget:
        page = QWidget()
        page.setStyleSheet("background: #1a1a1a;")
        outer = QVBoxLayout(page)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)

        # ── 工具栏 ──────────────────────────────────────────────────────────────
        toolbar = QWidget()
        toolbar.setFixedHeight(44)
        toolbar.setStyleSheet("background: #111; border-bottom: 1px solid #2a2a2a;")
        tb_layout = QHBoxLayout(toolbar)
        tb_layout.setContentsMargins(10, 0, 10, 0)
        tb_layout.setSpacing(12)

        self._granularity_slider = GranularitySlider()
        self._granularity_slider.granularity_changed.connect(self._on_granularity_changed)
        tb_layout.addWidget(self._granularity_slider)

        tb_layout.addStretch()

        self._total_label = QLabel("")
        self._total_label.setStyleSheet("color: #888; font-size: 12px;")
        tb_layout.addWidget(self._total_label)

        reselect_btn = QPushButton("重新选择目录")
        reselect_btn.setFixedHeight(28)
        reselect_btn.setStyleSheet(self._btn_style("#555", font_size=11))
        reselect_btn.clicked.connect(lambda: self._set_state(AppState.LAUNCH))
        tb_layout.addWidget(reselect_btn)

        outer.addWidget(toolbar)

        # ── 三栏布局 ────────────────────────────────────────────────────────────
        splitter = QSplitter(Qt.Orientation.Horizontal)
        splitter.setHandleWidth(1)
        splitter.setStyleSheet("QSplitter::handle { background: #2a2a2a; }")

        # 左：分组列表
        self._group_panel = GroupPanel()
        self._group_panel.setMinimumWidth(200)
        self._group_panel.setMaximumWidth(300)
        self._group_panel.group_selected.connect(self._on_group_selected)
        splitter.addWidget(self._group_panel)

        # 中：缩略图网格
        self._grid_panel = GridPanel()
        self._grid_panel.thumbnail_clicked.connect(self._on_thumbnail_clicked)
        self._grid_panel.selection_changed.connect(self._on_selection_changed)
        splitter.addWidget(self._grid_panel)

        # 右：操作面板
        self._action_panel = ActionPanel()
        self._action_panel.action_requested.connect(self._on_action_requested)
        self._action_panel.execute_requested.connect(self._on_execute_all)
        splitter.addWidget(self._action_panel)

        splitter.setSizes([220, 820, 220])
        outer.addWidget(splitter, 1)

        # 预览浮层（覆盖 GridPanel）
        self._preview_overlay = PreviewOverlay(self._grid_panel)
        self._preview_overlay.action_requested.connect(self._on_preview_action)
        self._grid_panel.resizeEvent = self._grid_resize_event

        return page

    # ══════════════════════════════════════════════════════════════════════════════
    # 状态切换
    # ══════════════════════════════════════════════════════════════════════════════

    def _set_state(self, state: AppState) -> None:
        self._stack.setCurrentIndex(state.value - 1)

    # ══════════════════════════════════════════════════════════════════════════════
    # Launch 页槽
    # ══════════════════════════════════════════════════════════════════════════════

    def _add_directory(self) -> None:
        d = QFileDialog.getExistingDirectory(self, "选择照片目录")
        if d and d not in self._selected_dirs:
            self._selected_dirs.append(d)
            self._dir_list.addItem(d)
            self._start_btn.setEnabled(True)

    def _remove_directory(self) -> None:
        row = self._dir_list.currentRow()
        if row >= 0:
            self._dir_list.takeItem(row)
            del self._selected_dirs[row]
            self._start_btn.setEnabled(bool(self._selected_dirs))

    # ══════════════════════════════════════════════════════════════════════════════
    # 分析流程
    # ══════════════════════════════════════════════════════════════════════════════

    def _on_start_analysis(self) -> None:
        if not self._selected_dirs:
            return

        # 重置分析页
        self._step1_label.setText("① 扫描文件       ⏳")
        self._step2_label.setText("② 提取特征       等待中")
        self._step3_label.setText("③ 自动分组       等待中")
        self._progress_bar.setValue(0)
        self._progress_label.setText("")
        self._set_state(AppState.ANALYZING)

        worker = ScanWorker(
            self._selected_dirs,
            self._embedder,
            recursive=self._recursive_cb.isChecked(),
            include_video=self._video_cb.isChecked(),
            parent=self,
        )
        worker.file_found.connect(self._on_file_found)
        worker.embed_progress.connect(self._on_embed_progress)
        worker.stage_changed.connect(self._on_stage_changed)
        worker.scan_complete.connect(self._on_scan_complete)
        worker.error_occurred.connect(self._on_worker_error)
        self._scan_worker = worker
        worker.start()

    def _on_cancel_analysis(self) -> None:
        if self._scan_worker and self._scan_worker.isRunning():
            self._scan_worker.requestInterruption()
            self._scan_worker.wait(2000)
        if self._cluster_worker and self._cluster_worker.isRunning():
            self._cluster_worker.requestInterruption()
            self._cluster_worker.wait(2000)
        self._set_state(AppState.LAUNCH)

    def _on_file_found(self, count: int) -> None:
        self._step1_label.setText(f"① 扫描文件       已发现 {count} 张")

    def _on_stage_changed(self, stage: str) -> None:
        if "特征" in stage:
            self._step1_label.setText(
                self._step1_label.text().replace("⏳", "✅")
            )
            self._step2_label.setText(f"② 提取特征       ⏳ {stage}")
        elif "分组" in stage or "UMAP" in stage or "降维" in stage:
            self._step3_label.setText(f"③ 自动分组       ⏳ {stage}")

    def _on_embed_progress(self, done: int, total: int) -> None:
        pct = int(done / total * 100) if total > 0 else 0
        self._progress_bar.setValue(pct)
        self._progress_label.setText(f"{done} / {total} 张")
        if done >= total:
            self._step2_label.setText("② 提取特征       ✅ 完成")

    def _on_scan_complete(self, records: list[ImageRecord]) -> None:
        self._records = records
        self._progress_bar.setRange(0, 0)  # 不定进度（UMAP 阶段）
        self._step3_label.setText("③ 自动分组       ⏳ 正在降维...")

        min_cs = self._granularity_slider.current_cluster_size()
        worker = ClusterWorker(
            records, self._clusterer, min_cs, reuse_reduced=False, parent=self
        )
        worker.stage_changed.connect(self._on_cluster_stage)
        worker.cluster_complete.connect(self._on_cluster_complete)
        worker.error_occurred.connect(self._on_worker_error)
        self._cluster_worker = worker
        worker.start()

    def _on_cluster_stage(self, stage: str) -> None:
        self._step3_label.setText(f"③ 自动分组       ⏳ {stage}")

    def _on_cluster_complete(self, records: list, groups: dict) -> None:
        self._records = records
        self._groups = groups
        self._progress_bar.setRange(0, 100)
        self._progress_bar.setValue(100)
        self._step3_label.setText(
            f"③ 自动分组       ✅ {len(groups)} 组"
        )

        # 近重复检测
        self._dup_groups = find_duplicates(records)

        # 切换到工作区
        n_clusters = len([k for k in groups if k != -1])
        self._total_label.setText(
            f"共 {n_clusters} 组 · {len(records)} 张"
            + (f" · 近重复 {len(self._dup_groups)} 对" if self._dup_groups else "")
        )
        self._group_panel.populate(groups, self._dup_groups)
        self._granularity_slider.set_enabled(True)
        self._set_state(AppState.WORKING)

    # ══════════════════════════════════════════════════════════════════════════════
    # 工作区槽
    # ══════════════════════════════════════════════════════════════════════════════

    def _on_group_selected(self, cluster_id: int) -> None:
        self._current_cluster_id = cluster_id
        if cluster_id == CLUSTER_ID_DUPLICATES:
            # 近重复组：展开所有近重复记录
            recs: list[ImageRecord] = []
            for g in self._dup_groups:
                recs.extend(g)
        else:
            recs = self._groups.get(cluster_id, [])
        self._grid_panel.load_group(recs)
        self._action_panel.set_current_group(recs)

    def _on_granularity_changed(self, min_cluster_size: int) -> None:
        # 停止旧 worker
        if self._cluster_worker and self._cluster_worker.isRunning():
            self._cluster_worker.requestInterruption()
            self._cluster_worker.wait(500)

        self._granularity_slider.set_enabled(False)
        self._total_label.setText("重新分组中...")

        worker = ClusterWorker(
            self._records,
            self._clusterer,
            min_cluster_size,
            reuse_reduced=True,
            parent=self,
        )
        worker.cluster_complete.connect(self._on_cluster_complete)
        worker.error_occurred.connect(self._on_worker_error)
        self._cluster_worker = worker
        worker.start()

    def _on_thumbnail_clicked(self, record: ImageRecord, group_records: list) -> None:
        self._preview_overlay.show_for(record, group_records)

    def _on_selection_changed(self, records: list[ImageRecord]) -> None:
        self._action_panel.update_selection(records)

    def _on_preview_action(self, action_type: ActionType, record: ImageRecord) -> None:
        self._on_action_requested(action_type, [record], None)

    def _on_action_requested(
        self,
        action_type: ActionType,
        records: list[ImageRecord],
        target_dir: str | None,
    ) -> None:
        action = StagedAction(
            action_type=action_type,
            image_paths=[r.path for r in records],
            target_dir=target_dir,
        )
        self._action_queue.add(action)
        self._action_panel.update_queue_summary(self._action_queue.get_summary())

    def _on_execute_all(self) -> None:
        from app.ui.dialogs.confirm_dialog import ConfirmDialog
        dlg = ConfirmDialog(self._action_queue, parent=self)
        if dlg.exec() != dlg.DialogCode.Accepted:
            return

        # 在后台线程执行文件操作
        class ExecWorker(QThread):
            def __init__(self_, queue, cb):
                super().__init__()
                self_._queue = queue
                self_._cb = cb
                self_.result = None
            def run(self_):
                self_.result = self_._queue.execute(self_._cb)

        def on_done():
            result = exec_worker.result
            self._action_queue.clear()
            self._action_panel.update_queue_summary(self._action_queue.get_summary())
            self._remove_executed_records(result.succeeded)
            msg = f"完成：{len(result.succeeded)} 张处理成功"
            if result.failed:
                msg += f"，{len(result.failed)} 张失败"
            self.statusBar().showMessage(msg, 5000)

        exec_worker = ExecWorker(self._action_queue, None)
        exec_worker.finished.connect(on_done)
        exec_worker.start()
        self._exec_worker = exec_worker  # 防止 GC

    def _remove_executed_records(self, succeeded_paths: list[str]) -> None:
        path_set = set(succeeded_paths)
        self._records = [r for r in self._records if r.path not in path_set]
        self._groups = Clusterer.build_groups(self._records)
        self._dup_groups = find_duplicates(self._records)
        self._group_panel.populate(self._groups, self._dup_groups)
        if self._current_cluster_id is not None:
            self._on_group_selected(self._current_cluster_id)

    def _on_worker_error(self, msg: str) -> None:
        QMessageBox.critical(self, "出错了", msg)
        self._set_state(AppState.LAUNCH)

    # ══════════════════════════════════════════════════════════════════════════════
    # 预览浮层
    # ══════════════════════════════════════════════════════════════════════════════

    def _grid_resize_event(self, event) -> None:
        """GridPanel resize 时同步更新浮层尺寸。"""
        GridPanel.resizeEvent(self._grid_panel, event)
        if self._preview_overlay.isVisible():
            self._preview_overlay.setGeometry(self._grid_panel.rect())

    # ══════════════════════════════════════════════════════════════════════════════
    # 生命周期
    # ══════════════════════════════════════════════════════════════════════════════

    def closeEvent(self, event) -> None:
        for worker in [self._scan_worker, self._cluster_worker]:
            if worker and worker.isRunning():
                worker.requestInterruption()
                worker.wait(1000)
        self._cache.close()
        super().closeEvent(event)

    # ══════════════════════════════════════════════════════════════════════════════
    # 工具方法
    # ══════════════════════════════════════════════════════════════════════════════

    def _on_scan_complete(self, records: list[ImageRecord]) -> None:
        log_debug("main_window_on_scan_complete", record_count=len(records))
        self._records = records
        self._progress_bar.setRange(0, 0)
        self._step3_label.setText("自动分组：准备降维...")

        min_cluster_size = self._granularity_slider.current_cluster_size()
        log_debug("main_window_cluster_worker_start", min_cluster_size=min_cluster_size)
        worker = ClusterWorker(
            records,
            self._clusterer,
            min_cluster_size,
            reuse_reduced=False,
            parent=self,
        )
        worker.stage_changed.connect(self._on_cluster_stage)
        worker.cluster_complete.connect(self._on_cluster_complete)
        worker.error_occurred.connect(self._on_worker_error)
        self._cluster_worker = worker
        worker.start()
        log_debug("main_window_cluster_worker_started")

    def _on_cluster_complete(self, records: list, groups: dict) -> None:
        log_debug(
            "main_window_on_cluster_complete_enter",
            record_count=len(records),
            group_count=len(groups),
        )
        self._records = records
        self._groups = groups
        self._progress_bar.setRange(0, 100)
        self._progress_bar.setValue(100)
        self._step3_label.setText(f"自动分组完成：{len(groups)} 组")
        log_debug("main_window_on_cluster_complete_progress_updated")

        log_debug("main_window_find_duplicates_start")
        self._dup_groups = find_duplicates(records)
        log_debug("main_window_find_duplicates_done", duplicate_group_count=len(self._dup_groups))

        cluster_count = len([cluster_id for cluster_id in groups if cluster_id != -1])
        summary = f"共 {cluster_count} 组 | {len(records)} 张"
        if self._dup_groups:
            summary += f" | 近重复 {len(self._dup_groups)} 组"
        self._total_label.setText(summary)
        log_debug("main_window_summary_updated", summary=summary)

        log_debug("main_window_group_panel_populate_start")
        self._group_panel.populate(groups, self._dup_groups)
        log_debug("main_window_group_panel_populate_done")

        self._granularity_slider.set_enabled(True)
        log_debug("main_window_granularity_enabled")
        self._set_state(AppState.WORKING)
        log_debug("main_window_state_set_working")

    def _on_group_selected(self, cluster_id: int) -> None:
        log_debug("main_window_on_group_selected_enter", cluster_id=cluster_id)
        self._current_cluster_id = cluster_id
        if cluster_id == CLUSTER_ID_DUPLICATES:
            records: list[ImageRecord] = []
            for group in self._dup_groups:
                records.extend(group)
        else:
            records = self._groups.get(cluster_id, [])
        log_debug("main_window_on_group_selected_records_ready", cluster_id=cluster_id, record_count=len(records))
        self._grid_panel.load_group(records)
        log_debug("main_window_on_group_selected_grid_loaded", cluster_id=cluster_id)
        self._action_panel.set_current_group(records)
        log_debug("main_window_on_group_selected_action_panel_updated", cluster_id=cluster_id)

    def _on_worker_error(self, msg: str) -> None:
        log_debug("main_window_worker_error", message=msg)
        QMessageBox.critical(self, "出错了", msg)
        self._set_state(AppState.LAUNCH)
        log_debug("main_window_worker_error_dialog_closed")

    def closeEvent(self, event) -> None:
        log_debug("main_window_close_event_start")
        for worker in [self._scan_worker, self._cluster_worker]:
            if worker and worker.isRunning():
                log_debug("main_window_close_event_wait_worker", worker_type=type(worker).__name__)
                worker.requestInterruption()
                worker.wait(1000)
        self._cache.close()
        log_debug("main_window_close_event_cache_closed")
        super().closeEvent(event)
        log_debug("main_window_close_event_done")

    @staticmethod
    def _btn_style(color: str, font_size: int = 12) -> str:
        return (
            f"QPushButton {{ background: {color}; color: white; border-radius: 5px; "
            f"font-size: {font_size}px; }}"
            f"QPushButton:hover {{ background: {color}cc; }}"
            f"QPushButton:disabled {{ background: #333; color: #666; }}"
        )
