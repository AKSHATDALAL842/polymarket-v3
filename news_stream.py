"""
Real-time news monitor — event-driven architecture.
Sources: Twitter API v2 filtered stream, Telegram channels, RSS fallback.
Emits NewsEvent objects into an asyncio queue as breaking news arrives.
"""
from __future__ import annotations

import asyncio
import json
import time
import logging
from datetime import datetime, timezone, timedelta
from dataclasses import dataclass, field

import httpx

import config
from scraper import scrape_all, NewsItem

log = logging.getLogger(__name__)


@dataclass
class NewsEvent:
    headline: str
    source: str  # "twitter", "telegram", "rss"
    url: str
    received_at: datetime
    published_at: datetime
    summary: str = ""
    raw_data: dict = field(default_factory=dict)
    latency_ms: int = 0  # time from publication to our receipt

    def age_seconds(self) -> float:
        return (datetime.now(timezone.utc) - self.received_at).total_seconds()


class TwitterStream:
    """Twitter API v2 filtered stream for real-time keyword monitoring."""

    def __init__(self, bearer_token: str, keywords: list[str]):
        self.bearer_token = bearer_token
        self.keywords = keywords
        self.base_url = "https://api.twitter.com/2"
        self.enabled = bool(bearer_token)

    def _headers(self) -> dict:
        return {"Authorization": f"Bearer {self.bearer_token}"}

    async def setup_rules(self):
        """Set up filtered stream rules based on keywords."""
        if not self.enabled:
            return

        async with httpx.AsyncClient() as client:
            # Get existing rules
            resp = await client.get(
                f"{self.base_url}/tweets/search/stream/rules",
                headers=self._headers(),
                timeout=10,
            )
            existing = resp.json().get("data", [])

            # Delete existing rules
            if existing:
                ids = [r["id"] for r in existing]
                await client.post(
                    f"{self.base_url}/tweets/search/stream/rules",
                    headers=self._headers(),
                    json={"delete": {"ids": ids}},
                    timeout=10,
                )

            # Create new rules from keywords (max 25 chars per rule for Basic)
            rules = []
            # Batch keywords into OR groups
            batch_size = 5
            for i in range(0, len(self.keywords), batch_size):
                batch = self.keywords[i:i + batch_size]
                value = " OR ".join(f'"{kw}"' for kw in batch)
                rules.append({"value": value, "tag": f"batch_{i // batch_size}"})

            if rules:
                await client.post(
                    f"{self.base_url}/tweets/search/stream/rules",
                    headers=self._headers(),
                    json={"add": rules[:5]},  # Basic tier: 5 rules max
                    timeout=10,
                )

    async def stream(self, queue: asyncio.Queue):
        """Connect to filtered stream and emit NewsEvents."""
        if not self.enabled:
            log.info("[twitter] No bearer token — stream disabled")
            return

        try:
            await self.setup_rules()
        except Exception as e:
            log.warning(f"[twitter] Failed to setup rules: {e}")
            return

        backoff = 1
        while True:
            try:
                async with httpx.AsyncClient() as client:
                    async with client.stream(
                        "GET",
                        f"{self.base_url}/tweets/search/stream",
                        headers=self._headers(),
                        params={"tweet.fields": "created_at,author_id,text"},
                        timeout=None,
                    ) as resp:
                        if resp.status_code == 429:
                            log.warning(
                                "[twitter] 429 Too Many Requests — filtered stream requires "
                                "Twitter API Basic tier ($100/mo). Falling back to RSS only."
                            )
                            return
                        if resp.status_code == 403:
                            log.warning(
                                "[twitter] 403 Forbidden — account does not have stream access. "
                                "Falling back to RSS only."
                            )
                            return
                        backoff = 1
                        async for line in resp.aiter_lines():
                            if not line.strip():
                                continue
                            try:
                                data = json.loads(line)
                                tweet = data.get("data", {})
                                text = tweet.get("text", "")
                                created = tweet.get("created_at", "")

                                now = datetime.now(timezone.utc)
                                try:
                                    pub = datetime.fromisoformat(created.replace("Z", "+00:00"))
                                    latency = int((now - pub).total_seconds() * 1000)
                                except (ValueError, AttributeError):
                                    pub = now
                                    latency = 0

                                event = NewsEvent(
                                    headline=text[:280],
                                    source="twitter",
                                    url=f"https://twitter.com/i/status/{tweet.get('id', '')}",
                                    received_at=now,
                                    published_at=pub,
                                    latency_ms=latency,
                                    raw_data=data,
                                )
                                await queue.put(event)
                            except Exception as e:
                                log.debug(f"[twitter] Parse error: {e}")

            except (httpx.HTTPError, Exception) as e:
                log.warning(f"[twitter] Stream error: {e}, reconnecting in {backoff}s")
                await asyncio.sleep(backoff)
                backoff = min(backoff * 2, 60)


