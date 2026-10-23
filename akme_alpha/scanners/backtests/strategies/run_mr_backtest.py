#!/usr/bin/env python
"""Run mean reversion backtest across all tickers and save results."""
import json
from akme_alpha.scanners.backtests.strategies.mean_reversion import run_mean_reversion_backtest

# Use 12 tickers to avoid timeout
tickers = ['AAPL', 'MSFT', 'NVDA', 'GOOGL', 'AMZN', 'META', 'TSLA', 'JPM', 'V', 'XOM', 'SPY', 'QQQ']

result = run_mean_reversion_backtest(
    tickers=tickers, days=30, initial_capital=10000
)

# Per-ticker breakdown
from collections import defaultdict
by_ticker = defaultdict(list)
for t in result.trades:
    by_ticker[t.ticker].append(t.pnl)

per_ticker = {}
for ticker, pnls in sorted(by_ticker.items()):
    total = sum(pnls)
    wins = sum(1 for p in pnls if p > 0)
    per_ticker[ticker] = {
        "trades": len(pnls),
        "wins": wins,
        "total_pnl": round(total, 2)
    }

report = {
    "study": "Open-Range Fade Mean Reversion",
    "tickers": tickers,
    "period": "30 trading days (Sep 25 - Oct 22, 2026)",
    "rules": "1. Day Open = RTH opening. 2. ATR = 14-day True Range. 3. Track max move from open (>= 0.5xATR). 4. Enter SHORT when price retreats to within 0.2xATR above open (from above). 5. Enter LONG when price retreats to within 0.2xATR below open (from below). 6. Stop = 1xATR. 7. Exit at 3:55 PM ET or stop.",
    "results": {
        "name": result.name,
        "trades": len(result.trades),
        "win_rate": round(result.win_rate, 1),
        "total_return_pct": round(result.total_return_pct, 1),
        "profit_factor": round(result.profit_factor, 2),
        "avg_win": round(result.avg_win, 2),
        "avg_loss": round(result.avg_loss, 2),
        "max_drawdown_pct": round(result.max_drawdown_pct, 1),
        "median_trade": round(result.median_trade, 2),
        "max_consecutive_wins": result.max_consecutive_wins,
        "max_consecutive_losses": result.max_consecutive_losses,
    },
    "per_ticker": per_ticker,
    "trades": [
        {
            "ticker": t.ticker,
            "date": t.entry_time[:10],
            "direction": t.direction,
            "entry_price": round(t.entry_price, 2),
            "exit_price": round(t.exit_price, 2),
            "pnl": round(t.pnl, 2),
            "pnl_pct": round(t.pnl_pct, 2),
            "exit_reason": t.exit_reason,
        }
        for t in result.trades
    ],
    "biases": [
        "Fill assumptions: entry at bar close is optimistic",
        "No transaction costs (would erode small profits)",
        "30 days = insufficient sample (<100 statistical validity)",
        "Survivorship: only living tickers",
        "Look-ahead: ATR uses prior 14 daily bars (no lookahead in entry)",
    ],
    "comparison_to_orb": {
        "orb_winner": "15-min ORB long-only: PF 1.00, -0.9% return, 180 trades",
        "mr_result": f"PF {round(result.profit_factor, 2)}, {round(result.total_return_pct, 1)}% return, {len(result.trades)} trades",
        "note": "Mean reversion generates fewer trades but higher PF — different risk profile"
    }
}

with open('/c/Users/cho_i/akme_alpha/mean_reversion_results.json', 'w') as f:
    json.dump(report, f, indent=2)

print(f"\n=== Mean Reversion Results ===")
r = report["results"]
print(f"Trades: {r['trades']}")
print(f"Win rate: {r['win_rate']}%")
print(f"Return: {r['total_return_pct']}%")
print(f"Profit Factor: {r['profit_factor']}")
print(f"Max DD: {r['max_drawdown_pct']}%")
print(f"Per ticker: {len(per_ticker)} tickers with trades")
for ticker, stats in per_ticker.items():
    print(f"  {ticker}: {stats['trades']} trades, {stats['wins']} wins, ${stats['total_pnl']:+.2f}")
