from __future__ import annotations

import math
import threading
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, replace
from typing import Any

from app.context import RuntimeContext
from tasks.task2_support.orbbec_camera import capture_task2_frame
from tasks.task2_support.vision import Task2VisionError, detect_task2_blocks, validate_slot_rois


TASK_NAME = "task2"
EXPECTED_NUMBERS = (1, 2, 3, 4)
DEFAULT_ORIENTATION = (-3.141, -1.552, 3.141)
_TASK2_LOCK = threading.Lock()


class Task2Error(RuntimeError):
    """A validation or execution error that can be reported to the contest server."""


@dataclass(frozen=True)
class Pose:
    x: float
    y: float
    z: float
    roll: float
    pitch: float
    yaw: float

    @classmethod
    def from_mapping(
        cls,
        value: object,
        field_name: str,
        *,
        fallback_orientation: tuple[float, float, float] | None = None,
    ) -> "Pose":
        if not isinstance(value, Mapping):
            raise Task2Error(f"{field_name} must be an object")

        fallback = fallback_orientation or DEFAULT_ORIENTATION
        return cls(
            x=_finite_float(value.get("x"), f"{field_name}.x"),
            y=_finite_float(value.get("y"), f"{field_name}.y"),
            z=_finite_float(value.get("z"), f"{field_name}.z"),
            roll=_finite_float(value.get("roll", fallback[0]), f"{field_name}.roll"),
            pitch=_finite_float(value.get("pitch", fallback[1]), f"{field_name}.pitch"),
            yaw=_finite_float(value.get("yaw", fallback[2]), f"{field_name}.yaw"),
        )

    @property
    def orientation(self) -> tuple[float, float, float]:
        return self.roll, self.pitch, self.yaw

    def raised(self, height: float) -> "Pose":
        return replace(self, z=self.z + height)

    def with_orientation(self, orientation: tuple[float, float, float]) -> "Pose":
        return replace(self, roll=orientation[0], pitch=orientation[1], yaw=orientation[2])

    def as_dict(self) -> dict[str, float]:
        return {
            "x": self.x,
            "y": self.y,
            "z": self.z,
            "roll": self.roll,
            "pitch": self.pitch,
            "yaw": self.yaw,
        }


@dataclass(frozen=True)
class BlockObservation:
    number: int
    source_slot: str
    confidence: float
    center: tuple[float, float, float] | None = None
    grasp_pose: Pose | None = None


@dataclass(frozen=True)
class TransferPlan:
    number: int
    source_slot: str
    pre_grasp: Pose
    grasp: Pose
    lift: Pose
    pre_place: Pose
    place: Pose
    retreat: Pose


@dataclass(frozen=True)
class Task2Settings:
    photo_pose: Pose
    safe_home: Pose
    source_slots: Mapping[str, object]
    drop_points: tuple[object, ...]
    safe_velocity: float
    normal_velocity: float
    approach_height: float
    lift_height: float
    min_confidence: float
    camera_config: Mapping[str, object]
    vision_config: Mapping[str, object]
    workspace: Mapping[str, object]
    grip_pose_name: str
    drop_min_spacing: float


