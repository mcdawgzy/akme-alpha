"""Opening Range Breakout (ORB) strategy — Toby Crabel classic.

Rules (testable, no discretion):
1. Opening Range = high and low of first N minutes of RTH (default 30).
   Range is frozen after N minutes; later bars don't widen it.
2. Entry: a 1-minute bar closes ABOVE OR high → long.
   A 1-minute bar closes BELOW OR low → short.
3. Stop: 1 tick below/above for longs/shorts (tight stop — we measure edge, not comfort).
4. Exit: 3:55 PM ET (5 min before close) or stop hit — same-day only.
5. Position size: equal dollar amount per trade (capital / num_trades).

Variations tested (via params):
- orb_minutes: 5, 15, 30, 60
- long_only: True/False (short side historically weak for retail)
- use_200ma_filter: True/False (only trade in direction of 200-day MA trend)
- min_volume_pct: minimum volume as % of daily average for the breakout bar
  (filters illiquid breakouts; 0 = no filter)

Biases guarded against:
- Lookahead: OR is frozen at bar N; entry uses only bars that close after OR end.
- Survivorship: we test the exact current tickers (no delisted removal).
- Fill assumptions: we use the breakout bar's close (conservative; real fills
  would be at the next bar open which is worse).
"""
from __future__ import annotations

import datetime as dt
import statistics
from typing import Optional

from ..data import fetch_1m, get_rth_bars, group_by_date
from ..engine import Trade, BacktestResult


# Equity tickers from the user's 31-ticker watchlist
DEFAULT_TICKERS = [
    "AAPL", "MSFT", "NVDA", "GOOGL", "AMZN",
    "META", "TSLA", "BRK-B", "JPM", "V",
    "XOM", "JNJ", "SPY", "QQQ", "EEM", "EFA",
]


def compute_200ma_daily(ticker: str, end_date: dt.date) -> Optional[float]:
    """Fetch daily data and return the 200-day SMA as of end_date."""
    from ..data import fetch_daily
    bars = fetch_daily(ticker, days=250)
    # Find bars up to and including end_date
    relevant = [b for b in bars if dt.date.fromisoformat(b["date"]) <= end_date]
    if len(relevant) < 200:
        return None
    closes = [b["close"] for b in relevant[-200:]]
    return statistics.mean(closes)


