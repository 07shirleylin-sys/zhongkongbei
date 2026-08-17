#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""任务一 现场标定小工具。

作用：比赛现场把机械臂（+灵巧手）挪到某个位置后，一键读取机械臂当前位姿，
记录成命名路点，最后写回 config/local.json 的 tasks.task1，免去手工抄坐标。

用法（在仓库根目录运行）：
  # 读取机械臂当前位姿
  python scripts/calibrate_task1.py read

  # 把当前位姿记录为某个路点（可反复覆盖）
  python scripts/calibrate_task1.py set photo            # 拍照位
  python scripts/calibrate_task1.py set red_approach    # 红(左)接近位
  python scripts/calibrate_task1.py set red_contact     # 红(左)接触位(按下)
  python scripts/calibrate_task1.py set white_approach
  python scripts/calibrate_task1.py set white_contact
  python scripts/calibrate_task1.py set green_approach
  python scripts/calibrate_task1.py set green_contact
  # 可选：拨动开关的滑动终点（相对接触位的位移会自动算出来）
  python scripts/calibrate_task1.py set green_swipe

  # 查看已记录的路点
  python scripts/calibrate_task1.py list

  # 写回 config/local.json 的 tasks.task1
  python scripts/calibrate_task1.py write

  # 没有机械臂时测试本工具（用模拟位姿）
  python scripts/calibrate_task1.py --mock set photo
  python scripts/calibrate_task1.py --mock list
  python scripts/calibrate_task1.py --mock write --config config/local.json

