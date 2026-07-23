# Copyright 2026 Injenium
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0

"""Configuration for the market modules.

Follows the dimOS ``Configurable``/``ModuleConfig`` pattern: every module gets
a typed pydantic config, values flow in through ``Module.blueprint(...)`` /
``dimos run --<module>-<field>``. No endpoints, ports, or contract addresses
are hard-coded here — they are fields with sensible PoC defaults.

Injective EVM network parameters (spec §链交互):

* Testnet (PoC target): chain id ``1439``,
  JSON-RPC ``https://k8s.testnet.json-rpc.injective.network/``,
  explorer ``https://testnet.blockscout.injective.network/``,
  faucet ``https://testnet.faucet.injective.network/``.
* Mainnet (future): chain id ``1776``,
  JSON-RPC ``https://sentry.evm-rpc.injective.network/``.

The signing key is taken from ``INJECTIVE_PRIVATE_KEY`` inside the client and is
deliberately absent from this config (spec assumption #4).
"""

from __future__ import annotations

from typing import Literal

from dimos.core.module import ModuleConfig

# Public defaults kept as named constants (referenced from prompts/docs).
INJECTIVE_TESTNET_CHAIN_ID = 1439
INJECTIVE_TESTNET_RPC = "https://k8s.testnet.json-rpc.injective.network/"
INJECTIVE_TESTNET_EXPLORER = "https://testnet.blockscout.injective.network/"
INJECTIVE_MAINNET_CHAIN_ID = 1776
INJECTIVE_MAINNET_RPC = "https://sentry.evm-rpc.injective.network/"

ChainBackend = Literal["mock", "injective"]


class ChainConfigMixin(ModuleConfig):
    """Shared chain-connection fields for market modules.

    ``chain_backend='mock'`` uses the file-backed :class:`MockChain` at
    ``market_state_path`` — this is the PoC default and needs no network.
    ``chain_backend='injective'`` uses ``web3.py`` against ``market_contract``.
    """

    chain_backend: ChainBackend = "mock"

    # Identity. For the mock ledger this is the account address; for the real
    # client the address is derived from the private key and this is ignored.
    agent_id: str = "0xA0000000000000000000000000000000000000A0"

    # Mock backend.
    market_state_path: str = "injenium_artifacts/market_state.json"

    # Injective backend.
    rpc_url: str = INJECTIVE_TESTNET_RPC
    market_contract: str | None = None
    chain_id: int = INJECTIVE_TESTNET_CHAIN_ID


class MarketConfig(ChainConfigMixin):
    """Config for :class:`MarketSkillContainer`."""

    # Where distilled recipes + template artifacts are written/read.
    artifacts_dir: str = "injenium_artifacts/recipes"

    # Recorded memory store the distiller reads from (spec PoC: go2_short.db).
    memory_db: str = "data/go2_short.db"

    # Default rating written after a successful settlement (1..5).
    default_rating: int = 5


class RequestListenerConfig(ChainConfigMixin):
    """Config for :class:`RequestListener` (the "wait for requests" module)."""

    # Seconds between board polls.
    poll_interval: float = 5.0

    # A request is "answerable by me" if any of its tags is in match_tags OR
    # any keyword appears (case-insensitive) in its need text. Empty lists mean
    # "match everything" so the PoC surfaces all open requests.
    match_tags: list[str] = []
    match_keywords: list[str] = []
