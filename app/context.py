from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from hardware.arm_client import ArmClient
from hardware.camera_client import CameraClient
from hardware.hand_client import HandClient


@dataclass
class RuntimeContext:
    config: dict[str, Any]
    arm: ArmClient
    hand: HandClient
    camera: CameraClient


def load_config(path: str | Path) -> dict[str, Any]:
    config_path = Path(path)
    with config_path.open("r", encoding="utf-8") as stream:
        return json.load(stream)


def build_context(config_path: str | Path) -> RuntimeContext:
    config = load_config(config_path)
    return RuntimeContext(
        config=config,
        arm=ArmClient(config["hardware"]["arm"]),
        hand=HandClient(config["hardware"]["hand"]),
        camera=CameraClient(config["hardware"]["camera"]),
    )
