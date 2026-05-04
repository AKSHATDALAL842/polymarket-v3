from __future__ import annotations

import datetime
import logging
import re
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

import numpy as np

import config
from signal.watchlist import check_watchlist, WatchlistHit

log = logging.getLogger(__name__)

_MODEL_PATH = Path(__file__).parent.parent / "models" / "fast_classifier.lgbm"

_CERTAINTY_WORDS = {
    "confirmed", "official", "officially", "announces", "announced",
    "signed", "passed", "approved", "rejected", "wins", "won", "loses", "lost",
    "convicted", "acquitted", "indicted", "arrested", "resigns", "fired",
    "bankrupt", "launched", "released", "deployed",
}

_UNCERTAINTY_WORDS = {
    "reportedly", "expected", "likely", "may", "might", "could",
    "considering", "exploring", "rumored", "speculation", "unconfirmed",
    "allegedly", "claims", "suggests",
}

_HIGH_CRED_SOURCES = {
    "reuters", "bloomberg", "ap", "associated press", "wsj",
    "wall street journal", "ft", "financial times", "bbc", "nyt", "new york times",
}

_MED_CRED_SOURCES = {
    "cnn", "fox", "cnbc", "msnbc", "the guardian",
    "washington post", "politico", "axios", "the hill",
}


@dataclass
class ClassifierResult:
    direction: str
    confidence: float
    materiality: float
    method: str
    latency_ms: int


def _source_credibility(source: str) -> float:
    lower = source.lower()
    if any(s in lower for s in _HIGH_CRED_SOURCES):
        return 1.0
    if any(s in lower for s in _MED_CRED_SOURCES):
        return 0.65
    return 0.35


def _certainty_score(lower: str) -> float:
    pos = sum(1 for w in _CERTAINTY_WORDS if w in lower)
    neg = sum(1 for w in _UNCERTAINTY_WORDS if w in lower)
    return max(0.0, min(1.0, (pos - neg * 0.5) / max(1, pos + neg)))


class FeatureExtractor:
    _POS_WORDS = {"up", "rise", "gain", "surge", "soar", "jump", "boost", "win", "pass", "approve"}
    _NEG_WORDS = {"down", "fall", "drop", "crash", "plunge", "lose", "fail", "reject", "deny", "block"}

    def extract(self, headline: str, source: str, market_yes_price: float,
                age_seconds: float = 0.0) -> np.ndarray:
        lower = headline.lower()
        words = lower.split()
        n = max(1, len(words))
        now = datetime.datetime.now()

        # Text (12)
        f0 = n / 30.0
        f1 = 1.0 if headline and headline[0].isupper() else 0.0
        f2 = float(bool(re.search(r"\d", headline)))
        f3 = float(any(m in lower for m in ["ed ", "ed:", "was ", "were ", "has ", "have "]))
        f4 = _certainty_score(lower)
        f5 = sum(1 for w in self._POS_WORDS if w in lower) / n
        f6 = sum(1 for w in self._NEG_WORDS if w in lower) / n
        f7 = len(headline) / 200.0
        f8 = float("%" in headline or "percent" in lower)
        f9 = float(any(c in headline for c in ["$", "€", "£"]))
        f10 = float(":" in headline)
        f11 = float("!" in headline)

        # NER proxies (8)
        f12 = float(bool(re.search(r"\b[A-Z]{2,}\b", headline)))
        f13 = float(bool(re.search(r"\b[A-Z][a-z]+ [A-Z][a-z]+\b", headline)))
        f14 = float("president" in lower or "senator" in lower or "congress" in lower)
        f15 = float("fed" in lower or "federal reserve" in lower or "powell" in lower)
        f16 = float("bitcoin" in lower or "btc" in lower or "crypto" in lower or "ethereum" in lower)
        f17 = float("china" in lower or "russia" in lower or "iran" in lower or "ukraine" in lower)
        f18 = float("openai" in lower or "anthropic" in lower or "google" in lower
                    or "meta" in lower or "microsoft" in lower)
        f19 = float("tariff" in lower or "sanction" in lower or "trade war" in lower)

        # Source (4)
        src_cred = _source_credibility(source)
        f20 = src_cred
        f21 = float(src_cred >= 0.9)
        f22 = float("twitter" in source.lower() or "reddit" in source.lower())
        f23 = float("telegram" in source.lower())

        # Market context (7)
        f24 = market_yes_price
        f25 = abs(market_yes_price - 0.5)
        f26 = float(market_yes_price > 0.7)
        f27 = float(market_yes_price < 0.3)
        f28 = float(0.4 <= market_yes_price <= 0.6)
        f29 = market_yes_price * (1.0 - market_yes_price)
        f30 = float(market_yes_price > 0.9 or market_yes_price < 0.1)

        # Temporal (5)
        f31 = min(1.0, age_seconds / 3600.0)
        f32 = (now.hour * 60 + now.minute) / 1440.0
        f33 = float(now.weekday() >= 5)
        f34 = now.weekday() / 6.0
        f35 = float(age_seconds > 300)

        # Novelty proxy (4)
        f36 = float(any(w in lower for w in ["breaking", "just in", "developing", "alert", "update"]))
        f37 = float(any(w in lower for w in ["exclusive", "first", "new", "latest"]))
        f38 = float(any(w in lower for w in ["report", "sources", "according"]))
        f39 = float(any(w in lower for w in ["official", "statement", "confirmed", "press release"]))

        return np.array([
            f0, f1, f2, f3, f4, f5, f6, f7, f8, f9, f10, f11,
            f12, f13, f14, f15, f16, f17, f18, f19,
            f20, f21, f22, f23,
            f24, f25, f26, f27, f28, f29, f30,
            f31, f32, f33, f34, f35,
            f36, f37, f38, f39,
        ], dtype=np.float32)


