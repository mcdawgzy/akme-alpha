#!/usr/bin/env python3
"""Macro Regime Positioning Strategy (Regime State → Sector/Ticker Tilt).

This strategy uses the 4-state regime verdict to determine market exposure:
- Expansion: Long growth/cyclical, commodities
- Recovery: Long value/quality, dividend stocks  
- Slowdown: Defensive tilt (utilities, staples, quality duration)
- Recession: Cash + treasuries + gold

Market impact: In a true slowdown, cash-like exposure beats equities.
In recession, duration outperforms (especially long-end).
In expansion, cyclicals and tech lead.
"""
import json
import sqlite3
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from enum import Enum
from pathlib import Path
from typing import Optional


# ── Position Sizing by Regime ──────────────────────────────────────────────
REGIME_ALLOCATION = {
    "Expansion": {
        "equity_exposure": 1.0,
        "sectors": {
            "tech": 0.30,      # NVDA, MSFT, GOOGL
            "cyclical": 0.25,  # AAPL, AMZN, TSLA
            "momentum": 0.20,  # QQQ, SPY
            "commodities": 0.15,  # GSG, DBC
            "cash": 0.10,
        },
        "description": "Growth leader — tech and cyclicals outperform"
    },
    "Recovery": {
        "equity_exposure": 0.90,
        "sectors": {
            "value": 0.30,     # JPM, BAC, financials
            "quality": 0.25,   # dividend payers
            "momentum": 0.20,
            "duration": 0.15,  # long treasuries
            "cash": 0.10,
        },
        "description": "Value rotation — financials and dividend payers lead"
    },
    "Slowdown": {
        "equity_exposure": 0.70,
        "sectors": {
            "defensive": 0.35, # utilities, staples
            "quality": 0.25,   # AAPL, MSFT (quality names)
            "duration": 0.25,  # long treasuries
            "cash": 0.15,
        },
        "description": "Defensive rotation — quality and duration lead"
    },
    "Recession": {
        "equity_exposure": 0.30,
        "sectors": {
            "duration": 0.40,  # long treasuries
            "gold": 0.20,      # IAU, SLV
            "quality": 0.20,   # defensive equities
            "cash": 0.20,
        },
        "description": "Cash and duration — equities underperform"
    },
}

# Ticker mapping by sector
SECTOR_TICKERS = {
    "tech": ["NVDA", "MSFT", "GOOGL"],
    "cyclical": ["AAPL", "AMZN", "TSLA"],
    "value": ["JPM", "BAC", "XLF"],
    "defensive": ["XLU", "XLP", "XLY"],
    "momentum": ["QQQ", "SPY", "IWM"],
    "duration": ["TLT", "IEF", "BND"],
    "commodities": ["GLD", "SLV", "DBC"],
    "gold": ["IAU", "SLV"],
    "quality": ["AAPL", "MSFT", "JNJ"],
    "cash": [],  # Cash is cash
}


@dataclass
class RegimePosition:
    """A single position based on regime allocation."""
    date: str
    regime: str
    allocation: dict
    tickers: list
    weight: float
    decision: str  # "enter" or "hold" or "exit"


@dataclass
class RegimeBacktestResult:
    """Results from regime positioning backtest."""
    name: str = "RegimePositioning"
    regime_history: list = field(default_factory=list)
    positions: list = field(default_factory=list)
    daily_pnl: list = field(default_factory=list)
    total_return_pct: float = 0.0
    max_drawdown_pct: float = 0.0
    win_rate: float = 0.0
    avg_win: float = 0.0
    avg_loss: float = 0.0
    median_trade: float = 0.0
    contracts_held: int = 0
    regime_switches: int = 0


