"""Commodity scanner — fetches energy and precious metals via Yahoo Finance.

Uses CBOE and Yahoo Finance symbols (no API key):
- Crude Oil: CL=F
- Natural Gas: NG=F  
- Gold: GC=F
- Silver: SI=F
- Copper: HG=F

These are settlement prices for near-month futures contracts.
"""

import argparse
import datetime as dt
import json
from pathlib import Path

import httpx

# ── Yahoo Finance ticker mapping ─────────────────────────────────────────
TICKERS = {
    "crude_oil": "CL=F",
    "natural_gas": "NG=F",
    "gold": "GC=F",
    "silver": "SI=F",
    "copper": "HG=F",
}

YAHOO_CHART_URL = "https://query1.finance.yahoo.com/v8/finance/chart/{ticker}"
UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0 Safari/537.36"


def fetch(ticker: str, range_days: int = 30) -> list[dict]:
    """Fetch {date, price, change} for a single commodity."""
    url = YAHOO_CHART_URL.format(ticker=ticker)
    resp = httpx.get(url, params={"range": f"{range_days}d", "interval": "1d"},
                     headers={"User-Agent": UA}, timeout=30)
    resp.raise_for_status()
    data = resp.json()["chart"]["result"][0]

    timestamps = data["timestamp"]
    closes = data["indicators"]["quote"][0]["close"]

    rows = []
    for ts, close in zip(timestamps, closes):
        if close is None:
            continue
        date = dt.datetime.fromtimestamp(ts, tz=None).date().isoformat()
        rows.append({"date": date, "price": close})
    return rows


def ingest(db_path: str | None = None) -> dict:
    """Ingest all commodities and store in unified DB."""
    from akme_alpha import db as dbmod

    db_path = db_path or "akme_alpha/data/akme_alpha.db"
    dbmod.init_db(db_path)

    summary = {}
    with dbmod.get_connection(db_path) as conn:
        for name, ticker in TICKERS.items():
            rows = fetch(ticker)
            summary[name] = len(rows)

            for row in rows:
                conn.execute(
                    """INSERT INTO commodities (date, commodity, price, ticker)
                       VALUES (?, ?, ?, ?)
                       ON CONFLICT(date, commodity) DO UPDATE SET
                         price = excluded.price, ticker = excluded.ticker""",
                    (row["date"], name, row["price"], ticker),
                )
            conn.commit()

    summary["total"] = sum(summary.values())
    return summary


def main():
    ap = argparse.ArgumentParser(description="Ingest commodity prices")
    ap.add_argument("--db", default="akme_alpha/data/akme_alpha.db")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()
    result = ingest(db_path=args.db)
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()