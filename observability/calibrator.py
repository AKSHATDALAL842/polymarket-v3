"""
Calibration System — tracks predicted vs actual outcomes with per-slice breakdowns.

Tracks accuracy by:
  - source (Twitter, Telegram, RSS)
  - category (crypto, politics, ai, ...)
  - confidence bucket (0.5-0.6, 0.6-0.7, 0.7-0.8, 0.8-0.9, 0.9-1.0)
  - materiality bucket

Outputs:
  - calibration curves (predicted confidence vs actual accuracy per bucket)
  - reliability scores
  - Brier score (proper scoring rule: lower = better)
"""
from __future__ import annotations

import logging
import math
from collections import defaultdict
from dataclasses import dataclass, field

import httpx

import config
from observability import logger

log = logging.getLogger(__name__)

GAMMA_API = "https://gamma-api.polymarket.com"


# ── Data classes ───────────────────────────────────────────────────────────────

@dataclass
class CalibrationBucket:
    """One confidence bin (e.g., 0.7–0.8)."""
    predicted_low: float
    predicted_high: float
    n_predictions: int = 0
    n_correct: int = 0
    sum_confidence: float = 0.0
    sum_brier: float = 0.0

    @property
    def accuracy(self) -> float:
        return self.n_correct / self.n_predictions if self.n_predictions else 0.0

    @property
    def mean_confidence(self) -> float:
        return self.sum_confidence / self.n_predictions if self.n_predictions else 0.0

    @property
    def mean_brier(self) -> float:
        return self.sum_brier / self.n_predictions if self.n_predictions else 0.0

    @property
    def calibration_error(self) -> float:
        """Signed error: positive = overconfident."""
        return self.mean_confidence - self.accuracy


@dataclass
class CalibrationReport:
    total: int
    overall_accuracy: float
    brier_score: float
    ece: float                                # Expected Calibration Error
    by_source: dict[str, dict]
    by_category: dict[str, dict]
    confidence_buckets: list[CalibrationBucket]
    recommendation: str


# ── Resolution checker ─────────────────────────────────────────────────────────

def check_resolutions() -> int:
    """
    Pull recent trades from SQLite, check if their markets have resolved,
    and update the calibration table. Returns count of newly resolved trades.
    """
    trades = logger.get_recent_trades(limit=200)
    unresolved = [
        t for t in trades
        if t.get("classification") and t.get("status") in ("dry_run", "executed")
    ]

    if not unresolved:
        return 0

    resolved_count = 0
    for trade in unresolved:
        market_id = trade["market_id"]
        try:
            resp = httpx.get(
                f"{GAMMA_API}/markets",
                params={"condition_id": market_id},
                timeout=10,
            )
            data = resp.json()
            items = data if isinstance(data, list) else data.get("data", [])
            if not items:
                continue

            market_data = items[0]
            if not market_data.get("closed", False):
                continue

            outcome_prices = market_data.get("outcomePrices", "")
            if isinstance(outcome_prices, str):
                import json
                try:
                    prices = json.loads(outcome_prices)
                except Exception:
                    continue
            else:
                prices = outcome_prices

            if not prices or len(prices) < 2:
                continue

            exit_price = float(prices[0])     # YES resolution price (0 or 1)
            entry_price = float(trade["market_price"])

            resolved_yes = exit_price > 0.5

            # What the model predicted
            cls = trade.get("classification", "neutral").upper()
            predicted_yes = cls == "YES"

            correct = predicted_yes == resolved_yes

            # Log to calibration table
            logger.log_calibration(
                trade_id=trade["id"],
                classification=cls,
                materiality=trade.get("materiality", 0.0),
                entry_price=entry_price,
                exit_price=exit_price,
                actual_direction="YES" if resolved_yes else "NO",
                correct=correct,
            )
            resolved_count += 1

        except Exception as e:
            log.debug(f"[calibrator] Error checking {market_id}: {e}")

    if resolved_count:
        log.info(f"[calibrator] Resolved {resolved_count} trades")
    return resolved_count


# ── Report generator ───────────────────────────────────────────────────────────

CONF_BUCKETS = [(i/10, (i+1)/10) for i in range(5, 10)]   # 0.5–0.6, 0.6–0.7, ...


