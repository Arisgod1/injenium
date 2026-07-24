# Copyright 2026 Injenium
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0

"""Assemble a runnable market blueprint from a capability domain's parts.

``build_market`` wires the domain-neutral market modules (skills + request
listener + an ``McpServer`` so skills are drivable with no LLM) with a domain's
primitive **provider** and any ``extra`` atoms (the robot stack, an LLM client,
…). A domain builds both its headless and agentic blueprints through this one
factory, so adding a domain never touches the core.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from dimos.core.coordination.blueprints import Blueprint


def build_market(
    *,
    provider_blueprint: Any,
    extra: tuple[Any, ...] | list[Any] = (),
    with_mcp: bool = True,
) -> Blueprint:
    """Compose ``MarketSkillContainer`` + ``RequestListener`` + a primitive
    provider (+ ``McpServer`` + ``extra``) into an autoconnected blueprint.

    Args:
        provider_blueprint: the domain's primitive-provider blueprint atom
            (e.g. ``MockPrimitives.blueprint()`` or ``Go2Primitives.blueprint()``).
        extra: additional blueprint atoms (robot stack, ``McpClient``, …).
        with_mcp: include an ``McpServer`` so the skills are reachable over the
            MCP HTTP surface (``dimos mcp``) with no LLM in the loop.
    """
    from dimos.core.coordination.blueprints import autoconnect

    from injenium.core.listener import RequestListener
    from injenium.core.skills import MarketSkillContainer

    atoms: list[Any] = [
        MarketSkillContainer.blueprint(),
        RequestListener.blueprint(),
        provider_blueprint,
    ]
    if with_mcp:
        from dimos.agents.mcp.mcp_server import McpServer

        atoms.append(McpServer.blueprint())
    atoms.extend(extra)
    return autoconnect(*atoms)
