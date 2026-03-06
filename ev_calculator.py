# ev_calculator.py
# Expected value calculation and line-comparison logic.

import logging
from typing import Optional

from probability import american_to_decimal, consensus_true_probability
import config

logger = logging.getLogger(__name__)


# --------------------------------------------------------------------------- #
# Step 6 — Expected Value                                                     #
# --------------------------------------------------------------------------- #

def calculate_ev(true_probability: float, american_odds: float) -> float:
    """
    Calculate expected value (EV) as a fraction of the unit stake.

    Formula:
        EV = (true_prob × profit_if_win) − (1 − true_prob) × stake_lost

    Because we stake 1 unit:
        profit_if_win = decimal_odds − 1
        stake_lost    = 1

    So:
        EV = true_prob × (decimal_odds − 1) − (1 − true_prob)

    A positive value means the bet is +EV.

    Example:
        true_prob = 0.55, odds = +110 (decimal 2.10)
        EV = 0.55 × 1.10 − 0.45 = 0.605 − 0.45 = +0.155  (+15.5 %)
    """
    decimal_odds = american_to_decimal(american_odds)
    profit_if_win = decimal_odds - 1.0
    ev = true_probability * profit_if_win - (1.0 - true_probability)
    return ev


# --------------------------------------------------------------------------- #
# Step 5 — Best line across books                                             #
# --------------------------------------------------------------------------- #

def best_line(book_odds: dict[str, float]) -> tuple[Optional[str], Optional[float]]:
    """
    Return (bookmaker, odds) for the highest available American odds.

    Higher American odds = better payout for the bettor.
        +135 > +120 > -110 > -150
    """
    if not book_odds:
        return None, None
    best_book = max(book_odds, key=lambda b: american_to_decimal(book_odds[b]))
    return best_book, book_odds[best_book]


# --------------------------------------------------------------------------- #
# Full EV scan for one outcome                                                #
# --------------------------------------------------------------------------- #

def evaluate_outcome(
    event_meta: dict,
    market: str,
    outcome_name: str,
    outcome_index: int,
    all_outcomes_per_book: dict[str, list[float]],
    book_odds_for_outcome: dict[str, float],
) -> Optional[dict]:
    """
    Run the complete pipeline for a single (event, market, outcome) triple.

    Returns an alert dict if EV >= MIN_EV_THRESHOLD, otherwise None.

    Args:
        event_meta:             {event_id, sport, home_team, away_team}
        market:                 "h2h" | "spreads" | "totals"
        outcome_name:           e.g. "Toronto Maple Leafs" or "Over"
        outcome_index:          position in the outcome list (for vig removal)
        all_outcomes_per_book:  {book: [odds_0, odds_1, ...]} — full market
        book_odds_for_outcome:  {book: american_odds} — just this outcome
    """
    # 1. Consensus true probability (vig removed, averaged across books)
    true_prob = consensus_true_probability(
        book_odds_for_outcome,
        outcome_index,
        all_outcomes_per_book,
    )
    if true_prob is None:
        return None

    # 2. Best available price
    top_book, top_odds = best_line(book_odds_for_outcome)
    if top_book is None:
        return None

    # 3. EV at best price
    ev = calculate_ev(true_prob, top_odds)

    logger.debug(
        "%s | %s | %s | book=%s odds=%+.0f true_prob=%.3f EV=%.3f",
        event_meta["event_id"], market, outcome_name,
        top_book, top_odds, true_prob, ev,
    )

    if ev < config.MIN_EV_THRESHOLD:
        return None

    from database import now_utc
    return {
        **event_meta,
        "market":           market,
        "outcome":          outcome_name,
        "best_book":        top_book,
        "best_odds":        top_odds,
        "true_probability": true_prob,
        "ev":               ev,
        "timestamp":        now_utc(),
    }
