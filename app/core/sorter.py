"""
组内图片排序。

纯函数，不修改原列表，不做 IO。
"""
from __future__ import annotations

import numpy as np

from app.models.image_record import ImageRecord


def sort_by_time(records: list[ImageRecord]) -> list[ImageRecord]:
    """
    按拍摄时间升序。
    优先 exif_datetime（字符串 "YYYY:MM:DD HH:MM:SS"），
    缺失时退回 mtime。
    """
    def key(r: ImageRecord):
        if r.exif_datetime:
            return (0, r.exif_datetime)
        return (1, str(r.mtime))

    return sorted(records, key=key)


def sort_by_sharpness(records: list[ImageRecord]) -> list[ImageRecord]:
    """按清晰度降序，sharpness=None 的排最后。"""
    return sorted(
        records,
        key=lambda r: (r.sharpness is None, -(r.sharpness or 0.0)),
    )


def sort_by_similarity(
    records: list[ImageRecord],
    anchor: ImageRecord | None = None,
) -> list[ImageRecord]:
    """
    按与锚点图片的余弦相似度降序。
    anchor=None 时自动选组内最"中心"的图片（与其他图平均相似度最高）。
    没有 embedding 的图片排最后。
    """
    embedded = [r for r in records if r.is_embedded()]
    no_emb = [r for r in records if not r.is_embedded()]

    if not embedded:
        return records

    matrix = np.stack([r.embedding for r in embedded]).astype(np.float32)
    # L2 归一化（embedding 应该已经归一化，但防御性处理）
    norms = np.linalg.norm(matrix, axis=1, keepdims=True)
    norms = np.where(norms == 0, 1.0, norms)
    matrix = matrix / norms

    if anchor is None or not anchor.is_embedded():
        # 选平均相似度最高的图作为锚点
        sim_matrix = matrix @ matrix.T
        mean_sim = sim_matrix.mean(axis=1)
        anchor_idx = int(np.argmax(mean_sim))
        anchor_vec = matrix[anchor_idx]
    else:
        anchor_vec = anchor.embedding.astype(np.float32)
        anchor_vec = anchor_vec / (np.linalg.norm(anchor_vec) or 1.0)

    similarities = matrix @ anchor_vec
    sorted_indices = np.argsort(-similarities)

    return [embedded[i] for i in sorted_indices] + no_emb