def run_task2(ctx: RuntimeContext) -> tuple[bool, str]:
    """识别数字 1-4 长方体，并严格按照 1 -> 2 -> 3 -> 4 转运。"""
    if not _TASK2_LOCK.acquire(blocking=False):
        return False, "task2 is already running"
    settings: Task2Settings | None = None
    motion_started = False

    try:
        ctx.log(TASK_NAME, "started", dry_run=ctx.dry_run)
        settings = _load_settings(ctx)
        _preflight(ctx, settings)
        if not ctx.dry_run:
            _plan_arm_pose(ctx, "plan photo pose", settings.photo_pose, settings.safe_velocity)
        motion_started = True
        _move_arm(ctx, "move to photo pose", settings.photo_pose, settings.normal_velocity, linear=False)

        capture = _checked_call(
            ctx,
            "capture image",
            lambda: _capture_and_detect(ctx, settings),
        )
        observations = _read_observations(ctx, capture, settings.min_confidence)
        plans = build_transfer_plans(observations, settings)

        ctx.log(
            TASK_NAME,
            "transfer plan ready",
            order=[plan.number for plan in plans],
            slots=[plan.source_slot for plan in plans],
        )

        _move_arm(ctx, "move to safe home", settings.safe_home, settings.normal_velocity, linear=False)
        for plan in plans:
            _execute_transfer(ctx, plan, settings)

        ctx.log(TASK_NAME, "finished", success=True, transferred=list(EXPECTED_NUMBERS))
        message = "task2 dry-run ok" if ctx.dry_run else "task2 ok"
        return True, message
    except Task2Error as error:
        if settings is not None and motion_started and not ctx.dry_run:
            _recover_to_safe_home(ctx, settings)
        ctx.log(TASK_NAME, "failed", success=False, error=str(error))
        return False, str(error)
    except Exception as error:
        message = f"unexpected {type(error).__name__}: {error}"
        if settings is not None and motion_started and not ctx.dry_run:
            _recover_to_safe_home(ctx, settings)
        ctx.log(TASK_NAME, "failed", success=False, error=message)
        return False, message
    finally:
        _TASK2_LOCK.release()


def _capture_and_detect(ctx: RuntimeContext, settings: Task2Settings) -> Mapping[str, Any]:
    if ctx.dry_run:
        return ctx.camera.capture()
    try:
        capture = capture_task2_frame(ctx.camera.config, settings.camera_config)
        blocks = detect_task2_blocks(capture, settings.vision_config)
    except (Task2VisionError, RuntimeError) as error:
        raise Task2Error(str(error)) from error
    return {**capture, "blocks": list(blocks)}


def _recover_to_safe_home(ctx: RuntimeContext, settings: Task2Settings) -> None:
    """Best-effort recovery after a motion-stage failure; never masks the cause."""
    try:
        status = ctx.arm.status()
        if isinstance(status, Mapping) and status.get("moving") is True:
            ctx.log(TASK_NAME, "recovery deferred", reason="arm still moving")
            return
        _move_arm(
            ctx,
            "recover to safe home",
            settings.safe_home,
            settings.safe_velocity,
            linear=False,
        )
        ctx.log(TASK_NAME, "recovery finished", success=True)
    except Exception as error:
        ctx.log(TASK_NAME, "recovery failed", success=False, error=str(error))


def validate_and_sort_observations(
    raw_blocks: object,
    *,
    min_confidence: float,
) -> tuple[BlockObservation, ...]:
    """Validate camera output and return the four blocks in contest order."""
    if isinstance(raw_blocks, (str, bytes)) or not isinstance(raw_blocks, Sequence):
        raise Task2Error("camera blocks must be an array")

    observations = tuple(_parse_observation(item, index) for index, item in enumerate(raw_blocks))
    if len(observations) != len(EXPECTED_NUMBERS):
        raise Task2Error(f"expected 4 blocks, detected {len(observations)}")

    numbers = [item.number for item in observations]
    if set(numbers) != set(EXPECTED_NUMBERS) or len(set(numbers)) != len(numbers):
        raise Task2Error(f"detected numbers must be exactly [1, 2, 3, 4], got {numbers}")

    slots = [item.source_slot for item in observations]
    if len(set(slots)) != len(slots):
        raise Task2Error(f"each block must use a different source slot, got {slots}")

    low_confidence = [item.number for item in observations if item.confidence < min_confidence]
    if low_confidence:
        raise Task2Error(
            f"low-confidence number detection for {low_confidence}; threshold={min_confidence:.2f}"
        )

    return tuple(sorted(observations, key=lambda item: item.number))


