# Copyright 2026 Injenium
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0

"""De-privatisation rules applied before a memory becomes a shareable recipe.

Nothing that could tie a recipe back to a place, a time, or a person may leave
the dog (spec §3 去隐私). Concretely this module:

* **drops the absolute world frame** — a run of absolute odom poses becomes a
  list of :class:`~injenium.distill.recipe.RelWaypoint` anchored at the
  start pose (translation rotated into the start heading, yaw made relative);
* **drops wall-clock time** — callers keep only relative offsets, never the
  epoch timestamps carried on observations;
* **blurs faces / crops object templates** — an image is reduced to the object
  of interest and any detected faces are Gaussian-blurred;
* **strips device identifiers** — serials/MACs/IPs are removed from tag dicts.

Image work needs the ``[vision]`` extra (OpenCV/Pillow/numpy). It is imported
lazily and degrades safely: if OpenCV is missing, face blur is skipped but the
crop (and every non-image rule) still applies, so distillation never hard-fails
on a headless box.
"""

from __future__ import annotations

import math
from typing import TYPE_CHECKING, Any

from injenium.distill.recipe import ObjectTemplate, RelWaypoint

if TYPE_CHECKING:
    from injenium.distill.extractor import FrameSample, TrajectorySample

# Tag keys considered device-identifying and stripped from any metadata we keep.
_DEVICE_TAG_KEYS = frozenset(
    {
        "device_id",
        "serial",
        "serial_number",
        "mac",
        "mac_address",
        "ip",
        "ip_address",
        "hostname",
        "robot_id",
        "sn",
        "uuid",
        "owner",
        "operator",
    }
)


def relativize_waypoints(
    trajectory: list[TrajectorySample],
) -> list[RelWaypoint]:
    """Express an absolute odom path as waypoints relative to its start anchor.

    The first pose becomes the origin of a local frame; every later pose is
    translated by the anchor and rotated by ``-anchor.yaw`` so the recipe never
    reveals where in the world it happened — only the shape of the motion.
    """
    if len(trajectory) < 2:
        return []
    anchor = trajectory[0]
    cos_a = math.cos(-anchor.yaw)
    sin_a = math.sin(-anchor.yaw)
    out: list[RelWaypoint] = []
    for p in trajectory[1:]:
        gx = p.x - anchor.x
        gy = p.y - anchor.y
        lx = gx * cos_a - gy * sin_a
        ly = gx * sin_a + gy * cos_a
        dyaw = math.atan2(
            math.sin(p.yaw - anchor.yaw), math.cos(p.yaw - anchor.yaw)
        )
        out.append(
            RelWaypoint(
                dx=round(lx, 3),
                dy=round(ly, 3),
                dz=round(p.z - anchor.z, 3),
                dyaw_deg=round(math.degrees(dyaw), 1),
            )
        )
    return out


def strip_device_identifiers(tags: dict[str, Any]) -> dict[str, Any]:
    """Return a copy of ``tags`` with device-identifying keys removed."""
    return {
        k: v
        for k, v in tags.items()
        if k.lower() not in _DEVICE_TAG_KEYS
    }


def blur_faces(image: Any) -> Any:
    """Return a copy of a dimOS ``Image`` with detected faces Gaussian-blurred.

    Uses OpenCV's bundled Haar cascade. If OpenCV/numpy are unavailable, or no
    face is found, the image is returned unchanged (the crop already limits
    exposure). Never raises for the missing-dependency case.
    """
    try:
        import cv2  # noqa: PLC0415
        import numpy as np  # noqa: PLC0415
    except Exception:  # pragma: no cover - vision extra not installed
        return image

    try:
        arr = image.as_numpy()
    except Exception:  # pragma: no cover - unexpected image shape
        return image

    cascade_path = cv2.data.haarcascades + "haarcascade_frontalface_default.xml"
    cascade = cv2.CascadeClassifier(cascade_path)
    if cascade.empty():  # pragma: no cover - cv2 build without data
        return image

    work = np.ascontiguousarray(arr)
    gray = cv2.cvtColor(work, cv2.COLOR_RGB2GRAY) if work.ndim == 3 else work
    faces = cascade.detectMultiScale(gray, scaleFactor=1.1, minNeighbors=5)
    if len(faces) == 0:
        return image
    for x, y, w, h in faces:
        roi = work[y : y + h, x : x + w]
        if roi.size:
            work[y : y + h, x : x + w] = cv2.GaussianBlur(roi, (0, 0), sigmaX=16)

    try:
        return type(image).from_numpy(work)
    except Exception:  # pragma: no cover - constructor drift
        return image


def make_object_template(
    frame: FrameSample,
    *,
    name: str,
    bbox: list[float] | None = None,
    directory: str,
    blur: bool = True,
) -> ObjectTemplate:
    """Crop + face-blur a frame into a de-privatised object template on disk.

    Args:
        frame: the source frame (its image is a dimOS ``Image``).
        name: template name (also the artifact filename stem).
        bbox: ``[x1, y1, x2, y2]`` pixels to crop to; ``None`` = center half.
        directory: where the ``<name>.png`` artifact is written.
        blur: whether to run :func:`blur_faces` on the crop.

    Returns:
        An :class:`ObjectTemplate` referencing the artifact by *relative* path.
    """
    import os  # noqa: PLC0415
    from pathlib import Path  # noqa: PLC0415

    image = frame.image
    width = int(getattr(image, "width", 0) or 0)
    height = int(getattr(image, "height", 0) or 0)

    if bbox is None and width and height:
        # Default region of interest: the centre half of the frame.
        x1, y1 = width // 4, height // 4
        crop_w, crop_h = width // 2, height // 2
        crop_bbox = [float(x1), float(y1), float(x1 + crop_w), float(y1 + crop_h)]
    elif bbox is not None:
        x1, y1, x2, y2 = (int(round(v)) for v in bbox)
        crop_w, crop_h = max(1, x2 - x1), max(1, y2 - y1)
        crop_bbox = [float(x1), float(y1), float(x2), float(y2)]
    else:  # no dimensions available — keep whole image, no crop math
        x1 = y1 = 0
        crop_w = crop_h = 0
        crop_bbox = None

    cropped = image
    if crop_w and crop_h:
        try:
            cropped = image.crop(x1, y1, crop_w, crop_h)
        except Exception:  # pragma: no cover - crop unsupported/out of range
            cropped = image

    if blur:
        cropped = blur_faces(cropped)

    Path(directory).mkdir(parents=True, exist_ok=True)
    rel_name = f"{name}.png"
    out_path = os.path.join(directory, rel_name)
    try:
        cropped.save(out_path)
    except Exception:  # pragma: no cover - save unsupported in headless env
        rel_name = ""

    return ObjectTemplate(
        name=name,
        image_path=rel_name,
        bbox=crop_bbox if crop_bbox is not None else None,
    )
