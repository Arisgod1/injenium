# Copyright 2026 Injenium
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0

"""Chain layer for the skill market.

Two interchangeable implementations satisfy the same :class:`ChainClient`
protocol:

* :class:`~injenium.core.chain.mock_chain.MockChain` — a file-backed, in-process
  ledger used to run the whole closed loop before any real deployment.
* :class:`~injenium.core.chain.client.InjectiveClient` — a ``web3.py`` wrapper
  that talks to the deployed ``Market.sol`` on Injective EVM.

Only pointers/hashes live on-chain; the recipe body and its artifacts stay
off-chain (local ``artifacts_dir`` for the PoC, IPFS/Arweave later).
"""

from __future__ import annotations

from injenium.core.chain.base import (
    ChainClient,
    Offer,
    OfferStatus,
    Rating,
    Request,
    RequestStatus,
)

__all__ = [
    "ChainClient",
    "Offer",
    "OfferStatus",
    "Rating",
    "Request",
    "RequestStatus",
]
