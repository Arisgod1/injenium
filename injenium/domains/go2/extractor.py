# Copyright 2026 Injenium
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0

"""Pull representative memory fragments out of a recorded ``dimos.memory2`` store.

This is the read side of distillation (spec §3 抽取). It leans entirely on the
query API that ships with dimOS (:mod:`dimos.memory2.stream`):

* ``stream.time_range(t1, t2)`` / ``.after`` / ``.before`` window a session;
* ``.order_by("ts")`` + iteration walks observations chronologically;
* ``.at(ts, tolerance).first()`` grabs the frame nearest a moment in time;
* ``.near(pose, radius)`` filters spatially;
* ``.search(embedding, k)`` / ``.search_text(text)`` locate "similar task"
  fragments semantically (best-effort — see :meth:`semantic_search`).

The extractor returns plain, source-agnostic samples; the actual de-privatizing
(relativising poses, blurring faces, cropping templates) lives in
:mod:`injenium.domains.go2.privacy` so this stays a thin reader.
"""

from __future__ import annotations

from dataclasses import dataclass, field
import math
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from dimos.memory2.store.sqlite import SqliteStore

# Default stream names in the PoC recording (data/go2_short.db).
DEFAULT_ODOM_STREAM = "odom"
DEFAULT_IMAGE_STREAM = "color_image"
DEFAULT_EMBED_STREAM = "color_image_embedded"


@dataclass
class TrajectorySample:
    """One pose along the recorded path (absolute, pre-privacy)."""

    ts: float
    x: float
    y: float
    z: float
    yaw: float  # radians, world frame


@dataclass
class FrameSample:
    """A representative image frame and the pose nearest it in time."""

    ts: float
    image: Any  # dimos.msgs.sensor_msgs.Image (kept untyped to avoid a hard dep)
    pose: TrajectorySample | None = None


@dataclass
class ExtractedMemory:
    """Everything the distiller needs before de-privatisation."""

    t_start: float
    t_end: float
    trajectory: list[TrajectorySample] = field(default_factory=list)
    frames: list[FrameSample] = field(default_factory=list)


def _yaw_of(obs_data: Any, pose_tuple: Any) -> float:
    """Best-effort yaw (radians) from a PoseStamped payload or a 7-tuple."""
    yaw = getattr(obs_data, "yaw", None)
    if yaw is not None:
        return float(yaw)
    if pose_tuple is not None and len(pose_tuple) == 7:
        _, _, _, qx, qy, qz, qw = pose_tuple
        siny = 2.0 * (qw * qz + qx * qy)
        cosy = 1.0 - 2.0 * (qy * qy + qz * qz)
        return math.atan2(siny, cosy)
    return 0.0


def _xyz_of(obs_data: Any, pose_tuple: Any) -> tuple[float, float, float]:
    """Best-effort (x, y, z) from a PoseStamped payload or a 7-tuple."""
    pos = getattr(obs_data, "position", None)
    if pos is not None:
        return (float(pos.x), float(pos.y), float(pos.z))
    if pose_tuple is not None and len(pose_tuple) >= 3:
        return (float(pose_tuple[0]), float(pose_tuple[1]), float(pose_tuple[2]))
    return (0.0, 0.0, 0.0)


