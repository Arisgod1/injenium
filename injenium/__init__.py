# Copyright 2026 Injenium
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0

"""Injenium (灵枢) — an on-chain skill economy: skills are the core, embodiments the extension (PoC).

The domain-neutral market kernel lives in ``injenium.core`` (chain/contract,
recipes, sandbox, identity, blueprint factory — no robot code). Each embodiment
plugs in as a domain under ``injenium.domains.<domain>``; the Unitree Go2 robot
dog is the first reference domain. Public surface is intentionally small —
everything the host runtime needs is reachable through the ``dimos.blueprints``
entry points defined in ``pyproject.toml`` (``injenium.domains.go2.blueprint``).
"""

from __future__ import annotations

__all__ = ["__version__"]

__version__ = "0.1.0"
