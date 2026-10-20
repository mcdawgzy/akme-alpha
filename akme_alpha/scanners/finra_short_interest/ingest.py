"""Ingest FINRA short interest data from the bi-weekly CSV feed.

Usage:
    python -m scanners.finra_short_interest.ingest --db C:/Users/cho_i/akme_alpha/data/akme_alpha.db

Data source: https://cdn.finra.org/equity/otcmarket/biweekly/shrt{YYYYMMDD}.csv
Pipe-delimited, no API key required. Bi-weekly (15th + last business day).

Publication is ~7 business days after settlement. This scanner tries the
expected settlement date ± 1 day if the primary date 404s.
"""
from __future__ import annotations

import argparse
import csv
import datetime as dt
import io
import json
import re

import httpx

from ... import db as dbmod
from .config import FINRA_CSV_URL, FINRA_USER_AGENT, THRESHOLDS, WATCHLIST


# ── Settlement date calendar ───────────────────────────────────────────────

def _is_business_day(d: dt.date) -> bool:
    """Monday=0 ... Sunday=6; Saturday = 5, Sunday = 6."""
    return d.weekday() < 5


def _last_business_day(year: int, month: int) -> dt.date:
    """Last business day of the month (adjust for weekends)."""
    # Start from last day of month
    if month == 12:
        next_month = dt.date(year + 1, 1, 1)
    else:
        next_month = dt.date(year, month + 1, 1)
    last = next_month - dt.timedelta(days=1)
    while not _is_business_day(last):
        last -= dt.timedelta(days=1)
    return last


def settlement_dates(year: int, quarter: int) -> list[str]:
    """Return the two settlement dates (as YYYYMMDD strings) for a quarter.

    FINRA settlement dates: 15th of month (adjusted to prior biz day if weekend)
    + last business day of the month.
    """
    months = {
        1: [1, 3], 2: [4, 6], 3: [7, 9], 4: [10, 12],
    }[quarter]
    dates = []
    for m in months:
        d = dt.date(year, m, 15)
        if not _is_business_day(d):
            d = d - dt.timedelta(days=d.weekday() - 4 if d.weekday() >= 5 else 0)
            # If Saturday (5), go to Friday; if Sunday (6), go to Friday
            while not _is_business_day(d):
                d -= dt.timedelta(days=1)
        dates.append(d)
        dates.append(_last_business_day(year, m))
    # Deduplicate (15th and last of some months may coincide)
    seen = set()
    result = []
    for d in dates:
        if d not in seen:
            seen.add(d)
            result.append(d)
    return [d.strftime("%Y%m%d") for d in result]


def _next_settlement_candidates(target: dt.date) -> list[str]:
    """Generate candidate settlement date strings around a target date.

    Publication lags settlement by ~7 business days, so if we're checking
    on date X, the most recent published data is from ~7 business days ago.
    """
    candidates = []
    for offset in range(0, 15):
        d = target - dt.timedelta(days=offset)
        year, quarter = d.year, (d.month - 1) // 3 + 1
        candidates.extend(settlement_dates(year, quarter))
    return candidates


# ── FINRA CSV fetching ────────────────────────────────────────────────────

def _fetch_csv(settlement_date: str) -> str:
    """Download the FINRA CSV for a settlement date (YYYYMMDD string)."""
    url = FINRA_CSV_URL.format(date=settlement_date)
    resp = httpx.get(url, headers={"User-Agent": FINRA_USER_AGENT}, timeout=60)
    if resp.status_code == 404:
        raise FileNotFoundError(f"No FINRA data for settlement date {settlement_date}")
    resp.raise_for_status()
    return resp.text


