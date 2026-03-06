# probability.py
# Odds conversion and vig-removal math.

from typing import Optional


# --------------------------------------------------------------------------- #
# Step 3 — American odds → implied probability                                #
# --------------------------------------------------------------------------- #

def american_to_implied(odds: float) -> float:
    """
    Convert American-format odds to raw implied probability (with vig).

    Positive odds (underdogs):
        P = 100 / (odds + 100)

    Negative odds (favourites):
        P = |odds| / (|odds| + 100)
    """
    if odds >= 0:
        return 100.0 / (odds + 100.0)
    else:
        abs_odds = abs(odds)
        return abs_odds / (abs_odds + 100.0)


# --------------------------------------------------------------------------- #
# Step 3 — American odds → decimal odds                                       #
# --------------------------------------------------------------------------- #

def american_to_decimal(odds: float) -> float:
    """
    Convert American odds to decimal (European) format.

    Decimal odds represent the total return per unit staked (stake included).

    Positive:  decimal = (odds / 100) + 1
    Negative:  decimal = (100 / |odds|) + 1
    """
    if odds >= 0:
        return (odds / 100.0) + 1.0
    else:
        return (100.0 / abs(odds)) + 1.0


# --------------------------------------------------------------------------- #
# Step 4 — Remove vig from a two-outcome market                               #
# --------------------------------------------------------------------------- #

def remove_vig(implied_probs: list[float]) -> list[float]:
    """
    Normalise a list of implied probabilities to sum to 1.0, removing the
    bookmaker's margin (vig).

    Example (two-sided market):
        -110 / -110  →  implied 52.38% each  →  total 104.76%
        After removal: 52.38 / 104.76 = 50.0% each  ✓

    Works for any number of outcomes (moneyline 3-way, round-robins, etc.).
    """
    total = sum(implied_probs)
    if total == 0:
        raise ValueError("Sum of implied probabilities is zero.")
    return [p / total for p in implied_probs]


def market_true_probabilities(odds_list: list[float]) -> list[float]:
    """
    Full pipeline: list of American odds → vig-free true probabilities.

    Args:
        odds_list: American odds for every outcome in the market
                   (e.g. [-110, -110] or [+120, -145]).

    Returns:
        List of true probabilities in the same order.
    """
    implied = [american_to_implied(o) for o in odds_list]
    return remove_vig(implied)


# --------------------------------------------------------------------------- #
# Consensus true probability across multiple books                            #
# --------------------------------------------------------------------------- #

def consensus_true_probability(
    all_book_odds: dict[str, float],
    outcome_index: int,
    all_outcomes_per_book: dict[str, list[float]],
) -> Optional[float]:
    """
    Given multiple sportsbooks each offering a set of odds for the same
    market, compute the average vig-free true probability for one outcome.

    Args:
        all_book_odds: {bookmaker: american_odds_for_this_outcome}
                       (not used directly here — kept for future weighting)
        outcome_index: which outcome (0-indexed) we want the probability for
        all_outcomes_per_book: {bookmaker: [odds_outcome_0, odds_outcome_1, ...]}

    Returns:
        Average true probability across all books, or None if unavailable.
    """
    true_probs = []
    for book, odds_list in all_outcomes_per_book.items():
        try:
            probs = market_true_probabilities(odds_list)
            if outcome_index < len(probs):
                true_probs.append(probs[outcome_index])
        except (ValueError, ZeroDivisionError):
            continue

    if not true_probs:
        return None
    return sum(true_probs) / len(true_probs)
