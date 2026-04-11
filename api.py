"""
REST + WebSocket API — FastAPI server that runs the pipeline as a background task.

Endpoints
---------
GET  /health                  — liveness check
GET  /status                  — pipeline status, uptime, risk state
GET  /signals/recent          — last N signals from SQLite
GET  /markets                 — currently tracked markets with prices
GET  /stats                   — trade stats, calibration accuracy, latency
GET  /sources                 — active news source status + event counts
GET  /subreddit-stats         — Reddit adaptive weight table
GET  /prediction?event=<text> — on-demand signal analysis for a free-text query
WS   /ws/signals              — real-time signal stream (JSON events)

Run:
    pip install fastapi uvicorn
    python api.py
    # or
    uvicorn api:app --host 0.0.0.0 --port 8000
"""
from __future__ import annotations

import asyncio
import json
import logging
import time
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from typing import Optional

log = logging.getLogger(__name__)


# ── Pipeline singleton ────────────────────────────────────────────────────────

_pipeline = None


def _get_pipeline():
    global _pipeline
    if _pipeline is None:
        from pipeline import Pipeline
        _pipeline = Pipeline()
    return _pipeline


# ── App lifespan: start pipeline in background ────────────────────────────────

@asynccontextmanager
async def lifespan(app):
    pipeline = _get_pipeline()
    asyncio.create_task(pipeline.run(), name="pipeline-main")
    log.info("[api] Pipeline started as background task")
    yield
    log.info("[api] Shutting down")


# ── FastAPI app ───────────────────────────────────────────────────────────────

try:
    from fastapi import FastAPI, WebSocket, WebSocketDisconnect, Query
    from fastapi.responses import JSONResponse
    import uvicorn
except ImportError:
    raise ImportError(
        "FastAPI and uvicorn are required. Install: pip install fastapi uvicorn"
    )

app = FastAPI(
    title="Polymarket Signal API",
    description="Real-time event-driven prediction market signal pipeline",
    version="3.0.0",
    lifespan=lifespan,
)

from fastapi.middleware.cors import CORSMiddleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000", "http://127.0.0.1:3000"],
    allow_methods=["*"],
    allow_headers=["*"],
)


# ── Health ────────────────────────────────────────────────────────────────────

@app.get("/health")
async def health():
    return {"status": "ok", "timestamp": datetime.now(timezone.utc).isoformat()}


# ── Pipeline status ───────────────────────────────────────────────────────────

@app.get("/status")
async def status():
    pipeline = _get_pipeline()
    return pipeline.status()


# ── Recent signals ────────────────────────────────────────────────────────────

@app.get("/signals/recent")
async def signals_recent(limit: int = Query(default=20, ge=1, le=200)):
    from logger import get_recent_trades
    trades = get_recent_trades(limit=limit)
    return {"count": len(trades), "signals": trades}


# ── Tracked markets ───────────────────────────────────────────────────────────

@app.get("/markets")
async def markets():
    pipeline = _get_pipeline()
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
    poly_count   = sum(1 for m in mkt_list if m["source"] == "polymarket")
    kalshi_count = sum(1 for m in mkt_list if m["source"] == "kalshi")
    return {
        "count": len(mkt_list),
        "polymarket": poly_count,
        "kalshi": kalshi_count,
        "markets": mkt_list,
    }


# ── Stats ─────────────────────────────────────────────────────────────────────

@app.get("/stats")
async def stats():
    from logger import get_trade_stats, get_calibration_stats, get_latency_stats
    return {
        "trades": get_trade_stats(),
        "calibration": get_calibration_stats(),
        "latency": get_latency_stats(),
    }


# ── News source status ────────────────────────────────────────────────────────

@app.get("/sources")
async def sources():
    pipeline = _get_pipeline()
    agg = pipeline._news_aggregator
    if agg is None:
        return {"error": "pipeline not yet started"}
    stats = dict(agg.stats)
    return {
        "sources": {
            "rss":     {"enabled": True,  "interval_s": 60},
            "newsapi": {"enabled": bool(agg.newsapi.enabled), "interval_s": 30},
            "reddit":  {"enabled": True,  "interval_s": 45},
            "gnews":   {"enabled": bool(agg.gnews.enabled), "interval_s": 900},
            "gdelt":   {"enabled": True,  "interval_s": 300},
            "twitter": {"enabled": bool(agg.twitter.enabled), "note": "requires Basic tier"},
            "telegram":{"enabled": bool(agg.telegram.enabled)},
        },
        "event_counts": stats,
    }


# ── Reddit adaptive weights ───────────────────────────────────────────────────

@app.get("/subreddit-stats")
async def subreddit_stats():
    from reddit_source import get_subreddit_stats
    rows = get_subreddit_stats()
    return {"subreddits": rows}


# ── On-demand prediction ──────────────────────────────────────────────────────

@app.get("/prediction")
async def prediction(event: str = Query(..., description="Free-text news headline to analyze")):
    """
    Classify a custom headline against all tracked markets and return signal candidates.
    Useful for manual testing or external callers.
    """
    from matcher import match_news_to_markets
    from classifier import classify_async
    from nlp_processor import process as nlp_process

    pipeline = _get_pipeline()
    markets = pipeline.watcher.tracked_markets
    if not markets:
        return JSONResponse(status_code=503, content={"error": "no markets loaded yet"})

    # NLP enrichment
    nlp = nlp_process(headline=event, source="api", age_seconds=0, novelty_score=0.5)

    # Semantic match
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

    # Classify top match
    top = matches[0]
    classification = await classify_async(
        headline=event,
        market=top.market,
        source="api",
        n_passes=1,   # single pass for latency
    )

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


# ── WebSocket real-time signal stream ─────────────────────────────────────────

@app.websocket("/ws/signals")
async def ws_signals(websocket: WebSocket):
    """
    Streams live signals as JSON objects.
    Each message: {"type": "signal", "side": "YES"|"NO", "market": "...", ...}
    Sends a heartbeat {"type": "ping"} every 30s to keep connection alive.
    """
    import broadcaster

    await websocket.accept()
    q = broadcaster.subscribe()
    log.info("[api] WebSocket client connected")

    try:
        ping_task = asyncio.create_task(_ws_ping(websocket))
        while True:
            try:
                data = await asyncio.wait_for(q.get(), timeout=1.0)
                await websocket.send_text(json.dumps(data))
            except asyncio.TimeoutError:
                continue
    except (WebSocketDisconnect, Exception):
        pass
    finally:
        broadcaster.unsubscribe(q)
        ping_task.cancel()
        log.info("[api] WebSocket client disconnected")


async def _ws_ping(websocket: WebSocket):
    while True:
        await asyncio.sleep(30)
        try:
            await websocket.send_text(json.dumps({"type": "ping"}))
        except Exception:
            break


# ── Entry point ───────────────────────────────────────────────────────────────

if __name__ == "__main__":
    import os
    from dotenv import load_dotenv
    load_dotenv()

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s  %(message)s",
        datefmt="%H:%M:%S",
    )
    # Silence noisy libraries
    for noisy in ("httpx", "httpcore", "sentence_transformers", "transformers"):
        logging.getLogger(noisy).setLevel(logging.WARNING)

    uvicorn.run(
        "api:app",
        host="0.0.0.0",
        port=int(os.getenv("API_PORT", "8000")),
        reload=False,
        log_level="warning",  # uvicorn access log → warning; our handlers are INFO
    )
