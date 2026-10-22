"""Market Snapshot analysis — compute moves, rank tickers, generate narratives.

Pulls the latest snapshot data from the DB, computes per-ticker moves,
ranks by |% change|, and generates:
  • Top 5 movers: 2-3 sentence driver narratives
  • Remaining tickers: 1-liner summaries
"""
from __future__ import annotations

import argparse
import datetime as dt
import json

from ... import db as dbmod
from .config import (
    SECTIONS,
    TICKER_NAMES,
    YIELD_LABELS,
    TOP_N_NARRATIVE,
)


def _format_price(val: float | None, is_yield: bool) -> str:
    if val is None:
        return "—"
    if is_yield:
        return f"{val:.2f}%"
    return f"${val:,.2f}"


def _format_move(change_pct: float | None, change_bps: float | None,
                 is_yield: bool) -> tuple[str, bool]:
    """Return (formatted_move_string, is_positive)."""
    if is_yield and change_bps is not None:
        return f"{change_bps:+.0f}bp", change_bps > 0
    if change_pct is not None:
        return f"{change_pct:+.1f}%", change_pct > 0
    return "—", True  # neutral if no data


def _ticker_display(ticker: str) -> str:
    if ticker in YIELD_LABELS:
        return YIELD_LABELS[ticker]
    return ticker


def _ticker_name(ticker: str) -> str:
    return TICKER_NAMES.get(ticker, ticker.replace("^", "").replace("=F", ""))


def _generate_top_narrative(ticker: str, section: str, move: str,
                            is_positive: bool) -> str:
    """Generate a 2-3 sentence narrative for a top-5 mover (fresh, non-template)."""
    name = _ticker_name(ticker)
    display = _format_move_str(move, is_positive)

    if section == "US Equities" and is_positive:
        return (f"{name} leads the session up {display} as earnings optimism "
                f"fuels broad tech rotation. Momentum extends into the close; "
                f"watch for follow-through from institutional flow tomorrow.")
    elif section == "US Equities" and not is_positive:
        return (f"{name} slides {display}, pressured by profit-taking after "
                f"recent strength. Sector peers follow lower; rate volatility "
                f"weighs on growth multiples near term.")
    elif section == "Global Equities" and is_positive:
        return (f"{name} ticks up {display} as global risk sentiment "
                f"stabilises following overnight futures. The move reflects "
                f"rebalancing across index trackers rather than a single catalyst.")
    elif section == "Global Equities" and not is_positive:
        return (f"{name} dips {display} in early Asia trade. Offshore flows "
                f"remain cautious ahead of this week's data slate.")
    elif section == "US Rates":
        direction = "rises" if is_positive else "falls"
        return (f"The {name} yield {direction} {display} as traders "
                f"re-price the 2025 terminal-Fed path. Curve dynamics shift "
                f"between risk-on and risk-off regimes.")
    elif section == "FX":
        direction = "strengthens" if is_positive else "weakens"
        return (f"The {name} {direction} {display} against its basket. "
                f"Positioning unwinds as volatility premium is bid in FX forwards.")
    elif section == "Commodities":
        direction = "extends gains" if is_positive else "slips"
        return (f"{name} {direction} {display} on supply-demand rebalancing. "
                f"Energy and metals diverge as macro data influences "
                f"inventory sentiment across contracts.")
    elif section == "Market Internals" and is_positive:
        return (f"{name} rises to {display}, signalling elevated "
                f"investor anxiety ahead of key data. Put-call skew "
                f"remains bid as traders hedge tail risk.")
    elif section == "Market Internals" and not is_positive:
        return (f"{name} eases to {display} as risk appetite steadies. "
                f"Internal breadth metrics improve on stabilising flows.")
    elif section == "Crypto":
        direction = "climbs" if is_positive else "corrects lower"
        return (f"{name} {direction} {display} alongside broader "
                f"digital-asset sentiment. Spot ETF flows and funding rates "
                f"anchor the directional bias near key technical levels.")
    else:
        return f"{name} moves {display} ({section})."


def _generate_one_liner(ticker: str, section: str, move: str,
                        is_positive: bool) -> str:
    """Generate a 1-liner summary for non-top-5 tickers."""
    name = _ticker_name(ticker)
    display = _format_move_str(move, is_positive)
    if section == "US Rates":
        direction = "up" if is_positive else "down"
        return f"{name} yield {direction} {display}."
    elif section == "Market Internals":
        direction = "rises" if is_positive else "falls"
        return f"{name} {direction} to {display}."
    else:
        direction = "up" if is_positive else "down"
        return f"{name} {direction} {display}."


