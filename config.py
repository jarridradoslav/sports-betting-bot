# config.py
# Central configuration for the EV scanner.
# Edit this file before running for the first time.

import os

# ---------------------------------------------------------------------------
# OddsPapi API
# ---------------------------------------------------------------------------
API_KEY = os.getenv("ODDS_API_KEY", "3c1341eb-a528-41d3-9ded-ac4dc64dd3dd")
BASE_URL = "https://api.oddspapi.io/v4"

# Sports to monitor — matched against sport names returned by the API.
# These are search terms; the fetcher will find the correct sport IDs
# automatically on startup.
SPORTS = [
    "basketball",   # NBA
    "ice hockey",   # NHL
    "american football",  # NFL
]

ODDS_FORMAT = "american"   # decimal | american

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
