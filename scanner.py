# scanner.py
# Orchestrates: group data → find best lines → calculate EV → alert.
# Also handles line-movement detection and CLV tracking.

import logging
from collections import defaultdict
from typing import Optional

import requests

import config
import database as db
from ev_calculator import evaluate_outcome
from probability import american_to_implied

logger = logging.getLogger(__name__)


# --------------------------------------------------------------------------- #
# Step 7 — Alerts                                                             #
# --------------------------------------------------------------------------- #

def _format_alert(alert: dict) -> str:
    sport_label = alert["sport"].replace("_", " ").title()
    ev_pct      = alert["ev"] * 100
    true_pct    = alert["true_probability"] * 100
    odds_str    = (f'+{alert["best_odds"]:.0f}'
                   if alert["best_odds"] >= 0
                   else f'{alert["best_odds"]:.0f}')

    return (
        "\n"
        "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
        "+EV Bet Found\n"
        "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
        f"Sport:            {sport_label}\n"
        f"Game:             {alert['away_team']} @ {alert['home_team']}\n"
        f"Market:           {alert['market'].upper()}\n"
        f"Outcome:          {alert['outcome']}\n"
        f"Book:             {alert['best_book']}\n"
        f"Odds:             {odds_str}\n"
        f"True Probability: {true_pct:.1f}%\n"
        f"Expected Value:   +{ev_pct:.1f}%\n"
        "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
    )


def send_alert(alert: dict) -> None:
    """Print alert and optionally push to Discord / Telegram."""
    msg = _format_alert(alert)
    print(msg)

    # --- Discord ---
    if config.DISCORD_WEBHOOK_URL:
        try:
            requests.post(
                config.DISCORD_WEBHOOK_URL,
                json={"content": f"```\n{msg}\n```"},
                timeout=10,
            )
        except Exception as exc:
            logger.warning("Discord alert failed: %s", exc)

    # --- Telegram ---
    if config.TELEGRAM_BOT_TOKEN and config.TELEGRAM_CHAT_ID:
        try:
            requests.post(
                f"https://api.telegram.org/bot{config.TELEGRAM_BOT_TOKEN}/sendMessage",
                json={
                    "chat_id": config.TELEGRAM_CHAT_ID,
                    "text":    f"<pre>{msg}</pre>",
                    "parse_mode": "HTML",
                },
                timeout=10,
            )
        except Exception as exc:
            logger.warning("Telegram alert failed: %s", exc)


# --------------------------------------------------------------------------- #
# Step 9 — Line-movement detection                                            #
# --------------------------------------------------------------------------- #

def check_line_movement(event_id: str, market: str,
                         outcome: str, current_best: float) -> None:
    """
    Compare today's best price to the previous best.
    Log a sharp-money warning if the move exceeds LINE_MOVEMENT_THRESHOLD.
    """
    prev = db.get_previous_best_odds(event_id, market, outcome)
    if prev is None:
        return

    move = abs(current_best - prev)
    if move >= config.LINE_MOVEMENT_THRESHOLD:
        direction = "UP" if current_best > prev else "DOWN"
        logger.warning(
            "SHARP MOVE [%s] %s | %s | %s  %+.0f → %+.0f  (Δ%.0f %s)",
            market.upper(), event_id, outcome,
            "", prev, current_best, move, direction,
        )
        print(
            f"\n[LINE MOVEMENT] {market.upper()} | {outcome}\n"
            f"  Previous best: {prev:+.0f}\n"
            f"  Current  best: {current_best:+.0f}\n"
            f"  Move: {move:.0f} points {direction} — possible sharp action\n"
        )


# --------------------------------------------------------------------------- #
# Data grouping helpers                                                       #
# --------------------------------------------------------------------------- #

def _group_rows(rows: list[dict]) -> dict:
    """
    Re-index flat snapshot rows by:
      event_id → market → {
          "meta":   {event_id, sport, home_team, away_team},
          "outcomes": [ outcome_name, ... ],   (ordered list)
          "books":  { bookmaker: { outcome_name: odds } }
      }
    """
    events: dict = {}

    for row in rows:
        eid    = row["event_id"]
        market = row["market"]
        book   = row["bookmaker"]
        out    = row["outcome"]
        odds   = row["odds"]

        if eid not in events:
            events[eid] = {}

        if market not in events[eid]:
            events[eid][market] = {
                "meta": {
                    "event_id":  eid,
                    "sport":     row["sport"],
                    "home_team": row["home_team"],
                    "away_team": row["away_team"],
                },
                "outcomes": [],
                "books": defaultdict(dict),
            }

        mkt = events[eid][market]
        if out not in mkt["outcomes"]:
            mkt["outcomes"].append(out)
        mkt["books"][book][out] = odds

    return events


# --------------------------------------------------------------------------- #
# Main scanner                                                                #
# --------------------------------------------------------------------------- #

def run_scan(rows: list[dict]) -> int:
    """
    Process a batch of snapshot rows through the full EV pipeline.

    Returns the number of +EV alerts fired.
    """
    if not rows:
        logger.info("No rows to scan.")
        return 0

    events = _group_rows(rows)
    alert_count = 0

    for eid, markets in events.items():
        for market_key, mkt in markets.items():
            meta      = mkt["meta"]
            outcomes  = mkt["outcomes"]   # ordered list
            books     = mkt["books"]      # {book: {outcome: odds}}

            # Build per-book full-market odds list (same outcome order for each)
            all_outcomes_per_book: dict[str, list[float]] = {}
            for book, outcome_odds in books.items():
                # Only include books that quote ALL outcomes in this market
                if all(o in outcome_odds for o in outcomes):
                    all_outcomes_per_book[book] = [
                        outcome_odds[o] for o in outcomes
                    ]

            if len(all_outcomes_per_book) < 2:
                # Need at least two full-market books for a reliable consensus
                continue

            for idx, outcome_name in enumerate(outcomes):
                # Collect odds for this outcome across all books
                book_odds_for_outcome = {
                    book: outcome_odds[outcome_name]
                    for book, outcome_odds in books.items()
                    if outcome_name in outcome_odds
                }

                # Step 9: line-movement check
                best_current = max(
                    book_odds_for_outcome.values(),
                    key=lambda o: (o / 100 + 1) if o >= 0 else (100 / abs(o) + 1),
                )
                check_line_movement(eid, market_key, outcome_name, best_current)

                # Steps 5+6: EV evaluation
                alert = evaluate_outcome(
                    event_meta             = meta,
                    market                 = market_key,
                    outcome_name           = outcome_name,
                    outcome_index          = idx,
                    all_outcomes_per_book  = all_outcomes_per_book,
                    book_odds_for_outcome  = book_odds_for_outcome,
                )

                if alert:
                    db.insert_ev_alert(alert)
                    send_alert(alert)
                    alert_count += 1

    logger.info("Scan complete. %d +EV alert(s) found.", alert_count)
    return alert_count
