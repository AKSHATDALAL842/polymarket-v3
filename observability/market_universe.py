"""
Market universe audit — trace every market through the filtering pipeline
to understand exactly why so few survive.
"""
from __future__ import annotations

import sys
from dataclasses import dataclass, field


@dataclass
class MarketFilterAudit:
    total_fetched_polymarket: int = 0
    total_fetched_kalshi: int = 0
    after_active_filter: int = 0
    after_volume_filter: int = 0
    after_category_filter: int = 0
    after_niche_filter: int = 0
    final_tracked: int = 0
    volume_distribution: dict[str, int] = field(default_factory=dict)
    category_distribution: dict[str, int] = field(default_factory=dict)
    source_distribution: dict[str, int] = field(default_factory=dict)
    filter_details: list[dict] = field(default_factory=list)


def audit_market_universe() -> MarketFilterAudit:
    """Fetch all markets and trace every filter that reduces the count."""
    import config
    from ingestion.markets import fetch_active_markets, filter_by_categories, Market
    from rich.console import Console

    console = Console()
    audit = MarketFilterAudit()

    # Step 1: Raw fetch
    console.print("[bold]Step 1: Raw market fetch[/bold]")
    all_poly = fetch_active_markets(limit=200)
    audit.total_fetched_polymarket = len(all_poly)
    console.print(f"  Polymarket: {len(all_poly)} markets")

    if config.KALSHI_ENABLED:
        try:
            from ingestion.kalshi_markets import fetch_kalshi_markets
            kalshi = fetch_kalshi_markets(limit=200)
            audit.total_fetched_kalshi = len(kalshi)
            all_markets = all_poly + kalshi
            console.print(f"  Kalshi: {len(kalshi)} markets")
        except Exception as e:
            all_markets = all_poly
            console.print(f"  Kalshi: skipped ({e})")
    else:
        all_markets = all_poly

    total_raw = len(all_markets)
    console.print(f"  Total raw: {total_raw}")

    # Step 2: Active filter
    active = [m for m in all_markets if m.active]
    audit.after_active_filter = len(active)
    console.print(f"\n[bold]Step 2: Active filter[/bold]")
    console.print(f"  Active: {len(active)} (removed {total_raw - len(active)} inactive)")

    # Step 3: Volume distribution analysis
    console.print(f"\n[bold]Step 3: Volume distribution[/bold]")
    volumes = [m.volume for m in active]
    if volumes:
        vols_sorted = sorted(volumes)
        console.print(f"  Min: ${min(volumes):,.0f}  Max: ${max(volumes):,.0f}")
        console.print(f"  Median: ${vols_sorted[len(vols_sorted)//2]:,.0f}")
        console.print(f"  p25: ${vols_sorted[len(vols_sorted)//4]:,.0f}")
        console.print(f"  p75: ${vols_sorted[int(len(vols_sorted)*0.75)]:,.0f}")
        console.print(f"  p90: ${vols_sorted[min(len(vols_sorted)-1, int(len(vols_sorted)*0.90))]:,.0f}")

    buckets = {"0-$1K": 0, "$1K-$10K": 0, "$10K-$100K": 0,
               "$100K-$500K": 0, "$500K-$1M": 0, "$1M-$10M": 0, "$10M+": 0}
    for m in active:
        v = m.volume
        if v < 1_000: buckets["0-$1K"] += 1
        elif v < 10_000: buckets["$1K-$10K"] += 1
        elif v < 100_000: buckets["$10K-$100K"] += 1
        elif v < 500_000: buckets["$100K-$500K"] += 1
        elif v < 1_000_000: buckets["$500K-$1M"] += 1
        elif v < 10_000_000: buckets["$1M-$10M"] += 1
        else: buckets["$10M+"] += 1
    audit.volume_distribution = buckets
    for bucket, count in buckets.items():
        marker = " [dim](in niche range)[/dim]" if bucket in ("$1K-$10K", "$10K-$100K", "$100K-$500K") else ""
        console.print(f"  {bucket}: {count}{marker}")

    # Step 4: Volume filter (niche)
    console.print(f"\n[bold]Step 4: Volume filter (niche: ${config.MIN_VOLUME_USD:,.0f}-${config.MAX_VOLUME_USD:,.0f})[/bold]")
    in_range = [m for m in active if config.MIN_VOLUME_USD <= m.volume <= config.MAX_VOLUME_USD]
    audit.after_volume_filter = len(in_range)
    console.print(f"  In range: {len(in_range)} (removed {len(active) - len(in_range)})")
    below_min = sum(1 for m in active if m.volume < config.MIN_VOLUME_USD)
    above_max = sum(1 for m in active if m.volume > config.MAX_VOLUME_USD)
    console.print(f"    Below ${config.MIN_VOLUME_USD:,.0f}: {below_min}")
    console.print(f"    Above ${config.MAX_VOLUME_USD:,.0f}: {above_max}")

    # Step 5: Category filter
    console.print(f"\n[bold]Step 5: Category filter[/bold]")
    console.print(f"  Target categories: {config.SELECTED_CATEGORIES}")
    categorized = filter_by_categories(all_markets)
    audit.after_category_filter = len(categorized)
    cat_counts: dict[str, int] = {}
    for m in categorized:
        cat_counts[m.category] = cat_counts.get(m.category, 0) + 1
    audit.category_distribution = cat_counts
    for cat, count in sorted(cat_counts.items(), key=lambda x: -x[1]):
        console.print(f"  {cat}: {count}")

    # Step 6: Combined niche + category
    console.print(f"\n[bold]Step 6: Combined (niche + category)[/bold]")
    niche_cat = [
        m for m in categorized
        if config.MIN_VOLUME_USD <= m.volume <= config.MAX_VOLUME_USD
    ]
    # Sort by expiry (short-duration first) to match watcher behavior
    from datetime import datetime, timezone
    now = datetime.now(timezone.utc)
    cutoff_days = config.PREFER_SHORT_DURATION_DAYS

    def _days(m):
        ed = m.end_date
        if not ed:
            return float("inf")
        try:
            if ed.endswith("Z"):
                ed = ed[:-1] + "+00:00"
            dt = datetime.fromisoformat(ed)
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            return max(0.0, (dt - now).total_seconds() / 86400.0)
        except (ValueError, TypeError):
            return float("inf")

    short = [m for m in niche_cat if _days(m) <= cutoff_days]
    long_ = [m for m in niche_cat if _days(m) > cutoff_days]
    final = short + long_
    audit.after_niche_filter = len(niche_cat)
    audit.final_tracked = len(final)

    source_counts: dict[str, int] = {}
    for m in final:
        src = getattr(m, "source", "polymarket")
        source_counts[src] = source_counts.get(src, 0) + 1
    audit.source_distribution = source_counts

    console.print(f"  Niche + category: {len(niche_cat)}")
    console.print(f"  Short-duration (<= {cutoff_days}d): {len(short)}")
    console.print(f"  Long-duration: {len(long_)}")
    console.print(f"  Final tracked: [bold]{len(final)}[/bold]")
    console.print(f"  By source: {source_counts}")

    # Summary
    console.print(f"\n[bold green]MARKET UNIVERSE: {len(final)} markets[/bold green]")
    console.print(f"[dim]Drop chain: {total_raw} fetched → {len(active)} active → "
                  f"{len(in_range)} volume-filtered → {len(categorized)} categorized → "
                  f"{len(niche_cat)} niche+categorized → {len(final)} final[/dim]")

    # Show what high-volume markets are being excluded
    high_vol = [m for m in active if m.volume > config.MAX_VOLUME_USD]
    if high_vol:
        console.print(f"\n[yellow]EXCLUDED HIGH-VOLUME MARKETS (>{config.MAX_VOLUME_USD:,.0f}):[/yellow]")
        for m in sorted(high_vol, key=lambda x: -x.volume)[:10]:
            console.print(f"  [{m.category}] {m.question[:70]} (${m.volume:,.0f})")

    return audit


if __name__ == "__main__":
    audit_market_universe()
