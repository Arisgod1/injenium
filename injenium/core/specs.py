# Copyright 2026 Injenium
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0

"""The primitive-provider injection contract.

:class:`PrimitiveSkillsSpec` is the dimOS ``Spec`` the market container gets a
provider injected against. It is kept in core (dimOS DI needs a concrete Spec
type on the module) even though its current method set mirrors the Go2 robot
skills; a domain's provider (mock or real) satisfies it structurally. The
sandbox calls the provider only through domain-registered adapters (see
:mod:`injenium.core.registry`), never by reflecting a recipe name onto it.
"""

from __future__ import annotations

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
