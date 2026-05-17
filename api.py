from __future__ import annotations

import asyncio
import json
import logging
import os
import time
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from typing import Optional

from fastapi import FastAPI, HTTPException, WebSocket, WebSocketDisconnect, Query, Request, Depends
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
import uvicorn

import config
from control.trading_mode import TradingMode

log = logging.getLogger(__name__)


def _require_auth(request: Request):
    if not config.API_AUTH_ENABLED:
        return
    api_key = request.headers.get("X-API-Key", "")
    if not api_key:
        raise HTTPException(status_code=401, detail="Missing X-API-Key header.")
    if api_key != config.API_SECRET_KEY:
        raise HTTPException(status_code=403, detail="Invalid API key.")


def _get_pipeline(request: Request):
    p = getattr(request.app.state, "pipeline", None)
    if p is None:
        raise HTTPException(status_code=503, detail="Pipeline not started yet.")
    return p


# ---- rate limiter for /prediction ----

class _TokenBucket:
    def __init__(self, rate: float, burst: int):
        self.rate = rate
        self.burst = burst
        self.tokens = float(burst)
        self.last_refill = time.monotonic()

    def consume(self) -> bool:
        now = time.monotonic()
        elapsed = now - self.last_refill
        self.tokens = min(self.burst, self.tokens + elapsed * self.rate)
        self.last_refill = now
        if self.tokens >= 1.0:
            self.tokens -= 1.0
            return True
        return False


_prediction_bucket = _TokenBucket(rate=10.0 / 60.0, burst=10)


# ---- lifespan ----

@asynccontextmanager
async def lifespan(app: FastAPI):
    from pipeline import Pipeline

    worker_count = int(os.getenv("API_WORKERS", "1"))
    if worker_count > 1:
        log.warning(
            "[api] Running %d uvicorn workers — each creates its own Pipeline, "
            "MarketWatcher, and trading logic. All workers share one Polymarket account. "
            "Set API_WORKERS=1 unless you have separate exchange accounts per worker.",
            worker_count,
        )

    app.state.pipeline = Pipeline()
    app.state.pipeline_task = asyncio.create_task(app.state.pipeline.run(), name="pipeline-main")
    log.info("[api] Pipeline started as background task")
    yield
    log.info("[api] Shutting down")
    app.state.pipeline_task.cancel()
    try:
        await app.state.pipeline_task
    except asyncio.CancelledError:
        pass


# ---- app ----

app = FastAPI(
    title="Polymarket Signal API",
    description="Real-time event-driven prediction market signal pipeline",
    version="3.0.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000", "http://127.0.0.1:3000"],
    allow_methods=["*"],
    allow_headers=["*"],
)


# ---- endpoints ----

@app.get("/health")
async def health():
    return {"status": "ok", "timestamp": datetime.now(timezone.utc).isoformat()}


@app.get("/status")
async def status(request: Request, pipeline=Depends(_get_pipeline), _auth=Depends(_require_auth)):
    result = pipeline.status()
    task = getattr(request.app.state, "pipeline_task", None)
    if task is not None and task.done():
        exc = task.exception()
        result["pipeline_error"] = str(exc) if exc else "task completed unexpectedly"
    return result


@app.get("/signals/recent")
async def signals_recent(
    limit: int = Query(default=20, ge=1, le=200),
    pipeline=Depends(_get_pipeline),
    _auth=Depends(_require_auth),
):
    from observability.logger import get_recent_trades
    trades = get_recent_trades(limit=limit)
    return {"count": len(trades), "signals": trades}


@app.get("/markets")
async def markets(
    category: Optional[str] = Query(default=None),
    source: Optional[str] = Query(default=None),
    pipeline=Depends(_get_pipeline),
    _auth=Depends(_require_auth),
):
    mkt_list = [
        {
            "condition_id": m.condition_id,
            "question": m.question,
            "category": m.category,
            "yes_price": m.yes_price,
            "no_price": m.no_price,
            "volume": m.volume,
            "end_date": m.end_date,
            "source": getattr(m, "source", "polymarket"),
        }
        for m in pipeline.watcher.tracked_markets
    ]
    if category:
        mkt_list = [m for m in mkt_list if m["category"] == category]
    if source:
        mkt_list = [m for m in mkt_list if m["source"] == source]

    poly_count   = sum(1 for m in mkt_list if m["source"] == "polymarket")
    kalshi_count = sum(1 for m in mkt_list if m["source"] == "kalshi")
    return {
        "count": len(mkt_list),
        "polymarket": poly_count,
        "kalshi": kalshi_count,
        "markets": mkt_list,
    }