def get_report() -> CalibrationReport:
    stats = logger.get_calibration_stats()

    if stats["total"] < 10:
        return CalibrationReport(
            total=stats["total"],
            overall_accuracy=0.0,
            brier_score=0.0,
            ece=0.0,
            by_source={},
            by_category={},
            confidence_buckets=[],
            recommendation="Need at least 10 resolved trades for meaningful calibration.",
        )

    trades = logger.get_recent_calibrated_trades(limit=500)

    # ── Build confidence buckets ───────────────────────────────────────────────
    buckets = {
        (lo, hi): CalibrationBucket(predicted_low=lo, predicted_high=hi)
        for lo, hi in CONF_BUCKETS
    }

    # ── Per-slice accumulators ─────────────────────────────────────────────────
    by_source: dict[str, dict] = defaultdict(lambda: {"n": 0, "correct": 0})
    by_category: dict[str, dict] = defaultdict(lambda: {"n": 0, "correct": 0})

    total_brier = 0.0
    total_correct = 0
    total = 0

    for trade in trades:
        conf = float(trade.get("materiality", 0.5))     # use materiality as proxy if no raw confidence
        correct = bool(trade.get("correct", False))
        source = trade.get("news_source", "unknown")
        category = trade.get("category", "unknown")

        predicted_prob = conf if correct else (1.0 - conf)   # heuristic
        actual = 1.0 if correct else 0.0

        brier = (predicted_prob - actual) ** 2
        total_brier += brier
        total += 1
        total_correct += int(correct)

        by_source[source]["n"] += 1
        by_source[source]["correct"] += int(correct)

        by_category[category]["n"] += 1
        by_category[category]["correct"] += int(correct)

        for (lo, hi), bucket in buckets.items():
            if lo <= conf < hi:
                bucket.n_predictions += 1
                bucket.n_correct += int(correct)
                bucket.sum_confidence += conf
                bucket.sum_brier += brier

    overall_accuracy = total_correct / total if total else 0.0
    brier_score = total_brier / total if total else 0.0

    # ECE: weighted average of |accuracy - mean_confidence| per bucket
    ece = 0.0
    for bucket in buckets.values():
        if bucket.n_predictions > 0:
            weight = bucket.n_predictions / total
            ece += weight * abs(bucket.calibration_error)

    # Recommendation
    if overall_accuracy >= 0.65:
        rec = f"Strong edge ({overall_accuracy:.1%} accuracy). Brier={brier_score:.3f}. Consider modest size increase."
    elif overall_accuracy >= 0.55:
        rec = f"Moderate edge ({overall_accuracy:.1%} accuracy). Brier={brier_score:.3f}. Hold current sizing."
    elif overall_accuracy >= 0.48:
        rec = f"Weak edge ({overall_accuracy:.1%}). Near random. Review novelty scoring and source quality."
    else:
        rec = f"NEGATIVE edge ({overall_accuracy:.1%}). PAUSE live trading, audit classification prompts."

    # Convert source/category accumulators to readable dicts
    def _acc_dict(d):
        return {
            k: {"accuracy": v["correct"] / v["n"] if v["n"] else 0, "n": v["n"]}
            for k, v in d.items()
        }

    return CalibrationReport(
        total=total,
        overall_accuracy=overall_accuracy,
        brier_score=brier_score,
        ece=ece,
        by_source=_acc_dict(by_source),
        by_category=_acc_dict(by_category),
        confidence_buckets=[b for b in buckets.values() if b.n_predictions > 0],
        recommendation=rec,
    )


def print_report(report: CalibrationReport):
    from rich.console import Console
    from rich.table import Table
    console = Console()

    console.print(f"\n[bold cyan]Calibration Report ({report.total} resolved trades)[/bold cyan]")
    console.print(f"Overall accuracy: [bold]{report.overall_accuracy:.1%}[/bold]  "
                  f"Brier score: [bold]{report.brier_score:.3f}[/bold]  "
                  f"ECE: [bold]{report.ece:.3f}[/bold]")
    console.print(f"[yellow]{report.recommendation}[/yellow]\n")

    # Confidence calibration curve
    if report.confidence_buckets:
        table = Table(title="Confidence Calibration Curve", header_style="bold green")
        table.add_column("Conf bucket")
        table.add_column("N", justify="right")
        table.add_column("Pred conf", justify="right")
        table.add_column("Actual acc", justify="right")
        table.add_column("Error", justify="right")

        for b in report.confidence_buckets:
            err = b.calibration_error
            err_style = "red" if abs(err) > 0.1 else ("yellow" if abs(err) > 0.05 else "green")
            table.add_row(
                f"{b.predicted_low:.1f}–{b.predicted_high:.1f}",
                str(b.n_predictions),
                f"{b.mean_confidence:.2f}",
                f"{b.accuracy:.2f}",
                f"[{err_style}]{err:+.2f}[/{err_style}]",
            )
        console.print(table)

    # By source
    if report.by_source:
        src_table = Table(title="Accuracy by Source", header_style="bold")
        src_table.add_column("Source")
        src_table.add_column("N", justify="right")
        src_table.add_column("Accuracy", justify="right")
        for src, d in sorted(report.by_source.items(), key=lambda x: -x[1]["n"]):
            color = "green" if d["accuracy"] >= 0.55 else "red"
            src_table.add_row(src, str(d["n"]), f"[{color}]{d['accuracy']:.1%}[/{color}]")
        console.print(src_table)
