from __future__ import annotations

from dataclasses import dataclass


@dataclass
class WatchlistHit:
    direction: str
    phrase: str
    confidence: float


_WATCHLIST: list[tuple[str, str, float]] = [
    # YES — definitive outcomes
    ("confirmed", "YES", 0.85),
    ("approved", "YES", 0.85),
    ("passed", "YES", 0.80),
    ("signed into law", "YES", 0.92),
    ("won", "YES", 0.88),
    ("wins", "YES", 0.88),
    ("victory", "YES", 0.85),
    ("elected", "YES", 0.92),
    ("launched", "YES", 0.82),
    ("released", "YES", 0.80),
    ("deal reached", "YES", 0.90),
    ("agreement signed", "YES", 0.90),
    ("ceasefire", "YES", 0.85),
    ("merger complete", "YES", 0.92),
    ("acquisition complete", "YES", 0.92),
    ("ipo priced", "YES", 0.88),
    ("rate cut", "YES", 0.88),
    ("indicted", "YES", 0.90),
    ("arrested", "YES", 0.88),
    ("convicted", "YES", 0.92),
    ("pleads guilty", "YES", 0.95),
    ("resigns", "YES", 0.90),
    ("resigned", "YES", 0.90),
    ("steps down", "YES", 0.88),
    ("fired", "YES", 0.88),
    ("bankrupt", "YES", 0.90),
    ("bankruptcy", "YES", 0.90),
    ("chapter 11", "YES", 0.90),
    ("default", "YES", 0.85),
    ("breakthrough", "YES", 0.75),
    ("record high", "YES", 0.80),
    ("all-time high", "YES", 0.80),
    ("new high", "YES", 0.78),
    ("surpasses", "YES", 0.78),
    ("exceeds", "YES", 0.78),
    ("beats expectations", "YES", 0.82),
    ("beats estimates", "YES", 0.82),
    ("impeached", "YES", 0.90),
    # NO — outcomes that prevent / reverse
    ("rejected", "NO", 0.85),
    ("denied", "NO", 0.82),
    ("failed", "NO", 0.80),
    ("blocked", "NO", 0.82),
    ("vetoed", "NO", 0.88),
    ("acquitted", "NO", 0.92),
    ("not guilty", "NO", 0.92),
    ("dismissed", "NO", 0.82),
    ("delayed", "NO", 0.72),
    ("postponed", "NO", 0.72),
    ("cancelled", "NO", 0.78),
    ("canceled", "NO", 0.78),
    ("withdrawn", "NO", 0.80),
    ("suspended", "NO", 0.78),
    ("banned", "NO", 0.80),
    ("misses expectations", "NO", 0.82),
    ("misses estimates", "NO", 0.82),
    ("below expectations", "NO", 0.80),
    ("record low", "NO", 0.80),
    ("all-time low", "NO", 0.80),
    ("collapses", "NO", 0.85),
    ("crashes", "NO", 0.82),
    ("plunges", "NO", 0.78),
    ("no deal", "NO", 0.88),
    ("talks collapse", "NO", 0.88),
    ("deal falls through", "NO", 0.88),
    ("ceasefire collapses", "NO", 0.90),
    ("ceasefire ends", "NO", 0.85),
    ("war declared", "NO", 0.85),
    ("sanctions imposed", "NO", 0.82),
    ("rate hike", "NO", 0.85),
]

_PHRASE_INDEX: dict[str, tuple[str, float]] = {
    phrase.lower(): (direction, confidence)
    for phrase, direction, confidence in _WATCHLIST
}


class WatchlistMatcher:

    def match(self, headline: str) -> WatchlistHit | None:
        lower = headline.lower()
        best: WatchlistHit | None = None
        for phrase, (direction, confidence) in _PHRASE_INDEX.items():
            if phrase in lower:
                if best is None or len(phrase) > len(best.phrase):
                    best = WatchlistHit(direction=direction, phrase=phrase, confidence=confidence)
        return best


_matcher = WatchlistMatcher()


def check_watchlist(headline: str) -> WatchlistHit | None:
    return _matcher.match(headline)
