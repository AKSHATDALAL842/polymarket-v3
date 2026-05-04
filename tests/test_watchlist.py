"""Tests for watchlist longest-match semantics (A-1 fix)."""
from __future__ import annotations

import pytest

from signal.watchlist import WatchlistMatcher, check_watchlist


@pytest.fixture
def matcher():
    return WatchlistMatcher()


# --- longest-match: "ceasefire collapses" beats "ceasefire" ---

@pytest.mark.parametrize("headline,expected_direction,expected_phrase", [
    # Short phrase "ceasefire" is YES; longer "ceasefire collapses" is NO.
    # Longest match must win.
    (
        "Middle East ceasefire collapses as fighting resumes",
        "NO",
        "ceasefire collapses",
    ),
    # "ceasefire ends" (NO) should beat "ceasefire" (YES).
    (
        "Gaza ceasefire ends after two weeks",
        "NO",
        "ceasefire ends",
    ),
    # Plain "ceasefire" with no shadowing phrase → YES.
    (
        "Leaders announce new ceasefire agreement",
        "YES",
        "ceasefire",
    ),
    # "deal falls through" (NO) beats "deal reached" (YES) if both
    # substrings appear — only "deal falls through" is a phrase hit here.
    (
        "Deal falls through despite last-minute talks",
        "NO",
        "deal falls through",
    ),
    # "talks collapse" (NO) beats "no deal" if both present.
    (
        "Talks collapse with no deal reached",
        "NO",
        "talks collapse",
    ),
])
def test_longest_match_wins(matcher, headline, expected_direction, expected_phrase):
    hit = matcher.match(headline)
    assert hit is not None, f"Expected a hit for: {headline!r}"
    assert hit.direction == expected_direction, (
        f"headline={headline!r}: expected {expected_direction}, got {hit.direction} "
        f"(phrase={hit.phrase!r})"
    )
    assert hit.phrase == expected_phrase, (
        f"headline={headline!r}: expected phrase {expected_phrase!r}, got {hit.phrase!r}"
    )


def test_no_match_returns_none(matcher):
    assert matcher.match("Nothing interesting happened today") is None


def test_check_watchlist_helper_delegates():
    """check_watchlist() is just a thin wrapper; verify it works the same."""
    hit = check_watchlist("ceasefire collapses in the region")
    assert hit is not None
    assert hit.direction == "NO"
    assert hit.phrase == "ceasefire collapses"


def test_case_insensitive(matcher):
    hit = matcher.match("CEASEFIRE COLLAPSES after summit")
    assert hit is not None
    assert hit.direction == "NO"


def test_longer_phrase_higher_confidence(matcher):
    # "ceasefire collapses" has confidence 0.90 vs "ceasefire" 0.85.
    hit = matcher.match("ceasefire collapses on the border")
    assert hit is not None
    assert hit.confidence == pytest.approx(0.90)
