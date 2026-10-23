"""Backtests sub-package — transparent, bias-audited strategy backtesting engine.

Follows the Milkman Trades model: precise rules, adversarial AI review,
transparent publication of results including failures.

Structure:
    data.py   — data fetching (Yahoo Finance 1m/1d bars)
    engine.py — generic position-tracking + P&L statistics engine
    strategies.orb — Opening Range Breakout strategy

Usage:
    from akme_alpha.scanners.backtests.strategies.orb import run_orb_backtest
    results = run_orb_backtest(tickers=["SPY","AAPL",...], days=60)
"""
from .data import fetch_1m, fetch_daily
from .engine import BacktestResult
