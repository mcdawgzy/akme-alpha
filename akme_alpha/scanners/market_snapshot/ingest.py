"""Market Snapshot data ingestion — fetch daily prices from Yahoo Finance.

Fetches the last N trading days for all 31 tickers across 7 sections.
Treasury yields are returned as yield_pct (like the yield_curves scanner);
equity/FX/commodity/crypto tickers return price data.

Returns a list of per-ticker daily records for the analyze step.
"""
from __future__ import annotations

import argparse
import datetime as dt
import json

import httpx

from .config import (
    FETCH_RANGE_DAYS,
    HTTP_TIMEOUT,
    SECTIONS,
    YAHOO_CHART_URL,
    YAHOO_UA,
    YIELD_TICKERS,
)


def _fetch_yahoo(ticker: str) -> list[dict]:
    """Return [{date, close}, ...] sorted ascending for a single Yahoo ticker.

    For yield tickers (^IRX, ^FVX, etc.) the "close" is the yield percentage.
    """
    url = YAHOO_CHART_URL.format(ticker=ticker)
    params = {"range": f"{FETCH_RANGE_DAYS}d", "interval": "1d"}
    headers = {"User-Agent": YAHOO_UA}
    resp = httpx.get(url, params=params, headers=headers, timeout=HTTP_TIMEOUT)
    resp.raise_for_status()
    data = resp.json()

    result = data["chart"]["result"][0]
    timestamps = result["timestamp"]
    closes = result["indicators"]["quote"][0]["close"]

    rows = []
    for ts, val in zip(timestamps, closes):
        if val is None:
            continue
        date = dt.datetime.fromtimestamp(ts, tz=dt.timezone.utc).date().isoformat()
        rows.append({"date": date, "close": round(float(val), 6)})
    return rows


def ingest(db_path: str | None = None, dry_run: bool = False) -> dict:
    """Fetch latest data for all snapshot tickers and upsert into the DB.

    Returns summary: {section: count, total: N, errors: [...]}.
    """
    from ... import db as dbmod

    db = dbmod.init_db(db_path)
    summary = {"sections": {}, "total": 0, "errors": []}

    for section, tickers in SECTIONS.items():
        section_count = 0
        for ticker in tickers:
            try:
                rows = _fetch_yahoo(ticker)
                if not rows:
                    summary["errors"].append(f"{ticker}: no data")
                    continue

                is_yield = ticker in YIELD_TICKERS
                if is_yield:
                    price = None
                    yield_pct = round(rows[-1]["close"], 4)
                    prev_yield = rows[-2]["close"] if len(rows) >= 2 else None
                    change_pct = None
                    change_bps = round((yield_pct - prev_yield) * 100, 1) if prev_yield else None
                else:
                    price = round(rows[-1]["close"], 4)
                    yield_pct = None
                    change_pct = round(
                        (rows[-1]["close"] - rows[-2]["close"]) / rows[-2]["close"] * 100, 3
                    ) if len(rows) >= 2 and rows[-2]["close"] else None
                    change_bps = None

                five_day_pct = None
                if len(rows) >= 2:
                    five_day_pct = round(
                        (rows[-1]["close"] - rows[-6]["close"]) / rows[-6]["close"] * 100, 3
                    ) if len(rows) >= 6 and rows[-6]["close"] else None

                if not dry_run:
                    with dbmod.get_connection(db) as conn:
                        conn.execute(
                            """INSERT INTO market_snapshot
                               (date, ticker, section, price, yield_pct,
                                change_pct, change_bps, change_5d_pct, is_yield)
                               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                               ON CONFLICT(date, ticker) DO UPDATE SET
                                 price         = excluded.price,
                                 yield_pct      = excluded.yield_pct,
                                 change_pct     = excluded.change_pct,
                                 change_bps     = excluded.change_bps,
                                 change_5d_pct  = excluded.change_5d_pct,
                                 ingested_at     = CURRENT_TIMESTAMP""",
                            (rows[-1]["date"], ticker, section,
                             price, yield_pct, change_pct, change_bps,
                             five_day_pct, 1 if is_yield else 0),
                        )
                        conn.commit()
                section_count += 1
                summary["total"] += 1
            except Exception as e:
                summary["errors"].append(f"{ticker}: {str(e)[:120]}")
        summary["sections"][section] = section_count

    return summary


def main():
    ap = argparse.ArgumentParser(description="Ingest market snapshot data")
    ap.add_argument("--db", default=None, help="DB path")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()
    result = ingest(db_path=args.db, dry_run=args.dry_run)
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
