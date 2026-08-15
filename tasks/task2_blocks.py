from __future__ import annotations

from app.context import RuntimeContext


def run_task2(ctx: RuntimeContext) -> tuple[bool, str]:
    """任务 2：识别数字 1-4 长方体，并按 1 -> 2 -> 3 -> 4 转运。

    负责人只改这个文件。建议流程：
    1. 机械臂到任务 2 拍照位。
    2. 识别顶面数字和每个长方体中心点。
    3. 按数字排序。
    4. 对每个物体执行：预抓取 -> 下降 -> 灵巧手抓取 -> 抬升 -> 放置 -> 释放。
    5. 保持放置姿态与槽内姿态一致。
    """
    del ctx
    return False, "task2 not implemented"
