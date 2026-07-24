# Copyright 2026 Injenium
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0

"""The four agent-facing market skills (spec §5).

:class:`MarketSkillContainer` is a dimOS ``Module`` whose ``@skill`` methods the
LLM calls to drive the closed loop:

    publish_request  -> distill_and_publish -> fetch_and_run -> pay

Each skill obeys the dimOS skill contract (docstring + fully typed args + ``str``
return) so it shows up in ``dimos mcp list-tools`` and is callable via
``dimos mcp call``. The chain surface is obtained through
:func:`~injenium.chain.factory.build_chain_client`, so the identical skill
code runs against the mock ledger or the Injective testnet by config alone.

Recipe execution in :meth:`fetch_and_run` goes through the sandbox, calling the
injected :class:`~injenium.specs.PrimitiveSkillsSpec` provider — foreign
recipe bytes are never imported or ``eval``'d.
"""

from __future__ import annotations

from dimos.agents.annotation import skill
from dimos.core.core import rpc
from dimos.core.module import Module
from dimos.utils.logging_config import setup_logger

from injenium.chain.base import ChainClient, inj_to_wei, wei_to_inj
from injenium.chain.factory import build_chain_client
from injenium.config import MarketConfig
from injenium.distill import distill_to_recipe, load_recipe
from injenium.sandbox import SandboxInterpreter
from injenium.specs import PrimitiveSkillsSpec

logger = setup_logger()


class MarketSkillContainer(Module):
    """Hosts the publish / distill / fetch-run / pay skills for the agent.

    ``_primitives`` is injected by the coordinator at blueprint-build time
    (``MockPrimitives`` in the headless market blueprint, ``Go2Primitives`` on a
    real robot); the sandbox drives it during :meth:`fetch_and_run`.
    """

    config: MarketConfig

    _primitives: PrimitiveSkillsSpec

    @property
    def _chain(self) -> ChainClient:
        client = getattr(self, "_chain_client", None)
        if client is None:
            client = build_chain_client(self.config)
            self._chain_client = client
        return client

    @rpc
    def start(self) -> None:
        super().start()

    @rpc
    def stop(self) -> None:
        super().stop()

    # -- skills --------------------------------------------------------------

    @skill
    def publish_request(self, need: str, budget: float) -> str:
        """Publish a hard situation as an on-chain request with an escrow budget.

        Registers a request on the market board and locks ``budget`` INJ in
        escrow, to be released to whoever provides a working recipe. Use this
        when the robot is stuck and wants to buy a skill from another dog.

        Args:
            need: Natural-language description of the task the robot cannot do.
            budget: INJ amount to escrow as the bounty (e.g. ``1.5``).

        Returns:
            A human-readable confirmation including the new request id.
        """
        budget_wei = inj_to_wei(budget)
        request_id = self._chain.publish_request(need, budget_wei, tags=[])
        logger.info("published request %s (budget=%s INJ)", request_id, budget)
        return (
            f"Published request {request_id} with a {budget} INJ escrow budget. "
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
        recipe, recipe_uri = distill_to_recipe(
            db_path=self.config.memory_db,
            intent=request.need,
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
            A per-step execution report; call ``pay`` if it succeeded.
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

        self._chain.accept_offer(offer_id)
        report = interpreter.run(recipe)

        logger.info("ran offer %s -> ok=%s", offer_id, report.ok)
        outcome = "succeeded" if report.ok else "FAILED"
        return f"Offer {offer_id} recipe {outcome}.\n{report.summary()}"

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
        release_ref = self._chain.release_payment(offer_id)
        score = self.config.default_rating
        self._chain.rate(offer_id, ratee=offer.responder, score=score)
        amount = wei_to_inj(offer.price)
        logger.info("settled offer %s (ref=%s)", offer_id, release_ref)
        return (
            f"Released {amount} INJ to {offer.responder} for offer {offer_id} "
            f"and rated the recipe {score}/5 (tx {release_ref})."
        )


# Blueprint handle used by blueprint.py (spec §5: `market_skills = ...`).
market_skills = MarketSkillContainer.blueprint
