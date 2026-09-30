"""Bounded, restart-safe completion receipt worker.

Application lifecycle wiring belongs to the integrator. Calling ``start``
performs a recovery scan immediately; expired leases are reclaimed on each
scan. There is no in-memory queue or source-row reconstruction.
"""

from __future__ import annotations

import asyncio
import logging
from typing import Protocol

from app.learning_companions.reward_repository import (
    MAX_CLAIM_BATCH,
    InvalidReceiptError,
    ReceiptClaim,
    ReceiptPosting,
)


logger = logging.getLogger(__name__)


class RewardReceiptStore(Protocol):
    def claim_due(self, *, limit: int) -> tuple[ReceiptClaim, ...]: ...

    def post_claim(self, claim: ReceiptClaim) -> ReceiptPosting | None: ...

    def fail_claim(self, claim: ReceiptClaim, *, category: str) -> bool: ...


class RewardWorker:
    def __init__(self, store: RewardReceiptStore, *, poll_seconds: float = 15.0):
        if poll_seconds <= 0:
            raise ValueError("Reward worker poll interval must be positive.")
        self._store = store
        self._poll_seconds = poll_seconds
        self._task: asyncio.Task[None] | None = None

    async def run_once(self) -> int:
        """Process at most 50 receipts, claiming only the one being posted.

        This prevents queued work from using up its 60-second lease. The
        repeated claim also allows the next same-day receipt to become due
        immediately after its predecessor posts.
        """
        processed = 0
        while processed < MAX_CLAIM_BATCH:
            claims = await asyncio.to_thread(self._store.claim_due, limit=1)
            if not claims:
                break
            for claim in claims:
                try:
                    await asyncio.to_thread(self._store.post_claim, claim)
                except asyncio.CancelledError:
                    # Let the 60-second lease expire; a new worker can retry.
                    raise
                except Exception as error:
                    category = (
                        "invalid_receipt" if isinstance(error, InvalidReceiptError)
                        else "posting_failed"
                    )
                    await asyncio.to_thread(
                        self._store.fail_claim, claim, category=category
                    )
                processed += 1
        return processed

    async def _run(self) -> None:
        while True:
            try:
                await self.run_once()
            except asyncio.CancelledError:
                raise
            except Exception:
                # A transient claim failure should not kill startup recovery.
                # Exception text may contain database values, so log a static
                # operational signal and retry on the next poll.
                logger.warning("Reward worker scan failed; retrying.")
            await asyncio.sleep(self._poll_seconds)

    def start(self) -> None:
        if self._task is not None and not self._task.done():
            return
        self._task = asyncio.create_task(self._run(), name="learning-reward-worker")

    async def stop(self) -> None:
        task = self._task
        self._task = None
        if task is None:
            return
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass
