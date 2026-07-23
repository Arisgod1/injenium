#!/usr/bin/env python3
# Copyright 2026 Injenium
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0

"""M3 demo — drive on-board primitives from a recipe through the sandbox.

Manual, interface-level demonstration (spec §接口验收: ``demo_`` prefix). Builds
recipes in code and runs them through :class:`SandboxInterpreter` against a
:class:`MockPrimitiveExecutor`, showing that:

* a valid, whitelisted recipe executes step-by-step and records the calls;
* an out-of-range parameter (``wait`` past the limit) is refused;
* a non-whitelisted / unsafe sport command (``BackFlip``) is refused;

before any primitive touches the (simulated) robot.

Run with the host runtime's Python::

    /Users/arisone/projects/dimos/.venv/bin/python demo/demo_m3_sandbox.py
"""

from __future__ import annotations

from injenium.distill.recipe import Recipe, Step
from injenium.primitives import MockPrimitiveExecutor
from injenium.sandbox import RecipeValidationError, SandboxInterpreter


def _valid_recipe() -> Recipe:
    return Recipe(
        intent="approach the target and greet",
        steps=[
            Step(primitive="execute_sport_command", params={"command_name": "BalanceStand"}),
            Step(primitive="relative_move", params={"forward": 1.2, "left": 0.0, "degrees": 15.0}),
            Step(primitive="wait", params={"seconds": 1.0}),
            Step(primitive="navigate_with_text", params={"query": "the blue chair"}),
            Step(primitive="execute_sport_command", params={"command_name": "Hello"}),
        ],
        success_criteria="reached the target and greeted",
    )


def _out_of_range_recipe() -> Recipe:
    return Recipe(
        intent="wait far too long",
        steps=[Step(primitive="wait", params={"seconds": 9999.0})],
    )


def _unsafe_command_recipe() -> Recipe:
    # BalanceStand is fine; BackFlip is not in SAFE_SPORT_COMMANDS -> rejected.
    return Recipe(
        intent="attempt an unsafe acrobatic",
        steps=[
            Step(primitive="execute_sport_command", params={"command_name": "BalanceStand"}),
            Step(primitive="execute_sport_command", params={"command_name": "BackFlip"}),
        ],
    )


def _run_expecting_success(interp: SandboxInterpreter, recipe: Recipe) -> None:
    report = interp.run(recipe)
    print(report.summary())
    assert report.ok, "expected the valid recipe to succeed"


def _run_expecting_refusal(interp: SandboxInterpreter, recipe: Recipe, label: str) -> None:
    try:
        interp.run(recipe)
    except RecipeValidationError as exc:
        print(f"{label}: REFUSED as expected -> {exc}")
        return
    raise AssertionError(f"{label}: expected refusal but the recipe ran")


def main() -> None:
    executor = MockPrimitiveExecutor()
    interp = SandboxInterpreter(executor)  # strict=True by default

    print("== M3 sandbox: valid recipe ==")
    _run_expecting_success(interp, _valid_recipe())
    print(f"\nrecorded {len(executor.calls)} primitive call(s):")
    for call in executor.calls:
        print(f"  - {call.primitive}({call.args})")

    print("\n== M3 sandbox: rejection cases ==")
    _run_expecting_refusal(interp, _out_of_range_recipe(), "out-of-range wait(9999s)")
    _run_expecting_refusal(interp, _unsafe_command_recipe(), "unsafe sport command BackFlip")

    print("\nM3 OK: valid recipe executed; unsafe/out-of-range recipes refused.")


if __name__ == "__main__":
    main()