路点临时数据保存在 captures/calib_task1.json（该目录已在 .gitignore 中，不会提交）。
"""
import argparse
import json
import sys
from pathlib import Path
from urllib import request

PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_CONFIG = PROJECT_ROOT / "config" / "local.json"
DEFAULT_CALIB = PROJECT_ROOT / "captures" / "calib_task1.json"

COLORS = ("red", "white", "green")

# 允许记录的路点 key -> 说明
KEY_MAP = {
    "photo": "拍照位",
    "red_approach": "红(左)接近位",
    "red_contact": "红(左)接触位(按下)",
    "red_swipe": "红(左)拨动终点(可选)",
    "white_approach": "白(中)接近位",
    "white_contact": "白(中)接触位(按下)",
    "white_swipe": "白(中)拨动终点(可选)",
    "green_approach": "绿(右)接近位",
    "green_contact": "绿(右)接触位(按下)",
    "green_swipe": "绿(右)拨动终点(可选)",
}

# 模拟机械臂：返回一组像真一样的位姿，用于无硬件时测试工具本身
MOCK_POSES = {
    "photo": {"x": 0.275, "y": -0.16, "z": 0.48, "roll": -3.141, "pitch": -1.552, "yaw": 3.141},
    "red_approach": {"x": 0.275, "y": -0.22, "z": 0.47, "roll": -3.141, "pitch": -1.552, "yaw": 3.141},
    "red_contact": {"x": 0.275, "y": -0.22, "z": 0.45, "roll": -3.141, "pitch": -1.552, "yaw": 3.141},
    "red_swipe": {"x": 0.275, "y": -0.20, "z": 0.45, "roll": -3.141, "pitch": -1.552, "yaw": 3.141},
    "white_approach": {"x": 0.275, "y": -0.16, "z": 0.47, "roll": -3.141, "pitch": -1.552, "yaw": 3.141},
    "white_contact": {"x": 0.275, "y": -0.16, "z": 0.45, "roll": -3.141, "pitch": -1.552, "yaw": 3.141},
    "green_approach": {"x": 0.275, "y": -0.10, "z": 0.47, "roll": -3.141, "pitch": -1.552, "yaw": 3.141},
    "green_contact": {"x": 0.275, "y": -0.10, "z": 0.45, "roll": -3.141, "pitch": -1.552, "yaw": 3.141},
}


def read_arm_pose(base_url: str) -> dict:
    """读取机械臂当前末端位姿。"""
    url = base_url.rstrip("/") + "/api/pose"
    with request.urlopen(url, timeout=5) as resp:
        data = json.loads(resp.read().decode("utf-8"))
    pose = data.get("pose")
    if not pose:
        raise RuntimeError("机械臂位姿未就绪（TF 未解算），请稍候重试")
    return pose


def load_store(path: Path) -> dict:
    if path.exists():
        return json.loads(path.read_text(encoding="utf-8"))
    return {}


def save_store(path: Path, store: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(store, ensure_ascii=False, indent=2), encoding="utf-8")


def cmd_read(args) -> int:
    base_url = args.base_url
    print("机械臂 base_url:", base_url)
    if args.mock:
        print("（--mock：使用模拟位姿）")
        pose = MOCK_POSES["photo"]
    else:
        pose = read_arm_pose(base_url)
    print("当前位姿:")
    print("  x={:.4f} y={:.4f} z={:.4f} roll={:.4f} pitch={:.4f} yaw={:.4f}".format(
        pose["x"], pose["y"], pose["z"], pose.get("roll", -3.141),
        pose.get("pitch", -1.552), pose.get("yaw", 3.141)))
    return 0


def cmd_set(args) -> int:
    if args.key not in KEY_MAP:
        print("未知路点 key：{}".format(args.key))
        print("可选：{}".format(", ".join(KEY_MAP)))
        return 1
    if args.mock:
        pose = MOCK_POSES.get(args.key)
        if not pose:
            print("（--mock 模式下该 key 无模拟数据，跳过）")
            return 1
    else:
        pose = read_arm_pose(args.base_url)
    store = load_store(args.calib)
    store[args.key] = pose
    save_store(args.calib, store)
    print("已记录 {}（{}）: x={:.4f} y={:.4f} z={:.4f}".format(
        args.key, KEY_MAP[args.key], pose["x"], pose["y"], pose["z"]))
    return 0


def cmd_list(args) -> int:
    store = load_store(args.calib)
    if not store:
        print("还没有记录任何路点。先用 set 记录。")
        return 0
    for key in KEY_MAP:
        if key in store:
            p = store[key]
            print("  {:<16} {}  x={:.4f} y={:.4f} z={:.4f}".format(
                key, KEY_MAP[key], p["x"], p["y"], p["z"]))
    return 0


def cmd_write(args) -> int:
    store = load_store(args.calib)
    if "photo" not in store:
        print("缺少 photo（拍照位），请先 set photo")
        return 1
    missing = [c + "_approach" for c in COLORS if c + "_approach" not in store]
    missing += [c + "_contact" for c in COLORS if c + "_contact" not in store]
    if missing:
        print("缺少路点：{}；请先用 set 记录完整".format(", ".join(missing)))
        return 1

    config_path = Path(args.config)
    config = json.loads(config_path.read_text(encoding="utf-8"))

    def full(p):
        return {
            "x": p["x"], "y": p["y"], "z": p["z"],
            "roll": p.get("roll", -3.141),
            "pitch": p.get("pitch", -1.552),
            "yaw": p.get("yaw", 3.141),
        }

    switch_targets = {}
    for color in COLORS:
        approach = full(store[color + "_approach"])
        contact = full(store[color + "_contact"])
        swipe = {"x": 0.0, "y": 0.0, "z": 0.0}
        if color + "_swipe" in store:
            end = store[color + "_swipe"]
            swipe = {
                "x": round(end["x"] - contact["x"], 4),
                "y": round(end["y"] - contact["y"], 4),
                "z": round(end["z"] - contact["z"], 4),
            }
        action = "toggle" if color == "green" else "button"  # 现场按实际情况改
        switch_targets[color] = {
            "action": action,
            "approach": approach,
            "contact": contact,
            "swipe": swipe,
        }

    task1 = config.setdefault("tasks", {}).setdefault("task1", {})
    task1["photo_pose"] = full(store["photo"])
    task1["switch_targets"] = switch_targets
    config_path.write_text(json.dumps(config, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print("已写入 {} 的 tasks.task1".format(config_path))
    print("  photo_pose =", full(store["photo"]))
    for color in COLORS:
        print("  {}: action={}, swipe={}".format(color, switch_targets[color]["action"], switch_targets[color]["swipe"]))
    print("提醒：现场联调真机前，请把 service.dry_run 改成 false。")
    return 0


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description="任务一现场标定工具")
    p.add_argument("command", choices=["read", "set", "list", "write"])
    p.add_argument("key", nargs="?", default=None, help="set 时填写路点 key（如 photo / red_approach）")
    p.add_argument("--base-url", default=None, help="机械臂 base_url（默认读 config/local.json 的 hardware.arm.base_url）")
    p.add_argument("--config", default=str(DEFAULT_CONFIG), help="写回用的配置文件路径")
    p.add_argument("--calib", default=str(DEFAULT_CALIB), help="路点临时文件路径")
    p.add_argument("--mock", action="store_true", help="无机械臂时用模拟位姿测试工具")
    return p


def main() -> int:
    args = build_parser().parse_args()
    args.calib = Path(args.calib)
    args.config = Path(args.config)
    if args.base_url is None:
        config = json.loads(Path(args.config).read_text(encoding="utf-8"))
        args.base_url = config["hardware"]["arm"]["base_url"]
    handlers = {"read": cmd_read, "set": cmd_set, "list": cmd_list, "write": cmd_write}
    return handlers[args.command](args)


if __name__ == "__main__":
    raise SystemExit(main())

