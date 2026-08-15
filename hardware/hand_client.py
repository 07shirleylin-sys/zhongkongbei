from __future__ import annotations

from typing import Any

from hardware.http_json import get_json, post_json


class HandClient:
    def __init__(self, config: dict[str, Any]) -> None:
        self.base_url = config["base_url"]
        self.poses = config.get("poses", {})
        self.dry_run = bool(config.get("dry_run", False))

    def status(self) -> dict:
        if self.dry_run:
            return {"success": True, "message": "dry-run hand status"}
        return get_json(self.base_url, "/api/status", timeout=5)

    def set_pos(self, position: list[float]) -> dict:
        if self.dry_run:
            return {"success": True, "message": "dry-run hand set_pos", "target": position}
        return post_json(self.base_url, "/api/set_pos", {"position": position}, timeout=10)

    def pose(self, name: str) -> dict:
        if name not in self.poses:
            raise KeyError(f"hand pose not configured: {name}")
        return self.set_pos(self.poses[name])

    def open_hand(self) -> dict:
        return self.pose("open")

    def release(self) -> dict:
        return self.pose("open")
