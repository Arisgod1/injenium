# Copyright 2026 Injenium
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0

"""The distiller contract: recorded experience -> a shareable :class:`Recipe`.

Distilling is domain-specific (a robot reads odom/images; another domain reads
its own logs), so the core only defines the :class:`Distiller` interface and a
process-global default that a domain sets on import (mirroring the primitive
registry). The market skill calls :func:`get_default_distiller`.
"""

from __future__ import annotations

from typing import Any, Protocol, runtime_checkable

from injenium.core.recipe import Recipe


@runtime_checkable
class Distiller(Protocol):
    """Turns a domain's recorded experience source into a saved recipe."""

    def distill(
        self,
        *,
        intent: str,
        source: str,
        artifacts_dir: str,
        query: str | None = None,
        success_criteria: str = "",
        storage: str = "local",
        ipfs_api_url: str | None = None,
        **kwargs: Any,
    ) -> tuple[Recipe, str]:
        """Return ``(recipe, uri)`` — recipe saved; uri local dir or ipfs://cid."""
        ...


_default: Distiller | None = None


def set_default_distiller(distiller: Distiller) -> None:
    """Register the process-wide distiller (a domain calls this on import)."""
    global _default
    _default = distiller


def get_default_distiller() -> Distiller:
    if _default is None:
        raise RuntimeError(
            "no distiller registered; import a capability domain "
            "(e.g. `import injenium.domains.go2`) before distilling."
        )
    return _default
