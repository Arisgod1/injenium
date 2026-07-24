# Copyright 2026 Injenium
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0

"""Recipe sandbox: validate a distilled recipe and drive on-board primitives.

The sandbox is the trust boundary for a foreign recipe (spec §4). It never
imports or ``eval``s anything from the recipe — it validates each step against
the primitive whitelist and dispatches type-checked calls to a locally injected
:class:`~injenium.core.specs.PrimitiveSkillsSpec` provider.
"""

from __future__ import annotations

from injenium.core.sandbox.interpreter import (
    RecipeValidationError,
    RunReport,
    SandboxInterpreter,
    StepResult,
)

__all__ = [
    "RecipeValidationError",
    "RunReport",
    "SandboxInterpreter",
    "StepResult",
]
