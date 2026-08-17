from __future__ import annotations

import importlib
import re
import time
from pathlib import Path
from typing import Any, Mapping

import numpy as np


class Task2CameraError(RuntimeError):
    """A camera setup, stream, or frame conversion error for task 2."""


def capture_task2_frame(
    camera_config: Mapping[str, Any],
    task2_camera_config: Mapping[str, Any],
) -> dict[str, Any]:
    """Capture one synchronized RGB/depth frame using the official Orbbec SDK.

    The SDK is imported lazily so hardware-free tests and dry-run execution do
    not require the proprietary Windows wheel. The returned arrays are kept in
    the in-process payload for the detector; ``*_path`` values are written for
    replay and field diagnostics.
    """
    try:
        ob = importlib.import_module("pyorbbecsdk")
    except Exception as error:  # pragma: no cover - exercised on the field PC
        raise Task2CameraError(
            "pyorbbecsdk is unavailable; install the official pyorbbecsdk2 wheel"
        ) from error

    options = dict(camera_config)
    options.update(dict(task2_camera_config))
    output_dir = Path(str(options.get("capture_dir", "captures/task2")))
    output_dir.mkdir(parents=True, exist_ok=True)
    timeout_ms = _positive_int(options.get("frame_timeout_ms", 1500), "frame_timeout_ms")
    warmup_frames = _nonnegative_int(options.get("warmup_frames", 12), "warmup_frames")
    requested_serial = str(options.get("serial", "")).strip()
    requested_name = _normalize_device_name(options.get("name", options.get("device_name", "")))

    context = ob.Context()
    devices = context.query_devices()
    count = int(devices.get_count())
    if count <= 0:
        raise Task2CameraError("no Orbbec camera was detected")

    device_index = _select_device(devices, count, requested_serial, requested_name)
    device = devices.get_device_by_index(device_index)
    pipeline = ob.Pipeline(device)
    config = ob.Config()
    align_filter = None
    try:
        _enable_streams(ob, pipeline, config)
        _try_enable_frame_sync(pipeline)
        pipeline.start(config)
        align_filter = _build_align_filter(ob, options)
        for _ in range(warmup_frames):
            pipeline.wait_for_frames(timeout_ms)

        frames = None
        color_frame = None
        depth_frame = None
        for _ in range(3):
            frames = pipeline.wait_for_frames(timeout_ms)
            if frames is None:
                continue
            if align_filter is not None:
                frames = align_filter.process(frames)
                if frames is None:
                    continue
            color_frame = frames.get_color_frame()
            depth_frame = frames.get_depth_frame()
            if color_frame is not None and depth_frame is not None:
                break
        if color_frame is None or depth_frame is None:
            raise Task2CameraError("RGB/depth synchronized frames were not received")

        rgb = _color_frame_to_rgb(color_frame, ob)
        depth_raw = _depth_frame_to_array(depth_frame)
        depth_scale_m = float(depth_frame.get_depth_scale()) / 1000.0
        if not np.isfinite(depth_scale_m) or depth_scale_m <= 0:
            raise Task2CameraError(f"invalid depth scale from SDK: {depth_scale_m!r}")

        calibration = _camera_calibration(pipeline, depth_scale_m)
        configured_extrinsics = options.get("camera_to_robot")
        if configured_extrinsics is not None:
            calibration["extrinsics"] = {"camera_to_robot": configured_extrinsics}
        timestamp = time.time()
        stem = f"task2_{time.strftime('%Y%m%d_%H%M%S')}_{time.time_ns() % 1_000_000:06d}"
        rgb_path = output_dir / f"{stem}_rgb.npy"
        depth_path = output_dir / f"{stem}_depth.npy"
        np.save(rgb_path, rgb)
        np.save(depth_path, depth_raw)

        calibration_path = _write_calibration_if_configured(
            options.get("calibration_path"), calibration
        )
        return {
            "success": True,
            "message": "frame captured",
            "timestamp": timestamp,
            "sdk_timestamp_ms": _frame_timestamp(color_frame),
            "rgb_path": str(rgb_path),
            "depth_path": str(depth_path),
            "intrinsics_path": calibration_path,
            "extrinsics_path": calibration_path if "extrinsics" in calibration else None,
            "depth_scale_m": depth_scale_m,
            "rgb": rgb,
            "depth_raw": depth_raw,
            "calibration": calibration,
        }
    except Task2CameraError:
        raise
    except Exception as error:
        raise Task2CameraError(f"Orbbec capture failed: {type(error).__name__}: {error}") from error
    finally:
        try:
            pipeline.stop()
        except Exception:
            pass


