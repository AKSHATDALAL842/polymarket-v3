"""
Category registry — keyword maps, RSS feeds, newsapi queries, reddit subs,
and twitter keywords per category.

No side effects on import.
"""
from __future__ import annotations

CATEGORIES: dict[str, dict] = {
    "crypto": {
        "keywords": [
            "bitcoin", "ethereum", "solana", "crypto", "defi", "sec crypto",
            "blockchain", "btc", "eth", "nft", "stablecoin", "coinbase",
        ],
        "twitter_keywords": ["Bitcoin", "Ethereum", "Solana", "crypto", "DeFi", "BTC", "ETH"],
        "rss_feeds": [
            "https://cointelegraph.com/rss",
            "https://coindesk.com/arc/outboundfeeds/rss/",
            "https://news.google.com/rss/search?q=bitcoin+crypto&hl=en-US&gl=US&ceid=US:en",
        ],
        "newsapi_queries": ["bitcoin", "ethereum crypto", "DeFi SEC"],
        "reddit_subs": ["CryptoCurrency", "Bitcoin", "ethereum", "CryptoMarkets"],
    },
    "politics": {
        "keywords": [
            "election", "trump", "congress", "senate", "tariff", "white house",
            "president", "democrat", "republican", "vote", "ballot", "impeach",
            "legislation", "executive order", "supreme court",
        ],
        "twitter_keywords": ["Trump", "Congress", "Senate", "election", "tariff", "White House"],
        "rss_feeds": [
            "https://news.google.com/rss/search?q=Trump+tariff+election&hl=en-US&gl=US&ceid=US:en",
            "https://feeds.reuters.com/reuters/topNews",
        ],
        "newsapi_queries": ["Trump election", "Congress Senate tariff", "White House executive"],
        "reddit_subs": ["politics", "Conservative", "democrat", "Republican", "PoliticalDiscussion"],
    },
    "economics": {
        "keywords": [
            "inflation", "fed", "federal reserve", "interest rate", "cpi", "fomc",
            "gdp", "recession", "unemployment", "jobs report", "pce", "ppi",
            "treasury", "yield curve", "rate hike", "rate cut",
        ],
        "twitter_keywords": ["Fed rate", "inflation", "FOMC", "CPI", "interest rate", "recession"],
        "rss_feeds": [
            "https://feeds.reuters.com/reuters/businessNews",
            "https://news.google.com/rss/search?q=Federal+Reserve+rate&hl=en-US&gl=US&ceid=US:en",
        ],
        "newsapi_queries": ["Federal Reserve interest rate", "inflation CPI FOMC", "GDP recession"],
        "reddit_subs": ["Economics", "economy", "investing", "wallstreetbets", "personalfinance"],
    },
    "weather": {
        "keywords": [
            "temperature", "storm", "hurricane", "noaa", "tornado", "flood",
            "drought", "wildfire", "earthquake", "blizzard", "heatwave", "typhoon",
            "forecast", "climate", "el nino", "la nina",
        ],
        "twitter_keywords": ["hurricane", "tornado", "storm", "NOAA", "flood", "wildfire"],
        "rss_feeds": [
            "https://news.google.com/rss/search?q=hurricane+storm+weather&hl=en-US&gl=US&ceid=US:en",
        ],
        "newsapi_queries": ["hurricane storm NOAA", "tornado flood weather", "wildfire earthquake"],
        "reddit_subs": ["weather", "hurricane", "climateskeptics", "ClimateOffensive"],
    },
    "sports": {
        "keywords": [
            "match", "league", "score", "championship", "nba", "nfl", "mlb",
            "nhl", "mls", "fifa", "world cup", "playoffs", "super bowl",
            "finals", "tournament", "draft", "trade",
        ],
        "twitter_keywords": ["NBA", "NFL", "MLB", "championship", "playoffs", "Super Bowl"],
        "rss_feeds": [
            "https://news.google.com/rss/search?q=NBA+NFL+championship&hl=en-US&gl=US&ceid=US:en",
        ],
        "newsapi_queries": ["NBA championship playoffs", "NFL Super Bowl", "MLB World Series"],
        "reddit_subs": ["nba", "nfl", "baseball", "soccer", "sports"],
    },
    "science": {
        "keywords": [
            "nasa", "spacex", "research", "discovery", "climate",
            "vaccine", "fda", "study", "breakthrough", "experiment",
            "mission", "launch", "orbit", "telescope", "protein",
        ],
        "twitter_keywords": ["NASA", "SpaceX", "research", "discovery", "climate", "FDA"],
        "rss_feeds": [
            "https://news.google.com/rss/search?q=SpaceX+Starship&hl=en-US&gl=US&ceid=US:en",
            "https://news.google.com/rss/search?q=NASA+science+discovery&hl=en-US&gl=US&ceid=US:en",
        ],
        "newsapi_queries": ["NASA SpaceX launch", "FDA vaccine approval", "scientific discovery research"],
        "reddit_subs": ["science", "space", "nasa", "Futurology", "medicine"],
    },
    "ai": {
        "keywords": [
            "openai", "gpt", "anthropic", "claude", "gemini", "llm",
            "artificial intelligence", "machine learning", "deep learning",
            "chatgpt", "mistral", "llama", "sam altman", "ai regulation",
        ],
        "twitter_keywords": ["OpenAI", "GPT", "Anthropic", "Claude", "Gemini", "LLM", "ChatGPT"],
        "rss_feeds": [
            "https://news.google.com/rss/search?q=OpenAI+GPT&hl=en-US&gl=US&ceid=US:en",
            "https://news.google.com/rss/search?q=AI+artificial+intelligence&hl=en-US&gl=US&ceid=US:en",
        ],
        "newsapi_queries": ["OpenAI GPT ChatGPT", "Anthropic Claude AI", "LLM artificial intelligence"],
        "reddit_subs": ["artificial", "MachineLearning", "OpenAI", "ChatGPT", "LocalLLaMA"],
    },
    "technology": {
        "keywords": [
            "apple", "microsoft", "nvidia", "google", "startup", "software",
            "semiconductor", "chip", "iphone", "android", "cybersecurity",
            "hack", "data breach", "ipo", "acquisition", "merger",
        ],
        "twitter_keywords": ["Apple", "Microsoft", "NVIDIA", "Google", "startup", "software"],
        "rss_feeds": [
            "https://feeds.feedburner.com/TechCrunch",
            "https://feeds.arstechnica.com/arstechnica/technology-lab",
            "https://www.theverge.com/rss/index.xml",
            "https://rss.nytimes.com/services/xml/rss/nyt/Technology.xml",
        ],
        "newsapi_queries": ["Apple Microsoft Google tech", "NVIDIA semiconductor chip", "startup IPO acquisition"],
        "reddit_subs": ["technology", "tech", "programming", "apple", "Android"],
    },
}


