# Copyright 2026 Injenium
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0

"""Injenium (灵枢) — on-chain skill market for embodied robots (PoC).

An external dimOS package that adds an on-chain skill marketplace to the Unitree
Go2 agent. Public surface is intentionally small — everything the host runtime
needs is reachable through the ``dimos.blueprints`` entry points defined in
``pyproject.toml`` (``injenium.blueprint``).
"""

from __future__ import annotations

__all__ = ["__version__"]

__version__ = "0.1.0"
