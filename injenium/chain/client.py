# Copyright 2026 Injenium
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0

"""``web3.py`` client for the deployed ``Market.sol`` on Injective EVM.

This is the drop-in replacement for :class:`MockChain`; it satisfies the same
:class:`ChainClient` protocol so the mock-verified call sequence replays
against the testnet unchanged (spec M5 / "链接口" acceptance).

* ``web3`` is imported lazily so the package installs and the mock loop runs
  without the ``[chain]`` extra.
* The signing key is read from the ``INJECTIVE_PRIVATE_KEY`` env var and is
  **never** stored in config, code, or memory (spec assumption #4).
* On-chain ids are ``uint256``; we expose them as decimal strings to keep the
  protocol's ``str`` id contract.
"""

from __future__ import annotations

import os
from typing import Any

from injenium.chain.base import (
    Offer,
    OfferStatus,
    Request,
    RequestStatus,
)

# Minimal ABI mirroring contracts/src/Market.sol. Kept here (not read from a
# build artifact) so the client works from a bare `pip install` without Foundry.
MARKET_ABI: list[dict[str, Any]] = [
    {
        "type": "function",
        "name": "publishRequest",
        "stateMutability": "payable",
        "inputs": [
            {"name": "need", "type": "string"},
            {"name": "tags", "type": "string[]"},
        ],
        "outputs": [{"name": "id", "type": "uint256"}],
    },
    {
        "type": "function",
        "name": "submitOffer",
        "stateMutability": "nonpayable",
        "inputs": [
            {"name": "requestId", "type": "uint256"},
            {"name": "recipeUri", "type": "string"},
            {"name": "recipeHash", "type": "bytes32"},
            {"name": "price", "type": "uint256"},
        ],
        "outputs": [{"name": "offerId", "type": "uint256"}],
    },
    {
        "type": "function",
        "name": "acceptOffer",
        "stateMutability": "nonpayable",
        "inputs": [{"name": "offerId", "type": "uint256"}],
        "outputs": [],
    },
    {
        "type": "function",
        "name": "releasePayment",
        "stateMutability": "nonpayable",
        "inputs": [{"name": "offerId", "type": "uint256"}],
        "outputs": [],
    },
    {
        "type": "function",
        "name": "cancelRequest",
        "stateMutability": "nonpayable",
        "inputs": [{"name": "requestId", "type": "uint256"}],
        "outputs": [],
    },
    {
        "type": "function",
        "name": "rate",
        "stateMutability": "nonpayable",
        "inputs": [
            {"name": "offerId", "type": "uint256"},
            {"name": "ratee", "type": "address"},
            {"name": "score", "type": "uint8"},
        ],
        "outputs": [],
    },
    {
        "type": "function",
        "name": "openRequestIds",
        "stateMutability": "view",
        "inputs": [],
        "outputs": [{"name": "", "type": "uint256[]"}],
    },
    {
        "type": "function",
        "name": "offerIdsOf",
        "stateMutability": "view",
        "inputs": [{"name": "requestId", "type": "uint256"}],
        "outputs": [{"name": "", "type": "uint256[]"}],
    },
    {
        "type": "function",
        "name": "getRequest",
        "stateMutability": "view",
        "inputs": [{"name": "id", "type": "uint256"}],
        "outputs": [
            {"name": "requester", "type": "address"},
            {"name": "need", "type": "string"},
            {"name": "budget", "type": "uint256"},
            {"name": "tags", "type": "string[]"},
            {"name": "status", "type": "uint8"},
            {"name": "createdTs", "type": "uint256"},
            {"name": "acceptedOfferId", "type": "uint256"},
        ],
    },
    {
        "type": "event",
        "name": "RequestPublished",
        "anonymous": False,
        "inputs": [
            {"name": "id", "type": "uint256", "indexed": True},
            {"name": "requester", "type": "address", "indexed": True},
            {"name": "budget", "type": "uint256", "indexed": False},
        ],
    },
    {
        "type": "event",
        "name": "OfferSubmitted",
        "anonymous": False,
        "inputs": [
            {"name": "id", "type": "uint256", "indexed": True},
            {"name": "requestId", "type": "uint256", "indexed": True},
            {"name": "responder", "type": "address", "indexed": True},
        ],
    },
    {
        "type": "function",
        "name": "getOffer",
        "stateMutability": "view",
        "inputs": [{"name": "id", "type": "uint256"}],
        "outputs": [
            {"name": "requestId", "type": "uint256"},
            {"name": "responder", "type": "address"},
            {"name": "recipeUri", "type": "string"},
            {"name": "recipeHash", "type": "bytes32"},
            {"name": "price", "type": "uint256"},
            {"name": "status", "type": "uint8"},
            {"name": "createdTs", "type": "uint256"},
        ],
    },
]

