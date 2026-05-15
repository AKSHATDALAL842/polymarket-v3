from __future__ import annotations

import json
import logging
import os
from pathlib import Path
from dotenv import load_dotenv

log = logging.getLogger(__name__)

load_dotenv()

# Must be set BEFORE any library imports tqdm (sentence-transformers,
# transformers, huggingface_hub).  tqdm progress bars crash with
# BrokenPipeError when running inside asyncio task contexts.
os.environ.setdefault("TQDM_DISABLE", "1")
os.environ.setdefault("HF_HUB_DISABLE_PROGRESS_BARS", "1")
os.environ["TOKENIZERS_PARALLELISM"] = "false"

ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY", "")
GROQ_API_KEY = os.getenv("GROQ_API_KEY", "")
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY", "")

IS_ANTHROPIC_CONFIGURED = bool(ANTHROPIC_API_KEY and ANTHROPIC_API_KEY != "sk-ant-...")
IS_GROQ_CONFIGURED = bool(GROQ_API_KEY)

USE_GROQ = IS_GROQ_CONFIGURED

_GROQ_CLASSIFY_MODEL = "llama-3.3-70b-versatile"
_ANTHROPIC_CLASSIFY_MODEL = "claude-haiku-4-5"
_ANTHROPIC_SCORING_MODEL = "claude-sonnet-4-6"

CLASSIFICATION_MODEL = _GROQ_CLASSIFY_MODEL if USE_GROQ else _ANTHROPIC_CLASSIFY_MODEL
SCORING_MODEL       = _GROQ_CLASSIFY_MODEL if USE_GROQ else _ANTHROPIC_SCORING_MODEL

POLYMARKET_API_KEY       = os.getenv("POLYMARKET_API_KEY", "")
POLYMARKET_API_SECRET    = os.getenv("POLYMARKET_API_SECRET", "")
POLYMARKET_API_PASSPHRASE = os.getenv("POLYMARKET_API_PASSPHRASE", "")
POLYMARKET_PRIVATE_KEY   = os.getenv("POLYMARKET_PRIVATE_KEY", "")
POLYMARKET_HOST    = "https://clob.polymarket.com"
POLYMARKET_WS_HOST = "wss://ws-subscriptions-clob.polymarket.com/ws/market"

TWITTER_BEARER_TOKEN = os.getenv("TWITTER_BEARER_TOKEN", "")

TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "")
TELEGRAM_CHANNEL_IDS = [
    c.strip() for c in os.getenv("TELEGRAM_CHANNEL_IDS", "").split(",") if c.strip()
]

KALSHI_EMAIL            = os.getenv("KALSHI_EMAIL", "")
KALSHI_PASSWORD         = os.getenv("KALSHI_PASSWORD", "")
KALSHI_API_KEY_ID       = os.getenv("KALSHI_API_KEY_ID", "")
KALSHI_PRIVATE_KEY_PATH = os.getenv("KALSHI_PRIVATE_KEY_PATH", "")
KALSHI_DEMO  = os.getenv("KALSHI_DEMO", "true").lower() == "true"
KALSHI_HOST  = (
    "https://demo-api.kalshi.co/trade-api/v2"
    if os.getenv("KALSHI_DEMO", "true").lower() == "true"
    else "https://trading-api.kalshi.com/trade-api/v2"
)
KALSHI_ENABLED = bool(KALSHI_EMAIL or KALSHI_API_KEY_ID)

GNEWS_API_KEY = os.getenv("GNEWS_API_KEY", "")
NEWSAPI_KEY   = os.getenv("NEWSAPI_KEY", "")

_RSS_FEEDS_PATH = Path(__file__).parent / "config" / "rss_feeds.json"

def _load_rss_feeds() -> list[str]:
    try:
        if _RSS_FEEDS_PATH.is_file():
            with open(_RSS_FEEDS_PATH) as f:
                data = json.load(f)
            if isinstance(data, list) and all(isinstance(u, str) for u in data):
                return data
    except Exception as e:
        log.warning("[config] Could not load rss_feeds.json: %s — using built-in defaults", e)
    return [
        "https://news.google.com/rss/search?q=AI+artificial+intelligence&hl=en-US&gl=US&ceid=US:en",
        "https://feeds.feedburner.com/TechCrunch",
        "https://feeds.arstechnica.com/arstechnica/technology-lab",
        "https://www.theverge.com/rss/index.xml",
        "https://rss.nytimes.com/services/xml/rss/nyt/Technology.xml",
        "https://cointelegraph.com/rss",
        "https://coindesk.com/arc/outboundfeeds/rss/",
        "https://news.google.com/rss/search?q=bitcoin+crypto&hl=en-US&gl=US&ceid=US:en",
        "https://feeds.reuters.com/reuters/topNews",
        "https://feeds.reuters.com/reuters/businessNews",
        "https://news.google.com/rss/search?q=Federal+Reserve+rate&hl=en-US&gl=US&ceid=US:en",
        "https://news.google.com/rss/search?q=Trump+tariff+election&hl=en-US&gl=US&ceid=US:en",
        "https://news.google.com/rss/search?q=OpenAI+GPT&hl=en-US&gl=US&ceid=US:en",
        "https://news.google.com/rss/search?q=SpaceX+Starship&hl=en-US&gl=US&ceid=US:en",
    ]

