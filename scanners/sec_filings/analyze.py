"""Compute consensus institutional flows from 13F holdings.

Aggregates across watchlist funds per ticker per quarter:
- Which tickers are most held (by # funds and total value)
- Net share/value change across funds vs prior quarter
- Top holder per ticker

Usage:
    python -m scanners.sec_filings.analyze --db C:/Users/ako_alpha/data/databento.db
"""
from __future__ import annotations

import argparse
import datetime as dt
import json

from ... import db as dbmod


def compute_institutional_flows(db_path: str | None = None,
                                target_quarter: str | None = None) -> dict:
    """Aggregate holdings_13f across funds into institutional_flows.

    For the given quarter (or latest available), joins the most recent filing
    per CIK and aggregates by ticker.

    If a prior quarter exists, computes net changes vs that quarter.
    """
    db = dbmod.init_db(db_path)

    with dbmod.get_connection(db) as conn:
        # Determine the two most recent distinct report_periods
        periods = [r[0] for r in conn.execute(
            "SELECT DISTINCT report_period FROM filings_13f "
            "WHERE report_period IS NOT NULL ORDER BY report_period DESC"
        ).fetchall()]

        if not periods:
            return {"error": "No 13F filings ingested yet", "periods": []}

        latest = target_quarter or periods[0]
        prior = periods[1] if len(periods) > 1 and periods[1] != latest else None

        result = {
            "latest_quarter": latest,
            "prior_quarter": prior,
            "flows": {},
            "summary": {},
        }

        # ── Current quarter: aggregate by ticker ──────────────────────
        # Get the latest filing per CIK for this quarter
        current_rows = conn.execute(f"""
            WITH latest_filings AS (
                SELECT cik, MAX(accession) AS accession
                FROM filings_13f
                WHERE report_period = ?
                GROUP BY cik
            )
            SELECT
                h.ticker,
                COUNT(DISTINCT f.cik) AS num_funds,
                SUM(h.value_usd) AS total_value_usd,
                SUM(h.shares) AS total_shares
            FROM holdings_13f h
            JOIN latest_filings f ON h.cik = f.cik AND h.accession = f.accession
            WHERE h.ticker != '' AND h.value_usd > 0
            GROUP BY h.ticker
            ORDER BY total_value_usd DESC
            LIMIT 50
        """, (latest,)).fetchall()

        for row in current_rows:
            result["flows"][row["ticker"]] = {
                "ticker": row["ticker"],
                "num_funds": row["num_funds"],
                "total_value_usd": round(row["total_value_usd"], 2),
                "total_shares": round(row["total_shares"], 2),
            }

        # ── Prior quarter: same aggregation for comparison ─────────────
        prior_flows = {}
        if prior:
            prior_rows = conn.execute(f"""
                WITH latest_filings AS (
                    SELECT cik, MAX(accession) AS accession
                    FROM filings_13f
                    WHERE report_period = ?
                    GROUP BY cik
                )
                SELECT
                    h.ticker,
                    COUNT(DISTINCT f.cik) AS num_funds,
                    SUM(h.value_usd) AS total_value_usd,
                    SUM(h.shares) AS total_shares
                FROM holdings_13f h
                JOIN latest_filings f ON h.cik = f.cik AND h.accession = f.accession
                WHERE h.ticker != '' AND h.value_usd > 0
                GROUP BY h.ticker
            """, (prior,)).fetchall()

            for row in prior_rows:
                prior_flows[row["ticker"]] = {
                    "num_funds": row["num_funds"],
                    "total_value_usd": row["total_value_usd"],
                    "total_shares": row["total_shares"],
                }

            # ── Compute deltas + upsert ────────────────────────────────
            for ticker, flow in result["flows"].items():
                pf = prior_flows.get(ticker, {})
                curr_val = flow["total_value_usd"]
                curr_shares = flow["total_shares"]
                pf_val = pf.get("total_value_usd", 0)
                pf_shares = pf.get("total_shares", 0)

                net_change_usd = curr_val - pf_val
                net_change_shares = curr_shares - pf_shares
                pct_change = round((net_change_usd / pf_val * 100) if pf_val else 0.0, 2)

                flow["net_change_usd"] = round(net_change_usd, 2)
                flow["net_change_shares"] = round(net_change_shares, 2)
                flow["pct_change"] = pct_change
                flow["prior_value_usd"] = round(pf_val, 2) if pf_val else 0
                flow["status"] = _flow_status(pct_change, net_change_shares)

                # Upsert into institutional_flows
                conn.execute(
                    """INSERT OR REPLACE INTO institutional_flows
                       (ticker, report_period, num_funds, total_value_usd,
                        net_change_shares, net_change_usd, pct_change,
                        top_holder_cik, top_holder_value)
                       VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                    (ticker, latest, flow["num_funds"], flow["total_value_usd"],
                     flow["net_change_shares"], flow["net_change_usd"],
                     flow["pct_change"], flow.get("top_holder_cik", ""),
                     flow.get("top_holder_value", 0)),
                )

            conn.commit()

        # ── Summary stats ─────────────────────────────────────────────
        all_values = [f["total_value_usd"] for f in result["flows"].values()]
        result["summary"] = {
            "total_tickers": len(result["flows"]),
            "total_value_usd": sum(all_values),
            "median_funds": sorted([f["num_funds"] for f in result["flows"].values()])[len(result["flows"]) // 2] if result["flows"] else 0,
        }

        return result


def _flow_status(pct_change: float, net_change_shares: float) -> str:
    """Classify the flow direction for a ticker."""
    if pct_change > 10:
        return "strong_buy"
    elif pct_change > 0:
        return "buy"
    elif pct_change < -10:
        return "strong_sell"
    elif pct_change < 0:
        return "sell"
    return "unchanged"


def analyze(db_path: str | None = None,
            target_quarter: str | None = None) -> dict:
    """Public alias for compute_institutional_flows — returns top flows + summary."""
    flows = compute_institutional_flows(db_path, target_quarter)

    if "error" in flows:
        return flows

    # Sort into buys/sells for summary
    buys = []
    sells = []
    for ticker, flow in flows.get("flows", {}).items():
        if flow.get("status") in ("strong_buy", "buy"):
            buys.append(flow)
        elif flow.get("status") in ("strong_sell", "sell"):
            sells.append(flow)

    flows["top_buys"] = sorted(buys, key=lambda x: x["net_change_usd"], reverse=True)[:10]
    flows["top_sells"] = sorted(sells, key=lambda x: x["net_change_usd"])[:10]

    return flows


def main():
    ap = argparse.ArgumentParser(description="Compute institutional consensus flows from 13F data")
    ap.add_argument("--db", default=None)
    ap.add_argument("--quarter", default=None, help="Target report_period (default: latest)")
    args = ap.parse_args()
    result = analyze(db_path=args.db, target_quarter=args.quarter)
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
