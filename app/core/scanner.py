"""
目录扫描器。

递归遍历目录，过滤图片文件，生成文件信息字典。
不读取文件内容，只用 os.scandir 的 DirEntry.stat()。
"""
from __future__ import annotations

import os
from collections.abc import Iterator
from typing import TypedDict

from app.config import MIN_FILE_SIZE_KB, SUPPORTED_EXTENSIONS, VIDEO_EXTENSIONS


class FileInfo(TypedDict):
    path: str           # 绝对路径
    mtime: float        # 修改时间戳
    filesize: int       # 字节数
    cache_key: str      # "{path}|{mtime}|{filesize}"


def scan(
    dirs: list[str],
    *,
    recursive: bool = True,
    include_video: bool = False,
    min_size_kb: int = MIN_FILE_SIZE_KB,
) -> Iterator[FileInfo]:
    """
    扫描一组目录，yield 每个合格文件的 FileInfo。

    - 不读取文件内容，仅依赖 DirEntry.stat()
    - 跳过不可读文件（OSError），记录到 stderr
    - 追踪 (dev, inode) 避免符号链接循环
    """
    allowed = SUPPORTED_EXTENSIONS | (VIDEO_EXTENSIONS if include_video else frozenset())
    min_bytes = min_size_kb * 1024
    seen_inodes: set[tuple[int, int]] = set()

    for root_dir in dirs:
        yield from _walk(root_dir, allowed, min_bytes, seen_inodes, recursive)


def _walk(
    directory: str,
    allowed: frozenset[str],
    min_bytes: int,
    seen_inodes: set[tuple[int, int]],
    recursive: bool,
) -> Iterator[FileInfo]:
    try:
        entries = list(os.scandir(directory))
    except OSError as e:
        print(f"[scanner] 无法读取目录 {directory}: {e}", flush=True)
        return

    for entry in entries:
        try:
            stat = entry.stat(follow_symlinks=True)
        except OSError as e:
            print(f"[scanner] 无法 stat {entry.path}: {e}", flush=True)
            continue

        # Windows 上 st_ino 对所有文件都是 0，只在 st_ino 非零时才做去重
        # （仅用于防止 Linux/Mac 上的符号链接循环）
        if stat.st_ino != 0:
            inode_key = (stat.st_dev, stat.st_ino)
            if inode_key in seen_inodes:
                continue
            seen_inodes.add(inode_key)

        if entry.is_dir(follow_symlinks=True):
            if recursive:
                yield from _walk(entry.path, allowed, min_bytes, seen_inodes, recursive)
            continue

        if not entry.is_file(follow_symlinks=True):
            continue

        ext = os.path.splitext(entry.name)[1].lower()
        if ext not in allowed:
            continue

        if stat.st_size < min_bytes:
            continue

        abs_path = os.path.abspath(entry.path)
        mtime = stat.st_mtime
        filesize = stat.st_size
        cache_key = f"{abs_path}|{mtime}|{filesize}"

        yield FileInfo(
            path=abs_path,
            mtime=mtime,
            filesize=filesize,
            cache_key=cache_key,
        )