def build_transfer_plans(
    observations: Sequence[BlockObservation],
    settings: Task2Settings,
) -> tuple[TransferPlan, ...]:
    """Build deterministic pick-and-place plans without touching hardware."""
    if tuple(item.number for item in observations) != EXPECTED_NUMBERS:
        raise Task2Error("observations must be validated and sorted before planning")
    if len(settings.drop_points) < len(EXPECTED_NUMBERS):
        raise Task2Error("task2.place_area.drop_points must contain at least 4 poses")

    _validate_pose_in_workspace(settings.safe_home, "motion.safe_home", settings.workspace)
    _validate_pose_in_workspace(settings.photo_pose, "tasks.task2.photo_pose", settings.workspace)

    place_poses = tuple(
        Pose.from_mapping(
            settings.drop_points[index],
            f"tasks.task2.place_area.drop_points[{index}]",
        )
        for index in range(len(EXPECTED_NUMBERS))
    )
    _validate_drop_spacing(place_poses, settings.drop_min_spacing)

    plans: list[TransferPlan] = []
    for index, observation in enumerate(observations):
        grasp = _resolve_grasp_pose(observation, settings)
        place = place_poses[index].with_orientation(grasp.orientation)

        plan = TransferPlan(
            number=observation.number,
            source_slot=observation.source_slot,
            pre_grasp=grasp.raised(settings.approach_height),
            grasp=grasp,
            lift=grasp.raised(settings.lift_height),
            pre_place=place.raised(settings.approach_height),
            place=place,
            retreat=place.raised(settings.lift_height),
        )
        for name in ("pre_grasp", "grasp", "lift", "pre_place", "place", "retreat"):
            _validate_pose_in_workspace(
                getattr(plan, name),
                f"task2.block_{observation.number}.{name}",
                settings.workspace,
            )
        plans.append(plan)
    return tuple(plans)


def _validate_drop_spacing(place_poses: Sequence[Pose], minimum_spacing: float) -> None:
    for left_index, left in enumerate(place_poses):
        for right_index in range(left_index + 1, len(place_poses)):
            right = place_poses[right_index]
            distance = math.hypot(left.x - right.x, left.y - right.y)
            if distance < minimum_spacing:
                raise Task2Error(
                    "tasks.task2.place_area.drop_points "
                    f"[{left_index}] and [{right_index}] are only {distance:.4f} m apart; "
                    f"minimum is {minimum_spacing:.4f} m"
                )


