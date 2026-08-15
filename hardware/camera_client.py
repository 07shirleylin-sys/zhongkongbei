from __future__ import annotations

from typing import Any


class CameraClient:
    def __init__(self, config: dict[str, Any]) -> None:
        self.config = config

    def capture(self) -> dict[str, Any]:
        """Replace this stub with Gemini335 capture code on site."""
        return {"success": False, "message": "camera capture is not implemented yet"}
