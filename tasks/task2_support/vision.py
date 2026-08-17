from __future__ import annotations

import json
import math
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

import numpy as np

from tasks.task2_support.calibration import pixel_to_robot
from tasks.task2_support.camera_contract import CameraExtrinsics, CameraIntrinsics
from tasks.task2_support.digits import detect_fixed_slots
from tasks.task2_support.orbbec_camera import Task2CameraError, load_frame_array


class Task2VisionError(RuntimeError):
    """A task 2 image, digit, depth, or pose estimation error."""


def detect_task2_blocks(
    capture: Mapping[str, Any],
    vision_config: Mapping[str, Any],
) -> tuple[dict[str, Any], ...]:
    """Turn one captured frame into task2-compatible block observations.

    ``fixed_slot`` mode only needs the number-to-slot mapping. This is the
    recommended competition mode because the four source slots are fixed. The
    optional ``depth_robot`` mode also emits a robot-frame center and grasp
    pose, but requires a validated camera calibration and a calibrated Z offset.
    """
    if capture.get("success") is not True:
        raise Task2VisionError(str(capture.get("message", "camera capture failed")))

    rgb = _capture_array(capture, "rgb", "rgb_path")
    rois = _parse_rois(vision_config.get("slot_rois"))
    confidence_threshold = _unit_float(
        vision_config.get("digit_min_confidence", 0.80),
        "vision.digit_min_confidence",
    )
    try:
        detections = detect_fixed_slots(
            rgb,
            rois,
            min_confidence=confidence_threshold,
        )
    except (ValueError, TypeError) as error:
        raise Task2VisionError(f"digit detection failed: {error}") from error

    mode = str(vision_config.get("coordinate_mode", "fixed_slot")).strip().lower()
    if mode not in {"fixed_slot", "depth_robot"}:
        raise Task2VisionError("vision.coordinate_mode must be fixed_slot or depth_robot")
    if mode == "fixed_slot":
        return tuple(detections)

    depth = _capture_array(capture, "depth_raw", "depth_path")
    calibration = _load_calibration(capture, vision_config)
    offset_z = _finite_float(
        vision_config.get("grasp_z_offset_m"),
        "vision.grasp_z_offset_m",
    )
    orientation = _parse_orientation(vision_config.get("default_orientation"))
    depth_radius = _positive_int(
        vision_config.get("depth_sample_radius_px", 3),
        "vision.depth_sample_radius_px",
    )

    enriched: list[dict[str, Any]] = []
    for item in detections:
        roi = rois[item["source_slot"]]
        pixel = _roi_center(roi, rgb.shape[1], rgb.shape[0])
        depth_pixel = _map_pixel_to_depth(pixel, rgb.shape, depth.shape)
        depth_raw = _robust_depth_sample(depth, depth_pixel, depth_radius)
        center = pixel_to_robot(
            float(depth_pixel[0]),
            float(depth_pixel[1]),
            depth_raw,
            calibration[0],
            calibration[1],
        )
        pose = {
            "x": float(center[0]),
            "y": float(center[1]),
            "z": float(center[2] + offset_z),
            "roll": orientation[0],
            "pitch": orientation[1],
            "yaw": orientation[2],
        }
        enriched.append(
            {
                **item,
                "center": {"x": float(center[0]), "y": float(center[1]), "z": float(center[2])},
                "grasp_pose": pose,
                "pixel": {"u": float(pixel[0]), "v": float(pixel[1])},
                "depth_raw": float(depth_raw),
            }
        )
    return tuple(enriched)


def validate_slot_rois(value: object, *, image_width: int | None = None, image_height: int | None = None) -> dict[str, tuple[int, int, int, int]]:
    """Validate four fixed-slot ROIs before a real run is allowed."""
    rois = _parse_rois(value)
    if image_width is not None and image_height is not None:
        for slot, (x, y, width, height) in rois.items():
            if x + width > image_width or y + height > image_height:
                raise Task2VisionError(f"vision.slot_rois.{slot} is outside the image")
    return rois


def estimate_top_face_orientation(
    source_slot: str,
    vision_config: Mapping[str, Any],
) -> tuple[float, float, float]:
    """Return the calibrated top-face orientation for a fixed source slot.

    Task 2 blocks have identical dimensions and fixed slot orientations, so a
    calibrated per-slot orientation is more stable than trying to infer an
    angle from a small printed digit. A dynamic orientation can be added later
    without changing the task executor contract.
    """
    slot_orientations = vision_config.get("slot_orientations", {})
    if isinstance(slot_orientations, Mapping) and source_slot in slot_orientations:
        return _parse_orientation(slot_orientations[source_slot])
    return _parse_orientation(vision_config.get("default_orientation"))


def _capture_array(capture: Mapping[str, Any], key: str, path_key: str) -> np.ndarray:
    value = capture.get(key)
    if value is None:
        value = capture.get(path_key)
    try:
        array = load_frame_array(value, field_name=key)
    except Task2CameraError as error:
        raise Task2VisionError(str(error)) from error
    if array.size == 0:
        raise Task2VisionError(f"{key} is empty")
    return np.asarray(array)


