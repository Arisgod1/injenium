#!/usr/bin/env python3
# Copyright 2026 Injenium
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0

"""M2 demo — distill a recorded memory into a de-privatized recipe.

Manual, interface-level demonstration (spec §接口验收: ``demo_`` prefix, not
part of any automated suite). Reads a recorded ``dimos.memory2`` store and runs
``distill_to_recipe`` (extractor + privacy + recipe), then prints a
human-auditable summary of the produced artifact.

Run with the host runtime's Python (the one that provides ``dimos``), e.g.::

    /Users/arisone/projects/dimos/.venv/bin/python demo/demo_m2_distill.py

Optionally point at a specific store / output dir::

    python demo/demo_m2_distill.py --db /path/to/go2_short.db --out ./demo_artifacts
"""

from __future__ import annotations

import argparse
from pathlib import Path
import sys

from injenium.distill import distill_to_recipe, load_recipe

# Candidate locations for the PoC recording (spec assumption: repo go2_short.db).
_DB_CANDIDATES = (
    Path("data/go2_short.db"),
    Path.home() / "projects/dimos/data/go2_short.db",
    Path(__file__).resolve().parents[2] / "dimos/data/go2_short.db",
)


def _find_db(explicit: str | None) -> Path:
    if explicit:
        p = Path(explicit).expanduser()
        if not p.exists():
            sys.exit(f"memory store not found: {p}")
        return p
    for cand in _DB_CANDIDATES:
        if cand.exists():
            return cand
    sys.exit(
        "could not locate go2_short.db; pass --db /path/to/go2_short.db "
        f"(looked in: {', '.join(str(c) for c in _DB_CANDIDATES)})"
    )


def main() -> None:
    parser = argparse.ArgumentParser(description="M2 distillation demo")
    parser.add_argument("--db", default=None, help="recorded memory2 SQLite store")
    parser.add_argument(
        "--out", default="demo_artifacts", help="artifacts output directory"
    )
    parser.add_argument(
        "--intent",
        default="navigate the recorded route to the target and stop",
        help="the human intent this recipe fulfils",
    )
    parser.add_argument(
        "--query",
        default="target object at the end of the route",
        help="semantic frame-selection query",
    )
    parser.add_argument(
        "--templates", type=int, default=1, help="object-template count to extract"
    )
    args = parser.parse_args()

    db_path = _find_db(args.db)
    print(f"== M2 distill ==\nmemory store : {db_path}")

    recipe, recipe_dir = distill_to_recipe(
        db_path=str(db_path),
        intent=args.intent,
        artifacts_dir=args.out,
        query=args.query,
        success_criteria=args.intent,
        template_count=args.templates,
    )

    print(f"recipe dir   : {recipe_dir}")
    print(f"content hash : 0x{recipe.content_hash()}")
    print(f"intent       : {recipe.intent}")
    print(f"steps        : {len(recipe.steps)}")
    print(f"rel_waypoints: {len(recipe.rel_waypoints)}")
    print(f"templates    : {len(recipe.object_templates)}")

    print("\nfirst steps:")
    for i, step in enumerate(recipe.steps[:6]):
        print(f"  [{i}] {step.primitive}({step.params})")
    if len(recipe.steps) > 6:
        print(f"  ... (+{len(recipe.steps) - 6} more)")

    for tpl in recipe.object_templates:
        artifact = Path(recipe_dir) / tpl.image_path
        exists = "OK" if artifact.exists() else "MISSING"
        print(f"\ntemplate {tpl.name!r}: {artifact} [{exists}]")

    # Prove the artifact round-trips and the whitelist holds.
    reloaded = load_recipe(recipe_dir)
    problems = reloaded.validate_whitelist()
    assert reloaded.content_hash() == recipe.content_hash(), "hash mismatch on reload"
    print(
        "\nreload round-trip: hash stable, "
        + ("whitelist clean" if not problems else f"PROBLEMS: {problems}")
    )
    print("\nM2 OK: recipe distilled, de-privatized, saved, and re-loadable.")


if __name__ == "__main__":
    main()
