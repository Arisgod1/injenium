#!/usr/bin/env python3
# Copyright 2026 Injenium
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0

"""M5 demo — full closed loop against a REAL EVM (anvil or Injective testnet).

Unlike ``demo_m4`` (MockChain), this drives two ``web3.py`` :class:`InjectiveClient`
wallets against a deployed ``Market.sol``, exercising the real on-chain path the
mock cannot: tx signing, gas, event-log id decoding, ``bytes32`` hashing, and the
native-coin escrow transfer.

Defaults target a local anvil node (chain id 31337) with its well-known dev keys,
so it runs with no funds and no secrets::

    anvil &
    (cd contracts && forge create src/Market.sol:Market \
        --rpc-url http://127.0.0.1:8545 --private-key <anvil key0> --broadcast)
    python demo/demo_m5_onchain.py --contract 0x<deployed>

Point it at the Injective testnet with ``--rpc-url``/``--chain-id``/``--contract``
and real, funded keys via ``--key-a``/``--key-b`` (or the ``A_KEY``/``B_KEY`` env).
"""

from __future__ import annotations

import argparse
import os
from pathlib import Path
import sys
import tempfile

from injenium.core.chain.base import inj_to_wei, wei_to_inj
from injenium.core.chain.client import InjectiveClient
from injenium.core.recipe import Recipe, Step, load_recipe
from injenium.domains.go2.providers import MockPrimitiveExecutor
from injenium.core.sandbox import SandboxInterpreter

# anvil defaults — public dev keys, local-only, NOT secrets.
ANVIL_RPC = "http://127.0.0.1:8545"
ANVIL_CHAIN_ID = 31337
ANVIL_KEY_A = "0xac0974bec39a17e36ba4a6b4d238ff944bacb478cbed5efcae784d7bf4f2ff80"
ANVIL_KEY_B = "0x59c6995e998f97a5a0044966f0945389dc9e86dae88c7a8412f4603b6b78690d"


def _standin_recipe(need: str, artifacts_dir: str) -> tuple[Recipe, str]:
    """A small whitelisted recipe, saved locally (shared FS for the PoC)."""
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
    p = argparse.ArgumentParser(description="M5 on-chain closed-loop demo (anvil/testnet)")
    p.add_argument("--rpc-url", default=os.environ.get("INJENIUM_RPC_URL", ANVIL_RPC))
    p.add_argument(
        "--chain-id",
        type=int,
        default=int(os.environ.get("INJENIUM_CHAIN_ID", ANVIL_CHAIN_ID)),
    )
    p.add_argument(
        "--contract",
        default=os.environ.get("INJENIUM_CONTRACT"),
        help="deployed Market.sol address (or INJENIUM_CONTRACT env)",
    )
    p.add_argument("--key-a", default=os.environ.get("A_KEY", ANVIL_KEY_A))
    p.add_argument("--key-b", default=os.environ.get("B_KEY", ANVIL_KEY_B))
    p.add_argument("--budget", type=float, default=0.1, help="escrow bounty (native coin)")
    args = p.parse_args()

    if not args.contract:
        sys.exit("pass --contract 0x<deployed Market address> (or set INJENIUM_CONTRACT)")

    need = "climb the loading ramp"
    workdir = Path(tempfile.mkdtemp(prefix="injenium_m5_"))

    chain_a = InjectiveClient(args.rpc_url, args.contract, args.chain_id, private_key=args.key_a)
    chain_b = InjectiveClient(args.rpc_url, args.contract, args.chain_id, private_key=args.key_b)
    print("== M5 on-chain closed loop ==")
    print(f"rpc={args.rpc_url} chain_id={args.chain_id} contract={args.contract}")
    print(f"A (requester): {chain_a.address}")
    print(f"B (responder): {chain_b.address}\n")

    a0, b0 = chain_a.balance_of(chain_a.address), chain_b.balance_of(chain_b.address)

    # 1) A publishes and locks escrow (real tx).
    request_id = chain_a.publish_request(need, inj_to_wei(args.budget), tags=["locomotion"])
    print(f"[A] publish_request -> request {request_id} (escrow {args.budget})")

    # 2) B distills a recipe (local) and submits an offer (real tx).
    req = chain_b.get_request(request_id)
    recipe, recipe_dir = _standin_recipe(req.need, str(workdir))
    recipe_hash = recipe.content_hash()
    offer_id = chain_b.submit_offer(
        request_id=request_id, recipe_uri=recipe_dir, recipe_hash=recipe_hash, price=req.budget
    )
    print(f"[B] submit_offer -> offer {offer_id} (hash 0x{recipe_hash[:12]}…)")

    # 3) A verifies hash + sandbox-validates BEFORE accepting on-chain, then runs.
    offer = chain_a.get_offer(offer_id)
    fetched = load_recipe(offer.recipe_uri)
    if fetched.content_hash() != offer.recipe_hash:
        sys.exit(f"[A] recipe hash mismatch: {fetched.content_hash()} vs {offer.recipe_hash}")
    executor = MockPrimitiveExecutor()
    interp = SandboxInterpreter(executor)
    problems = interp.validate(fetched)
    if problems:
        sys.exit(f"[A] sandbox refused: {problems}")
    accept_ref = chain_a.accept_offer(offer_id)
    report = interp.run(fetched)
    print(
        f"[A] accept_offer (tx {accept_ref[:12]}…) + fetch_and_run -> "
        f"ok={report.ok}, {len(executor.calls)} primitive call(s)"
    )
    assert report.ok, "recipe execution failed"

    # 4) A releases escrow to B and rates the counterparty (real txs).
    rel = chain_a.release_payment(offer_id)
    rate_ref = chain_a.rate(offer_id, ratee=chain_b.address, score=5)
    print(f"[A] release_payment (tx {rel[:12]}…) + rate 5/5 (tx {rate_ref[:12]}…)")

    # 5) Read state back from the chain.
    a1, b1 = chain_a.balance_of(chain_a.address), chain_b.balance_of(chain_b.address)
    settled = chain_a.get_request(request_id)
    print("\n-- on-chain state --")
    print(f"request {request_id}: status={settled.status.value}")
    print(f"A balance: {wei_to_inj(a0)} -> {wei_to_inj(a1)}  (escrow out + gas)")
    print(f"B balance: {wei_to_inj(b0)} -> {wei_to_inj(b1)}  (+ bounty)")
    assert settled.status.value == "settled", "request should be settled on-chain"
    assert b1 > b0, "responder should have received the bounty"
    print("\nM5 OK: publish -> offer -> accept -> run -> pay -> rate on a real EVM.")
    print(f"(recipe artifacts under {workdir})")


if __name__ == "__main__":
    main()
