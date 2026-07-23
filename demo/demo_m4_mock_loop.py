#!/usr/bin/env python3
# Copyright 2026 Injenium
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0

"""M4 demo — full mock closed loop (publish -> answer -> run -> pay -> rate).

Manual, interface-level demonstration (spec §接口验收: ``demo_`` prefix). Two
:class:`MockChain` clients ("dog A" the requester, "dog B" the responder) share
one file-backed ledger, so this exercises the exact ``ChainClient`` call
sequence that the real ``InjectiveClient`` will replay on the testnet (M5).

The steps mirror the four market skills:

    A.publish_request  ->  B.distill_and_publish  ->  A.fetch_and_run  ->  A.pay

Recipe distillation reuses M2 when a recorded store is available; otherwise a
small hand-built recipe stands in, so the loop runs anywhere.

Run with the host runtime's Python::

    /Users/arisone/projects/dimos/.venv/bin/python demo/demo_m4_mock_loop.py
"""

from __future__ import annotations

import argparse
from pathlib import Path
import sys
import tempfile

from injenium.chain.base import inj_to_wei, wei_to_inj
from injenium.chain.mock_chain import MockChain
from injenium.distill import distill_to_recipe
from injenium.distill.recipe import Recipe, Step
from injenium.primitives import MockPrimitiveExecutor
from injenium.sandbox import SandboxInterpreter

DOG_A = "0xA0000000000000000000000000000000000000A0"  # requester
DOG_B = "0xB0000000000000000000000000000000000000B0"  # responder

_DB_CANDIDATES = (
    Path("data/go2_short.db"),
    Path.home() / "projects/dimos/data/go2_short.db",
    Path(__file__).resolve().parents[2] / "dimos/data/go2_short.db",
)


def _find_db(explicit: str | None) -> Path | None:
    if explicit:
        p = Path(explicit).expanduser()
        return p if p.exists() else None
    return next((c for c in _DB_CANDIDATES if c.exists()), None)


def _make_recipe(db: Path | None, need: str, artifacts_dir: str) -> tuple[Recipe, str]:
    """Distil from a real store if we have one, else build a stand-in recipe."""
    if db is not None:
        print(f"  (distilling from {db})")
        return distill_to_recipe(
            db_path=str(db),
            intent=need,
            artifacts_dir=artifacts_dir,
            query=need,
            success_criteria=need,
        )
    print("  (no recording found; using a hand-built stand-in recipe)")
    recipe = Recipe(
        intent=need,
        steps=[
            Step(primitive="execute_sport_command", params={"command_name": "BalanceStand"}),
            Step(primitive="relative_move", params={"forward": 0.8, "left": 0.0, "degrees": 0.0}),
            Step(primitive="navigate_with_text", params={"query": "the doorway"}),
        ],
        success_criteria=need,
    )
    recipe_dir = str(Path(artifacts_dir) / "standin-recipe")
    recipe.save(recipe_dir)
    return recipe, recipe_dir