@app.get("/stats")
async def stats(
    category: Optional[str] = Query(default=None),
    pipeline=Depends(_get_pipeline),
    _auth=Depends(_require_auth),
):
    from observability.logger import get_trade_stats, get_calibration_stats, get_latency_stats, get_category_stats
    result = {
        "trades": get_trade_stats(),
        "calibration": get_calibration_stats(),
        "latency": get_latency_stats(),
    }
    if category:
        all_cat_stats = get_category_stats()
        result["category"] = all_cat_stats.get(category, {})
    else:
        result["by_category"] = get_category_stats()
    return result


@app.get("/portfolio")
async def portfolio_state(pipeline=Depends(_get_pipeline), _auth=Depends(_require_auth)):
    from portfolio import get_portfolio
    return get_portfolio().get_portfolio_state()


@app.get("/categories")
async def categories_info(pipeline=Depends(_get_pipeline), _auth=Depends(_require_auth)):
    from ingestion.categories import CATEGORIES
    markets = pipeline.watcher.tracked_markets
    counts: dict[str, int] = {}
    for cat in CATEGORIES:
        counts[cat] = sum(1 for m in markets if getattr(m, "category", "") == cat)
    return {
        "available": list(CATEGORIES.keys()),
        "selected": config.SELECTED_CATEGORIES,
        "counts": counts,
    }


@app.get("/news/headlines")
async def news_headlines(limit: int = Query(default=50, ge=1, le=200)):
    """Recent raw headlines from the ingestion pipeline."""
    from ingestion.news_stream import get_recent_headlines
    headlines = get_recent_headlines(limit=limit)
    return {"count": len(headlines), "headlines": headlines}


@app.get("/sources")
async def sources(pipeline=Depends(_get_pipeline), _auth=Depends(_require_auth)):
    stats = pipeline.get_source_stats()
    agg = pipeline._news_aggregator
    rss_enabled = True
    newsapi_enabled = bool(agg.newsapi.enabled) if agg else False
    gnews_enabled = bool(agg.gnews.enabled) if agg else False
    twitter_enabled = bool(agg.twitter.enabled) if agg else False
    telegram_enabled = bool(agg.telegram.enabled) if agg else False
    return {
        "sources": {
            "rss":     {"enabled": rss_enabled,  "interval_s": 60},
            "newsapi": {"enabled": newsapi_enabled, "interval_s": 30},
            "reddit":  {"enabled": True,  "interval_s": 45},
            "gnews":   {"enabled": gnews_enabled, "interval_s": 900},
            "gdelt":   {"enabled": True,  "interval_s": 300},
            "twitter": {"enabled": twitter_enabled, "note": "requires Basic tier"},
            "telegram":{"enabled": telegram_enabled},
        },
        "event_counts": stats,
    }


@app.get("/subreddit-stats")
async def subreddit_stats(pipeline=Depends(_get_pipeline), _auth=Depends(_require_auth)):
    from ingestion.reddit_source import get_subreddit_stats
    rows = get_subreddit_stats()
    return {"subreddits": rows}


@app.get("/prediction")
async def prediction(
    request: Request,
    event: str = Query(..., description="Free-text news headline to analyze"),
    pipeline=Depends(_get_pipeline),
    _auth=Depends(_require_auth),
):
    if not _prediction_bucket.consume():
        raise HTTPException(status_code=429, detail="Rate limit exceeded. Max 10 req/min.")
    markets = pipeline.watcher.tracked_markets
    if not markets:
        raise HTTPException(status_code=503, detail="No markets loaded yet.")

    from signal.matcher import match_news_to_markets
    from signal.classifier import classify_async
    from signal.nlp_processor import process as nlp_process

    nlp = nlp_process(headline=event, source="api", age_seconds=0, novelty_score=0.5)
    matches = match_news_to_markets(event, markets, top_k=5)
    if not matches:
        return {
            "query": event,
            "nlp": {
                "category": nlp.category,
                "sentiment": round(nlp.sentiment_polarity, 3),
                "impact_score": round(nlp.impact_score, 3),
                "entities": [{"text": e.text, "label": e.label} for e in nlp.entities],
            },
            "matches": [],
        }

    top = matches[0]
    classification = await classify_async(headline=event, market=top.market, source="api", n_passes=1)

    results = []
    for m in matches:
        results.append({
            "market": m.market.question,
            "market_id": m.market.condition_id,
            "similarity": round(m.similarity, 3),
            "yes_price": m.market.yes_price,
        })

    return {
        "query": event,
        "nlp": {
            "category": nlp.category,
            "sentiment": round(nlp.sentiment_polarity, 3),
            "sentiment_confidence": round(nlp.sentiment_confidence, 3),
            "impact_score": round(nlp.impact_score, 3),
            "entities": [{"text": e.text, "label": e.label} for e in nlp.entities],
        },
        "classification": {
            "direction": classification.direction,
            "confidence": round(classification.confidence, 3),
            "materiality": round(classification.materiality, 3),
            "novelty": round(classification.novelty_score, 3),
            "reasoning": classification.reasoning,
            "actionable": classification.is_actionable,
        },
        "top_market_matches": results,
    }