_extractor = FeatureExtractor()
_lgbm_model = None


def is_trained() -> bool:
    """True if a trained LightGBM model is available for inference."""
    return _lgbm_model is not None or _MODEL_PATH.exists()


def _load_lgbm():
    global _lgbm_model
    if not _MODEL_PATH.exists():
        return None
    try:
        import lightgbm as lgb
        _lgbm_model = lgb.Booster(model_file=str(_MODEL_PATH))
        log.info("[fast_classifier] Loaded LightGBM model")
    except Exception as e:
        log.warning(f"[fast_classifier] Could not load model: {e}")
        _lgbm_model = None
    return _lgbm_model


def _rule_based(headline: str, source: str) -> ClassifierResult:
    lower = headline.lower()
    certainty = sum(1 for w in _CERTAINTY_WORDS if w in lower)
    src_cred = _source_credibility(source)
    hit = check_watchlist(headline)
    watched = 1.0 if hit else 0.0
    has_num = float(bool(re.search(r"\d", headline)))
    past = float(any(m in lower for m in ["ed ", "ed:", "was ", "were "]))

    score = certainty * 0.25 + src_cred * 0.35 + watched * 0.15 + has_num * 0.10 + past * 0.15

    if score < 0.30 or hit is None:
        return ClassifierResult(direction="NEUTRAL", confidence=0.0, materiality=0.0,
                                method="rule_based", latency_ms=0)

    confidence = min(0.80, hit.confidence * src_cred * 1.1)
    materiality = min(0.80, score * 0.70)
    return ClassifierResult(direction=hit.direction, confidence=confidence,
                            materiality=materiality, method="rule_based", latency_ms=0)


