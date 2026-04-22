from __future__ import annotations

import os
from dotenv import load_dotenv

load_dotenv()

ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY", "")

GROQ_API_KEY = os.getenv("GROQ_API_KEY", "")
GROQ_BASE_URL = "https://api.groq.com/openai/v1"
USE_GROQ = bool(GROQ_API_KEY)

CLASSIFICATION_MODEL = "llama-3.3-70b-versatile" if USE_GROQ else "claude-haiku-4-5-20251001"
SCORING_MODEL       = "llama-3.3-70b-versatile" if USE_GROQ else "claude-sonnet-4-6-20250514"

POLYMARKET_API_KEY = os.getenv("POLYMARKET_API_KEY", "")
POLYMARKET_API_SECRET = os.getenv("POLYMARKET_API_SECRET", "")
POLYMARKET_API_PASSPHRASE = os.getenv("POLYMARKET_API_PASSPHRASE", "")
POLYMARKET_PRIVATE_KEY = os.getenv("POLYMARKET_PRIVATE_KEY", "")
POLYMARKET_HOST = "https://clob.polymarket.com"
POLYMARKET_WS_HOST = "wss://ws-subscriptions-clob.polymarket.com/ws/market"

TWITTER_BEARER_TOKEN = os.getenv("TWITTER_BEARER_TOKEN", "")

TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "")
TELEGRAM_CHANNEL_IDS = [
    c.strip() for c in os.getenv("TELEGRAM_CHANNEL_IDS", "").split(",") if c.strip()
]

KALSHI_EMAIL    = os.getenv("KALSHI_EMAIL", "")
KALSHI_PASSWORD = os.getenv("KALSHI_PASSWORD", "")
KALSHI_API_KEY_ID       = os.getenv("KALSHI_API_KEY_ID", "")
KALSHI_PRIVATE_KEY_PATH = os.getenv("KALSHI_PRIVATE_KEY_PATH", "")
KALSHI_DEMO = os.getenv("KALSHI_DEMO", "true").lower() == "true"
KALSHI_HOST = (
    "https://demo-api.kalshi.co/trade-api/v2"
    if os.getenv("KALSHI_DEMO", "true").lower() == "true"
    else "https://trading-api.kalshi.com/trade-api/v2"
)
KALSHI_ENABLED = bool(KALSHI_EMAIL or KALSHI_API_KEY_ID)

GNEWS_API_KEY = os.getenv("GNEWS_API_KEY", "")

NEWSAPI_KEY = os.getenv("NEWSAPI_KEY", "")
RSS_FEEDS = [
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

MAX_VOLUME_USD = float(os.getenv("MAX_VOLUME_USD", "500000"))
MIN_VOLUME_USD = float(os.getenv("MIN_VOLUME_USD", "1000"))
MARKET_CATEGORIES = ["ai", "technology", "crypto", "politics", "science"]
PREFER_SHORT_DURATION_DAYS = int(os.getenv("PREFER_SHORT_DURATION_DAYS", "30"))
NEWS_LOOKBACK_HOURS = 6
TWITTER_KEYWORDS = [
    "OpenAI", "GPT-5", "Anthropic", "Claude", "Google AI", "Gemini",
    "Bitcoin", "Ethereum", "Solana", "crypto",
    "Fed rate", "tariff", "Congress", "White House",
    "SpaceX", "Starship", "NASA",
    "Apple", "NVIDIA", "Microsoft", "Google",
]

CLASSIFICATION_PASSES = 3
CONSISTENCY_THRESHOLD = 0.6
NOVELTY_CACHE_TTL_SECONDS = 3600
NOVELTY_SIMILARITY_THRESHOLD = 0.85

EMBEDDING_BACKEND = os.getenv("EMBEDDING_BACKEND", "sentence_transformers")
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY", "")
MATCHER_TOP_K = 5
MATCHER_MIN_SIMILARITY = 0.30

EDGE_ALPHA = 0.40
EDGE_BETA = 0.30
EDGE_GAMMA = 0.30
EDGE_THRESHOLD = float(os.getenv("EDGE_THRESHOLD", "0.03"))
EDGE_MAX_ADJUSTMENT = float(os.getenv("EDGE_MAX_ADJUSTMENT", "0.12"))
MATERIALITY_THRESHOLD = float(os.getenv("MATERIALITY_THRESHOLD", "0.30"))
MIN_CONFIDENCE = 0.55
MIN_NOVELTY = 0.20
MIN_LIQUIDITY_SCORE = 0.20

DRY_RUN = os.getenv("DRY_RUN", "true").lower() == "true"
MAX_BET_USD = float(os.getenv("MAX_BET_USD", "25"))
SIZING_K = 0.25
BANKROLL_USD = float(os.getenv("BANKROLL_USD", "1000"))

DAILY_LOSS_LIMIT_USD = float(os.getenv("DAILY_LOSS_LIMIT_USD", "100"))
MAX_CONCURRENT_POSITIONS = int(os.getenv("MAX_CONCURRENT_POSITIONS", "5"))
MAX_EXPOSURE_PER_CATEGORY_USD = float(os.getenv("MAX_EXPOSURE_PER_CATEGORY_USD", "60"))
CONSECUTIVE_LOSS_COOLDOWN = int(os.getenv("CONSECUTIVE_LOSS_COOLDOWN", "3"))
COOLDOWN_MINUTES = int(os.getenv("COOLDOWN_MINUTES", "30"))

ORDER_TYPE = os.getenv("ORDER_TYPE", "limit")
MARKET_SIGNAL_COOLDOWN_SECONDS = int(os.getenv("MARKET_SIGNAL_COOLDOWN_SECONDS", "600"))
MAX_SPREAD_FRACTION = 0.08
MAX_SLIPPAGE_FRACTION = 0.03
ORDER_RETRY_ATTEMPTS = 3
ORDER_RETRY_DELAY_SECONDS = 1.0
LIMIT_ORDER_OFFSET = 0.01

MIN_ORDERBOOK_DEPTH_USD = 200
MOMENTUM_WINDOW_SECONDS = 60
MOMENTUM_THRESHOLD = 0.05

NLP_ENABLED = os.getenv("NLP_ENABLED", "true").lower() == "true"
NLP_MIN_IMPACT = float(os.getenv("NLP_MIN_IMPACT", "0.10"))
NLP_DECAY_LAMBDA = 0.05

SPEED_TARGET_SECONDS = float(os.getenv("SPEED_TARGET_SECONDS", "5"))
LATENCY_WARN_MS = 3000

SELECTED_CATEGORIES = [
    c.strip()
    for c in os.getenv("SELECTED_CATEGORIES", "all").split(",")
    if c.strip()
]

PAPER_BALANCE = float(os.getenv("PAPER_BALANCE", "1000000"))
