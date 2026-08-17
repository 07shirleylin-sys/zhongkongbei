from __future__ import annotations

import itertools
import unittest
from types import SimpleNamespace

from tasks import task2_blocks
from tasks.task2_blocks import (
    BlockObservation,
    Pose,
    Task2Error,
    Task2Settings,
    _load_settings,
    build_transfer_plans,
    run_task2,
    validate_and_sort_observations,
)


class _FakeArm:
    arm = "right"

    def __init__(self) -> None:
        self.moves: list[dict[str, object]] = []

    def status(self) -> dict[str, object]:
        return {"success": True, "moveit_available": True, "moving": False}

    def motors(self) -> dict[str, object]:
        return {"success": True, "enabled": True}

    def enable(self) -> dict[str, object]:
        return {"right": {"success": True, "message": "enabled"}}

    def move_pose(self, *args: object, **kwargs: object) -> dict[str, object]:
        self.moves.append({"args": args, **kwargs})
        return {"success": True, "message": "Cartesian execution finished"}


class _FakeHand:
    def __init__(self) -> None:
        self.poses = {
            "open": [1.0] * 10,
            "box_grip": [0.5] * 10,
        }
        self.commands: list[str] = []

    def status(self) -> dict[str, object]:
        return {"success": True, "connected": True}

    def open_hand(self) -> dict[str, object]:
        self.commands.append("open")
        return {"success": True, "message": "opened"}

    def pose(self, name: str) -> dict[str, object]:
        self.commands.append(name)
        return {"success": True, "message": name}

    def release(self) -> dict[str, object]:
        self.commands.append("release")
        return {"success": True, "message": "released"}


class _FakeCamera:
    config = {"name": "Gemini335", "serial": ""}

    def capture(self) -> dict[str, object]:
        return {"success": True, "message": "dry camera"}


class _FakeContext:
    def __init__(self) -> None:
        self.dry_run = True
        self.arm = _FakeArm()
        self.hand = _FakeHand()
        self.camera = _FakeCamera()
        self.events: list[tuple[str, str, dict[str, object]]] = []
        self.config = {
            "motion": {
                "safe_velocity": 0.08,
                "normal_velocity": 0.12,
                "safe_home": {
                    "x": 0.275,
                    "y": -0.16,
                    "z": 0.50,
                    "roll": -3.141,
                    "pitch": -1.552,
                    "yaw": 3.141,
                },
            },
            "tasks": {
                "task2": {
                    "photo_pose": None,
                    "source_slots": {},
                    "place_area": {},
                    "approach_height_m": 0.05,
                    "lift_height_m": 0.06,
                    "min_confidence": 0.8,
                    "grip_pose_name": "box_grip",
                    "camera": {},
                    "vision": {},
                    "workspace": {},
                }
            },
        }

    def log(self, task: str, message: str, **fields: object) -> None:
        self.events.append((task, message, fields))


def _settings(*, source_x: float = 0.20) -> Task2Settings:
    orientation = (-3.141, -1.552, 3.141)
    source_slots = {
        f"slot_{index}": {
            "x": source_x,
            "y": -0.30 + index * 0.05,
            "z": 0.30,
            "roll": orientation[0],
            "pitch": orientation[1],
            "yaw": orientation[2],
        }
        for index in range(4)
    }
    drop_points = tuple(
        {
            "x": 0.30,
            "y": -0.10 + index * 0.04,
            "z": 0.30,
            "roll": orientation[0],
            "pitch": orientation[1],
            "yaw": orientation[2],
        }
        for index in range(4)
    )
    return Task2Settings(
        photo_pose=Pose(0.25, -0.20, 0.50, *orientation),
        safe_home=Pose(0.25, -0.16, 0.50, *orientation),
        source_slots=source_slots,
        drop_points=drop_points,
        safe_velocity=0.08,
        normal_velocity=0.12,
        approach_height=0.05,
        lift_height=0.08,
        min_confidence=0.8,
        camera_config={},
        vision_config={},
        workspace={
            "bounds": {"x": [0.0, 0.50], "y": [-0.50, 0.50], "z": [0.0, 0.80]},
            "safety_margin_m": 0.01,
        },
        grip_pose_name="box_grip",
        drop_min_spacing=0.03,
    )