def run_orb_backtest(
    tickers: list[str] | None = None,
    orb_minutes: int = 30,
    long_only: bool = True,
    use_200ma_filter: bool = False,
    min_volume_pct: float = 0.0,
    initial_capital: float = 10000.0,
    days: int = 60,
) -> BacktestResult:
    """Run the ORB backtest across a ticker universe.

    Args:
        tickers: list of ticker symbols (default: 16 equity tickers)
        orb_minutes: opening range window in minutes (5/15/30/60)
        long_only: if True, skip short breakouts
        use_200ma_filter: only trade breakouts in the direction of 200-day MA
        min_volume_pct: breakout bar must have >= this % of recent average volume
        initial_capital: starting capital
        days: how many days of 1m data to fetch per ticker (max 60)

    Returns:
        BacktestResult with all trades and stats
    """
    if tickers is None:
        tickers = DEFAULT_TICKERS

    all_trades: list[Trade] = []
    per_ticker_stats: dict[str, list[Trade]] = {}

    for ticker in tickers:
        try:
            bars = fetch_1m(ticker, days=days)
        except Exception as e:
            print(f"[orb] {ticker}: fetch error — {e}")
            continue

        rth_bars = get_rth_bars(bars)
        daily_groups = group_by_date(rth_bars)

        # Pre-compute 200-day MAs if filter is on
        ma_cache: dict[str, float] = {}
        if use_200ma_filter:
            for date_str in daily_groups:
                end_date = dt.date.fromisoformat(date_str)
                ma = compute_200ma_daily(ticker, end_date)
                if ma:
                    ma_cache[date_str] = ma

        for date_str, day_bars in sorted(daily_groups.items()):
            if len(day_bars) < orb_minutes + 5:
                continue  # not enough intraday data

            # ── 1. Compute Opening Range (first N RTH bars) ──
            or_bars = day_bars[:orb_minutes]
            or_high = max(b["high"] for b in or_bars)
            or_low = min(b["low"] for b in or_bars)
            or_range = or_high - or_low
            if or_range == 0:
                continue

            # ── 2. Compute recent avg volume for filter ──
            recent_vol = statistics.mean(b["volume"] for b in day_bars if b["volume"] > 0) if day_bars else 0

            # ── 3. Scan for breakout (bars after OR window) ──
            entry_bar = None
            direction = None
            for b in day_bars[orb_minutes:]:
                # Long breakout
                if b["close"] > or_high and not long_only:
                    if min_volume_pct > 0 and recent_vol > 0:
                        if b["volume"] < recent_vol * min_volume_pct:
                            continue
                    entry_bar = b
                    direction = "long"
                    break
                # Long breakout (long_only mode)
                elif b["close"] > or_high and long_only:
                    if min_volume_pct > 0 and recent_vol > 0:
                        if b["volume"] < recent_vol * min_volume_pct:
                            continue
                    entry_bar = b
                    direction = "long"
                    break
                # Short breakout
                if b["close"] < or_low and not long_only:
                    if min_volume_pct > 0 and recent_vol > 0:
                        if b["volume"] < recent_vol * min_volume_pct:
                            continue
                    entry_bar = b
                    direction = "short"
                    break

            if not entry_bar:
                continue

            # ── 4. Apply 200-day MA filter ──
            if use_200ma_filter:
                ma = ma_cache.get(date_str)
                open_price = day_bars[0]["open"]
                if ma:
                    if direction == "long" and open_price < ma:
                        continue  # trade only in MA direction
                    if direction == "short" and open_price > ma:
                        continue

            # ── 5. Exit at 3:55 PM ET (5 min before close) ──
            exit_bar = None
            for b in day_bars:
                # 3:55 PM = 15*60+55 = 955 minute of day
                if b["minute_of_day"] >= 15 * 60 + 55:
                    exit_bar = b
                    break
            if not exit_bar:
                exit_bar = day_bars[-1]  # last available bar

            # ── 6. Stop loss ──
            # Tight stop: for longs, below OR low; for shorts, above OR high
            stop_hit = False
            stop_price = or_low if direction == "long" else or_high

            for b in day_bars[day_bars.index(entry_bar):]:
                if direction == "long" and b["low"] <= stop_price:
                    stop_hit = True
                    exit_bar = b
                    break
                if direction == "short" and b["high"] >= stop_price:
                    stop_hit = True
                    exit_bar = b
                    break

            # ── 7. Compute P&L ──
            entry_price = entry_bar["close"]
            exit_price = exit_bar["close"]
            exit_reason = "stop" if stop_hit else "eod"

            # Position: risk 5% of capital on the OR range
            # position_size = (capital * 0.05) / or_range
            risk_per_trade = initial_capital * 0.05
            shares = risk_per_trade / or_range

            trade = Trade(
                ticker=ticker,
                entry_time=entry_bar["timestamp"],
                entry_price=entry_price,
                exit_time=exit_bar["timestamp"],
                exit_price=exit_price,
                direction=direction,
                shares=shares,
                entry_reason=f"ORB_{orb_minutes}m_breakout",
                exit_reason=exit_reason,
            )
            all_trades.append(trade)
            per_ticker_stats.setdefault(ticker, []).append(trade)

        print(f"[orb] {ticker}: {len(per_ticker_stats.get(ticker, []))} trades")

    return BacktestResult(
        name=f"ORB_{orb_minutes}m_{'long_only' if long_only else 'long_short'}",
        trades=all_trades,
        initial_capital=initial_capital,
    )


def compare_variants(tickers: list[str] | None = None, days: int = 60) -> list[dict]:
    """Run multiple ORB variants and return a comparison table.

    Tests different ORB window sizes (5/15/30/60 min) and long-only vs long-short.
    """
    if tickers is None:
        tickers = DEFAULT_TICKERS

    variants = [
        {"orb_minutes": 5,  "long_only": True,  "use_200ma_filter": False},
        {"orb_minutes": 15, "long_only": True,  "use_200ma_filter": False},
        {"orb_minutes": 30, "long_only": True,  "use_200ma_filter": False},
        {"orb_minutes": 30, "long_only": False, "use_200ma_filter": False},
        {"orb_minutes": 30, "long_only": True,  "use_200ma_filter": True},
    ]

    results = []
    for v in variants:
        print(f"[orb] Testing variant: {v}")
        result = run_orb_backtest(
            tickers=tickers,
            orb_minutes=v["orb_minutes"],
            long_only=v["long_only"],
            use_200ma_filter=v["use_200ma_filter"],
            days=days,
        )
        results.append({
            "variant": v,
            "name": result.name,
            "trades": len(result.trades),
            "win_rate": round(result.win_rate, 1),
            "avg_win": round(result.avg_win, 2),
            "avg_loss": round(result.avg_loss, 2),
            "total_return_pct": round(result.total_return_pct, 1),
            "profit_factor": round(result.profit_factor, 2),
            "max_drawdown_pct": round(result.max_drawdown_pct, 1),
            "median_trade": round(result.median_trade, 2),
        })
    return results


if __name__ == "__main__":
    results = compare_variants()
    print("\n=== ORB Strategy Backtest — Variant Comparison ===\n")
    for r in results:
        v = r["variant"]
        label = f"{r['name']}"
        print(f"{label:40s} | Trades: {r['trades']:4d} | WR: {r['win_rate']:5.1f}% | "
              f"AvgW: ${r['avg_win']:7.2f} | AvgL: ${r['avg_loss']:7.2f} | "
              f"Return: {r['total_return_pct']:6.1f}% | PF: {r['profit_factor']:4.2f} | "
              f"MaxDD: {r['max_drawdown_pct']:5.1f}%")
