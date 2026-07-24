# Copyright 2026 Injenium
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0

"""Go2 (robot-dog) capability domain.

Importing this package registers the domain into the core: its primitive
whitelist + dispatch adapters go into ``default_registry`` and its
:class:`~injenium.domains.go2.distiller.Go2Distiller` becomes the default
distiller. dimOS workers that load a Go2 blueprint import this package, so the
registration is present wherever the market skills run.
"""

from __future__ import annotations

from injenium.core.distill import set_default_distiller
from injenium.core.registry import default_registry
from injenium.domains.go2 import primitives as _primitives

_primitives.register(default_registry)

from injenium.domains.go2.distiller import Go2Distiller  # noqa: E402

set_default_distiller(Go2Distiller())
