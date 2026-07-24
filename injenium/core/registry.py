# Copyright 2026 Injenium
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0

"""Primitive validation specs + the pluggable primitive registry.

``ParamSpec``/``PrimitiveSpec`` are the domain-neutral validation rules the
sandbox enforces. A domain registers each primitive as a ``(PrimitiveSpec,
dispatch)`` pair, where ``dispatch`` is an explicit adapter the domain author
writes — the sandbox therefore never reflects/``getattr``s a recipe-supplied
name onto the provider (that is the executable trust boundary, preserved).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable

# adapter(provider, coerced_params) -> human-readable result string
Dispatch = Callable[[Any, dict[str, Any]], str]


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


@dataclass(frozen=True)
class RegisteredPrimitive:
    """A primitive spec paired with the domain adapter that executes it."""

    spec: PrimitiveSpec
    dispatch: Dispatch


class PrimitiveRegistry:
    """The set of primitives a sandbox may validate + dispatch.

    Domains populate a registry (usually :data:`default_registry`) on import;
    the sandbox reads it. Adding a new domain/primitive never touches the
    sandbox interpreter.
    """

    def __init__(self) -> None:
        self._prims: dict[str, RegisteredPrimitive] = {}

    def register(self, spec: PrimitiveSpec, dispatch: Dispatch) -> None:
        self._prims[spec.name] = RegisteredPrimitive(spec, dispatch)

    def get(self, name: str) -> RegisteredPrimitive | None:
        return self._prims.get(name)

    def spec(self, name: str) -> PrimitiveSpec | None:
        rp = self._prims.get(name)
        return rp.spec if rp is not None else None

    def names(self) -> tuple[str, ...]:
        return tuple(self._prims)

    def __contains__(self, name: object) -> bool:
        return name in self._prims


# Process-global registry domains register into on import; the sandbox's
# default. Mutated in place, so a registry captured before registration still
# sees later registrations.
default_registry = PrimitiveRegistry()