RSS_FEEDS = _load_rss_feeds()

MAX_VOLUME_USD             = float(os.getenv("MAX_VOLUME_USD", "500000"))
MIN_VOLUME_USD             = float(os.getenv("MIN_VOLUME_USD", "1000"))
PREFER_SHORT_DURATION_DAYS = int(os.getenv("PREFER_SHORT_DURATION_DAYS", "30"))
NEWS_LOOKBACK_HOURS = 6

MARKET_CATEGORIES = ["ai", "technology", "crypto", "politics", "science", "economics"]

SELECTED_CATEGORIES = [
    c.strip()
    for c in os.getenv("SELECTED_CATEGORIES", "all").split(",")
    if c.strip()
]

TWITTER_KEYWORDS = [
    "OpenAI", "GPT-5", "Anthropic", "Claude", "Google AI", "Gemini",
    "Bitcoin", "Ethereum", "Solana", "crypto",
    "Fed rate", "tariff", "Congress", "White House",
    "SpaceX", "Starship", "NASA",
    "Apple", "NVIDIA", "Microsoft", "Google",
]

CLASSIFICATION_PASSES       = 3
CONSISTENCY_THRESHOLD       = 0.6
NOVELTY_CACHE_TTL_SECONDS   = 3600
NOVELTY_SIMILARITY_THRESHOLD = 0.85

EMBEDDING_BACKEND     = os.getenv("EMBEDDING_BACKEND", "sentence_transformers")
MATCHER_TOP_K         = 5
MATCHER_MIN_SIMILARITY = float(os.getenv("MATCHER_MIN_SIMILARITY", "0.30"))

_EDGE_ALPHA             = 0.40
_EDGE_BETA              = 0.30
_EDGE_GAMMA             = 0.30
_EDGE_HARD_CAP          = 0.12
_EDGE_THRESHOLD_DEFAULT = 0.03
_EDGE_MIN_CONFIDENCE    = 0.55
_EDGE_MIN_NOVELTY       = 0.20
_EDGE_MIN_LIQUIDITY     = 0.20

EDGE_ALPHA           = _EDGE_ALPHA
EDGE_BETA            = _EDGE_BETA
EDGE_GAMMA           = _EDGE_GAMMA
EDGE_THRESHOLD       = float(os.getenv("EDGE_THRESHOLD", str(_EDGE_THRESHOLD_DEFAULT)))
EDGE_MAX_ADJUSTMENT  = float(os.getenv("EDGE_MAX_ADJUSTMENT", str(_EDGE_HARD_CAP)))
MATERIALITY_THRESHOLD = float(os.getenv("MATERIALITY_THRESHOLD", "0.30"))
MIN_CONFIDENCE       = _EDGE_MIN_CONFIDENCE
MIN_NOVELTY          = _EDGE_MIN_NOVELTY
MIN_LIQUIDITY_SCORE  = _EDGE_MIN_LIQUIDITY

DRY_RUN          = os.getenv("DRY_RUN", "true").lower() == "true"
MAX_BET_USD      = float(os.getenv("MAX_BET_USD", "25"))
SIZING_K         = 0.25
BANKROLL_USD     = float(os.getenv("BANKROLL_USD", "1000"))
PAPER_BALANCE    = float(os.getenv("PAPER_BALANCE", "1000000"))

_DAILY_LOSS_LIMIT         = 100
_MAX_POSITIONS            = 5
_MAX_CATEGORY_EXPOSURE    = 60
_CONSECUTIVE_LOSS_TRIGGER = 3
_COOLDOWN_MINUTES_DEFAULT = 30

DAILY_LOSS_LIMIT_USD          = float(os.getenv("DAILY_LOSS_LIMIT_USD", str(_DAILY_LOSS_LIMIT)))
MAX_CONCURRENT_POSITIONS      = int(os.getenv("MAX_CONCURRENT_POSITIONS", str(_MAX_POSITIONS)))
MAX_EXPOSURE_PER_CATEGORY_USD = float(os.getenv("MAX_EXPOSURE_PER_CATEGORY_USD", str(_MAX_CATEGORY_EXPOSURE)))
CONSECUTIVE_LOSS_COOLDOWN     = int(os.getenv("CONSECUTIVE_LOSS_COOLDOWN", str(_CONSECUTIVE_LOSS_TRIGGER)))
COOLDOWN_MINUTES              = int(os.getenv("COOLDOWN_MINUTES", str(_COOLDOWN_MINUTES_DEFAULT)))

