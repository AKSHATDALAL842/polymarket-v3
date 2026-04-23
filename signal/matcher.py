from __future__ import annotations

import logging
import time
from dataclasses import dataclass
from typing import Callable

import numpy as np

import config
from ingestion.markets import Market

log = logging.getLogger(__name__)

EmbedFn = Callable[[list[str]], np.ndarray]

_embed_fn: EmbedFn | None = None


def _load_sentence_transformers() -> EmbedFn:
    try:
        import os
        hf_token = os.getenv("HF_TOKEN") or config.ANTHROPIC_API_KEY and None
        from sentence_transformers import SentenceTransformer
        model = SentenceTransformer("all-MiniLM-L6-v2", token=hf_token or None)
        log.info("[matcher] Loaded sentence-transformers (all-MiniLM-L6-v2)")

        def embed(texts: list[str]) -> np.ndarray:
            vecs = model.encode(texts, normalize_embeddings=True, show_progress_bar=False)
            return vecs.astype(np.float32)

        return embed
    except ImportError:
        raise ImportError("sentence-transformers not installed. Run: pip install sentence-transformers")


def _load_openai_embeddings() -> EmbedFn:
    import httpx

    def embed(texts: list[str]) -> np.ndarray:
        resp = httpx.post(
            "https://api.openai.com/v1/embeddings",
            headers={"Authorization": f"Bearer {config.OPENAI_API_KEY}"},
            json={"model": "text-embedding-3-small", "input": texts},
            timeout=15,
        )
        resp.raise_for_status()
        data = resp.json()["data"]
        vecs = np.array([d["embedding"] for d in data], dtype=np.float32)
        norms = np.linalg.norm(vecs, axis=1, keepdims=True)
        return vecs / np.maximum(norms, 1e-9)

    log.info("[matcher] Using OpenAI text-embedding-3-small")
    return embed


def get_embed_fn() -> EmbedFn:
    global _embed_fn
    if _embed_fn is not None:
        return _embed_fn

    backend = config.EMBEDDING_BACKEND
    try:
        if backend == "openai" and config.OPENAI_API_KEY:
            _embed_fn = _load_openai_embeddings()
        else:
            _embed_fn = _load_sentence_transformers()
    except ImportError:
        log.warning("[matcher] Embedding backend unavailable — using keyword fallback")
        _embed_fn = None

    return _embed_fn


@dataclass
class _MarketEmbedding:
    market: Market
    vector: np.ndarray


class MarketEmbeddingCache:

    def __init__(self):
        self._cache: dict[str, _MarketEmbedding] = {}
        self._last_build: float = 0.0

    def update(self, markets: list[Market]) -> None:
        embed = get_embed_fn()
        if embed is None:
            return

        new_ids = {m.condition_id for m in markets}
        stale = set(self._cache) - new_ids
        for sid in stale:
            del self._cache[sid]

        to_embed = [m for m in markets if m.condition_id not in self._cache]
        if not to_embed:
            return

        t0 = time.monotonic()
        texts = [m.question for m in to_embed]
        try:
            vecs = embed(texts)
            for m, vec in zip(to_embed, vecs):
                self._cache[m.condition_id] = _MarketEmbedding(market=m, vector=vec)
            self._last_build = time.monotonic()
            log.debug(
                f"[matcher] Embedded {len(to_embed)} markets in "
                f"{int((time.monotonic() - t0)*1000)}ms, "
                f"cache size={len(self._cache)}"
            )
        except Exception as e:
            log.warning(f"[matcher] Embedding update failed: {e}")

    def all_entries(self) -> list[_MarketEmbedding]:
        return list(self._cache.values())


_cache = MarketEmbeddingCache()


def update_market_embeddings(markets: list[Market]) -> None:
    _cache.update(markets)


@dataclass
class MarketMatch:
    market: Market
    similarity: float
    match_method: str


def match_news_to_markets(
    headline: str,
    markets: list[Market],
    top_k: int | None = None,
    min_similarity: float | None = None,
) -> list[MarketMatch]:
    k = top_k or config.MATCHER_TOP_K
    threshold = min_similarity if min_similarity is not None else config.MATCHER_MIN_SIMILARITY

    embed = get_embed_fn()

    if embed is not None and _cache.all_entries():
        return _semantic_match(headline, k, threshold)

    return _keyword_match(headline, markets, k)


def _semantic_match(
    headline: str,
    top_k: int,
    threshold: float,
) -> list[MarketMatch]:
    embed = get_embed_fn()
    entries = _cache.all_entries()
    if not entries:
        return []

    try:
        query_vec = embed([headline])[0]
    except Exception as e:
        log.warning(f"[matcher] Query embedding failed: {e}")
        return []

    matrix = np.stack([e.vector for e in entries])  # (N, D), already normalized
    scores = matrix @ query_vec

    ranked_idx = np.argsort(-scores)
    results = []
    for idx in ranked_idx:
        sim = float(scores[idx])
        if sim < threshold:
            break
        if len(results) >= top_k:
            break
        results.append(MarketMatch(
            market=entries[idx].market,
            similarity=sim,
            match_method="semantic",
        ))

    return results


def _keyword_match(
    headline: str,
    markets: list[Market],
    top_k: int,
) -> list[MarketMatch]:
    headline_lower = headline.lower()
    scored: list[tuple[float, Market]] = []

    for market in markets:
        keywords = _extract_keywords(market.question)
        if not keywords:
            continue
        hits = sum(1 for kw in keywords if kw in headline_lower)
        if hits == 0:
            continue
        score = hits / len(keywords)
        scored.append((score, market))

    scored.sort(key=lambda x: x[0], reverse=True)
    return [
        MarketMatch(market=m, similarity=s, match_method="keyword")
        for s, m in scored[:top_k]
        if s > 0
    ]


def _extract_keywords(question: str) -> list[str]:
    stopwords = {
        "will", "the", "a", "an", "be", "by", "in", "on", "at", "to",
        "of", "for", "is", "it", "this", "that", "and", "or", "not",
        "before", "after", "end", "yes", "no", "any", "has", "have",
        "does", "do", "than", "more", "less", "over", "under", "above",
        "below", "through", "during", "between", "reach", "exceed",
    }
    words = question.lower().split()
    return [
        w.strip("?.,!\"'()[]")
        for w in words
        if w.strip("?.,!\"'()[]") not in stopwords and len(w.strip("?.,!\"'()[]")) > 2
    ]