class TelegramMonitor:
    """Monitor Telegram channels via Bot API long polling."""

    def __init__(self, bot_token: str, channel_ids: list[str]):
        self.bot_token = bot_token
        self.channel_ids = channel_ids
        self.enabled = bool(bot_token) and bool(channel_ids)
        self.last_update_id = 0

    async def stream(self, queue: asyncio.Queue):
        """Poll for new messages and emit NewsEvents."""
        if not self.enabled:
            log.info("[telegram] No bot token or channels — monitor disabled")
            return

        base_url = f"https://api.telegram.org/bot{self.bot_token}"

        while True:
            try:
                async with httpx.AsyncClient() as client:
                    resp = await client.get(
                        f"{base_url}/getUpdates",
                        params={"offset": self.last_update_id + 1, "timeout": 30},
                        timeout=35,
                    )
                    data = resp.json()

                for update in data.get("result", []):
                    self.last_update_id = update["update_id"]
                    msg = update.get("channel_post") or update.get("message", {})
                    text = msg.get("text", "")
                    chat_id = str(msg.get("chat", {}).get("id", ""))

                    if not text or (self.channel_ids and chat_id not in self.channel_ids):
                        continue

                    now = datetime.now(timezone.utc)
                    msg_date = msg.get("date", 0)
                    pub = datetime.fromtimestamp(msg_date, tz=timezone.utc) if msg_date else now
                    latency = int((now - pub).total_seconds() * 1000)

                    event = NewsEvent(
                        headline=text[:500],
                        source="telegram",
                        url="",
                        received_at=now,
                        published_at=pub,
                        latency_ms=latency,
                        raw_data=update,
                    )
                    await queue.put(event)

            except Exception as e:
                log.warning(f"[telegram] Error: {e}")
                await asyncio.sleep(5)


