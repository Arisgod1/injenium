# Copyright 2026 Injenium
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0

"""Deterministic per-robot wallet identity derived from ``ROBOT_IP``.

Every robot agent boots with a fixed ``ROBOT_IP`` env var (e.g. ``10.88.15.25``),
unique and stable per robot. We turn that into one wallet the robot uses across
the mock ledger and the Injective testnet, with no manual per-robot key
provisioning::

    private_key = sha256("injenium-wallet:v1:" + WALLET_SALT + ":" + ROBOT_IP)
    address     = EVM address of that key   (the mock ledger uses the same one)

``WALLET_SALT`` is an optional deployment secret; without it the key is
reconstructable from the (LAN-visible) IP alone, so set it for anything past a
throwaway demo.

SECURITY: an IP-derived key is only as secret as ``ROBOT_IP`` + ``WALLET_SALT``.
This is a testnet-PoC convenience. Deriving a signing key from a low-entropy IP
is **refused on mainnet** (see :func:`resolve_signing_key`); a real
``INJECTIVE_PRIVATE_KEY`` must be supplied there.
"""

from __future__ import annotations

import hashlib
import os
import warnings

ROBOT_IP_ENV = "ROBOT_IP"
WALLET_SALT_ENV = "WALLET_SALT"
PRIVATE_KEY_ENV = "INJECTIVE_PRIVATE_KEY"

_KEY_DOMAIN = "injenium-wallet:v1:"

# Fallback mock address when neither an explicit agent_id nor ROBOT_IP is set.
_DEFAULT_MOCK_ADDRESS = "0xA0000000000000000000000000000000000000A0"


def robot_ip() -> str | None:
    """The robot's fixed identity IP from the environment (``None`` if unset)."""
    ip = os.environ.get(ROBOT_IP_ENV, "").strip()
    return ip or None


def _seed(ip: str) -> bytes:
    salt = os.environ.get(WALLET_SALT_ENV, "")
    return (_KEY_DOMAIN + salt + ":" + ip).encode("utf-8")


def derive_private_key(ip: str) -> str:
    """Deterministic ``0x``-prefixed 32-byte hex private key for ``ip``."""
    return "0x" + hashlib.sha256(_seed(ip)).hexdigest()


def derive_address(ip: str) -> str:
    """EVM address of the key :func:`derive_private_key` produces for ``ip``.

    Uses ``eth-account`` for the exact secp256k1 address when the ``[chain]``
    extra is installed, so a robot's mock identity matches its on-chain one. On
    a pure-mock box without that extra it falls back to a deterministic
    pseudo-address — stable and unique, but not a real key's address (only ever
    used as a mock-ledger label, never to sign).
    """
    priv = derive_private_key(ip)
    try:
        from eth_account import Account  # noqa: PLC0415
    except Exception:  # pragma: no cover - [chain] extra not installed
        return "0x" + hashlib.sha256(("addr:" + priv).encode("utf-8")).hexdigest()[:40]
    return str(Account.from_key(priv).address)


def resolve_mock_address(explicit_agent_id: str = "") -> str:
    """Address the mock ledger acts as.

    An explicit ``agent_id`` wins; otherwise the ROBOT_IP-derived address; else a
    fixed PoC default.
    """
    if explicit_agent_id:
        return explicit_agent_id
    ip = robot_ip()
    return derive_address(ip) if ip else _DEFAULT_MOCK_ADDRESS


def resolve_signing_key(
    explicit: str | None = None, *, allow_ip_derivation: bool
) -> str:
    """The private key the real client signs with.

    Priority: an explicit key / ``INJECTIVE_PRIVATE_KEY`` always wins. Otherwise,
    when ``ROBOT_IP`` is set and ``allow_ip_derivation`` is true (testnet), the
    key is derived from it. On mainnet (``allow_ip_derivation`` false) IP
    derivation is refused so real funds are never guarded by a LAN-visible IP.
    """
    key = explicit or os.environ.get(PRIVATE_KEY_ENV)
    if key:
        return key
    ip = robot_ip()
    if not ip:
        raise RuntimeError(
            f"no signing key: set {PRIVATE_KEY_ENV} (or {ROBOT_IP_ENV} on testnet)."
        )
    if not allow_ip_derivation:
        raise RuntimeError(
            f"refusing to derive a wallet key from {ROBOT_IP_ENV} on mainnet; "
            f"set {PRIVATE_KEY_ENV} to a real key."
        )
    warnings.warn(
        f"deriving the signing wallet from {ROBOT_IP_ENV} (testnet only); "
        f"set {WALLET_SALT_ENV}, and prefer {PRIVATE_KEY_ENV} for anything real.",
        stacklevel=2,
    )
    return derive_private_key(ip)
