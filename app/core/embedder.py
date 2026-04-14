"""
CLIP 特征提取器。

- 懒加载模型（首次调用时加载）
- 优先使用 GPU（自动检测）
- 优先读取本地权重文件，避免网络下载
- 大图用 img.draft() 快速解码（JPEG 快 8-16 倍）
- 批量推理，OOM 时自动减半 batch size
- pHash 和清晰度在同一次图片打开时计算，避免重复 IO
"""
from __future__ import annotations

import os
from collections.abc import Callable
from typing import TYPE_CHECKING

import numpy as np
from PIL import Image, UnidentifiedImageError

from app.config import (
    CLIP_BATCH_SIZE,
    CLIP_LOCAL_WEIGHTS,
    CLIP_MODEL_NAME,
    EMBEDDING_DIM,
)
from app.models.image_record import ImageRecord

if TYPE_CHECKING:
    from app.core.cache import Cache
    from app.core.scanner import FileInfo

# 注册 HEIC 支持（若 pillow-heif 已安装）
try:
    from pillow_heif import register_heif_opener
    register_heif_opener()
except ImportError:
    pass


def _compute_sharpness(img: Image.Image) -> float:
    """Laplacian 方差，纯 numpy 实现，无需 OpenCV。"""
    gray = np.array(img.convert("L"), dtype=np.float32)
    # Laplacian 卷积核
    kernel = np.array([[0, 1, 0], [1, -4, 1], [0, 1, 0]], dtype=np.float32)
    from scipy.ndimage import convolve
    lap = convolve(gray, kernel)
    return float(np.var(lap))


def _open_image(path: str) -> Image.Image | None:
    """
    打开图片，对 JPEG 使用 draft 加速。
    返回 RGB PIL Image 或 None（损坏/不支持）。
    """
    try:
        img = Image.open(path)
        # JPEG draft：只解码到目标分辨率所需的 DCT 系数
        if img.format == "JPEG":
            img.draft("RGB", (512, 512))
        img.load()
        return img.convert("RGB")
    except (UnidentifiedImageError, OSError, Exception):
        return None


class Embedder:
    def __init__(self, cache: Cache, device: str | None = None) -> None:
        self._cache = cache
        self._model = None
        self._preprocess = None
        self._device: str | None = device  # None = 自动检测

    def _load_model(self) -> None:
        """懒加载 CLIP 模型，首次调用时执行（约 3-10 秒）。"""
        if self._model is not None:
            return

        import torch
        import clip  # openai/CLIP

        if self._device is None:
            self._device = "cuda" if torch.cuda.is_available() else "cpu"

        # 优先使用本地权重文件
        weights_path = str(CLIP_LOCAL_WEIGHTS)
        if os.path.isfile(weights_path):
            model, preprocess = clip.load(weights_path, device=self._device)
        else:
            print(f"[embedder] 本地权重未找到，尝试从缓存加载: {CLIP_MODEL_NAME}")
            model, preprocess = clip.load(CLIP_MODEL_NAME, device=self._device)

        model.eval()
        self._model = model
        self._preprocess = preprocess
        print(f"[embedder] CLIP 模型已加载，设备: {self._device}")

    def process(
        self,
        file_infos: list[FileInfo],
        progress_callback: Callable[[int, int], None] | None = None,
        interrupt_check: Callable[[], bool] | None = None,
    ) -> list[ImageRecord]:
        """
        处理文件列表，返回 ImageRecord 列表。

        - 缓存命中：直接从 SQLite 读取，跳过推理
        - 缓存未命中：批量 CLIP 推理，写入缓存
        - embedding=None 表示文件损坏或不支持，不写缓存
        """
        self._load_model()

        import torch

        total = len(file_infos)
        records: list[ImageRecord] = []
        to_embed: list[tuple[int, FileInfo]] = []   # (在 records 中的下标, file_info)

        # ── 第一遍：检查缓存 ────────────────────────────────────────────────────
        for info in file_infos:
            cached = self._cache.get(info["cache_key"])
            if cached:
                rec = ImageRecord(
                    cache_key=info["cache_key"],
                    path=info["path"],
                    mtime=info["mtime"],
                    filesize=info["filesize"],
                    embedding=cached["embedding"],
                    phash=cached["phash"],
                    sharpness=cached["sharpness"],
                )
            else:
                rec = ImageRecord(
                    cache_key=info["cache_key"],
                    path=info["path"],
                    mtime=info["mtime"],
                    filesize=info["filesize"],
                )
                to_embed.append((len(records), info))
            records.append(rec)

        cached_count = total - len(to_embed)
        done = cached_count

        if progress_callback:
            progress_callback(done, total)

        # ── 第二遍：批量推理未缓存的文件 ───────────────────────────────────────
        batch_size = CLIP_BATCH_SIZE
        i = 0
        while i < len(to_embed):
            if interrupt_check and interrupt_check():
                break

            batch = to_embed[i: i + batch_size]
            tensors = []
            pil_images = []
            valid_indices = []

            for idx, (rec_idx, info) in enumerate(batch):
                img = _open_image(info["path"])
                if img is None:
                    print(f"[embedder] 跳过损坏文件: {info['path']}")
                    done += 1
                    continue
                pil_images.append(img)
                valid_indices.append((idx, rec_idx))
                try:
                    tensors.append(self._preprocess(img))
                except Exception:
                    pil_images.pop()
                    valid_indices.pop()
                    done += 1

            if not tensors:
                i += batch_size
                if progress_callback:
                    progress_callback(done, total)
                continue

            # GPU 推理
            try:
                batch_tensor = torch.stack(tensors).to(self._device)
                with torch.no_grad():
                    features = self._model.encode_image(batch_tensor)
                    features = features / features.norm(dim=-1, keepdim=True)
                embeddings = features.cpu().numpy().astype(np.float32)
            except RuntimeError as e:
                if "out of memory" in str(e).lower() and batch_size > 1:
                    # OOM：减半 batch size，重试当前批次
                    batch_size = max(1, batch_size // 2)
                    print(f"[embedder] OOM，减小 batch size 至 {batch_size}")
                    torch.cuda.empty_cache()
                    continue
                raise

            # 填回 records，同时计算 pHash 和清晰度
            import imagehash
            new_records_to_cache = []
            for (_, rec_idx), embedding, img in zip(valid_indices, embeddings, pil_images):
                try:
                    phash_val = str(imagehash.phash(img))
                except Exception:
                    phash_val = None
                try:
                    sharpness = _compute_sharpness(img)
                except Exception:
                    sharpness = None

                records[rec_idx].embedding = embedding
                records[rec_idx].phash = phash_val
                records[rec_idx].sharpness = sharpness
                new_records_to_cache.append(records[rec_idx])

            self._cache.put_batch(new_records_to_cache)

            done += len(batch)
            if progress_callback:
                progress_callback(min(done, total), total)

            i += batch_size

        return records
