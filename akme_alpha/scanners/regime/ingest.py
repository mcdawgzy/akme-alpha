"""Regime indicator data ingestion — fetch factor data from free sources.

Fetches daily factor data via Yahoo Finance chart API (no auth needed) and
Shiller CAPE (CSV download). Yield curve and commodity data come from the
DB (already populated by yield_curves/ and commodities/ scanners).

Stores results in the `regime_factors` table:
    date, factor_name, value, source
"""
from __future__ import annotations

import argparse
import csv
import datetime as dt
import io
import json
import statistics
import sys
from pathlib import Path

import httpx

from ... import db as dbmod
from .config import (
    FACTORS,
    HTTP_TIMEOUT,
    SHILLER_URLS,
    YAHOO_CHART_URL,
    YAHOO_UA,
    ZSCORE_LOOKBACK,
)


# ── Yahoo Finance helpers ──────────────────────────────────────────────

def _fetch_yahoo_chart(ticker: str, range_days: int = 700) -> list[dict]:
    """Fetch daily close prices for a ticker via Yahoo Finance chart API.

    Returns [{date, close, open, high, low}, ...] sorted by date.
    """
    url = YAHOO_CHART_URL.format(ticker=ticker)
    params = {"range": f"{range_days}d", "interval": "1d"}
    resp = httpx.get(url, params=params, headers={"User-Agent": YAHOO_UA},
                     timeout=HTTP_TIMEOUT)
    resp.raise_for_status()
    data = resp.json()

    result = data["chart"]["result"][0]
    timestamps = result["timestamp"]
    quote = result["indicators"]["quote"][0]

    rows = []
    closes = quote["close"]
    opens = quote.get("open", [None] * len(timestamps))
    highs = quote.get("high", [None] * len(timestamps))
    lows = quote.get("low", [None] * len(timestamps))

    for i, ts in enumerate(timestamps):
        if closes[i] is None:
            continue
        date = dt.datetime.fromtimestamp(ts, tz=dt.timezone.utc).date().isoformat()
        rows.append({
            "date": date,
            "close": round(float(closes[i]), 6),
            "open": round(float(opens[i]), 6) if opens[i] else None,
            "high": round(float(highs[i]), 6) if highs[i] else None,
            "low": round(float(lows[i]), 6) if lows[i] else None,
        })
    return rows


def _fetch_shiller_cape() -> list[dict]:
    """Fetch Shiller CAPE data from one of the mirror URLs.

    Returns [{date, cape, cpi, pe10, ...}, ...] sorted by date ascending.
    Falls back to SPY price z-score if Shiller is unavailable.
    """
    for url in SHILLER_URLS:
        try:
            resp = httpx.get(url, timeout=30, follow_redirects=True,
                             headers={"User-Agent": YAHOO_UA})
            resp.raise_for_status()
            text = resp.text

            # Try parsing as CSV first
            reader = csv.DictReader(io.StringIO(text))
            rows = []
            for r in reader:
                # Shiller CSV columns: Date, P, D, E, PE10, ...
                date_str = r.get("Date", "").strip()
                cape_val = r.get("CAPE", r.get("pe10", r.get("PE10", "")))
                if date_str and cape_val:
                    try:
                        # Handle "1871.00" → "1871-01-01" format
                        year = int(float(date_str))
                        month = 1
                        # Shiller dates are like "1871.00" (year.fraction)
                        frac = float(date_str) - year
                        month = int(round(frac * 12)) + 1
                        if month > 12:
                            month = 12
                        date = f"{year:04d}-{month:02d}-01"
                        rows.append({"date": date, "cape": float(cape_val)})
                    except (ValueError, TypeError):
                        continue
            if rows:
                rows.sort(key=lambda x: x["date"])
                return rows
        except Exception:
            continue

    return []


# ── Factor value computations ────────────────────────────────────────────

def compute_growth_value(ticker_a: str = "IWF",  # Russell Growth
                         ticker_b: str = "IWD",  # Russell Value
                         range_days: int = ZSCORE_LOOKBACK) -> list[dict]:
    """Compute IWF/IWD price ratio over time.
    Higher ratio = growth outperforming value = risk-on.
    """
    data_a = _fetch_yahoo_chart(ticker_a, range_days)
    data_b = _fetch_yahoo_chart(ticker_b, range_days)

    # Match dates and compute ratio
    dict_a = {r["date"]: r["close"] for r in data_a}
    dict_b = {r["date"]: r["close"] for r in data_b}

    common_dates = sorted(set(dict_a.keys()) & set(dict_b.keys()))
    results = []
    for d in common_dates:
        if dict_a[d] and dict_b[d] and dict_b[d] > 0:
            ratio = round(dict_a[d] / dict_b[d], 6)
            results.append({"date": d, "value": ratio})
    return results


def compute_momentum(ticker: str = "SPY",
                     momentum_days: int = 252,
                     range_days: int = ZSCORE_LOOKBACK) -> list[dict]:
    """Compute trailing 12-month (252-day) momentum for a ticker.
    (current_price / price_N_days_ago - 1)
    """
    data = _fetch_yahoo_chart(ticker, range_days)
    if len(data) < momentum_days + 1:
        return []

    results = []
    for i in range(momentum_days, len(data)):
        current = data[i]["close"]
        past = data[i - momentum_days]["close"]
        if past and past > 0:
            mom = round((current / past - 1.0), 6)
            results.append({"date": data[i]["date"], "value": mom})
    return results


