#!/usr/bin/env python3
# Copyright 2026 Injenium
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0

"""Deploy Market.sol via web3.py — a fallback for when ``forge create`` cannot
complete the TLS handshake with the RPC.

Observed against the Injective testnet endpoint: ``curl`` and ``web3.py`` (both
OpenSSL) reach it fine, but ``forge``'s Rust TLS stack fails the handshake every
time. Since ``forge build`` (local compile) still works, we take the compiled
artifact and send the deploy tx over the same web3 path the closed loop uses,
retrying around the endpoint's occasional handshake resets.

    (cd contracts && forge build)                 # produces out/Market.sol/Market.json
    INJECTIVE_PRIVATE_KEY=0x... python contracts/deploy_web3.py --network testnet
"""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import sys
import time

from web3 import Web3

# network -> (rpc_url, chain_id, explorer_base)
NETS = {
    "testnet": (
        "https://k8s.testnet.json-rpc.injective.network/",
        1439,
        "https://testnet.blockscout.injective.network",
    ),
    "mainnet": (
        "https://sentry.evm-rpc.injective.network/",
        1776,
        "https://blockscout.injective.network",
    ),
}


def _retry(fn, what: str, n: int = 12, delay: float = 3.0):
    """Retry ``fn`` around the endpoint's flaky TLS handshake (connect-time)."""
    last: Exception | None = None
    for i in range(n):
        try:
            return fn()
        except Exception as exc:  # noqa: BLE001 - handshake EOF is not a typed error
            last = exc
            print(f"  {what}: retry {i + 1}/{n} ({type(exc).__name__}: {str(exc)[:50]})")
            time.sleep(delay)
    raise SystemExit(f"{what} failed after {n} retries: {last}")


def main() -> None:
    p = argparse.ArgumentParser(description="Deploy Market.sol via web3.py (forge-TLS fallback)")
    p.add_argument("--network", choices=sorted(NETS), default="testnet")
    p.add_argument("--rpc-url", default=None)
    p.add_argument("--chain-id", type=int, default=None)
    p.add_argument("--key", default=os.environ.get("INJECTIVE_PRIVATE_KEY"))
    p.add_argument("--artifact", default="contracts/out/Market.sol/Market.json")
    args = p.parse_args()

    rpc, chain_id, explorer = NETS[args.network]
    rpc = args.rpc_url or rpc
    chain_id = args.chain_id or chain_id
    if not args.key:
        sys.exit("set INJECTIVE_PRIVATE_KEY (or pass --key)")
    art_path = Path(args.artifact)
    if not art_path.exists():
        sys.exit(f"artifact not found: {art_path} — run `forge build` in contracts/ first")

    art = json.loads(art_path.read_text())
    abi, bytecode = art["abi"], art["bytecode"]["object"]

    w3 = Web3(Web3.HTTPProvider(rpc, request_kwargs={"timeout": 30}))
    acct = w3.eth.account.from_key(args.key)
    print(f"deploying Market.sol -> {args.network} (chain {chain_id}) as {acct.address}")

    market = w3.eth.contract(abi=abi, bytecode=bytecode)
    nonce = _retry(lambda: w3.eth.get_transaction_count(acct.address), "nonce")
    gas_price = _retry(lambda: w3.eth.gas_price, "gas_price")
    tx = _retry(
        lambda: market.constructor().build_transaction(
            {"chainId": chain_id, "from": acct.address, "nonce": nonce, "gasPrice": gas_price}
        ),
        "build+estimate_gas",
    )
    signed = acct.sign_transaction(tx)
    tx_hash = _retry(lambda: w3.eth.send_raw_transaction(signed.raw_transaction), "broadcast")
    print(f"  tx: {w3.to_hex(tx_hash)}")
    receipt = _retry(
        lambda: w3.eth.wait_for_transaction_receipt(tx_hash, timeout=180), "receipt"
    )
    addr = receipt["contractAddress"]
    print(f"\nDeployed to: {addr}")
    print(f"Explorer:    {explorer}/address/{addr}")
    print(
        "\nRun the closed loop:\n"
        f"  python demo/demo_m5_onchain.py --rpc-url {rpc} --chain-id {chain_id} \\\n"
        f"    --contract {addr} --key-a $INJECTIVE_PRIVATE_KEY --key-b $INJECTIVE_PRIVATE_KEY"
    )


if __name__ == "__main__":
    main()
