# Copyright 2026 Injenium
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0

"""Memory distillation: recorded memory -> de-privatized, parameterized recipe.

:func:`distill_to_recipe` is the one call the market skill (and the M2 demo)
makes. It wires the three concerns kept in separate modules — reading
(:mod:`extractor`), de-privatising (:mod:`privacy`), and the recipe schema
(:mod:`recipe`) — into a single artifact written under ``artifacts_dir``.
"""

from __future__ import annotations

import math
from typing import Any
import uuid

from injenium.distill.extractor import (
    ExtractedMemory,
    FrameSample,
    MemoryExtractor,
    TrajectorySample,
)
from injenium.distill.privacy import (
    make_object_template,
    relativize_waypoints,
    strip_device_identifiers,
)
from injenium.distill.recipe import (
    ObjectTemplate,
    Recipe,
    RelWaypoint,
    Step,
    load_recipe,
)

__all__ = [
    "ExtractedMemory",
    "FrameSample",
    "MemoryExtractor",
    "ObjectTemplate",
    "Recipe",
    "RelWaypoint",
    "Step",
    "TrajectorySample",
    "distill_to_recipe",
    "load_recipe",
    "strip_device_identifiers",
    "trajectory_to_steps",
]

# Whitelist bounds mirrored from specs.PRIMITIVE_WHITELIST for step clamping.
_MOVE_LIMIT_M = 10.0
_ROT_LIMIT_DEG = 360.0
_MIN_SEGMENT_M = 0.05  # segments shorter than this (and un-turning) are dropped


def trajectory_to_steps(trajectory: list[TrajectorySample]) -> list[Step]:
    """Turn an absolute path into incremental ``relative_move`` steps.

    Each consecutive pose pair becomes one move expressed in the *previous*
    pose's heading frame (so it composes when replayed from an arbitrary start
    anchor), with the heading delta as ``degrees``. A leading ``BalanceStand``
    makes the recipe self-contained. Segments are clamped to the whitelist
    bounds; effectively-zero segments are skipped.
    """
    steps: list[Step] = [
        Step(primitive="execute_sport_command", params={"command_name": "BalanceStand"})
    ]
    for prev, cur in zip(trajectory, trajectory[1:]):
        dx = cur.x - prev.x
        dy = cur.y - prev.y
        forward = dx * math.cos(prev.yaw) + dy * math.sin(prev.yaw)
        left = -dx * math.sin(prev.yaw) + dy * math.cos(prev.yaw)
        dyaw = math.degrees(
            math.atan2(math.sin(cur.yaw - prev.yaw), math.cos(cur.yaw - prev.yaw))
        )
        if abs(forward) < _MIN_SEGMENT_M and abs(left) < _MIN_SEGMENT_M and abs(dyaw) < 1.0:
            continue
        steps.append(
            Step(
                primitive="relative_move",
                params={
                    "forward": round(_clamp(forward, _MOVE_LIMIT_M), 3),
                    "left": round(_clamp(left, _MOVE_LIMIT_M), 3),
                    "degrees": round(_clamp(dyaw, _ROT_LIMIT_DEG), 1),
                },
            )
        )
    return steps


def distill_to_recipe(
    db_path: str,
    intent: str,
    *,
    artifacts_dir: str,
    query: str | None = None,
    recipe_name: str | None = None,
    t_start: float | None = None,
    t_end: float | None = None,
    template_count: int = 1,
    preconditions: list[str] | None = None,
    success_criteria: str = "",
    storage: str = "local",
    ipfs_api_url: str | None = None,
    **traj_kwargs: Any,
) -> tuple[Recipe, str]:
    """Distill a recorded session into a saved, whitelist-valid :class:`Recipe`.

    Args:
        db_path: recorded ``dimos.memory2`` SQLite store (PoC: go2_short.db).
        intent: the human intent this recipe fulfils (the request's ``need``).
        artifacts_dir: parent dir; a fresh per-recipe subdir is created inside.
        query: optional text used for semantic frame search (best-effort).
        recipe_name: subdir name; defaults to ``recipe-<8 hex>``.
        template_count: how many object-template artifacts to extract.
        preconditions / success_criteria: passed through onto the recipe.
        traj_kwargs: forwarded to :meth:`MemoryExtractor.extract` (e.g.
            ``min_step_m``, ``max_points``).

    Returns:
        ``(recipe, uri)`` — the recipe is saved under ``artifacts_dir``; ``uri``
        is the local recipe dir, or an ``ipfs://<cid>`` pointer when
        ``storage="ipfs"`` (the whole dir is pinned so template artifacts
        resolve under the same CID and ``content_hash`` is unchanged).

    Raises:
        ValueError: if the distilled recipe violates the primitive whitelist.
    """
    from pathlib import Path  # noqa: PLC0415

    name = recipe_name or f"recipe-{uuid.uuid4().hex[:8]}"
    recipe_dir = str(Path(artifacts_dir) / name)

    with MemoryExtractor(db_path) as ex:
        memory = ex.extract(t_start=t_start, t_end=t_end, **traj_kwargs)
        frames = _select_template_frames(ex, memory, query, template_count)

    steps = trajectory_to_steps(memory.trajectory)
    rel_waypoints = relativize_waypoints(memory.trajectory)
    templates = _build_templates(frames, recipe_dir)

    recipe = Recipe(
        intent=intent,
        preconditions=preconditions or [],
        steps=steps,
        rel_waypoints=rel_waypoints,
        object_templates=templates,
        success_criteria=success_criteria,
    )
    problems = recipe.validate_whitelist()
    if problems:
        raise ValueError("distilled recipe is invalid: " + "; ".join(problems))

    recipe.save(recipe_dir)
    if storage == "ipfs":
        from injenium.distill import ipfs  # noqa: PLC0415

        return recipe, ipfs.publish_dir(recipe_dir, api_url=ipfs_api_url)
    return recipe, recipe_dir


def _select_template_frames(
    ex: MemoryExtractor,
    memory: ExtractedMemory,
    query: str | None,
    template_count: int,
) -> list[FrameSample]:
    if template_count <= 0:
        return []
    if query:
        hits = ex.semantic_search(query, k=template_count)
        if hits:
            return hits[:template_count]
    return memory.frames[:template_count]


def _build_templates(
    frames: list[FrameSample], recipe_dir: str
) -> list[ObjectTemplate]:
    templates: list[ObjectTemplate] = []
    for i, frame in enumerate(frames):
        template = make_object_template(
            frame,
            name=f"template_{i}",
            directory=recipe_dir,
        )
        # Keep only templates whose artifact actually landed on disk.
        if template.image_path:
            templates.append(template)
    return templates


def _clamp(value: float, limit: float) -> float:
    return max(-limit, min(limit, value))