def predict(
    headline: str,
    source: str,
    market_yes_price: float,
    age_seconds: float = 0.0,
) -> ClassifierResult:
    t0 = time.monotonic()

    # Watchlist short-circuit for high-confidence phrase + credible source
    hit = check_watchlist(headline)
    if hit is not None and _source_credibility(source) >= 0.65:
        confidence = min(0.88, hit.confidence * _source_credibility(source))
        return ClassifierResult(
            direction=hit.direction,
            confidence=confidence,
            materiality=0.70,
            method="watchlist",
            latency_ms=int((time.monotonic() - t0) * 1000),
        )

    model = _lgbm_model or _load_lgbm()

    if model is None:
        result = _rule_based(headline, source)
        result.latency_ms = int((time.monotonic() - t0) * 1000)
        return result

    try:
        features = _extractor.extract(headline, source, market_yes_price, age_seconds)
        # model output columns assumed: [P(NEUTRAL)=0, P(NO)=1, P(YES)=2]
        probs = model.predict(features.reshape(1, -1))[0]
        yes_p, no_p = float(probs[2]), float(probs[1])

        if yes_p > no_p and yes_p > 0.5:
            direction, confidence = "YES", yes_p
        elif no_p > yes_p and no_p > 0.5:
            direction, confidence = "NO", no_p
        else:
            direction, confidence = "NEUTRAL", 0.0

        return ClassifierResult(
            direction=direction,
            confidence=confidence,
            materiality=max(yes_p, no_p) * 0.80,
            method="lgbm",
            latency_ms=int((time.monotonic() - t0) * 1000),
        )

    except Exception as e:
        log.warning(f"[fast_classifier] Inference failed, falling back: {e}")
        result = _rule_based(headline, source)
        result.latency_ms = int((time.monotonic() - t0) * 1000)
        return result


def build_classification(result: ClassifierResult):
    from signal.classifier import Classification
    novelty = 0.50 if result.method in ("lgbm", "watchlist") else 0.40
    return Classification(
        direction=result.direction,
        confidence=result.confidence,
        materiality=result.materiality,
        novelty_score=novelty,
        time_sensitivity="immediate" if result.method == "watchlist" else "short-term",
        reasoning=f"fast_classifier ({result.method}): {result.direction} conf={result.confidence:.2f}",
        consistency=config.HOT_PATH_CONSISTENCY,
        total_latency_ms=result.latency_ms,
        model="fast_classifier",
    )


def train(label_store_path: str) -> bool:
    try:
        import json
        import lightgbm as lgb
        from sklearn.model_selection import train_test_split

        records = []
        with open(label_store_path) as f:
            for line in f:
                line = line.strip()
                if line:
                    records.append(json.loads(line))

        if len(records) < 50:
            log.info(f"[fast_classifier] Only {len(records)} labels — need 50+ to train")
            return False

        label_map = {"NEUTRAL": 0, "NO": 1, "YES": 2}
        X, y = [], []
        for r in records:
            feats = _extractor.extract(
                r["headline"], r.get("source", ""), r.get("yes_price", 0.5)
            )
            X.append(feats)
            y.append(label_map.get(r.get("label", "NEUTRAL"), 0))

        X_arr = np.array(X)
        y_arr = np.array(y)

        X_tr, X_val, y_tr, y_val = train_test_split(X_arr, y_arr, test_size=0.2, random_state=42)
        ds_tr = lgb.Dataset(X_tr, label=y_tr)
        ds_val = lgb.Dataset(X_val, label=y_val, reference=ds_tr)

        params = {
            "objective": "multiclass",
            "num_class": 3,
            "learning_rate": 0.05,
            "num_leaves": 31,
            "verbosity": -1,
        }
        model = lgb.train(
            params, ds_tr, num_boost_round=200,
            valid_sets=[ds_val],
            callbacks=[lgb.early_stopping(20, verbose=False), lgb.log_evaluation(0)],
        )
        _MODEL_PATH.parent.mkdir(parents=True, exist_ok=True)
        model.save_model(str(_MODEL_PATH))
        log.info(f"[fast_classifier] Trained on {len(records)} examples → {_MODEL_PATH}")
        return True

    except Exception as e:
        log.error(f"[fast_classifier] Training failed: {e}")
        return False
