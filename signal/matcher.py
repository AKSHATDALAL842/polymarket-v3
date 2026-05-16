from __future__ import annotations

import logging
import os
import time
from dataclasses import dataclass, field
from typing import Callable

import numpy as np

import config
from ingestion.markets import Market

# Must be set before sentence-transformers or huggingface_hub are imported —
# tqdm progress bars crash with BrokenPipeError in asyncio subprocess contexts.
os.environ.setdefault("HF_HUB_DISABLE_PROGRESS_BARS", "1")
os.environ.setdefault("TQDM_DISABLE", "1")

log = logging.getLogger(__name__)

EmbedFn = Callable[[list[str]], np.ndarray]

_embed_fn: EmbedFn | None = None
_embed_load_attempted: bool = False  # set True after first attempt, even if it failed


def _load_sentence_transformers() -> EmbedFn:
    try:
        # Suppress all output during model load — tqdm/transformers progress
        # bars crash with BrokenPipeError in asyncio contexts.
        import sys as _sys
        _real_stderr = _sys.stderr
        _sys.stderr = open(os.devnull, 'w')
        try:
            from sentence_transformers import SentenceTransformer
            model = SentenceTransformer("all-MiniLM-L6-v2", token=os.getenv("HF_TOKEN") or None)
        finally:
            _sys.stderr.close()
            _sys.stderr = _real_stderr

        log.info("[matcher] Loaded sentence-transformers (all-MiniLM-L6-v2)")

        def embed(texts: list[str]) -> np.ndarray:
            vecs = model.encode(texts, normalize_embeddings=True, show_progress_bar=False)
            return vecs.astype(np.float32)

        return embed
    except ImportError:
        raise ImportError("sentence-transformers not installed. Run: pip install sentence-transformers")
    except Exception as e:
        log.warning(f"[matcher] Failed to load sentence-transformers: {e}")
        return None


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
    global _embed_fn, _embed_load_attempted
    if _embed_fn is not None:
        return _embed_fn
    if _embed_load_attempted:
        return None  # already tried and failed — don't retry

    _embed_load_attempted = True
    backend = config.EMBEDDING_BACKEND
    try:
        if backend == "openai" and config.OPENAI_API_KEY:
            _embed_fn = _load_openai_embeddings()
        else:
            _embed_fn = _load_sentence_transformers()
    except ImportError:
        log.warning("[matcher] Embedding backend unavailable — using keyword fallback")
        _embed_fn = None
    except Exception as e:
        log.warning(f"[matcher] Embedding backend failed ({type(e).__name__}) — using keyword fallback")
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
    score_components: dict = field(default_factory=dict)


def _entity_overlap_score(headline_entities: set[str], market_question: str) -> float:
    """Score how many headline entities appear in the market question."""
    if not headline_entities:
        return 0.0
    q_lower = market_question.lower()
    hits = sum(1 for e in headline_entities if e.lower() in q_lower)
    return min(1.0, hits / max(1, len(headline_entities)) * 1.5)


def match_news_to_markets(
    headline: str,
    markets: list[Market],
    top_k: int | None = None,
    min_similarity: float | None = None,
) -> list[MarketMatch]:
    k = top_k or config.MATCHER_TOP_K
    threshold = min_similarity if min_similarity is not None else config.MATCHER_MIN_SIMILARITY

    embed = get_embed_fn()

    # Extract entities from headline for overlap scoring
    headline_entities: set[str] = set()
    try:
        from signal.nlp_processor import extract_entities as _nlp_entities
        for e in _nlp_entities(headline):
            headline_entities.add(e.text)
    except Exception:
        pass

    # Extract keywords from headline for overlap scoring
    headline_keywords = set(_extract_keywords(headline))

    # Get semantic matches (always try, even if embedding cache partial)
    semantic_results: list[MarketMatch] = []
    if embed is not None and _cache.all_entries():
        semantic_results = _semantic_match_raw(headline, k * 2, threshold * 0.5)

    # Get keyword matches for all markets
    keyword_results = _keyword_match_raw(headline, markets, k * 2)

    # Merge and rescore with hybrid formula
    all_candidates: dict[str, MarketMatch] = {}
    for m in semantic_results:
        all_candidates[m.market.condition_id] = m
    for m in keyword_results:
        if m.market.condition_id not in all_candidates:
            all_candidates[m.market.condition_id] = m

    # Hybrid rescoring
    for cid, match in all_candidates.items():
        entity_score = _entity_overlap_score(headline_entities, match.market.question)
        kw_score = _keyword_jaccard(headline_keywords, match.market.question)
        sem_score = match.similarity if match.match_method == "semantic" else 0.0
        raw_kw_score = match.similarity if match.match_method == "keyword" else 0.0

        # Base score: best of semantic or keyword, then boost with entity/kw overlap
        base_score = max(sem_score, raw_kw_score)
        entity_bonus = entity_score * 0.25
        kw_bonus = kw_score * 0.15
        hybrid = min(1.0, base_score + entity_bonus + kw_bonus)
        match.similarity = round(hybrid, 4)
        match.score_components = {
            "semantic": round(sem_score, 4),
            "entity_overlap": round(entity_score, 4),
            "keyword_overlap": round(kw_score, 4),
            "raw_keyword": round(raw_kw_score, 4),
            "hybrid": match.similarity,
        }

    ranked = sorted(all_candidates.values(), key=lambda x: x.similarity, reverse=True)
    return [m for m in ranked[:k] if m.similarity >= threshold]


def _semantic_match_raw(
    headline: str,
    top_k: int,
    threshold: float,
) -> list[MarketMatch]:
    """Raw semantic matching without keyword fallback."""
    embed = get_embed_fn()
    entries = _cache.all_entries()
    if not entries or embed is None:
        return []

    try:
        query_vec = embed([headline])[0]
    except Exception:
        return []

    matrix = np.stack([e.vector for e in entries])
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


def _keyword_match_raw(
    headline: str,
    markets: list[Market],
    top_k: int,
) -> list[MarketMatch]:
    """Raw keyword matching, returning low-threshold results for hybrid rescoring."""
    headline_lower = headline.lower()
    headline_words = set(headline_lower.split())
    scored: list[tuple[float, Market]] = []

    for market in markets:
        keywords = _extract_keywords(market.question)
        if not keywords:
            continue
        hits = sum(1 for kw in keywords if kw in headline_lower)
        if hits == 0:
            continue
        union = len(set(keywords) | headline_words)
        score = hits / max(1, union) if union > 0 else 0.0
        score = min(1.0, score + hits * 0.12)
        scored.append((score, market))

    scored.sort(key=lambda x: x[0], reverse=True)
    return [
        MarketMatch(market=m, similarity=s, match_method="keyword")
        for s, m in scored[:top_k] if s > 0
    ]


def _keyword_jaccard(headline_keywords: set[str], market_question: str) -> float:
    """Jaccard similarity between headline keywords and market question keywords."""
    if not headline_keywords:
        return 0.0
    market_kw = set(_extract_keywords(market_question))
    if not market_kw:
        return 0.0
    intersection = len(headline_keywords & market_kw)
    union = len(headline_keywords | market_kw)
    return intersection / union if union > 0 else 0.0


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
        # Score: Jaccard-like — hits / (keywords + unique headline words - hits)
        # This penalises long questions less harshly than hits/len(keywords).
        headline_words = set(headline_lower.split())
        union = len(set(keywords) | headline_words)
        score = hits / max(1, union) if union > 0 else 0.0
        # Boost by raw hit count so 2-keyword hits outrank 1-keyword hits
        score = min(1.0, score + hits * 0.12)
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
