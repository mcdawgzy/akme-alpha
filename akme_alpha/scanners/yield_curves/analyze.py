"""Yield curve regime analysis: compute spreads, classify regimes, generate
digestible summaries for the /yield-curve-regime endpoint.

A yield curve regime is derived from the 3-month / 10-year spread — the
single best-performing recession predictor (better than 2s10s in several
post-mortem studies). We also track 5y-10y and 3m-30y slopes for context.
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import statistics

from .config import REGIME_THRESHOLDS, ZSCORE_LOOKBACK, MATURITY_TICKERS
from ... import db as dbmod


def _latest_curve(conn) -> dict[str, float | None]:
    """Return the most recent available yield per maturity."""
    maturities = list(MATURITY_TICKERS.keys())
    result = {}
    for m in maturities:
        row = conn.execute(
            "SELECT yield_pct FROM yield_curves WHERE maturity = ? "
            "ORDER BY date DESC LIMIT 1",
            (m,),
        ).fetchone()
        result[m] = row["yield_pct"] if row else None
    return result


def _latest_regime_date(conn) -> str | None:
    row = conn.execute(
        "SELECT date FROM yield_curve_regime ORDER BY date DESC LIMIT 1"
    ).fetchone()
    return row["date"] if row else None


def _historical_spread(conn, spread_days: int | None = None) -> list[float]:
    """Return recent 3m10s spreads (bps) sorted by date ascending."""
    limit = spread_days if spread_days else ZSCORE_LOOKBACK
    q = (
        "SELECT spread_3m10 FROM yield_curve_regime "
        "WHERE spread_3m10 IS NOT NULL "
        f"ORDER BY date DESC LIMIT {limit}"
    )
    spreads = [r["spread_3m10"] for r in conn.execute(q).fetchall()]
    spreads.reverse()  # ascending order for mean/std
    return spreads


def _zscore(current: float, history: list[float]) -> float | None:
    if len(history) < 30:
        return None
    mean = statistics.mean(history)
    stdev = statistics.stdev(history)
    if stdev == 0:
        return 0.0
    return round((current - mean) / stdev, 3)


def classify(spread_3m10: float, zscore: float | None) -> tuple[str, str]:
    """Return (regime, classification) from the 3m10s spread.

    regime:           STEEP / NORMAL / FLAT / INVERTED
    classification:   risk_on / neutral / risk_off / recession_warning
    """
    spread = spread_3m10  # in basis points

    if spread <= REGIME_THRESHOLDS["inverted"]:
        return "INVERTED", "recession_warning"

    if abs(spread) < REGIME_THRESHOLDS["flat"]:
        return "FLAT", "neutral"

    steep = REGIME_THRESHOLDS["steep"]
    if spread > steep and (zscore is None or zscore > 1.0):
        return "STEEP", "risk_on"

    if spread > REGIME_THRESHOLDS["normal_risk_on"]:
        return "NORMAL", "risk_on"

    return "NORMAL", "neutral"


def _narrative(regime: str, classification: str, spreads: dict, zscore: float | None) -> str:
    """One-sentence digestible summary for traders."""
    s3m10 = spreads.get("spread_3m10")
    y10 = spreads.get("y10_level")

    if regime == "INVERTED":
        return (
            f"Yield curve INVERTED (3m10s = {s3m10:+.0f}bp). "
            f"Historical recession signal — watch for risk-off rotation."
        )
    if regime == "STEEP":
        return (
            f"Curve STEEP (3m10s = {s3m10:+.0f}bp, z={zscore}). "
            f"Bull-steepening — growth optimism priced in."
        )
    if regime == "FLAT":
        return (
            f"Curve FLAT (3m10s = {s3m10:+.0f}bp). "
            f"Awaiting directional catalyst; low term-premium environment."
        )
    return (
        f"Normal upward slope (3m10s = {s3m10:+.0f}bp, 10y={y10}%). "
        f"Risk-on regime; term premium adequate."
    )


def analyze(db_path: str | None = None, target_date: str | None = None) -> dict:
    """Compute and store the yield curve regime for a given date.

    If target_date is None, uses the latest date with curve data.
    Returns the stored regime record as a dict.
    """
    db = dbmod.init_db(db_path)

    with dbmod.get_connection(db) as conn:
        curve = _latest_curve(conn)

        # Determine the analysis date
        if target_date:
            analysis_date = target_date
        else:
            latest_curve_date = conn.execute(
                "SELECT MAX(date) FROM yield_curves"
            ).fetchone()[0]
            analysis_date = latest_curve_date

        # Build the curve for this date
        date_curve = {}
        for m in MATURITY_TICKERS:
            row = conn.execute(
                "SELECT yield_pct FROM yield_curves WHERE date = ? AND maturity = ?",
                (analysis_date, m),
            ).fetchone()
            if row:
                date_curve[m] = row["yield_pct"]

        if "3m" not in date_curve or "10y" not in date_curve:
            return {"error": f"Insufficient curve data for {analysis_date}",
                    "date": analysis_date}

        y3m = date_curve["3m"]
        y5y = date_curve.get("5y")
        y10 = date_curve["10y"]
        y30 = date_curve.get("30y")

        # Spreads in basis points — convention: long minus short
        # 3m10s = 10y − 3m  (negative → inverted)
        spread_3m10 = round((y10 - y3m) * 100, 2)
        spread_5y10 = round((y10 - y5y) * 100, 2) if y5y is not None else None
        spread_3m30 = round((y30 - y3m) * 100, 2) if y30 is not None else None

        # Z-score of 3m10s spread vs 2-year history
        history = _historical_spread(conn)
        current_idx = len(history)
        # Exclude today (if already computed) when computing z-score
        prior_history = history[:-1] if current_idx else history
        zscore = _zscore(spread_3m10, prior_history)

        # 6-month change in 10y level
        half_year_ago = (dt.date.fromisoformat(analysis_date) - dt.timedelta(days=180)).isoformat()
        old_10y = conn.execute(
            "SELECT yield_pct FROM yield_curves WHERE maturity='10y' AND date <= ? ORDER BY date DESC LIMIT 1",
            (half_year_ago,),
        ).fetchone()
        y10_6m_change = None
        if old_10y:
            y10_6m_change = round((y10 - old_10y["yield_pct"]) * 100, 2)

        regime, classification = classify(spread_3m10, zscore)

        notes = _narrative(
            regime, classification,
            {"spread_3m10": spread_3m10, "y10_level": y10},
            zscore,
        )

        # Store
        conn.execute(
            """INSERT INTO yield_curve_regime
               (date, spread_3m10, spread_5y10, spread_3m30, regime,
                classification, zscore_3m10, y10_level_6m, notes)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
               ON CONFLICT(date) DO UPDATE SET
                 spread_3m10   = excluded.spread_3m10,
                 spread_5y10    = excluded.spread_5y10,
                 spread_3m30     = excluded.spread_3m30,
                 regime          = excluded.regime,
                 classification   = excluded.classification,
                 zscore_3m10     = excluded.zscore_3m10,
                 y10_level_6m    = excluded.y10_level_6m,
                 notes            = excluded.notes,
                 created_at       = CURRENT_TIMESTAMP""",
            (analysis_date, spread_3m10, spread_5y10, spread_3m30,
             regime, classification, zscore, y10_6m_change, notes),
        )
        conn.commit()

        return {
            "date": analysis_date,
            "curve": {k: round(v, 4) for k, v in date_curve.items()},
            "spreads": {
                "spread_3m10": spread_3m10,
                "spread_5y10": spread_5y10,
                "spread_3m30": spread_3m30,
            },
            "regime": regime,
            "classification": classification,
            "zscore_3m10": zscore,
            "y10_level_6m_change": y10_6m_change,
            "notes": notes,
        }


def main():
    ap = argparse.ArgumentParser(description="Analyze yield curve regime")
    ap.add_argument("--db", default=None)
    ap.add_argument("--date", default=None,
                    help="Analysis date (default: latest available)")
    ap.add_argument("--backfill", action="store_true",
                    help="Re-run regime for all dates with curve data")
    args = ap.parse_args()

    db = dbmod.init_db(args.db)

    if args.backfill:
        with dbmod.get_connection(db) as conn:
            dates = [r[0] for r in conn.execute(
                "SELECT DISTINCT date FROM yield_curves ORDER BY date"
            ).fetchall()]
        total = 0
        for d in dates:
            result = analyze(db_path=db, target_date=d)
            if "error" not in result:
                total += 1
        print(f"Analyzed {total}/{len(dates)} dates")
    else:
        result = analyze(db_path=db, target_date=args.date)
        print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