class NewsAPISource:
    """
    NewsAPI.org polling — free tier gives 100 req/day.
    Polls /v2/everything every 30s across all keyword groups.
    Covers breaking news 2-3 minutes after publication.
    """

    BASE_URL = "https://newsapi.org/v2/everything"
    QUERIES = [
        "Bitcoin OR Ethereum OR crypto",
        "OpenAI OR Anthropic OR GPT",
        "Federal Reserve OR Fed rate OR inflation",
        "Trump OR tariff OR election",
        "SpaceX OR Starship OR NASA",
        "NVIDIA OR Apple OR Microsoft earnings",
    ]

    def __init__(self, api_key: str, interval_seconds: float = 30):
        self.api_key = api_key
        self.interval = interval_seconds
        self.enabled = bool(api_key)
        self._seen: set[str] = set()

    async def stream(self, queue: asyncio.Queue):
        if not self.enabled:
            log.info("[newsapi] No API key — disabled")
            return

        log.info("[newsapi] Starting — polling every 30s")
        query_cycle = 0

        while True:
            try:
                query = self.QUERIES[query_cycle % len(self.QUERIES)]
                query_cycle += 1

                async with httpx.AsyncClient() as client:
                    resp = await client.get(
                        self.BASE_URL,
                        params={
                            "q": query,
                            "sortBy": "publishedAt",
                            "pageSize": 20,
                            "language": "en",
                            "apiKey": self.api_key,
                        },
                        timeout=10,
                    )
                    if resp.status_code == 429:
                        log.warning("[newsapi] Rate limit hit — slowing down")
                        await asyncio.sleep(60)
                        continue
                    if resp.status_code != 200:
                        await asyncio.sleep(self.interval)
                        continue

                    articles = resp.json().get("articles", [])
                    now = datetime.now(timezone.utc)
                    new_count = 0

                    for article in articles:
                        headline = article.get("title", "").strip()
                        if not headline or headline == "[Removed]":
                            continue

                        key = headline.lower()[:80]
                        if key in self._seen:
                            continue
                        self._seen.add(key)
                        new_count += 1

                        pub_str = article.get("publishedAt", "")
                        try:
                            pub = datetime.fromisoformat(pub_str.replace("Z", "+00:00"))
                        except Exception:
                            pub = now
                        latency = int((now - pub).total_seconds() * 1000)

                        # Skip stale articles (>30 min old)
                        if latency > 1800000:
                            continue

                        event = NewsEvent(
                            headline=headline,
                            source="newsapi",
                            url=article.get("url", ""),
                            received_at=now,
                            published_at=pub,
                            summary=article.get("description", "")[:300],
                            latency_ms=latency,
                        )
                        await queue.put(event)

                    if new_count:
                        log.info(f"[newsapi] {new_count} new articles (query: {query[:40]})")

                    if len(self._seen) > 5000:
                        self._seen = set(list(self._seen)[-2000:])

            except Exception as e:
                log.warning(f"[newsapi] Error: {e}")

            await asyncio.sleep(self.interval)


class RedditSource:
    """
    Reddit JSON API — no key required.
    Uses AdaptiveSubredditSelector for alpha-weighted, performance-adaptive sampling.
    Filters posts with is_high_signal() before emitting to pipeline.
    """

    def __init__(self, interval_seconds: float = 45):
        self.interval = interval_seconds
        self._seen: set[str] = set()
        self._headers = {
            "User-Agent": "polymarket-pipeline/3.0 (news aggregator)"
        }
        from reddit_source import AdaptiveSubredditSelector, is_high_signal
        self._selector = AdaptiveSubredditSelector()
        self._is_high_signal = is_high_signal

    async def stream(self, queue: asyncio.Queue):
        log.info("[reddit] Starting — adaptive weighted subreddit sampling")

        while True:
            try:
                sub = self._selector.get_next()

                async with httpx.AsyncClient(headers=self._headers) as client:
                    resp = await client.get(
                        f"https://www.reddit.com/r/{sub}/new.json",
                        params={"limit": 25},
                        timeout=10,
                    )
                    if resp.status_code != 200:
                        await asyncio.sleep(self.interval)
                        continue

                    posts = resp.json().get("data", {}).get("children", [])
                    now = datetime.now(timezone.utc)
                    new_count = 0
                    filtered_count = 0

                    for post in posts:
                        data = post.get("data", {})
                        title = data.get("title", "").strip()
                        if not title:
                            continue

                        self._selector.record_post_seen(sub)

                        key = title.lower()[:80]
                        if key in self._seen:
                            continue
                        self._seen.add(key)

                        created_utc = data.get("created_utc", 0)
                        pub = datetime.fromtimestamp(created_utc, tz=timezone.utc)
                        latency = int((now - pub).total_seconds() * 1000)

                        # Skip posts older than 20 minutes
                        if latency > 1200000:
                            continue

                        # Filter: only pass high-signal posts
                        if not self._is_high_signal(title):
                            filtered_count += 1
                            continue

                        new_count += 1
                        event = NewsEvent(
                            headline=title,
                            source="reddit",
                            url=f"https://reddit.com{data.get('permalink', '')}",
                            received_at=now,
                            published_at=pub,
                            summary=data.get("selftext", "")[:200],
                            latency_ms=latency,
                            raw_data={"subreddit": sub},
                        )
                        await queue.put(event)

                    if new_count:
                        log.info(f"[reddit] {new_count} signals (r/{sub}, filtered={filtered_count})")

                    if len(self._seen) > 5000:
                        self._seen = set(list(self._seen)[-2000:])

            except Exception as e:
                log.warning(f"[reddit] Error: {e}")

            await asyncio.sleep(self.interval)


