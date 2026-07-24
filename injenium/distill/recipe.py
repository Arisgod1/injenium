# Copyright 2026 Injenium
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0

"""The ``Recipe`` data model — the tradeable, executable skill artifact.

A recipe is the only thing that crosses between dogs. It is deliberately:

* **parameterized** — a list of steps referencing whitelisted primitives with
  plain params, never code;
* **de-privatized** — waypoints are relative to a start anchor, timestamps are
  dropped, object templates are cropped/blurred (see :mod:`privacy`);
* **content-addressed** — :meth:`content_hash` yields a sha256 the chain stores
  as ``bytes32`` while the body lives off-chain.

The off-chain storage boundary lives here (``save``/``load`` + ``artifacts``):
swapping the local ``artifacts_dir`` for IPFS/Arweave later touches only this
module (spec §链下产物存储).
"""

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field, field_validator

from injenium.specs import PRIMITIVE_WHITELIST

RECIPE_SCHEMA_VERSION = 1
RECIPE_FILENAME = "recipe.json"


class Step(BaseModel):
    """One executable step: a whitelisted primitive plus its params."""

    primitive: str
    params: dict[str, Any] = Field(default_factory=dict)

    @field_validator("primitive")
    @classmethod
    def _known_primitive(cls, v: str) -> str:
        if v not in PRIMITIVE_WHITELIST:
            raise ValueError(
                f"primitive {v!r} is not in the whitelist {tuple(PRIMITIVE_WHITELIST)}"
            )
        return v


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


class Recipe(BaseModel):
    """A distilled, shareable skill recipe."""

    intent: str
    preconditions: list[str] = Field(default_factory=list)
    steps: list[Step] = Field(default_factory=list)
    rel_waypoints: list[RelWaypoint] = Field(default_factory=list)
    object_templates: list[ObjectTemplate] = Field(default_factory=list)
    success_criteria: str = ""
    schema_version: int = RECIPE_SCHEMA_VERSION

    # -- validation ----------------------------------------------------------

    def validate_whitelist(self) -> list[str]:
        """Return a list of human-readable violations (empty == valid).

        Checks that every step references a whitelisted primitive. Parameter
        type/range checks are the sandbox's job (see interpreter) so a recipe
        can be inspected without a primitive provider.
        """
        problems: list[str] = []
        if not self.steps:
            problems.append("recipe has no steps")
        for i, step in enumerate(self.steps):
            if step.primitive not in PRIMITIVE_WHITELIST:
                problems.append(f"step[{i}]: unknown primitive {step.primitive!r}")
        return problems

    # -- serialization / addressing -----------------------------------------

    def canonical_json(self) -> str:
        """Deterministic JSON (sorted keys) used for hashing and storage."""
        return json.dumps(self.model_dump(), sort_keys=True, separators=(",", ":"))

    def content_hash(self) -> str:
        """Hex sha256 of the canonical body (64 hex chars == bytes32 on-chain)."""
        return hashlib.sha256(self.canonical_json().encode("utf-8")).hexdigest()

    def save(self, directory: str | os.PathLike[str]) -> str:
        """Write ``recipe.json`` into ``directory``; return the file path.

        Object-template artifacts are expected to already live in ``directory``
        (the distiller writes them there), referenced by relative path.
        """
        d = Path(os.fspath(directory))
        d.mkdir(parents=True, exist_ok=True)
        path = d / RECIPE_FILENAME
        path.write_text(
            json.dumps(self.model_dump(), indent=2, sort_keys=True), encoding="utf-8"
        )
        return str(path)


def load_recipe(uri: str | os.PathLike[str]) -> Recipe:
    """Load a recipe from an ``ipfs://<cid>`` pointer or a local path.

    ``uri`` is the off-chain pointer stored in an :class:`Offer`: either an
    ``ipfs://<cid>`` CID (resolved through the IPFS HTTP API, so two machines
    share the artifact) or, for the zero-dependency PoC, a local directory /
    ``recipe.json`` path.
    """
    from injenium.distill import ipfs  # noqa: PLC0415 -- avoids an import cycle

    if ipfs.is_ipfs_uri(uri):
        raw = ipfs.cat(f"{ipfs.cid_from_uri(uri)}/{RECIPE_FILENAME}")
        return Recipe.model_validate(json.loads(raw))
    p = Path(os.fspath(uri))
    if p.is_dir():
        p = p / RECIPE_FILENAME
    data = json.loads(p.read_text(encoding="utf-8"))
    return Recipe.model_validate(data)