def _parse_csv(csv_text: str, settlement_date: str) -> list[dict]:
    """Parse the pipe-delimited FINRA CSV into clean row dicts."""
    reader = csv.DictReader(io.StringIO(csv_text), delimiter="|")
    rows = []
    for r in reader:
        symbol = (r.get("symbolCode") or "").strip()
        if not symbol:
            continue
        try:
            rows.append({
                "symbol": symbol,
                "settlement_date": r.get("settlementDate", settlement_date),
                "issue_name": r.get("issueName", "").strip(),
                "exchange": r.get("issuerServicesGroupExchangeCode", "").strip(),
                "current_short": int(r.get("currentShortPositionQuantity", 0) or 0),
                "previous_short": int(r.get("previousShortPositionQuantity", 0) or 0),
                "avg_daily_volume": int(r.get("averageDailyVolumeQuantity", 0) or 0),
                "days_to_cover": _safe_float(r.get("daysToCoverQuantity")),
                "change_pct": _safe_float(r.get("changePercent")),
                "revision_flag": r.get("revisionFlag", "").strip() or None,
                "stock_split_flag": r.get("stockSplitFlag", "").strip() or None,
            })
        except (ValueError, TypeError):
            continue
    return rows


def _safe_float(val) -> float | None:
    if val is None or val == "" or val == ".":
        return None
    try:
        return float(val)
    except (ValueError, TypeError):
        return None


# ── Ingestion ─────────────────────────────────────────────────────────────

def ingest(db_path: str | None = None, settlement_date: str | None = None,
           only_watchlist: bool = True, dry_run: bool = False) -> dict:
    """Ingest FINRA short interest data for a settlement date.

    Args:
        db_path: Path to the DB (default: from config)
        settlement_date: YYYYMMDD string; if None, auto-detects latest available
        only_watchlist: If True, filter to WATCHLIST tickers (curated universe)
        dry_run: Fetch + parse but don't write to DB

    Returns: {settlement_date, rows_fetched, rows_written, skipped, status}
    """
    db = dbmod.init_db(db_path)
    today = dt.date.today()

    summary = {
        "settlement_date": settlement_date,
        "rows_fetched": 0,
        "rows_written": 0,
        "skipped": 0,
        "status": "ok",
    }

    # Auto-detect settlement date if not provided
    if not settlement_date:
        settlement_date = _detect_latest_settlement(today)
        if not settlement_date:
            summary["status"] = "no_data"
            summary["message"] = "No recent settlement date with published data"
            return summary
        summary["settlement_date"] = settlement_date

    # Fetch + parse CSV
    try:
        csv_text = _fetch_csv(settlement_date)
    except FileNotFoundError:
        summary["status"] = "no_data"
        summary["message"] = f"No FINRA data for {settlement_date}"
        return summary
    except Exception as e:
        summary["status"] = "failed"
        summary["message"] = str(e)[:200]
        return summary

    rows = _parse_csv(csv_text, settlement_date)
    summary["rows_fetched"] = len(rows)

    if not rows:
        summary["status"] = "empty"
        return summary

    # Filter to watchlist if requested
    if only_watchlist:
        wl = set(WATCHLIST)
        rows = [r for r in rows if r["symbol"] in wl]
        summary["skipped"] = len([r for r in _parse_csv(csv_text, settlement_date) if r["symbol"] not in wl])

    if dry_run:
        summary["rows_written"] = 0
        summary["status"] = "dry_run"
        return summary

    # Compute absolute change; avoid division by zero for %
    for r in rows:
        r["change_abs"] = r["current_short"] - r["previous_short"]
        if r["previous_short"] and r["previous_short"] > 0:
            r["change_pct"] = (r["change_abs"] / r["previous_short"]) if r["change_abs"] else 0.0
        else:
            r["change_pct"] = None  # Cannot compute % without prior value

    # Upsert into DB
    written = 0
    with dbmod.get_connection(db) as conn:
        for r in rows:
            conn.execute(
                """INSERT OR REPLACE INTO short_interest
                   (symbol, settlement_date, issue_name, exchange, current_short,
                    previous_short, avg_daily_volume, days_to_cover, change_pct,
                    change_abs, revision_flag, stock_split_flag)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (r["symbol"], r["settlement_date"], r["issue_name"], r["exchange"],
                 r["current_short"], r["previous_short"], r["avg_daily_volume"],
                 r["days_to_cover"], r["change_pct"], r["change_abs"],
                 r["revision_flag"], r["stock_split_flag"]),
            )
            written += 1
        conn.commit()

    summary["rows_written"] = written

    # Log ingestion
    _log_ingestion(db_path=db, settlement_date=settlement_date,
                   rows_fetched=summary["rows_fetched"], rows_written=written,
                   status="ok" if written > 0 else "partial")

    # Update ticker_short_meta aggregates
    _update_meta(db)

    return summary


def _detect_latest_settlement(today: dt.date) -> str | None:
    """Find the most recent settlement date with published FINRA data."""
    for candidate in _next_settlement_candidates(today):
        try:
            url = FINRA_CSV_URL.format(date=candidate)
            resp = httpx.head(url, headers={"User-Agent": FINRA_USER_AGENT}, timeout=10)
            if resp.status_code == 200:
                return candidate
        except Exception:
            continue
    return None


def _log_ingestion(db_path, settlement_date: str, rows_fetched: int,
                   rows_written: int, status: str, error: str | None = None):
    """Insert a row into ingestion_log_si."""
    now = dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%d %H:%M:%S")
    db = dbmod.init_db(db_path)
    with dbmod.get_connection(db) as conn:
        conn.execute(
            """INSERT INTO ingestion_log_si
               (run_date, run_start, run_end, status, rows_fetched,
                rows_written, settlement_date, error_message)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
            (settlement_date[:8] if len(settlement_date)==8 else settlement_date,
             now, now, status, rows_fetched, rows_written,
             settlement_date, error),
        )
        conn.commit()