_ORDER_TYPE_DEFAULT = "limit"
_SIGNAL_COOLDOWN_SECS = 600
_MAX_SPREAD_PCT       = 0.08
_MAX_SLIPPAGE_PCT     = 0.03
_RETRY_ATTEMPTS       = 3
_RETRY_DELAY_SECS     = 1.0
_LIMIT_OFFSET         = 0.01

ORDER_TYPE                    = os.getenv("ORDER_TYPE", _ORDER_TYPE_DEFAULT)
MARKET_SIGNAL_COOLDOWN_SECONDS = int(os.getenv("MARKET_SIGNAL_COOLDOWN_SECONDS", str(_SIGNAL_COOLDOWN_SECS)))
MAX_SPREAD_FRACTION           = _MAX_SPREAD_PCT
MAX_SLIPPAGE_FRACTION         = _MAX_SLIPPAGE_PCT
ORDER_RETRY_ATTEMPTS          = _RETRY_ATTEMPTS
ORDER_RETRY_DELAY_SECONDS     = _RETRY_DELAY_SECS
LIMIT_ORDER_OFFSET            = _LIMIT_OFFSET

MIN_ORDERBOOK_DEPTH_USD = 200
MOMENTUM_WINDOW_SECONDS = 60
MOMENTUM_THRESHOLD      = 0.05

NLP_ENABLED      = os.getenv("NLP_ENABLED", "true").lower() == "true"
NLP_MIN_IMPACT   = float(os.getenv("NLP_MIN_IMPACT", "0.10"))
NLP_DECAY_LAMBDA = 0.05

SPEED_TARGET_SECONDS = float(os.getenv("SPEED_TARGET_SECONDS", "5"))
LATENCY_WARN_MS      = 3000

HOT_PATH_ENABLED              = os.getenv("HOT_PATH_ENABLED", "true").lower() == "true"
FAST_CLASSIFIER_MIN_CONFIDENCE = float(os.getenv("FAST_CLASSIFIER_MIN_CONFIDENCE", "0.60"))
STALENESS_THRESHOLD           = float(os.getenv("STALENESS_THRESHOLD", "0.50"))
HOT_PATH_CONSISTENCY          = float(os.getenv("HOT_PATH_CONSISTENCY", "0.70"))

# Ensemble strategy weights (overridable at runtime)
NEWS_WEIGHT      = float(os.getenv("NEWS_WEIGHT", "0.60"))
MOMENTUM_WEIGHT  = float(os.getenv("MOMENTUM_WEIGHT", "0.40"))

API_SECRET_KEY = os.getenv("API_SECRET_KEY", "")
API_AUTH_ENABLED = bool(API_SECRET_KEY)


def validate_config() -> list[str]:
    warnings: list[str] = []

    if not IS_GROQ_CONFIGURED and not IS_ANTHROPIC_CONFIGURED:
        warnings.append(
            "No LLM backend configured. Set GROQ_API_KEY or ANTHROPIC_API_KEY "
            "in .env — the pipeline cannot classify without one."
        )
    elif USE_GROQ and not IS_GROQ_CONFIGURED:
        warnings.append("USE_GROQ is True but GROQ_API_KEY is empty or missing.")
    elif not USE_GROQ and not IS_ANTHROPIC_CONFIGURED:
        warnings.append(
            "Groq not configured; falling back to Anthropic, but "
            "ANTHROPIC_API_KEY is empty or still the placeholder value."
        )

    has_poly_keys = all([POLYMARKET_API_KEY, POLYMARKET_API_SECRET,
                         POLYMARKET_API_PASSPHRASE, POLYMARKET_PRIVATE_KEY])
    if has_poly_keys and DRY_RUN:
        warnings.append(
            "Polymarket trading keys are configured but DRY_RUN=true. "
            "Set DRY_RUN=false in .env to trade live (or POST /trading/mode)."
        )

    if KALSHI_ENABLED:
        if KALSHI_API_KEY_ID and not KALSHI_PRIVATE_KEY_PATH:
            warnings.append("KALSHI_API_KEY_ID is set but KALSHI_PRIVATE_KEY_PATH is empty.")
        if not KALSHI_API_KEY_ID and not (KALSHI_EMAIL and KALSHI_PASSWORD):
            warnings.append("KALSHI_ENABLED is True but no auth method is fully configured.")

    if PAPER_BALANCE < BANKROLL_USD:
        warnings.append(
            f"PAPER_BALANCE (${PAPER_BALANCE:,.0f}) is smaller than "
            f"BANKROLL_USD (${BANKROLL_USD:,.0f}). BANKROLL_USD drives Kelly sizing; "
            f"this may be intentional for small-scale testing but will constrain bets."
        )

    if not (0.0 < EDGE_THRESHOLD <= 0.50):
        warnings.append(f"EDGE_THRESHOLD={EDGE_THRESHOLD} is outside sensible range (0, 0.50].")
    if not (1 <= MAX_CONCURRENT_POSITIONS <= 50):
        warnings.append(f"MAX_CONCURRENT_POSITIONS={MAX_CONCURRENT_POSITIONS} is outside sensible range [1, 50].")
    if not (0.01 <= MAX_BET_USD <= 10_000):
        warnings.append(f"MAX_BET_USD=${MAX_BET_USD} is outside sensible range [$0.01, $10,000].")
    if MAX_SPREAD_FRACTION >= 1.0:
        warnings.append(f"MAX_SPREAD_FRACTION={MAX_SPREAD_FRACTION} >= 1.0 will never reject on spread.")
    if MARKET_SIGNAL_COOLDOWN_SECONDS < 10:
        warnings.append(
            f"MARKET_SIGNAL_COOLDOWN_SECONDS={MARKET_SIGNAL_COOLDOWN_SECONDS}s is very low."
        )
    if COOLDOWN_MINUTES < 1:
        warnings.append(f"COOLDOWN_MINUTES={COOLDOWN_MINUTES} is too short to be meaningful.")

    if not API_SECRET_KEY:
        warnings.append(
            "API_SECRET_KEY is not set — the API server will run without authentication. "
            "Anyone who can reach the server can view trades, portfolio state, and toggle live trading."
        )

    return warnings


