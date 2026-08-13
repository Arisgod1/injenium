# Injenium

[English](README.md) | [简体中文](README.zh-CN.md)

**Injenium** is an on-chain skill economy for embodied agents. It turns
recorded experience into privacy-reduced, parameterized `Recipe` data that can
be requested, offered, validated in a whitelist sandbox, executed, and settled
through Injective EVM escrow.

The market kernel is embodiment-neutral. `injenium.core` owns recipes, storage,
identity, sandboxing, market flows, chain clients, and blueprint assembly.
Embodiments are domain plugins under `injenium.domains.<domain>`; the reference
integration is Unitree Go2 in `injenium.domains.go2`. New robot, drone,
humanoid, or software-agent integrations can be added without branching core
logic. See [INTEGRATION.md](INTEGRATION.md).

The primary target is Injective EVM testnet, Chain ID `1439`. A file-backed
mock chain implements the same `ChainClient` protocol, so the complete market
loop can be exercised before deploying or funding a wallet.

## Browser Experience

The `frontend/` workspace is a Chinese-first interactive experience for users
who do not have dimOS or a robot. It includes:

- a skill market with one-click Recipe verification and loading;
- a whitelist sandbox simulator with a Canvas robot path and step results;
- a two-sided bounty market with request, quote, accept, run, release, rating,
  and refund flows;
- local, Injective testnet, and read-only mainnet modes;
- JSON and controlled `ipfs://` Recipe loading;
- browser-only EIP-1193 wallet signing, pending-transaction recovery, and
  mainnet write safeguards;
- a FastAPI companion that never receives private keys, seed phrases, or
  signing authority.

Run it from the repository root:

```bash
uv venv --python 3.12 frontend/.venv
uv pip install --python frontend/.venv/bin/python -e . -r frontend/server/requirements.txt
cd frontend
npm install
npm run dev
```

Open <http://127.0.0.1:5173>. The companion API is available at
<http://127.0.0.1:8000>. Environment variables, Docker deployment, API
boundaries, and ABI synchronization rules are documented in
[frontend/README.md](frontend/README.md); product and visual decisions are in
[PRODUCT.md](PRODUCT.md) and [DESIGN.md](DESIGN.md).

## Market Skills

The headless dimOS interface exposes read-only inspection, bounty settlement,
skill sales, and execution control through `dimos mcp list-tools` and
`dimos mcp call`:

| Skill | Purpose |
| --- | --- |
| `chain_status()` | Read-only wallet, balance, network, RPC, and pending-transaction preflight. |
| `list_requests()` | Browse open requests with IDs, needs, budgets, and requesters. |
| `list_offers(request_id)` | Browse offers, responders, prices, and Recipe hashes. |
| `search_skills(query)` | Search active skill listings before creating a new bounty. |
| `set_auto_publish(enabled)` | Automatically list successfully completed skills for resale. |
| `publish_skill(description, price, query)` | Distill completed experience and list it as a reusable data product. |
| `publish_request(need, budget)` | Create a hard request and lock its budget in escrow. |
| `distill_and_publish(request_id, query)` | Distill a privacy-reduced Recipe and submit its content hash as an offer. |
| `fetch_and_run(offer_id)` | Verify URI, hash, and sandbox permissions before accepting and executing. |
| `buy_and_run(listing_id)` | Verify a listing before paying the seller and executing locally. |
| `pay(offer_id)` | Release escrow and write the rating after successful execution. |
| `stop_run()` | Cooperatively stop background Recipe execution between primitive steps. |

`fetch_and_run` and `buy_and_run` reject a mismatched hash or unsafe primitive
before touching the chain. A requester can cancel an open request immediately;
an accepted but unsettled request can be refunded after the contract timeout.
The `RequestListener` polls both sides of the board and notifies agents when a
new request or offer needs attention.

## Repository Layout

- `injenium/core/` — recipes, sandbox, identity, storage, market, and chain clients.
- `injenium/domains/go2/` — Go2 primitive whitelist, providers, distillers, and blueprints.
- `contracts/src/Market.sol` — Injective EVM market contract.
- `frontend/` — React/Vite experience and FastAPI companion; it never stores chain keys.
- `demo/` — manual M2-M5 end-to-end demonstrations.
- `INTEGRATION.md` — machine and new-embodiment integration guide.
- `TESTING.md` — mock, Anvil, testnet, and interface-level verification flows.
- `TESTNET_NOTES.md` — testnet deployment and RPC notes.

The Solidity contract, Python `MARKET_ABI`, and frontend ABI in
`frontend/src/chain.ts` must stay in lockstep.

## Installation and Headless Runtime

Use the Python environment that provides dimOS. Python 3.10-3.12 is supported.

```bash
pip install -e '.[chain]'

# Full Go2 agentic stack plus market skills:
dimos run injenium.agentic

# Headless market service, with no robot or LLM key:
dimos run injenium.market
dimos mcp list-tools
```

