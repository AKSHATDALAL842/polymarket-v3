"""
Market matching audit — deep inspection of embedding quality, entity extraction,
keyword matching, and candidate ranking.

Usage: python -m observability.market_audit [--headlines-file PATH]
"""
from __future__ import annotations

import json
import time
from dataclasses import dataclass, field
from typing import Optional


@dataclass
class MatchAuditResult:
    headline: str
    source: str
    n_available_markets: int
    semantic_matches: list[dict] = field(default_factory=list)
    keyword_matches: list[dict] = field(default_factory=list)
    embedding_available: bool = False
    nlp_entities: list[str] = field(default_factory=list)
    nlp_sentiment: float = 0.0
    nlp_impact: float = 0.0
    nlp_relevance: float = 0.0
    passed_nlp_gate: bool = False
    category_filter_pass: bool = False
    best_similarity: float = 0.0
    match_latency_ms: int = 0
    error: Optional[str] = None


def audit_headline(headline: str, source: str = "audit",
                   markets: list | None = None) -> MatchAuditResult:
    """Run a single headline through NLP + matching and return full diagnostics."""
    import config
    from signal import nlp_processor
    from signal.matcher import match_news_to_markets, get_embed_fn
    from ingestion.categories import is_relevant_event

    result = MatchAuditResult(headline=headline, source=source, n_available_markets=0)

    # Check embedding availability
    embed_fn = get_embed_fn()
    result.embedding_available = embed_fn is not None

    # NLP analysis
    nlp = nlp_processor.process(
        headline=headline,
        source=source,
        age_seconds=0,
        novelty_score=0.5,
    )
    result.nlp_entities = [e.text for e in nlp.entities]
    result.nlp_sentiment = round(nlp.sentiment_polarity, 4)
    result.nlp_impact = round(nlp.impact_score, 4)
    result.nlp_relevance = round(nlp.relevance, 4)
    result.passed_nlp_gate = nlp.relevance >= config.NLP_MIN_IMPACT

    # Category check
    event_headline = headline
    class StubEvent:
        pass
    stub = StubEvent()
    stub.headline = event_headline
    result.category_filter_pass = is_relevant_event(stub, config.SELECTED_CATEGORIES)

    if markets is None:
        from ingestion.markets import fetch_active_markets, filter_by_categories
        try:
            all_m = fetch_active_markets(limit=100)
            markets = filter_by_categories(all_m)
        except Exception as e:
            result.error = f"Market fetch failed: {e}"
            return result

    result.n_available_markets = len(markets)
    if not markets:
        result.error = "No markets available to match against"
        return result

    # Matching
    t0 = time.monotonic()
    try:
        matches = match_news_to_markets(headline, markets, top_k=5)
        result.match_latency_ms = int((time.monotonic() - t0) * 1000)

        for m in matches:
            match_info = {
                "market_id": m.market.condition_id,
                "question": m.market.question,
                "similarity": round(m.similarity, 4),
                "method": m.match_method,
                "yes_price": m.market.yes_price,
                "volume": m.market.volume,
                "category": getattr(m.market, "category", "unknown"),
            }
            if m.match_method == "semantic":
                result.semantic_matches.append(match_info)
            else:
                result.keyword_matches.append(match_info)

        if matches:
            result.best_similarity = matches[0].similarity
    except Exception as e:
        result.error = f"Match failed: {e}"

    return result


def batch_audit(headlines: list[str], source: str = "audit",
                markets: list | None = None) -> list[MatchAuditResult]:
    """Run audit on multiple headlines. Fetches markets once."""
    import config
    from ingestion.markets import fetch_active_markets, filter_by_categories

    if markets is None:
        try:
            all_m = fetch_active_markets(limit=100)
            markets = filter_by_categories(all_m)
            print(f"Fetched {len(markets)} markets for audit")
        except Exception as e:
            print(f"Market fetch failed: {e}")
            markets = []

    results = []
    for i, h in enumerate(headlines):
        r = audit_headline(h, source=source, markets=markets)
        results.append(r)
        if (i + 1) % 10 == 0:
            print(f"  Audited {i+1}/{len(headlines)} headlines...")

    return results


