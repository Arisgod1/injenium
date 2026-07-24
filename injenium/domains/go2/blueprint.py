# Copyright 2026 Injenium
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0

"""Go2 domain blueprints, registered as ``dimos.blueprints`` entry points.

Both blueprints are assembled through :func:`injenium.core.blueprint.build_market`:

* ``injenium_market`` — headless: market skills + request listener + a mock
  primitive provider + an ``McpServer``. No robot-only deps, so it loads on any
  box and its skills are drivable with no LLM (``dimos mcp list-tools`` /
  ``dimos mcp call``) — the interface-acceptance target.
* ``injenium_agentic`` — the full Go2 agentic stack (spatial + MCP server/client
  + common skills) with the real ``Go2Primitives`` provider and the market
  briefing appended to the system prompt. Built lazily (PEP 562) so the heavy
  robot imports never fire for the headless blueprint.

Importing this module imports the ``injenium.domains.go2`` package, whose
``__init__`` registers the Go2 primitives + distiller into the core.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import injenium.domains.go2  # noqa: F401 -- ensures primitives + distiller are registered
from injenium.core.blueprint import build_market
from injenium.core.prompt import market_system_prompt
from injenium.domains.go2.providers import MockPrimitives

if TYPE_CHECKING:
    from dimos.core.coordination.blueprints import Blueprint

injenium_market: Blueprint = build_market(provider_blueprint=MockPrimitives.blueprint())


def _build_agentic() -> Blueprint:
    """Compose the full Go2 agentic stack + market modules (heavy imports)."""
    from dimos.agents.mcp.mcp_client import McpClient
    from dimos.robot.unitree.go2.blueprints.agentic._common_agentic import (
        _common_agentic,
    )
    from dimos.robot.unitree.go2.blueprints.smart.unitree_go2_spatial import (
        unitree_go2_spatial,
    )

    from injenium.domains.go2.providers_go2 import Go2Primitives

    return build_market(
        provider_blueprint=Go2Primitives.blueprint(),
        extra=(
            unitree_go2_spatial,
            McpClient.blueprint(system_prompt=market_system_prompt()),
            _common_agentic,
        ),
    )


def __getattr__(name: str) -> object:
    # PEP 562 lazy attribute: build the robot-heavy blueprint only on access.
    if name == "injenium_agentic":
        return _build_agentic()
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
