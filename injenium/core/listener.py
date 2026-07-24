# Copyright 2026 Injenium
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0

"""The "wait for requests" module (spec §2).

This is where the "do we need a backend?" question is answered: **no**. Waiting
for work is a resident :class:`~dimos.core.module.Module`, not a skill. On
``start`` it launches a background thread that polls the on-chain board every
``poll_interval`` seconds; when an open request matches this dog's declared
capabilities it nudges the agent through the same ``/human_input`` transport a
human would use, and the LLM decides whether to call ``distill_and_publish``.

The skeleton mirrors :class:`dimos.memory2.module.Recorder` (a subscribe-style
resident module) and reuses :class:`dimos.agents.web_human_input.WebInput`'s
notification path so no extra blueprint wiring is required.
"""

from __future__ import annotations

from threading import Event, Thread
from typing import Any

from dimos.constants import DEFAULT_THREAD_JOIN_TIMEOUT
from dimos.core.core import rpc
from dimos.core.module import Module
from dimos.core.transport_factory import make_transport
from dimos.utils.logging_config import setup_logger

from injenium.core.chain.base import ChainClient, Request, wei_to_inj
from injenium.core.chain.factory import build_chain_client
from injenium.core.config import RequestListenerConfig

logger = setup_logger()

# The topic McpClient reads as human input (see WebInput.start()).
_HUMAN_INPUT_TOPIC = "/human_input"


class RequestListener(Module):
    """Polls the market board and notifies the agent about answerable requests."""

    config: RequestListenerConfig

    def __init__(self, **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self._stop_event = Event()
        self._thread: Thread | None = None
        self._seen: set[str] = set()
        self._transport = None
        self._chain_client: ChainClient | None = None

    @property
    def _chain(self) -> ChainClient:
        if self._chain_client is None:
            self._chain_client = build_chain_client(self.config)
        return self._chain_client

    @rpc
    def start(self) -> None:
        super().start()
        self._transport = make_transport(_HUMAN_INPUT_TOPIC)
        self._stop_event.clear()
        self._thread = Thread(target=self._poll_loop, name="market-listener", daemon=True)
        self._thread.start()
        logger.info("RequestListener polling every %ss", self.config.poll_interval)

    @rpc
    def stop(self) -> None:
        self._stop_event.set()
        thread = self._thread
        if thread is not None:
            thread.join(timeout=DEFAULT_THREAD_JOIN_TIMEOUT)
            self._thread = None
        super().stop()

    # -- polling -------------------------------------------------------------

    def _poll_loop(self) -> None:
        while not self._stop_event.is_set():
            try:
                self._poll_once()
            except Exception:  # never let a transient board error kill the thread
                logger.exception("RequestListener poll failed")
            self._stop_event.wait(self.config.poll_interval)

    def _poll_once(self) -> None:
        me = self._chain.address
        for request in self._chain.list_open_requests():
            if request.requester == me or request.id in self._seen:
                continue
            if not self._matches(request):
                continue
            self._seen.add(request.id)
            self._notify(request)

    def _matches(self, request: Request) -> bool:
        """Answerable if no filters are set, or a tag/keyword matches the need."""
        tags = self.config.match_tags
        keywords = self.config.match_keywords
        if not tags and not keywords:
            return True
        if tags and set(tags) & set(request.tags):
            return True
        need = request.need.lower()
        return any(kw.lower() in need for kw in keywords)

    def _notify(self, request: Request) -> None:
        budget = wei_to_inj(request.budget)
        message = (
            f"[market] An answerable request is open: id={request.id}, "
            f"budget={budget} INJ, need={request.need!r}. If you can help, call "
            f"distill_and_publish(request_id={request.id!r}, query=...)."
        )
        logger.info("notifying agent about request %s", request.id)
        if self._transport is not None:
            try:
                self._transport.publish(message)
            except Exception:  # pragma: no cover - transport backend dependent
                logger.exception("failed to publish market notification")


# Blueprint handle used by blueprint.py.
request_listener = RequestListener.blueprint