def print_audit_report(results: list[MatchAuditResult]):
    """Print a comprehensive market matching audit report."""
    from rich.console import Console
    from rich.table import Table
    from rich.panel import Panel

    console = Console()
    console.print(Panel("[bold bright_cyan]MARKET MATCHING AUDIT[/bold bright_cyan]",
                        style="bright_cyan"))

    total = len(results)
    passed_nlp = sum(1 for r in results if r.passed_nlp_gate)
    passed_cat = sum(1 for r in results if r.category_filter_pass)
    has_matches = sum(1 for r in results if r.semantic_matches or r.keyword_matches)
    has_embedding = results[0].embedding_available if results else False

    console.print(f"\n[bold]SUMMARY[/bold]")
    console.print(f"  Headlines audited: {total}")
    console.print(f"  Embedding model loaded: [{'green' if has_embedding else 'red'}]{has_embedding}[/{'green' if has_embedding else 'red'}]")
    console.print(f"  Passed NLP gate: {passed_nlp}/{total} ({passed_nlp/max(1,total)*100:.1f}%)")
    console.print(f"  Passed category filter: {passed_cat}/{total} ({passed_cat/max(1,total)*100:.1f}%)")
    console.print(f"  Has at least one match: {has_matches}/{total} ({has_matches/max(1,total)*100:.1f}%)")

    # Similarity distribution
    sims = [r.best_similarity for r in results if r.semantic_matches or r.keyword_matches]
    if sims:
        sims_sorted = sorted(sims)
        console.print(f"\n[bold]SIMILARITY DISTRIBUTION[/bold]")
        console.print(f"  Best: {max(sims):.4f}  Worst: {min(sims):.4f}")
        console.print(f"  Median: {sims_sorted[len(sims_sorted)//2]:.4f}")
        console.print(f"  p75: {sims_sorted[int(len(sims_sorted)*0.75)]:.4f}")
        console.print(f"  p90: {sims_sorted[min(len(sims_sorted)-1, int(len(sims_sorted)*0.90))]:.4f}")
        below_03 = sum(1 for s in sims if s < 0.30)
        below_02 = sum(1 for s in sims if s < 0.20)
        console.print(f"  Below 0.30 threshold: {below_03}/{len(sims)} ({below_03/max(1,len(sims))*100:.1f}%)")
        console.print(f"  Below 0.20: {below_02}/{len(sims)} ({below_02/max(1,len(sims))*100:.1f}%)")

    # NLP impact distribution
    impacts = [r.nlp_impact for r in results]
    if impacts:
        console.print(f"\n[bold]NLP IMPACT DISTRIBUTION[/bold]")
        console.print(f"  Mean: {sum(impacts)/len(impacts):.4f}")
        console.print(f"  Max: {max(impacts):.4f}  Min: {min(impacts):.4f}")
        below_010 = sum(1 for i in impacts if i < 0.10)
        console.print(f"  Below 0.10 (NLP_MIN_IMPACT): {below_010}/{len(impacts)} ({below_010/max(1,len(impacts))*100:.1f}%)")

    # Per-headline details
    console.print(f"\n[bold]PER-HEADLINE DETAILS[/bold]")
    table = Table(show_header=True, header_style="bold white")
    table.add_column("Headline", max_width=45)
    table.add_column("NLP Gate", width=9)
    table.add_column("Cat OK", width=7)
    table.add_column("Best Sim", justify="right", width=9)
    table.add_column("Matches", justify="right", width=8)
    table.add_column("Entities", max_width=25)

    for r in results:
        nlp_color = "green" if r.passed_nlp_gate else "red"
        cat_color = "green" if r.category_filter_pass else "red"
        sim_color = "green" if r.best_similarity >= 0.30 else ("yellow" if r.best_similarity >= 0.15 else "red")
        n_matches = len(r.semantic_matches) + len(r.keyword_matches)

        table.add_row(
            r.headline[:45],
            f"[{nlp_color}]{'PASS' if r.passed_nlp_gate else 'FAIL'}[/{nlp_color}]",
            f"[{cat_color}]{'Y' if r.category_filter_pass else 'N'}[/{cat_color}]",
            f"[{sim_color}]{r.best_similarity:.4f}[/{sim_color}]",
            str(n_matches),
            ", ".join(r.nlp_entities[:4]) if r.nlp_entities else "none",
        )

    console.print(table)

    # Recommendations
    console.print(f"\n[bold]FINDINGS:[/bold]")
    nlp_fail_rate = 1.0 - (passed_nlp / max(1, total))
    match_fail_rate = 1.0 - (has_matches / max(1, total))

    if nlp_fail_rate > 0.5:
        console.print(f"[red]NLP gate is blocking {nlp_fail_rate:.0%} of headlines[/red]")
        console.print(f"[dim]  NLP_MIN_IMPACT = 0.10. Consider whether headline impact scores are systematically low.[/dim]")
        console.print(f"[dim]  Check: source reliability weights, entity extraction quality, sentiment signals.[/dim]")

    if match_fail_rate > 0.5:
        console.print(f"[red]Market matching fails for {match_fail_rate:.0%} of headlines[/red]")
        console.print(f"[dim]  MATCHER_MIN_SIMILARITY = 0.30. Consider whether this threshold is too high.[/dim]")
        console.print(f"[dim]  Check: embedding model quality, market question diversity, keyword fallback effectiveness.[/dim]")

    if not has_embedding:
        console.print(f"[yellow]Embedding model not loaded — falling back to keyword matching only[/yellow]")
        console.print(f"[dim]  Keyword matching is fragile and misses semantic connections.[/dim]")
        console.print(f"[dim]  Fix: pip install sentence-transformers[/dim]")


if __name__ == "__main__":
    # Default test headlines covering diverse scenarios
    test_headlines = [
        "Bitcoin surges past $100K as ETF inflows hit record levels",
        "Federal Reserve signals rate cut in September FOMC meeting",
        "OpenAI announces GPT-5 with breakthrough reasoning capabilities",
        "SpaceX Starship completes first orbital test flight successfully",
        "Trump wins Republican nomination for 2028 presidential race",
        "EU Parliament approves comprehensive AI regulation framework",
        "China GDP growth misses expectations at 3.2% for Q3",
        "NVIDIA reports record quarterly revenue of $45 billion",
        "SEC approves spot Ethereum ETF for immediate trading",
        "Major earthquake detected off Japan coast, tsunami warning issued",
        "New international climate deal signed at UN summit in Geneva",
        "Apple unveils augmented reality glasses at WWDC keynote",
        "Oil prices crash 15% after surprise OPEC production increase",
        "Pfizer announces breakthrough results in cancer vaccine trial",
        "UK inflation rate unexpectedly drops to 1.8% in December",
        "just thinking about market dynamics today",  # low-signal
        "what do you guys think about the fed?",  # discussion
        "BREAKING: Fed raises interest rates by 50 basis points",  # high-signal
    ]

    import sys
    if len(sys.argv) > 1 and sys.argv[1] == "--file":
        with open(sys.argv[2]) as f:
            headlines = [line.strip() for line in f if line.strip()]
    else:
        headlines = test_headlines

    results = batch_audit(headlines)
    print_audit_report(results)
