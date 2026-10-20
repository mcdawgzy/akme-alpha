"""Ingest 13F-HR filings from SEC EDGAR daily index + filing text files.

Usage:
    python -m scanners.sec_filings.ingest --db C:/Users/cho_i/akme_alpha/data/akme_alpha.db

Pipeline:
1. Scan the last INDEX_LOOKBACK_DAYS of SEC daily index files for 13F-HR filings
   matching our watchlist CIKs.
2. Download each filing's full text (.txt) via the redirect URL.
3. Parse the infoTable XML block (last <XML> block in the filing) for holdings.
4. Upsert filings_13f + holdings_13f into the unified DB.

No third-party deps — uses httpx + stdlib xml.etree.ElementTree.
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import re
import xml.etree.ElementTree as ET

import httpx

from ... import db as dbmod
from .config import (
    DAILY_INDEX_URL,
    FILING_URL,
    FILING_FORMS,
    INDEX_LOOKBACK_DAYS,
    SEC_USER_AGENT,
    WATCHLIST_CIKS,
    WATCHLIST_FUNDS,
)

# Namespace used by SEC infoTable XML (default namespace, no prefix)
INFO_NS = "http://www.sec.gov/edgar/document/thirteenf/informationtable"
NS = f"{{{INFO_NS}}}"

# Header rows in the daily .idx file before the pipe-delimited data starts
IDX_HEADER_SKIP = 9


# ── SEC EDGAR discovery ────────────────────────────────────────────────────

def _idx_url(date: dt.date) -> str:
    """Build the master index URL for a given date."""
    q = (date.month - 1) // 3 + 1
    return DAILY_INDEX_URL.format(year=date.year, q=f"QTR{q}", date=date.strftime("%Y%m%d"))


def discover_filings(target_date: dt.date) -> list[dict]:
    """Scan the SEC daily index for a single date; return watchlist 13F-HR entries.

    Each entry: {cik, accession, filer_name, form, filed_date, idx_path}
    """
    url = _idx_url(target_date)
    resp = httpx.get(url, headers={"User-Agent": SEC_USER_AGENT}, timeout=30)
    if resp.status_code == 404:
        return []
    resp.raise_for_status()

    lines = resp.text.splitlines()
    results = []
    for line in lines:
        if "|" not in line:
            continue
        parts = line.strip().split("|")
        if len(parts) < 5:
            continue
        cik = parts[0]
        # SEC CIKs in the index are zero-padded to 10 digits
        cik = cik.lstrip("0") or "0"
        if not cik.isdigit():
            continue
        form = parts[2]
        if form not in FILING_FORMS:
            continue
        if cik not in WATCHLIST_CIKS:
            continue
        # idx_path like: edgar/data/1009016/0001193125-26-422223.txt
        idx_path = parts[4]
        results.append({
            "cik": cik,
            "accession": idx_path.split("/")[-1].replace(".txt", ""),
            "filer_name": parts[1],
            "form": form,
            "filed_date": parts[3],
            "idx_path": idx_path,
        })
    return results


def discover_recent_filings(days: int = INDEX_LOOKBACK_DAYS) -> list[dict]:
    """Scan the last N days of daily index files for watchlist 13F-HR filings."""
    today = dt.date.today()
    all_filings = []
    for i in range(days):
        d = today - dt.timedelta(days=i)
        found = discover_filings(d)
        all_filings.extend(found)
    return all_filings


# ── Filing download + XML parsing ──────────────────────────────────────────

def _download_filing(cik: str, accession: str) -> str:
    """Download a 13F filing's full text. CIK must be zero-stripped for the URL."""
    url = FILING_URL.format(cik_nozeros=cik, accession=accession)
    resp = httpx.get(url, headers={"User-Agent": SEC_USER_AGENT}, timeout=30)
    resp.raise_for_status()
    # SEC returns the filing content (may be a redirect that httpx follows)
    return resp.text


