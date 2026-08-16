from __future__ import annotations

import unittest

import numpy as np

from tasks.task2_support.calibration import pixel_to_camera, pixel_to_robot
from tasks.task2_support.camera_contract import CameraExtrinsics, CameraIntrinsics
from tasks.task2_support.digits import classify_digit, detect_fixed_slots, render_digit


class CameraAndVisionTests(unittest.TestCase):
    def test_fixture_classifier_handles_all_digits_and_noise(self) -> None:
        for number in (1, 2, 3, 4):
            image = render_digit(number, noise_std=4.0, seed=number)
            detected, confidence = classify_digit(image)
            self.assertEqual(detected, number)
            self.assertGreaterEqual(confidence, 0.55)

    def test_fixed_slot_detection_preserves_slot_identity(self) -> None:
        numbers = (3, 1, 4, 2)
        patches = [render_digit(number, noise_std=2.0, seed=index) for index, number in enumerate(numbers)]
        canvas = np.full((patches[0].shape[0], sum(patch.shape[1] for patch in patches)), 235, dtype=np.uint8)
        rois: dict[str, tuple[int, int, int, int]] = {}
        offset = 0
        for index, patch in enumerate(patches):
            canvas[:, offset : offset + patch.shape[1]] = patch
            rois[f"slot_{index}"] = (offset, 0, patch.shape[1], patch.shape[0])
            offset += patch.shape[1]

        detections = detect_fixed_slots(canvas, rois)
        self.assertEqual([item["number"] for item in detections], list(numbers))
        self.assertEqual([item["source_slot"] for item in detections], list(rois))

    def test_calibration_transform_uses_depth_scale_and_translation(self) -> None:
        intrinsics = CameraIntrinsics(
            width=640,
            height=480,
            fx=100.0,
            fy=100.0,
            cx=320.0,
            cy=240.0,
            depth_scale=0.001,
        )
        extrinsics = CameraExtrinsics(
            camera_to_robot=(
                (1.0, 0.0, 0.0, 0.1),
                (0.0, 1.0, 0.0, -0.2),
                (0.0, 0.0, 1.0, 0.3),
                (0.0, 0.0, 0.0, 1.0),
            )
        )
        camera_point = pixel_to_camera(320.0, 240.0, 1000.0, intrinsics)
        robot_point = pixel_to_robot(320.0, 240.0, 1000.0, intrinsics, extrinsics)
        np.testing.assert_allclose(camera_point, [0.0, 0.0, 1.0])
        np.testing.assert_allclose(robot_point, [0.1, -0.2, 1.3])


if __name__ == "__main__":
    unittest.main()