def _load_settings(ctx: RuntimeContext) -> Task2Settings:
    tasks = ctx.config.get("tasks")
    if not isinstance(tasks, Mapping):
        raise Task2Error("config.tasks must be an object")
    task_config = tasks.get("task2")
    if not isinstance(task_config, Mapping):
        raise Task2Error("config.tasks.task2 must be an object")

    motion = ctx.config.get("motion")
    if not isinstance(motion, Mapping):
        raise Task2Error("config.motion must be an object")

    camera_config = task_config.get("camera", {})
    if not isinstance(camera_config, Mapping):
        raise Task2Error("tasks.task2.camera must be an object")
    vision_config = task_config.get("vision", {})
    if not isinstance(vision_config, Mapping):
        raise Task2Error("tasks.task2.vision must be an object")
    workspace = task_config.get("workspace", {})
    if not isinstance(workspace, Mapping):
        raise Task2Error("tasks.task2.workspace must be an object")

    safe_home = Pose.from_mapping(motion.get("safe_home"), "motion.safe_home")
    safe_velocity = _positive_float(motion.get("safe_velocity", 0.08), "motion.safe_velocity")
    normal_velocity = _positive_float(motion.get("normal_velocity", 0.12), "motion.normal_velocity")
    if safe_velocity > 0.3 or normal_velocity > 0.3:
        raise Task2Error("task2 velocity scaling must not exceed 0.3")

    approach_value = task_config.get("approach_height_m")
    lift_value = task_config.get("lift_height_m")
    if approach_value is None:
        if not ctx.dry_run:
            raise Task2Error("tasks.task2.approach_height_m is not configured")
        approach_value = 0.05
    if lift_value is None:
        if not ctx.dry_run:
            raise Task2Error("tasks.task2.lift_height_m is not configured")
        lift_value = 0.06
    approach_height = _positive_float(
        approach_value,
        "tasks.task2.approach_height_m",
    )
    lift_height = _positive_float(
        lift_value,
        "tasks.task2.lift_height_m",
    )
    if lift_height < approach_height:
        raise Task2Error("tasks.task2.lift_height_m must be >= approach_height_m")

    min_confidence = _unit_float(
        task_config.get("min_confidence", 0.80),
        "tasks.task2.min_confidence",
    )
    grip_pose_name = str(task_config.get("grip_pose_name", "box_grip")).strip()
    if not grip_pose_name:
        raise Task2Error("tasks.task2.grip_pose_name must be a non-empty string")

    photo_pose_raw = task_config.get("photo_pose")
    if photo_pose_raw is None:
        if not ctx.dry_run:
            raise Task2Error("tasks.task2.photo_pose is not configured")
        photo_pose = safe_home
    else:
        photo_pose = Pose.from_mapping(
            photo_pose_raw,
            "tasks.task2.photo_pose",
            fallback_orientation=safe_home.orientation,
        )

    source_slots = task_config.get("source_slots")
    if not isinstance(source_slots, Mapping) or not source_slots:
        if not ctx.dry_run:
            raise Task2Error("tasks.task2.source_slots is not configured")
        source_slots = _simulation_source_slots(safe_home.orientation)

    place_area = task_config.get("place_area")
    drop_points: object = None
    if isinstance(place_area, Mapping):
        drop_points = place_area.get("drop_points")
    if isinstance(drop_points, (str, bytes)) or not isinstance(drop_points, Sequence) or not drop_points:
        if not ctx.dry_run:
            raise Task2Error("tasks.task2.place_area.drop_points is not configured")
        drop_points = _simulation_drop_points(safe_home.orientation)
    spacing_value = place_area.get("min_spacing_m") if isinstance(place_area, Mapping) else None
    if spacing_value is None:
        if not ctx.dry_run:
            raise Task2Error("tasks.task2.place_area.min_spacing_m is not configured")
        spacing_value = 0.03
    drop_min_spacing = _positive_float(spacing_value, "tasks.task2.place_area.min_spacing_m")

    if not ctx.dry_run:
        _validate_real_task2_config(
            camera_config=camera_config,
            vision_config=vision_config,
            workspace=workspace,
            source_slots=source_slots,
            drop_points=drop_points,
        )

    return Task2Settings(
        photo_pose=photo_pose,
        safe_home=safe_home,
        source_slots=source_slots,
        drop_points=tuple(drop_points),
        safe_velocity=safe_velocity,
        normal_velocity=normal_velocity,
        approach_height=approach_height,
        lift_height=lift_height,
        min_confidence=min_confidence,
        camera_config=camera_config,
        vision_config=vision_config,
        workspace=workspace,
        grip_pose_name=grip_pose_name,
        drop_min_spacing=drop_min_spacing,
    )


def _validate_real_task2_config(
    *,
    camera_config: Mapping[str, object],
    vision_config: Mapping[str, object],
    workspace: Mapping[str, object],
    source_slots: object,
    drop_points: object,
) -> None:
    try:
        rois = validate_slot_rois(vision_config.get("slot_rois"))
    except Task2VisionError as error:
        raise Task2Error(str(error)) from error

    mode = str(vision_config.get("coordinate_mode", "fixed_slot")).strip().lower()
    if mode not in {"fixed_slot", "depth_robot"}:
        raise Task2Error("tasks.task2.vision.coordinate_mode is invalid")
    if mode == "depth_robot":
        calibration_path = vision_config.get("calibration_path") or camera_config.get("calibration_path")
        if not str(calibration_path or "").strip():
            raise Task2Error("depth_robot mode requires a task2 calibration_path")
        _finite_float(
            vision_config.get("grasp_z_offset_m"),
            "tasks.task2.vision.grasp_z_offset_m",
        )
        try:
            _parse_orientation_config(vision_config.get("default_orientation"))
        except Task2Error:
            raise

    if not camera_config.get("name") and not camera_config.get("device_name"):
        raise Task2Error("tasks.task2.camera.name must identify Gemini335")
    if not str(camera_config.get("serial", "")).strip():
        raise Task2Error("tasks.task2.camera.serial must be the exact field camera serial")
    if not isinstance(source_slots, Mapping) or len(source_slots) != 4:
        raise Task2Error("tasks.task2.source_slots must contain exactly 4 slots")
    if set(source_slots) != set(rois):
        raise Task2Error("source_slots and vision.slot_rois must use the same four names")
    for slot, value in source_slots.items():
        if not isinstance(slot, str) or not slot.strip():
            raise Task2Error("tasks.task2.source_slots keys must be non-empty strings")
        if not isinstance(value, Mapping):
            raise Task2Error(f"tasks.task2.source_slots.{slot} must be an object")
        Pose.from_mapping(
            value.get("grasp_pose", value),
            f"tasks.task2.source_slots.{slot}.grasp_pose",
        )
    if isinstance(drop_points, (str, bytes)) or not isinstance(drop_points, Sequence):
        raise Task2Error("tasks.task2.place_area.drop_points must be an array")
    if len(drop_points) != 4:
        raise Task2Error("tasks.task2.place_area.drop_points must contain exactly 4 poses")
    for index, value in enumerate(drop_points):
        Pose.from_mapping(value, f"tasks.task2.place_area.drop_points[{index}]")
    _validate_workspace_config(workspace)


