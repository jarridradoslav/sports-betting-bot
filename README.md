# Sports Betting +EV Scanner

A fully automated pipeline that connects to The Odds API, removes sportsbook
vig, and surfaces positive-expected-value betting opportunities in real time.

---

## Project Structure

```
sports-betting-bot/
├── config.py          — API key, sports list, thresholds, alert channels
├── database.py        — SQLite schema, inserts, queries
├── odds_fetcher.py    — The Odds API calls + response normalisation
├── probability.py     — Odds conversion & vig removal math
├── ev_calculator.py   — EV formula, best-line selection
├── scanner.py         — Grouping, EV loop, alerts, line-movement detection
├── main.py            — Entry point (single run or scheduled loop)
└── README.md
```

---

## Setup

### 1. Install dependencies

```bash
pip install requests
```

### 2. Get an API key

Sign up at <https://the-odds-api.com> and copy your key.

### 3. Configure

Open `config.py` and set your API key:

```python
API_KEY = "your_key_here"
```

Or export it as an environment variable (recommended):

```bash
export ODDS_API_KEY="your_key_here"
```

### 4. (Optional) Alert channels

**Discord**

```bash
export DISCORD_WEBHOOK_URL="https://discord.com/api/webhooks/..."
```

**Telegram**

```bash
export TELEGRAM_BOT_TOKEN="your_bot_token"
export TELEGRAM_CHAT_ID="your_chat_id"
```

---

## Running

### Single run

```bash
python main.py
```

### Continuous loop (every 5 minutes)

```bash
python main.py --loop
```

### Schedule with cron (Linux / macOS)

```cron
*/5 * * * * cd /path/to/sports-betting-bot && python main.py >> scanner.log 2>&1
```

### Schedule with Task Scheduler (Windows)

Create a Basic Task that runs every 5 minutes:

```
Action: Start a program
Program: python
Arguments: main.py
Start in: C:\path\to\sports-betting-bot
```

---

## How EV is Calculated

### Step 1 — Convert American odds to implied probability

```
Positive odds:  P = 100 / (odds + 100)
Negative odds:  P = |odds| / (|odds| + 100)
```

### Step 2 — Remove vig (normalise)

Books bake margin into prices so all probabilities sum to more than 100 %.

```
true_prob = implied_prob / sum(all_implied_probs_in_market)
```

The scanner averages this across every book that quotes the full market,
giving a "consensus" true probability.

### Step 3 — Find the best available odds

The highest decimal price across all sportsbooks for that outcome.

### Step 4 — Calculate EV

```
EV = true_prob × (decimal_odds − 1) − (1 − true_prob)
```

A positive value means you expect to profit per unit staked.

Only bets with EV ≥ 3 % (configurable via `MIN_EV_THRESHOLD` in `config.py`)
generate an alert.

---

## Database

SQLite file: `odds_history.db`

| Table            | Purpose                                       |
|------------------|-----------------------------------------------|
| `odds_snapshots` | Full timestamped history of every odds pull   |
| `ev_alerts`      | Every +EV alert that was fired                |
| `clv_tracking`   | Track bet_odds vs closing_odds (CLV)          |

Query examples:

```sql
-- All +EV alerts today
SELECT * FROM ev_alerts WHERE date(timestamp) = date('now') ORDER BY ev DESC;

-- Line movement history for one event
SELECT bookmaker, outcome, odds, timestamp
FROM odds_snapshots
WHERE event_id = '<id>' AND market = 'h2h'
ORDER BY timestamp;

-- Closing Line Value (once you fill closing_odds)
SELECT outcome, bet_odds, closing_odds, (closing_odds - bet_odds) AS clv
FROM clv_tracking;
```

---

## Closing Line Value (CLV)

The `clv_tracking` table lets you measure whether your bets beat the closing
price. Positive CLV is the best long-run indicator of a genuine edge.

To record a bet, insert a row:

```python
import database as db, sqlite3
with db.get_connection() as conn:
    conn.execute("""
        INSERT INTO clv_tracking
            (event_id, sport, market, outcome, bookmaker, bet_odds, bet_timestamp)
        VALUES (?, ?, ?, ?, ?, ?, ?)
    """, (event_id, sport, market, outcome, bookmaker, bet_odds, db.now_utc()))
```

Before game time, run a query to fill in `closing_odds` from `odds_snapshots`.

---

## Configuration Reference

| Setting                    | Default    | Description                                   |
|----------------------------|------------|-----------------------------------------------|
| `API_KEY`                  | —          | Your Odds API key                             |
| `SPORTS`                   | NBA/NHL/NFL| List of sport keys to monitor                 |
| `MIN_EV_THRESHOLD`         | `0.03`     | Minimum EV (3 %) to trigger an alert          |
| `LINE_MOVEMENT_THRESHOLD`  | `7`        | Odds-point shift flagged as sharp money       |
| `POLL_INTERVAL_SECONDS`    | `300`      | Loop sleep time (5 minutes)                   |
