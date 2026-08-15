from __future__ import annotations

from app.context import RuntimeContext


def run_task3(ctx: RuntimeContext) -> tuple[bool, str]:
    """任务 3：识别竖直摆放的几何体，并放入对应形状名称槽位。

    负责人只改这个文件。建议流程：
    1. 机械臂到任务 3 拍照位。
    2. 识别形状类别和抓取点。
    3. 查 config["tasks"]["task3"]["slots"] 中对应槽位。
    4. 抓取、抬升、移动、校正姿态、放置。
    """
    del ctx
    return False, "task3 not implemented"
