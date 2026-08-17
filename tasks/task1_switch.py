from __future__ import annotations

import time
from typing import Any

from app.context import RuntimeContext

# 亮灯识别：默认依赖 numpy + Pillow（现场机器需要安装，pip install numpy Pillow）
# 三个检测框从左到右对应开关：red(红/左) -> white(白/中) -> green(绿/右)，
# 与 config/local.json 里 tasks.task1.switch_targets 的键一一对应。
_LAMP_NAMES = ("red", "white", "green")

# 颜色阈值（HSV，H 0~180，S/V 0~255）
_RED_LO, _RED_HI = 0, 14
_RED_WRAP = 168
_GREEN_LO, _GREEN_HI = 38, 88
_MIN_SAT, _MIN_VAL = 80, 80
_WHITE_MAX_SAT, _WHITE_MIN_VAL = 45, 200


class Task1Error(RuntimeError):
    pass


# ---------------- 亮灯识别 ----------------
def _to_rgb_array(img: Any):
    import numpy as np

    if hasattr(img, "convert"):  # PIL Image
        img = np.asarray(img.convert("RGB"))
    arr = np.asarray(img)
    if arr.ndim != 3 or arr.shape[2] != 3:
        raise Task1Error("图像必须是 RGB 三通道")
    return arr


def _rgb_to_hsv(img: Any):
    import numpy as np

    rgb = np.asarray(img, dtype=np.float32) / 255.0
    r, g, b = rgb[..., 0], rgb[..., 1], rgb[..., 2]
    mx = np.maximum(np.maximum(r, g), b)
    mn = np.minimum(np.minimum(r, g), b)
    diff = mx - mn
    h = np.zeros_like(mx)
    ok = diff > 1e-6
    rm = ok & (mx == r)
    gm = ok & (mx == g)
    bm = ok & (mx == b)
    h[rm] = ((g - b)[rm] / diff[rm]) % 6.0
    h[gm] = ((b - r)[gm] / diff[gm]) + 2.0
    h[bm] = ((r - g)[bm] / diff[bm]) + 4.0
    h = h * 30.0
    s = np.where(mx > 1e-6, diff / np.maximum(mx, 1e-6), 0.0) * 255.0
    v = mx * 255.0
    return h, s, v


def _detect_lit(image: Any, detect_cfg: dict[str, Any] | None = None) -> list[int]:
    """识别面板上哪几盏灯亮着，返回亮灯索引（0 左 / 1 中 / 2 右）。"""
    detect_cfg = detect_cfg or {}
    centers = detect_cfg.get("centers", [0.25, 0.5, 0.75])
    roi_width = float(detect_cfg.get("roi_width", 0.22))
    roi_height = float(detect_cfg.get("roi_height", 0.5))
    roi_center_y = float(detect_cfg.get("roi_center_y", 0.5))
    min_pixels = int(detect_cfg.get("min_pixels", 30))

    arr = _to_rgb_array(image)
    h, s, v = _rgb_to_hsv(arr)
    red = (((h >= _RED_LO) & (h <= _RED_HI)) | (h >= _RED_WRAP)) & (s >= _MIN_SAT) & (v >= _MIN_VAL)
    green = (h >= _GREEN_LO) & (h <= _GREEN_HI) & (s >= _MIN_SAT) & (v >= _MIN_VAL)
    white = (s <= _WHITE_MAX_SAT) & (v >= _WHITE_MIN_VAL)
    height, width = h.shape

    lit: list[int] = []
    for i, cx in enumerate(centers):
        x0 = max(0.0, cx - roi_width / 2.0)
        x1 = min(1.0, cx + roi_width / 2.0)
        y0 = max(0.0, roi_center_y - roi_height / 2.0)
        y1 = min(1.0, roi_center_y + roi_height / 2.0)
        x0i, y0i = int(x0 * width), int(y0 * height)
        x1i, y1i = max(int(x1 * width), x0i + 1), max(int(y1 * height), y0i + 1)
        r_cnt = int(red[y0i:y1i, x0i:x1i].sum())
        g_cnt = int(green[y0i:y1i, x0i:x1i].sum())
        w_cnt = int(white[y0i:y1i, x0i:x1i].sum())
        if max(r_cnt, g_cnt, w_cnt) >= min_pixels:
            lit.append(i)
    return lit


def _load_capture_image(capture_result: dict[str, Any]):
    """从相机返回结果里取 RGB 图像（rgb_path 为图片文件路径）。"""
    rgb_path = capture_result.get("rgb_path")
    if not rgb_path:
        raise Task1Error("相机未返回 rgb_path，请确认 Gemini335 取图已实现")
    from PIL import Image

    return Image.open(rgb_path).convert("RGB")


# ---------------- 机械臂辅助 ----------------
def _move_pose(ctx: RuntimeContext, pose: dict[str, Any], velocity_scaling: float, label: str = "") -> None:
    resp = ctx.arm.move_pose(
        pose["x"], pose["y"], pose["z"],
        roll=pose.get("roll", -3.141),
        pitch=pose.get("pitch", -1.552),
        yaw=pose.get("yaw", 3.141),
        linear=True,
        velocity_scaling=velocity_scaling,
    )
    if not resp.get("success"):
        raise Task1Error("{}运动失败: {}".format(label or "机械臂", resp.get("message")))
    ctx.log("task1", "moved", label=label,
            x=round(pose["x"], 4), y=round(pose["y"], 4), z=round(pose["z"], 4))


