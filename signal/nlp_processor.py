from __future__ import annotations

import math
import logging
from dataclasses import dataclass, field

log = logging.getLogger(__name__)

_nlp = None
_vader = None


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

_LABEL_IMPORTANCE: dict[str, float] = {
    "LAW": 0.90, "EVENT": 0.85, "ORG": 0.80, "MONEY": 0.80,
    "PERSON": 0.75, "GPE": 0.70, "PERCENT": 0.70,
    "NORP": 0.65, "PRODUCT": 0.60, "FAC": 0.50, "LOC": 0.50,
    "WORK_OF_ART": 0.40,
}

SOURCE_RELIABILITY: dict[str, float] = {
    "gnews":    0.88,
    "gdelt":    0.85,
    "newsapi":  0.85,
    "rss":      0.80,
    "twitter":  0.65,
    "telegram": 0.60,
    "reddit":   0.50,
}

_DECAY_LAMBDA = 0.05  # per minute; half-life ≈ 13.9 minutes

# Custom entity patterns — spaCy en_core_web_sm misses many domain-specific terms.
# (pattern_regex, label, importance)
_CUSTOM_ENTITIES: list[tuple[str, str, float]] = [
    # AI companies & products
    (r"\bOpenAI\b", "ORG", 0.95),
    (r"\bAnthropic\b", "ORG", 0.90),
    (r"\bGPT-[345]\b", "PRODUCT", 0.88),
    (r"\bChatGPT\b", "PRODUCT", 0.88),
    (r"\bClaude\b", "PRODUCT", 0.85),
    (r"\bGemini\b", "PRODUCT", 0.85),
    (r"\bLLaMA\b", "PRODUCT", 0.82),
    (r"\bMistral\b", "ORG", 0.82),
    (r"\bDeepMind\b", "ORG", 0.88),
    (r"\bMidjourney\b", "ORG", 0.80),
    (r"\bStable Diffusion\b", "PRODUCT", 0.80),
    # Crypto assets
    (r"\bBitcoin\b", "MONEY", 0.90),
    (r"\bBTC\b", "MONEY", 0.85),
    (r"\bEthereum\b", "MONEY", 0.90),
    (r"\bETH\b", "MONEY", 0.85),
    (r"\bSolana\b", "MONEY", 0.85),
    (r"\bSOL\b", "MONEY", 0.80),
    (r"\bXRP\b", "MONEY", 0.80),
    (r"\bDogecoin\b", "MONEY", 0.75),
    (r"\bUSDT\b", "MONEY", 0.80),
    (r"\bUSDC\b", "MONEY", 0.80),
    # Exchanges
    (r"\bCoinbase\b", "ORG", 0.88),
    (r"\bBinance\b", "ORG", 0.88),
    (r"\bKraken\b", "ORG", 0.82),
    (r"\bFTX\b", "ORG", 0.85),
    # ETFs & finance
    (r"\bETF\b", "PRODUCT", 0.85),
    (r"\bSEC\b", "ORG", 0.90),
    (r"\bCFTC\b", "ORG", 0.85),
    (r"\bFDIC\b", "ORG", 0.85),
    # Geopolitical
    (r"\bNATO\b", "ORG", 0.90),
    (r"\bOPEC\b", "ORG", 0.90),
    (r"\bG7\b", "ORG", 0.88),
    (r"\bG20\b", "ORG", 0.88),
    (r"\bBRICS\b", "ORG", 0.88),
    # Central banks
    (r"\bFederal Reserve\b", "ORG", 0.95),
    (r"\bFed\b", "ORG", 0.85),
    (r"\bECB\b", "ORG", 0.90),
    (r"\bBank of England\b", "ORG", 0.90),
    (r"\bBank of Japan\b", "ORG", 0.90),
    (r"\bBOJ\b", "ORG", 0.85),
    (r"\bPBOC\b", "ORG", 0.85),
    # Tech companies
    (r"\bNVIDIA\b", "ORG", 0.92),
    (r"\bAMD\b", "ORG", 0.88),
    (r"\bIntel\b", "ORG", 0.88),
    (r"\bTesla\b", "ORG", 0.90),
    (r"\bSpaceX\b", "ORG", 0.90),
    (r"\bMeta\b", "ORG", 0.88),
    (r"\bApple\b", "ORG", 0.90),
    (r"\bMicrosoft\b", "ORG", 0.90),
    (r"\bAlphabet\b", "ORG", 0.88),
    # Pharma
    (r"\bPfizer\b", "ORG", 0.90),
    (r"\bModerna\b", "ORG", 0.88),
    (r"\bFDA\b", "ORG", 0.90),
    # Indicators
    (r"\bCPI\b", "EVENT", 0.90),
    (r"\bPCE\b", "EVENT", 0.85),
    (r"\bGDP\b", "EVENT", 0.90),
    (r"\bPMI\b", "EVENT", 0.85),
    (r"\bFOMC\b", "EVENT", 0.90),
]

# Normalization aliases (lowercase)
_ENTITY_ALIASES: dict[str, str] = {
    "btc": "Bitcoin",
    "eth": "Ethereum",
    "sol": "Solana",
    "fed": "Federal Reserve",
    "powell": "Jerome Powell",
    "putin": "Vladimir Putin",
    "xi": "Xi Jinping",
    "zelenskyy": "Volodymyr Zelenskyy",
    "musk": "Elon Musk",
    "altman": "Sam Altman",
    "nvidia": "NVIDIA",
    "apple": "Apple Inc.",
    "microsoft": "Microsoft",
    "tesla": "Tesla",
    "spacex": "SpaceX",
}



@dataclass
class Entity:
    text: str
    label: str
    importance: float


@dataclass
class NLPResult:
    entities: list[Entity] = field(default_factory=list)
    category: str = "other"
    sentiment_polarity: float = 0.0
    sentiment_confidence: float = 0.0
    entity_importance: float = 0.0
    impact_score: float = 0.0
    relevance: float = 0.0
    velocity_score: float = 0.0


def extract_entities(text: str) -> list[Entity]:
    """Extract entities using spaCy NER + custom regex patterns."""
    import re
    seen: set[tuple[str, str]] = set()
    entities: list[Entity] = []

    # 1. Custom regex patterns (highest priority — catches terms spaCy misses)
    for pattern, label, importance in _CUSTOM_ENTITIES:
        for match in re.finditer(pattern, text, re.IGNORECASE):
            entity_text = match.group(0)
            key = (entity_text.lower(), label)
            if key not in seen:
                seen.add(key)
                # Use alias if available
                display = _ENTITY_ALIASES.get(entity_text.lower(), entity_text)
                entities.append(Entity(text=display, label=label, importance=importance))

    # 2. spaCy NER (augments with standard entity types)
    nlp = _get_nlp()
    if nlp:
        doc = nlp(text)
        for ent in doc.ents:
            key = (ent.text.lower(), ent.label_)
            if key in seen:
                continue
            seen.add(key)
            importance = _LABEL_IMPORTANCE.get(ent.label_, 0.30)
            entities.append(Entity(text=ent.text, label=ent.label_, importance=importance))

    return entities


def analyze_sentiment(text: str) -> tuple[float, float]:
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
    # Impact = w1*reliability + w2*|sentiment|*conf + w3*entity + w4*novelty + w5*velocity
    # Novelty upweighted because already-priced-in news has near-zero alpha
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
    age_minutes = age_seconds / 60.0
    return impact * math.exp(-_DECAY_LAMBDA * age_minutes)


def process(
    headline: str,
    source: str,
    age_seconds: float,
    novelty_score: float = 0.5,
    velocity_score: float = 0.0,
) -> NLPResult:
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
