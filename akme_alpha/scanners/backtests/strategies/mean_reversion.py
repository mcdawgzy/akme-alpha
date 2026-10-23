"""Mean Reversion Strategy (Open-Range Fade) — complementary to ORB.

Rules:
1. Day Open = opening price of RTH
2. ATR = 14-day historical True Range (daily bars)
3. Phase 1: Wait for price to move ≥ 0.5×ATR away from open (track extreme)
4. Phase 2: Enter SHORT when price retraces to within 0.2×ATR of open (from above)
              Enter LONG when price retracts to within 0.2×ATR of open (from below)
5. Stop: 1×ATR from entry
6. Exit: 3:55 PM ET or stop hit — same-day only
7. Position: 5% of capital risked per trade

This tests "open-range fade" — a classic mean-reversion approach.
"""
from __future__ import annotations

import datetime as dt
import statistics
from typing import Optional

from ..data import fetch_1m, get_rth_bars, group_by_date
from ..engine import Trade, BacktestResult
from .orb import DEFAULT_TICKERS


def compute_daily_atr(ticker: str, end_date: dt.date, window: int = 14) -> Optional[float]:
    """Fetch daily data and return the ATR (True Range average)."""
    from ..data import fetch_daily

    bars = fetch_daily(ticker, days=window + 5)
    relevant = [b for b in bars if dt.date.fromisoformat(b["date"]) <= end_date]
    if len(relevant) < window + 1:
        return None

    tr_values = []
    for i in range(len(relevant) - window, len(relevant)):
        prev_close = relevant[i - 1]["close"]
        curr_high = relevant[i]["high"]
        curr_low = relevant[i]["low"]
        tr = max(curr_high - curr_low, abs(curr_high - prev_close), abs(curr_low - prev_close))
        tr_values.append(tr)

    return statistics.mean(tr_values) if tr_values else None


def run_mean_reversion_backtest(
    tickers: list[str] | None = None,
    atr_mult: float = 1.0,
    initial_capital: float = 10000.0,
    days: int = 30,
) -> BacktestResult:
    """Run the open-range fade mean reversion backtest."""
    if tickers is None:
        tickers = DEFAULT_TICKERS

    all_trades: list[Trade] = []

    for ticker in tickers:
        try:
            bars = fetch_1m(ticker, days=days)
        except Exception as e:
            print(f"[mr] {ticker}: fetch error — {e}")
            continue

        rth_bars = get_rth_bars(bars)
        daily_groups = group_by_date(rth_bars)

        for date_str, day_bars in sorted(daily_groups.items()):
            if len(day_bars) < 60:
                continue

            day_open = day_bars[0]["open"]
            end_date = dt.date.fromisoformat(date_str)
            atr = compute_daily_atr(ticker, end_date)
            if not atr or atr <= 0:
                continue

            move_threshold = 0.5 * atr
            entry_threshold = 0.2 * atr
            stop_distance = atr * atr_mult

            max_above = 0.0
            max_below = 0.0
            entry_bar = None
            direction = None

            for i, b in enumerate(day_bars[5:], 5):
                excursion = b["close"] - day_open

                if excursion > max_above:
                    max_above = excursion
                if excursion < -max_below:
                    max_below = -excursion

                # Short: went above open, retracing toward/below open
                if max_above >= move_threshold and excursion <= entry_threshold:
                    entry_bar = b
                    direction = "short"
                    break

                # Long: went below open, retracing toward/above open
                if max_below >= move_threshold and excursion >= -entry_threshold:
                    entry_bar = b
                    direction = "long"
                    break

            if not entry_bar:
                continue

            exit_bar = None
            for b in day_bars[day_bars.index(entry_bar):]:
                if b["minute_of_day"] >= 15 * 60 + 55:
                    exit_bar = b
                    break
            if not exit_bar:
                exit_bar = day_bars[-1]

            stop_hit = False
            if direction == "long":
                stop_price = entry_bar["close"] - stop_distance
                for b in day_bars[day_bars.index(entry_bar):]:
                    if b["low"] <= stop_price:
                        stop_hit = True
                        exit_bar = b
                        break
            else:
                stop_price = entry_bar["close"] + stop_distance
                for b in day_bars[day_bars.index(entry_bar):]:
                    if b["high"] >= stop_price:
                        stop_hit = True
                        exit_bar = b
                        break

            entry_price = entry_bar["close"]
            exit_price = exit_bar["close"]
            risk_per_trade = initial_capital * 0.05
            shares = risk_per_trade / stop_distance if stop_distance > 0 else 0

            trade = Trade(
                ticker=ticker,
                entry_time=entry_bar["timestamp"],
                entry_price=entry_price,
                exit_time=exit_bar["timestamp"],
                exit_price=exit_price,
                direction=direction,
                shares=shares,
                entry_reason="OPEN_FADE",
                exit_reason="stop" if stop_hit else "eod",
            )
            all_trades.append(trade)

        print(f"[mr] {ticker}: {len([t for t in all_trades if t.ticker == ticker])} trades")

    return BacktestResult(
        name="MeanReversion_OpenFade",
        trades=all_trades,
        initial_capital=initial_capital,
    )


if __name__ == "__main__":
    result = run_mean_reversion_backtest(tickers=['AAPL','MSFT','NVDA','SPY','QQQ'], days=30)
    print(f"\n=== Mean Reversion (Open-Fade) ===")
    print(f"Trades: {len(result.trades)}")
    print(f"Win rate: {result.win_rate:.1f}%")
    print(f"Return: {result.total_return_pct:.1f}% | PF: {result.profit_factor:.2f}")
    for t in result.trades[:5]:
        print(f"  {t.ticker} {t.direction} entry={t.entry_price:.2f} exit={t.exit_price:.2f} pnl=\${t.pnl:.2f}")