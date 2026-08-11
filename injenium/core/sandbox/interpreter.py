# Copyright 2026 Injenium
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0

"""Validate a :class:`~injenium.core.recipe.Recipe` and run it safely.

This is the executable trust boundary (spec §4). The interpreter:

* rejects any step whose ``primitive`` is not in the active
  :class:`~injenium.core.registry.PrimitiveRegistry`;
* type/range/choice/length-checks every parameter against that primitive's
  :class:`~injenium.core.registry.ParamSpec` rules;
* dispatches surviving steps through the registered **adapter** for that
  primitive — a callable a *domain author* wrote, invoked as
  ``adapter(provider, params)``. The recipe-supplied name only ever selects a
  pre-registered adapter; it is **never** ``getattr``/``eval``'d onto the
  provider.

A recipe that fails validation is refused wholesale before any primitive runs
(``strict`` mode), so a malformed or malicious step never reaches the robot.
"""

from __future__ import annotations

import threading
from dataclasses import dataclass, field
from typing import Any

from injenium.core.recipe import Recipe, Step
from injenium.core.registry import (
    ParamSpec,
    PrimitiveRegistry,
    PrimitiveSpec,
    default_registry,
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
        primitives: the on-board primitive provider (injected via the domain's
            provider Spec; the mock provider for demos).
        registry: the primitive whitelist + dispatch adapters to enforce; the
            process-wide :data:`~injenium.core.registry.default_registry` a
            domain populated on import, by default.
        strict: when ``True`` (default) any validation problem aborts the run
            before executing a single step; when ``False`` valid steps still
            run and invalid ones are reported as failed.
    """

    def __init__(
        self,
        primitives: Any,
        registry: PrimitiveRegistry = default_registry,
        *,
        strict: bool = True,
    ) -> None:
        self._primitives = primitives
        self._registry = registry
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
        spec = self._registry.spec(step.primitive)
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

    def run(self, recipe: Recipe, *, abort: threading.Event | None = None) -> RunReport:
        """Validate then execute ``recipe``; return a per-step report.

        In strict mode a non-empty validation raises
        :class:`RecipeValidationError` before any primitive is invoked.

        Args:
            recipe: the recipe to validate and execute.
            abort: optional cooperative stop flag checked **between** steps;
                once set, no further primitive is dispatched and the report
                comes back failed with an "aborted" message. The in-flight
                step is never interrupted mid-motion — cancelling it is the
                caller's job (e.g. the robot's own stop skill).
        """
        problems = self.validate(recipe)
        if problems and self._strict:
            raise RecipeValidationError(problems)

        results: list[StepResult] = []
        for i, step in enumerate(recipe.steps):
            if abort is not None and abort.is_set():
                return RunReport(
                    ok=False,
                    steps=results,
                    message=f"aborted before step {i} of {len(recipe.steps)}",
                )
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
        """Call the registered adapter — no reflection on recipe-supplied names."""
        registered = self._registry.get(step.primitive)
        if registered is None:
            # Unreachable: validate() already gates the primitive name.
            raise RecipeValidationError([f"unknown primitive {step.primitive!r}"])
        params = _coerced_kwargs(registered.spec, step.params)
        return registered.dispatch(self._primitives, params)


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
