# Copyright 2026 Injenium
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0

"""File-backed mock chain implementing :class:`ChainClient`.

The ledger is a single JSON file guarded by a sibling lock file, so two agent
processes ("dog A" and "dog B") pointed at the same ``state_path`` share one
market and can run the full closed loop (publish -> offer -> run -> pay ->
rate) with no network. Swapping in the real ``InjectiveClient`` replays the
exact same call sequence — that equivalence is the "链接口" acceptance gate.

This is a PoC ledger, not a chain: it mirrors ``Market.sol``'s caller/state
``require`` checks (so a mock-verified call sequence cannot revert on the
real contract), but does no signature verification and keeps escrow
accounting as plain integers.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
import tempfile
import time
import uuid

from injenium.chain.base import (
    Offer,
    OfferStatus,
    Rating,
    Request,
    RequestStatus,
)

# Deployer/faucet address. Every unknown account is seeded from here on first
# escrow debit so demos never hit "insufficient funds".
_GENESIS = "0x0000000000000000000000000000000000000000"
_DEFAULT_SEED_WEI = 1000 * (10**18)

# Mirrors Market.sol CANCEL_TIMEOUT: an Answered-but-never-settled request
# becomes cancellable by the requester after this many seconds.
_CANCEL_TIMEOUT_S = 3600.0


class _FileLock:
    """Best-effort cross-process lock via exclusive lock-file creation."""

    def __init__(self, path: Path, timeout: float = 10.0) -> None:
        self._path = path.with_suffix(path.suffix + ".lock")
        self._timeout = timeout
        self._fd: int | None = None

    def __enter__(self) -> _FileLock:
        deadline = time.monotonic() + self._timeout
        while True:
            try:
                self._fd = os.open(str(self._path), os.O_CREAT | os.O_EXCL | os.O_RDWR)
                return self
            except FileExistsError:
                if time.monotonic() > deadline:
                    # Stale lock recovery: steal it rather than deadlock a demo.
                    try:
                        self._path.unlink()
                    except OSError:
                        pass
                    continue
                time.sleep(0.02)

    def __exit__(self, *_exc: object) -> None:
        if self._fd is not None:
            os.close(self._fd)
            self._fd = None
        try:
            self._path.unlink()
        except OSError:
            pass


class MockChain:
    """In-process, file-backed market ledger.

    Args:
        state_path: JSON file backing the ledger. Created on first write.
        address: the wallet address this client acts as.
        seed_wei: starting balance seeded for any account on first debit.
    """

    def __init__(
        self,
        state_path: str | os.PathLike[str],
        address: str,
        seed_wei: int = _DEFAULT_SEED_WEI,
    ) -> None:
        self._path = Path(os.fspath(state_path))
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._address = address
        self._seed_wei = seed_wei

    # -- ChainClient surface -------------------------------------------------

    @property
    def address(self) -> str:
        return self._address

    def list_open_requests(self) -> list[Request]:
        state = self._read()
        return [
            Request.from_dict(r)
            for r in state["requests"].values()
            if r["status"] == RequestStatus.OPEN.value
        ]

    def get_request(self, request_id: str) -> Request:
        state = self._read()
        if request_id not in state["requests"]:
            raise KeyError(f"unknown request {request_id!r}")
        return Request.from_dict(state["requests"][request_id])

    def publish_request(self, need: str, budget: int, tags: list[str]) -> str:
        budget = int(budget)
        with _FileLock(self._path):
            state = self._read()
            self._ensure_funded(state, self._address, budget)
            request_id = f"req-{uuid.uuid4().hex[:12]}"
            req = Request(
                id=request_id,
                requester=self._address,
                need=need,
                budget=budget,
                tags=list(tags),
                status=RequestStatus.OPEN,
                created_ts=time.time(),
            )
            # Lock escrow: debit requester, credit the market escrow bucket.
            state["balances"][self._address] -= budget
            state["escrow"][request_id] = budget
            state["requests"][request_id] = req.to_dict()
            self._write(state)
        return request_id

    def list_offers(self, request_id: str) -> list[Offer]:
        state = self._read()
        return [
            Offer.from_dict(o)
            for o in state["offers"].values()
            if o["request_id"] == request_id
        ]

    def get_offer(self, offer_id: str) -> Offer:
        state = self._read()
        if offer_id not in state["offers"]:
            raise KeyError(f"unknown offer {offer_id!r}")
        return Offer.from_dict(state["offers"][offer_id])

    def submit_offer(
        self, request_id: str, recipe_uri: str, recipe_hash: str, price: int
    ) -> str:
        with _FileLock(self._path):
            state = self._read()
            if request_id not in state["requests"]:
                raise KeyError(f"unknown request {request_id!r}")
            # Mirror Market.sol: offers only against an Open request.
            if state["requests"][request_id]["status"] != RequestStatus.OPEN.value:
                raise ValueError(f"request {request_id!r} is not open")
            offer_id = f"off-{uuid.uuid4().hex[:12]}"
            offer = Offer(
                id=offer_id,
                request_id=request_id,
                responder=self._address,
                recipe_uri=recipe_uri,
                recipe_hash=recipe_hash,
                price=int(price),
                status=OfferStatus.OPEN,
                created_ts=time.time(),
            )
            state["offers"][offer_id] = offer.to_dict()
            self._write(state)
        return offer_id

    def accept_offer(self, offer_id: str) -> str:
        with _FileLock(self._path):
            state = self._read()
            offer = self._require_offer(state, offer_id)
            req = state["requests"][offer["request_id"]]
            # Mirror Market.sol: only the requester, only while Open.
            if self._address != req["requester"]:
                raise ValueError("only the requester can accept an offer")
            if req["status"] != RequestStatus.OPEN.value:
                raise ValueError(f"request {offer['request_id']!r} is not open")
            offer["status"] = OfferStatus.ACCEPTED.value
            req["status"] = RequestStatus.ANSWERED.value
            req["accepted_offer_id"] = offer_id
            self._write(state)
        return f"mock:accept:{offer_id}"

    def release_payment(self, offer_id: str) -> str:
        with _FileLock(self._path):
            state = self._read()
            offer = self._require_offer(state, offer_id)
            request_id = offer["request_id"]
            req = state["requests"][request_id]
            # Mirror Market.sol: only the requester, only the accepted offer of
            # an Answered request, and only with escrow still locked.
            if self._address != req["requester"]:
                raise ValueError("only the requester can release payment")
            if req["status"] != RequestStatus.ANSWERED.value:
                raise ValueError(f"request {request_id!r} is not answered")
            if req.get("accepted_offer_id") != offer_id:
                raise ValueError(f"offer {offer_id!r} is not the accepted offer")
            escrowed = int(state["escrow"].get(request_id, 0))
            if escrowed <= 0:
                raise ValueError(f"no escrow to release for request {request_id!r}")
            responder = offer["responder"]
            self._ensure_account(state, responder)
            state["balances"][responder] += escrowed
            state["escrow"][request_id] = 0
            offer["status"] = OfferStatus.PAID.value
            req["status"] = RequestStatus.SETTLED.value
            self._write(state)
        return f"mock:release:{offer_id}:{escrowed}"

    def cancel_request(self, request_id: str) -> str:
        with _FileLock(self._path):
            state = self._read()
            if request_id not in state["requests"]:
                raise KeyError(f"unknown request {request_id!r}")
            req = state["requests"][request_id]
            # Mirror Market.sol::cancelRequest.
            if self._address != req["requester"]:
                raise ValueError("only the requester can cancel a request")
            status = req["status"]
            timed_out = (
                status == RequestStatus.ANSWERED.value
                and time.time() >= float(req["created_ts"]) + _CANCEL_TIMEOUT_S
            )
            if status != RequestStatus.OPEN.value and not timed_out:
                raise ValueError(f"request {request_id!r} cannot be cancelled")
            escrowed = int(state["escrow"].get(request_id, 0))
            self._ensure_account(state, self._address)
            state["balances"][self._address] += escrowed
            state["escrow"][request_id] = 0
            req["status"] = RequestStatus.CANCELLED.value
            accepted = req.get("accepted_offer_id")
            if accepted and accepted in state["offers"]:
                state["offers"][accepted]["status"] = OfferStatus.REJECTED.value
            self._write(state)
        return f"mock:cancel:{request_id}:{escrowed}"

    def rate(self, offer_id: str, ratee: str, score: int) -> str:
        score = int(score)
        if not 1 <= score <= 5:
            raise ValueError("score must be within 1..5")
        with _FileLock(self._path):
            state = self._read()
            self._require_offer(state, offer_id)
            rating = Rating(
                offer_id=offer_id,
                rater=self._address,
                ratee=ratee,
                score=score,
                created_ts=time.time(),
            )
            state["ratings"].append(rating.to_dict())
            self._write(state)
        return f"mock:rate:{offer_id}:{score}"

    def balance_of(self, address: str) -> int:
        return int(self._read()["balances"].get(address, 0))

    # -- helpers -------------------------------------------------------------

    def ratings(self) -> list[Rating]:
        """PoC convenience for demos/inspection (not part of ChainClient)."""
        return [Rating.from_dict(r) for r in self._read()["ratings"]]

    def _require_offer(self, state: dict, offer_id: str) -> dict:
        if offer_id not in state["offers"]:
            raise KeyError(f"unknown offer {offer_id!r}")
        return state["offers"][offer_id]

    def _ensure_account(self, state: dict, address: str) -> None:
        state["balances"].setdefault(address, 0)

    def _ensure_funded(self, state: dict, address: str, needed: int) -> None:
        bal = state["balances"].get(address)
        if bal is None:
            state["balances"][address] = self._seed_wei
            bal = self._seed_wei
        if bal < needed:
            # Top up from genesis so PoC demos never stall on funding.
            state["balances"][address] = bal + self._seed_wei

    def _empty_state(self) -> dict:
        return {
            "balances": {_GENESIS: self._seed_wei},
            "escrow": {},
            "requests": {},
            "offers": {},
            "ratings": [],
        }

    def _read(self) -> dict:
        if not self._path.exists():
            return self._empty_state()
        try:
            with self._path.open("r", encoding="utf-8") as fh:
                return json.load(fh)
        except (json.JSONDecodeError, OSError):
            return self._empty_state()

    def _write(self, state: dict) -> None:
        # Atomic replace so a concurrent reader never sees a half-written file.
        fd, tmp = tempfile.mkstemp(dir=str(self._path.parent), suffix=".tmp")
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as fh:
                json.dump(state, fh, indent=2, sort_keys=True)
            os.replace(tmp, self._path)
        finally:
            if os.path.exists(tmp):
                os.unlink(tmp)