def _extract_info_table(content: str) -> list[dict]:
    """Parse the infoTable XML block from filing text → list of holdings.

    SEC filings contain multiple <XML>...</XML> blocks; the infoTable data is
    in the LAST block. We use the default namespace.
    """
    # Find all <XML>...</XML> blocks
    xml_starts = [m.start() for m in re.finditer(r"<XML>", content, re.IGNORECASE)]
    xml_ends = [m.start() for m in re.finditer(r"</XML>", content, re.IGNORECASE)]
    if not xml_starts or not xml_ends:
        return []

    # Last <XML> block is the infoTable
    last_start = xml_starts[-1]
    last_end = xml_ends[-1] + len("</XML>")
    xml_block = content[last_start:last_end]

    # Strip the <XML> wrapper tags for clean parsing
    xml_block = re.sub(r"<\?xml[^>]*\?>", "", xml_block)
    xml_block = xml_block.replace("<XML>", "").replace("</XML>", "").strip()

    try:
        root = ET.fromstring(xml_block)
    except ET.ParseError:
        return []

    holdings = []
    for info_table in root.iter(f"{NS}infoTable"):
        issuer = info_table.find(f"{NS}nameOfIssuer")
        cusip = info_table.find(f"{NS}cusip")
        value_elem = info_table.find(f"{NS}value")
        shares_elem = info_table.find(f"{NS}shrsOrPrnAmt/{NS}sshPrnamt")
        put_call = info_table.find(f"{NS}putCall")
        discretion = info_table.find(f"{NS}investmentDiscretion")

        # SEC spec: <value> is in thousands of USD. Convert to actual USD.
        raw_value = float(value_elem.text) if value_elem is not None and value_elem.text else 0.0
        value_usd = raw_value * 1000

        shares = float(shares_elem.text) if shares_elem is not None and shares_elem.text else 0.0

        ticker = _resolve_ticker(cusip.text if cusip is not None else "")

        holdings.append({
            "name_of_issuer": issuer.text if issuer is not None else "",
            "title_of_class": (info_table.find(f"{NS}titleOfClass").text
                               if info_table.find(f"{NS}titleOfClass") is not None else ""),
            "cusip": cusip.text if cusip is not None else "",
            "ticker": ticker,
            "shares": shares,
            "price_per_share": round(value_usd / shares, 4) if shares > 0 else None,
            "value_usd": value_usd,
            "put_call": put_call.text if put_call is not None else None,
            "investment_discretion": discretion.text if discretion is not None else None,
            "voting_sole": _voting(info_table, "Sole"),
            "voting_shared": _voting(info_table, "Shared"),
            "voting_none": _voting(info_table, "None"),
        })

    return holdings


def _voting(info_table, tag: str) -> float | None:
    el = info_table.find(f"{NS}votingAuthority/{NS}{tag}")
    if el is not None and el.text:
        return float(el.text)
    return None


# Simple CUSIP → ticker resolver using company_tickers.json
# This is fetched lazily and cached for the process lifetime.
_TICKER_MAP: dict[str, str] | None = None
_CIK_FILER_MAP: dict[str, str] | None = None


def _resolve_ticker(cusip: str) -> str:
    """Resolve a CUSIP to a ticker symbol via SEC's company_tickers.json.

    Returns '' if not found (bond/option/private holding).
    """
    global _TICKER_MAP
    if cusip == "" or not cusip:
        return ""
    # NOTE: SEC's company_tickers.json does not map CUSIP → ticker.
    # A full CUSIP resolver requires the CUSIP universe (paid) or fuzzy matching.
    # For the MVP we leave ticker empty and resolve later via a lookup table.
    return cusip  # Return CUSIP as placeholder; enrichment step can map later


# ── Ingestion ──────────────────────────────────────────────────────────────

