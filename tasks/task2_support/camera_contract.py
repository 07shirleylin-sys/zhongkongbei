from __future__ import annotations

import math
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any


def _finite(value: object, field_name: str) -> float:
    if isinstance(value, bool):
        raise ValueError(f"{field_name} must be a finite number")
    try:
        number = float(value)
    except (TypeError, ValueError) as error:
        raise ValueError(f"{field_name} must be a finite number") from error
    if not math.isfinite(number):
        raise ValueError(f"{field_name} must be a finite number")
    return number


@dataclass(frozen=True)
class CameraIntrinsics:
    """RGB/depth camera intrinsics and the raw-depth-to-metre scale."""

    width: int
    height: int
    fx: float
    fy: float
    cx: float
    cy: float
    depth_scale: float
    distortion: tuple[float, ...] = ()

    @classmethod
    def from_mapping(cls, value: object, field_name: str = "intrinsics") -> "CameraIntrinsics":
        if not isinstance(value, Mapping):
            raise ValueError(f"{field_name} must be an object")
        width = value.get("width")
        height = value.get("height")
        if isinstance(width, bool) or not isinstance(width, int) or width <= 0:
            raise ValueError(f"{field_name}.width must be a positive integer")
        if isinstance(height, bool) or not isinstance(height, int) or height <= 0:
            raise ValueError(f"{field_name}.height must be a positive integer")
        distortion_raw = value.get("distortion", ())
        if isinstance(distortion_raw, (str, bytes)) or not isinstance(distortion_raw, Sequence):
            raise ValueError(f"{field_name}.distortion must be an array")
        return cls(
            width=width,
            height=height,
            fx=_positive(_finite(value.get("fx"), f"{field_name}.fx"), f"{field_name}.fx"),
            fy=_positive(_finite(value.get("fy"), f"{field_name}.fy"), f"{field_name}.fy"),
            cx=_finite(value.get("cx"), f"{field_name}.cx"),
            cy=_finite(value.get("cy"), f"{field_name}.cy"),
            depth_scale=_positive(
                _finite(value.get("depth_scale"), f"{field_name}.depth_scale"),
                f"{field_name}.depth_scale",
            ),
            distortion=tuple(_finite(item, f"{field_name}.distortion[{index}]") for index, item in enumerate(distortion_raw)),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "width": self.width,
            "height": self.height,
            "fx": self.fx,
            "fy": self.fy,
            "cx": self.cx,
            "cy": self.cy,
            "depth_scale": self.depth_scale,
            "distortion": list(self.distortion),
        }


@dataclass(frozen=True)
class CameraExtrinsics:
    """Homogeneous transform from camera coordinates to robot-base coordinates."""

    camera_to_robot: tuple[tuple[float, float, float, float], ...]

    @classmethod
    def from_mapping(cls, value: object, field_name: str = "extrinsics") -> "CameraExtrinsics":
        if not isinstance(value, Mapping):
            raise ValueError(f"{field_name} must be an object")
        raw_matrix = value.get("camera_to_robot")
        if isinstance(raw_matrix, (str, bytes)) or not isinstance(raw_matrix, Sequence) or len(raw_matrix) != 4:
            raise ValueError(f"{field_name}.camera_to_robot must be a 4x4 array")
        matrix: list[tuple[float, float, float, float]] = []
        for row_index, row in enumerate(raw_matrix):
            if isinstance(row, (str, bytes)) or not isinstance(row, Sequence) or len(row) != 4:
                raise ValueError(f"{field_name}.camera_to_robot[{row_index}] must have 4 values")
            matrix.append(
                tuple(_finite(item, f"{field_name}.camera_to_robot[{row_index}][{column}]") for column, item in enumerate(row))
            )
        if matrix[3] != (0.0, 0.0, 0.0, 1.0):
            raise ValueError(f"{field_name}.camera_to_robot bottom row must be [0, 0, 0, 1]")
        return cls(camera_to_robot=tuple(matrix))

    def to_dict(self) -> dict[str, Any]:
        return {"camera_to_robot": [list(row) for row in self.camera_to_robot]}


@dataclass(frozen=True)
class CameraFrame:
    """Stable output of CameraClient.capture()."""

    success: bool
    message: str
    timestamp: float | None = None
    rgb_path: str | None = None
    depth_path: str | None = None
    intrinsics_path: str | None = None
    extrinsics_path: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "success": self.success,
            "message": self.message,
            "timestamp": self.timestamp,
            "rgb_path": self.rgb_path,
            "depth_path": self.depth_path,
            "intrinsics_path": self.intrinsics_path,
            "extrinsics_path": self.extrinsics_path,
        }


@dataclass(frozen=True)
class BlockDetection:
    """Task 2 detection output after image/depth processing."""

    number: int
    source_slot: str
    confidence: float
    center: tuple[float, float, float] | None = None
    grasp_pose: dict[str, float] | None = None

    def to_dict(self) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "number": self.number,
            "source_slot": self.source_slot,
            "confidence": self.confidence,
        }
        if self.center is not None:
            payload["center"] = {"x": self.center[0], "y": self.center[1], "z": self.center[2]}
        if self.grasp_pose is not None:
            payload["grasp_pose"] = dict(self.grasp_pose)
        return payload


def _positive(value: float, field_name: str) -> float:
    if value <= 0:
        raise ValueError(f"{field_name} must be greater than zero")
    return value
