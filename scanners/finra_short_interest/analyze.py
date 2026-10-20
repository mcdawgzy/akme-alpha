"""Analyze FINRA short interest data for trading signals.

Signal types:
- Short Spike: >50% WoW increase with >1M short (sudden short buildup)
- High DTC: >10 days to cover with >1M short (squeeze candidate)
- Largest Shorts: biggest absolute short positions
- Covering: >-30% WoW decrease with >1M short (short covering)
- Consensus: avg 5M+ short across 3+ settlement periods (heavily shorted)
"""
from __future__ import annotations

import argparse
import json

from ... import db as dbmod
from .config import THRESHOLDS


def analyze(db_path: str | None = None, settlement_date: str | None = None) -> dict:
    """Compute short interest signals for the latest settlement date.

    Returns: {latest_settlement, spikes[], high_dtc[], largest[], covering[],
              consensus[], summary}
    """
    db = dbmod.init_db(db_path)
    result = {"latest_settlement": None, "signals": {}, "summary": {}}

    with dbmod.get_connection(db) as conn:
        # Find latest settlement date
        latest = conn.execute(
            "SELECT MAX(settlement_date) FROM short_interest"
        ).fetchone()[0]
        if not latest:
            return {"error": "No short interest data ingested. Run ingest first.",
                    "status": "no_data"}
        result["latest_settlement"] = latest

        # ── Short Spikes (WoW > 50% increase, > 1M short) ─────────────────
        spikes = conn.execute(
            """SELECT symbol, issue_name, current_short, previous_short,
                      change_pct, days_to_cover, avg_daily_volume
               FROM short_interest
               WHERE settlement_date = ?
                 AND change_pct > ?
                 AND current_short > ?
               ORDER BY change_pct DESC
               LIMIT 20""",
            (latest, THRESHOLDS["spike_pct"], THRESHOLDS["spike_min_short"]),
        ).fetchall()
        result["spikes"] = [dict(r) for r in spikes]

        # ── High Days-to-Cover (> 10, > 1M short) ────────────────────────
        high_dtc = conn.execute(
            """SELECT symbol, issue_name, current_short, days_to_cover,
                      change_pct
               FROM short_interest
               WHERE settlement_date = ?
                 AND days_to_cover > ?
                 AND current_short > ?
                 AND days_to_cover IS NOT NULL
               ORDER BY days_to_cover DESC
               LIMIT 20""",
            (latest, THRESHOLDS["high_dtc"], THRESHOLDS["high_dtc_min_short"]),
        ).fetchall()
        result["high_dtc"] = [dict(r) for r in high_dtc]

        # ── Largest Short Positions (> 1M short) ──────────────────────────
        largest = conn.execute(
            """SELECT symbol, issue_name, current_short, days_to_cover,
                      change_pct, avg_daily_volume
               FROM short_interest
               WHERE settlement_date = ?
                 AND current_short > ?
               ORDER BY current_short DESC
               LIMIT 20""",
            (latest, THRESHOLDS["high_dtc_min_short"]),
        ).fetchall()
        result["largest"] = [dict(r) for r in largest]

        # ── Covering (>30% decrease, > 1M short) ─────────────────────────
        covering = conn.execute(
            """SELECT symbol, issue_name, current_short, previous_short,
                      change_pct, days_to_cover
               FROM short_interest
               WHERE settlement_date = ?
                 AND change_pct < ?
                 AND current_short > ?
               ORDER BY change_pct ASC
               LIMIT 20""",
            (latest, THRESHOLDS["covering_pct"], THRESHOLDS["covering_min_short"]),
        ).fetchall()
        result["covering"] = [dict(r) for r in covering]

        # ── Consensus (avg 5M+ across 3+ periods) ────────────────────────
        consensus = conn.execute(
            """SELECT symbol, COUNT(*) as periods,
                      AVG(current_short) as avg_short,
                      MAX(current_short) as peak_short,
                      MAX(settlement_date) as latest_date
               FROM short_interest
               GROUP BY symbol
               HAVING COUNT(*) >= ? AND AVG(current_short) >= ?
               ORDER BY avg_short DESC
               LIMIT 20""",
            (THRESHOLDS["consensus_min_periods"],
             THRESHOLDS["consensus_min_avg_short"]),
        ).fetchall()
        result["consensus"] = [dict(r) for r in consensus]

        # ── Summary ───────────────────────────────────────────────────────
        total_short = conn.execute(
            """SELECT SUM(current_short) as total, COUNT(*) as tickers
               FROM short_interest WHERE settlement_date = ?""",
            (latest,)).fetchone()
        result["summary"] = {
            "latest_settlement": latest,
            "total_short_interest": total_short["total"] if total_short["total"] else 0,
            "tracked_tickers": total_short["tickers"] if total_short["tickers"] else 0,
            "signal_counts": {
                "spikes": len(result["spikes"]),
                "high_dtc": len(result["high_dtc"]),
                "covering": len(result["covering"]),
                "largest": len(result["largest"]),
            },
        }

    return result


def analyze_ticker(db_path: str | None = None, ticker: str = "") -> dict:
    """Single-ticker short interest history + latest signals."""
    db = dbmod.init_db(db_path)
    ticker = ticker.upper()

    with dbmod.get_connection(db) as conn:
        # Latest data
        latest = conn.execute(
            "SELECT MAX(settlement_date) FROM short_interest"
        ).fetchone()[0]

        if not latest:
            return {"error": "No data", "ticker": ticker}

        # Full history for this ticker
        history = conn.execute(
            """SELECT settlement_date, current_short, previous_short,
                      change_pct, days_to_cover, avg_daily_volume
               FROM short_interest
               WHERE symbol = ?
               ORDER BY settlement_date DESC""",
            (ticker,),
        ).fetchall()

        if not history:
            return {"error": f"No short interest data for {ticker}", "ticker": ticker}

        return {
            "ticker": ticker,
            "latest": dict(history[0]),
            "history": [dict(r) for r in reversed(history)],
            "source": "FINRA bi-weekly (exchange-reported aggregate)",
        }


def main():
    ap = argparse.ArgumentParser(description="Analyze FINRA short interest signals")
    ap.add_argument("--db", default=None)
    ap.add_argument("--ticker", default=None, help="Single ticker analysis")
    args = ap.parse_args()

    if args.ticker:
        result = analyze_ticker(db_path=args.db, ticker=args.ticker)
    else:
        result = analyze(db_path=args.db)
    print(json.dumps(result, indent=2, default=str))


if __name__ == "__main__":
    main()
