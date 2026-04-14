"""
暂存操作队列（纯内存）。

所有删除/移动/标记操作先 add() 进队列，
用户确认后调用 execute() 才真正操作文件系统。
进程退出后队列清空，不持久化。
"""
from __future__ import annotations

from collections import defaultdict
from collections.abc import Callable

from app.models.action import ActionType, ExecutionResult, StagedAction


class ActionConflictError(Exception):
    """同一路径同时出现在不同操作类型中。"""


class ActionQueue:
    def __init__(self) -> None:
        # {action_type: {path: target_dir or None}}
        self._actions: dict[ActionType, dict[str, str | None]] = defaultdict(dict)

    # ── 增删 ─────────────────────────────────────────────────────────────────────

    def add(self, action: StagedAction) -> None:
        """
        将操作加入队列。
        同路径不能同时出现在 DELETE 和 MOVE 中（后加的覆盖，并从旧类型移除）。
        """
        for path in action.image_paths:
            # 从其他类型中移除该路径（避免冲突）
            for other_type in ActionType:
                if other_type != action.action_type:
                    self._actions[other_type].pop(path, None)
            self._actions[action.action_type][path] = action.target_dir

    def remove_paths(self, action_type: ActionType, paths: list[str]) -> None:
        for path in paths:
            self._actions[action_type].pop(path, None)

    def clear(self) -> None:
        self._actions.clear()

    # ── 查询 ─────────────────────────────────────────────────────────────────────

    def get_summary(self) -> dict[str, int]:
        return {
            "delete": len(self._actions[ActionType.DELETE]),
            "move":   len(self._actions[ActionType.MOVE]),
            "review": len(self._actions[ActionType.REVIEW]),
        }

    def get_paths(self, action_type: ActionType) -> list[str]:
        return list(self._actions[action_type].keys())

    def total(self) -> int:
        return sum(len(v) for v in self._actions.values())

    def is_empty(self) -> bool:
        return self.total() == 0

    def staged_paths(self) -> set[str]:
        """所有已暂存的路径（任意操作类型）。"""
        result: set[str] = set()
        for paths_dict in self._actions.values():
            result.update(paths_dict.keys())
        return result

    # ── 执行 ─────────────────────────────────────────────────────────────────────

    def execute(
        self,
        progress_callback: Callable[[int, int], None] | None = None,
    ) -> ExecutionResult:
        """
        执行所有暂存操作。
        - DELETE：移入系统回收站（send2trash），非永久删除
        - MOVE：shutil.move，支持跨盘符
        - REVIEW：写路径到文本文件（~/image_classify_review.txt）
        单个文件失败不中断整体执行。
        """
        import os
        import shutil

        import send2trash

        result = ExecutionResult()
        all_items = []

        for path, target in self._actions[ActionType.DELETE].items():
            all_items.append((ActionType.DELETE, path, target))
        for path, target in self._actions[ActionType.MOVE].items():
            all_items.append((ActionType.MOVE, path, target))
        for path, target in self._actions[ActionType.REVIEW].items():
            all_items.append((ActionType.REVIEW, path, target))

        total = len(all_items)
        done = 0

        # 收集 REVIEW 路径，批量写文件
        review_paths: list[str] = []

        for action_type, path, target in all_items:
            try:
                if action_type == ActionType.DELETE:
                    send2trash.send2trash(path)
                    result.succeeded.append(path)

                elif action_type == ActionType.MOVE:
                    if not target:
                        raise ValueError("MOVE 操作缺少目标目录")
                    os.makedirs(target, exist_ok=True)
                    dest = os.path.join(target, os.path.basename(path))
                    # 目标已存在时加后缀避免覆盖
                    if os.path.exists(dest):
                        name, ext = os.path.splitext(os.path.basename(path))
                        dest = os.path.join(target, f"{name}_1{ext}")
                    shutil.move(path, dest)
                    result.succeeded.append(path)

                elif action_type == ActionType.REVIEW:
                    review_paths.append(path)
                    result.succeeded.append(path)

            except Exception as e:
                result.failed.append((path, e))

            done += 1
            if progress_callback:
                progress_callback(done, total)

        # 写 REVIEW 文件
        if review_paths:
            review_file = os.path.expanduser("~/image_classify_review.txt")
            try:
                with open(review_file, "a", encoding="utf-8") as f:
                    for p in review_paths:
                        f.write(p + "\n")
            except OSError as e:
                print(f"[action_queue] 写 review 文件失败: {e}")

        return result
