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

from decimal import Decimal
from typing import Literal

from dimos.core.module import ModuleConfig
from pydantic import Field

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

    # Identity override for the account address. The mock ledger acts as this
    # address; the real client ignores it (its address comes from the signing
    # key). Empty = auto: derive from the ``ROBOT_IP`` env var when set, else a
    # fixed PoC default (see identity.py). The same ROBOT_IP feeds the derived
    # on-chain wallet on testnet.
    agent_id: str = ""

    # Mock backend.
    market_state_path: str = "injenium_artifacts/market_state.json"

    # Injective backend.
    rpc_url: str = INJECTIVE_TESTNET_RPC
    market_contract: str | None = None
    chain_id: int = INJECTIVE_TESTNET_CHAIN_ID

    # Transaction confirmation policy. Receipt polling is backed by sender /
    # nonce block scans for RPCs whose receipt index lags chain state.
    tx_receipt_timeout: float = Field(default=180.0, gt=0)
    tx_poll_interval: float = Field(default=2.0, gt=0)
    tx_broadcast_attempts: int = Field(default=3, ge=1, le=10)
    tx_confirmations: int = Field(default=1, ge=1)
    pending_tx_path: str = "injenium_artifacts/pending_txs.json"
    tx_recovery_scan_blocks: int = Field(default=2048, ge=1)


class MarketConfig(ChainConfigMixin):
    """Config for :class:`MarketSkillContainer`."""

    # Supply side: when true the agent is briefed to list each successfully
    # completed task on-chain via ``publish_skill`` (runtime-togglable with
    # the ``set_auto_publish`` skill).
    auto_publish: bool = False

    # Where distilled recipes + template artifacts are written/read.
    artifacts_dir: str = "injenium_artifacts/recipes"

    # Recorded memory store the distiller reads from (spec PoC: go2_short.db).
    memory_db: str = "data/go2_short.db"

    # Default rating written after a successful settlement (1..5).
    default_rating: int = 5

    # Safety rails for agent-initiated value transfers. Mainnet deployments
    # should normally override the cap with a smaller operational limit.
    max_transaction_inj: Decimal = Field(default=Decimal("10"), gt=0)
    min_gas_reserve_inj: Decimal = Field(default=Decimal("0.01"), ge=0)

    # Off-chain recipe storage: "local" (PoC default; recipe_uri is a local dir)
    # or "ipfs" (pin the recipe dir, put an ipfs://<cid> on-chain so two
    # machines share it). "ipfs" needs a reachable IPFS/Kubo HTTP API.
    recipe_storage: Literal["local", "ipfs"] = "local"
    ipfs_api_url: str = "http://127.0.0.1:5001"


class RequestListenerConfig(ChainConfigMixin):
    """Config for :class:`RequestListener` (the "wait for requests" module)."""

    # Seconds between board polls.
    poll_interval: float = 5.0

    # A request is "answerable by me" if any of its tags is in match_tags OR
    # any keyword appears (case-insensitive) in its need text. Empty lists mean
    # "match everything" so the PoC surfaces all open requests.
    match_tags: list[str] = []
    match_keywords: list[str] = []
