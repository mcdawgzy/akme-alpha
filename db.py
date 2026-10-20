"""Database initialization and connection management.

Uses SQLite (unified purrtfolio.db convention) with read-only URI support
for the web layer, matching the 13F-scanner pattern.
"""
import sqlite3
from contextlib import contextmanager
from pathlib import Path

from .config import DB_PATH


SCHEMA = """
-- ── Yield curve data (daily, per maturity) ──────────────────────────
CREATE TABLE IF NOT EXISTS yield_curves (
    date        DATE    NOT NULL,
    maturity    TEXT    NOT NULL,   -- '3m', '5y', '10y', '30y'
    yield_pct   REAL,               -- percentage, e.g. 5.106
    source      TEXT    DEFAULT 'yahoo_finance',
    ingested_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (date, maturity)
);
CREATE INDEX IF NOT EXISTS idx_yc_date      ON yield_curves(date);
CREATE INDEX IF NOT EXISTS idx_yc_maturity  ON yield_curves(maturity);

-- ── Yield curve regime classification (daily) ───────────────────────
CREATE TABLE IF NOT EXISTS yield_curve_regime (
    date            DATE    NOT NULL PRIMARY KEY,
    spread_3m10     REAL,   -- 3-month minus 10-year (basis points)
    spread_5y10     REAL,   -- 5-year minus 10-year
    spread_3m30     REAL,   -- 3-month minus 30-year
    regime          TEXT,   -- 'STEEP', 'NORMAL', 'FLAT', 'INVERTED'
    classification  TEXT,   -- 'risk_on', 'risk_off', 'neutral', 'recession_warning'
    zscore_3m10     REAL,   -- z-score of 3m10 spread (2y lookback)
    y10_level_6m    REAL,   -- 6-month change in 10y yield (bp)
    notes           TEXT,
    created_at      DATETIME DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX IF NOT EXISTS idx_ycr_classif ON yield_curve_regime(classification);

-- ── API keys for rate-limited access ────────────────────────────────
CREATE TABLE IF NOT EXISTS api_keys (
    key        TEXT    NOT NULL PRIMARY KEY,
    tier       TEXT    NOT NULL DEFAULT 'free'
                       CHECK(tier IN ('free','pro','team')),
    label      TEXT,
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP
);

-- ── API usage log (for billing / monitoring) ────────────────────────────────
CREATE TABLE IF NOT EXISTS api_usage (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    api_key    TEXT    NOT NULL,
    endpoint   TEXT,
    tier       TEXT,
    timestamp  DATETIME DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (api_key) REFERENCES api_keys(key)
);

-- ── Commodities data (daily prices) ────────────────────────────────────────
CREATE TABLE IF NOT EXISTS commodities (
    date        DATE    NOT NULL,
    commodity   TEXT    NOT NULL,  -- 'crude_oil', 'gold', etc.
    price       REAL,             -- settlement price (USD per unit)
    ticker      TEXT,             -- Yahoo Finance ticker
    ingested_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (date, commodity)
);
CREATE INDEX IF NOT EXISTS idx_comm_date    ON commodities(date);
CREATE INDEX IF NOT EXISTS idx_comm_name    ON commodities(commodity);

-- ── Economic indicators (monthly/daily) ───────────────────────────────────
CREATE TABLE IF NOT EXISTS economic_indicators (
    date        DATE    NOT NULL,
    indicator   TEXT    NOT NULL,  -- 'cpi', 'ppi', 'fed_funds', 'unemployment'
    value       REAL,               -- indicator-specific unit
    unit        TEXT,               -- 'index', 'percent', 'billions_usd'
    frequency   TEXT,               -- 'daily', 'monthly', 'quarterly'
    ingested_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (date, indicator)
);
CREATE INDEX IF NOT EXISTS idx_econ_date    ON economic_indicators(date);
CREATE INDEX IF NOT EXISTS idx_econ_indicator ON economic_indicators(indicator);

-- ── 13F filing metadata (quarterly institutional holdings) ────────────────
CREATE TABLE IF NOT EXISTS filings_13f (
    cik           TEXT    NOT NULL,
    accession     TEXT    NOT NULL,       -- e.g. 0001193125-26-422223
    filer_name    TEXT,
    report_period DATE    NOT NULL,       -- quarter end date (e.g. 2026-09-30)
    filed_date    DATE,                   -- when the filing was submitted
    total_value   REAL,                   -- total portfolio value (USD), from SEC infoTable
    num_holdings  INTEGER,                -- number of distinct positions
    created_at    DATETIME DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (cik, accession)
);
CREATE INDEX IF NOT EXISTS idx_filings_cik           ON filings_13f(cik);
CREATE INDEX IF NOT EXISTS idx_filings_period        ON filings_13f(report_period);

-- ── 13F holdings (individual positions within a filing) ───────────────────
CREATE TABLE IF NOT EXISTS holdings_13f (
    cik            TEXT    NOT NULL,
    accession      TEXT    NOT NULL,
    name_of_issuer TEXT,
    title_of_class TEXT,
    cusip          TEXT,
    ticker         TEXT    DEFAULT '',
    shares         REAL,
    price_per_share REAL,
    value_usd      REAL,
    put_call       TEXT,
    investment_discretion TEXT,
    voting_sole    REAL,
    voting_shared  REAL,
    voting_none    REAL,
    created_at     DATETIME DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (cik, accession, cusip, put_call)
);
CREATE INDEX IF NOT EXISTS idx_holdings_cik      ON holdings_13f(cik);
CREATE INDEX IF NOT EXISTS idx_holdings_ticker   ON holdings_13f(ticker);
CREATE INDEX IF NOT EXISTS idx_holdings_accession ON holdings_13f(accession);

-- ── 13F consensus institutional flows (aggregated across funds) ────────────
CREATE TABLE IF NOT EXISTS institutional_flows (
    ticker          TEXT    NOT NULL,
    report_period   DATE    NOT NULL,
    num_funds       INTEGER,
    total_value_usd REAL,
    net_change_shares REAL,
    net_change_usd  REAL,
    pct_change      REAL,
    top_holder_cik  TEXT,
    top_holder_value REAL,
    created_at      DATETIME DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (ticker, report_period)
);
CREATE INDEX IF NOT EXISTS idx_flows_ticker ON institutional_flows(ticker);
CREATE INDEX IF NOT EXISTS idx_flows_period ON institutional_flows(report_period);

-- ── 13F ingestion audit log ───────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS ingestion_log_13f (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    run_date      DATE    NOT NULL,
    run_start     DATETIME,
    run_end       DATETIME,
    status        TEXT,
    filings_found INTEGER,
    filings_processed INTEGER,
    holdings_written INTEGER,
    error_message TEXT,
    created_at    DATETIME DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX IF NOT EXISTS idx_log_date ON ingestion_log_13f(run_date);

-- ── FINRA Short Interest (bi-weekly per ticker, aggregate) ─────────────────
CREATE TABLE IF NOT EXISTS short_interest (
    id              INTEGER PRIMARY KEY,
    symbol          TEXT    NOT NULL,
    settlement_date DATE    NOT NULL,
    issue_name      TEXT,
    exchange        TEXT,
    current_short   BIGINT,
    previous_short  BIGINT,
    avg_daily_volume BIGINT,
    days_to_cover   REAL,
    change_pct      REAL,
    change_abs      BIGINT,
    revision_flag   TEXT,
    stock_split_flag TEXT,
    ingested_at     DATETIME DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(symbol, settlement_date)
);
CREATE INDEX IF NOT EXISTS idx_si_symbol_date ON short_interest(symbol, settlement_date);
CREATE INDEX IF NOT EXISTS idx_si_date         ON short_interest(settlement_date);
CREATE INDEX IF NOT EXISTS idx_si_dtc          ON short_interest(days_to_cover);
CREATE INDEX IF NOT EXISTS idx_si_short        ON short_interest(current_short DESC);

-- ── Short interest pre-computed aggregates per ticker ─────────────────────
CREATE TABLE IF NOT EXISTS ticker_short_meta (
    ticker          TEXT    NOT NULL,
    latest_date     DATE,
    latest_short    BIGINT,
    latest_dtc      REAL,
    latest_change_pct REAL,
    peak_short      BIGINT,
    peak_date       DATE,
    avg_short_12m   BIGINT,
    pct_of_ff       REAL,
    signal          TEXT,
    updated_at      DATETIME DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (ticker)
);

-- ── Short interest ingestion audit log ────────────────────────────────────
CREATE TABLE IF NOT EXISTS ingestion_log_si (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    run_date        DATE    NOT NULL,
    run_start       DATETIME,
    run_end         DATETIME,
    status          TEXT,
    rows_fetched    INTEGER,
    rows_written    INTEGER,
    settlement_date DATE,
    error_message   TEXT,
    created_at      DATETIME DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX IF NOT EXISTS idx_log_si_date ON ingestion_log_si(run_date);
"""


