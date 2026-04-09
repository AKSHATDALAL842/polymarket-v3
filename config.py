"""
Configuration — all settings, API keys, thresholds.
Upgraded for V3: edge model params, risk controls, execution config.
"""
from __future__ import annotations

import os
from dotenv import load_dotenv

load_dotenv()

# ── Anthropic (optional — fallback if Groq not configured) ────────────────────
ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY", "")

# ── Groq (free tier — primary LLM backend) ─────────────────────────────────────
GROQ_API_KEY = os.getenv("GROQ_API_KEY", "")
GROQ_BASE_URL = "https://api.groq.com/openai/v1"

# Use Groq if key is present, otherwise fall back to Anthropic
USE_GROQ = bool(GROQ_API_KEY)

CLASSIFICATION_MODEL = "llama-3.3-70b-versatile" if USE_GROQ else "claude-haiku-4-5-20251001"
SCORING_MODEL       = "llama-3.3-70b-versatile" if USE_GROQ else "claude-sonnet-4-6-20250514"

# ── Polymarket CLOB ────────────────────────────────────────────────────────────
POLYMARKET_API_KEY = os.getenv("POLYMARKET_API_KEY", "")
POLYMARKET_API_SECRET = os.getenv("POLYMARKET_API_SECRET", "")
POLYMARKET_API_PASSPHRASE = os.getenv("POLYMARKET_API_PASSPHRASE", "")
POLYMARKET_PRIVATE_KEY = os.getenv("POLYMARKET_PRIVATE_KEY", "")
POLYMARKET_HOST = "https://clob.polymarket.com"
POLYMARKET_WS_HOST = "wss://ws-subscriptions-clob.polymarket.com/ws/market"

# ── Twitter API v2 ─────────────────────────────────────────────────────────────
TWITTER_BEARER_TOKEN = os.getenv("TWITTER_BEARER_TOKEN", "")

# ── Telegram ───────────────────────────────────────────────────────────────────
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "")
TELEGRAM_CHANNEL_IDS = [
    c.strip() for c in os.getenv("TELEGRAM_CHANNEL_IDS", "").split(",") if c.strip()
]

# ── NewsAPI / RSS fallback ─────────────────────────────────────────────────────
NEWSAPI_KEY = os.getenv("NEWSAPI_KEY", "")
RSS_FEEDS = [
    "https://news.google.com/rss/search?q=AI+artificial+intelligence&hl=en-US&gl=US&ceid=US:en",
    "https://feeds.feedburner.com/TechCrunch",
    "https://feeds.arstechnica.com/arstechnica/technology-lab",
    "https://www.theverge.com/rss/index.xml",
    "https://rss.nytimes.com/services/xml/rss/nyt/Technology.xml",
]

# ── Market Filters ─────────────────────────────────────────────────────────────
MAX_VOLUME_USD = float(os.getenv("MAX_VOLUME_USD", "500000"))
MIN_VOLUME_USD = float(os.getenv("MIN_VOLUME_USD", "1000"))
MARKET_CATEGORIES = ["ai", "technology", "crypto", "politics", "science"]
NEWS_LOOKBACK_HOURS = 6
TWITTER_KEYWORDS = [
    "OpenAI", "GPT-5", "Anthropic", "Claude", "Google AI", "Gemini",
    "Bitcoin", "Ethereum", "Solana", "crypto",
    "Fed rate", "tariff", "Congress", "White House",
    "SpaceX", "Starship", "NASA",
    "Apple", "NVIDIA", "Microsoft", "Google",
]

# ── Classification (V3) ────────────────────────────────────────────────────────
CLASSIFICATION_PASSES = 3            # number of LLM voting rounds
CONSISTENCY_THRESHOLD = 0.6          # min fraction of agreeing votes
NOVELTY_CACHE_TTL_SECONDS = 3600     # how long to remember recent headlines
NOVELTY_SIMILARITY_THRESHOLD = 0.85  # cosine similarity → "already priced in"

# ── Semantic Matching (V3) ─────────────────────────────────────────────────────
EMBEDDING_BACKEND = os.getenv("EMBEDDING_BACKEND", "sentence_transformers")
# Options: "sentence_transformers" (local, fast) or "openai" (requires OPENAI_API_KEY)
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY", "")
MATCHER_TOP_K = 5
MATCHER_MIN_SIMILARITY = 0.30        # cosine similarity floor

# ── Edge Model (V3) ────────────────────────────────────────────────────────────
# p_true = p_market ± adjustment where adjustment = f(direction, materiality, novelty, confidence)
EDGE_ALPHA = 0.40          # weight on materiality in price adjustment
EDGE_BETA = 0.30           # weight on confidence
EDGE_GAMMA = 0.30          # weight on novelty
EDGE_THRESHOLD = float(os.getenv("EDGE_THRESHOLD", "0.06"))   # min |EV| to trade
MATERIALITY_THRESHOLD = float(os.getenv("MATERIALITY_THRESHOLD", "0.55"))
MIN_CONFIDENCE = 0.60       # min LLM confidence to proceed
MIN_NOVELTY = 0.40          # skip if likely already priced in

# ── Position Sizing (V3 — capped fractional) ───────────────────────────────────
DRY_RUN = os.getenv("DRY_RUN", "true").lower() == "true"
MAX_BET_USD = float(os.getenv("MAX_BET_USD", "25"))
SIZING_K = 0.25             # fractional risk factor
# size = min(MAX_BET_USD, SIZING_K * |EV| * confidence * bankroll)
BANKROLL_USD = float(os.getenv("BANKROLL_USD", "1000"))

# ── Risk Management (V3) ───────────────────────────────────────────────────────
DAILY_LOSS_LIMIT_USD = float(os.getenv("DAILY_LOSS_LIMIT_USD", "100"))
MAX_CONCURRENT_POSITIONS = int(os.getenv("MAX_CONCURRENT_POSITIONS", "5"))
MAX_EXPOSURE_PER_CATEGORY_USD = float(os.getenv("MAX_EXPOSURE_PER_CATEGORY_USD", "60"))
CONSECUTIVE_LOSS_COOLDOWN = int(os.getenv("CONSECUTIVE_LOSS_COOLDOWN", "3"))  # N losses → pause
COOLDOWN_MINUTES = int(os.getenv("COOLDOWN_MINUTES", "30"))

# ── Execution (V3) ─────────────────────────────────────────────────────────────
ORDER_TYPE = os.getenv("ORDER_TYPE", "limit")      # "limit" or "market"
MAX_SPREAD_FRACTION = 0.08                          # skip if spread > 8% of mid
MAX_SLIPPAGE_FRACTION = 0.03                        # reject if estimated slippage > 3%
ORDER_RETRY_ATTEMPTS = 3
ORDER_RETRY_DELAY_SECONDS = 1.0
LIMIT_ORDER_OFFSET = 0.01   # place limit ORDER_OFFSET inside spread

# ── Microstructure ─────────────────────────────────────────────────────────────
MIN_ORDERBOOK_DEPTH_USD = 200        # skip if < $200 on best 3 levels
MOMENTUM_WINDOW_SECONDS = 60         # lookback for momentum calc
MOMENTUM_THRESHOLD = 0.05            # skip if |price move| > 5% in window (already moving)

# ── Performance Targets ────────────────────────────────────────────────────────
SPEED_TARGET_SECONDS = float(os.getenv("SPEED_TARGET_SECONDS", "5"))
LATENCY_WARN_MS = 3000
