"""Global configuration for the akme-alpha stack."""
from pathlib import Path

BASE_DIR = Path(__file__).parent
DATA_DIR = BASE_DIR / "data"
DB_PATH = DATA_DIR / "akme_alpha.db"

# API tier definitions: daily request allowance
TIERS = {
    "free": {"daily_limit": 100, "price": 0, "label": "Free"},
    "pro": {"daily_limit": 1_000, "price": 49, "label": "Pro"},
    "team": {"daily_limit": 10_000, "price": 299, "label": "Team"},
}

# Default seeded API keys (replace in production with a registration flow)
# Format: {key: tier}
SEED_API_KEYS = {
    "dl_free_demo": "free",
    "dl_pro_demo": "pro",
    "dl_team_demo": "team",
}
