"""Economic indicators scanner — CPI, PPI, Fed funds, unemployment, GDP.

Uses FRED API (free registration at fred.stlouisfed.org/docs/api/fred/).
Set FRED_API_KEY environment variable to enable this scanner.

Series tracked:
- CPIAUCSL — Consumer Price Index (All Urban Consumers)
- PPIACO — Producer Price Index (Commodities)
- FEDFUNDS — Effective Federal Funds Rate
- GDPC1 — Real Gross Domestic Product
- UNRATE — Civilian Unemployment Rate

Data frequency: Monthly (most series) or daily (rates).
"""

import argparse
import json
import os
from datetime import date

import httpx

# ── FRED series definitions ───────────────────────────────────────────────
SERIES = {
    "cpi": {
        "id": "CPIAUCSL",
        "description": "Consumer Price Index — All items (seasonally adjusted)",
        "unit": "index",
        "frequency": "monthly",
    },
    "ppi": {
        "id": "PPIACO",
        "description": "Producer Price Index — Commodities (seasonally adjusted)",
        "unit": "index",
        "frequency": "monthly",
    },
    "fed_funds": {
        "id": "FEDFUNDS",
        "description": "Effective Federal Funds Rate",
        "unit": "percent",
        "frequency": "daily",
    },
    "gdp_real": {
        "id": "GDPC1",
        "description": "Real Gross Domestic Product ( chained dollars)",
        "unit": "billions_usd",
        "frequency": "quarterly",
    },
    "unemployment": {
        "id": "UNRATE",
        "description": "Civilian Unemployment Rate",
        "unit": "percent",
        "frequency": "monthly",
    },
    "treasury_curves": {
        "ids": ["DGS3MO", "DGS1", "DGS2", "DGS5", "DGS10", "DGS30"],
        "description": "Daily Treasury Yield Curve",
        "unit": "percent",
        "frequency": "daily",
    },
}


def fetch_fred_observations(series_id: str, api_key: str, limit: int = 1000) -> list[dict]:
    """Fetch observations from FRED API v2. Returns [{date, value}, ...]."""
    url = "https://api.stlouisfed.org/fred/series/observations"
    params = {
        "series_id": series_id,
        "api_key": api_key,
        "file_type": "json",
        "limit": limit,
        "sort_order": "asc",
    }
    resp = httpx.get(url, params=params, timeout=30)
    resp.raise_for_status()
    data = resp.json()

    if "error" in data:
        raise ValueError(f"FRED API error: {data['error']}")

    rows = []
    for obs in data.get("observations", []):
        val = obs.get("value")
        if val and val != ".":
            rows.append({"date": obs["date"], "value": float(val)})
    return rows


def ingest(db_path: str, api_key: str | None = None) -> dict:
    """Fetch all FRED series and upsert into DB. Returns summary dict."""
    from akme_alpha import db as dbmod

    if not api_key:
        # Check env for FRED_API_KEY
        api_key = os.environ.get("FRED_API_KEY")
        if not api_key:
            print("FRED_API_KEY not set — skipping economic ingestion")
            return {"skipped": "no API key", "note": "Set FRED_API_KEY env var"}

    dbmod.init_db(db_path)
    summary = {"series": {}, "total_points": 0}

    with dbmod.get_connection(db_path) as conn:
        for name, meta in SERIES.items():
            if name == "treasury_curves":
                # Multi-series lookup for yield curves
                for ts_id in meta["ids"]:
                    try:
                        rows = fetch_fred_observations(ts_id, api_key, limit=1000)
                        for r in rows:
                            conn.execute(
                                """INSERT INTO yield_curves (date, maturity, yield_pct, source)
                                   VALUES (?, ?, ?, 'fred')
                                   ON CONFLICT(date, maturity) DO UPDATE SET
                                     yield_pct = excluded.yield_pct""",
                                (r["date"], ts_id.replace("DGS", "").lower().replace("MO", "3m"), r["value"]),
                            )
                        summary["series"][ts_id] = len(rows)
                        summary["total_points"] += len(rows)
                    except Exception as e:
                        print(f"  {ts_id}: {e}")
            else:
                try:
                    rows = fetch_fred_observations(meta["id"], api_key, limit=1000)
                    for r in rows:
                        conn.execute(
                            f"""INSERT INTO economic_indicators
                                   (date, indicator, value, unit, frequency)
                                   VALUES (?, ?, ?, ?, ?)
                                   ON CONFLICT(date, indicator) DO UPDATE SET
                                     value = excluded.value""",
                            (r["date"], name, r["value"], meta["unit"], meta["frequency"]),
                        )
                    summary["series"][name] = len(rows)
                    summary["total_points"] += len(rows)
                except Exception as e:
                    print(f"  {name}: {e}")

        conn.commit()

    return summary


def main():
    ap = argparse.ArgumentParser(description="Fetch economic indicators from FRED")
    ap.add_argument("--db", default="akme_alpha/data/akme_alpha.db")
    ap.add_argument("--api-key", default=None, help="FRED API key (or set FRED_API_KEY env)")
    args = ap.parse_args()
    result = ingest(args.db, args.api_key)
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()