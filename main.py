# main.py
# Entry point.  Runs the full pipeline once, or loops on a schedule.
#
# Usage:
#   python main.py            # run once and exit
#   python main.py --loop     # run every POLL_INTERVAL_SECONDS

import argparse
import logging
import time

import config
import database as db
from odds_fetcher import fetch_and_flatten
from scanner import run_scan

# --------------------------------------------------------------------------- #
# Logging setup                                                               #
# --------------------------------------------------------------------------- #

logging.basicConfig(
    level   = logging.INFO,
    format  = "%(asctime)s  %(levelname)-8s  %(name)s  %(message)s",
    datefmt = "%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger("main")


# --------------------------------------------------------------------------- #
# Single pipeline run                                                         #
# --------------------------------------------------------------------------- #

def run_pipeline() -> None:
    logger.info("=== Pipeline start ===")
    from odds_fetcher import get_sport_ids
    all_rows: list[dict] = []

    sport_ids = get_sport_ids()
    if not sport_ids:
        logger.error("Could not resolve any sport IDs — check API key and connection.")
        return

    for sport_label, sport_id in sport_ids.items():
        rows = fetch_and_flatten(sport_label, sport_id)
        if rows:
            db.insert_snapshot(rows)
            all_rows.extend(rows)

    run_scan(all_rows)
    logger.info("=== Pipeline complete ===\n")


# --------------------------------------------------------------------------- #
# Main                                                                        #
# --------------------------------------------------------------------------- #

def main() -> None:
    parser = argparse.ArgumentParser(description="Sports betting +EV scanner")
    parser.add_argument(
        "--loop",
        action  = "store_true",
        help    = f"Run continuously every {config.POLL_INTERVAL_SECONDS}s",
    )
    args = parser.parse_args()

    db.init_db()

    if args.loop:
        logger.info(
            "Starting scheduler — polling every %ds for sports: %s",
            config.POLL_INTERVAL_SECONDS,
            ", ".join(config.SPORTS),
        )
        while True:
            try:
                run_pipeline()
            except Exception as exc:
                logger.exception("Unhandled error in pipeline: %s", exc)
            logger.info("Sleeping %ds …", config.POLL_INTERVAL_SECONDS)
            time.sleep(config.POLL_INTERVAL_SECONDS)
    else:
        run_pipeline()


if __name__ == "__main__":
    main()
