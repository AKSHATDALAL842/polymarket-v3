from __future__ import annotations

import asyncio
import json
import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

log = logging.getLogger(__name__)

_LABEL_STORE = Path(__file__).parent.parent / "models" / "labels.jsonl"
_RETRAIN_THRESHOLD = 50


@dataclass
class ColdPathJob:
    headline: str
    source: str
    market_id: str
    market_question: str
    yes_price: float
    fast_confidence: float
    is_loss_trade: bool
    timestamp: str


class ColdPathWorker:

    def __init__(self) -> None:
        self._queue: asyncio.Queue = asyncio.Queue(maxsize=200)
        self._label_count = self._count_existing_labels()

    def _count_existing_labels(self) -> int:
        if not _LABEL_STORE.exists():
            return 0
        with open(_LABEL_STORE) as f:
            return sum(1 for line in f if line.strip())

    def submit(self, job: ColdPathJob) -> None:
        try:
            self._queue.put_nowait(job)
        except asyncio.QueueFull:
            log.debug("[cold_path] Queue full — dropping job")

    async def run(self) -> None:
        log.info("[cold_path] Worker started")
        while True:
            job: ColdPathJob = await self._queue.get()
            try:
                await self._process(job)
            except Exception as e:
                log.warning(f"[cold_path] Job error: {e}")

    async def _process(self, job: ColdPathJob) -> None:
        is_borderline = 0.40 <= job.fast_confidence <= 0.70
        if not is_borderline and not job.is_loss_trade:
            return

        from signal.classifier import classify_async
        from ingestion.markets import Market

        stub = Market(
            condition_id=job.market_id,
            question=job.market_question,
            category="",
            yes_price=job.yes_price,
            no_price=1.0 - job.yes_price,
            volume=0,
            end_date="",
            active=True,
            tokens=[],
        )

        try:
            cls = await classify_async(headline=job.headline, market=stub, source=job.source)
            if cls.direction != "NEUTRAL":
                self._write_label(job, cls.direction)
                self._label_count += 1
                if self._label_count % _RETRAIN_THRESHOLD == 0:
                    await self._trigger_retrain()
        except Exception as e:
            log.debug(f"[cold_path] LLM labeling error: {e}")

    def _write_label(self, job: ColdPathJob, label: str) -> None:
        _LABEL_STORE.parent.mkdir(parents=True, exist_ok=True)
        record = {
            "headline": job.headline,
            "source": job.source,
            "yes_price": job.yes_price,
            "label": label,
            "fast_confidence": job.fast_confidence,
            "timestamp": job.timestamp,
        }
        with open(_LABEL_STORE, "a") as f:
            f.write(json.dumps(record) + "\n")
        log.debug(f"[cold_path] Wrote label {label} for: {job.headline[:60]}")

    async def _trigger_retrain(self) -> None:
        log.info(f"[cold_path] {self._label_count} labels accumulated — retraining")
        loop = asyncio.get_running_loop()
        await loop.run_in_executor(None, self._retrain_sync)

    def _retrain_sync(self) -> None:
        from signal.fast_classifier import train, _lgbm_model
        import signal.fast_classifier as fc
        success = train(str(_LABEL_STORE))
        if success:
            fc._lgbm_model = None
            fc._load_lgbm()


_worker: Optional[ColdPathWorker] = None


def get_cold_path_worker() -> ColdPathWorker:
    global _worker
    if _worker is None:
        _worker = ColdPathWorker()
    return _worker
