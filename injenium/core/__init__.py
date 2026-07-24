# Copyright 2026 Injenium
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0

"""Injenium core — the domain-agnostic experience-capability market.

Everything here is domain-neutral: the chain surface, the market skills, the
content-addressed recipe model, the registry-driven sandbox, identity and the
``build_market`` blueprint factory. Domain plugins (e.g.
:mod:`injenium.domains.go2`) register their primitives + provider + distiller
against this core without modifying it.
"""
