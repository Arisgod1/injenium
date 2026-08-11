# Copyright 2026 Injenium
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0

"""Atomic persistence for signed EVM transactions awaiting confirmation."""

from __future__ import annotations

from contextlib import contextmanager
from dataclasses import asdict, dataclass
import fcntl
import json
import os
from pathlib import Path
from typing import Any, Iterator


@dataclass(frozen=True)
class PendingTx:
    """Enough signed transaction data to confirm or rebroadcast after restart."""

    chain_id: int
    account: str
    nonce: int
    transaction_hash: str
    raw_transaction: str
    to: str
    data: str
    value: int
    start_block: int
    created_at: float

    @classmethod
    def from_dict(cls, raw: dict[str, Any]) -> PendingTx:
        return cls(**raw)


class PendingTxStore:
    """A small process-safe JSON store keyed by chain and account."""

    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)
        self._lock_path = self.path.with_suffix(self.path.suffix + ".lock")

    def get(self, chain_id: int, account: str) -> PendingTx | None:
        with self._locked():
            raw = self._read().get(self._key(chain_id, account))
            return None if raw is None else PendingTx.from_dict(raw)

    def put(self, pending: PendingTx) -> None:
        with self._locked():
            state = self._read()
            state[self._key(pending.chain_id, pending.account)] = asdict(pending)
            self._write(state)

    def remove(self, chain_id: int, account: str) -> None:
        with self._locked():
            state = self._read()
            if state.pop(self._key(chain_id, account), None) is not None:
                self._write(state)

    @staticmethod
    def _key(chain_id: int, account: str) -> str:
        return f"{int(chain_id)}:{account.lower()}"

    @contextmanager
    def _locked(self) -> Iterator[None]:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self._lock_path.open("a+") as lock_file:
            os.chmod(self._lock_path, 0o600)
            fcntl.flock(lock_file.fileno(), fcntl.LOCK_EX)
            try:
                yield
            finally:
                fcntl.flock(lock_file.fileno(), fcntl.LOCK_UN)

    def _read(self) -> dict[str, dict[str, Any]]:
        if not self.path.exists():
            return {}
        try:
            value = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise RuntimeError(f"cannot read pending transaction store {self.path}") from exc
        if not isinstance(value, dict):
            raise RuntimeError(f"invalid pending transaction store {self.path}")
        return value

    def _write(self, state: dict[str, dict[str, Any]]) -> None:
        temporary = self.path.with_name(f".{self.path.name}.{os.getpid()}.tmp")
        descriptor = os.open(
            temporary,
            os.O_WRONLY | os.O_CREAT | os.O_TRUNC,
            0o600,
        )
        try:
            with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
                json.dump(state, handle, indent=2, sort_keys=True)
                handle.write("\n")
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temporary, self.path)
            os.chmod(self.path, 0o600)
        finally:
            if temporary.exists():
                temporary.unlink()
