# config.py
# Central configuration for the EV scanner.
# Edit this file before running for the first time.

import os

# ---------------------------------------------------------------------------
# The Odds API
# ---------------------------------------------------------------------------
API_KEY = os.getenv("ODDS_API_KEY", "YOUR_API_KEY_HERE")
BASE_URL = "https://api.the-odds-api.com/v4"

# Sports to monitor.  Add / remove from this list freely.
SPORTS = [
    "basketball_nba",
    "icehockey_nhl",
    "americanfootball_nfl",
]

REGIONS = "us"
MARKETS = "h2h,spreads,totals"
ODDS_FORMAT = "american"

# ---------------------------------------------------------------------------
# Database
# ---------------------------------------------------------------------------
DB_PATH = "odds_history.db"

# ---------------------------------------------------------------------------
# EV / scanning thresholds
# ---------------------------------------------------------------------------
MIN_EV_THRESHOLD = 0.03          # Flag bets with EV >= 3 %
LINE_MOVEMENT_THRESHOLD = 7      # Odds-point shift that counts as "sharp move"
                                 # (e.g. spread moves by 2 pts, or ML moves 7+)

# ---------------------------------------------------------------------------
# Scheduler
# ---------------------------------------------------------------------------
POLL_INTERVAL_SECONDS = 300      # Run pipeline every 5 minutes

# ---------------------------------------------------------------------------
# Alert channels (optional — leave blank to skip)
# ---------------------------------------------------------------------------
DISCORD_WEBHOOK_URL = os.getenv("DISCORD_WEBHOOK_URL", "")
TELEGRAM_BOT_TOKEN  = os.getenv("TELEGRAM_BOT_TOKEN",  "")
TELEGRAM_CHAT_ID    = os.getenv("TELEGRAM_CHAT_ID",    "")
