"""
NLP Intelligence Layer — NER, sentiment analysis, impact scoring, temporal decay.

Components
----------
NER          : spaCy en_core_web_sm extracts persons, orgs, geopolitical entities.
Sentiment    : VADER (fast, no GPU) — compound score → polarity + confidence.
Impact Score : Weighted composite:
                 Impact = w_rel*reliability + w_sent*|polarity|*conf
                        + w_ent*entity_importance + w_nov*novelty + w_vel*velocity
Temporal Decay: relevance(t) = impact * exp(−λ * age_minutes), λ=0.05 → half-life ≈14 min.
Category     : Rules-based keyword tagger (politics, macro, tech, conflict, crypto).

All backends degrade gracefully: if spaCy or VADER are not installed the module
still returns a valid NLPResult with zeroed-out fields.
"""
from __future__ import annotations

import math
import logging
from dataclasses import dataclass, field

log = logging.getLogger(__name__)

# ── Lazy-loaded backends ──────────────────────────────────────────────────────

_nlp = None      # spaCy pipeline
_vader = None    # VADER SentimentIntensityAnalyzer


def _get_nlp():
    global _nlp
    if _nlp is not None:
        return _nlp
    try:
        import spacy
        _nlp = spacy.load("en_core_web_sm")
        log.info("[nlp] spaCy en_core_web_sm loaded")
    except Exception as e:
        log.warning(f"[nlp] spaCy unavailable ({e}) — NER disabled. "
                    "Install: pip install spacy && python -m spacy download en_core_web_sm")
        _nlp = False
    return _nlp


def _get_vader():
    global _vader
    if _vader is not None:
        return _vader
    try:
        from vaderSentiment.vaderSentiment import SentimentIntensityAnalyzer
        _vader = SentimentIntensityAnalyzer()
        log.info("[nlp] VADER sentiment loaded")
    except ImportError:
        log.warning("[nlp] vaderSentiment not installed — sentiment disabled. "
                    "Install: pip install vaderSentiment")
        _vader = False
    return _vader


# ── Category keywords ─────────────────────────────────────────────────────────

_CATEGORY_KEYWORDS: dict[str, set[str]] = {
    "politics": {
        "congress", "senate", "president", "election", "vote",
        "trump", "white house", "democrat", "republican",
        "parliament", "minister", "legislation", "bill",
    },
    "macro": {
        "fed", "federal reserve", "rate hike", "rate cut", "inflation",
        "gdp", "recession", "tariff", "trade war", "unemployment",
        "cpi", "pce", "interest rate", "treasury", "fiscal",
    },
    "tech": {
        "openai", "anthropic", "google", "microsoft", "apple", "nvidia",
        "ai", "gpt", "llm", "chip", "semiconductor", "quantum",
        "spacex", "starship", "nasa", "launch",
    },
    "conflict": {
        "war", "attack", "military", "missile", "sanction", "nato",
        "invasion", "airstrike", "troops", "ceasefire", "nuclear",
    },
    "crypto": {
        "bitcoin", "ethereum", "crypto", "btc", "eth", "solana",
        "defi", "nft", "blockchain", "sec crypto", "etf",
    },
}

# ── Entity label importance weights ──────────────────────────────────────────

_LABEL_IMPORTANCE: dict[str, float] = {
    "LAW": 0.90, "EVENT": 0.85, "ORG": 0.80, "MONEY": 0.80,
    "PERSON": 0.75, "GPE": 0.70, "PERCENT": 0.70,
    "NORP": 0.65, "PRODUCT": 0.60, "FAC": 0.50, "LOC": 0.50,
    "WORK_OF_ART": 0.40,
}

# ── Source reliability priors ─────────────────────────────────────────────────

SOURCE_RELIABILITY: dict[str, float] = {
    "gnews":    0.88,
    "gdelt":    0.85,
    "newsapi":  0.85,
    "rss":      0.80,
    "twitter":  0.65,
    "telegram": 0.60,
    "reddit":   0.50,
}

# Temporal decay constant — relevance halves every ≈14 minutes
_DECAY_LAMBDA = 0.05  # per minute


# ── Data classes ──────────────────────────────────────────────────────────────

@dataclass
class Entity:
    text: str
    label: str          # PERSON, ORG, GPE, LAW, EVENT, PRODUCT, MONEY…
    importance: float   # 0–1 derived from label priority


