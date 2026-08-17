from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from tasks.task2_support.vision import Task2VisionError, detect_task2_blocks


def main() -> int:
    parser = argparse.ArgumentParser(description="Replay task 2 digit/center detection without moving the robot")
    parser.add_argument("config", type=Path, help="deployment JSON containing tasks.task2.vision")
    parser.add_argument("--rgb", required=True, type=Path, help="captured RGB .npy or image file")
    parser.add_argument("--depth", type=Path, help="captured raw depth .npy; required for depth_robot mode")
    parser.add_argument("--calibration", type=Path, help="override calibration JSON")
    args = parser.parse_args()
    try:
        payload = json.loads(args.config.read_text(encoding="utf-8"))
        vision = dict(payload["tasks"]["task2"]["vision"])
        if args.calibration is not None:
            vision["calibration_path"] = str(args.calibration)
        capture: dict[str, object] = {"success": True, "rgb_path": str(args.rgb)}
        if args.depth is not None:
            capture["depth_path"] = str(args.depth)
        blocks = detect_task2_blocks(capture, vision)
    except (OSError, ValueError, KeyError, TypeError, Task2VisionError) as error:
        print(json.dumps({"success": False, "message": str(error)}, ensure_ascii=False, indent=2))
        return 1
    print(json.dumps({"success": True, "blocks": blocks}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
