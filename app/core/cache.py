"""
SQLite embedding 缓存。

只存一张表：image_cache。
职责：embedding/phash/sharpness 的读写，不含任何业务逻辑。
线程安全：写操作加锁，读操作并发安全（WAL 模式）。
"""
from __future__ import annotations

import sqlite3
import threading
from pathlib import Path
from typing import TYPE_CHECKING

import numpy as np

from app.config import DB_PATH, EMBEDDING_DIM

if TYPE_CHECKING:
    from app.models.image_record import ImageRecord

_CREATE_TABLE_SQL = """
CREATE TABLE IF NOT EXISTS image_cache (
    cache_key  TEXT PRIMARY KEY,
    path       TEXT NOT NULL,
    embedding  BLOB NOT NULL,
    phash      TEXT,
    sharpness  REAL
);
"""


class Cache:
    def __init__(self, db_path: Path = DB_PATH) -> None:
        db_path.parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(
            str(db_path),
            check_same_thread=False,   # 多线程共享连接，写操作自行加锁
        )
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._conn.execute("PRAGMA synchronous=NORMAL")
        self._conn.execute(_CREATE_TABLE_SQL)
        self._conn.commit()
        self._write_lock = threading.Lock()

    # ── 读 ──────────────────────────────────────────────────────────────────────

    def get(self, cache_key: str) -> dict | None:
        """
        返回 {embedding, phash, sharpness} 或 None（未命中）。
        embedding 已还原为 numpy array。
        """
        row = self._conn.execute(
            "SELECT embedding, phash, sharpness FROM image_cache WHERE cache_key = ?",
            (cache_key,),
        ).fetchone()
        if row is None:
            return None
        raw_emb, phash, sharpness = row
        embedding = np.frombuffer(raw_emb, dtype=np.float32).copy()
        if embedding.shape != (EMBEDDING_DIM,):
            # 缓存损坏，当作未命中
            return None
        return {"embedding": embedding, "phash": phash, "sharpness": sharpness}

    def count(self) -> int:
        return self._conn.execute("SELECT COUNT(*) FROM image_cache").fetchone()[0]

    # ── 写 ──────────────────────────────────────────────────────────────────────

    def put_batch(self, records: list[ImageRecord]) -> None:
        """
        批量写入，单事务（比逐条 INSERT 快约 100x）。
        只写已成功提取 embedding 的 record。
        """
        rows = [
            (
                r.cache_key,
                r.path,
                r.embedding.astype(np.float32).tobytes(),
                r.phash,
                r.sharpness,
            )
            for r in records
            if r.embedding is not None
        ]
        if not rows:
            return
        with self._write_lock:
            self._conn.executemany(
                "INSERT OR REPLACE INTO image_cache "
                "(cache_key, path, embedding, phash, sharpness) "
                "VALUES (?, ?, ?, ?, ?)",
                rows,
            )
            self._conn.commit()

    def invalidate(self, cache_key: str) -> None:
        with self._write_lock:
            self._conn.execute(
                "DELETE FROM image_cache WHERE cache_key = ?", (cache_key,)
            )
            self._conn.commit()

    # ── 生命周期 ─────────────────────────────────────────────────────────────────

    def close(self) -> None:
        self._conn.close()

    def __enter__(self) -> "Cache":
        return self

    def __exit__(self, *_) -> None:
        self.close()
