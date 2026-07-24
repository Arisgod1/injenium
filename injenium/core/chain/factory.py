# Copyright 2026 Injenium
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0

"""Build a :class:`ChainClient` from a module's chain config.

Single place that decides mock vs. real, so both market modules share identical
selection logic and swapping backends is a one-line config change (the "无缝切
测试网" requirement).
"""

from __future__ import annotations

from injenium.core.chain.base import ChainClient
from injenium.core.config import ChainConfigMixin
from injenium.core.identity import resolve_mock_address


def build_chain_client(config: ChainConfigMixin) -> ChainClient:
    """Construct the configured chain client.

    ``mock`` -> file-backed :class:`MockChain` (no network).
    ``injective`` -> ``web3.py`` :class:`InjectiveClient` (requires the
    ``market_contract`` address and the ``INJECTIVE_PRIVATE_KEY`` env var).
    """
    if config.chain_backend == "mock":
        from injenium.core.chain.mock_chain import MockChain

        return MockChain(
            state_path=config.market_state_path,
            address=resolve_mock_address(config.agent_id),
        )

    if config.chain_backend == "injective":
        if not config.market_contract:
            raise ValueError(
                "chain_backend='injective' requires 'market_contract' to be set."
            )
        from injenium.core.chain.client import InjectiveClient

        return InjectiveClient(
            rpc_url=config.rpc_url,
            contract_address=config.market_contract,
            chain_id=config.chain_id,
        )

    raise ValueError(f"unknown chain_backend {config.chain_backend!r}")
