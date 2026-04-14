"""Clustering pipeline based on PCA + HDBSCAN."""
from __future__ import annotations

import numpy as np

from app.config import HDBSCAN_MIN_SAMPLES, PCA_N_COMPONENTS, PCA_SKIP_THRESHOLD
from app.models.image_record import ImageRecord


class Clusterer:
    def __init__(self) -> None:
        self.reduced_matrix: np.ndarray | None = None

    def run_pca(self, records: list[ImageRecord]) -> np.ndarray:
        """Reduce normalized embeddings and cache the result for reclustering."""
        matrix = self._build_matrix(records)
        sample_count = len(records)

        if sample_count <= PCA_SKIP_THRESHOLD:
            print(f"[clusterer] skipping PCA for {sample_count} samples")
            self.reduced_matrix = matrix
            return matrix

        from sklearn.decomposition import PCA

        component_count = min(PCA_N_COMPONENTS, sample_count - 1)
        print(f"[clusterer] PCA: {matrix.shape} -> (N, {component_count})")
        reduced = PCA(n_components=component_count, random_state=42).fit_transform(matrix)
        self.reduced_matrix = reduced.astype(np.float32)
        print(f"[clusterer] PCA done: {self.reduced_matrix.shape}")
        return self.reduced_matrix

    def run_hdbscan(
        self,
        records: list[ImageRecord],
        reduced: np.ndarray,
        min_cluster_size: int,
    ) -> list[ImageRecord]:
        """Cluster the reduced vectors and write labels back into the records."""
        from sklearn.cluster import HDBSCAN

        sample_count = len(records)
        if sample_count <= 1:
            for record in records:
                record.cluster_id = 0 if sample_count == 1 else -1
            return records

        effective_min_cluster_size = max(2, min(min_cluster_size, sample_count))
        effective_min_samples = max(1, min(HDBSCAN_MIN_SAMPLES, effective_min_cluster_size))

        print(
            "[clusterer] HDBSCAN: "
            f"min_cluster_size={effective_min_cluster_size}, N={sample_count}"
        )
        labels = HDBSCAN(
            min_cluster_size=effective_min_cluster_size,
            min_samples=effective_min_samples,
            metric="euclidean",
            n_jobs=1,
            copy=True,
        ).fit_predict(reduced)

        for record, label in zip(records, labels):
            record.cluster_id = int(label)

        cluster_count = len(set(labels)) - (1 if -1 in labels else 0)
        noise_count = int(np.sum(labels == -1))
        print(f"[clusterer] result: {cluster_count} clusters, {noise_count} noise samples")
        return records

    def cluster(self, records: list[ImageRecord], min_cluster_size: int) -> list[ImageRecord]:
        embedded_records = [record for record in records if record.is_embedded()]
        if not embedded_records:
            return records
        reduced = self.run_pca(embedded_records)
        return self.run_hdbscan(embedded_records, reduced, min_cluster_size)

    def recluster(self, records: list[ImageRecord], min_cluster_size: int) -> list[ImageRecord]:
        """Reuse the last reduced matrix when only clustering parameters changed."""
        embedded_records = [record for record in records if record.is_embedded()]
        if not embedded_records or self.reduced_matrix is None:
            return self.cluster(records, min_cluster_size)
        return self.run_hdbscan(embedded_records, self.reduced_matrix, min_cluster_size)

    @staticmethod
    def _build_matrix(records: list[ImageRecord]) -> np.ndarray:
        matrix = np.stack([record.embedding for record in records]).astype(np.float32)
        norms = np.linalg.norm(matrix, axis=1, keepdims=True)
        return matrix / np.where(norms == 0, 1.0, norms)

    @staticmethod
    def build_groups(records: list[ImageRecord]) -> dict[int, list[ImageRecord]]:
        groups: dict[int, list[ImageRecord]] = {}
        for record in records:
            groups.setdefault(record.cluster_id, []).append(record)
        return groups
