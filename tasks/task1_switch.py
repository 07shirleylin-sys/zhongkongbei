from __future__ import annotations

from app.context import RuntimeContext


def run_task1(ctx: RuntimeContext) -> tuple[bool, str]:
    """任务 1：识别亮灯并点按按钮或拨动开关。

    负责人只改这个文件。建议流程：
    1. 机械臂到任务 1 拍照位。
    2. Gemini335 拍照，识别哪个灯亮。
    3. 查 config["tasks"]["task1"] 中对应开关坐标。
    4. 设置灵巧手点按/拨动手势。
    5. 机械臂执行预位 -> 接触位 -> 撤离位。
    """
    del ctx
    return False, "task1 not implemented"