def load_frame_array(value: object, *, field_name: str) -> np.ndarray:
    """Load an ``.npy`` array or an optional image file for offline replay."""
    if isinstance(value, np.ndarray):
        return value
    if not isinstance(value, (str, Path)) or not str(value).strip():
        raise Task2CameraError(f"{field_name} must be an ndarray or file path")
    path = Path(value)
    if path.suffix.lower() == ".npy":
        try:
            return np.load(path, allow_pickle=False)
        except Exception as error:
            raise Task2CameraError(f"cannot load {field_name}: {path}") from error

    try:
        from PIL import Image
    except Exception as error:
        raise Task2CameraError(
            f"{field_name} is an image; install Pillow or provide an .npy replay file"
        ) from error
    try:
        with Image.open(path) as image:
            return np.asarray(image.convert("RGB"))
    except Exception as error:
        raise Task2CameraError(f"cannot decode {field_name}: {path}") from error


def _enable_streams(ob: Any, pipeline: Any, config: Any) -> None:
    color_profiles = pipeline.get_stream_profile_list(ob.OBSensorType.COLOR_SENSOR)
    depth_profiles = pipeline.get_stream_profile_list(ob.OBSensorType.DEPTH_SENSOR)
    if color_profiles is None or depth_profiles is None:
        raise Task2CameraError("Gemini335 does not expose both color and depth streams")

    color_profile = None
    try:
        color_profile = color_profiles.get_video_stream_profile(0, 0, ob.OBFormat.RGB, 0)
    except Exception:
        color_profile = color_profiles.get_default_video_stream_profile()
    depth_profile = depth_profiles.get_default_video_stream_profile()
    if color_profile is None or depth_profile is None:
        raise Task2CameraError("no usable RGB/depth stream profile was found")
    config.enable_stream(color_profile)
    config.enable_stream(depth_profile)
    aggregate_mode = getattr(ob, "OBFrameAggregateOutputMode", None)
    if aggregate_mode is not None:
        full_frame = getattr(aggregate_mode, "FULL_FRAME_REQUIRE", None)
        if full_frame is not None and hasattr(config, "set_frame_aggregate_output_mode"):
            config.set_frame_aggregate_output_mode(full_frame)


def _try_enable_frame_sync(pipeline: Any) -> None:
    enable = getattr(pipeline, "enable_frame_sync", None)
    if enable is None:
        return
    try:
        enable()
    except Exception:
        # Some firmware revisions do not expose hardware sync. The frame set
        # still has to be checked for both streams before accepting it.
        pass


def _build_align_filter(ob: Any, options: Mapping[str, Any]) -> Any | None:
    if not bool(options.get("align_depth_to_color", True)):
        return None
    align_cls = getattr(ob, "AlignFilter", None)
    stream_type = getattr(ob, "OBStreamType", None)
    color_stream = getattr(stream_type, "COLOR_STREAM", None) if stream_type is not None else None
    if align_cls is None or color_stream is None:
        raise Task2CameraError("SDK does not provide depth-to-color alignment")
    return align_cls(align_to_stream=color_stream)


def _select_device(devices: Any, count: int, serial: str, name: str) -> int:
    if not serial and not name:
        if count == 1:
            return 0
        raise Task2CameraError("multiple Orbbec cameras found; configure camera serial")

    matches: list[int] = []
    for index in range(count):
        device = devices.get_device_by_index(index)
        info = device.get_device_info()
        device_serial = str(info.get_serial_number()).strip()
        device_name = _normalize_device_name(info.get_name())
        if serial and device_serial == serial:
            matches.append(index)
        elif not serial and name and name in device_name:
            matches.append(index)
    if len(matches) != 1:
        raise Task2CameraError(
            f"camera selection matched {len(matches)} devices; configure an exact serial"
        )
    return matches[0]


