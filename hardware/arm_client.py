from __future__ import annotations

from typing import Any

from hardware.http_json import get_json, post_json


class ArmClient:
    def __init__(self, config: dict[str, Any]) -> None:
        self.base_url = config["base_url"]
        self.arm = config.get("arm", "right")
        self.default_timeout = float(config.get("timeout_sec", 90))

    def status(self) -> dict:
        return get_json(self.base_url, "/api/status", timeout=5)

    def motors(self) -> dict:
        return get_json(self.base_url, "/api/motors", timeout=5)

    def enable(self) -> dict:
        return post_json(self.base_url, "/api/enable", {}, timeout=15)

    def move_pose(
        self,
        x: float,
        y: float,
        z: float,
        roll: float = -3.141,
        pitch: float = -1.552,
        yaw: float = 3.141,
        *,
        linear: bool = True,
        velocity_scaling: float = 0.12,
        plan_only: bool = False,
        timeout: float | None = None,
    ) -> dict:
        payload = {
            "mode": f"{self.arm}_arm",
            self.arm: {"x": x, "y": y, "z": z, "roll": roll, "pitch": pitch, "yaw": yaw},
            "cartesian_linear": linear,
            "velocity_scaling": velocity_scaling,
            "plan_only": plan_only,
        }
        return post_json(self.base_url, "/api/end_effector", payload, timeout=timeout or self.default_timeout)

    def move_joints(self, joints: list[float], velocity_scaling: float = 0.2) -> dict:
        payload = {
            "mode": f"{self.arm}_arm",
            f"{self.arm}_joints": joints,
            "velocity_scaling": velocity_scaling,
        }
        return post_json(self.base_url, "/api/joints", payload, timeout=120)
