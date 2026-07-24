# Copyright 2026 Injenium
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0

"""The Go2 primitive whitelist + dispatch adapters.

:func:`register` populates a :class:`~injenium.core.registry.PrimitiveRegistry`
with the five safe robot primitives: each gets a :class:`PrimitiveSpec` (the
parameter validation rules the sandbox enforces) and an explicit ``dispatch``
adapter that calls the injected provider. The adapters — not any recipe-supplied
string — are what actually invoke the provider, preserving the sandbox's
"no reflection / no eval" trust boundary.
"""

from __future__ import annotations

from typing import Any

from injenium.core.registry import ParamSpec, PrimitiveRegistry, PrimitiveSpec

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

_SPECS: dict[str, PrimitiveSpec] = {
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


# -- dispatch adapters: explicit provider calls (domain-authored, never reflected)


def _relative_move(p: Any, kw: dict[str, Any]) -> str:
    return p.relative_move(
        forward=kw.get("forward", 0.0),
        left=kw.get("left", 0.0),
        degrees=kw.get("degrees", 0.0),
    )


def _navigate_with_text(p: Any, kw: dict[str, Any]) -> str:
    return p.navigate_with_text(query=kw["query"])


def _follow_person(p: Any, kw: dict[str, Any]) -> str:
    return p.follow_person(query=kw["query"], initial_bbox=kw.get("initial_bbox"))


def _execute_sport_command(p: Any, kw: dict[str, Any]) -> str:
    return p.execute_sport_command(command_name=kw["command_name"])


def _wait(p: Any, kw: dict[str, Any]) -> str:
    return p.wait(seconds=kw["seconds"])


_ADAPTERS = {
    "relative_move": _relative_move,
    "navigate_with_text": _navigate_with_text,
    "follow_person": _follow_person,
    "execute_sport_command": _execute_sport_command,
    "wait": _wait,
}


def register(registry: PrimitiveRegistry) -> None:
    """Register every Go2 primitive (spec + adapter) into ``registry``."""
    for name, spec in _SPECS.items():
        registry.register(spec, _ADAPTERS[name])
