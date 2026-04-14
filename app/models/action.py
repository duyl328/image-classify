"""
StagedAction：暂存的待执行文件操作。

所有删除/移动/标记操作先进入 ActionQueue（内存），
用户在确认弹窗点击"执行"后才真正操作文件系统。
"""
from __future__ import annotations

import time
from dataclasses import dataclass, field
from enum import Enum, auto


class ActionType(Enum):
    DELETE = auto()     # 移入系统回收站（send2trash）
    MOVE = auto()       # 移动到指定目录（shutil.move）
    REVIEW = auto()     # 仅标记"待复查"，不移动文件


@dataclass
class StagedAction:
    action_type: ActionType
    image_paths: list[str]          # 绝对路径列表
    target_dir: str | None = None   # 仅 MOVE 时有值
    created_at: float = field(default_factory=time.time)


@dataclass
class ExecutionResult:
    """execute() 的返回值，记录成功和失败的路径。"""
    succeeded: list[str] = field(default_factory=list)
    failed: list[tuple[str, Exception]] = field(default_factory=list)

    def total(self) -> int:
        return len(self.succeeded) + len(self.failed)

    def has_failures(self) -> bool:
        return bool(self.failed)
