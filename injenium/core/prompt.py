# Copyright 2026 Injenium
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0

"""Compose the market skill briefing onto the stock Go2 system prompt (spec §1).

We never edit ``dimos.agents.system_prompt`` in place. Instead we copy the
shipped ``SYSTEM_PROMPT`` string and append a market section describing the four
skills and the closed loop, then hand the result to
``McpClient.blueprint(system_prompt=...)``.
"""

from __future__ import annotations

from dimos.agents.system_prompt import SYSTEM_PROMPT

MARKET_PROMPT_SECTION = """
# SKILL MARKET (Injective)

You can buy and sell robot skills on an on-chain marketplace. Money is INJ held
in escrow by the market contract; recipes are parameterized, de-privatised
plans that run in a sandbox — never foreign code.

## When you are stuck
If you cannot complete a task with your own skills, publish it for others to
answer, then run the recipe you get back:
- `publish_request(need, budget)` — post the task and escrow an INJ bounty.
- `fetch_and_run(offer_id)` — once a dog answers, fetch its recipe, run it in
  the sandbox, and report the per-step result.
- `pay(offer_id)` — after the recipe succeeds, release the escrow and rate it.

## When another dog is stuck
The RequestListener will tell you (as a `[market]` message) when an open request
matches what you can do. If you have relevant recorded experience:
- `distill_and_publish(request_id, query)` — distil a recipe from your memory
  and post an offer against that request.

Only offer recipes for tasks you have actually performed. Keep budgets modest.
"""


def market_system_prompt(base: str | None = None) -> str:
    """Return the stock system prompt with the market section appended.

    Args:
        base: prompt to extend; defaults to the shipped dimOS ``SYSTEM_PROMPT``.
    """
    return f"{base or SYSTEM_PROMPT}\n{MARKET_PROMPT_SECTION}"