def _ensure_arm_ready(ctx: RuntimeContext) -> None:
    motors = ctx.arm.motors()
    if not isinstance(motors, dict) or not motors:
        raise Task1Error("机械臂电机未就绪（motors 返回空），请现场检查")
    enabled = all(
        isinstance(j, dict) and j.get("enabled") == 1
        for j in motors.values()
    ) if motors else False
    if not enabled:
        resp = ctx.arm.enable()
        inner = resp.get(ctx.arm.arm, resp) if isinstance(resp, dict) else resp
        if not (isinstance(inner, dict) and inner.get("success")):
            raise Task1Error("机械臂使能失败: {}".format(
                inner.get("message") if isinstance(inner, dict) else resp))
    ctx.log("task1", "arm ready", enabled=enabled)


def _safe_recover(ctx: RuntimeContext) -> None:
    """出错后尽力回安全位。"""
    home = ctx.config.get("motion", {}).get("safe_home")
    if not home:
        return
    try:
        ctx.log("task1", "recovering to safe home")
        _move_pose(ctx, home, float(ctx.config["motion"].get("safe_velocity", 0.08)), label="safe_home")
    except Exception as exc:  # noqa: BLE001
        ctx.log("task1", "recover failed", error=repr(exc))


# ---------------- 任务一主流程 ----------------
def run_task1(ctx: RuntimeContext) -> tuple[bool, str]:
    """任务 1：识别亮灯并点按按钮或拨动开关。

    负责人只改这个文件。流程：
    1. 机械臂到任务 1 拍照位（tasks.task1.photo_pose）。
    2. Gemini335 拍照，识别哪个灯亮。
    3. 查 tasks.task1.switch_targets 中对应开关坐标（red/white/green）。
    4. 设置灵巧手 press 手势。
    5. 机械臂执行 接近位 -> 接触位(按下) -> 抬起回接近位。
    """
    ctx.log("task1", "started")
    if ctx.dry_run:
        ctx.log("task1", "dry-run finished")
        return True, "task1 dry-run ok"

    try:
        cfg = ctx.config["tasks"]["task1"]
        motion = ctx.config["motion"]
        safe_vel = float(motion.get("safe_velocity", 0.08))
        press_hold_s = float(cfg.get("press_hold_s", 0.4))

        # 1) 机械臂就绪
        _ensure_arm_ready(ctx)

        # 2) 到拍照位
        photo = cfg.get("photo_pose")
        if not photo:
            return False, "task1 未配置 photo_pose，请现场标定后填入 config/local.json"
        ctx.log("task1", "moving to photo pose")
        _move_pose(ctx, photo, safe_vel, label="photo")

        # 3) 拍照并识别亮灯
        shot = ctx.camera.capture()
        lit = _detect_lit(_load_capture_image(shot), cfg.get("detect"))
        ctx.log("task1", "detected lit lamps", lit=lit)
        if not lit:
            return False, "task1 未检测到亮灯，请检查相机画面与面板位置"

        name = _LAMP_NAMES[lit[0]]
        targets = cfg.get("switch_targets", {})
        target = targets.get(name)
        if not target:
            return False, "task1 未配置 switch_targets[{}]，请现场标定后填入 config/local.json".format(name)
        action = target.get("action", "button")
        ctx.log("task1", "target switch", lamp=name, action=action)

        # 4) 灵巧手摆 press 手势
        ctx.hand.pose("press")
        ctx.log("task1", "hand pose set", pose="press")

        # 5) 接近 -> 接触(按下) -> 抬起
        approach = target["approach"]
        contact = target["contact"]
        _move_pose(ctx, approach, safe_vel, label="approach")
        _move_pose(ctx, contact, safe_vel * 0.5, label="contact_press")
        time.sleep(press_hold_s)

        swipe = target.get("swipe") or {}
        if any(abs(float(swipe.get(k, 0.0))) > 1e-6 for k in ("x", "y", "z")):
            swipe_pose = {
                "x": contact["x"] + float(swipe.get("x", 0.0)),
                "y": contact["y"] + float(swipe.get("y", 0.0)),
                "z": contact["z"] + float(swipe.get("z", 0.0)),
                "roll": contact.get("roll", -3.141),
                "pitch": contact.get("pitch", -1.552),
                "yaw": contact.get("yaw", 3.141),
            }
            _move_pose(ctx, swipe_pose, safe_vel * 0.5, label="swipe")
            time.sleep(0.2)

        _move_pose(ctx, approach, safe_vel, label="retract")

        ctx.log("task1", "finished", lamp=name, success=True)
        return True, "task1 ok（{}）".format(name)

    except Exception as exc:  # noqa: BLE001
        ctx.log("task1", "failed", error=repr(exc))
        _safe_recover(ctx)
        return False, "task1 失败: {}".format(exc)
