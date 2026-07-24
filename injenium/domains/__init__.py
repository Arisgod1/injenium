# Copyright 2026 Injenium
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0

"""Capability domains: pluggable primitive sets + providers + distillers.

Each domain package registers its primitives into
:data:`injenium.core.registry.default_registry` and its distiller via
:func:`injenium.core.distill.set_default_distiller` on import, then exposes a
blueprint built through :func:`injenium.core.blueprint.build_market`.
"""
