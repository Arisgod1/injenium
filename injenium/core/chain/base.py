# Copyright 2026 Injenium
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0

"""Data models and the ``ChainClient`` protocol shared by mock and real chains.

The protocol is the single contract that the mock and the ``web3.py`` client
must both honour, so the closed loop that runs against the mock can be replayed
verbatim against the Injective testnet (spec: "链接口" acceptance).

Money is denominated in the smallest unit (``wei``, 18 decimals for INJ) as an
``int`` everywhere, to avoid float rounding on the escrow path. The market
skills accept a human ``float`` budget and convert at the edge.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Protocol, runtime_checkable

INJ_DECIMALS = 18


def inj_to_wei(amount: float) -> int:
    """Convert a human INJ amount to integer wei (18 decimals)."""
    return int(round(float(amount) * (10**INJ_DECIMALS)))


def wei_to_inj(amount: int) -> float:
    """Convert integer wei back to a human INJ amount."""
    return int(amount) / (10**INJ_DECIMALS)


class RequestStatus(str, Enum):
    """Lifecycle of a hard-request on the board."""

    OPEN = "open"          # published, escrow funded, awaiting offers
    ANSWERED = "answered"  # at least one offer accepted / picked up
    SETTLED = "settled"    # escrow released to the responder
    CANCELLED = "cancelled"


class OfferStatus(str, Enum):
    """Lifecycle of an answer-offer against a request."""

    OPEN = "open"
    ACCEPTED = "accepted"  # requester pulled the recipe (fetch_and_run)
    PAID = "paid"          # escrow released to this offer's responder
    REJECTED = "rejected"


@dataclass
class Request:
    """A published hard-request. ``budget`` is escrowed wei held by the market."""

    id: str
    requester: str
    need: str
    budget: int
    tags: list[str] = field(default_factory=list)
    status: RequestStatus = RequestStatus.OPEN
    created_ts: float = 0.0
    accepted_offer_id: str | None = None

    def to_dict(self) -> dict[str, Any]:
        d = self.__dict__.copy()
        d["status"] = self.status.value
        return d

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> Request:
        d = dict(d)
        d["status"] = RequestStatus(d.get("status", RequestStatus.OPEN.value))
        return cls(**d)


@dataclass
class Offer:
    """An answer to a request. On-chain we only keep the recipe pointer + hash."""

    id: str
    request_id: str
    responder: str
    recipe_uri: str
    recipe_hash: str
    price: int
    status: OfferStatus = OfferStatus.OPEN
    created_ts: float = 0.0

    def to_dict(self) -> dict[str, Any]:
        d = self.__dict__.copy()
        d["status"] = self.status.value
        return d

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> Offer:
        d = dict(d)
        d["status"] = OfferStatus(d.get("status", OfferStatus.OPEN.value))
        return cls(**d)


@dataclass
class Rating:
    """A two-way review written after settlement."""

    offer_id: str
    rater: str
    ratee: str
    score: int  # 1..5
    created_ts: float = 0.0

    def to_dict(self) -> dict[str, Any]:
        return self.__dict__.copy()

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> Rating:
        return cls(**d)


@dataclass
class Listing:
    """A skill listed for direct sale (supply side).

    A listing is a data good: it stays ``active`` and can be sold to many
    buyers until the seller delists it. ``price`` is wei per purchase, paid
    straight to the seller on ``buy_skill``.
    """

    id: str
    seller: str
    description: str
    tags: list[str] = field(default_factory=list)
    recipe_uri: str = ""
    recipe_hash: str = ""
    price: int = 0
    active: bool = True
    created_ts: float = 0.0

    def to_dict(self) -> dict[str, Any]:
        return self.__dict__.copy()

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> Listing:
        return cls(**d)


@runtime_checkable
class ChainClient(Protocol):
    """The market's on-chain surface, backed by mock or ``web3.py``.

    Implementations must be safe to construct without side effects and expose
    the caller's own address via :attr:`address`. The same call sequence
    (query / list / publish / offer / escrow / release / cancel / rate)
    drives both backends.
    """

    @property
    def address(self) -> str:
        """The wallet/account address this client acts as."""
        ...

    def list_open_requests(self) -> list[Request]:
        """Return all requests currently in ``OPEN`` status."""
        ...

    def get_request(self, request_id: str) -> Request:
        """Fetch a single request by id (raises ``KeyError`` if unknown)."""
        ...

    def publish_request(self, need: str, budget: int, tags: list[str]) -> str:
        """Register a hard-request and lock ``budget`` wei in escrow.

        Returns the new request id.
        """
        ...

    def list_offers(self, request_id: str) -> list[Offer]:
        """Return all offers submitted against ``request_id``."""
        ...

    def get_offer(self, offer_id: str) -> Offer:
        """Fetch a single offer by id (raises ``KeyError`` if unknown)."""
        ...

    def submit_offer(
        self, request_id: str, recipe_uri: str, recipe_hash: str, price: int
    ) -> str:
        """Post an answer-offer pointing at an off-chain recipe. Returns offer id."""
        ...

    def accept_offer(self, offer_id: str) -> str:
        """Mark an offer accepted (requester committed to run it). Returns tx ref."""
        ...

    def release_payment(self, offer_id: str) -> str:
        """Release the escrow of the offer's request to the responder. Returns tx ref."""
        ...

    def cancel_request(self, request_id: str) -> str:
        """Cancel a request and refund its escrow to the requester.

        Only the requester may cancel, and only while the request is ``OPEN``
        (no offer accepted) or ``ANSWERED`` past the cancel timeout — mirrors
        ``Market.sol::cancelRequest``. Raises ``KeyError`` if the request id
        is unknown. Returns a tx ref.
        """
        ...

    def rate(self, offer_id: str, ratee: str, score: int) -> str:
        """Write a 1..5 rating for the counterparty of a settled offer. Returns tx ref."""
        ...

    def list_skill(
        self,
        description: str,
        tags: list[str],
        recipe_uri: str,
        recipe_hash: str,
        price: int,
    ) -> str:
        """List a distilled skill for direct sale. Returns the new listing id."""
        ...

    def buy_skill(self, listing_id: str) -> str:
        """Pay an active listing's price straight to its seller. Returns a tx ref.

        Callers hash-check + sandbox-validate the recipe **before** buying;
        payment is settlement, not access control (mirrors ``Market.sol``).
        """
        ...

    def delist_skill(self, listing_id: str) -> str:
        """Take one's own listing off the board. Returns a tx ref."""
        ...

    def list_active_listings(self) -> list[Listing]:
        """Return all listings currently active (buyable)."""
        ...

    def get_listing(self, listing_id: str) -> Listing:
        """Fetch a single listing by id (raises ``KeyError`` if unknown)."""
        ...

    def balance_of(self, address: str) -> int:
        """Return the wei balance tracked for ``address`` (escrow accounting)."""
        ...