def _validate_workspace_config(workspace: Mapping[str, object]) -> None:
    bounds = workspace.get("bounds")
    if not isinstance(bounds, Mapping):
        raise Task2Error("tasks.task2.workspace.bounds is not configured")
    for axis in ("x", "y", "z"):
        value = bounds.get(axis)
        if isinstance(value, (str, bytes)) or not isinstance(value, Sequence) or len(value) != 2:
            raise Task2Error(f"tasks.task2.workspace.bounds.{axis} must be [min,max]")
        low = _finite_float(value[0], f"workspace.bounds.{axis}[0]")
        high = _finite_float(value[1], f"workspace.bounds.{axis}[1]")
        if not low < high:
            raise Task2Error(f"tasks.task2.workspace.bounds.{axis} must be increasing")
    margin = _finite_float(workspace.get("safety_margin_m", 0.0), "workspace.safety_margin_m")
    if margin < 0:
        raise Task2Error("tasks.task2.workspace.safety_margin_m must be non-negative")


def _validate_pose_in_workspace(
    pose: Pose,
    field_name: str,
    workspace: Mapping[str, object],
) -> None:
    bounds = workspace.get("bounds")
    if not isinstance(bounds, Mapping) or not bounds:
        # Dry-run uses a simulation workspace and does not require physical bounds.
        return
    margin = _finite_float(workspace.get("safety_margin_m", 0.0), "workspace.safety_margin_m")
    for axis, value in (("x", pose.x), ("y", pose.y), ("z", pose.z)):
        limits = bounds.get(axis)
        if isinstance(limits, (str, bytes)) or not isinstance(limits, Sequence) or len(limits) != 2:
            raise Task2Error(f"workspace.bounds.{axis} must be [min,max]")
        low = _finite_float(limits[0], f"workspace.bounds.{axis}[0]") + margin
        high = _finite_float(limits[1], f"workspace.bounds.{axis}[1]") - margin
        if not low < high or not low <= value <= high:
            raise Task2Error(f"{field_name}.{axis}={value:.6f} is outside the safe workspace")


def _parse_orientation_config(value: object) -> tuple[float, float, float]:
    if isinstance(value, Mapping):
        values = (value.get("roll"), value.get("pitch"), value.get("yaw"))
    elif isinstance(value, Sequence) and not isinstance(value, (str, bytes)) and len(value) == 3:
        values = tuple(value)
    else:
        raise Task2Error("tasks.task2.vision.default_orientation must contain roll, pitch, yaw")
    return tuple(_finite_float(item, "tasks.task2.vision.default_orientation") for item in values)  # type: ignore[return-value]


def _validate_hand_pose(ctx: RuntimeContext, pose_name: str) -> None:
    poses = getattr(ctx.hand, "poses", None)
    if not isinstance(poses, Mapping) or pose_name not in poses:
        raise Task2Error(f"hand pose is not configured: {pose_name}")
    value = poses[pose_name]
    if isinstance(value, (str, bytes)) or not isinstance(value, Sequence) or len(value) != 10:
        raise Task2Error(f"hand pose {pose_name} must contain 10 normalized values")
    for index, item in enumerate(value):
        number = _finite_float(item, f"hand pose {pose_name}[{index}]")
        if not 0 <= number <= 1:
            raise Task2Error(f"hand pose {pose_name}[{index}] must be between 0 and 1")