@dataclass
class NLPResult:
    entities: list[Entity] = field(default_factory=list)
    category: str = "other"
    sentiment_polarity: float = 0.0     # −1 (negative) → +1 (positive)
    sentiment_confidence: float = 0.0   # 0–1 (|compound| as proxy)
    entity_importance: float = 0.0      # max importance across extracted entities
    impact_score: float = 0.0           # composite 0–1
    relevance: float = 0.0              # impact after temporal decay
    velocity_score: float = 0.0         # set externally by velocity tracker


# ── Core functions ────────────────────────────────────────────────────────────

def extract_entities(text: str) -> list[Entity]:
    nlp = _get_nlp()
    if not nlp:
        return []
    doc = nlp(text)
    seen: set[tuple[str, str]] = set()
    entities: list[Entity] = []
    for ent in doc.ents:
        key = (ent.text.lower(), ent.label_)
        if key in seen:
            continue
        seen.add(key)
        importance = _LABEL_IMPORTANCE.get(ent.label_, 0.30)
        entities.append(Entity(text=ent.text, label=ent.label_, importance=importance))
    return entities


def analyze_sentiment(text: str) -> tuple[float, float]:
    """
    Returns (polarity, confidence).
    polarity : −1.0 (very negative) → +1.0 (very positive)
    confidence: |compound| — how far from neutral (0 = neutral)
    """
    vader = _get_vader()
    if not vader:
        return 0.0, 0.0
    scores = vader.polarity_scores(text)
    compound = scores["compound"]
    return compound, abs(compound)


def classify_category(text: str, entities: list[Entity]) -> str:
    lower = text.lower()
    entity_texts = {e.text.lower() for e in entities}
    best_cat, best_score = "other", 0
    for cat, keywords in _CATEGORY_KEYWORDS.items():
        score = sum(
            1 for kw in keywords
            if kw in lower or any(kw in et for et in entity_texts)
        )
        if score > best_score:
            best_score, best_cat = score, cat
    return best_cat


def compute_impact_score(
    source: str,
    sentiment_polarity: float,
    sentiment_confidence: float,
    entity_importance: float,
    novelty_score: float,
    velocity_score: float = 0.0,
) -> float:
    """
    Mathematical impact model:
        Impact = w1*source_reliability
               + w2*|sentiment|*sentiment_confidence
               + w3*entity_importance
               + w4*novelty_score
               + w5*velocity_score

    Weights: (0.20, 0.20, 0.20, 0.25, 0.15) — sum = 1.0
    Novelty is upweighted because already-priced-in news has near-zero alpha.
    """
    w = (0.20, 0.20, 0.20, 0.25, 0.15)
    reliability = SOURCE_RELIABILITY.get(source, 0.60)
    sentiment_signal = abs(sentiment_polarity) * sentiment_confidence

    score = (
        w[0] * reliability
        + w[1] * sentiment_signal
        + w[2] * entity_importance
        + w[3] * novelty_score
        + w[4] * velocity_score
    )
    return min(1.0, max(0.0, score))


def apply_temporal_decay(impact: float, age_seconds: float) -> float:
    """
    Exponential decay: relevance(t) = impact * exp(−λ * age_minutes)
    λ = 0.05 → half-life ≈ 13.9 minutes.
    """
    age_minutes = age_seconds / 60.0
    return impact * math.exp(-_DECAY_LAMBDA * age_minutes)


def process(
    headline: str,
    source: str,
    age_seconds: float,
    novelty_score: float = 0.5,
    velocity_score: float = 0.0,
) -> NLPResult:
    """
    Full enrichment pipeline for a single headline.
    Safe to call from async context (pure CPU, no I/O).
    """
    entities = extract_entities(headline)
    category = classify_category(headline, entities)
    polarity, sent_conf = analyze_sentiment(headline)
    entity_importance = max((e.importance for e in entities), default=0.30)
    impact = compute_impact_score(
        source, polarity, sent_conf, entity_importance, novelty_score, velocity_score
    )
    relevance = apply_temporal_decay(impact, age_seconds)

    return NLPResult(
        entities=entities,
        category=category,
        sentiment_polarity=polarity,
        sentiment_confidence=sent_conf,
        entity_importance=entity_importance,
        impact_score=impact,
        relevance=relevance,
        velocity_score=velocity_score,
    )