class GNewsSource:
    """
    GNews API (gnews.io) — structured news with clean metadata.
    Free tier: 100 requests/day → poll every 15 min, 6 topic groups.
    Each request returns up to 10 articles.
    """

    BASE_URL = "https://gnews.io/api/v4"
    TOPICS = [
        ("breaking", "top-headlines"),
        ("technology", "top-headlines"),
        ("business", "top-headlines"),
        ("world", "top-headlines"),
        ("politics", "search"),
        ("crypto OR bitcoin OR ethereum", "search"),
    ]

    def __init__(self, api_key: str, interval_seconds: float = 900):
        self.api_key = api_key
        self.interval = interval_seconds
        self.enabled = bool(api_key)
        self._seen: set[str] = set()
        self._topic_cycle = 0

    async def stream(self, queue: asyncio.Queue):
        if not self.enabled:
            log.info("[gnews] No API key — disabled")
            return

        log.info("[gnews] Starting — polling every 15 min (100 req/day free tier)")

        while True:
            try:
                topic, endpoint = self.TOPICS[self._topic_cycle % len(self.TOPICS)]
                self._topic_cycle += 1

                params = {
                    "token": self.api_key,
                    "lang": "en",
                    "max": 10,
                    "sortby": "publishedAt",
                }
                if endpoint == "top-headlines":
                    params["topic"] = topic
                    url = f"{self.BASE_URL}/top-headlines"
                else:
                    params["q"] = topic
                    url = f"{self.BASE_URL}/search"

                async with httpx.AsyncClient() as client:
                    resp = await client.get(url, params=params, timeout=10)

                if resp.status_code == 403:
                    log.warning("[gnews] 403 — invalid API key")
                    return
                if resp.status_code == 429:
                    log.warning("[gnews] Daily limit hit — sleeping 1h")
                    await asyncio.sleep(3600)
                    continue
                if resp.status_code != 200:
                    await asyncio.sleep(self.interval)
                    continue

                articles = resp.json().get("articles", [])
                now = datetime.now(timezone.utc)
                new_count = 0

                for article in articles:
                    headline = article.get("title", "").strip()
                    if not headline:
                        continue

                    key = headline.lower()[:80]
                    if key in self._seen:
                        continue
                    self._seen.add(key)

                    pub_str = article.get("publishedAt", "")
                    try:
                        pub = datetime.fromisoformat(pub_str.replace("Z", "+00:00"))
                    except Exception:
                        pub = now
                    latency = int((now - pub).total_seconds() * 1000)

                    if latency > 3600000:   # skip if >1h old
                        continue

                    new_count += 1
                    event = NewsEvent(
                        headline=headline,
                        source="gnews",
                        url=article.get("url", ""),
                        received_at=now,
                        published_at=pub,
                        summary=article.get("description", "")[:300],
                        latency_ms=latency,
                        raw_data={"topic": topic, "source_name": article.get("source", {}).get("name", "")},
                    )
                    await queue.put(event)

                if new_count:
                    log.info(f"[gnews] {new_count} new articles (topic={topic})")

                if len(self._seen) > 5000:
                    self._seen = set(list(self._seen)[-2000:])

            except Exception as e:
                log.warning(f"[gnews] Error: {e}")

            await asyncio.sleep(self.interval)


