# Injenium · 灵枢

[English](README.md) | [中文](README.zh-CN.md)

**Injenium** (灵枢) — the on-chain skill economy for embodied machines, settled on Injective.

A robot-dog skill marketplace, packaged as an external **dimOS** blueprint (zero
source-modification of dimOS, registered through the `dimos.blueprints` entry
point). Dogs publish "hard-request" needs on-chain, distill their own recorded
memory into parameterized **recipes**, answer requests, run fetched recipes in a
whitelisted **sandbox** that only calls on-board primitive skills, and settle
payment through an on-chain escrow with two-way ratings. A fetched recipe is
hash-checked and sandbox-validated **before** the offer is accepted on-chain,
and a requester can always reclaim a stuck escrow through the cancel/refund path.

Target chain: **Injective EVM testnet** (Chain ID `1439`). A file-backed
**mock chain** implements the same `ChainClient` protocol so the whole closed
loop runs before any real deployment.

## Market skills

The agent uses a read-only `chain_status` self-check plus four loop-driving
dimOS `@skill`s — discoverable via `dimos mcp list-tools`, callable via
`dimos mcp call`:

| skill | what it does |
| --- | --- |
| `chain_status()` | **read-only** self-check: report the wallet, its balance, and whether the chain is reachable (answers "can you go on-chain?") — spends nothing, locks no escrow |
| `publish_request(need, budget)` | register a hard-request and lock `budget` INJ in escrow |
| `distill_and_publish(request_id, query)` | distill a de-privatized recipe from recorded memory, post an offer carrying its content hash |
| `fetch_and_run(offer_id)` | verify the recipe hash + sandbox-validate it, **then** accept on-chain and run it |
| `pay(offer_id)` | release the escrow to the responder and write a rating |

`fetch_and_run` refuses — **without touching the chain** — on a hash mismatch or
any sandbox violation, so a bad offer never strands a request in `Answered`.
Escrow that would otherwise be stuck is reclaimable by the requester through
`ChainClient.cancel_request` / `Market.sol::cancelRequest` (open requests
immediately; answered-but-unsettled ones after the cancel timeout).

## Install & run

```bash
pip install -e '.[chain]'          # editable install into the dimOS runtime's Python (not on PyPI); [chain]=web3>=7 for the real path

# full go2 agentic stack + market skills:
dimos run injenium.agentic

# headless, server-only (no robot, no LLM key) — for interface acceptance:
dimos run injenium.market
dimos mcp list-tools               # the market skills appear (incl. chain_status)
```

### Wallet identity

Each robot boots with a fixed `ROBOT_IP` (e.g. `10.88.15.25`); the agent derives
one deterministic wallet from it (`key = sha256(WALLET_SALT ‖ ROBOT_IP)`), used as
both the mock-ledger identity and the testnet signing wallet — no per-robot key
wrangling. Set `WALLET_SALT` (a deployment secret) so the key can't be rebuilt
from the LAN-visible IP. An explicit `INJECTIVE_PRIVATE_KEY` always overrides; on
mainnet (chain id `1776`) IP derivation is refused and a real
`INJECTIVE_PRIVATE_KEY` is required.

## Demos (manual, `demo_` prefix — never auto-collected)

Run with the host runtime's Python (the one that provides `dimos`):

```bash
python demo/demo_m2_distill.py     # M2: recorded memory -> de-privatized recipe + template
python demo/demo_m3_sandbox.py     # M3: recipe drives whitelisted primitives; unsafe steps refused
python demo/demo_m4_mock_loop.py   # M4: publish -> answer -> run -> pay -> rate on the mock chain
```

`demo_m2`/`demo_m4` auto-locate `data/go2_short.db` (repo or the dimOS checkout);
pass `--db /path/to/go2_short.db` to override.

## Contract (M5)

`contracts/src/Market.sol` mirrors `chain/client.py::MARKET_ABI`; deploy to the
Injective EVM testnet and verify on Blockscout with Foundry (see the header of
`contracts/foundry.toml`), then switch the agent to the real chain with
`-o marketskillcontainer.chain_backend=injective -o marketskillcontainer.market_contract=0x…` (same on `requestlistener`).

To run this on a real robot dog, follow `INTEGRATION.md` (step-by-step commands,
including how to adapt it to a non-Go2 robot). Layered testing is in `TESTING.md`.

See `spec.md` (repo root) for the full design and milestones. Verification is
interface-level only — no unit tests / no TDD by project policy.
