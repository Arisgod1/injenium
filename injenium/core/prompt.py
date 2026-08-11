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

## Checking whether you can go on-chain
If asked "can you go on-chain?" / "do you have a blockchain skill?", call:
- `chain_status()` — read-only: reports your wallet address, balance, and
  whether the chain is reachable. It costs nothing and locks no escrow.

## When you are stuck
First call `search_skills(query)` — if a listed skill matches, buy it with
`buy_and_run(listing_id)`: instant and usually cheaper than a bounty.
**After buying, the recipe runs in the background on the robot — do NOT call
buy_and_run again or search again. Just wait.** Only when nothing matches,
publish the task for others to answer, then run the recipe you get back:
- `publish_request(need, budget)` — post the task and escrow an INJ bounty.
- `fetch_and_run(offer_id)` — once a dog answers, fetch its recipe, run it in
  the sandbox, and return a background run id.
- `run_status(run_id)` — wait until the run reports `state=succeeded`.
- `pay(offer_id)` — only after success, release the escrow and rate it.

## Interrupting a running recipe
While a bought/fetched recipe runs in the background it owns the robot's
movement — your own move/rotate goals will keep getting overridden. If the
user says stop or wants manual control back, call `stop_run()` first (aborts
the background recipe between steps), then use your normal stop skill to halt
the step in flight.

## Selling skills (auto-publish switch)
`set_auto_publish(enabled)` toggles the supply side of the economy. While it is
ON: after you successfully complete a task, call
`publish_skill(description, price, query)` to distill that experience and list
it for direct sale (price modestly, e.g. 0.05 INJ). A listing is a data good —
it stays on the board and can sell many times; buyers find it via
`search_skills` and pay you directly with `buy_and_run`.

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
