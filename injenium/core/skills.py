# Copyright 2026 Injenium
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0

"""The agent-facing market skills (spec §5) — domain-neutral.

:class:`MarketSkillContainer` is a dimOS ``Module`` whose ``@skill`` methods the
LLM calls to drive the closed loop:

    publish_request  -> distill_and_publish -> fetch_and_run -> pay

plus read-only ``chain_status`` / ``list_requests`` / ``list_offers`` /
``search_skills`` for self-check and browsing, a supply side: a
``set_auto_publish`` switch, ``publish_skill`` to list a distilled skill for
direct sale, and ``buy_and_run`` to purchase and execute a listing
(validate-then-pay, mirroring ``fetch_and_run``) — plus ``run_status`` and
``stop_run`` to observe or abort a background recipe cooperatively.

Each skill obeys the dimOS skill contract (docstring + fully typed args + ``str``
return) so it shows up in ``dimos mcp list-tools`` and is callable via
``dimos mcp call``. The chain surface comes from
:func:`~injenium.core.chain.factory.build_chain_client` (mock or Injective by
config); distillation is delegated to the domain's registered
:class:`~injenium.core.distill.Distiller`; execution goes through the sandbox
against the injected primitive provider — foreign recipe bytes are never
imported or ``eval``'d.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
import threading

from dimos.agents.annotation import skill
from dimos.core.core import rpc
from dimos.core.module import Module
from dimos.utils.logging_config import setup_logger

from injenium.core.chain.base import ChainClient, OfferStatus, inj_to_wei, wei_to_inj
from injenium.core.chain.factory import build_chain_client
from injenium.core.config import MarketConfig
from injenium.core.distill import get_default_distiller
from injenium.core.identity import resolve_mock_address
from injenium.core.recipe import load_recipe
from injenium.core.sandbox import SandboxInterpreter
from injenium.core.specs import PrimitiveSkillsSpec

logger = setup_logger()


class RunPhase(str, Enum):
    """Local execution state used to gate escrow settlement."""

    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    ABORTED = "aborted"
    SETTLED = "settled"


@dataclass
class RunRecord:
    """State retained for one background offer or listing execution."""

    run_id: str
    phase: RunPhase = RunPhase.RUNNING
    abort: threading.Event = field(default_factory=threading.Event)
    summary: str = ""
    payment_tx: str | None = None


class MarketSkillContainer(Module):
    """Hosts the publish / distill / fetch-run / pay skills for the agent.

    ``_primitives`` is injected by the coordinator at blueprint-build time (a
    mock provider in the headless market blueprint, the real robot provider on
    a robot); the sandbox drives it during :meth:`fetch_and_run`. Distillation
    is delegated to the capability domain's registered distiller.
    """

    config: MarketConfig

    _primitives: PrimitiveSkillsSpec

    _recipe_runs: dict[str, RunRecord]
    _recipe_runs_lock: threading.Lock

    @property
    def _runs(self) -> dict[str, RunRecord]:
        runs = getattr(self, "_recipe_runs", None)
        if runs is None:
            runs = {}
            self._recipe_runs = runs
        return runs

    @property
    def _runs_lock(self) -> threading.Lock:
        lock = getattr(self, "_recipe_runs_lock", None)
        if lock is None:
            lock = threading.Lock()
            self._recipe_runs_lock = lock
        return lock

    @staticmethod
    def _run_id(kind: str, ident: str) -> str:
        return f"{kind}:{ident}"

    @property
    def _chain(self) -> ChainClient:
        client = getattr(self, "_chain_client", None)
        if client is None:
            client = build_chain_client(self.config)
            self._chain_client = client
        return client

    @property
    def _auto_publish_enabled(self) -> bool:
        # Runtime switch; falls back to the configured default until toggled.
        state = getattr(self, "_auto_publish", None)
        return bool(self.config.auto_publish) if state is None else bool(state)

    def _amount_rejection(self, amount_wei: int, operation: str) -> str | None:
        """Return a refusal reason when an amount violates configured limits."""
        if amount_wei <= 0:
            return f"Refused {operation}: amount must be greater than 0 INJ."
        maximum_wei = inj_to_wei(self.config.max_transaction_inj)
        if amount_wei > maximum_wei:
            return (
                f"Refused {operation}: {wei_to_inj(amount_wei)} INJ exceeds the "
                f"configured single-transaction limit of "
                f"{self.config.max_transaction_inj} INJ."
            )
        return None

    def _spend_rejection(self, amount_wei: int, operation: str) -> str | None:
        """Apply amount limits and retain the configured gas reserve on-chain."""
        rejection = self._amount_rejection(amount_wei, operation)
        if rejection is not None or self.config.chain_backend != "injective":
            return rejection
        reserve_wei = inj_to_wei(self.config.min_gas_reserve_inj)
        balance_wei = self._chain.balance_of(self._chain.address)
        if balance_wei < amount_wei + reserve_wei:
            return (
                f"Refused {operation}: wallet balance is "
                f"{wei_to_inj(balance_wei)} INJ; spending "
                f"{wei_to_inj(amount_wei)} INJ must leave at least "
                f"{self.config.min_gas_reserve_inj} INJ for gas."
            )
        return None

    @rpc
    def start(self) -> None:
        super().start()

    @rpc
    def stop(self) -> None:
        super().stop()

    # -- skills --------------------------------------------------------------

    @skill
    def chain_status(self) -> str:
        """Report whether the robot can go on-chain, and with which wallet.

        Read-only self-check for questions like "can you go on-chain?" / "do you
        have a blockchain skill?". It spends nothing and locks no escrow: it
        names the active chain backend and the robot's wallet, and — by reading
        that wallet's balance — reports whether the chain is reachable right
        now. Run it before ``publish_request``/``pay`` to confirm the robot is
        connected and funded.

        Returns:
            A human-readable line stating the backend, wallet, balance, and
            whether transacting is possible (or why it is not).
        """
        cfg = self.config
        backend = cfg.chain_backend
        try:
            chain = self._chain
            address = chain.address
            balance = wei_to_inj(chain.balance_of(address))
        except Exception as exc:  # self-check must never crash the agent
            intended = resolve_mock_address(cfg.agent_id)
            logger.warning("chain_status: %s backend unavailable: %s", backend, exc)
            return (
                f"On-chain check: backend={backend}, but I cannot transact right "
                f"now: {exc}. Intended wallet {intended}. For the injective "
                f"backend, check market_contract, INJECTIVE_PRIVATE_KEY, and RPC "
                f"{cfg.rpc_url}."
            )

        auto = "ON" if self._auto_publish_enabled else "OFF"
        if backend == "mock":
            logger.info("chain_status: mock ledger ok for %s", address)
            return (
                f"On-chain check: backend=mock (local file ledger at "
                f"{cfg.market_state_path}, no network needed). Wallet {address} "
                f"holds {balance} INJ (auto-funded on first request). I can run "
                f"the full market loop off-chain. Auto-publish is {auto}."
            )

        pending_reader = getattr(chain, "pending_transaction", None)
        pending = pending_reader() if callable(pending_reader) else None
        pending_note = (
            " No persisted transaction is awaiting recovery."
            if pending is None
            else (
                f" Pending transaction nonce={pending.nonce}, "
                f"hash={pending.transaction_hash[:12]}... will be recovered "
                "before the next write."
            )
        )
        logger.info("chain_status: injective reachable for %s", address)
        return (
            f"On-chain check: backend=injective, chain_id={cfg.chain_id}, "
            f"contract={cfg.market_contract}. Wallet {address} is reachable on "
            f"{cfg.rpc_url} and holds {balance} INJ. Ready to transact on-chain. "
            f"Auto-publish is {auto}.{pending_note}"
        )

    @skill
    def list_requests(self) -> str:
        """List the open requests currently on the market board.

        Read-only browse for "what tasks are open on-chain?" / "what can I
        answer?". Shows each open request's id, need, escrow budget and
        requester (yours are marked). Pick a ``request_id`` here to answer with
        ``distill_and_publish``. Spends nothing.

        Returns:
            A human-readable list of open requests, or a note that there are
            none.
        """
        try:
            requests = self._chain.list_open_requests()
        except Exception as exc:  # self-check must never crash the agent
            return f"Could not read the market board: {exc}"
        if not requests:
            return "No open requests on the market right now."
        me = self._chain.address
        lines = [f"Open requests on the market ({len(requests)}):"]
        for r in requests:
            mine = " (yours)" if r.requester == me else ""
            tags = f", tags={r.tags}" if r.tags else ""
            lines.append(
                f"- {r.id}: {r.need!r} — {wei_to_inj(r.budget)} INJ — "
                f"by {r.requester}{mine}{tags}"
            )
        return "\n".join(lines)

    @skill
    def list_offers(self, request_id: str) -> str:
        """List the offers submitted against a request.

        Read-only browse for "did anyone answer my request?" / "which offers can
        I run?". Shows each offer's id, responder, price, recipe hash and
        status. After ``publish_request``, poll this to find an ``offer_id`` to

        Args:
            request_id: The request to list offers for (e.g. the id returned by
                ``publish_request``).

        Returns:
            A human-readable list of offers, or a note that there are none.
        """
        try:
            offers = self._chain.list_offers(request_id)
        except Exception as exc:  # bad id / backend hiccup must not crash the agent
            return f"Could not read offers for request {request_id!r}: {exc}"
        if not offers:
            return (
                f"No offers for request {request_id} yet. Another dog answers by "
                f"calling distill_and_publish; check again shortly."
            )
        lines = [f"Offers for request {request_id} ({len(offers)}):"]
        for o in offers:
            lines.append(
                f"- {o.id}: {wei_to_inj(o.price)} INJ — by {o.responder} — "
                f"recipe 0x{o.recipe_hash[:12]}… — status={o.status.value} — "
                f"run with fetch_and_run(offer_id={o.id!r})"
            )
        return "\n".join(lines)

    @skill
    def search_skills(self, query: str) -> str:
        """Search the on-chain skill board for listings matching a query.

        Read-only browse of the supply side: matches ``query`` words against
        each active listing's description and tags (case-insensitive; empty
        query lists everything). When you are stuck, search here **first** —
        buying an existing skill with ``buy_and_run`` is faster and cheaper
        than posting a bounty with ``publish_request``. Spends nothing.

        Args:
            query: Keywords describing the skill you need (e.g. ``"backflip"``).

        Returns:
            Matching listings with id, description, price and seller, or a
            note that nothing matched.
        """
        try:
            listings = self._chain.list_active_listings()
        except Exception as exc:  # browse must never crash the agent
            return f"Could not read the skill board: {exc}"
        tokens = [t for t in query.lower().split() if t]
        if tokens:
            listings = [
                listing
                for listing in listings
                if any(
                    token in (listing.description + " " + " ".join(listing.tags)).lower()
                    for token in tokens
                )
            ]
        if not listings:
            return (
                f"No skill listings match {query!r}. You can post a bounty "
                f"instead with publish_request(need=..., budget=...)."
            )
        lines = [f"Skill listings matching {query!r} ({len(listings)}):"]
        for listing in listings:
            lines.append(
                f"- {listing.id}: {listing.description!r} — "
                f"{wei_to_inj(listing.price)} INJ — by {listing.seller} — "
                f"buy with buy_and_run(listing_id={listing.id!r})"
            )
        return "\n".join(lines)

    @skill
    def set_auto_publish(self, enabled: bool) -> str:
        """Turn the auto-publish switch on or off.

        The switch opts this robot into the supply side of the skill economy.
        While it is ON, after you successfully complete a task you should call
        ``publish_skill(description=..., price=..., query=...)`` to distill and
        list that experience on-chain so other robots can find and buy it.
        Turning it OFF stops the automatic listing behaviour; manual
        ``publish_skill`` still works.

        Args:
            enabled: ``true`` to enable auto-publishing, ``false`` to disable.

        Returns:
            The new switch state and a reminder of the expected behaviour.
        """
        self._auto_publish = bool(enabled)
        logger.info("auto-publish switched %s", "ON" if enabled else "OFF")
        if self._auto_publish:
            return (
                "Auto-publish is now ON: after each task you complete "
                "successfully, call publish_skill(description=..., price=..., "
                "query=...) to list the experience on-chain (price modestly, "
                "e.g. 0.05 INJ)."
            )
        return (
            "Auto-publish is now OFF: skills are only listed when you call "
            "publish_skill explicitly."
        )

    @skill
    def publish_skill(self, description: str, price: str, query: str) -> str:
        """Distill a completed task from memory and list it for sale on-chain.

        The supply side of the market: turns recorded experience into a
        de-privatised, parameterized recipe and puts it on the skill board at
        ``price`` INJ per purchase (a listing can sell many times). Other
        robots find it with ``search_skills`` and buy it with ``buy_and_run``.
        Call this after completing a task when auto-publish is ON, or whenever
        asked to sell a skill.

        Args:
            description: What the skill does, as buyers will see it
                (e.g. ``"climb a 20cm ramp"``).
            price: Exact decimal INJ price per purchase (e.g. ``"0.05"``).
            query: Text used to pick the recorded experience to distil
                (semantic frame selection, like ``distill_and_publish``).

        Returns:
            A confirmation including the new listing id.
        """
        price_wei = inj_to_wei(price)
        rejection = self._amount_rejection(price_wei, "skill listing")
        if rejection is not None:
            return rejection
        recipe, recipe_uri = get_default_distiller().distill(
            intent=description,
            source=self.config.memory_db,
            artifacts_dir=self.config.artifacts_dir,
            query=query,
            success_criteria=description,
            storage=self.config.recipe_storage,
            ipfs_api_url=self.config.ipfs_api_url,
        )
        listing_id = self._chain.list_skill(
            description=description,
            tags=[],
            recipe_uri=recipe_uri,
            recipe_hash=recipe.content_hash(),
            price=price_wei,
        )
        logger.info("listed skill %s (%s INJ)", listing_id, price)
        return (
            f"Listed skill {listing_id}: {description!r} at "
            f"{wei_to_inj(price_wei)} INJ "
            f"({len(recipe.steps)} steps). Other robots can now find it with "
            f"search_skills and buy it with buy_and_run."
        )

    @skill
    def publish_request(self, need: str, budget: str) -> str:
        """Publish a hard situation as an on-chain request with an escrow budget.

        Registers a request on the market board and locks ``budget`` INJ in
        escrow, to be released to whoever provides a working recipe. Use this
        when the robot is stuck and wants to buy a skill from another dog.

        Args:
            need: Natural-language description of the task the robot cannot do.
            budget: Exact decimal INJ amount to escrow (e.g. ``"1.5"``).

        Returns:
            A human-readable confirmation including the new request id.
        """
        budget_wei = inj_to_wei(budget)
        rejection = self._spend_rejection(budget_wei, "request publication")
        if rejection is not None:
            return rejection
        request_id = self._chain.publish_request(need, budget_wei, tags=[])
        logger.info("published request %s (budget=%s INJ)", request_id, budget)
        return (
            f"Published request {request_id} with a "
            f"{wei_to_inj(budget_wei)} INJ escrow budget. "
            f"Other dogs can now answer it with a recipe."
        )

    @skill
    def distill_and_publish(self, request_id: str, query: str) -> str:
        """Answer an open request by distilling a recipe from recorded memory.

        Pulls the request, distils a de-privatised, parameterized recipe from
        the local recorded memory store (matched by ``query``), writes it under
        the configured artifacts directory, and posts an offer on-chain that
        points at the recipe and carries its content hash.

        Args:
            request_id: The id of the open request to answer.
            query: Text describing which recorded experience to distil from
                (used for semantic frame selection).

        Returns:
            A confirmation including the new offer id and the recipe hash.
        """
        request = self._chain.get_request(request_id)
        recipe, recipe_uri = get_default_distiller().distill(
            intent=request.need,
            source=self.config.memory_db,
            artifacts_dir=self.config.artifacts_dir,
            query=query,
            success_criteria=request.need,
            storage=self.config.recipe_storage,
            ipfs_api_url=self.config.ipfs_api_url,
        )
        recipe_hash = recipe.content_hash()
        offer_id = self._chain.submit_offer(
            request_id=request_id,
            recipe_uri=recipe_uri,
            recipe_hash=recipe_hash,
            price=request.budget,
        )
        logger.info("submitted offer %s for request %s", offer_id, request_id)
        return (
            f"Distilled a {len(recipe.steps)}-step recipe and submitted offer "
            f"{offer_id} for request {request_id} (recipe hash 0x{recipe_hash[:12]}…)."
        )

    @skill
    def fetch_and_run(self, offer_id: str) -> str:
        """Fetch an offer's recipe, verify it, and run it through the sandbox.

        Loads the referenced recipe, checks its content hash against the
        on-chain commitment, and validates every step in the sandbox — all
        **before** accepting the offer on-chain, so a bad recipe can never
        strand the request in ``Answered`` with the escrow locked. Only a
        fully verified recipe is accepted and then executed against the local
        primitive skills. The recipe is never imported or evaluated as code —
        only whitelisted primitives with checked parameters run.

        Args:
            offer_id: The id of the offer to accept and execute.

        Returns:
            A background run id to inspect with ``run_status``. Call ``pay``
            only after that run reports ``state=succeeded``.
        """
        offer = self._chain.get_offer(offer_id)
        try:
            recipe = load_recipe(offer.recipe_uri)
        except (OSError, ValueError) as exc:
            return (
                f"Refused offer {offer_id}: could not load recipe from "
                f"{offer.recipe_uri!r}: {exc}"
            )

        actual = recipe.content_hash()
        if actual != offer.recipe_hash:
            return (
                f"Refused offer {offer_id}: recipe hash mismatch "
                f"(offer 0x{offer.recipe_hash[:12]}… vs file 0x{actual[:12]}…)."
            )

        # On-chain accept must mean "every off-chain check passed"; run the
        # sandbox validation before committing, never after.
        interpreter = SandboxInterpreter(self._primitives)
        problems = interpreter.validate(recipe)
        if problems:
            return (
                f"Refused offer {offer_id}: recipe failed validation: "
                f"{'; '.join(problems)}"
            )

        run_id = self._run_id("offer", offer_id)
        with self._runs_lock:
            previous = self._runs.get(run_id)
            if previous is not None:
                return (
                    f"Offer {offer_id} already has local run {run_id} in "
                    f"state={previous.phase.value}. Call run_status(run_id="
                    f"'{run_id}') instead of executing it again."
                )

        self._chain.accept_offer(offer_id)
        record = RunRecord(run_id=run_id)
        with self._runs_lock:
            self._runs[run_id] = record

        # Run in background — real robot moves far exceed MCP's 120s HTTP
        # timeout; return immediately so the agent loop stays alive.
        def _bg_run() -> None:
            try:
                report = interpreter.run(recipe, abort=record.abort)
                phase = (
                    RunPhase.ABORTED
                    if record.abort.is_set()
                    else RunPhase.SUCCEEDED
                    if report.ok
                    else RunPhase.FAILED
                )
                with self._runs_lock:
                    record.phase = phase
                    record.summary = report.summary()
                logger.info("ran offer %s -> ok=%s", offer_id, report.ok)
            except Exception as exc:
                with self._runs_lock:
                    record.phase = RunPhase.FAILED
                    record.summary = f"execution error: {exc!r}"
                logger.error("background run failed for offer %s: %s", offer_id, exc)

        threading.Thread(target=_bg_run, daemon=True, name=f"run-{offer_id}").start()
        return (
            f"Offer {offer_id} accepted and recipe execution started "
            f"as {run_id} ({len(recipe.steps)} background steps). Call "
            f"run_status(run_id='{run_id}'); pay is enabled only after it "
            f"reports state=succeeded."
        )

    @skill
    def buy_and_run(self, listing_id: str) -> str:
        """Buy a listed skill and run its recipe in the sandbox.

        Verifies **before** paying: loads the listing's recipe, checks its
        content hash against the on-chain commitment, and sandbox-validates
        every step. Only when everything passes is the price paid (straight to
        the seller) and the recipe executed against the local primitives — the
        recipe is never imported or evaluated as code. On any refusal nothing
        is paid.

        Args:
            listing_id: The id of the listing to buy (from ``search_skills``).

        Returns:
            A purchase confirmation plus the per-step execution report, or the
            reason the listing was refused.
        """
        listing = self._chain.get_listing(listing_id)
        if not listing.active:
            return f"Refused listing {listing_id}: it is no longer active. Nothing was paid."
        rejection = self._spend_rejection(
            listing.price, f"listing {listing_id} purchase"
        )
        if rejection is not None:
            return rejection + " Nothing was paid."
        try:
            recipe = load_recipe(listing.recipe_uri)
        except (OSError, ValueError) as exc:
            return (
                f"Refused listing {listing_id}: could not load recipe from "
                f"{listing.recipe_uri!r}: {exc}. Nothing was paid."
            )

        actual = recipe.content_hash()
        if actual != listing.recipe_hash:
            return (
                f"Refused listing {listing_id}: recipe hash mismatch "
                f"(listing 0x{listing.recipe_hash[:12]}… vs file 0x{actual[:12]}…). "
                f"Nothing was paid."
            )

        interpreter = SandboxInterpreter(self._primitives)
        problems = interpreter.validate(recipe)
        if problems:
            return (
                f"Refused listing {listing_id}: recipe failed validation: "
                f"{'; '.join(problems)}. Nothing was paid."
            )

        run_id = self._run_id("listing", listing_id)
        with self._runs_lock:
            previous = self._runs.get(run_id)
            if previous is not None:
                return (
                    f"Listing {listing_id} already has local run {run_id} in "
                    f"state={previous.phase.value}; it will not be purchased again."
                )

        tx_ref = self._chain.buy_skill(listing_id)
        price = wei_to_inj(listing.price)
        record = RunRecord(run_id=run_id, payment_tx=tx_ref)
        with self._runs_lock:
            self._runs[run_id] = record

        # Run in background — real robot moves far exceed MCP's 120s HTTP
        # timeout; return immediately so the agent loop stays alive.
        def _bg_run() -> None:
            try:
                report = interpreter.run(recipe, abort=record.abort)
                phase = (
                    RunPhase.ABORTED
                    if record.abort.is_set()
                    else RunPhase.SUCCEEDED
                    if report.ok
                    else RunPhase.FAILED
                )
                with self._runs_lock:
                    record.phase = phase
                    record.summary = report.summary()
                logger.info("bought listing %s for %s INJ -> ok=%s", listing_id, price, report.ok)
            except Exception as exc:
                with self._runs_lock:
                    record.phase = RunPhase.FAILED
                    record.summary = f"execution error: {exc!r}"
                logger.error("background run failed for listing %s: %s", listing_id, exc)

        threading.Thread(target=_bg_run, daemon=True, name=f"run-{listing_id}").start()
        return (
            f"Bought listing {listing_id} for {price} INJ (tx {tx_ref}). "
            f"Recipe execution started as {run_id} ({len(recipe.steps)} background "
            f"steps). Call run_status(run_id='{run_id}') for its result."
        )

    @skill
    def run_status(self, run_id: str = "") -> str:
        """Report background recipe execution state and its final sandbox result.

        Args:
            run_id: The id returned by ``fetch_and_run`` or ``buy_and_run``
                (for example ``"offer:1"``). Empty lists every session run.

        Returns:
            Current state; successful offer runs are eligible for ``pay``.
        """
        with self._runs_lock:
            if run_id:
                records = [self._runs[run_id]] if run_id in self._runs else []
            else:
                records = list(self._runs.values())
            snapshots = [
                (record.run_id, record.phase.value, record.summary)
                for record in records
            ]
        if not snapshots:
            target = f" {run_id}" if run_id else ""
            return f"No local recipe run{target} is recorded in this process."
        lines = []
        for ident, phase, summary in snapshots:
            detail = f"\n{summary}" if summary else ""
            lines.append(f"{ident}: state={phase}{detail}")
        return "\n\n".join(lines)

    @skill
    def pay(self, offer_id: str) -> str:
        """Release the escrow to the responder and write two-way ratings.

        Call after :meth:`fetch_and_run` succeeded and the success criteria are
        met. Releases the request's escrow to the offer's responder and records
        a rating for the counterparty.

        Args:
            offer_id: The id of the fulfilled offer to settle.

        Returns:
            A confirmation of the release and the rating written.
        """
        offer = self._chain.get_offer(offer_id)
        if offer.status is OfferStatus.PAID:
            return f"Offer {offer_id} is already paid; no second release was sent."
        run_id = self._run_id("offer", offer_id)
        with self._runs_lock:
            record = self._runs.get(run_id)
            phase = None if record is None else record.phase
        if phase is not RunPhase.SUCCEEDED:
            state = "unknown" if phase is None else phase.value
            return (
                f"Refused payment for offer {offer_id}: local run {run_id} has "
                f"state={state}, not succeeded. Check run_status; escrow remains locked."
            )
        assert record is not None
        release_ref = self._chain.release_payment(offer_id)
        with self._runs_lock:
            record.phase = RunPhase.SETTLED
            record.payment_tx = release_ref
        score = self.config.default_rating
        try:
            self._chain.rate(offer_id, ratee=offer.responder, score=score)
            rating_note = f"and rated the recipe {score}/5"
        except Exception as exc:
            logger.error("payment released but rating failed for %s: %s", offer_id, exc)
            rating_note = f"but rating failed: {exc}"
        amount = wei_to_inj(offer.price)
        logger.info("settled offer %s (ref=%s)", offer_id, release_ref)
        return (
            f"Released {amount} INJ to {offer.responder} for offer {offer_id} "
            f"{rating_note} (tx {release_ref})."
        )

    @skill
    def stop_run(self) -> str:
        """Abort every recipe currently running in the background.

        Call when the user says stop / wants to interrupt a bought or fetched
        recipe mid-execution. Sets the cooperative abort flag on every active
        run: the step already in flight finishes (or is cancelled by the
        robot's own stop skill), and no further step is dispatched — so the
        robot's movement capability is handed back to you. Costs nothing and
        touches nothing on-chain; anything already paid stays paid.

        Returns:
            Which runs were signalled to stop, or a note that none were active.
        """
        with self._runs_lock:
            running = [
                record
                for record in self._runs.values()
                if record.phase is RunPhase.RUNNING
            ]
        if not running:
            return "No recipe is running in the background; nothing to stop."
        ids = sorted(record.run_id for record in running)
        for record in running:
            record.abort.set()
        logger.info("stop_run signalled %d active run(s): %s", len(ids), ids)
        return (
            f"Signalled {len(ids)} background run(s) to stop: {', '.join(ids)}. "
            f"The current step may take a moment to finish — use your own stop "
            f"skill if the robot must halt immediately."
        )


# Blueprint handle used by the market factory.
market_skills = MarketSkillContainer.blueprint