def _parse_rois(value: object) -> dict[str, tuple[int, int, int, int]]:
    if not isinstance(value, Mapping):
        raise Task2VisionError("vision.slot_rois must be an object with four slots")
    rois: dict[str, tuple[int, int, int, int]] = {}
    for slot, raw in value.items():
        if not isinstance(slot, str) or not slot.strip():
            raise Task2VisionError("vision.slot_rois keys must be non-empty strings")
        if isinstance(raw, Mapping):
            values = (raw.get("x"), raw.get("y"), raw.get("width"), raw.get("height"))
        elif isinstance(raw, Sequence) and not isinstance(raw, (str, bytes)) and len(raw) == 4:
            values = tuple(raw)
        else:
            raise Task2VisionError(f"vision.slot_rois.{slot} must be [x,y,width,height]")
        try:
            x, y, width, height = (int(item) for item in values)
        except (TypeError, ValueError) as error:
            raise Task2VisionError(f"vision.slot_rois.{slot} contains a non-integer") from error
        if x < 0 or y < 0 or width <= 0 or height <= 0:
            raise Task2VisionError(f"vision.slot_rois.{slot} must be inside the image")
        rois[slot.strip()] = (x, y, width, height)
    if len(rois) != 4:
        raise Task2VisionError(f"vision.slot_rois must contain exactly 4 slots, got {len(rois)}")
    return rois


def _roi_center(roi: tuple[int, int, int, int], width: int, height: int) -> tuple[float, float]:
    x, y, roi_width, roi_height = roi
    if x + roi_width > width or y + roi_height > height:
        raise Task2VisionError("slot ROI is outside the RGB frame")
    return x + (roi_width - 1) / 2.0, y + (roi_height - 1) / 2.0


def _map_pixel_to_depth(
    pixel: tuple[float, float],
    rgb_shape: tuple[int, ...],
    depth_shape: tuple[int, ...],
) -> tuple[float, float]:
    rgb_height, rgb_width = rgb_shape[:2]
    depth_height, depth_width = depth_shape[:2]
    if rgb_width <= 0 or rgb_height <= 0 or depth_width <= 0 or depth_height <= 0:
        raise Task2VisionError("RGB/depth frame dimensions are invalid")
    if (rgb_width, rgb_height) != (depth_width, depth_height):
        raise Task2VisionError(
            "depth_robot mode requires depth aligned to RGB at the same resolution"
        )
    return pixel


def _robust_depth_sample(
    depth: np.ndarray,
    pixel: tuple[float, float],
    radius: int,
) -> float:
    height, width = depth.shape[:2]
    x = int(round(pixel[0]))
    y = int(round(pixel[1]))
    x0, x1 = max(0, x - radius), min(width, x + radius + 1)
    y0, y1 = max(0, y - radius), min(height, y + radius + 1)
    values = np.asarray(depth[y0:y1, x0:x1], dtype=np.float64).reshape(-1)
    values = values[np.isfinite(values) & (values > 0)]
    if values.size < 3:
        raise Task2VisionError("not enough valid depth samples at block center")
    low, high = np.percentile(values, [15, 85])
    trimmed = values[(values >= low) & (values <= high)]
    return float(np.median(trimmed if trimmed.size else values))


def _load_calibration(
    capture: Mapping[str, Any],
    vision_config: Mapping[str, Any],
) -> tuple[CameraIntrinsics, CameraExtrinsics]:
    raw = capture.get("calibration")
    if not isinstance(raw, Mapping) or raw.get("extrinsics") is None:
        path = vision_config.get("calibration_path") or capture.get("intrinsics_path")
        if path is None or not str(path).strip():
            raise Task2VisionError("depth_robot mode requires a calibration_path")
        try:
            file_payload = json.loads(Path(str(path)).read_text(encoding="utf-8"))
        except (OSError, ValueError) as error:
            raise Task2VisionError(f"cannot read calibration file: {path}") from error
        if not isinstance(file_payload, Mapping):
            raise Task2VisionError("calibration file root must be an object")
        merged = dict(file_payload)
        if isinstance(raw, Mapping) and raw.get("intrinsics") is not None:
            merged["intrinsics"] = raw["intrinsics"]
        raw = merged
    if not isinstance(raw, Mapping):
        raise Task2VisionError("calibration must be an object")
    try:
        intrinsics = CameraIntrinsics.from_mapping(raw.get("intrinsics"))
        extrinsics = CameraExtrinsics.from_mapping(raw.get("extrinsics"))
    except ValueError as error:
        raise Task2VisionError(f"invalid camera calibration: {error}") from error
    return intrinsics, extrinsics


def _parse_orientation(value: object) -> tuple[float, float, float]:
    if isinstance(value, Mapping):
        values = (value.get("roll"), value.get("pitch"), value.get("yaw"))
    elif isinstance(value, Sequence) and not isinstance(value, (str, bytes)) and len(value) == 3:
        values = tuple(value)
    else:
        raise Task2VisionError("vision orientation must contain roll, pitch, yaw")
    return tuple(_finite_float(item, "vision.orientation") for item in values)  # type: ignore[return-value]


def _finite_float(value: object, field_name: str) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError) as error:
        raise Task2VisionError(f"{field_name} must be a finite number") from error
    if not math.isfinite(number):
        raise Task2VisionError(f"{field_name} must be a finite number")
    return number


def _unit_float(value: object, field_name: str) -> float:
    number = _finite_float(value, field_name)
    if not 0 <= number <= 1:
        raise Task2VisionError(f"{field_name} must be between 0 and 1")
    return number


def _positive_int(value: object, field_name: str) -> int:
    try:
        number = int(value)
    except (TypeError, ValueError) as error:
        raise Task2VisionError(f"{field_name} must be a positive integer") from error
    if number <= 0:
        raise Task2VisionError(f"{field_name} must be a positive integer")
    return number