@app.websocket("/ws/signals")
async def ws_signals(websocket: WebSocket):
    from observability import broadcaster

    await websocket.accept()
    q = broadcaster.subscribe()
    log.info("[api] WebSocket client connected")

    ping_task = None
    try:
        ping_task = asyncio.create_task(_ws_ping(websocket))
        while True:
            try:
                data = await asyncio.wait_for(q.get(), timeout=1.0)
                await websocket.send_text(json.dumps(data))
            except asyncio.TimeoutError:
                continue
    except WebSocketDisconnect:
        pass
    except Exception:
        log.debug("[api] WebSocket error", exc_info=True)
    finally:
        broadcaster.unsubscribe(q)
        if ping_task is not None:
            ping_task.cancel()
        log.info("[api] WebSocket client disconnected")


async def _ws_ping(websocket: WebSocket):
    while True:
        await asyncio.sleep(30)
        try:
            await websocket.send_text(json.dumps({"type": "ping"}))
        except Exception:
            break


class TradingModeRequest(BaseModel):
    mode: str
    confirm: bool = False


@app.post("/trading/mode")
async def set_trading_mode(
    request: TradingModeRequest,
    pipeline=Depends(_get_pipeline),
    _auth=Depends(_require_auth),
):
    result = TradingMode.instance().set_mode(request.mode, confirm=request.confirm)
    if not result["success"]:
        raise HTTPException(status_code=400, detail=result["error"])
    return result


@app.get("/trading/status")
async def get_trading_status(_auth=Depends(_require_auth)):
    tm = TradingMode.instance()
    return {
        "mode":    tm.mode,
        "is_live": tm.is_live,
        "history": tm.get_history()[-10:],
    }


# ── Runtime config endpoints ──────────────────────────────────────────

class ConfigOverrideRequest(BaseModel):
    overrides: dict[str, object]  # {"SIZING_K": 0.40, "MIN_CONFIDENCE": 0.50, ...}


@app.get("/config/risk")
async def get_risk_config():
    """Return current effective config values for all overridable keys."""
    import config as cfg
    return {
        "overrides": cfg.get_overrides(),
        "effective": cfg.get_effective_config(),
    }


@app.post("/config/risk")
async def set_risk_config(request: ConfigOverrideRequest):
    """Apply one or more runtime config overrides."""
    import config as cfg
    results = {}
    for key, value in request.overrides.items():
        ok = cfg.override(key, value)
        results[key] = "applied" if ok else "rejected"
    return {"results": results, "effective": cfg.get_effective_config()}


@app.post("/config/risk/reset")
async def reset_risk_config():
    """Reset all runtime config overrides to defaults."""
    import config as cfg
    cfg.restore()
    return {"status": "reset", "effective": cfg.get_effective_config()}


# ===========================================================================
# Debug / Observability endpoints
# ===========================================================================

@app.get("/debug/traces")
async def debug_traces(
    request: Request,
    status: str | None = Query(default=None),
    reason: str | None = Query(default=None),
    severity: str | None = Query(default=None),
    market_id: str | None = Query(default=None),
    limit: int = Query(default=50, ge=1, le=200),
    pipeline=Depends(_get_pipeline),
    _auth=Depends(_require_auth),
):
    from observability.logger import get_recent_traces
    traces = get_recent_traces(limit=limit, status=status, reason=reason, severity=severity)
    if market_id:
        traces = [t for t in traces if t.get("market_id") == market_id]
    return {"count": len(traces), "traces": traces}


@app.get("/debug/traces/{trace_id}")
async def debug_trace_detail(
    trace_id: str,
    pipeline=Depends(_get_pipeline),
    _auth=Depends(_require_auth),
):
    from observability.logger import get_trace_by_id
    from observability.tracer import get_trace as get_active, reconstruct_trace
    active = get_active(trace_id)
    if active:
        row = active.finalize()
        return {"source": "in_memory", "trace": row}
    row = get_trace_by_id(trace_id)
    if row:
        reconstructed = reconstruct_trace(trace_id, row)
        return {"source": "sqlite", "trace": reconstructed}
    raise HTTPException(status_code=404, detail=f"Trace {trace_id} not found")