class MemoryExtractor:
    """Reader over a recorded :class:`SqliteStore` session.

    Use as a context manager so the underlying store is always closed::

        with MemoryExtractor("data/go2_short.db") as ex:
            mem = ex.extract()
    """

    def __init__(
        self,
        db_path: str,
        *,
        odom_stream: str = DEFAULT_ODOM_STREAM,
        image_stream: str = DEFAULT_IMAGE_STREAM,
        embed_stream: str = DEFAULT_EMBED_STREAM,
    ) -> None:
        self._db_path = db_path
        self._odom_stream = odom_stream
        self._image_stream = image_stream
        self._embed_stream = embed_stream
        self._store: SqliteStore | None = None

    # -- lifecycle -----------------------------------------------------------

    def open(self) -> MemoryExtractor:
        from dimos.memory2.store.sqlite import SqliteStore  # noqa: PLC0415

        self._store = SqliteStore(path=self._db_path, must_exist=True)
        return self

    def close(self) -> None:
        if self._store is not None:
            self._store.stop()
            self._store = None

    def __enter__(self) -> MemoryExtractor:
        return self.open()

    def __exit__(self, *_exc: object) -> None:
        self.close()

    # -- primitives ----------------------------------------------------------

    @property
    def _store_or_raise(self) -> SqliteStore:
        if self._store is None:
            raise RuntimeError("MemoryExtractor is not open; call .open() first.")
        return self._store

    def time_bounds(self) -> tuple[float, float]:
        """(min_ts, max_ts) of the odom stream (the session clock)."""
        odom = self._store_or_raise.stream(self._odom_stream)
        return odom.get_time_range()

    def extract_trajectory(
        self,
        *,
        t_start: float | None = None,
        t_end: float | None = None,
        min_step_m: float = 0.4,
        min_turn_deg: float = 20.0,
        max_points: int = 40,
    ) -> list[TrajectorySample]:
        """Down-sampled odom path within an optional time window.

        A pose is kept when it has moved ``min_step_m`` metres or turned
        ``min_turn_deg`` degrees since the last kept pose, so a dense 1 kHz-ish
        odom log collapses to a handful of intent-bearing waypoints. The result
        is finally capped to ``max_points`` by uniform stride.
        """
        odom = self._store_or_raise.stream(self._odom_stream).order_by("ts")
        if t_start is not None and t_end is not None:
            odom = odom.time_range(t_start, t_end)
        elif t_start is not None:
            odom = odom.after(t_start)
        elif t_end is not None:
            odom = odom.before(t_end)

        min_turn = math.radians(min_turn_deg)
        kept: list[TrajectorySample] = []
        for obs in odom:
            x, y, z = _xyz_of(obs.data, obs.pose_tuple)
            yaw = _yaw_of(obs.data, obs.pose_tuple)
            if not kept:
                kept.append(TrajectorySample(obs.ts, x, y, z, yaw))
                continue
            last = kept[-1]
            moved = math.hypot(x - last.x, y - last.y)
            turned = abs(math.atan2(math.sin(yaw - last.yaw), math.cos(yaw - last.yaw)))
            if moved >= min_step_m or turned >= min_turn:
                kept.append(TrajectorySample(obs.ts, x, y, z, yaw))

        if len(kept) > max_points:
            stride = math.ceil(len(kept) / max_points)
            trimmed = kept[::stride]
            if trimmed[-1] is not kept[-1]:
                trimmed.append(kept[-1])  # always keep the final pose
            kept = trimmed
        return kept

    def frames_at(
        self, timestamps: list[float], *, tolerance: float = 1.0
    ) -> list[FrameSample]:
        """Nearest image frame to each timestamp (skips misses)."""
        images = self._store_or_raise.stream(self._image_stream)
        out: list[FrameSample] = []
        for ts in timestamps:
            try:
                obs = images.at(ts, tolerance=tolerance).first()
            except LookupError:
                continue
            out.append(FrameSample(ts=obs.ts, image=obs.data))
        return out

    def semantic_search(self, text: str, *, k: int = 3) -> list[FrameSample]:
        """Best-effort "find similar frames" over the embedded image stream.

        Uses the CLIP text encoder to build a query embedding and the store's
        vector search (``stream.search``). Semantic search is optional in the
        PoC: if the embedding model or the embedded stream is unavailable this
        returns an empty list rather than failing distillation.
        """
        try:
            embed_stream = self._store_or_raise.stream(self._embed_stream)
            query_vec = self._encode_text(text)
            if query_vec is None:
                return []
            out: list[FrameSample] = []
            for obs in embed_stream.search(query_vec, k=k):
                out.append(FrameSample(ts=obs.ts, image=obs.data))
            return out
        except Exception:  # pragma: no cover - optional, model/env dependent
            return []

    @staticmethod
    def _encode_text(text: str) -> Any:
        try:
            from dimos.models.embedding.clip import CLIPModel  # noqa: PLC0415

            return CLIPModel().embed_text(text)
        except Exception:  # pragma: no cover - optional heavy dependency
            return None

    # -- one-shot ------------------------------------------------------------

    def extract(
        self,
        *,
        t_start: float | None = None,
        t_end: float | None = None,
        with_frames: bool = True,
        frame_count: int = 3,
        **traj_kwargs: Any,
    ) -> ExtractedMemory:
        """Convenience: trajectory + a few evenly-spaced representative frames."""
        traj = self.extract_trajectory(t_start=t_start, t_end=t_end, **traj_kwargs)
        if traj:
            lo, hi = traj[0].ts, traj[-1].ts
        else:
            lo, hi = self.time_bounds()

        frames: list[FrameSample] = []
        if with_frames and frame_count > 0:
            if traj:
                idx = _even_indices(len(traj), frame_count)
                sample_ts = [traj[i].ts for i in idx]
            else:
                sample_ts = _even_values(lo, hi, frame_count)
            frames = self.frames_at(sample_ts)
            # attach the nearest trajectory pose to each frame for privacy work
            for fr in frames:
                fr.pose = _nearest_pose(traj, fr.ts)
        return ExtractedMemory(t_start=lo, t_end=hi, trajectory=traj, frames=frames)


def _even_indices(n: int, k: int) -> list[int]:
    if n <= 0 or k <= 0:
        return []
    if k >= n:
        return list(range(n))
    return [round(i * (n - 1) / (k - 1)) for i in range(k)] if k > 1 else [n // 2]


def _even_values(lo: float, hi: float, k: int) -> list[float]:
    if k <= 1:
        return [(lo + hi) / 2.0]
    return [lo + (hi - lo) * i / (k - 1) for i in range(k)]


def _nearest_pose(
    traj: list[TrajectorySample], ts: float
) -> TrajectorySample | None:
    if not traj:
        return None
    return min(traj, key=lambda p: abs(p.ts - ts))
