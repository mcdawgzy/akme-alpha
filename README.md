# Akme Alpha — Public Market Data API

A free, rate-limited API delivering highly digestible market data summaries for traders and analysts.

## What's Built (as of 2026-10-19)

### ✅ Yield Curve Regime API (`/api/yield-curve/regime`)
- **Data source**: Yahoo Finance CBOE indices (no API key required)
- **Coverage**: 3-month, 5-year, 10-year, 30-year Treasury yields
- **Outputs**: 
  - 3m10s spread (recession predictor signal)
  - Z-score vs 2-year history
  - Regime classification: `NORMAL`, `FLAT`, `STEEP`, `INVERTED`
  - Market classification: `risk_on`, `risk_off`, `neutral`, `recession_warning`
  - One-sentence trader digest

### ✅ Rate-Limited API
- Free tier: 100 req/day
- Pro: $49/month for 1,000 req/day
- Team: $299/month for 10,000 req/day
- API key authentication via `Authorization: Bearer <key>`

### ✅ Daily Cron Pipeline
- Scheduled via Hermes cron: `0 6 * * *` (6 AM UTC+10)
- Fetches latest yields, computes regime, persists to SQLite

## API Endpoints

```
GET /api/yield-curve/regime          Latest regime + digest
GET /api/yield-curve/history?days=N  Historical regimes (max 365)
GET /api/yield-curve/latest          Raw curve data only
POST /api/register                   Generate free-tier key
GET  /api/tiers                      Tier definitions
GET  /api/me                         Identity / debug
```

## Placeholder Endpoints (need data pipeline support)

```
GET /api/institutional-flows    → 13F consensus positions
GET /api/short-interest-ratio   → FINRA short interest & squeeze signals
GET /api/factor-exposure        → Hedge fund factor exposures
```

## Next Steps

1. **Build SEC EDGAR pipelines** — Automate 13F, Form 4, 8-K, 13D/G ingestion
2. **Add economic data sources** — CPI/PPI (BLS), FRED, EIA, CFTC COT
3. **Deploy to Render** — Free tier with daily keep-alive cron
4. **Productionize rate limiting** — Redis-backed for multi-instance scale

## Local Development

```bash
# Install dependencies
pip install fastapi uvicorn httpx

# Initialize DB
python -c "from akme_alpha.db import init_db; init_db()"

# Run daily ingestion
python -m akme_alpha.scanners.yield_curves.ingest
python -m akme_alpha.scanners.yield_curves.analyze

# Test API
uvicorn akme_alpha.main:app --port 8000
curl localhost:8000/api/yield-curve/regime
```

## Deployment

```bash
# Push to GitHub
git add .
git commit -m "Initial release: yield curve regime API"
git push origin main

# Create render.yaml (auto-deploy on push)
# Render will detect and build
```

## Database Schema

- `yield_curves` — Daily maturity yields (3m, 5y, 10y, 30y)
- `yield_curve_regime` — Computed regime, classification, z-score, notes
- `api_keys` — User API keys with tier metadata
- `api_usage` — Request log for rate limiting

## Data Sources

| Source | Access | Notes |
|--------|--------|-------|
| Yahoo Finance CBOE indices | No key | 3m(^IRX), 5y(^FVX), 10y(^TNX), 30y(^TYX) |
| SEC EDGAR | Free | Daily index HTTP (S3 API deprecated) |
| FINRA | Free | Bi-weekly short interest CSV |
| BLS CPI/PPI | API key | Inflation data |
| FRED | API key | Yield curves, rates, indices |
| EIA | API key | Energy prices |
| CFTC | No key | Commitments of Traders (weekly) |