"""Generic backtest engine — position tracking, P&L, and statistics.

Pure Python stdlib only (no pandas dependency). Trades are simulated with
realistic fill assumptions. Designed for bias audit: every fill is keyed
to information available at that moment (no lookahead).
"""
from __future__ import annotations

import statistics
from dataclasses import dataclass, field
from typing import Optional


@dataclass
class Trade:
    """A single completed trade."""
    ticker: str
    entry_time: str   # ISO timestamp of entry bar close
    entry_price: float
    exit_time: str    # ISO timestamp of exit bar close
    exit_price: float
    direction: str    # 'long' or 'short'
    shares: float
    entry_reason: str
    exit_reason: str
    pnl: float = field(init=False)
    pnl_pct: float = field(init=False)

    def __post_init__(self):
        self.pnl = (self.exit_price - self.entry_price) * self.shares if self.direction == "long" else (self.entry_price - self.exit_price) * self.shares
        self.pnl_pct = (self.exit_price - self.entry_price) / self.entry_price * 100 if self.direction == "long" else (self.entry_price - self.exit_price) / self.entry_price * 100


@dataclass
class BacktestResult:
    """Aggregated backtest results."""
    name: str
    trades: list[Trade]
    initial_capital: float = 10000.0

    @property
    def total_pnl(self) -> float:
        return sum(t.pnl for t in self.trades)

    @property
    def total_return_pct(self) -> float:
        return (self.total_pnl / self.initial_capital) * 100

    @property
    def win_rate(self) -> float:
        if not self.trades:
            return 0.0
        return sum(1 for t in self.trades if t.pnl > 0) / len(self.trades) * 100

    @property
    def avg_win(self) -> float:
        wins = [t.pnl for t in self.trades if t.pnl > 0]
        return statistics.mean(wins) if wins else 0.0

    @property
    def avg_loss(self) -> float:
        losses = [t.pnl for t in self.trades if t.pnl < 0]
        return statistics.mean(losses) if losses else 0.0

    @property
    def median_trade(self) -> float:
        if not self.trades:
            return 0.0
        return statistics.median(t.pnl for t in self.trades)

    @property
    def profit_factor(self) -> float:
        wins = sum(t.pnl for t in self.trades if t.pnl > 0)
        losses = abs(sum(t.pnl for t in self.trades if t.pnl < 0))
        if losses == 0:
            return float("inf") if wins > 0 else 0.0
        return wins / losses

    @property
    def max_drawdown_pct(self) -> float:
        """Max drawdown on cumulative equity curve."""
        if not self.trades:
            return 0.0
        equity = self.initial_capital
        peak = equity
        max_dd = 0.0
        for t in self.trades:
            equity += t.pnl
            if equity > peak:
                peak = equity
            dd = (peak - equity) / peak * 100 if peak > 0 else 0
            max_dd = max(max_dd, dd)
        return max_dd

    @property
    def max_consecutive_wins(self) -> int:
        if not self.trades:
            return 0
        best = cur = 0
        for t in self.trades:
            if t.pnl > 0:
                cur += 1
                best = max(best, cur)
            else:
                cur = 0
        return best

    @property
    def max_consecutive_losses(self) -> int:
        if not self.trades:
            return 0
        best = cur = 0
        for t in self.trades:
            if t.pnl < 0:
                cur += 1
                best = max(best, cur)
            else:
                cur = 0
        return best

    def equity_curve(self) -> list[tuple[str, float]]:
        """Return [(timestamp, cumulative_pnl), ...] for plotting."""
        equity = self.initial_capital
        curve = [(self.trades[0].entry_time, equity)] if self.trades else []
        for t in self.trades:
            equity += t.pnl
            curve.append((t.exit_time, equity))
        return curve


@dataclass
class Bar:
    """Single OHLCV bar."""
    timestamp: str
    open: float
    high: float
    low: float
    close: float
    volume: Optional[int] = None


@dataclass
class Position:
    """Open position tracker."""
    ticker: str
    direction: str   # 'long' or 'short'
    entry_price: float
    shares: float
    entry_time: str
    stop_loss: Optional[float] = None
    target: Optional[float] = None
