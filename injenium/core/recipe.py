# Copyright 2026 Injenium
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0

"""The ``Recipe`` data model — the tradeable, executable capability artifact.

A recipe is the only thing that crosses between agents. It is deliberately:

* **parameterized** — a list of steps referencing whitelisted primitives with
  plain params, never code;
* **content-addressed** — :meth:`content_hash` yields a sha256 the chain stores
  as ``bytes32`` while the body lives off-chain;
* **domain-neutral** — the executable core is ``steps``; anything a domain needs
  to carry (robot waypoints, cropped templates, …) goes in :attr:`payload` and
  is hashed with the rest.

The off-chain storage boundary lives here (``save`` + :func:`load_recipe`);
swapping the local dir for IPFS touches only this module + :mod:`injenium.core.storage`.
"""

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field

from injenium.core.registry import PrimitiveRegistry, default_registry

RECIPE_SCHEMA_VERSION = 1
RECIPE_FILENAME = "recipe.json"


class Step(BaseModel):
    """One executable step: a primitive name plus its params.

    The primitive whitelist is enforced by the sandbox against the active
    registry (see :mod:`injenium.core.sandbox.interpreter`), not at model
    construction — the recipe is inert data until the sandbox validates it.
    """

    primitive: str
    params: dict[str, Any] = Field(default_factory=dict)


class Recipe(BaseModel):
    """A distilled, shareable capability recipe."""

    intent: str
    preconditions: list[str] = Field(default_factory=list)
    steps: list[Step] = Field(default_factory=list)
    success_criteria: str = ""
    schema_version: int = RECIPE_SCHEMA_VERSION
    # Domain-specific extras (e.g. Go2: rel_waypoints / object_templates).
    # Hashed with the rest so the on-chain commitment covers it.
    payload: dict[str, Any] = Field(default_factory=dict)

    # -- validation ----------------------------------------------------------

    def validate_whitelist(self, registry: PrimitiveRegistry | None = None) -> list[str]:
        """Return human-readable violations (empty == every step is whitelisted).

        Checks each step's primitive against ``registry`` (defaults to the
        process registry a domain has populated). Parameter type/range checks
        are the sandbox's job.
        """
        reg = registry if registry is not None else default_registry
        problems: list[str] = []
        if not self.steps:
            problems.append("recipe has no steps")
        for i, step in enumerate(self.steps):
            if step.primitive not in reg:
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

        Any artifacts referenced from ``payload`` (by relative path) are
        expected to already live in ``directory`` (the distiller writes them).
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

    ``uri`` is the off-chain pointer stored in an ``Offer``: either an
    ``ipfs://<cid>`` CID (resolved through the IPFS HTTP API, so two machines
    share the artifact) or, for the zero-dependency PoC, a local directory /
    ``recipe.json`` path.
    """
    from injenium.core import storage  # noqa: PLC0415 -- avoids an import cycle

    if storage.is_ipfs_uri(uri):
        raw = storage.cat(f"{storage.cid_from_uri(uri)}/{RECIPE_FILENAME}")
        return Recipe.model_validate(json.loads(raw))
    p = Path(os.fspath(uri))
    if p.is_dir():
        p = p / RECIPE_FILENAME
    data = json.loads(p.read_text(encoding="utf-8"))
    return Recipe.model_validate(data)