# Solidity enum ordinals -> Python enums (keep in lockstep with Market.sol).
_REQUEST_STATUS = [
    RequestStatus.OPEN,
    RequestStatus.ANSWERED,
    RequestStatus.SETTLED,
    RequestStatus.CANCELLED,
]
_OFFER_STATUS = [
    OfferStatus.OPEN,
    OfferStatus.ACCEPTED,
    OfferStatus.PAID,
    OfferStatus.REJECTED,
]

# Sentinel used by the contract for "no accepted offer".
_NO_OFFER = 0


class InjectiveClient:
    """Talks to ``Market.sol`` over EVM JSON-RPC using ``web3.py``.

    Args:
        rpc_url: Injective EVM JSON-RPC endpoint.
        contract_address: deployed ``Market`` address (checksum or lowercase).
        chain_id: EVM chain id (testnet ``1439`` / mainnet ``1776``).
        private_key: overrides ``INJECTIVE_PRIVATE_KEY`` if given (tests only).
    """

    def __init__(
        self,
        rpc_url: str,
        contract_address: str,
        chain_id: int,
        private_key: str | None = None,
    ) -> None:
        try:
            from web3 import Web3  # noqa: PLC0415 -- optional dependency
        except ImportError as exc:  # pragma: no cover - env-dependent
            raise RuntimeError(
                "InjectiveClient needs the 'chain' extra: pip install 'injenium[chain]'"
            ) from exc

        key = private_key or os.environ.get("INJECTIVE_PRIVATE_KEY")
        if not key:
            raise RuntimeError(
                "INJECTIVE_PRIVATE_KEY is not set; refusing to build a signing client."
            )

        self._w3 = Web3(Web3.HTTPProvider(rpc_url))
        self._chain_id = int(chain_id)
        self._account = self._w3.eth.account.from_key(key)
        self._contract = self._w3.eth.contract(
            address=Web3.to_checksum_address(contract_address),
            abi=MARKET_ABI,
        )

    # -- ChainClient surface -------------------------------------------------

    @property
    def address(self) -> str:
        return str(self._account.address)

    def list_open_requests(self) -> list[Request]:
        ids = self._contract.functions.openRequestIds().call()
        return [self.get_request(str(i)) for i in ids]

    def get_request(self, request_id: str) -> Request:
        r = self._call_view(
            self._contract.functions.getRequest(int(request_id)), "request", request_id
        )
        accepted = int(r[6])
        return Request(
            id=str(request_id),
            requester=str(r[0]),
            need=str(r[1]),
            budget=int(r[2]),
            tags=list(r[3]),
            status=_REQUEST_STATUS[int(r[4])],
            created_ts=float(r[5]),
            accepted_offer_id=None if accepted == _NO_OFFER else str(accepted),
        )

    def publish_request(self, need: str, budget: int, tags: list[str]) -> str:
        receipt = self._send(
            self._contract.functions.publishRequest(need, list(tags)),
            value=int(budget),
        )
        return str(self._decode_id(receipt, "publishRequest"))

    def list_offers(self, request_id: str) -> list[Offer]:
        ids = self._contract.functions.offerIdsOf(int(request_id)).call()
        return [self.get_offer(str(i)) for i in ids]

    def get_offer(self, offer_id: str) -> Offer:
        o = self._call_view(
            self._contract.functions.getOffer(int(offer_id)), "offer", offer_id
        )
        recipe_hash = self._normalize_hash(o[3])
        return Offer(
            id=str(offer_id),
            request_id=str(o[0]),
            responder=str(o[1]),
            recipe_uri=str(o[2]),
            recipe_hash=recipe_hash,
            price=int(o[4]),
            status=_OFFER_STATUS[int(o[5])],
            created_ts=float(o[6]),
        )

    def submit_offer(
        self, request_id: str, recipe_uri: str, recipe_hash: str, price: int
    ) -> str:
        receipt = self._send(
            self._contract.functions.submitOffer(
                int(request_id),
                recipe_uri,
                self._to_bytes32(recipe_hash),
                int(price),
            )
        )
        return str(self._decode_id(receipt, "submitOffer"))

    def accept_offer(self, offer_id: str) -> str:
        receipt = self._send(self._contract.functions.acceptOffer(int(offer_id)))
        return receipt["transactionHash"].hex()

    def release_payment(self, offer_id: str) -> str:
        receipt = self._send(self._contract.functions.releasePayment(int(offer_id)))
        return receipt["transactionHash"].hex()

    def cancel_request(self, request_id: str) -> str:
        receipt = self._send(self._contract.functions.cancelRequest(int(request_id)))
        return receipt["transactionHash"].hex()

    def rate(self, offer_id: str, ratee: str, score: int) -> str:
        from web3 import Web3  # noqa: PLC0415

        receipt = self._send(
            self._contract.functions.rate(
                int(offer_id), Web3.to_checksum_address(ratee), int(score)
            )
        )
        return receipt["transactionHash"].hex()

    def balance_of(self, address: str) -> int:
        from web3 import Web3  # noqa: PLC0415

        return int(self._w3.eth.get_balance(Web3.to_checksum_address(address)))

    # -- tx plumbing ---------------------------------------------------------

    def _send(self, fn: Any, value: int = 0) -> Any:
        tx = fn.build_transaction(
            {
                "chainId": self._chain_id,
                "from": self._account.address,
                "nonce": self._w3.eth.get_transaction_count(self._account.address),
                "value": int(value),
                "gasPrice": self._w3.eth.gas_price,
            }
        )
        signed = self._account.sign_transaction(tx)
        tx_hash = self._w3.eth.send_raw_transaction(signed.raw_transaction)
        return self._w3.eth.wait_for_transaction_receipt(tx_hash)

    @staticmethod
    def _call_view(fn: Any, kind: str, ident: str) -> Any:
        """Call a view fn, mapping the contract's ``unknown ...`` revert to the
        ``KeyError`` the :class:`ChainClient` protocol promises."""
        try:
            return fn.call()
        except Exception as exc:
            from web3.exceptions import ContractLogicError  # noqa: PLC0415

            if isinstance(exc, ContractLogicError):
                raise KeyError(f"unknown {kind} {ident!r}") from exc
            raise

    @staticmethod
    def _normalize_hash(value: Any) -> str:
        """Normalize an on-chain ``bytes32`` to the mock's bare 64-hex form.

        ``bytes(value).hex()`` is the stdlib call (lowercase, no ``0x``) even
        when ``value`` is a ``HexBytes`` of any vintage (pre-1.0 ``.hex()``
        added a prefix); a stray string form gets its prefix stripped.
        """
        if isinstance(value, (bytes, bytearray)):
            return bytes(value).hex()
        text = str(value)
        return text[2:].lower() if text.startswith("0x") else text.lower()

    def _decode_id(self, receipt: Any, fn_name: str) -> int:
        """Pull the emitted id out of the receipt's event logs."""
        event_name = "RequestPublished" if fn_name == "publishRequest" else "OfferSubmitted"
        try:
            event = getattr(self._contract.events, event_name)()
            entries = event.process_receipt(receipt)
            if entries:
                return int(entries[0]["args"]["id"])
        except Exception:  # pragma: no cover - ABI/log shape drift
            pass
        # Fallback: contracts also return the id, but that's unavailable from a
        # mined tx; callers should prefer reading the emitted event.
        raise RuntimeError(f"could not decode id from {fn_name} receipt")

    @staticmethod
    def _to_bytes32(hex_hash: str) -> bytes:
        raw = bytes.fromhex(hex_hash[2:] if hex_hash.startswith("0x") else hex_hash)
        if len(raw) != 32:
            raise ValueError("recipe_hash must be 32 bytes (sha256 hex)")
        return raw
