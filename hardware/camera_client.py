from __future__ import annotations

from typing import Any


class CameraClient:
    def __init__(self, config: dict[str, Any]) -> None:
        self.config = config
        self.dry_run = bool(config.get("dry_run", False))

    def capture(self) -> dict[str, Any]:
        """Replace this stub with Gemini335 capture code on site."""
        if self.dry_run:
            return {
                "success": True,
                "message": "dry-run camera capture",
                "rgb_path": None,
                "depth_path": None,
            }
        return {"success": False, "message": "camera capture is not implemented yet"}