@app.get("/debug/rejections")
async def debug_rejections(
    since: str | None = Query(default=None),
    pipeline=Depends(_get_pipeline),
    _auth=Depends(_require_auth),
):
    from observability.logger import get_rejection_analytics
    window = 3600
    if since:
        import re
        m = re.match(r"(\d+)(h|m)", since)
        if m:
            val = int(m.group(1))
            unit = m.group(2)
            window = val * 3600 if unit == "h" else val * 60
    return get_rejection_analytics(window_seconds=window)


@app.get("/debug/pipeline")
async def debug_pipeline(
    pipeline=Depends(_get_pipeline),
    _auth=Depends(_require_auth),
):
    from observability.inspector import inspect
    result = inspect(pipeline)
    return result.__dict__


@app.get("/debug/heatmap")
async def debug_heatmap(
    window: int = Query(default=3600, ge=60, le=86400),
    pipeline=Depends(_get_pipeline),
    _auth=Depends(_require_auth),
):
    from observability.inspector import get_heatmap
    result = get_heatmap(pipeline, window_seconds=window)
    return result.__dict__


@app.get("/debug/stages")
async def debug_stages(
    pipeline=Depends(_get_pipeline),
    _auth=Depends(_require_auth),
):
    from observability.stage_timer import get_stage_timer
    timer = get_stage_timer()
    dists = timer.get_all_distributions()
    return {
        stage: {
            "p50_ms": round(d.p50_us / 1000, 2),
            "p95_ms": round(d.p95_us / 1000, 2),
            "p99_ms": round(d.p99_us / 1000, 2),
            "mean_ms": round(d.mean_us / 1000, 2),
            "min_ms": round(d.min_us / 1000, 2),
            "max_ms": round(d.max_us / 1000, 2),
            "count": d.count,
        }
        for stage, d in dists.items()
    }


@app.get("/debug/queues")
async def debug_queues(
    pipeline=Depends(_get_pipeline),
    _auth=Depends(_require_auth),
):
    from observability.inspector import _get_queue_depths
    result = _get_queue_depths(pipeline)
    return result.__dict__


@app.get("/debug/dlq")
async def debug_dlq(
    pipeline=Depends(_get_pipeline),
    _auth=Depends(_require_auth),
):
    from observability.logger import get_dlq_stats
    from observability.tracer import get_dlq
    in_memory = get_dlq().stats()
    persisted = get_dlq_stats()
    return {"in_memory": in_memory, "persisted": persisted}


@app.post("/debug/dlq/{dlq_id}/retry")
async def debug_dlq_retry(
    dlq_id: str,
    pipeline=Depends(_get_pipeline),
    _auth=Depends(_require_auth),
):
    from observability.tracer import get_dlq
    from observability.logger import update_dead_letter
    dlq = get_dlq()
    for dl in dlq._queue:
        if dl.dlq_id == dlq_id:
            dl.retry_count += 1
            dl.status = "pending"
            update_dead_letter(dlq_id, "retrying")
            return {"status": "retrying", "dlq_id": dlq_id, "retry_count": dl.retry_count}
    raise HTTPException(status_code=404, detail=f"DLQ entry {dlq_id} not found")


@app.post("/debug/dlq/{dlq_id}/bury")
async def debug_dlq_bury(
    dlq_id: str,
    pipeline=Depends(_get_pipeline),
    _auth=Depends(_require_auth),
):
    from observability.tracer import get_dlq
    from observability.logger import update_dead_letter
    dlq = get_dlq()
    if dlq.bury(dlq_id):
        update_dead_letter(dlq_id, "dead")
        return {"status": "buried", "dlq_id": dlq_id}
    raise HTTPException(status_code=404, detail=f"DLQ entry {dlq_id} not found")


@app.post("/live/approve")
async def live_approve(
    pipeline=Depends(_get_pipeline),
    _auth=Depends(_require_auth),
):
    """Approve the pending trade proposal for live execution."""
    from execution.live_safety import get_live_safety
    safety = get_live_safety()
    result = safety.approve_trade()
    if result is None:
        raise HTTPException(status_code=404, detail="No pending trade to approve")
    return result


