# Copyright 2026 Injenium
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0

"""Reliable, serialized EVM transaction submission for one signing account."""

from __future__ import annotations

from dataclasses import dataclass
import logging
from pathlib import Path
from threading import Lock
import time
from typing import Any

from injenium.core.chain.pending_store import PendingTx, PendingTxStore

logger = logging.getLogger(__name__)


class TransactionReplacedError(RuntimeError):
    """Raised when another payload is mined with a transaction's nonce."""


class TransactionRevertedError(RuntimeError):
    """Raised when a confirmed EVM transaction has status 0."""


@dataclass(frozen=True)
class TxResult:
    """A confirmed transaction, with a receipt when the RPC indexes one."""

    transaction_hash: str
    nonce: int
    receipt: Any | None
    block_number: int | None
    confirmed_by_nonce: bool = False


class TxManager:
    """Build, sign, broadcast, and confirm writes for a single EVM account.

    A process-local lock prevents concurrent skills from selecting the same
    nonce. Receipt polling is supplemented by block scans keyed by sender and
    nonce because some Injective RPC nodes advance account state before their
    transaction-receipt index becomes queryable.
    """

    def __init__(
        self,
        web3: Any,
        account: Any,
        chain_id: int,
        *,
        receipt_timeout: float = 180.0,
        poll_interval: float = 2.0,
        broadcast_attempts: int = 3,
        confirmations: int = 1,
        pending_store_path: str | Path | None = None,
        recovery_scan_blocks: int = 2048,
    ) -> None:
        self._w3 = web3
        self._account = account
        self._chain_id = int(chain_id)
        self._receipt_timeout = float(receipt_timeout)
        self._poll_interval = float(poll_interval)
        self._broadcast_attempts = int(broadcast_attempts)
        self._confirmations = int(confirmations)
        self._store = (
            None if pending_store_path is None else PendingTxStore(pending_store_path)
        )
        self._recovery_scan_blocks = int(recovery_scan_blocks)
        self._lock = Lock()
        self._next_nonce: int | None = None

    def send(self, fn: Any, *, value: int = 0) -> TxResult:
        """Submit one contract call and wait until it is confirmed."""
        with self._lock:
            self._recover_pending_locked()
            nonce = self._reserve_nonce()
            start_block = int(self._w3.eth.block_number)
            try:
                tx = fn.build_transaction(
                    {
                        "chainId": self._chain_id,
                        "from": self._account.address,
                        "nonce": nonce,
                        "value": int(value),
                        "gasPrice": self._w3.eth.gas_price,
                    }
                )
                signed = self._account.sign_transaction(tx)
                pending = self._make_pending(signed, tx, nonce, start_block)
                if self._store is not None:
                    self._store.put(pending)
                tx_hash = self._broadcast(signed.raw_transaction, signed.hash)
                result = self._confirm(tx_hash, nonce, tx, start_block)
                self._remove_pending()
                return result
            except (TransactionReplacedError, TransactionRevertedError):
                self._remove_pending()
                self._next_nonce = None
                raise
            except Exception:
                # Re-read the pending nonce on the next attempt. If this tx was
                # accepted despite an RPC error, the block scan above resolves
                # it before an exception reaches this point.
                self._next_nonce = None
                raise

    def recover_pending(self) -> TxResult | None:
        """Confirm or rebroadcast this account's persisted transaction."""
        with self._lock:
            return self._recover_pending_locked()

    def pending(self) -> PendingTx | None:
        """Return this account's persisted transaction without network access."""
        if self._store is None:
            return None
        return self._store.get(self._chain_id, self._account.address)

    def _recover_pending_locked(self) -> TxResult | None:
        pending = self.pending()
        if pending is None:
            return None
        built_tx = {
            "to": pending.to,
            "data": pending.data,
            "value": pending.value,
        }
        tx_hash = bytes.fromhex(pending.transaction_hash)
        receipt = self._get_receipt(tx_hash)
        if receipt is not None:
            try:
                self._check_receipt(receipt, pending.transaction_hash)
            except TransactionRevertedError:
                self._remove_pending()
                raise
            block_number = int(receipt["blockNumber"])
            self._wait_for_confirmations(
                block_number, time.monotonic() + self._receipt_timeout
            )
            self._remove_pending()
            return TxResult(
                pending.transaction_hash,
                pending.nonce,
                receipt,
                block_number,
            )

        current_block = int(self._w3.eth.block_number)
        first_block = max(
            pending.start_block,
            current_block - self._recovery_scan_blocks + 1,
        )
        mined = self._find_by_nonce(first_block, current_block, pending.nonce)
        if mined is not None:
            if not self._same_intent(mined, built_tx):
                self._remove_pending()
                raise TransactionReplacedError(
                    f"pending transaction {pending.transaction_hash} nonce "
                    f"{pending.nonce} was replaced by {self._hex(mined['hash'])}"
                )
            mined_hash = mined["hash"]
            receipt = self._get_receipt(mined_hash)
            if receipt is not None:
                try:
                    self._check_receipt(receipt, self._hex(mined_hash))
                except TransactionRevertedError:
                    self._remove_pending()
                    raise
            block_number = int(mined["blockNumber"])
            self._wait_for_confirmations(
                block_number, time.monotonic() + self._receipt_timeout
            )
            self._remove_pending()
            logger.info(
                "recovered confirmed transaction %s at nonce %s",
                pending.transaction_hash,
                pending.nonce,
            )
            return TxResult(
                self._hex(mined_hash),
                pending.nonce,
                receipt,
                block_number,
                confirmed_by_nonce=receipt is None,
            )

        latest_nonce = int(
            self._w3.eth.get_transaction_count(self._account.address, "latest")
        )
        if latest_nonce > pending.nonce:
            raise RuntimeError(
                f"cannot safely recover pending nonce {pending.nonce}: account "
                "nonce advanced but the matching transaction is outside the "
                "configured block scan window"
            )

        raw_transaction = bytes.fromhex(pending.raw_transaction)
        broadcast_hash = self._broadcast(raw_transaction, tx_hash)
        result = self._confirm(
            broadcast_hash,
            pending.nonce,
            built_tx,
            first_block,
        )
        self._remove_pending()
        logger.info(
            "rebroadcast and recovered transaction %s at nonce %s",
            pending.transaction_hash,
            pending.nonce,
        )
        return result

    def _make_pending(
        self, signed: Any, tx: dict[str, Any], nonce: int, start_block: int
    ) -> PendingTx:
        return PendingTx(
            chain_id=self._chain_id,
            account=str(self._account.address),
            nonce=nonce,
            transaction_hash=self._hex(signed.hash),
            raw_transaction=self._hex(signed.raw_transaction),
            to=str(tx.get("to", "")),
            data=self._hex(tx.get("data", b"")),
            value=int(tx.get("value", 0)),
            start_block=start_block,
            created_at=time.time(),
        )

    def _remove_pending(self) -> None:
        if self._store is not None:
            self._store.remove(self._chain_id, self._account.address)

    def _reserve_nonce(self) -> int:
        pending = int(
            self._w3.eth.get_transaction_count(self._account.address, "pending")
        )
        if self._next_nonce is None or self._next_nonce < pending:
            self._next_nonce = pending
        nonce = self._next_nonce
        self._next_nonce += 1
        return nonce

    def _broadcast(self, raw_transaction: Any, signed_hash: Any) -> Any:
        last_error: Exception | None = None
        for attempt in range(1, self._broadcast_attempts + 1):
            try:
                return self._w3.eth.send_raw_transaction(raw_transaction)
            except Exception as exc:  # RPC/provider exception types vary
                last_error = exc
                message = str(exc).lower()
                if "already known" in message or "known transaction" in message:
                    return signed_hash
                if attempt < self._broadcast_attempts:
                    logger.warning(
                        "transaction broadcast attempt %s/%s failed: %s",
                        attempt,
                        self._broadcast_attempts,
                        exc,
                    )
                    time.sleep(self._poll_interval)
        assert last_error is not None
        raise last_error

    def _confirm(
        self, tx_hash: Any, nonce: int, built_tx: dict[str, Any], start_block: int
    ) -> TxResult:
        deadline = time.monotonic() + self._receipt_timeout
        last_scanned = start_block
        tx_hash_hex = self._hex(tx_hash)
        while time.monotonic() < deadline:
            receipt = self._get_receipt(tx_hash)
            if receipt is not None:
                self._check_receipt(receipt, tx_hash_hex)
                block_number = int(receipt["blockNumber"])
                self._wait_for_confirmations(block_number, deadline)
                return TxResult(tx_hash_hex, nonce, receipt, block_number)

            current_block = int(self._w3.eth.block_number)
            mined = self._find_by_nonce(last_scanned, current_block, nonce)
            last_scanned = current_block + 1
            if mined is not None:
                mined_hash = mined["hash"]
                mined_hash_hex = self._hex(mined_hash)
                if not self._same_intent(mined, built_tx):
                    raise TransactionReplacedError(
                        f"transaction {tx_hash_hex} nonce {nonce} was replaced by "
                        f"{mined_hash_hex} with a different payload"
                    )
                receipt = self._get_receipt(mined_hash)
                if receipt is not None:
                    self._check_receipt(receipt, mined_hash_hex)
                block_number = int(mined["blockNumber"])
                self._wait_for_confirmations(block_number, deadline)
                return TxResult(
                    mined_hash_hex,
                    nonce,
                    receipt,
                    block_number,
                    confirmed_by_nonce=receipt is None,
                )

            time.sleep(self._poll_interval)

        latest_nonce = int(
            self._w3.eth.get_transaction_count(self._account.address, "latest")
        )
        detail = "account nonce advanced" if latest_nonce > nonce else "nonce unchanged"
        raise TimeoutError(
            f"transaction {tx_hash_hex} was not confirmed within "
            f"{self._receipt_timeout:g}s ({detail})"
        )

    def _find_by_nonce(
        self, first_block: int, last_block: int, nonce: int
    ) -> Any | None:
        if first_block > last_block:
            return None
        sender = str(self._account.address).lower()
        for block_number in range(first_block, last_block + 1):
            block = self._w3.eth.get_block(block_number, full_transactions=True)
            for tx in block["transactions"]:
                if str(tx.get("from", "")).lower() == sender and int(tx["nonce"]) == nonce:
                    return tx
        return None

    def _wait_for_confirmations(self, block_number: int, deadline: float) -> None:
        target = block_number + self._confirmations - 1
        while int(self._w3.eth.block_number) < target:
            if time.monotonic() >= deadline:
                raise TimeoutError(
                    f"transaction mined in block {block_number} but did not reach "
                    f"{self._confirmations} confirmation(s) in time"
                )
            time.sleep(self._poll_interval)

    def _get_receipt(self, tx_hash: Any) -> Any | None:
        try:
            return self._w3.eth.get_transaction_receipt(tx_hash)
        except Exception as exc:
            from web3.exceptions import TransactionNotFound  # noqa: PLC0415

            if isinstance(exc, TransactionNotFound):
                return None
            logger.warning("receipt lookup failed for %s: %s", self._hex(tx_hash), exc)
            return None

    @staticmethod
    def _check_receipt(receipt: Any, tx_hash: str) -> None:
        if int(receipt.get("status", 1)) != 1:
            raise TransactionRevertedError(f"transaction {tx_hash} reverted")

    @classmethod
    def _same_intent(cls, mined: Any, built: dict[str, Any]) -> bool:
        return (
            str(mined.get("to", "")).lower() == str(built.get("to", "")).lower()
            and cls._hex(mined.get("input", b"")) == cls._hex(built.get("data", b""))
            and int(mined.get("value", 0)) == int(built.get("value", 0))
        )

    @staticmethod
    def _hex(value: Any) -> str:
        if isinstance(value, str):
            return value.removeprefix("0x").lower()
        return bytes(value).hex()