def main() -> None:
    parser = argparse.ArgumentParser(description="M4 mock closed-loop demo")
    parser.add_argument("--db", default=None, help="optional recorded memory2 store")
    parser.add_argument("--budget", type=float, default=2.5, help="escrow bounty in INJ")
    args = parser.parse_args()

    workdir = Path(tempfile.mkdtemp(prefix="go2inj_m4_"))
    state_path = workdir / "market_state.json"
    artifacts_dir = str(workdir / "recipes")
    need = "climb the loading ramp I keep slipping on"
    db = _find_db(args.db)

    # One shared ledger, two clients acting as the two dogs.
    chain_a = MockChain(state_path=state_path, address=DOG_A)
    chain_b = MockChain(state_path=state_path, address=DOG_B)

    print(f"== M4 mock closed loop ==\nledger: {state_path}\n")
    b0 = chain_b.balance_of(DOG_B)

    # 1) Dog A publishes a hard request and locks the escrow (publish_request).
    #    The mock ledger seeds A on this first debit, so we read A's balance
    #    *after* publish to get a stable post-escrow baseline.
    budget_wei = inj_to_wei(args.budget)
    request_id = chain_a.publish_request(need, budget_wei, tags=["locomotion"])
    a_after_publish = chain_a.balance_of(DOG_A)
    print(f"[A] publish_request -> {request_id} (escrow {args.budget} INJ locked)")

    # 2) Dog B's listener would surface this; here we poll directly, then
    #    distil a recipe and submit an offer (distill_and_publish).
    open_reqs = chain_b.list_open_requests()
    assert any(r.id == request_id for r in open_reqs), "B cannot see A's open request"
    req = chain_b.get_request(request_id)
    recipe, recipe_dir = _make_recipe(db, req.need, artifacts_dir)
    recipe_hash = recipe.content_hash()
    offer_id = chain_b.submit_offer(
        request_id=request_id,
        recipe_uri=recipe_dir,
        recipe_hash=recipe_hash,
        price=req.budget,
    )
    print(f"[B] distill_and_publish -> offer {offer_id} "
          f"({len(recipe.steps)} steps, hash 0x{recipe_hash[:12]}…)")

    # 3) Dog A verifies the hash and sandbox-validates the recipe *before*
    #    accepting it on-chain, then runs it (fetch_and_run).
    offer = chain_a.get_offer(offer_id)
    from injenium.distill import load_recipe

    fetched = load_recipe(offer.recipe_uri)
    if fetched.content_hash() != offer.recipe_hash:
        sys.exit("[A] hash mismatch — refusing offer")
    executor = MockPrimitiveExecutor()
    interp = SandboxInterpreter(executor)
    problems = interp.validate(fetched)
    if problems:
        sys.exit(f"[A] recipe refused by sandbox: {'; '.join(problems)}")
    chain_a.accept_offer(offer_id)
    report = interp.run(fetched)
    print(f"[A] fetch_and_run -> ok={report.ok}, {len(executor.calls)} primitive call(s)")
    assert report.ok, "recipe execution failed"

    # 4) Dog A releases escrow to B and rates the recipe (pay).
    release_ref = chain_a.release_payment(offer_id)
    chain_a.rate(offer_id, ratee=offer.responder, score=5)
    print(f"[A] pay -> released escrow to B (tx {release_ref}), rated 5/5")

    # Final ledger state.
    a1, b1 = chain_a.balance_of(DOG_A), chain_b.balance_of(DOG_B)
    settled = chain_a.get_request(request_id)
    print("\n-- ledger --")
    print(f"request {request_id}: status={settled.status.value}")
    print(f"dog A balance (post-escrow -> final): "
          f"{wei_to_inj(a_after_publish)} -> {wei_to_inj(a1)} INJ")
    print(f"dog B balance (before -> after payment): "
          f"{wei_to_inj(b0)} -> {wei_to_inj(b1)} INJ")
    print(f"ratings written: {len(chain_a.ratings())}")

    # Escrow was debited from A at publish and released to B at pay; A is not
    # touched again on release, so its post-escrow balance is unchanged.
    assert b1 - b0 == budget_wei, "responder should have received the bounty"
    assert a1 == a_after_publish, "requester's balance changed after escrow release"
    assert settled.status.value == "settled", "request should be settled"

    # 5) Cancel path: a fresh request's escrow is refunded by cancel_request.
    refund_budget = inj_to_wei(1.0)
    cancel_id = chain_a.publish_request(need + " (cancel me)", refund_budget, tags=[])
    a_pre_cancel = chain_a.balance_of(DOG_A)
    chain_a.cancel_request(cancel_id)
    a_post_cancel = chain_a.balance_of(DOG_A)
    assert a_post_cancel - a_pre_cancel == refund_budget, "escrow should be refunded"
    assert chain_a.get_request(cancel_id).status.value == "cancelled"
    print(f"[A] cancel_request -> {cancel_id}, escrow refunded to A")

    print("\nM4 OK: publish -> answer -> run -> pay -> rate closed on the mock chain.")
    print(f"(inspect artifacts under {workdir})")


if __name__ == "__main__":
    main()