def _preflight(ctx: RuntimeContext, settings: Task2Settings) -> None:
    # Validate every configured fixed-slot route before enabling or moving the arm.
    static_observations = tuple(
        BlockObservation(number=index + 1, source_slot=slot, confidence=1.0)
        for index, slot in enumerate(settings.source_slots)
    )
    if len(static_observations) == len(EXPECTED_NUMBERS):
        build_transfer_plans(static_observations, settings)

    _validate_hand_pose(ctx, "open")
    _validate_hand_pose(ctx, settings.grip_pose_name)
    arm_status = _checked_call(ctx, "check arm status", ctx.arm.status, require_success=False)
    if arm_status.get("moveit_available") is False:
        raise Task2Error("arm MoveIt service is unavailable")
    if arm_status.get("moving") is True:
        raise Task2Error("arm is already moving")

    motors = _checked_call(ctx, "check arm motors", ctx.arm.motors, require_success=False)
    _validate_motors(motors, require_enabled=False)

    arm_name = str(getattr(ctx.arm, "arm", "right"))
    _checked_call(ctx, "enable arm", ctx.arm.enable, nested_result_key=arm_name)

    enabled_motors = _checked_call(ctx, "verify arm motors", ctx.arm.motors, require_success=False)
    _validate_motors(enabled_motors, require_enabled=True)

    hand_status = _checked_call(ctx, "check hand status", ctx.hand.status, require_success=False)
    connected = hand_status.get("connected")
    if connected is False or (not ctx.dry_run and connected is not True):
        raise Task2Error("hand is not connected")
    _checked_call(ctx, "open hand", ctx.hand.open_hand)


def _read_observations(
    ctx: RuntimeContext,
    capture: Mapping[str, Any],
    min_confidence: float,
) -> tuple[BlockObservation, ...]:
    raw_blocks = capture.get("blocks")
    if raw_blocks is None:
        if not ctx.dry_run:
            raise Task2Error("camera result does not contain task2 blocks")
        raw_blocks = _simulation_blocks()

    observations = validate_and_sort_observations(raw_blocks, min_confidence=min_confidence)
    ctx.log(
        TASK_NAME,
        "detected blocks",
        blocks=[
            {
                "number": item.number,
                "source_slot": item.source_slot,
                "confidence": item.confidence,
            }
            for item in observations
        ],
    )
    return observations


def _parse_observation(value: object, index: int) -> BlockObservation:
    field_name = f"camera.blocks[{index}]"
    if not isinstance(value, Mapping):
        raise Task2Error(f"{field_name} must be an object")

    number = value.get("number")
    if isinstance(number, bool) or not isinstance(number, int):
        raise Task2Error(f"{field_name}.number must be an integer")

    source_slot = value.get("source_slot")
    if not isinstance(source_slot, str) or not source_slot.strip():
        raise Task2Error(f"{field_name}.source_slot must be a non-empty string")

    confidence = _unit_float(value.get("confidence", 1.0), f"{field_name}.confidence")
    center = _parse_center(value.get("center"), f"{field_name}.center")
    grasp_pose_raw = value.get("grasp_pose")
    grasp_pose = None
    if grasp_pose_raw is not None:
        grasp_pose = Pose.from_mapping(grasp_pose_raw, f"{field_name}.grasp_pose")

    return BlockObservation(
        number=number,
        source_slot=source_slot.strip(),
        confidence=confidence,
        center=center,
        grasp_pose=grasp_pose,
    )


def _resolve_grasp_pose(observation: BlockObservation, settings: Task2Settings) -> Pose:
    if observation.grasp_pose is not None:
        return observation.grasp_pose

    slot_value = settings.source_slots.get(observation.source_slot)
    if slot_value is None:
        raise Task2Error(f"source slot is not configured: {observation.source_slot}")
    if not isinstance(slot_value, Mapping):
        raise Task2Error(f"source slot {observation.source_slot} must be an object")

    pose_value = slot_value.get("grasp_pose", slot_value)
    slot_pose = Pose.from_mapping(
        pose_value,
        f"tasks.task2.source_slots.{observation.source_slot}.grasp_pose",
        fallback_orientation=settings.safe_home.orientation,
    )
    if observation.center is None:
        return slot_pose
    return replace(
        slot_pose,
        x=observation.center[0],
        y=observation.center[1],
        z=observation.center[2],
    )


