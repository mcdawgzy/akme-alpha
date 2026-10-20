"""FastAPI application with rate limiting and all akme-alpha endpoints."""

from __future__ import annotations

import json
import os
import uuid
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from pathlib import Path

# Load .env file if present (allows local FRED_API_KEY, etc.)
try:
    from dotenv import load_dotenv
    load_dotenv(Path(__file__).parent / ".env")
except ImportError:
    pass

import httpx
from fastapi import FastAPI, Request, HTTPException
from fastapi.responses import JSONResponse, HTMLResponse
from fastapi.middleware.cors import CORSMiddleware

from akme_alpha import config, db as dbmod
from akme_alpha.scanners.yield_curves import analyze as yc
from akme_alpha.scanners.sec_filings import ingest as si_ingest, analyze as si_analyze
from akme_alpha.scanners.finra_short_interest import ingest as finra_ingest, analyze as finra_analyze


@asynccontextmanager
async def lifespan(app: FastAPI):
    dbmod.init_db()
    yield

app = FastAPI(
    title="Akme Alpha — Public Market Data API",
    version="0.2.0",
    description="Digestible, summarized market data from public sources. "
                "Free tier: 100 req/day. Pro: $49/mo (1K/day). Team: $299/mo (10K/day).",
    lifespan=lifespan,
)
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_credentials=True,
                   allow_methods=["*"], allow_headers=["*"])


# Rate limiting middleware
@app.middleware("http")
async def rate_limiter(request: Request, call_next):
    auth = request.headers.get("Authorization", "")
    api_key = auth[7:] if auth.startswith("Bearer ") else None
    if api_key:
        with dbmod.get_connection() as conn:
            tier, limit = dbmod.get_tier_limit(conn, api_key)
            if tier is None:
                return JSONResponse({"error": "Invalid API key", "message": "Provide a valid Bearer token"},
                                    status_code=401)
            if dbmod.count_requests_today(conn, api_key) >= limit:
                return JSONResponse({"error": "Rate limit exceeded", "tier": tier, "limit": limit,
                                     "message": f"Upgrade at https://akme.alpha/pricing"}, status_code=429)
            dbmod.log_request(conn, api_key, request.url.path, tier)
            conn.commit()
    return await call_next(request)


def parse_api_key(request: Request) -> str | None:
    auth = request.headers.get("Authorization", "")
    return auth[7:] if auth.startswith("Bearer ") else None


# API Key Registration
@app.post("/api/register")
async def register_key(email: str | None = None, label: str = "client-app"):
    key = f"dl_free_{uuid.uuid4().hex[:8]}"
    with dbmod.get_connection() as conn:
        conn.execute("INSERT INTO api_keys (key, tier, label) VALUES (?, ?, ?)", (key, "free", label))
        conn.commit()
    return {"api_key": key, "tier": "free", "daily_limit": config.TIERS["free"]["daily_limit"],
            "message": "Free tier: 100 requests/day."}


# Tier definitions
@app.get("/api/tiers")
async def tiers():
    return {"tiers": {t: {"daily_limit": i["daily_limit"], "price_usd_monthly": i["price"], "label": i["label"]}
                      for t, i in config.TIERS.items()}}


# Yield Curve Regime Endpoint
@app.get("/api/yield-curve/regime")
async def get_yield_curve_regime():
    r = yc.analyze()
    return {"date": r["date"], "curve": r["curve"], "spreads": r["spreads"], "regime": r["regime"],
            "classification": r["classification"], "zscore_3m10": r["zscore_3m10"],
            "six_month_yield_change": r.get("y10_level_6m_change"), "summary": r["notes"],
            "source": "Yahoo Finance (CBOE: ^IRX, ^FVX, ^TNX, ^TYX)"}


@app.get("/api/yield-curve/history")
async def get_yield_curve_history(days: int = 90):
    days = min(days, 365)
    with dbmod.get_connection() as conn:
        rows = conn.execute("SELECT date, spread_3m10, regime, classification, notes FROM yield_curve_regime ORDER BY date DESC LIMIT ?", (days,)).fetchall()
    return {"count": len(rows), "days": days, "data": [{"date": r["date"], "spread_3m10_bps": r["spread_3m10"],
             "regime": r["regime"], "classification": r["classification"], "summary": r["notes"]} for r in rows]}


@app.get("/api/yield-curve/latest")
async def get_latest_curve():
    with dbmod.get_connection() as conn:
        rows = conn.execute("SELECT date, maturity, yield_pct FROM yield_curves WHERE date = (SELECT MAX(date) FROM yield_curves) ORDER BY maturity").fetchall()
    return {"date": rows[0]["date"] if rows else None, "curve": {r["maturity"]: r["yield_pct"] for r in rows}, "source": "Yahoo Finance"}


