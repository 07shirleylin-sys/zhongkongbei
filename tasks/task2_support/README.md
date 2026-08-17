# Task 2 camera, calibration, and offline vision

All files in this directory belong to task 2. The shared `hardware/` clients
and the other task entry points are intentionally not modified by this support
package.

## SDK choice

Use the official Orbbec SDK v2 Python binding for the Gemini 335 family. The
distribution is `pyorbbecsdk2`; the import name is `pyorbbecsdk`.

Official resources:

- SDK downloads: https://www.orbbec.com/developers/orbbec-sdk/
- Python binding: https://github.com/orbbec/pyorbbecsdk
- Gemini 330 installation guide: https://doc.orbbec.com/documentation/Orbbec%20Gemini%20330%20Series%20Documentation/Install%20Orbbec%20SDK

Prepare the wheel/installer and documentation on a USB drive before arriving
on site. Do not commit the SDK binary into this repository.

For a prepared Python environment, the upstream quick start is:

```text
python -m venv .venv
python -m pip install --upgrade pyorbbecsdk2
python tasks/task2_support/check_camera_sdk.py
```

The final command should be run on the competition computer after the SDK and
its OS-level setup have been installed. `tasks/task2_support/check_camera_sdk.py --allow-missing`
is suitable for this hardware-free development machine.

## Camera frame contract

`CameraClient.capture()` must return a JSON-compatible object with this shape:

```json
{
  "success": true,
  "message": "frame captured",
  "timestamp": 0.0,
  "rgb_path": "captures/task2_rgb.png",
  "depth_path": "captures/task2_depth.npy",
  "intrinsics_path": "calibration/camera_intrinsics.json",
  "extrinsics_path": "calibration/camera_to_robot.json"
}
```

The task-specific detector adds a `blocks` array. Each item contains
an integer `number` in 1..4, a unique `source_slot`, a confidence in 0..1, and
optionally a robot-frame `center` or complete `grasp_pose`.

`tasks/task2_blocks.py` now invokes the task-2-only Orbbec adapter in
`orbbec_camera.py`, passes the synchronized frame to `vision.py`, and then
feeds the resulting `blocks` into the existing motion planner. The shared
`hardware/camera_client.py` and the other two task entry points are untouched.

`fixed_slot` is the recommended competition mode. It recognizes which number
is in each fixed ROI, then uses the calibrated `source_slots.*.grasp_pose`.
`depth_robot` is optional and may only be enabled after a complete
camera-to-robot calibration has been validated.

## Calibration file and transform

Use `tasks/task2_support/calibration.py` to validate a JSON file containing:

```json
{
  "intrinsics": {
    "width": 1280,
    "height": 800,
    "fx": 0.0,
    "fy": 0.0,
    "cx": 0.0,
    "cy": 0.0,
    "depth_scale": 0.001,
    "distortion": []
  },
  "extrinsics": {
    "camera_to_robot": [
      [1, 0, 0, 0],
      [0, 1, 0, 0],
      [0, 0, 1, 0],
      [0, 0, 0, 1]
    ]
  }
}
```

The values above are schema placeholders only and must never be used on the
real robot. On site:

1. Capture the SDK-reported RGB/depth intrinsics and depth scale.
2. Capture a rigid calibration board at multiple end-effector poses.
3. Solve and validate the camera-to-robot transform.
4. Confirm the transform with a known board point before enabling grasp motion.
5. Save the real calibration outside the source tree or in the agreed private
   deployment directory.

## Offline tests

The task 2 tests use NumPy-only synthetic digits and fake camera/robot clients.
They verify fixed-slot recognition, depth coordinate math, all 24 number
permutations, the four-block executor, workspace rejection, duplicate-call
locking, and the Orbbec SDK contract. They do not claim to replace the final
physical camera and robot validation.

```text
python -B -m unittest tasks.task2_support.test_support tasks.task2_support.test_executor tasks.task2_support.test_orbbec_camera -v
```

## Field checklist

Chinese final acceptance steps and the ten required task metrics are maintained in
`tasks/task2_support/FIELD_FINAL_CHECKLIST_CN.md`.

```text
[ ] SDK installer/wheel and viewer copied to USB
[ ] SDK imports successfully
[ ] RGB and depth frames are synchronized
[ ] Depth scale and intrinsics saved
[ ] Camera-to-robot transform validated on a board point
[ ] Four slot ROIs captured and checked
[ ] One block grasp tested at low velocity
[ ] Full 1 -> 2 -> 3 -> 4 run tested
```