def ingest(db_path: str | None = None, days: int = INDEX_LOOKBACK_DAYS,
           dry_run: bool = False) -> dict:
    """Discover and ingest recent 13F-HR filings for watchlist funds.

    Returns summary: {filings_found, filings_processed, holdings_written, ...}
    """
    db = dbmod.init_db(db_path)
    start_time = dt.datetime.now(dt.timezone.utc).isoformat()

    summary = {
        "filings_found": 0,
        "filings_processed": 0,
        "holdings_written": 0,
        "errors": [],
        "db_path": str(db),
    }

    # 1. Discover recent 13F-HR filings for watchlist CIKs
    filings = discover_recent_filings(days=days)
    summary["filings_found"] = len(filings)
    summary["discovery_start"] = start_time
    summary["filings"] = []

    if not filings:
        summary["message"] = f"No 13F-HR filings found for watchlist in last {days} days"
        return summary

    # 2. Process each filing
    for f in filings:
        try:
            # Check if already ingested (dedupe)
            with dbmod.get_connection(db) as conn:
                existing = conn.execute(
                    "SELECT 1 FROM filings_13f WHERE cik = ? AND accession = ?",
                    (f["cik"], f["accession"]),
                ).fetchone()
                if existing:
                    summary["filings"].append({
                        "cik": f["cik"], "accession": f["accession"],
                        "status": "skipped",
                    })
                    summary["filings_processed"] += 1
                    continue

            # Download filing text
            content = _download_filing(f["cik"], f["accession"])

            # Parse infoTable
            holdings = _extract_info_table(content)

            if dry_run:
                summary["filings"].append({
                    "cik": f["cik"], "accession": f["accession"],
                    "holdings": len(holdings), "status": "dry_run",
                })
                summary["filings_processed"] += 1
                summary["holdings_written"] += len(holdings)
                continue

            # Determine report period (quarter end) from filing
            report_period = _infer_report_period(content, f["filed_date"])

            # Upsert filing metadata
            total_value = sum(h["value_usd"] for h in holdings)
            with dbmod.get_connection(db) as conn:
                conn.execute(
                    """INSERT OR REPLACE INTO filings_13f
                       (cik, accession, filer_name, report_period, filed_date,
                        total_value, num_holdings)
                       VALUES (?, ?, ?, ?, ?, ?, ?)""",
                    (f["cik"], f["accession"], f["filer_name"],
                     report_period, f["filed_date"],
                     total_value, len(holdings)),
                )
                # Upsert holdings
                for h in holdings:
                    conn.execute(
                        """INSERT OR REPLACE INTO holdings_13f
                           (cik, accession, name_of_issuer, title_of_class, cusip,
                            ticker, shares, price_per_share, value_usd, put_call,
                            investment_discretion, voting_sole, voting_shared, voting_none)
                           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                        (f["cik"], f["accession"], h["name_of_issuer"],
                         h["title_of_class"], h["cusip"], h["ticker"],
                         h["shares"], h["price_per_share"], h["value_usd"],
                         h["put_call"], h["investment_discretion"],
                         h["voting_sole"], h["voting_shared"], h["voting_none"]),
                    )
                conn.commit()

            summary["filings"].append({
                "cik": f["cik"], "accession": f["accession"],
                "holdings": len(holdings), "status": "ok",
            })
            summary["filings_processed"] += 1
            summary["holdings_written"] += len(holdings)

        except Exception as e:
            summary["errors"].append({
                "cik": f["cik"], "accession": f["accession"],
                "error": str(e)[:200],
            })
            summary["filings"].append({
                "cik": f["cik"], "accession": f["accession"],
                "status": "error", "error": str(e)[:100],
            })

    # 3. Log to ingestion_log_13f
    run_date = dt.date.today().isoformat()
    end_time = dt.datetime.now(dt.timezone.utc).isoformat()
    status = "ok" if not summary["errors"] else ("partial" if summary["filings_processed"] > 0 else "failed")
    with dbmod.get_connection(db) as conn:
        conn.execute(
            """INSERT INTO ingestion_log_13f
               (run_date, run_start, run_end, status, filings_found,
                filings_processed, holdings_written, error_message)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
            (run_date, start_time, end_time, status,
             summary["filings_found"], summary["filings_processed"],
             summary["holdings_written"],
             json.dumps(summary["errors"]) if summary["errors"] else None),
        )
        conn.commit()

    summary["status"] = status
    summary["run_end"] = end_time
    return summary


def _infer_report_period(content: str, filed_date: str) -> str | None:
    """Infer the quarter-end report period from the filing.

    SEC 13F-HR filings include <endDate> in the infoTable XML.
    Falls back to filing the date's quarter-end if not found.
    """
    # Try to find <endDate> in the content
    m = re.search(r"<endDate>(\d{4}-\d{2}-\d{2})</endDate>", content)
    if m:
        return m.group(1)

    # Fallback: compute quarter-end from filed_date
    if filed_date:
        try:
            d = dt.date.fromisoformat(filed_date)
            quarter_end_month = (d.month - 1) // 3 * 3 + 3
            qend = dt.date(d.year, quarter_end_month, 1)
            # Last day of that month
            qend = qend.replace(day=28)
            while True:
                next_day = qend + dt.timedelta(days=1)
                if next_day.month != qend.month:
                    break
                qend = next_day
            return qend.isoformat()
        except (ValueError, TypeError):
            pass
    return None


def main():
    ap = argparse.ArgumentParser(description="Ingest 13F-HR filings from SEC EDGAR")
    ap.add_argument("--db", default=None, help="DB path (default: from config)")
    ap.add_argument("--days", type=int, default=INDEX_LOOKBACK_DAYS,
                    help="Days of daily index to scan")
    ap.add_argument("--dry-run", action="store_true", help="Discover but don't write")
    args = ap.parse_args()
    result = ingest(db_path=args.db, days=args.days, dry_run=args.dry_run)
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