# ═══════════════════════════════════════════════════════════════════
# Runtime config overrides — allows the dashboard to change settings
# on a live pipeline without restarting.
# ═══════════════════════════════════════════════════════════════════

import sys as _sys

_original_values: dict[str, object] = {}
_override_values: dict[str, object] = {}

_MODULE = _sys.modules[__name__]

# Keys the frontend is allowed to change via the API
_ALLOWED_OVERRIDE_KEYS = {
    "SIZING_K",
    "MAX_CONCURRENT_POSITIONS",
    "DAILY_LOSS_LIMIT_USD",
    "MIN_CONFIDENCE",
    "MATERIALITY_THRESHOLD",
    "EDGE_THRESHOLD",
    "MAX_BET_USD",
    "COOLDOWN_MINUTES",
    "MAX_SPREAD_FRACTION",
    "MAX_SLIPPAGE_FRACTION",
    "MIN_LIQUIDITY_SCORE",
    "NLP_ENABLED",
    "NLP_MIN_IMPACT",
    "HOT_PATH_ENABLED",
    "FAST_CLASSIFIER_MIN_CONFIDENCE",
    "NEWS_WEIGHT",
    "MOMENTUM_WEIGHT",
}


def override(key: str, value: object) -> bool:
    """Override a config value at runtime.  Only allowed keys are accepted.
    Returns True on success, False if the key is not allowed."""
    if key not in _ALLOWED_OVERRIDE_KEYS:
        log.warning("[config] Refusing to override non-whitelisted key %r", key)
        return False

    if key not in _original_values:
        _original_values[key] = getattr(_MODULE, key, None)

    coerced = _coerce(key, value)
    _override_values[key] = coerced
    setattr(_MODULE, key, coerced)
    log.info("[config] Runtime override: %s = %s", key, coerced)
    return True


def restore(key: str | None = None) -> None:
    """Restore original value(s).  Pass None to restore everything."""
    if key:
        if key in _original_values:
            setattr(_MODULE, key, _original_values[key])
            _original_values.pop(key, None)
            _override_values.pop(key, None)
            log.info("[config] Restored default for %s", key)
    else:
        for k, v in list(_original_values.items()):
            setattr(_MODULE, k, v)
        _original_values.clear()
        _override_values.clear()
        log.info("[config] All runtime overrides restored to defaults")


def get_overrides() -> dict[str, object]:
    """Return a snapshot of current override values."""
    return dict(_override_values)


def get_effective_config() -> dict[str, object]:
    """Return the effective (currently live) values for all allowed keys."""
    return {k: getattr(_MODULE, k, None) for k in _ALLOWED_OVERRIDE_KEYS}


def _coerce(key: str, value: object) -> object:
    """Coerce the incoming value to the same type as the current config attribute."""
    current = getattr(_MODULE, key, None)
    if current is None:
        return value
    if isinstance(current, bool):
        if isinstance(value, bool):
            return value
        if isinstance(value, str):
            return value.lower() in ("true", "1", "yes", "on")
        return bool(value)
    if isinstance(current, int):
        return int(float(value))
    if isinstance(current, float):
        return float(value)
    return value


_warnings = validate_config()
for _w in _warnings:
    log.warning("[config] %s", _w)
