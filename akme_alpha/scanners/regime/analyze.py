"""Regime indicator analysis — compute z-scores, composite verdict, and narrative.

Pulls factor data from the unified DB (regime_factors + yield_curves + commodities)
and existing scanner outputs, normalises each factor to a z-score vs a 2-year
lookback, then combines into a weighted composite score.

Verdict mapping:
  composite >  +0.5  → Expansion  (risk-on, growth above trend)
  0 to +0.5     → Recovery   (risk-on, emerging from trough)
  -0.5 to 0     → Slowdown   (risk-off, growth decelerating)
  composite <  -0.5  → Recession  (severe stress, contraction)
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import statistics
import sys
from pathlib import Path

from ... import db as dbmod
from .config import FACTORS, REGIME_COLORS, REGIME_LOWER, REGIME_UPPER, ZSCORE_LOOKBACK


# ── Z-score utilities ────────────────────────────────────────────────────

def _zscore(current: float, history: list[float]) -> float | None:
    """Z-score of current vs historical mean/stdev.

    Follows the same pattern as yield_curves/analyze.py.
    Returns None if insufficient history (< 30 points).
    """
    # Only use completed prior observations (exclude current date if present)
    prior = [h for h in history if h is not None and h != current]
    if len(prior) < 30:
        # Fallback: use all history including current
        full = [h for h in history if h is not None]
        if len(full) < 30:
            return None
        prior = full
    mean = statistics.mean(prior)
    stdev = statistics.stdev(prior)
    if stdev == 0:
        return 0.0
    return round((current - mean) / stdev, 3)


def _get_factor_history(conn, factor_name: str, days: int = ZSCORE_LOOKBACK) -> list[tuple[str, float]]:
    """Return [(date, value), ...] from regime_factors for a factor, ascending by date."""
    rows = conn.execute(
        """SELECT date, value FROM regime_factors
           WHERE factor_name = ? AND value IS NOT NULL
           ORDER BY date ASC LIMIT ?""",
        (factor_name, days),
    ).fetchall()
    return [(r["date"], r["value"]) for r in rows]


def _get_latest_yield_curve(conn) -> dict | None:
    """Pull the latest yield curve regime from DB (computed by yield_curves scanner)."""
    row = conn.execute(
        """SELECT date, spread_3m10, zscore_3m10, regime, classification
           FROM yield_curve_regime ORDER BY date DESC LIMIT 1""",
    ).fetchone()
    if not row:
        return None
    return dict(row)


def _get_latest_commodity_index(conn) -> dict | None:
    """Pull the latest commodity prices from DB (computed by commodities scanner).

    We compute a simple equal-weighted commodity index from gold + crude_oil + copper.
    """
    rows = conn.execute(
        """SELECT date, commodity, price FROM commodities
           WHERE date = (SELECT MAX(date) FROM commodities)
           AND commodity IN ('gold', 'crude_oil', 'copper')""",
    ).fetchall()
    if not rows:
        return None
    total = sum(r["price"] for r in rows if r["price"])
    n = len([r for r in rows if r["price"]])
    return {"date": rows[0]["date"], "index": total / n if n else 0, "components": [dict(r) for r in rows]}


def _get_commodity_history(conn, days: int = ZSCORE_LOOKBACK) -> list[tuple[str, float]]:
    """Return [(date, equal-weighted commodity index), ...] over history."""
    # We compute a daily equal-weighted index of gold + crude_oil + copper
    rows = conn.execute(
        f"""SELECT date, AVG(price) as idx FROM commodities
            WHERE commodity IN ('gold', 'crude_oil', 'copper')
            AND date >= date('now', '-{days} days')
            GROUP BY date
            ORDER BY date ASC""",
    ).fetchall()
    return [(r["date"], r["idx"]) for r in rows if r["idx"]]


# ── Regime classification ────────────────────────────────────────────────

def classify_regime(composite: float) -> str:
    """Map composite z-score to one of four regime states."""
    if composite > REGIME_UPPER:       # > +0.5
        return "Expansion"
    elif composite >= 0:               # 0 to +0.5
        return "Recovery"
    elif composite >= REGIME_LOWER:    # -0.5 to 0
        return "Slowdown"
    else:                              # < -0.5
        return "Recession"


# ── Narrative generation ─────────────────────────────────────────────────

_IMPLICATIONS = {
    "Expansion": "Maintain growth-oriented positioning. Monitor for overcrowding signals.",
    "Recovery": "Early-cycle traits — quality growth and cyclicals favored. Valuation headroom remains.",
    "Slowdown": "Defensive rotation likely. Increase cash and quality duration exposure.",
    "Recession": "Severe risk-off environment — reduce equity exposure, favor cash and defensive sectors.",
}


def _generate_narrative(verdict: str, composite: float,
                        factor_zscores: dict, factors_ranked: list) -> str:
    """Generate a one-sentence narrative for traders.

    Factors ranked by |z-score| descending. Top 3 drive the narrative.
    """
    top3 = factors_ranked[:3]
    driver_names = [f["name"] for f in top3]
    driver_str = ", ".join(
        f"{f['name']} ({f['zscore']:+.1f}σ)" for f in top3
    )

    # Determine if this is a regime shift
    prefix = "Market regime shifts to" if any(f.get("shift") for f in factors_ranked[:1]) else "Market regime holds at"

    implications = _IMPLICATIONS.get(verdict, "Monitor positioning carefully.")

    narrative = (
        f"{prefix} {verdict} (composite: {composite:+.2f}). "
        f"Drivers: {driver_str}. "
        f"{implications}"
    )
    return narrative


# ── Core analyze ─────────────────────────────────────────────────────────

def analyze(db_path: str | None = None, target_date: str | None = None) -> dict:
    """Compute the full regime for the latest available data.

    Returns: {date, composite, verdict, regime_changed,
              factor_z_scores, factor_raw, narrative, last_shift_date,
              source_health, top_factors}
    """
    db = dbmod.init_db(db_path)

    with dbmod.get_connection(db) as conn:
        # Determine analysis date (latest factor data available)
        latest_factor_date = conn.execute(
            "SELECT MAX(date) FROM regime_factors"
        ).fetchone()[0]
        latest_yld_date = conn.execute(
            "SELECT MAX(date) FROM yield_curves"
        ).fetchone()[0]
        latest_comm_date = conn.execute(
            "SELECT MAX(date) FROM commodities"
        ).fetchone()[0]

        dates = [d for d in [latest_factor_date, latest_yld_date, latest_comm_date] if d]
        if not dates:
            return {"error": "No data ingested. Run regime ingest first.", "status": "no_data"}

        analysis_date = max(dates)  # most recent data available
        if target_date:
            analysis_date = target_date

        # ── Compute z-score for each factor ────────────────────────────────
        factor_zscores: dict[str, float | None] = {}
        factor_raw: dict[str, float | None] = {}
        source_health: dict[str, str] = {}
        factors_ranked: list[dict] = []

        for factor_name, cfg in FACTORS.items():
            weight = cfg["weight"]
            if weight == 0:
                source_health[factor_name] = "disabled_phase1b"
                factor_zscores[factor_name] = None
                factor_raw[factor_name] = None
                continue

            source = cfg["source"]
            zscore = None
            raw_value = None

            if source == "yahoo_finance" or source == "shiller":
                # Read from regime_factors table
                history = _get_factor_history(conn, factor_name)
                if history:
                    latest = history[-1]
                    if latest[0] == analysis_date or abs(
                        (dt.date.fromisoformat(latest[0]) - dt.date.fromisoformat(analysis_date)).days
                    ) <= 3:
                        raw_value = latest[1]
                        prior_history = [h[1] for h in history[:-1]]
                        zscore = _zscore(raw_value, prior_history)

            elif source == "db":
                if factor_name == "yield_curve":
                    yc = _get_latest_yield_curve(conn)
                    if yc:
                        raw_value = yc["spread_3m10"]
                        zscore = yc["zscore_3m10"]
                elif factor_name == "commodities":
                    comm = _get_latest_commodity_index(conn)
                    if comm:
                        raw_value = comm["index"]
                        hist = _get_commodity_history(conn)
                        if hist:
                            prior = [h[1] for h in hist[:-1]]
                            zscore = _zscore(raw_value, prior)

            factor_zscores[factor_name] = zscore
            factor_raw[factor_name] = raw_value
            source_health[factor_name] = "ok" if zscore is not None else "no_data"

            if zscore is not None:
                factors_ranked.append({
                    "name": factor_name,
                    "zscore": zscore,
                    "weight": weight,
                    "direction": cfg["direction"],
                    "abs_zscore": abs(zscore),
                })

        # Sort factors by |z-score| descending
        factors_ranked.sort(key=lambda x: x["abs_zscore"], reverse=True)

        # ── Compute weighted composite ───────────────────────────────────────
        total_weight = 0.0
        weighted_sum = 0.0
        for factor_name, cfg in FACTORS.items():
            zscore = factor_zscores[factor_name]
            if zscore is None:
                continue
            weight = cfg["weight"]
            sign = 1.0 if cfg["direction"] == "positive" else -1.0
            weighted_sum += zscore * sign * weight
            total_weight += weight

        if total_weight == 0:
            return {"error": "No factors available for scoring", "date": analysis_date,
                    "status": "no_factors"}

        # Re-normalise weights for missing factors
        composite = round(weighted_sum / total_weight, 3)
        verdict = classify_regime(composite)

        # ── Check if regime changed from previous day ────────────────────────
        prev_row = conn.execute(
            """SELECT verdict FROM regime_daily
               WHERE date < ? ORDER BY date DESC LIMIT 1""",
            (analysis_date,),
        ).fetchone()
        prev_verdict = prev_row["verdict"] if prev_row else None
        regime_changed = prev_verdict is not None and prev_verdict != verdict

        # ── Find last shift date ─────────────────────────────────────────────
        last_shift_rows = conn.execute(
            """SELECT date, verdict FROM (
                   SELECT date, verdict,
                          LAG(verdict) OVER (ORDER BY date) as prev_verdict
                   FROM regime_daily
               ) WHERE verdict != prev_verdict AND prev_verdict IS NOT NULL
               ORDER BY date DESC LIMIT 1""",
        ).fetchone()
        last_shift_date = last_shift_rows["date"] if last_shift_rows else analysis_date

        # ── Generate narrative ───────────────────────────────────────────────
        for f in factors_ranked:
            f["shift"] = regime_changed

        narrative = _generate_narrative(verdict, composite, factor_zscores, factors_ranked)

        # ── Build result dict ────────────────────────────────────────────────
        result = {
            "date": analysis_date,
            "composite_score": composite,
            "verdict": verdict,
            "regime_changed": regime_changed,
            "factor_z_scores": {k: v for k, v in factor_zscores.items() if v is not None},
            "factor_raw": {k: v for k, v in factor_raw.items() if v is not None},
            "top_factors": factors_ranked[:3],
            "narrative": narrative,
            "last_shift_date": last_shift_date,
            "source_health": source_health,
            "weight_normalisation": round(total_weight, 4),
        }

        # ── Store in regime_daily ────────────────────────────────────────────
        conn.execute(
            """INSERT INTO regime_daily
               (date, composite_score, verdict, regime_changed,
                factor_z_scores, narrative, last_shift_date, source_health)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?)
               ON CONFLICT(date) DO UPDATE SET
                 composite_score  = excluded.composite_score,
                 verdict           = excluded.verdict,
                 regime_changed    = excluded.regime_changed,
                 factor_z_scores   = excluded.factor_z_scores,
                 narrative         = excluded.narrative,
                 last_shift_date   = excluded.last_shift_date,
                 source_health     = excluded.source_health,
                 created_at        = CURRENT_TIMESTAMP""",
            (
                analysis_date, composite, verdict,
                1 if regime_changed else 0,
                json.dumps(result["factor_z_scores"]),
                narrative, last_shift_date,
                json.dumps(source_health),
            ),
        )
        conn.commit()

        return result


def main():
    ap = argparse.ArgumentParser(description="Analyze market regime")
    # --db must come before subcommand (matches project convention)
    ap.add_argument("--db", default=None, help="DB path")
    ap.add_argument("--date", default=None, help="Analysis date (default: latest available)")
    args = ap.parse_args()

    result = analyze(db_path=args.db, target_date=args.date)
    print(json.dumps(result, indent=2, default=str))


if __name__ == "__main__":
    main()
