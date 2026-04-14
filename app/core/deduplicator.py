"""Near-duplicate image grouping based on pHash Hamming distance."""
from __future__ import annotations

from collections import defaultdict

import numpy as np

from app.config import PHASH_THRESHOLD
from app.core.debug_log import log_debug
from app.models.image_record import ImageRecord


def find_duplicates(
    records: list[ImageRecord],
    threshold: int = PHASH_THRESHOLD,
) -> list[list[ImageRecord]]:
    log_debug("find_duplicates_start", record_count=len(records), threshold=threshold)

    valid = [record for record in records if record.phash is not None]
    if len(valid) < 2:
        log_debug("find_duplicates_done", valid_count=len(valid), group_count=0)
        return []

    hashes = np.array([int(record.phash, 16) for record in valid], dtype=np.uint64)
    parent = list(range(len(valid)))

    def find(index: int) -> int:
        while parent[index] != index:
            parent[index] = parent[parent[index]]
            index = parent[index]
        return index

    def union(left: int, right: int) -> None:
        parent[find(left)] = find(right)

    valid_count = len(valid)
    for index in range(valid_count):
        xor = np.bitwise_xor(hashes[index], hashes[index + 1 :])
        xor_bytes = xor.view(np.uint8).reshape(-1, 8)
        popcount = np.unpackbits(xor_bytes, axis=1).sum(axis=1)
        close = np.where(popcount <= threshold)[0]
        for offset in close:
            union(index, index + 1 + int(offset))

    groups: dict[int, list[ImageRecord]] = defaultdict(list)
    for index, record in enumerate(valid):
        groups[find(index)].append(record)

    result = [group for group in groups.values() if len(group) >= 2]
    log_debug("find_duplicates_done", valid_count=len(valid), group_count=len(result))
    return result