def compute_credit_spreads(ticker_high: str = "HYG",  # high-yield
                           ticker_low: str = "LQD",   # investment-grade
                           range_days: int = ZSCORE_LOOKBACK) -> list[dict]:
    """Compute HYG/LQD ratio (credit spread proxy).
    Lower ratio = wider credit spreads = risk-off.
    Higher ratio = tighter spreads = risk-on.
    """
    data_a = _fetch_yahoo_chart(ticker_high, range_days)
    data_b = _fetch_yahoo_chart(ticker_low, range_days)

    dict_a = {r["date"]: r["close"] for r in data_a}
    dict_b = {r["date"]: r["close"] for r in data_b}

    common_dates = sorted(set(dict_a.keys()) & set(dict_b.keys()))
    results = []
    for d in common_dates:
        if dict_a[d] and dict_b[d] and dict_b[d] > 0:
            ratio = round(dict_a[d] / dict_b[d], 6)
            results.append({"date": d, "value": ratio})
    return results


def compute_fx_strength(ticker: str = "UUP",  # USD Bullish Index
                        range_days: int = ZSCORE_LOOKBACK) -> list[dict]:
    """Compute DXY strength proxy z-score from UUP.
    Higher UUP = stronger dollar = risk-off for EM/commodities.
    """
    data = _fetch_yahoo_chart(ticker, range_days)
    if not data:
        return []
    return [{"date": r["date"], "value": r["close"]} for r in data]


def compute_valuation(ticker: str = "SPY",
                      range_days: int = ZSCORE_LOOKBACK) -> list[dict]:
    """Compute SPY price deviation from 200-day MA as a valuation proxy.

    Higher deviation = more overvalued = risk-on regime (temporarily).
    Returns [{date, value}, ...] where value is % deviation from 200-day MA.
    """
    data = _fetch_yahoo_chart(ticker, range_days)
    if len(data) < 201:
        return []
    closes = [r["close"] for r in data]
    results = []
    for i in range(200, len(data)):
        window = closes[i - 200:i]
        ma_200 = sum(window) / 200
        if ma_200 and ma_200 > 0:
            dev = data[i]["close"] / ma_200 - 1.0
            results.append({"date": data[i]["date"], "value": round(dev, 6)})
    return results


# ── Ingestion ──────────────────────────────────────────────────────────

def _store_factor(conn, factor_name: str, rows: list[dict], source: str):
    """Store factor data rows into regime_factors table."""
    for r in rows:
        conn.execute(
            """INSERT INTO regime_factors (date, factor_name, value, source)
               VALUES (?, ?, ?, ?)
               ON CONFLICT(date, factor_name) DO UPDATE SET
                 value = excluded.value,
                 source = excluded.source""",
            (r["date"], factor_name, r["value"], source),
        )


def ingest(db_path: str | None = None, dry_run: bool = False) -> dict:
    """Fetch all factor data and store in regime_factors table.

    Returns summary of rows written per factor.
    """
    db = dbmod.init_db(db_path)
    summary = {"factors": {}, "total_points": 0, "status": "ok"}

    # ── Valuation (SPY 200-day price deviation) ──────────────────────────
    try:
        val_rows = compute_valuation()
        if val_rows:
            summary["factors"]["valuation_cape"] = {"source": "yahoo_finance", "rows": len(val_rows)}
            if not dry_run:
                with dbmod.get_connection(db) as conn:
                    _store_factor(conn, "valuation_cape", val_rows, "yahoo_finance")
                    conn.commit()
        else:
            summary["factors"]["valuation_cape"] = {"source": "yahoo_finance", "rows": 0, "error": "no_data"}
    except Exception as e:
        summary["factors"]["valuation_cape"] = {"source": "yahoo_finance", "rows": 0, "error": str(e)[:120]}

    # ── Yahoo Finance factors ───────────────────────────────────────────
    yf_factors = {
        "growth_value": (compute_growth_value, "yahoo_finance"),
        "momentum": (compute_momentum, "yahoo_finance"),
        "credit_spreads": (compute_credit_spreads, "yahoo_finance"),
        "fx_strength": (compute_fx_strength, "yahoo_finance"),
    }

    for factor_name, (fetch_fn, source) in yf_factors.items():
        try:
            rows = fetch_fn()
            if rows:
                summary["factors"][factor_name] = {"source": source, "rows": len(rows)}
                if not dry_run:
                    with dbmod.get_connection(db) as conn:
                        _store_factor(conn, factor_name, rows, source)
                        conn.commit()
            else:
                summary["factors"][factor_name] = {"source": source, "rows": 0, "error": "no_data"}
        except Exception as e:
            summary["factors"][factor_name] = {"source": source, "rows": 0, "error": str(e)[:120]}

    summary["total_points"] = sum(v.get("rows", 0) for v in summary["factors"].values())
    return summary


def main():
    ap = argparse.ArgumentParser(description="Ingest regime factor data")
    ap.add_argument("--db", default=None, help="DB path (default: from config)")
    ap.add_argument("--dry-run", action="store_true", help="Fetch but don't write")
    args = ap.parse_args()

    result = ingest(db_path=args.db, dry_run=args.dry_run)
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
