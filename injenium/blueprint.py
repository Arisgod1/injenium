# Copyright 2026 Injenium
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0

"""Blueprints registered as ``dimos.blueprints`` entry points (spec §1).

Two runnable blueprints are exposed:

* ``injenium_market`` — headless: just the market skills, the request
  listener, and a mock primitive provider. It imports no robot-only deps so it
  loads on any box (this is the interface-acceptance target: ``dimos mcp
  list-tools`` / ``dimos mcp call``).
* ``injenium_agentic`` — the full Go2 agentic stack (spatial + MCP
  server/client + common skills) with the market modules and the real
  ``Go2Primitives`` provider added, and the system prompt extended with the
  market briefing.

The agentic blueprint pulls in heavy robot dependencies, so it is built lazily
through module ``__getattr__`` (PEP 562): importing this module for the market
blueprint never triggers those imports. dimOS resolves each entry point by
attribute access at ``dimos run`` time, so the lazy build is transparent.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from injenium.listener import RequestListener
from injenium.primitives import MockPrimitives
from injenium.prompt import market_system_prompt
from injenium.skills import MarketSkillContainer

if TYPE_CHECKING:
    from dimos.core.coordination.blueprints import Blueprint

# Headless market-only blueprint (no robot deps) — safe to import anywhere.
from dimos.core.coordination.blueprints import autoconnect  # noqa: E402

injenium_market: Blueprint = autoconnect(
    MarketSkillContainer.blueprint(),
    RequestListener.blueprint(),
    MockPrimitives.blueprint(),
)


def _build_agentic() -> Blueprint:
    """Compose the full Go2 agentic stack + market modules (heavy imports)."""
    from dimos.agents.mcp.mcp_client import McpClient
    from dimos.agents.mcp.mcp_server import McpServer
    from dimos.robot.unitree.go2.blueprints.agentic._common_agentic import (
        _common_agentic,
    )
    from dimos.robot.unitree.go2.blueprints.smart.unitree_go2_spatial import (
        unitree_go2_spatial,
    )

    from injenium.primitives_go2 import Go2Primitives

    return autoconnect(
        unitree_go2_spatial,
        McpServer.blueprint(),
        McpClient.blueprint(system_prompt=market_system_prompt()),
        _common_agentic,
        Go2Primitives.blueprint(),
        MarketSkillContainer.blueprint(),
        RequestListener.blueprint(),
    )


def __getattr__(name: str) -> object:
    # PEP 562 lazy attribute: build the robot-heavy blueprint only on access.
    if name == "injenium_agentic":
        return _build_agentic()
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
