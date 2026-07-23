# Copyright 2026 Injenium
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0

"""Validate a :class:`~injenium.distill.recipe.Recipe` and run it safely.

This is the executable trust boundary (spec §4). The interpreter:

* rejects any step whose ``primitive`` is not in
  :data:`~injenium.specs.PRIMITIVE_WHITELIST`;
* type/range/choice/length-checks every parameter against that primitive's
  :class:`~injenium.specs.ParamSpec` rules;
* dispatches surviving steps to a locally injected
  :class:`~injenium.specs.PrimitiveSkillsSpec` provider through an explicit
  typed switch — **never** ``getattr``/``eval`` on recipe-supplied names.

A recipe that fails validation is refused wholesale before any primitive runs
(``strict`` mode), so a malformed or malicious step never reaches the robot.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from injenium.distill.recipe import Recipe, Step
from injenium.specs import (
    PRIMITIVE_WHITELIST,
    ParamSpec,
    PrimitiveSkillsSpec,
    PrimitiveSpec,
)


class RecipeValidationError(ValueError):
    """Raised when a recipe fails whitelist/param validation in strict mode."""

    def __init__(self, problems: list[str]) -> None:
        self.problems = problems
        super().__init__("; ".join(problems) if problems else "invalid recipe")


@dataclass
class StepResult:
    """Outcome of a single executed (or skipped) step."""

    index: int
    primitive: str
    params: dict[str, Any]
    ok: bool
    detail: str

    def __str__(self) -> str:
        status = "ok" if self.ok else "FAIL"
        return f"[{self.index}] {self.primitive}({self.params}) -> {status}: {self.detail}"


@dataclass
class RunReport:
    """Aggregate result of running a recipe through the sandbox."""

    ok: bool
    steps: list[StepResult] = field(default_factory=list)
    message: str = ""

    def summary(self) -> str:
        head = "SUCCESS" if self.ok else "FAILED"
        lines = [f"sandbox run {head}: {self.message}".rstrip(": ")]
        lines.extend(f"  {s}" for s in self.steps)
        return "\n".join(lines)


class SandboxInterpreter:
    """Runs whitelisted recipe steps against an injected primitive provider.

    Args:
        primitives: the on-board primitive provider (injected via
            :class:`PrimitiveSkillsSpec`; the mock provider for demos).
        strict: when ``True`` (default) any validation problem aborts the run
            before executing a single step; when ``False`` valid steps still
            run and invalid ones are reported as failed.
    """

    def __init__(
        self, primitives: PrimitiveSkillsSpec, *, strict: bool = True
    ) -> None:
        self._primitives = primitives
        self._strict = strict

    # -- validation ----------------------------------------------------------

    def validate(self, recipe: Recipe) -> list[str]:
        """Return a list of human-readable problems (empty == safe to run)."""
        problems: list[str] = []
        if not recipe.steps:
            problems.append("recipe has no steps")
        for i, step in enumerate(recipe.steps):
            problems.extend(f"step[{i}]: {p}" for p in self._validate_step(step))
        return problems

    def _validate_step(self, step: Step) -> list[str]:
        spec = PRIMITIVE_WHITELIST.get(step.primitive)
        if spec is None:
            return [f"unknown primitive {step.primitive!r}"]
        return self._validate_params(spec, step.params)

    @staticmethod
    def _validate_params(spec: PrimitiveSpec, params: dict[str, Any]) -> list[str]:
        problems: list[str] = []
        allowed = {p.name for p in spec.params}
        for key in params:
            if key not in allowed:
                problems.append(f"unexpected param {key!r}")
        for ps in spec.params:
            if ps.name not in params:
                if ps.required:
                    problems.append(f"missing required param {ps.name!r}")
                continue
            problems.extend(_check_value(ps, params[ps.name]))
        return problems

    # -- execution -----------------------------------------------------------

    def run(self, recipe: Recipe) -> RunReport:
        """Validate then execute ``recipe``; return a per-step report.

        In strict mode a non-empty validation raises
        :class:`RecipeValidationError` before any primitive is invoked.
        """
        problems = self.validate(recipe)
        if problems and self._strict:
            raise RecipeValidationError(problems)

        results: list[StepResult] = []
        for i, step in enumerate(recipe.steps):
            step_problems = self._validate_step(step)
            if step_problems:
                results.append(
                    StepResult(i, step.primitive, dict(step.params), False,
                               "; ".join(step_problems))
                )
                continue
            try:
                detail = self._dispatch(step)
                results.append(
                    StepResult(i, step.primitive, dict(step.params), True, str(detail))
                )
            except Exception as exc:  # a primitive failing is a run failure, not a crash
                results.append(
                    StepResult(i, step.primitive, dict(step.params), False, repr(exc))
                )

        ok = bool(results) and all(r.ok for r in results)
        message = (
            f"executed {len(results)} step(s)"
            if ok
            else "one or more steps failed or were rejected"
        )
        return RunReport(ok=ok, steps=results, message=message)

    def _dispatch(self, step: Step) -> str:
        """Explicit typed switch — no reflection on recipe-supplied names."""
        p = self._primitives
        prim = step.primitive
        params = _coerced_kwargs(PRIMITIVE_WHITELIST[prim], step.params)
        if prim == "relative_move":
            return p.relative_move(
                forward=params.get("forward", 0.0),
                left=params.get("left", 0.0),
                degrees=params.get("degrees", 0.0),
            )
        if prim == "navigate_with_text":
            return p.navigate_with_text(query=params["query"])
        if prim == "follow_person":
            return p.follow_person(
                query=params["query"],
                initial_bbox=params.get("initial_bbox"),
            )
        if prim == "execute_sport_command":
            return p.execute_sport_command(command_name=params["command_name"])
        if prim == "wait":
            return p.wait(seconds=params["seconds"])
        # Unreachable: validate() already gates the primitive name.
        raise RecipeValidationError([f"unknown primitive {prim!r}"])


def _check_value(ps: ParamSpec, value: Any) -> list[str]:
    """Type/range/choice/length checks for one parameter value."""
    problems: list[str] = []
    if ps.type is float:
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            return [f"param {ps.name!r} must be a number, got {type(value).__name__}"]
        v = float(value)
        if ps.min is not None and v < ps.min:
            problems.append(f"param {ps.name!r}={v} below min {ps.min}")
        if ps.max is not None and v > ps.max:
            problems.append(f"param {ps.name!r}={v} above max {ps.max}")
    elif ps.type is str:
        if not isinstance(value, str):
            return [f"param {ps.name!r} must be a string, got {type(value).__name__}"]
        if ps.choices is not None and value not in ps.choices:
            problems.append(f"param {ps.name!r}={value!r} not in {ps.choices}")
    elif ps.type is list:
        if not isinstance(value, list):
            return [f"param {ps.name!r} must be a list, got {type(value).__name__}"]
        if ps.length is not None and len(value) != ps.length:
            problems.append(f"param {ps.name!r} must have length {ps.length}")
    return problems


def _coerced_kwargs(spec: PrimitiveSpec, params: dict[str, Any]) -> dict[str, Any]:
    """Coerce validated JSON scalars to the exact primitive types (int->float)."""
    out: dict[str, Any] = {}
    types = {p.name: p.type for p in spec.params}
    for key, value in params.items():
        if types.get(key) is float and isinstance(value, (int, float)):
            out[key] = float(value)
        else:
            out[key] = value
    return out
