from __future__ import annotations

import json
import tempfile
import unittest
from enum import Enum
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import numpy as np

from tasks.task2_support.orbbec_camera import capture_task2_frame


class _Format(Enum):
    RGB = 1


class _Sensor:
    COLOR_SENSOR = 1
    DEPTH_SENSOR = 2


class _FrameMode:
    FULL_FRAME_REQUIRE = 1


class _StreamType:
    COLOR_STREAM = 1


class _Profile:
    pass


class _ProfileList:
    def get_video_stream_profile(self, *_args: object) -> _Profile:
        return _Profile()

    def get_default_video_stream_profile(self) -> _Profile:
        return _Profile()


class _Config:
    def enable_stream(self, _profile: object) -> None:
        pass

    def set_frame_aggregate_output_mode(self, _mode: object) -> None:
        pass


class _Info:
    def get_serial_number(self) -> str:
        return "TEST-335"

    def get_name(self) -> str:
        return "Orbbec Gemini 335"


class _Device:
    def get_device_info(self) -> _Info:
        return _Info()


class _Devices:
    def get_count(self) -> int:
        return 1

    def get_device_by_index(self, _index: int) -> _Device:
        return _Device()


class _Context:
    def query_devices(self) -> _Devices:
        return _Devices()


class _ColorFrame:
    def __init__(self) -> None:
        self.array = np.arange(4 * 6 * 3, dtype=np.uint8).reshape(4, 6, 3)

    def get_width(self) -> int:
        return 6

    def get_height(self) -> int:
        return 4

    def get_data(self) -> memoryview:
        return memoryview(self.array.tobytes())

    def get_format(self) -> _Format:
        return _Format.RGB

    def get_timestamp(self) -> float:
        return 1234.0


class _DepthFrame:
    def __init__(self) -> None:
        self.array = np.full((4, 6), 1000, dtype=np.uint16)

    def get_width(self) -> int:
        return 6

    def get_height(self) -> int:
        return 4

    def get_data(self) -> memoryview:
        return memoryview(self.array.tobytes())

    def get_depth_scale(self) -> float:
        return 1.0


class _Frames:
    def get_color_frame(self) -> _ColorFrame:
        return _ColorFrame()

    def get_depth_frame(self) -> _DepthFrame:
        return _DepthFrame()


class _AlignFilter:
    def __init__(self, **_kwargs: object) -> None:
        pass

    def process(self, frames: _Frames) -> _Frames:
        return frames


class _Pipeline:
    last_instance: "_Pipeline | None" = None

    def __init__(self, _device: object) -> None:
        self.stopped = False
        _Pipeline.last_instance = self

    def get_stream_profile_list(self, _sensor: object) -> _ProfileList:
        return _ProfileList()

    def enable_frame_sync(self) -> None:
        pass

    def start(self, _config: object) -> None:
        pass

    def stop(self) -> None:
        self.stopped = True

    def wait_for_frames(self, _timeout: int) -> _Frames:
        return _Frames()

    def get_camera_param(self) -> SimpleNamespace:
        intrinsic = SimpleNamespace(width=6, height=4, fx=100.0, fy=100.0, cx=3.0, cy=2.0)
        distortion = SimpleNamespace(k1=0.0, k2=0.0, p1=0.0, p2=0.0, k3=0.0)
        return SimpleNamespace(rgb_intrinsic=intrinsic, rgb_distortion=distortion)


class OrbbecCaptureTests(unittest.TestCase):
    def test_capture_uses_sdk_contract_and_writes_replay_arrays(self) -> None:
        fake_sdk = SimpleNamespace(
            Context=_Context,
            Pipeline=_Pipeline,
            Config=_Config,
            OBSensorType=_Sensor,
            OBFormat=_Format,
            OBFrameAggregateOutputMode=_FrameMode,
            OBStreamType=_StreamType,
            AlignFilter=_AlignFilter,
        )
        with tempfile.TemporaryDirectory() as directory:
            calibration_path = Path(directory) / "calibration.json"
            calibration_path.write_text(
                json.dumps(
                    {
                        "extrinsics": {
                            "camera_to_robot": [
                                [1, 0, 0, 0],
                                [0, 1, 0, 0],
                                [0, 0, 1, 0],
                                [0, 0, 0, 1],
                            ]
                        }
                    }
                ),
                encoding="utf-8",
            )
            with patch("tasks.task2_support.orbbec_camera.importlib.import_module", return_value=fake_sdk):
                capture = capture_task2_frame(
                    {"name": "Gemini335"},
                    {
                        "capture_dir": directory,
                        "calibration_path": str(calibration_path),
                        "warmup_frames": 0,
                        "frame_timeout_ms": 100,
                    },
                )

            self.assertTrue(capture["success"])
            self.assertEqual(capture["rgb"].shape, (4, 6, 3))
            self.assertEqual(capture["depth_raw"].shape, (4, 6))
            self.assertAlmostEqual(capture["depth_scale_m"], 0.001)
            self.assertTrue(Path(capture["rgb_path"]).exists())
            self.assertTrue(Path(capture["depth_path"]).exists())
            saved = json.loads(calibration_path.read_text(encoding="utf-8"))
            self.assertIn("intrinsics", saved)
            self.assertIn("extrinsics", saved)
            self.assertTrue(_Pipeline.last_instance and _Pipeline.last_instance.stopped)


if __name__ == "__main__":
    unittest.main()
