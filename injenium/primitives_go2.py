# Copyright 2026 Injenium
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0

"""Real-robot provider of :class:`~injenium.specs.PrimitiveSkillsSpec`.

On an actual Go2 the five whitelisted primitives live in three separate dimOS
skill containers (``UnitreeSkillContainer``, ``NavigationSkillContainer``,
``PersonFollowSkillContainer``). :class:`Go2Primitives` is a thin facade module
that gathers those containers through dimOS dependency injection and re-exposes
one unified spec surface for the sandbox to call.

The three narrow ``Spec`` protocols below intentionally mirror the exact
signatures of the real skills so the coordinator resolves each to its provider
by structural + annotation compliance at blueprint-build time — no concrete
robot container is imported here, so this module stays import-light (the heavy
vision/tracking deps are only pulled in when the real blueprint is deployed).
"""

from __future__ import annotations

from typing import Protocol

from dimos.core.core import rpc
from dimos.core.module import Module
from dimos.spec.utils import Spec


class UnitreeMoveSpec(Spec, Protocol):
    """Motion + posture primitives (provided by ``UnitreeSkillContainer``)."""

    def relative_move(
        self, forward: float = 0.0, left: float = 0.0, degrees: float = 0.0
    ) -> str: ...

    def execute_sport_command(self, command_name: str) -> str: ...

    def wait(self, seconds: float) -> str: ...


class NavigateSpec(Spec, Protocol):
    """Semantic navigation (provided by ``NavigationSkillContainer``)."""

    def navigate_with_text(self, query: str) -> str: ...


class FollowSpec(Spec, Protocol):
    """Person following (provided by ``PersonFollowSkillContainer``)."""

    def follow_person(
        self,
        query: str,
        initial_bbox: list[float] | None = None,
        initial_image: str | None = None,
    ) -> str: ...


class Go2Primitives(Module):
    """Unified :class:`PrimitiveSkillsSpec` facade over the real Go2 skills.

    dimOS injects the three sub-specs; each ``@rpc`` method forwards verbatim so
    the injected proxy the sandbox receives is signature-identical to the mock.
    """

    _move: UnitreeMoveSpec
    _nav: NavigateSpec
    _follow: FollowSpec

    @rpc
    def relative_move(
        self, forward: float = 0.0, left: float = 0.0, degrees: float = 0.0
    ) -> str:
        return self._move.relative_move(forward=forward, left=left, degrees=degrees)

    @rpc
    def navigate_with_text(self, query: str) -> str:
        return self._nav.navigate_with_text(query)

    @rpc
    def follow_person(
        self,
        query: str,
        initial_bbox: list[float] | None = None,
        initial_image: str | None = None,
    ) -> str:
        return self._follow.follow_person(
            query, initial_bbox=initial_bbox, initial_image=initial_image
        )

    @rpc
    def execute_sport_command(self, command_name: str) -> str:
        return self._move.execute_sport_command(command_name)

    @rpc
    def wait(self, seconds: float) -> str:
        return self._move.wait(seconds)