def _update_meta(db_path: str | None = None):
    """Refresh ticker_short_meta aggregates from short_interest table."""
    db = dbmod.init_db(db_path)

    # Use Python to compute aggregates, then insert
    with dbmod.get_connection(db) as conn:
        # Clear existing
        conn.execute("DELETE FROM ticker_short_meta")

        # Get all short_interest rows, sorted by ticker + date descending
        rows = conn.execute(
            "SELECT symbol, settlement_date, current_short, days_to_cover, "
            "change_pct, previous_short FROM short_interest "
            "ORDER BY symbol, settlement_date DESC"
        ).fetchall()

        if not rows:
            conn.commit()
            return

        # Group by ticker
        from collections import defaultdict
        by_ticker = defaultdict(list)
        for r in rows:
            by_ticker[r["symbol"]].append(r)

        # Compute aggregates per ticker
        for ticker, items in by_ticker.items():
            latest = items[0]  # already sorted desc by date
            all_vals = [i["current_short"] for i in items]

            conn.execute(
                """INSERT INTO ticker_short_meta
                   (ticker, latest_date, latest_short, latest_dtc, latest_change_pct,
                    peak_short, peak_date, avg_short_12m)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                (ticker,
                 latest["settlement_date"],
                 latest["current_short"],
                 latest["days_to_cover"],
                 latest["change_pct"],
                 max(all_vals),
                 items[0]["settlement_date"],  # latest == peak_date for max short
                 sum(all_vals) // len(all_vals) if all_vals else 0,
                ),
            )

        conn.commit()


def main():
    ap = argparse.ArgumentParser(description="Ingest FINRA short interest data")
    ap.add_argument("--db", default=None, help="DB path (default: from config)")
    ap.add_argument("--date", default=None, help="Settlement date YYYYMMDD (default: auto-detect)")
    ap.add_argument("--all-tickers", action="store_true", help="Ingest all tickers, not just watchlist")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()
    result = ingest(
        db_path=args.db,
        settlement_date=args.date,
        only_watchlist=not args.all_tickers,
        dry_run=args.dry_run,
    )
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
