import pytest
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from ingestion.categories import (
    CATEGORIES,
    is_relevant_event,
    get_twitter_keywords,
    get_rss_feeds,
    get_newsapi_queries,
    get_reddit_subreddits,
    get_category,
)
from dataclasses import dataclass


@dataclass
class FakeEvent:
    headline: str
    source: str = "rss"


def test_categories_keys():
    expected = {"crypto", "politics", "economics", "weather", "sports", "science", "ai", "technology"}
    assert set(CATEGORIES.keys()) == expected


def test_is_relevant_event_all():
    event = FakeEvent(headline="anything at all")
    assert is_relevant_event(event, ["all"]) is True


def test_is_relevant_event_match():
    event = FakeEvent(headline="Bitcoin hits new all time high")
    assert is_relevant_event(event, ["crypto"]) is True


def test_is_relevant_event_no_match():
    event = FakeEvent(headline="Local dog wins award at county fair")
    assert is_relevant_event(event, ["crypto", "politics"]) is False


def test_is_relevant_event_multi_category():
    event = FakeEvent(headline="Fed raises interest rates amid inflation")
    assert is_relevant_event(event, ["economics", "sports"]) is True


def test_get_twitter_keywords_union():
    kws = get_twitter_keywords(["crypto", "ai"])
    assert "Bitcoin" in kws
    assert "OpenAI" in kws


def test_get_rss_feeds_returns_list():
    feeds = get_rss_feeds(["crypto"])
    assert isinstance(feeds, list)
    assert len(feeds) > 0


def test_get_newsapi_queries_returns_list():
    queries = get_newsapi_queries(["politics"])
    assert isinstance(queries, list)
    assert len(queries) > 0


def test_get_reddit_subreddits_returns_list():
    subs = get_reddit_subreddits(["technology"])
    assert isinstance(subs, list)
    assert len(subs) > 0


def test_get_category_crypto():
    event = FakeEvent(headline="Bitcoin crashes amid SEC lawsuit")
    assert get_category(event) == "crypto"


def test_get_category_fallback():
    event = FakeEvent(headline="A completely unrelated sentence with no keywords")
    assert get_category(event) == "other"


def test_get_twitter_keywords_all():
    kws = get_twitter_keywords(["all"])
    assert len(kws) > 0
    assert "Bitcoin" in kws
    assert "OpenAI" in kws
    assert "Trump" in kws