class RegimePositioningStrategy:
    """Backtest regime-based market positioning."""

    def __init__(self, db_path: str = None):
        self.db_path = db_path or "C:/Users/cho_i/akme_alpha/akme_alpha/data/akme_alpha.db"
        self.portfolio = {
            "cash": 10000.0,
            "positions": {},  # ticker -> {qty, cost_basis, value}
            "equity": 0.0,
            "total_value": 10000.0,
        }
        self.history = []
        self.pnl_history = []

    def _get_regime_history(self, start_date: str = None, days: int = 365) -> list:
        """Fetch regime history from DB."""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()

        if start_date:
            cursor.execute(
                "SELECT date, verdict, composite_score FROM regime_daily WHERE date >= ? ORDER BY date DESC LIMIT ?",
                (start_date, days)
            )
        else:
            cursor.execute(
                "SELECT date, verdict, composite_score FROM regime_daily ORDER BY date DESC LIMIT ?",
                (days,)
            )

        rows = cursor.fetchall()
        conn.close()

        # Sort by date ascending (oldest first)
        return sorted([{
            "date": r[0],
            "verdict": r[1],
            "score": r[2],
        } for r in rows], key=lambda x: x["date"])

    def _get_price(self, ticker: str, date: str) -> Optional[float]:
        """Get closing price for a ticker on a date from DB or Yahoo."""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()

        # Check if we have daily price data in DB
        try:
            cursor.execute(
                "SELECT close FROM price_daily WHERE ticker = ? AND date = ? LIMIT 1",
                (ticker, date)
            )
            row = cursor.fetchone()
            if row:
                conn.close()
                return row[0]
        except:
            pass
        finally:
            conn.close()

        # Fallback: return None (will skip price calc)
        return None

    def _generate_tickers_for_regime(self, regime: str) -> list:
        """Generate list of tickers to hold for a regime."""
        alloc = REGIME_ALLOCATION.get(regime, REGIME_ALLOCATION["Slowdown"])
        tickers = []

        for sector, weight in alloc.get("sectors", {}).items():
            if sector == "cash":
                continue
            sector_tickers = SECTOR_TICKERS.get(sector, [])
            # Distribute weight across sector tickers
            per_ticker = weight / len(sector_tickers) if sector_tickers else 0
            for t in sector_tickers:
                tickers.append({"ticker": t, "weight": per_ticker, "sector": sector})

        return tickers

    def simulate(self, days: int = 365, initial_capital: float = 100000.0) -> RegimeBacktestResult:
        """Run regime positioning simulation."""
        result = RegimeBacktestResult()
        result.name = f"RegimePositioning_{days}d"

        # Get regime history
        history = self._get_regime_history(days=days)
        result.regime_history = history

        if not history:
            print("[regime_pos] No regime data available")
            return result

        # Track portfolio
        cash = initial_capital
        positions = {}  # ticker -> qty
        daily_values = [initial_capital]

        for i, row in enumerate(history):
            date = row["date"]
            regime = row["verdict"]

            # Get target allocation
            target_tickers = self._generate_tickers_for_regime(regime)

            # Calculate current equity value
            equity_value = 0.0
            for t, qty in positions.items():
                price = self._get_price(t, date)
                if price:
                    equity_value += qty * price

            total_value = cash + equity_value
            daily_values.append(total_value)

            # Determine if regime changed
            regime_changed = (i > 0 and history[i-1]["verdict"] != regime)
            if regime_changed:
                result.regime_switches += 1

            # Store position decision
            pos = RegimePosition(
                date=date,
                regime=regime,
                allocation=REGIME_ALLOCATION.get(regime, {}),
                tickers=[t["ticker"] for t in target_tickers],
                weight=1.0 if regime_changed else 0.0,
                decision="enter" if regime_changed else "hold"
            )
            result.positions.append(pos)

            # Rebalance simulation (simplified: assume we enter on regime change)
            # This is a simplified model - actual trading would need more sophistication
            if regime_changed:
                # Exit existing positions, enter new
                positions = {}
                for t_info in target_tickers:
                    ticker = t_info["ticker"]
                    weight = t_info["weight"]
                    price = self._get_price(ticker, date) or 100.0  # Simplified
                    
                    # Allocate weight% of equity
                    target_value = total_value * weight * 0.8  # 80% of regime allocation
                    qty = target_value / price
                    positions[ticker] = qty
                    cash -= qty * price

        # Calculate final values
        cash += sum(qty * (self._get_price(t, history[-1]["date"]) or 100.0) 
                   for t, qty in positions.items())
        final_value = cash

        result.daily_pnl = daily_values
        result.total_return_pct = (final_value / initial_capital - 1) * 100
        result.max_drawdown_pct = self._calc_max_dd(daily_values)

        return result

    def _calc_max_dd(self, values: list) -> float:
        """Calculate maximum drawdown percentage."""
        if not values:
            return 0.0
        peak = values[0]
        max_dd = 0.0
        for v in values[1:]:
            if v > peak:
                peak = v
            dd = (peak - v) / peak * 100 if peak > 0 else 0
            max_dd = max(max_dd, dd)
        return round(max_dd, 2)


def run_regime_backtest(days: int = 365, initial_capital: float = 100000.0) -> RegimeBacktestResult:
    """Run regime positioning backtest."""
    strat = RegimePositioningStrategy()
    return strat.simulate(days=days, initial_capital=initial_capital)


if __name__ == "__main__":
    result = run_regime_backtest(days=365, initial_capital=100000.0)
    print(f"=== Regime Positioning Backtest ===")
    print(f"Trades: {len(result.positions)}")
    print(f"Regime switches: {result.regime_switches}")
    print(f"Return: {result.total_return_pct:+.1f}%")
    print(f"Max DD: {result.max_drawdown_pct:.1f}%")
    print(f"Recent regimes: {[h['verdict'] for h in result.regime_history[-5:]]}")