def _execute_transfer(ctx: RuntimeContext, plan: TransferPlan, settings: Task2Settings) -> None:
    ctx.log(
        TASK_NAME,
        "block transfer started",
        number=plan.number,
        source_slot=plan.source_slot,
    )

    _checked_call(ctx, f"open hand for block {plan.number}", ctx.hand.open_hand)
    _move_arm(ctx, f"block {plan.number} pre-grasp", plan.pre_grasp, settings.normal_velocity, linear=False)
    _move_arm(ctx, f"block {plan.number} grasp", plan.grasp, settings.safe_velocity, linear=True)
    _checked_call(
        ctx,
        f"grip block {plan.number}",
        lambda: ctx.hand.pose(settings.grip_pose_name),
    )
    _move_arm(ctx, f"block {plan.number} lift", plan.lift, settings.safe_velocity, linear=True)

    _move_arm(ctx, f"block {plan.number} carry safe", settings.safe_home, settings.normal_velocity, linear=False)
    _move_arm(ctx, f"block {plan.number} pre-place", plan.pre_place, settings.normal_velocity, linear=False)
    _move_arm(ctx, f"block {plan.number} place", plan.place, settings.safe_velocity, linear=True)
    _checked_call(ctx, f"release block {plan.number}", ctx.hand.release)
    _move_arm(ctx, f"block {plan.number} retreat", plan.retreat, settings.safe_velocity, linear=True)
    _move_arm(ctx, f"block {plan.number} return safe", settings.safe_home, settings.normal_velocity, linear=False)

    ctx.log(
        TASK_NAME,
        "block transfer finished",
        number=plan.number,
        source_slot=plan.source_slot,
    )


def _move_arm(
    ctx: RuntimeContext,
    action: str,
    pose: Pose,
    velocity: float,
    *,
    linear: bool,
) -> Mapping[str, Any]:
    ctx.log(
        TASK_NAME,
        "arm move started",
        action=action,
        target=pose.as_dict(),
        linear=linear,
        velocity=velocity,
    )
    response = _checked_call(
        ctx,
        action,
        lambda: ctx.arm.move_pose(
            pose.x,
            pose.y,
            pose.z,
            pose.roll,
            pose.pitch,
            pose.yaw,
            linear=linear,
            velocity_scaling=velocity,
        ),
    )
    message = str(response.get("message", ""))
    if linear and "OMPL" in message.upper():
        raise Task2Error(f"{action} did not execute as a Cartesian line: {message}")
    return response


def _plan_arm_pose(
    ctx: RuntimeContext,
    action: str,
    pose: Pose,
    velocity: float,
) -> Mapping[str, Any]:
    ctx.log(TASK_NAME, "arm plan started", action=action, target=pose.as_dict())
    response = _checked_call(
        ctx,
        action,
        lambda: ctx.arm.move_pose(
            pose.x,
            pose.y,
            pose.z,
            pose.roll,
            pose.pitch,
            pose.yaw,
            linear=False,
            velocity_scaling=velocity,
            plan_only=True,
        ),
    )
    ctx.log(TASK_NAME, "arm plan finished", action=action)
    return response


def _checked_call(
    ctx: RuntimeContext,
    action: str,
    operation: Callable[[], object],
    *,
    require_success: bool = True,
    nested_result_key: str | None = None,
) -> Mapping[str, Any]:
    ctx.log(TASK_NAME, "operation started", action=action)
    response = operation()
    if not isinstance(response, Mapping) or not response:
        raise Task2Error(f"{action} returned an invalid response")

    result: Mapping[str, Any] = response
    if nested_result_key is not None:
        nested = response.get(nested_result_key)
        if not isinstance(nested, Mapping):
            raise Task2Error(f"{action} response is missing {nested_result_key}")
        result = nested

    if result.get("success") is False:
        raise Task2Error(f"{action} failed: {result.get('message', 'unknown error')}")
    if require_success and result.get("success") is not True:
        raise Task2Error(f"{action} response does not confirm success")

    ctx.log(TASK_NAME, "operation finished", action=action)
    return response


