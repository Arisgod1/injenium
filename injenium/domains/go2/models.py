# Copyright 2026 Injenium
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0

"""Go2 domain recipe-payload models (carried in :attr:`Recipe.payload`).

These are robot-specific de-privatised artifacts — a relative waypoint path and
cropped/blurred object templates — kept out of the domain-neutral core recipe
schema. They travel inside ``recipe.payload`` and are hashed with the rest.
"""

from __future__ import annotations

from pydantic import BaseModel


class RelWaypoint(BaseModel):
    """A waypoint relative to the recipe's start anchor (no absolute frame)."""

    dx: float = 0.0
    dy: float = 0.0
    dz: float = 0.0
    dyaw_deg: float = 0.0


class ObjectTemplate(BaseModel):
    """A reference to a cropped/blurred object image stored beside the recipe."""

    name: str
    image_path: str  # relative to the recipe directory
    bbox: list[float] | None = None  # [x1, y1, x2, y2] in the cropped frame
