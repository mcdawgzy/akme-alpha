"""Data fetching for backtests — Yahoo Finance 1m and daily bars.

Uses the same Yahoo chart API pattern as the regime scanner (no auth, no API key).
1-minute data is limited to ~60 days by Yahoo; for longer history we fall back
to daily bars and approximate the opening range using the first 30-min proxy.
"""
from __future__ import annotations

import datetime as dt
from pathlib import Path

import httpx

from ...scanners.regime.config import YAHOO_CHART_URL, YAHOO_UA, HTTP_TIMEOUT

# RTH constants (Eastern Time)
RTH_START_MIN = 9 * 60 + 30  # 9:30 AM ET
RTH_END_MIN = 16 * 60        # 4:00 PM ET
RTH_END_EXIT_MIN = 15 * 60 + 55  # 3:55 PM ET (exit 5 min before close)


def fetch_1m(ticker: str, days: int = 60) -> list[dict]:
    """Fetch 1-minute bars for a ticker using 7-day chunks.

    Yahoo Finance limits 1-minute data to 7 days per request when using
    the `range` parameter. By using `period1`/`period2` epoch timestamps
    with 7-day windows, we can backfill up to `days` days of history.

    Returns bars sorted by timestamp, each:
    {timestamp, open, high, low, close, volume, datetime, rth}
    """
    url = YAHOO_CHART_URL.format(ticker=ticker)
    all_bars: list[dict] = []
    today = dt.datetime.now(tz=dt.timezone.utc)
    window_days = 7  # Yahoo's 1m limit per request

    num_chunks = max(1, (days + window_days - 1) // window_days)
    for chunk in range(num_chunks):
        end_date = today - dt.timedelta(days=chunk * window_days)
        start_date = end_date - dt.timedelta(days=window_days)
        period1 = int(start_date.timestamp())
        period2 = int(end_date.timestamp())

        params = {
            "period1": period1,
            "period2": period2,
            "interval": "1m",
        }
        try:
            resp = httpx.get(url, params=params,
                             headers={"User-Agent": YAHOO_UA},
                             timeout=HTTP_TIMEOUT)
            resp.raise_for_status()
            data = resp.json()
        except Exception:
            continue

        if not data.get("chart", {}).get("result"):
            continue

        result = data["chart"]["result"][0]
        timestamps = result["timestamp"]
        quote = result["indicators"]["quote"][0]

        for i, ts in enumerate(timestamps):
            if quote["close"][i] is None:
                continue
            d = dt.datetime.fromtimestamp(ts, tz=dt.timezone.utc)
            et = d - dt.timedelta(hours=4)
            minute_of_day = et.hour * 60 + et.minute
            is_rth = RTH_START_MIN <= minute_of_day <= RTH_END_MIN
            all_bars.append({
                "timestamp": d.isoformat(),
                "datetime": et,
                "open": float(quote["open"][i]),
                "high": float(quote["high"][i]),
                "low": float(quote["low"][i]),
                "close": float(quote["close"][i]),
                "volume": int(quote["volume"][i]) if quote["volume"][i] else 0,
                "rth": is_rth,
                "minute_of_day": minute_of_day,
            })

    # Deduplicate by timestamp (chunks may overlap at boundaries), sort descending
    seen = set()
    unique_bars = []
    for b in sorted(all_bars, key=lambda x: x["timestamp"], reverse=True):
        if b["timestamp"] not in seen:
            seen.add(b["timestamp"])
            unique_bars.append(b)
    return list(reversed(unique_bars))


def fetch_daily(ticker: str, days: int = 1000) -> list[dict]:
    """Fetch daily bars for a ticker."""
    url = YAHOO_CHART_URL.format(ticker=ticker)
    params = {"range": f"{min(days, 1000)}d", "interval": "1d"}
    resp = httpx.get(url, params=params, headers={"User-Agent": YAHOO_UA},
                     timeout=HTTP_TIMEOUT)
    resp.raise_for_status()
    data = resp.json()

    if not data.get("chart", {}).get("result"):
        return []

    result = data["chart"]["result"][0]
    timestamps = result["timestamp"]
    quote = result["indicators"]["quote"][0]

    bars = []
    for i, ts in enumerate(timestamps):
        if quote["close"][i] is None:
            continue
        d = dt.datetime.fromtimestamp(ts, tz=dt.timezone.utc).date()
        bars.append({
            "date": d.isoformat(),
            "open": float(quote["open"][i]),
            "high": float(quote["high"][i]),
            "low": float(quote["low"][i]),
            "close": float(quote["close"][i]),
            "volume": int(quote["volume"][i]) if quote["volume"][i] else 0,
        })
    return bars


def get_rth_bars(bars: list[dict]) -> list[dict]:
    """Filter to RTH bars only."""
    return [b for b in bars if b.get("rth", True)]


def group_by_date(bars: list[dict]) -> dict[str, list[dict]]:
    """Group intraday bars by date (ISO date string)."""
    groups = {}
    for b in bars:
        d = b["datetime"].date().isoformat()
        groups.setdefault(d, []).append(b)
    return groups
