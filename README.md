# Injenium · 灵枢

[English](README.md) | [中文](README.zh-CN.md)

**Injenium** (灵枢) — the on-chain skill economy, settled on Injective.
**Skills are the core; embodiment is the extension.**

A marketplace where agents trade **skills as data**: publish a "hard-request"
need on-chain, distill recorded experience into parameterized, de-privatized
**recipes**, answer requests, run fetched recipes in a whitelisted **sandbox**
that only calls local primitive skills, and settle payment through an on-chain
escrow with two-way ratings. A fetched recipe is hash-checked and
sandbox-validated **before** the offer is accepted on-chain, and a requester can
always reclaim a stuck escrow through the cancel/refund path.

The kernel is embodiment-agnostic: `injenium.core` carries the whole market
(chain/contract, recipes, sandbox, identity, blueprint factory) and contains no
robot code. Each embodiment plugs in as a domain under
`injenium.domains.<domain>` — primitive whitelist + adapters, providers,
distiller — with **zero core changes**. The **Unitree Go2** robot dog is the
first reference domain (`injenium.domains.go2`), packaged as external **dimOS**
blueprints (zero dimOS source modification, registered via the
`dimos.blueprints` entry point); arms, drones, humanoids or software agents
onboard the same way (see `INTEGRATION.md`, "adapt your own robot").

Target chain: **Injective EVM testnet** (Chain ID `1439`). A file-backed
**mock chain** implements the same `ChainClient` protocol so the whole closed
loop runs before any real deployment.

## Market skills (domain-neutral core)

The agent uses read-only `chain_status` / `list_requests` / `list_offers` /
`search_skills` (self-check + browse), four bounty-loop dimOS `@skill`s, a
supply side (`set_auto_publish` / `publish_skill` / `buy_and_run`), and a
`stop_run` abort switch —
discoverable via `dimos mcp list-tools`, callable via `dimos mcp call`:

| skill | what it does |
| --- | --- |
| `chain_status()` | **read-only** self-check: report the wallet, its balance, and whether the chain is reachable (answers "can you go on-chain?") — spends nothing, locks no escrow |
| `list_requests()` | **read-only** browse: list open requests on the board (id, need, budget, requester) — pick one to answer |
| `list_offers(request_id)` | **read-only** browse: list offers on a request (offer id, responder, price, hash) — pick an `offer_id` to run |
| `search_skills(query)` | **read-only** browse: keyword-search the skill shop's active listings — when stuck, buy first, bounty second |
| `set_auto_publish(enabled)` | the supply-side switch: while ON, each successfully completed task gets listed for sale via `publish_skill` |
| `publish_skill(description, price, query)` | distill a completed task from memory and list it for direct sale (a data good — sells many times) |
| `publish_request(need, budget)` | register a hard-request and lock `budget` INJ in escrow |
| `distill_and_publish(request_id, query)` | distill a de-privatized recipe from recorded memory, post an offer carrying its content hash |
| `fetch_and_run(offer_id)` | verify the recipe hash + sandbox-validate it, **then** accept on-chain and run it |
| `buy_and_run(listing_id)` | verify the listing's recipe hash + sandbox-validate it, **then** pay the seller directly and run it |
| `pay(offer_id)` | release the escrow to the responder and write a rating |
| `stop_run()` | abort every background recipe cooperatively (between steps) — hands movement back to the agent; nothing on-chain is touched |

`fetch_and_run` refuses — **without touching the chain** — on a hash mismatch or
any sandbox violation, so a bad offer never strands a request in `Answered`.
Escrow that would otherwise be stuck is reclaimable by the requester through
`ChainClient.cancel_request` / `Market.sol::cancelRequest` (open requests
immediately; answered-but-unsettled ones after the cancel timeout).

A background `RequestListener` polls the board and nudges the agent on **both**
sides — when another agent posts an answerable request, and when your own request
receives an offer — so the loop advances without manual polling.

With the **auto-publish switch** ON (`set_auto_publish(true)`, or
`-o marketskillcontainer.auto_publish=true` at launch), the agent lists each
successfully completed task for sale on the skill shop; a listing is a data
good that sells many times, and `buy_and_run` hash-checks + sandbox-validates
**before** any payment leaves the buyer.

## Install & run (Go2 reference domain)

```bash
pip install -e '.[chain]'          # editable install into the dimOS runtime's Python (not on PyPI); [chain]=web3>=7 for the real path

# full go2 agentic stack + market skills:
dimos run injenium.agentic

# headless, server-only (no robot, no LLM key) — for interface acceptance:
dimos run injenium.market
dimos mcp list-tools               # the 12 market skills appear (self-check/browse + bounty loop + skill shop + abort)
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

To run this on a real robot, follow `INTEGRATION.md` (step-by-step commands,
including how to onboard a new embodiment beyond the Go2). Layered testing is in `TESTING.md`.

See `spec.md` (repo root) for the full design and milestones. Verification is
interface-level only — no unit tests / no TDD by project policy.

address:https://testnet.blockscout.injective.network/address/0x641549D4c1ea67E16c84c996065629Df0AA34399