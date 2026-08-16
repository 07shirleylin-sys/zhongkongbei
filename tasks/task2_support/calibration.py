from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

import numpy as np

from tasks.task2_support.camera_contract import CameraExtrinsics, CameraIntrinsics


def pixel_to_camera(
    u: float,
    v: float,
    depth_raw: float,
    intrinsics: CameraIntrinsics,
) -> np.ndarray:
    """Convert one aligned depth pixel to metres in the camera frame."""
    depth = float(depth_raw) * intrinsics.depth_scale
    if not np.isfinite(depth) or depth <= 0:
        raise ValueError("depth must be a positive finite value")
    return np.array(
        [
            (float(u) - intrinsics.cx) * depth / intrinsics.fx,
            (float(v) - intrinsics.cy) * depth / intrinsics.fy,
            depth,
        ],
        dtype=np.float64,
    )


def transform_point(
    point_camera: np.ndarray | list[float] | tuple[float, float, float],
    extrinsics: CameraExtrinsics,
) -> np.ndarray:
    """Transform a camera-frame point into robot-base coordinates."""
    point = np.asarray(point_camera, dtype=np.float64)
    if point.shape != (3,):
        raise ValueError("point must contain exactly three coordinates")
    homogeneous = np.concatenate([point, np.array([1.0])])
    matrix = np.asarray(extrinsics.camera_to_robot, dtype=np.float64)
    result = matrix @ homogeneous
    if not np.isclose(result[3], 1.0, atol=1e-6):
        raise ValueError("camera_to_robot produced an invalid homogeneous coordinate")
    return result[:3]


def pixel_to_robot(
    u: float,
    v: float,
    depth_raw: float,
    intrinsics: CameraIntrinsics,
    extrinsics: CameraExtrinsics,
) -> np.ndarray:
    return transform_point(pixel_to_camera(u, v, depth_raw, intrinsics), extrinsics)


def load_calibration(path: str | Path) -> tuple[CameraIntrinsics, CameraExtrinsics]:
    calibration_path = Path(path)
    with calibration_path.open("r", encoding="utf-8") as stream:
        payload = json.load(stream)
    if not isinstance(payload, dict):
        raise ValueError("calibration root must be an object")
    return (
        CameraIntrinsics.from_mapping(payload.get("intrinsics")),
        CameraExtrinsics.from_mapping(payload.get("extrinsics")),
    )


def calibration_summary(path: str | Path) -> dict[str, Any]:
    intrinsics, extrinsics = load_calibration(path)
    return {
        "path": str(path),
        "resolution": [intrinsics.width, intrinsics.height],
        "depth_scale": intrinsics.depth_scale,
        "distortion_coefficients": len(intrinsics.distortion),
        "camera_to_robot": extrinsics.to_dict()["camera_to_robot"],
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Validate a camera calibration JSON file")
    parser.add_argument("calibration", type=Path)
    args = parser.parse_args()
    try:
        print(json.dumps(calibration_summary(args.calibration), ensure_ascii=False, indent=2))
    except (OSError, ValueError, json.JSONDecodeError) as error:
        print(f"calibration invalid: {error}")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
