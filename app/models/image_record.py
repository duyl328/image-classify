"""
ImageRecord：贯穿整个系统的核心数据结构。

从扫描到聚类到 UI 显示，所有层共享同一个对象引用。
cluster_id 在聚类后原地修改，不重建对象。
"""
from __future__ import annotations

from dataclasses import dataclass, field
import numpy as np


@dataclass
class ImageRecord:
    # ── 文件标识 ──────────────────────────────────────────────────────────────
    cache_key: str          # "{abs_path}|{mtime}|{filesize}"，SQLite 主键
    path: str               # 绝对路径

    # ── 文件元数据（来自 os.stat，不读取文件内容）────────────────────────────
    mtime: float            # 修改时间戳（秒）
    filesize: int           # 字节数

    # ── ML 特征（提特征后填入）──────────────────────────────────────────────
    embedding: np.ndarray | None = None   # shape (512,), float32；None 表示未提取或失败
    phash: str | None = None              # imagehash.phash 的十六进制字符串
    sharpness: float | None = None        # Laplacian 方差，越大越清晰

    # ── 聚类结果（聚类后原地修改）──────────────────────────────────────────
    cluster_id: int = -1    # -1 = 噪声（HDBSCAN 未分配），归入"未分类"组

    # ── 懒加载字段（首次在 UI 中显示时填入）────────────────────────────────
    width: int | None = None
    height: int | None = None
    exif_datetime: str | None = None      # 格式 "YYYY:MM:DD HH:MM:SS"

    def is_embedded(self) -> bool:
        """是否已成功提取 CLIP 特征。"""
        return self.embedding is not None

    def display_name(self) -> str:
        """用于 UI 显示的文件名（不含路径）。"""
        import os
        return os.path.basename(self.path)

    def size_mb(self) -> float:
        """文件大小（MB），保留一位小数。"""
        return round(self.filesize / (1024 * 1024), 1)