def is_relevant_event(event, selected: list[str]) -> bool:
    """True if headline contains any keyword from any selected category.

    Returns True for all events if selected == ["all"].
    """
    if selected == ["all"]:
        return True
    headline_lower = event.headline.lower()
    for cat in selected:
        cat_data = CATEGORIES.get(cat, {})
        for kw in cat_data.get("keywords", []):
            if kw.lower() in headline_lower:
                return True
    return False


def get_twitter_keywords(categories: list[str]) -> list[str]:
    """Union of twitter_keywords across selected categories."""
    result: list[str] = []
    seen: set[str] = set()
    for cat in categories:
        for kw in CATEGORIES.get(cat, {}).get("twitter_keywords", []):
            if kw not in seen:
                seen.add(kw)
                result.append(kw)
    return result


def get_rss_feeds(categories: list[str]) -> list[str]:
    """Union of rss_feeds across selected categories."""
    result: list[str] = []
    seen: set[str] = set()
    for cat in categories:
        for feed in CATEGORIES.get(cat, {}).get("rss_feeds", []):
            if feed not in seen:
                seen.add(feed)
                result.append(feed)
    return result


def get_newsapi_queries(categories: list[str]) -> list[str]:
    """Union of newsapi_queries across selected categories."""
    result: list[str] = []
    seen: set[str] = set()
    for cat in categories:
        for q in CATEGORIES.get(cat, {}).get("newsapi_queries", []):
            if q not in seen:
                seen.add(q)
                result.append(q)
    return result


def get_reddit_subreddits(categories: list[str]) -> list[str]:
    """Union of reddit_subs across selected categories."""
    result: list[str] = []
    seen: set[str] = set()
    for cat in categories:
        for sub in CATEGORIES.get(cat, {}).get("reddit_subs", []):
            if sub not in seen:
                seen.add(sub)
                result.append(sub)
    return result


def get_category(event_or_market) -> str:
    """Infer category from event headline or market question text."""
    from markets import _infer_category  # type: ignore
    text = getattr(event_or_market, "headline", None) or getattr(event_or_market, "question", "")
    return _infer_category(text)