The reference identity is stable per robot. A deployment may derive a wallet
from `ROBOT_IP` and a secret `WALLET_SALT` for testnet/mock use, but an explicit
`INJECTIVE_PRIVATE_KEY` always takes precedence. Mainnet must use an explicit
key and must never derive one from a robot IP. Never commit either secret or a
real `.env` file.

## Manual Demonstrations

These scripts are deliberately manual and are not auto-discovered tests:

```bash
python demo/demo_m2_distill.py     # recording -> privacy-reduced Recipe
python demo/demo_m3_sandbox.py     # whitelist execution and unsafe-step rejection
python demo/demo_m4_mock_loop.py --db /nonexistent
```

The M4 flow covers publish, offer, accept, execute, release, rating, and refund
on the mock chain. The browser companion has its own repeatable smoke flow:

```bash
cd frontend
./.venv/bin/python -m compileall -q server
./.venv/bin/python server/smoke.py
npm run lint
npm run build
npm run test:e2e
```

No unit-test suite is added by project convention; interface-level demos and
browser/API acceptance checks are the release gate.

## Development Networks

### Anvil

Build the contract and start a local node:

```bash
export PATH="$HOME/.foundry/bin:$PATH"
cd contracts
forge build
anvil --silent
```

Use only Anvil's public development key for a local deployment:

```bash
forge create src/Market.sol:Market \
  --rpc-url http://127.0.0.1:8545 \
  --private-key 0xac0974bec39a17e36ba4a6b4d238ff944bacb478cbed5efcae784d7bf4f2ff80 \
  --broadcast
```

### Injective Testnet

Testnet uses Chain ID `1439` and the official Injective EVM RPC. Deploy with a
funded test wallet, then run the on-chain demo with the deployment address:

```bash
cd "$INJENIUM_ROOT"
./contracts/script/deploy.sh testnet
python demo/demo_m5_onchain.py \
  --rpc-url https://k8s.testnet.json-rpc.injective.network/ \
  --chain-id 1439 \
  --contract 0x<deployment-address> \
  --key-a "$INJECTIVE_PRIVATE_KEY" \
  --key-b "$INJECTIVE_PRIVATE_KEY"
```

Verify transaction hashes in
[Injective EVM Testnet Blockscout](https://testnet.blockscout.injective.network/).
The repository's known testnet contract is historical reference only:
[`0x6415...4399`](https://testnet.blockscout.injective.network/address/0x641549D4c1ea67E16c84c996065629Df0AA34399).

### Mainnet

Mainnet uses Chain ID `1776`. The browser experience keeps mainnet read-only
unless both a market address and `VITE_ENABLE_MAINNET_WRITES=true` are supplied.
Production readiness additionally requires:

- an independent audit of `Market.sol` and all ABI/enumeration mappings;
- hardware-backed or managed keys with explicit human approval;
- low-balance hot wallets and enforced transaction/gas limits;
- fixed RPC, contract, IPFS, recovery-file, and log configuration;
- alerts for balance, RPC health, nonce/pending transactions, confirmations,
  Blockscout reconciliation, and IPFS availability;
- testnet drills for outages, timeouts, crashes, duplicate calls, hash tampering,
  execution failure, and refund paths.

## Transaction Semantics

### Bounty requests

```text
publish_request -> distill_and_publish -> list_offers
-> fetch_and_run -> run_status(state=succeeded) -> pay
```

The request budget is escrowed first. Recipe URI and content hash are checked
before acceptance. Payment is released only for a successful run. Release and
rating are separate transactions, so a rating failure never rolls back a
completed payment.

### Skill listings

```text
publish_skill -> search_skills -> buy_and_run -> run_status
```

The buyer validates the Recipe before payment. `buySkill` pays the seller and
local execution follows; a failed local run does not automatically reverse a
completed sale.

### Recovery

Every real-chain write is recorded before broadcast in a `0600` pending
transaction file. RPC delays and process restarts recover the original sender,
nonce, transaction hash, and newly created IDs instead of blindly rebroadcasting
with a new nonce. The browser stores pending hashes, accounts, and chain IDs in
local storage and resumes receipt polling after refresh.

## Security Boundary

- Recipes may call only primitives registered in the whitelist; no `eval`, shell,
  imports, or dynamic code loading is accepted.
- Recipe content is validated, normalized, hashed, and sandbox-checked before
  execution or payment.
- The companion stores an HttpOnly SameSite session cookie and an isolated,
  temporary mock ledger; it cannot sign EVM transactions.
- IPFS reads accept only valid `ipfs://` CIDs through a fixed gateway with
  timeout and response-size limits. Arbitrary URLs and local paths are rejected.
- Browser writes require the intended chain, wallet network match, balance and
  gas-reserve checks, transaction preview, and explicit confirmation. Mainnet
  also requires typing `MAINNET`.
- Never commit `INJECTIVE_PRIVATE_KEY`, `WALLET_SALT`, `.env`, or real robot data.
- Physical actions must be validated in mock and controlled environments first;
  `stop_run` is cooperative and depends on the underlying primitive.

For machine-specific configuration see [INTEGRATION.md](INTEGRATION.md). For
the complete verification matrix see [TESTING.md](TESTING.md).