class GDELTSource:
    """
    GDELT Project DOC 2.0 API — structured global event data.
    Free, no key required. Rich geopolitical + macro coverage.
    Polls multiple queries every 5 minutes.
    """

    BASE_URL = "https://api.gdeltproject.org/api/v2/doc/doc"
    QUERIES = [
        "Federal Reserve interest rate",
        "election results president",
        "sanctions war military",
        "OpenAI Google Microsoft AI",
        "Bitcoin Ethereum cryptocurrency SEC",
        "SpaceX NASA launch",
        "trade tariff import export",
        "central bank monetary policy",
    ]

    def __init__(self, interval_seconds: float = 300):
        self.interval = interval_seconds
        self._seen: set[str] = set()
        self._query_cycle = 0

    async def stream(self, queue: asyncio.Queue):
        log.info("[gdelt] Starting — polling 8 queries every 5 min (free, no key)")

        while True:
            try:
                query = self.QUERIES[self._query_cycle % len(self.QUERIES)]
                self._query_cycle += 1

                async with httpx.AsyncClient() as client:
                    resp = await client.get(
                        self.BASE_URL,
                        params={
                            "query": query,
                            "mode": "artlist",
                            "maxrecords": 25,
                            "sort": "DateDesc",
                            "format": "json",
                        },
                        timeout=15,
                    )

                if resp.status_code != 200:
                    await asyncio.sleep(self.interval)
                    continue

                data = resp.json()
                articles = data.get("articles", [])
                now = datetime.now(timezone.utc)
                new_count = 0

                for article in articles:
                    headline = article.get("title", "").strip()
                    if not headline:
                        continue

                    key = headline.lower()[:80]
                    if key in self._seen:
                        continue
                    self._seen.add(key)

                    # GDELT seendate format: YYYYMMDDTHHMMSSZ
                    seendate = article.get("seendate", "")
                    try:
                        pub = datetime.strptime(seendate, "%Y%m%dT%H%M%SZ").replace(tzinfo=timezone.utc)
                    except Exception:
                        pub = now
                    latency = int((now - pub).total_seconds() * 1000)

                    if latency > 1800000:   # skip if >30 min old
                        continue

                    new_count += 1
                    event = NewsEvent(
                        headline=headline,
                        source="gdelt",
                        url=article.get("url", ""),
                        received_at=now,
                        published_at=pub,
                        summary=article.get("socialimage", ""),
                        latency_ms=latency,
                        raw_data={"query": query, "domain": article.get("domain", "")},
                    )
                    await queue.put(event)

                if new_count:
                    log.info(f"[gdelt] {new_count} new articles (query: {query[:40]})")

                if len(self._seen) > 5000:
                    self._seen = set(list(self._seen)[-2000:])

            except Exception as e:
                log.warning(f"[gdelt] Error: {e}")

            await asyncio.sleep(self.interval)


class RSSFallback:
    """Periodic RSS scraping as a fallback news source."""

    def __init__(self, interval_seconds: float = 120, feeds=None):
        self.interval = interval_seconds
        self._feeds = feeds
        self._seen_headlines: set[str] = set()

    async def stream(self, queue: asyncio.Queue):
        """Poll RSS feeds periodically and emit new headlines."""
        while True:
            try:
                items = await asyncio.get_event_loop().run_in_executor(
                    None, lambda: scrape_all(feeds=self._feeds)
                )
                now = datetime.now(timezone.utc)
                new_count = 0

                for item in items:
                    key = item.headline.lower()[:80]
                    if key in self._seen_headlines:
                        continue
                    self._seen_headlines.add(key)
                    new_count += 1

                    latency = int((now - item.published_at).total_seconds() * 1000)

                    event = NewsEvent(
                        headline=item.headline,
                        source="rss",
                        url=item.url,
                        received_at=now,
                        published_at=item.published_at,
                        summary=item.summary,
                        latency_ms=latency,
                    )
                    await queue.put(event)

                if new_count:
                    log.info(f"[rss] {new_count} new headlines")

                # Trim seen cache
                if len(self._seen_headlines) > 5000:
                    self._seen_headlines = set(list(self._seen_headlines)[-2000:])

            except Exception as e:
                log.warning(f"[rss] Error: {e}")

            await asyncio.sleep(self.interval)


