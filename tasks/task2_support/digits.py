from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any

import numpy as np


# A deliberately small fixture classifier. The field detector can later be replaced
# without changing the task2 block/pose contract.
DIGIT_TEMPLATES: dict[int, tuple[str, ...]] = {
    1: ("00100", "01100", "00100", "00100", "00100", "00100", "01110"),
    2: ("01110", "10001", "00001", "00010", "00100", "01000", "11111"),
    3: ("11110", "00001", "00001", "01110", "00001", "00001", "11110"),
    4: ("00010", "00110", "01010", "10010", "11111", "00010", "00010"),
}


def render_digit(
    number: int,
    *,
    scale: int = 8,
    padding: int = 12,
    background: int = 235,
    foreground: int = 25,
    noise_std: float = 0.0,
    seed: int = 0,
) -> np.ndarray:
    """Render one deterministic grayscale fixture without OpenCV or font files."""
    if number not in DIGIT_TEMPLATES:
        raise ValueError(f"unsupported digit: {number}")
    if scale <= 0 or padding < 0:
        raise ValueError("scale must be positive and padding must be non-negative")
    glyph = np.array([[int(char) for char in row] for row in DIGIT_TEMPLATES[number]], dtype=np.uint8)
    glyph = np.repeat(np.repeat(glyph, scale, axis=0), scale, axis=1)
    image = np.full(
        (glyph.shape[0] + 2 * padding, glyph.shape[1] + 2 * padding),
        background,
        dtype=np.float32,
    )
    image[padding : padding + glyph.shape[0], padding : padding + glyph.shape[1]] = np.where(
        glyph == 1,
        foreground,
        background,
    )
    if noise_std > 0:
        rng = np.random.default_rng(seed)
        image += rng.normal(0.0, noise_std, image.shape)
    return np.clip(image, 0, 255).astype(np.uint8)


def classify_digit(image: np.ndarray, *, min_confidence: float = 0.55) -> tuple[int, float]:
    """Classify a fixed-slot grayscale crop against the four fixture templates."""
    normalized = _normalize_digit(image)
    scores: list[tuple[float, int]] = []
    for number, rows in DIGIT_TEMPLATES.items():
        template = np.array([[int(char) for char in row] for row in rows], dtype=np.uint8)
        distance = float(np.mean(np.abs(normalized.astype(np.int16) - template.astype(np.int16))))
        scores.append((distance, number))
    scores.sort()
    distance, number = scores[0]
    confidence = max(0.0, 1.0 - distance)
    if confidence < min_confidence:
        raise ValueError(f"digit confidence {confidence:.3f} is below {min_confidence:.3f}")
    return number, confidence


def detect_fixed_slots(
    image: np.ndarray,
    rois: Mapping[str, Sequence[int]],
    *,
    min_confidence: float = 0.55,
) -> list[dict[str, Any]]:
    """Detect one digit per fixed ROI and return task2-compatible observations."""
    grayscale = _as_grayscale(image)
    detections: list[dict[str, Any]] = []
    for source_slot, roi in rois.items():
        if len(roi) != 4:
            raise ValueError(f"ROI for {source_slot} must be [x, y, width, height]")
        x, y, width, height = (int(value) for value in roi)
        if width <= 0 or height <= 0:
            raise ValueError(f"ROI for {source_slot} must have positive dimensions")
        crop = grayscale[y : y + height, x : x + width]
        if crop.shape != (height, width):
            raise ValueError(f"ROI for {source_slot} is outside the image")
        number, confidence = classify_digit(crop, min_confidence=min_confidence)
        detections.append(
            {
                "number": number,
                "source_slot": source_slot,
                "confidence": confidence,
            }
        )
    return detections


def _as_grayscale(image: np.ndarray) -> np.ndarray:
    array = np.asarray(image)
    if array.ndim == 2:
        return array.astype(np.uint8, copy=False)
    if array.ndim == 3 and array.shape[2] in (3, 4):
        return np.mean(array[..., :3], axis=2).astype(np.uint8)
    raise ValueError("image must be a grayscale or RGB array")


def _normalize_digit(image: np.ndarray) -> np.ndarray:
    grayscale = _as_grayscale(image).astype(np.float32)
    low = float(np.percentile(grayscale, 5))
    high = float(np.percentile(grayscale, 95))
    if high <= low:
        raise ValueError("digit crop has no usable contrast")
    mask = grayscale < (low + high) / 2.0
    row_indices = np.flatnonzero(mask.sum(axis=1) >= 2)
    column_indices = np.flatnonzero(mask.sum(axis=0) >= 2)
    if row_indices.size == 0 or column_indices.size == 0:
        raise ValueError("digit foreground was not found")
    cropped = mask[row_indices[0] : row_indices[-1] + 1, column_indices[0] : column_indices[-1] + 1]
    row_positions = np.rint(np.linspace(0, cropped.shape[0] - 1, 7)).astype(int)
    column_positions = np.rint(np.linspace(0, cropped.shape[1] - 1, 5)).astype(int)
    return cropped[row_positions][:, column_positions].astype(np.uint8)
