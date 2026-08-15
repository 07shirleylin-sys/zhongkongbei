from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime
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
    dry_run: bool
    log_dir: Path

    def log(self, task: str, message: str, **fields: Any) -> None:
        event = {
            "time": datetime.now().isoformat(timespec="seconds"),
            "task": task,
            "message": message,
            **fields,
        }
        line = json.dumps(event, ensure_ascii=False)
        print(line, flush=True)
        self.log_dir.mkdir(parents=True, exist_ok=True)
        log_path = self.log_dir / f"{datetime.now().strftime('%Y%m%d')}.jsonl"
        with log_path.open("a", encoding="utf-8") as stream:
            stream.write(line + "\n")


def load_config(path: str | Path) -> dict[str, Any]:
    config_path = Path(path)
    with config_path.open("r", encoding="utf-8") as stream:
        return json.load(stream)


def build_context(config_path: str | Path) -> RuntimeContext:
    config = load_config(config_path)
    service_config = config.get("service", {})
    dry_run = bool(service_config.get("dry_run", False))
    log_dir = Path(service_config.get("log_dir", "logs"))

    arm_config = dict(config["hardware"]["arm"])
    hand_config = dict(config["hardware"]["hand"])
    camera_config = dict(config["hardware"]["camera"])
    arm_config["dry_run"] = dry_run
    hand_config["dry_run"] = dry_run
    camera_config["dry_run"] = dry_run

    return RuntimeContext(
        config=config,
        arm=ArmClient(arm_config),
        hand=HandClient(hand_config),
        camera=CameraClient(camera_config),
        dry_run=dry_run,
        log_dir=log_dir,
    )