@contextmanager
def get_connection(db_path: str | Path | None = None, read_only: bool = False):
    """Yield a SQLite connection, autocommit, with Row factory."""
    path = Path(db_path) if db_path else DB_PATH
    if read_only:
        uri = f"file:{path}?mode=ro"
        conn = sqlite3.connect(uri, uri=True, check_same_thread=False)
    else:
        path.parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(str(path), check_same_thread=False)
    conn.row_factory = sqlite3.Row
    try:
        yield conn
    finally:
        conn.close()


def init_db(db_path: str | Path | None = None) -> Path:
    """Create all tables (idempotent) and seed default API keys."""
    path = Path(db_path) if db_path else DB_PATH
    path.parent.mkdir(parents=True, exist_ok=True)
    with get_connection(path) as conn:
        conn.executescript(SCHEMA)
        # Seed API keys
        from .config import SEED_API_KEYS
        for key, tier in SEED_API_KEYS.items():
            conn.execute(
                "INSERT OR IGNORE INTO api_keys (key, tier, label) VALUES (?, ?, ?)",
                (key, tier, f"Seed {tier} key"),
            )
        conn.commit()
    return path


def get_tier_limit(conn, api_key: str):
    """Return (tier, daily_limit) or (None, None) if key invalid."""
    row = conn.execute(
        "SELECT tier FROM api_keys WHERE key = ?", (api_key,)
    ).fetchone()
    if not row:
        return None, None
    from .config import TIERS
    return row["tier"], TIERS[row["tier"]]["daily_limit"]


def count_requests_today(conn, api_key: str) -> int:
    """Count API requests made today by this key."""
    return conn.execute(
        """SELECT COUNT(*) FROM api_usage
           WHERE api_key = ? AND date(timestamp) = date('now')""",
        (api_key,),
    ).fetchone()[0]


def log_request(conn, api_key: str, endpoint: str, tier: str):
    """Record a request for rate-limiting and analytics."""
    conn.execute(
        "INSERT INTO api_usage (api_key, endpoint, tier) VALUES (?, ?, ?)",
        (api_key, endpoint, tier),
    )
