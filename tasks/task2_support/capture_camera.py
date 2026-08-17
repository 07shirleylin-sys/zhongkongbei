from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from tasks.task2_support.orbbec_camera import Task2CameraError, capture_task2_frame


def main() -> int:
    parser = argparse.ArgumentParser(description="Capture one Gemini335 RGB/depth frame for task 2")
    parser.add_argument("config", type=Path, help="deployment JSON containing hardware.camera and tasks.task2.camera")
    args = parser.parse_args()
    try:
        payload = json.loads(args.config.read_text(encoding="utf-8"))
        hardware_camera = payload["hardware"]["camera"]
        task2_camera = payload["tasks"]["task2"]["camera"]
        capture = capture_task2_frame(hardware_camera, task2_camera)
    except (OSError, ValueError, KeyError, TypeError, Task2CameraError) as error:
        print(json.dumps({"success": False, "message": str(error)}, ensure_ascii=False, indent=2))
        return 1

    summary = {key: value for key, value in capture.items() if key not in {"rgb", "depth_raw", "calibration"}}
    summary["rgb_shape"] = list(capture["rgb"].shape)
    summary["depth_shape"] = list(capture["depth_raw"].shape)
    summary["calibration"] = capture["calibration"]
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
