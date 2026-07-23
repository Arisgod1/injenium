# Copyright 2026 Injenium
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0

"""Providers that satisfy :class:`~injenium.specs.PrimitiveSkillsSpec`.

The sandbox never reflects into the robot's skill registry — it calls a typed
provider that dimOS injects at blueprint-build time (spec §4). Two providers
exist, mirroring the mock/real split of the chain client:

* :class:`MockPrimitives` — a headless :class:`~dimos.core.module.Module` used
  by the ``injenium.market`` blueprint and the M3/M4 demos. It simulates
  each primitive (logs + returns a human string) so the closed loop runs with
  no robot and no LLM keys.
* ``Go2Primitives`` (in :mod:`injenium.primitives_go2`) — delegates to the
  real Unitree/navigation/person-follow skill modules on the robot. It is kept
  in a separate module so importing this one never drags in robot-only deps.

:class:`MockPrimitiveExecutor` is the plain (non-Module) implementation the
mock module wraps; demos instantiate it directly to inspect the call log
without standing up the coordinator.
"""

from __future__ import annotations

from dataclasses import dataclass

from dimos.core.core import rpc
from dimos.core.module import Module


@dataclass
class PrimitiveCall:
    """One recorded primitive invocation (for demo/inspection)."""

    primitive: str
    args: dict[str, object]


class MockPrimitiveExecutor:
    """Simulates the on-board primitives; records every call.

    Structurally satisfies :class:`PrimitiveSkillsSpec` so it can drive the
    sandbox interpreter directly in a demo. Every method returns the same kind
    of human-readable ``str`` the real skills return.
    """

    def __init__(self) -> None:
        self.calls: list[PrimitiveCall] = []

    def relative_move(
        self, forward: float = 0.0, left: float = 0.0, degrees: float = 0.0
    ) -> str:
        self.calls.append(
            PrimitiveCall(
                "relative_move",
                {"forward": forward, "left": left, "degrees": degrees},
            )
        )
        return (
            f"[mock] moved forward={forward}m left={left}m, "
            f"turned {degrees}deg (goal reached)"
        )

    def navigate_with_text(self, query: str) -> str:
        self.calls.append(PrimitiveCall("navigate_with_text", {"query": query}))
        return f"[mock] navigated to {query!r} (goal reached)"

    def follow_person(
        self,
        query: str,
        initial_bbox: list[float] | None = None,
        initial_image: str | None = None,
    ) -> str:
        self.calls.append(
            PrimitiveCall(
                "follow_person",
                {"query": query, "initial_bbox": initial_bbox},
            )
        )
        return f"[mock] followed person matching {query!r}"

    def execute_sport_command(self, command_name: str) -> str:
        self.calls.append(
            PrimitiveCall("execute_sport_command", {"command_name": command_name})
        )
        return f"[mock] executed sport command {command_name!r}"

    def wait(self, seconds: float) -> str:
        self.calls.append(PrimitiveCall("wait", {"seconds": seconds}))
        return f"[mock] waited {seconds}s"


class MockPrimitives(Module):
    """Headless dimOS provider of :class:`PrimitiveSkillsSpec`.

    Wraps a :class:`MockPrimitiveExecutor`; methods are ``@rpc`` so they are
    reachable through the injected spec proxy from the market container. Signed
    signatures match the spec exactly (that is what the DI annotation check
    verifies at build time).
    """

    @property
    def _executor(self) -> MockPrimitiveExecutor:
        ex = getattr(self, "_mock_executor", None)
        if ex is None:
            ex = MockPrimitiveExecutor()
            self._mock_executor = ex
        return ex

    @rpc
    def relative_move(
        self, forward: float = 0.0, left: float = 0.0, degrees: float = 0.0
    ) -> str:
        return self._executor.relative_move(forward=forward, left=left, degrees=degrees)

    @rpc
    def navigate_with_text(self, query: str) -> str:
        return self._executor.navigate_with_text(query)

    @rpc
    def follow_person(
        self,
        query: str,
        initial_bbox: list[float] | None = None,
        initial_image: str | None = None,
    ) -> str:
        return self._executor.follow_person(
            query, initial_bbox=initial_bbox, initial_image=initial_image
        )

    @rpc
    def execute_sport_command(self, command_name: str) -> str:
        return self._executor.execute_sport_command(command_name)

    @rpc
    def wait(self, seconds: float) -> str:
        return self._executor.wait(seconds)