def _normalize_device_name(value: object) -> str:
    return re.sub(r"[^a-z0-9]+", "", str(value).strip().lower())


def _color_frame_to_rgb(frame: Any, ob: Any) -> np.ndarray:
    width = int(frame.get_width())
    height = int(frame.get_height())
    raw = np.asanyarray(frame.get_data())
    frame_format = getattr(frame, "get_format", lambda: "unknown")()
    format_name = str(getattr(frame_format, "name", frame_format)).upper()
    if "RGB" in format_name and "MJPG" not in format_name:
        data = np.asarray(raw, dtype=np.uint8).reshape(height, width, 3)
        return data.copy()
    if "BGR" in format_name:
        data = np.asarray(raw, dtype=np.uint8).reshape(height, width, 3)
        return data[..., ::-1].copy()
    if "MJPG" in format_name or "JPEG" in format_name:
        try:
            from io import BytesIO
            from PIL import Image

            with Image.open(BytesIO(np.asarray(raw, dtype=np.uint8).tobytes())) as image:
                return np.asarray(image.convert("RGB"))
        except Exception as error:
            raise Task2CameraError("MJPG color frame requires Pillow for decoding") from error
    raise Task2CameraError(
        f"unsupported color frame format {format_name}; request RGB or install a decoder"
    )


def _depth_frame_to_array(frame: Any) -> np.ndarray:
    width = int(frame.get_width())
    height = int(frame.get_height())
    expected = width * height
    data = np.frombuffer(frame.get_data(), dtype=np.uint16).reshape(-1)
    if data.size != expected:
        raise Task2CameraError(
            f"depth frame size mismatch: expected {expected}, received {data.size}"
        )
    return data.reshape(height, width).copy()


def _camera_calibration(pipeline: Any, depth_scale_m: float) -> dict[str, Any]:
    params = pipeline.get_camera_param()
    # The depth frame is aligned to the RGB image before detection, so use the
    # RGB intrinsics for RGB-pixel back-projection.
    depth = params.rgb_intrinsic
    distortion = params.rgb_distortion
    return {
        "intrinsics": {
            "width": int(depth.width),
            "height": int(depth.height),
            "fx": float(depth.fx),
            "fy": float(depth.fy),
            "cx": float(depth.cx),
            "cy": float(depth.cy),
            "depth_scale": depth_scale_m,
            "distortion": [
                float(distortion.k1),
                float(distortion.k2),
                float(distortion.p1),
                float(distortion.p2),
                float(distortion.k3),
            ],
        }
    }


def _write_calibration_if_configured(path_value: object, payload: Mapping[str, Any]) -> str | None:
    if path_value is None or not str(path_value).strip():
        return None
    path = Path(str(path_value))
    path.parent.mkdir(parents=True, exist_ok=True)
    import json

    merged: dict[str, Any] = {}
    if path.exists():
        try:
            existing = json.loads(path.read_text(encoding="utf-8"))
            if isinstance(existing, dict):
                merged.update(existing)
        except (OSError, ValueError):
            raise Task2CameraError(f"calibration file is not valid JSON: {path}")
    for key, value in payload.items():
        merged[key] = value
    path.write_text(json.dumps(merged, ensure_ascii=False, indent=2), encoding="utf-8")
    return str(path)


def _frame_timestamp(frame: Any) -> float | None:
    try:
        return float(frame.get_timestamp())
    except Exception:
        return None


def _positive_int(value: object, field_name: str) -> int:
    try:
        number = int(value)
    except (TypeError, ValueError) as error:
        raise Task2CameraError(f"{field_name} must be a positive integer") from error
    if number <= 0:
        raise Task2CameraError(f"{field_name} must be a positive integer")
    return number


def _nonnegative_int(value: object, field_name: str) -> int:
    try:
        number = int(value)
    except (TypeError, ValueError) as error:
        raise Task2CameraError(f"{field_name} must be a non-negative integer") from error
    if number < 0:
        raise Task2CameraError(f"{field_name} must be a non-negative integer")
    return number