@app.post("/live/reject")
async def live_reject(
    reason: str = Query(default="manual_rejection"),
    pipeline=Depends(_get_pipeline),
    _auth=Depends(_require_auth),
):
    """Reject the pending trade proposal."""
    from execution.live_safety import get_live_safety
    safety = get_live_safety()
    result = safety.reject_trade(reason)
    if result is None:
        raise HTTPException(status_code=404, detail="No pending trade to reject")
    return result


@app.get("/live/pending")
async def live_pending(
    pipeline=Depends(_get_pipeline),
    _auth=Depends(_require_auth),
):
    """View the pending trade proposal awaiting approval."""
    from execution.live_safety import get_live_safety
    safety = get_live_safety()
    # Check for expiry
    expired = safety.check_proposal_expiry()
    if expired:
        return {"status": "expired", "reason": expired}
    if safety._pending_approval is None:
        return {"status": "no_pending_trade"}
    return safety._pending_approval


@app.get("/live/eva")
async def live_eva(
    pipeline=Depends(_get_pipeline),
    _auth=Depends(_require_auth),
):
    """Expected vs Actual analysis — compare expectations against real exchange behavior."""
    from observability.eva_analysis import get_eva_analyzer
    from observability.exchange_logger import get_exchange_logger
    return {
        "eva": get_eva_analyzer().summary(),
        "exchange_payloads": len(get_exchange_logger()._payloads),
    }


@app.get("/live/snapshot")
async def live_snapshot(
    pipeline=Depends(_get_pipeline),
    _auth=Depends(_require_auth),
):
    """Capture a complete runtime snapshot for postmortem."""
    from execution.live_safety import get_live_safety
    safety = get_live_safety()
    return safety.snapshot_runtime(pipeline)


@app.post("/live/hard-stop")
async def live_hard_stop(
    reason: str = Query(default="api_triggered"),
    _auth=Depends(_require_auth),
):
    """EMERGENCY: immediately halt all execution."""
    from execution.live_safety import get_live_safety
    safety = get_live_safety()
    safety.hard_stop(reason)
    return {"status": "hard_stop_engaged", "reason": reason}


@app.post("/live/clear-stop")
async def live_clear_stop(
    _auth=Depends(_require_auth),
):
    """Clear hard stop after investigation."""
    from execution.live_safety import get_live_safety
    safety = get_live_safety()
    safety.clear_hard_stop()
    return {"status": "hard_stop_cleared"}


@app.get("/health")
async def debug_health(
    pipeline=Depends(_get_pipeline),
    _auth=Depends(_require_auth),
):
    return pipeline._health_monitor.status()


@app.get("/debug/supervisor")
async def debug_supervisor(
    pipeline=Depends(_get_pipeline),
    _auth=Depends(_require_auth),
):
    from execution.task_supervisor import get_task_supervisor
    from execution.reconciliation import get_reconciliation_engine
    from execution.settlement import get_settlement_engine
    from execution.market_sync import get_market_synchronizer
    from execution.circuit_breakers import get_circuit_breakers
    return {
        "tasks": get_task_supervisor().status(),
        "reconciliation": get_reconciliation_engine().status(),
        "settlement": get_settlement_engine().status(),
        "market_sync": get_market_synchronizer().status(),
        "circuit_breakers": get_circuit_breakers().status(),
        "risk_accounting": pipeline.risk.status() if hasattr(pipeline, 'risk') else {},
    }


@app.websocket("/ws/debug")
async def ws_debug(websocket: WebSocket):
    from observability import broadcaster
    await websocket.accept()
    q: asyncio.Queue = asyncio.Queue(maxsize=100)
    broadcaster._subscribers.append(q)
    log.info("[api] Debug WebSocket client connected")
    ping_task = None
    try:
        ping_task = asyncio.create_task(_ws_ping(websocket))
        while True:
            try:
                data = await asyncio.wait_for(q.get(), timeout=1.0)
                await websocket.send_text(json.dumps(data))
            except asyncio.TimeoutError:
                continue
    except WebSocketDisconnect:
        pass
    except Exception:
        log.debug("[api] Debug WebSocket error", exc_info=True)
    finally:
        try:
            broadcaster._subscribers.remove(q)
        except ValueError:
            pass
        if ping_task is not None:
            ping_task.cancel()
        log.info("[api] Debug WebSocket client disconnected")


if __name__ == "__main__":
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s  %(message)s",
        datefmt="%H:%M:%S",
    )
    for noisy in ("httpx", "httpcore", "sentence_transformers", "transformers"):
        logging.getLogger(noisy).setLevel(logging.WARNING)

    uvicorn.run(
        "api:app",
        host="0.0.0.0",
        port=int(os.getenv("API_PORT", "8000")),
        reload=False,
        log_level="warning",
    )