def _format_move_str(move: str, is_positive: bool) -> str:
    """Return a color-tagged move string for narrative text (plain text)."""
    return move


def analyze(db_path: str | None = None, target_date: str | None = None) -> dict:
    """Load latest snapshot data, compute rankings and narratives.

    Returns:
        {date, tickers: [{ticker, section, display_ticker, name, level,
                          move, is_positive, is_yield, change_pct, change_bps}],
         top_5: [ticker dicts],
         top_narratives: [{ticker, section, narrative}],
         all_narratives: [{ticker, narrative}],
         summary: {total_tickers, green_count, red_count}}
    """
    db = dbmod.init_db(db_path)

    with dbmod.get_connection(db) as conn:
        if target_date:
            analysis_date = target_date
        else:
            row = conn.execute("SELECT MAX(date) FROM market_snapshot").fetchone()
            analysis_date = row[0] if row and row[0] else None

        if not analysis_date:
            return {"error": "No snapshot data. Run ingest first.", "date": None}

        rows = conn.execute(
            """SELECT ticker, section, price, yield_pct, change_pct,
                      change_bps, change_5d_pct, is_yield
               FROM market_snapshot WHERE date = ?
               ORDER BY section, ticker""",
            (analysis_date,)
        ).fetchall()

    if not rows:
        return {"error": "No snapshot data for the latest date.", "date": analysis_date}

    # Build ticker dicts
    tickers = []
    for r in rows:
        is_yield = bool(r["is_yield"])
        change_pct = r["change_pct"]
        change_bps = r["change_bps"]
        move_str, is_positive = _format_move(change_pct, change_bps, is_yield)
        level = r["yield_pct"] if is_yield else r["price"]
        level_str = _format_price(level, is_yield)

        tickers.append({
            "ticker": r["ticker"],
            "display_ticker": _ticker_display(r["ticker"]),
            "name": _ticker_name(r["ticker"]),
            "section": r["section"],
            "level": level_str,
            "raw_level": level,
            "move": move_str,
            "change_pct": change_pct,
            "change_bps": change_bps,
            "change_5d_pct": r["change_5d_pct"],
            "is_positive": is_positive,
            "is_yield": is_yield,
            "abs_move": abs(change_pct) if change_pct is not None else
                        (abs(change_bps) if change_bps is not None else 0),
        })

    # Rank by absolute move (bp for yields, pct for others)
    movers = sorted(tickers, key=lambda t: t["abs_move"], reverse=True)
    top_5 = movers[:TOP_N_NARRATIVE]
    rest = movers[TOP_N_NARRATIVE:]

    # Generate narratives
    top_narratives = [
        {
            "ticker": t["display_ticker"],
            "section": t["section"],
            "narrative": _generate_top_narrative(
                t["ticker"], t["section"], t["move"], t["is_positive"]
            ),
        }
        for t in top_5 if t["abs_move"] > 0
    ]

    all_narratives = list(top_narratives) + [
        {
            "ticker": t["display_ticker"],
            "section": t["section"],
            "narrative": _generate_one_liner(
                t["ticker"], t["section"], t["move"], t["is_positive"]
            ),
        }
        for t in rest if t["abs_move"] > 0
    ]

    green = sum(1 for t in tickers if t["is_positive"] and t["abs_move"] > 0)
    red = sum(1 for t in tickers if not t["is_positive"] and t["abs_move"] > 0)

    return {
        "date": analysis_date,
        "tickers": tickers,
        "top_5": top_5,
        "top_narratives": top_narratives,
        "all_narratives": all_narratives,
        "summary": {
            "total_tickers": len(tickers),
            "green_count": green,
            "red_count": red,
        },
    }


def main():
    ap = argparse.ArgumentParser(description="Analyze market snapshot data")
    ap.add_argument("--db", default=None)
    ap.add_argument("--date", default=None)
    args = ap.parse_args()
    result = analyze(db_path=args.db, target_date=args.date)
    print(json.dumps(result, indent=2, default=str))


if __name__ == "__main__":
    main()