def _validate_motors(response: Mapping[str, Any], *, require_enabled: bool) -> None:
    if response.get("success") is True:
        if require_enabled and response.get("enabled") is False:
            raise Task2Error("arm motors are not enabled")
        return

    joint_states = [value for value in response.values() if isinstance(value, Mapping)]
    if not joint_states:
        raise Task2Error("arm motor state is unavailable")

    for state in joint_states:
        if state.get("fault", 0) != 0:
            raise Task2Error("arm motor fault detected")
        if state.get("motor_error", 0) != 0:
            raise Task2Error("arm motor error detected")
        if state.get("has_feedback", 1) != 1:
            raise Task2Error("arm motor feedback is unavailable")
        feedback_age = state.get("feedback_age")
        if feedback_age is not None and _finite_float(feedback_age, "motor.feedback_age") >= 0.1:
            raise Task2Error("arm motor feedback is stale")
        if require_enabled and state.get("enabled") != 1:
            raise Task2Error("arm motors are not enabled")


def _parse_center(value: object, field_name: str) -> tuple[float, float, float] | None:
    if value is None:
        return None
    if isinstance(value, Mapping):
        return (
            _finite_float(value.get("x"), f"{field_name}.x"),
            _finite_float(value.get("y"), f"{field_name}.y"),
            _finite_float(value.get("z"), f"{field_name}.z"),
        )
    if isinstance(value, (str, bytes)) or not isinstance(value, Sequence) or len(value) != 3:
        raise Task2Error(f"{field_name} must contain x, y, z")
    return (
        _finite_float(value[0], f"{field_name}[0]"),
        _finite_float(value[1], f"{field_name}[1]"),
        _finite_float(value[2], f"{field_name}[2]"),
    )


def _finite_float(value: object, field_name: str) -> float:
    if isinstance(value, bool):
        raise Task2Error(f"{field_name} must be a finite number")
    try:
        number = float(value)
    except (TypeError, ValueError) as error:
        raise Task2Error(f"{field_name} must be a finite number") from error
    if not math.isfinite(number):
        raise Task2Error(f"{field_name} must be a finite number")
    return number


def _positive_float(value: object, field_name: str) -> float:
    number = _finite_float(value, field_name)
    if number <= 0:
        raise Task2Error(f"{field_name} must be greater than zero")
    return number


def _unit_float(value: object, field_name: str) -> float:
    number = _finite_float(value, field_name)
    if not 0 <= number <= 1:
        raise Task2Error(f"{field_name} must be between 0 and 1")
    return number


def _simulation_blocks() -> tuple[dict[str, object], ...]:
    return (
        {"number": 3, "source_slot": "slot_a", "confidence": 0.99},
        {"number": 1, "source_slot": "slot_b", "confidence": 0.99},
        {"number": 4, "source_slot": "slot_c", "confidence": 0.99},
        {"number": 2, "source_slot": "slot_d", "confidence": 0.99},
    )


def _simulation_source_slots(
    orientation: tuple[float, float, float],
) -> dict[str, dict[str, float]]:
    roll, pitch, yaw = orientation
    return {
        "slot_a": {"x": 0.275, "y": -0.28, "z": 0.44, "roll": roll, "pitch": pitch, "yaw": yaw},
        "slot_b": {"x": 0.275, "y": -0.24, "z": 0.44, "roll": roll, "pitch": pitch, "yaw": yaw},
        "slot_c": {"x": 0.275, "y": -0.20, "z": 0.44, "roll": roll, "pitch": pitch, "yaw": yaw},
        "slot_d": {"x": 0.275, "y": -0.16, "z": 0.44, "roll": roll, "pitch": pitch, "yaw": yaw},
    }


def _simulation_drop_points(
    orientation: tuple[float, float, float],
) -> tuple[dict[str, float], ...]:
    roll, pitch, yaw = orientation
    return tuple(
        {
            "x": 0.275,
            "y": y,
            "z": 0.44,
            "roll": roll,
            "pitch": pitch,
            "yaw": yaw,
        }
        for y in (-0.13, -0.10, -0.07, -0.04)
    )