# Commodities Endpoint
@app.get("/api/commodities")
async def get_commodities(date: str | None = None):
    with dbmod.get_connection() as conn:
        if date:
            rows = conn.execute("SELECT date, commodity, price, ticker FROM commodities WHERE date = ?", (date,)).fetchall()
        else:
            rows = conn.execute("SELECT DISTINCT commodity, price, ticker, date FROM commodities WHERE date = (SELECT MAX(date) FROM commodities)").fetchall()
    return {"date": rows[0]["date"] if rows else None,
            "commodities": {r["commodity"]: {"price": r["price"], "ticker": r["ticker"]} for r in rows},
            "source": "Yahoo Finance", "note": "USD per barrel (oil/gas) or troy oz (gold/silver)"}


# Economic Indicators (requires FRED_API_KEY env var)
@app.get("/api/economic-indicators")
async def get_economic_indicators():
    api_key = os.environ.get("FRED_API_KEY")
    if not api_key:
        return {"error": "API key required", "message": "Set FRED_API_KEY env var", "docs": "https://fred.stlouisfed.org/docs/api/fred/"}
    series = {"cpi": "CPIAUCSL", "ppi": "PPIACO", "fed_funds": "FEDFUNDS", "unemployment": "UNRATE", "gdp": "GDPC1"}
    results = {}
    for name, fid in series.items():
        try:
            r = httpx.get("https://api.stlouisfed.org/fred/series/observations",
                          params={"series_id": fid, "api_key": api_key, "file_type": "json"}, timeout=15)
            data = r.json().get("observations", [])
            if data:
                val = [o for o in data if o["value"] != "."][-1]
                results[name] = {"date": val["date"], "value": float(val["value"])}
        except Exception as e:
            results[name] = {"error": str(e)}
    return {"date": results.get("cpi", {}).get("date"), "indicators": results, "source": "FRED API"}


# ── API Endpoints ──────────────────────────────────────────────────────────

# Institutional Flows — live 13F consensus data
@app.get("/api/institutional-flows")
async def institutional_flows(top: int = 50, quarter: str | None = None):
    r = si_analyze.analyze(target_quarter=quarter)
    if "error" in r:
        return {"error": r["error"], "latest_quarter": r.get("latest_quarter", None)}
    # Return top N by total value, plus top buys/sells
    top_flows = sorted(r["flows"].values(), key=lambda x: x["total_value_usd"], reverse=True)[:top]
    return {
        "date": r["latest_quarter"],
        "prior_quarter": r["prior_quarter"],
        "top_holdings": top_flows,
        "top_buys": r["top_buys"][:10],
        "top_sells": r["top_sells"][:10],
        "summary": r["summary"],
        "source": "SEC EDGAR (13F-HR filings)",
    }


@app.get("/api/institutional-flows/{ticker}")
async def institutional_flows_ticker(ticker: str):
    """Single-ticker institutional holding detail."""
    with dbmod.get_connection() as conn:
        # Latest filing per CIK for this ticker
        rows = conn.execute(
            """SELECT f.filer_name, f.cik, f.report_period, f.total_value AS filing_total,
                      h.shares, h.value_usd, h.put_call, h.investment_discretion
               FROM holdings_13f h
               JOIN filings_13f f ON h.cik = f.cik AND h.accession = f.accession
               WHERE h.ticker = ? AND f.report_period = (
                   SELECT MAX(report_period) FROM filings_13f
               )
               ORDER BY h.value_usd DESC
               LIMIT 20""",
            (ticker.upper(),),
        ).fetchall()
    return {
        "ticker": ticker.upper(),
        "holders": [dict(r) for r in rows],
        "source": "SEC EDGAR (13F-HR)",
    }

# Short Interest Ratio — live FINRA data
@app.get("/api/short-interest-ratio")
async def short_interest_ratio():
    r = finra_analyze.analyze()
    if "error" in r:
        return {"error": r["error"], "status": r.get("status", "error")}
    return {
        "date": r["latest_settlement"],
        "signals": {k: v for k, v in r.items() if isinstance(v, list)},
        "summary": r["summary"],
        "source": "FINRA bi-weekly (exchange-reported aggregate)",
    }


@app.get("/api/short-interest-ratio/{ticker}")
async def short_interest_ticker(ticker: str):
    """Single-ticker short interest history."""
    r = finra_analyze.analyze_ticker(ticker=ticker)
    if "error" in r:
        return {"error": r["error"], "ticker": ticker.upper()}
    return r

@app.get("/api/factor-exposure")
async def factor_exposure():
    raise HTTPException(status_code=503, detail="Factor exposure: 13F analysis in progress")


# Health / Debug
@app.get("/api/health")
async def health():
    return {"status": "ok", "timestamp": datetime.now(timezone.utc).isoformat(), "version": "0.2.0"}


@app.get("/api/me")
async def me(request: Request):
    api_key = parse_api_key(request)
    if not api_key:
        return {"message": "No API key provided", "tip": "Authorization: Bearer ***"}
    with dbmod.get_connection() as conn:
        tier, limit = dbmod.get_tier_limit(conn, api_key)
        if not tier:
            return {"error": "Invalid API key"}
        return {"api_key": api_key, "tier": tier, "daily_limit": limit,
                "used_today": dbmod.count_requests_today(conn, api_key)}


@app.get("/", include_in_schema=False)
async def root():
    html = (Path(__file__).parent / "index.html").read_text()
    return HTMLResponse(content=html, media_type="text/html")