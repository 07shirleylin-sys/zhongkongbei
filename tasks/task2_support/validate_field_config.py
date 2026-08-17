from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from types import SimpleNamespace

PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from tasks.task2_blocks import (
    BlockObservation,
    Task2Error,
    _load_settings,
    build_transfer_plans,
)
from tasks.task2_support.calibration import load_calibration


def main() -> int:
    parser = argparse.ArgumentParser(description="Validate every field-only task 2 parameter without hardware movement")
    parser.add_argument("config", type=Path)
    parser.add_argument(
        "--require-real",
        action="store_true",
        help="also require service.dry_run=false; no hardware is moved by this command",
    )
    args = parser.parse_args()
    try:
        payload = json.loads(args.config.read_text(encoding="utf-8"))
        service = payload.get("service", {})
        configured_dry_run = not isinstance(service, dict) or bool(service.get("dry_run", True))
        if args.require_real and configured_dry_run:
            raise Task2Error("service.dry_run must be false for field validation")
        context = SimpleNamespace(config=payload, dry_run=False)
        settings = _load_settings(context)  # type: ignore[arg-type]
        _validate_hand_poses(payload, settings.grip_pose_name)
        if str(settings.vision_config.get("coordinate_mode", "fixed_slot")) == "depth_robot":
            calibration_path = settings.vision_config.get("calibration_path") or settings.camera_config.get(
                "calibration_path"
            )
            load_calibration(str(calibration_path))
        slots = list(settings.source_slots)
        observations = tuple(
            BlockObservation(number=index + 1, source_slot=slot, confidence=1.0)
            for index, slot in enumerate(slots)
        )
        plans = build_transfer_plans(observations, settings)
    except (OSError, ValueError, TypeError, KeyError, Task2Error) as error:
        print(json.dumps({"success": False, "message": str(error)}, ensure_ascii=False, indent=2))
        return 1

    print(
        json.dumps(
            {
                "success": True,
                "message": "task2 field configuration is complete and within workspace bounds",
                "coordinateMode": settings.vision_config.get("coordinate_mode", "fixed_slot"),
                "configuredDryRun": configured_dry_run,
                "readyForReal": not configured_dry_run,
                "sourceSlots": slots,
                "dropPointCount": len(settings.drop_points),
                "plannedOrder": [plan.number for plan in plans],
                "gripPoseName": settings.grip_pose_name,
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0


def _validate_hand_poses(payload: dict[str, object], grip_pose_name: str) -> None:
    hardware = payload.get("hardware")
    if not isinstance(hardware, dict):
        raise Task2Error("hardware configuration is missing")
    hand = hardware.get("hand")
    if not isinstance(hand, dict):
        raise Task2Error("hardware.hand configuration is missing")
    poses = hand.get("poses")
    if not isinstance(poses, dict):
        raise Task2Error("hardware.hand.poses configuration is missing")
    for name in ("open", grip_pose_name):
        values = poses.get(name)
        if not isinstance(values, list) or len(values) != 10:
            raise Task2Error(f"hardware.hand.poses.{name} must contain 10 values")
        if any(isinstance(value, bool) or not 0 <= float(value) <= 1 for value in values):
            raise Task2Error(f"hardware.hand.poses.{name} values must be between 0 and 1")


if __name__ == "__main__":
    raise SystemExit(main())
