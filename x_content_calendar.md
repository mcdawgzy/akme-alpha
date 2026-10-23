# X/Twitter Content Calendar

| Day | Post | Thread Type | Notes |
|-----|------|-------------|-------|
| Mon | Weekend strategy thread | `strategy` | Deep dive: new/backtested strategy |
| Tue | Regime shift update + PNG | `regime` | Auto-post from cron at 7 AM, manual if no creds |
| Wed | Data vault release | `data_vault` | New CSV + script, tagged with strategy link |
| Thu | Forward test update | `strategy` | Paper account P&L (future) |
| Fri | Market wrap + next week plan | `weekly` | Weekly recap + preview |
| Sat | Failed study spotlight | `failed` | From "The Graveyard" archive |
| Sun | Weekly recap tweet | `weekly` | Summary of week's posts |

## Current Queue (next 7 days)

### ✅ Ready to post:
1. **Regime update** — `thread_templates.py regime` → ready
2. **Mean reversion strategy thread** — `thread_templates.py strategy` → ready
3. **Data vault: regime yield curve history** — `thread_templates.py data_vault --csv regime_yield_curve_history.csv` → ready

### Draft queue:
4. **Failed study spotlight**: "ORB 5-min variant" — PF 0.83, -100% return
5. **Data vault: short interest latest** — CSV release
6. **Weekly recap** — summary of first week of posting

## Thread templates location
Scripts: `~/AppData/Local/hermes/scripts/x_thread_templates.py`
Output: `~/AppData/Local/hermes/cron/output/x_threads/`
Regime PNG: `~/AppData/Local/hermes/cron/output/regime_indicator/latest.png`

## Posting modes
- Auto: `cron:akme-alpha-regime-x-poster` (runs daily 7 AM, needs TWITTER_API_* env vars)
- Manual: scripts write to output/x_threads/ for copy-paste posting
