# Repository Guidelines

## Project Structure & Module Organization

`injenium/core/` is the domain-neutral market kernel: recipes, storage,
identity, sandboxing, chain clients, and blueprint assembly. Keep it free of
robot-specific imports. Domain adapters live under `injenium/domains/<domain>/`;
the reference integration is `injenium/domains/go2/`, which registers Go2
primitives, providers, and distillers. Add new embodiments as sibling domains,
not by branching core code. `contracts/src/Market.sol` is the Injective EVM
market contract. `demo/` contains manual end-to-end checks; `contracts/script/`
holds deployment helpers.

## Setup, Build, and Development Commands

Use the host dimOS Python environment (Python 3.10-3.12), then install the
package in editable mode:

```bash
pip install -e '.[chain]'
dimos run injenium.market
python demo/demo_m4_mock_loop.py --db /nonexistent
forge build --root contracts
```

The first command enables the real-chain client (`web3`). The market command
starts the headless MCP interface. The mock-loop demo validates the local market
and sandbox without credentials. `forge build` compiles the Solidity contract
with solc 0.8.24. See `TESTING.md` for the complete mock, Anvil, and Injective
testnet flows.

## Coding Style & Naming Conventions

Follow the existing Python style: four-space indentation, type annotations,
`snake_case` functions and modules, `PascalCase` classes, and concise module and
public-API docstrings. Keep imports grouped and use `from __future__ import
annotations` in new typed modules. Name manual demos `demo_m<N>_<purpose>.py`.
Use Solidity 0.8.24, four-space indentation, `PascalCase` contracts/structs,
and `camelCase` externally callable functions. There is no configured formatter
or linter; keep changes consistent with the surrounding file.

## Testing Guidelines

This project deliberately uses interface-level validation rather than an
automated unit-test suite. Run the smallest relevant demo before submitting:
`demo_m3_sandbox.py` for sandbox changes and `demo_m4_mock_loop.py` for market
flow changes. For ABI, escrow, or transaction work, run `forge build --root
contracts` and the local Anvil M5 flow in `TESTING.md`. Do not add `demo_` files
that assume auto-discovery by a test runner.

## Contracts, Configuration, and Security

Keep `contracts/src/Market.sol` and `injenium/core/chain/client.py::MARKET_ABI`
in lockstep. Validate recipes through the primitive whitelist before accepting
or executing them. Never commit `.env` files, `WALLET_SALT`, or
`INJECTIVE_PRIVATE_KEY`; use funded private keys only for explicit testnet or
mainnet deployment commands.

## Commits and Pull Requests

Recent commits use focused conventional prefixes such as `feat(market): ...`
and `fix(skills): ...`; follow that pattern with an imperative summary. Keep
commits scoped. Pull requests should describe behavior and affected layers,
link the issue when applicable, list verification commands and results, and
include screenshots or MCP output when an interface-visible change warrants it.