def _field_config() -> dict[str, object]:
    settings = _settings()
    return {
        "motion": {
            "safe_velocity": settings.safe_velocity,
            "normal_velocity": settings.normal_velocity,
            "safe_home": settings.safe_home.as_dict(),
        },
        "tasks": {
            "task2": {
                "approach_height_m": settings.approach_height,
                "lift_height_m": settings.lift_height,
                "min_confidence": settings.min_confidence,
                "grip_pose_name": settings.grip_pose_name,
                "photo_pose": settings.photo_pose.as_dict(),
                "source_slots": settings.source_slots,
                "place_area": {
                    "drop_points": list(settings.drop_points),
                    "min_spacing_m": settings.drop_min_spacing,
                },
                "camera": {"name": "Gemini335", "serial": "TEST-335"},
                "vision": {
                    "coordinate_mode": "fixed_slot",
                    "digit_min_confidence": 0.8,
                    "slot_rois": {
                        f"slot_{index}": [index * 10, 0, 10, 10]
                        for index in range(4)
                    },
                },
                "workspace": settings.workspace,
            }
        },
    }


class Task2ExecutorTests(unittest.TestCase):
    def test_all_twenty_four_number_permutations_sort_to_contest_order(self) -> None:
        for permutation in itertools.permutations((1, 2, 3, 4)):
            raw = [
                {"number": number, "source_slot": f"slot_{index}", "confidence": 0.99}
                for index, number in enumerate(permutation)
            ]
            observations = validate_and_sort_observations(raw, min_confidence=0.8)
            self.assertEqual([item.number for item in observations], [1, 2, 3, 4])

    def test_full_dry_run_executes_four_grips_and_four_releases(self) -> None:
        context = _FakeContext()
        ok, message = run_task2(context)  # type: ignore[arg-type]
        self.assertTrue(ok, message)
        self.assertEqual(context.hand.commands.count("box_grip"), 4)
        self.assertEqual(context.hand.commands.count("release"), 4)
        self.assertEqual(len(context.arm.moves), 2 + 8 * 4)

    def test_second_task2_call_is_rejected_while_first_is_running(self) -> None:
        context = _FakeContext()
        acquired = task2_blocks._TASK2_LOCK.acquire(blocking=False)
        self.assertTrue(acquired)
        try:
            ok, message = run_task2(context)  # type: ignore[arg-type]
        finally:
            task2_blocks._TASK2_LOCK.release()
        self.assertFalse(ok)
        self.assertEqual(message, "task2 is already running")

    def test_planner_rejects_grasp_outside_safe_workspace(self) -> None:
        observations = tuple(
            BlockObservation(number=index + 1, source_slot=f"slot_{index}", confidence=0.99)
            for index in range(4)
        )
        with self.assertRaises(Task2Error):
            build_transfer_plans(observations, _settings(source_x=0.60))

    def test_planner_rejects_drop_points_that_are_too_close(self) -> None:
        observations = tuple(
            BlockObservation(number=index + 1, source_slot=f"slot_{index}", confidence=0.99)
            for index in range(4)
        )
        settings = _settings()
        crowded_points = list(settings.drop_points)
        crowded_points[1] = {**crowded_points[0], "y": crowded_points[0]["y"] + 0.01}
        with self.assertRaises(Task2Error):
            build_transfer_plans(
                observations,
                Task2Settings(**{**settings.__dict__, "drop_points": tuple(crowded_points)}),
            )

    def test_complete_field_config_builds_a_safe_four_block_plan(self) -> None:
        context = SimpleNamespace(config=_field_config(), dry_run=False)
        settings = _load_settings(context)  # type: ignore[arg-type]
        observations = tuple(
            BlockObservation(number=index + 1, source_slot=f"slot_{index}", confidence=0.99)
            for index in range(4)
        )
        plans = build_transfer_plans(observations, settings)
        self.assertEqual([plan.number for plan in plans], [1, 2, 3, 4])


if __name__ == "__main__":
    unittest.main()
