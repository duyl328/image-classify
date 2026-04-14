"""Background worker for PCA + HDBSCAN clustering."""
from __future__ import annotations

from PyQt6.QtCore import QThread, pyqtSignal

from app.core.clusterer import Clusterer
from app.core.debug_log import log_current_exception, log_debug
from app.models.image_record import ImageRecord


class ClusterWorker(QThread):
    stage_changed = pyqtSignal(str)
    cluster_complete = pyqtSignal(list, dict)
    error_occurred = pyqtSignal(str)

    def __init__(
        self,
        records: list[ImageRecord],
        clusterer: Clusterer,
        min_cluster_size: int,
        *,
        reuse_reduced: bool = False,
        parent=None,
    ) -> None:
        super().__init__(parent)
        self._records = records
        self._clusterer = clusterer
        self._min_cluster_size = min_cluster_size
        self._reuse_reduced = reuse_reduced

    def run(self) -> None:
        try:
            log_debug(
                "cluster_worker_run_start",
                record_count=len(self._records),
                min_cluster_size=self._min_cluster_size,
                reuse_reduced=self._reuse_reduced,
                has_reduced=self._clusterer.reduced_matrix is not None,
            )

            if self._reuse_reduced and self._clusterer.reduced_matrix is not None:
                self.stage_changed.emit("正在重新分组...")
                log_debug("cluster_worker_recluster_only_start")
                records = self._clusterer.recluster(self._records, self._min_cluster_size)
                log_debug("cluster_worker_recluster_only_done")
            else:
                embedded_records = [record for record in self._records if record.is_embedded()]
                self.stage_changed.emit("正在降维（PCA）...")
                log_debug("cluster_worker_pca_start", embedded_count=len(embedded_records))
                self._clusterer.run_pca(embedded_records)
                log_debug("cluster_worker_pca_done")

                if self.isInterruptionRequested():
                    log_debug("cluster_worker_interrupted_after_pca")
                    return

                self.stage_changed.emit("正在自动分组...")
                log_debug("cluster_worker_hdbscan_start")
                records = self._clusterer.recluster(self._records, self._min_cluster_size)
                log_debug("cluster_worker_hdbscan_done")

            if self.isInterruptionRequested():
                log_debug("cluster_worker_interrupted_after_cluster")
                return

            log_debug("cluster_worker_build_groups_start")
            groups = Clusterer.build_groups(records)
            log_debug("cluster_worker_build_groups_done", group_count=len(groups))
            log_debug("cluster_worker_emit_cluster_complete_start")
            self.cluster_complete.emit(records, groups)
            log_debug("cluster_worker_emit_cluster_complete_done")

        except Exception as exc:
            log_current_exception("cluster_worker_exception")
            self.error_occurred.emit(f"{exc}\n")
