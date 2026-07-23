# Copyright 2026 Injenium
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0

"""Typed interface for the on-board primitive skills + the recipe whitelist.

:class:`PrimitiveSkillsSpec` is a dimOS ``Spec`` (``Spec, Protocol``) so a
concrete provider is injected into the market container at blueprint-build time
and the sandbox can call it type-checked, with **no string reflection** into the
robot's skill registry.

:data:`PRIMITIVE_WHITELIST` is the single source of truth for which primitives a
distilled recipe may reference and the parameter bounds the sandbox enforces.
Method names/signatures mirror the real dimOS skills:

* ``UnitreeSkillContainer.relative_move / execute_sport_command / wait``
* ``NavigationSkillContainer.navigate_with_text``
* ``PersonFollowSkillContainer.follow_person``
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Protocol

from dimos.spec.utils import Spec


class PrimitiveSkillsSpec(Spec, Protocol):
    """Structural interface a primitive provider must satisfy.

    The signatures intentionally match the real robot skills so the same
    provider can either delegate to them (real robot) or simulate them (mock).
    """

    def relative_move(
        self, forward: float = 0.0, left: float = 0.0, degrees: float = 0.0
    ) -> str: ...

    def navigate_with_text(self, query: str) -> str: ...

    def follow_person(
        self,
        query: str,
        initial_bbox: list[float] | None = None,
        initial_image: str | None = None,
    ) -> str: ...

    def execute_sport_command(self, command_name: str) -> str: ...

    def wait(self, seconds: float) -> str: ...


@dataclass(frozen=True)
class ParamSpec:
    """Validation rule for a single recipe-step parameter."""

    name: str
    type: type
    required: bool = False
    min: float | None = None
    max: float | None = None
    # For string params, an optional closed set of allowed values.
    choices: tuple[str, ...] | None = None
    # For list params, the exact expected length (e.g. bbox = 4).
    length: int | None = None


@dataclass(frozen=True)
class PrimitiveSpec:
    """A whitelisted primitive: its dispatch name and accepted params."""

    name: str
    params: tuple[ParamSpec, ...] = field(default_factory=tuple)


# Curated safe sport commands a recipe may invoke. Deliberately excludes
# high-risk acrobatics (flips/handstand) from the distilled-recipe path.
SAFE_SPORT_COMMANDS: tuple[str, ...] = (
    "BalanceStand",
    "StandUp",
    "StandDown",
    "RecoveryStand",
    "Sit",
    "RiseSit",
    "Hello",
    "Stretch",
)

_MOVE_LIMIT_M = 10.0
_ROT_LIMIT_DEG = 360.0
_WAIT_LIMIT_S = 120.0


PRIMITIVE_WHITELIST: dict[str, PrimitiveSpec] = {
    "relative_move": PrimitiveSpec(
        "relative_move",
        (
            ParamSpec("forward", float, min=-_MOVE_LIMIT_M, max=_MOVE_LIMIT_M),
            ParamSpec("left", float, min=-_MOVE_LIMIT_M, max=_MOVE_LIMIT_M),
            ParamSpec("degrees", float, min=-_ROT_LIMIT_DEG, max=_ROT_LIMIT_DEG),
        ),
    ),
    "navigate_with_text": PrimitiveSpec(
        "navigate_with_text",
        (ParamSpec("query", str, required=True),),
    ),
    "follow_person": PrimitiveSpec(
        "follow_person",
        (
            ParamSpec("query", str, required=True),
            ParamSpec("initial_bbox", list, length=4),
        ),
    ),
    "execute_sport_command": PrimitiveSpec(
        "execute_sport_command",
        (ParamSpec("command_name", str, required=True, choices=SAFE_SPORT_COMMANDS),),
    ),
    "wait": PrimitiveSpec(
        "wait",
        (ParamSpec("seconds", float, required=True, min=0.0, max=_WAIT_LIMIT_S),),
    ),
}