class NewsAggregator:
    """Runs all news sources concurrently, deduplicates, emits to output queue."""

    def __init__(self, output_queue: asyncio.Queue, categories=None):
        from categories import (
            get_twitter_keywords, get_rss_feeds,
            get_newsapi_queries, get_reddit_subreddits,
        )
        cats = categories or config.SELECTED_CATEGORIES
        if cats != ["all"]:
            _twitter_keywords = get_twitter_keywords(cats)
            _rss_feeds = get_rss_feeds(cats)
            _newsapi_queries = get_newsapi_queries(cats)
            _reddit_subs = get_reddit_subreddits(cats)
        else:
            _twitter_keywords = config.TWITTER_KEYWORDS
            _rss_feeds = config.RSS_FEEDS
            _newsapi_queries = None   # use source defaults
            _reddit_subs = None       # use source defaults

        self.output_queue = output_queue
        self._internal_queue: asyncio.Queue = asyncio.Queue()
        self._seen: set[str] = set()

        self.twitter = TwitterStream(config.TWITTER_BEARER_TOKEN, _twitter_keywords)
        self.telegram = TelegramMonitor(config.TELEGRAM_BOT_TOKEN, config.TELEGRAM_CHANNEL_IDS)
        self.rss = RSSFallback(interval_seconds=60, feeds=_rss_feeds)
        # NewsAPISource does not accept a queries param; it uses a hardcoded QUERIES class attribute.
        # Category-specific newsapi queries are not wired into NewsAPISource (out of scope).
        self.newsapi = NewsAPISource(config.NEWSAPI_KEY, interval_seconds=30)
        # RedditSource does not accept a subs param; it uses AdaptiveSubredditSelector internally.
        # Category-specific subreddits are not wired into RedditSource (out of scope).
        self.reddit = RedditSource(interval_seconds=45)
        self.gnews = GNewsSource(config.GNEWS_API_KEY, interval_seconds=900)
        self.gdelt = GDELTSource(interval_seconds=300)

        self.stats = {
            "twitter": 0, "telegram": 0, "rss": 0,
            "newsapi": 0, "reddit": 0, "gnews": 0, "gdelt": 0,
            "total": 0, "deduped": 0,
        }

    async def run(self):
        """Start all sources and the dedup router."""
        await asyncio.gather(
            self.twitter.stream(self._internal_queue),
            self.telegram.stream(self._internal_queue),
            self.rss.stream(self._internal_queue),
            self.newsapi.stream(self._internal_queue),
            self.reddit.stream(self._internal_queue),
            self.gnews.stream(self._internal_queue),
            self.gdelt.stream(self._internal_queue),
            self._dedup_router(),
            return_exceptions=True,
        )

    async def _dedup_router(self):
        """Deduplicate and forward events to output queue."""
        while True:
            event = await self._internal_queue.get()
            key = event.headline.lower()[:80]
            if key in self._seen:
                self.stats["deduped"] += 1
                continue

            self._seen.add(key)
            self.stats[event.source] = self.stats.get(event.source, 0) + 1
            self.stats["total"] += 1

            await self.output_queue.put(event)

            if len(self._seen) > 10000:
                self._seen = set(list(self._seen)[-5000:])


if __name__ == "__main__":
    async def _test():
        q: asyncio.Queue = asyncio.Queue()
        agg = NewsAggregator(q)

        async def printer():
            while True:
                event = await q.get()
                print(f"[{event.source}] ({event.latency_ms}ms) {event.headline[:80]}")

        await asyncio.gather(agg.run(), printer())

    asyncio.run(_test())
