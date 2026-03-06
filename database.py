# database.py
# Handles all SQLite persistence: schema creation, inserts, and queries.

import sqlite3
import logging
from datetime import datetime, timezone
from typing import Optional

import config

logger = logging.getLogger(__name__)


def get_connection() -> sqlite3.Connection:
    conn = sqlite3.connect(config.DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_db() -> None:
    """Create tables if they don't exist yet."""
    with get_connection() as conn:
        conn.executescript("""
        CREATE TABLE IF NOT EXISTS odds_snapshots (
            id           INTEGER PRIMARY KEY AUTOINCREMENT,
            event_id     TEXT    NOT NULL,
            sport        TEXT    NOT NULL,
            home_team    TEXT    NOT NULL,
            away_team    TEXT    NOT NULL,
            commence_time TEXT,
            bookmaker    TEXT    NOT NULL,
            market       TEXT    NOT NULL,   -- h2h | spreads | totals
            outcome      TEXT    NOT NULL,   -- team name or Over/Under
            odds         REAL    NOT NULL,   -- American odds
            point        REAL,              -- spread / total value (NULL for h2h)
            timestamp    TEXT    NOT NULL
        );

        CREATE INDEX IF NOT EXISTS idx_event_market
            ON odds_snapshots (event_id, market, outcome, timestamp);

        CREATE TABLE IF NOT EXISTS ev_alerts (
            id              INTEGER PRIMARY KEY AUTOINCREMENT,
            event_id        TEXT    NOT NULL,
            sport           TEXT    NOT NULL,
            home_team       TEXT    NOT NULL,
            away_team       TEXT    NOT NULL,
            market          TEXT    NOT NULL,
            outcome         TEXT    NOT NULL,
            best_book       TEXT    NOT NULL,
            best_odds       REAL    NOT NULL,
            true_probability REAL   NOT NULL,
            ev              REAL    NOT NULL,
            timestamp       TEXT    NOT NULL
        );

        CREATE TABLE IF NOT EXISTS clv_tracking (
            id            INTEGER PRIMARY KEY AUTOINCREMENT,
            event_id      TEXT    NOT NULL,
            sport         TEXT    NOT NULL,
            market        TEXT    NOT NULL,
            outcome       TEXT    NOT NULL,
            bookmaker     TEXT    NOT NULL,
            bet_odds      REAL    NOT NULL,   -- odds when bet was placed
            closing_odds  REAL,              -- filled in at close
            bet_timestamp TEXT    NOT NULL,
            close_timestamp TEXT
        );
        """)
    logger.info("Database initialised at %s", config.DB_PATH)


def insert_snapshot(rows: list[dict]) -> None:
    """Bulk-insert a list of odds-snapshot dicts."""
    sql = """
        INSERT INTO odds_snapshots
            (event_id, sport, home_team, away_team, commence_time,
             bookmaker, market, outcome, odds, point, timestamp)
        VALUES
            (:event_id, :sport, :home_team, :away_team, :commence_time,
             :bookmaker, :market, :outcome, :odds, :point, :timestamp)
    """
    with get_connection() as conn:
        conn.executemany(sql, rows)
    logger.debug("Inserted %d snapshot rows", len(rows))


def insert_ev_alert(alert: dict) -> None:
    sql = """
        INSERT INTO ev_alerts
            (event_id, sport, home_team, away_team, market, outcome,
             best_book, best_odds, true_probability, ev, timestamp)
        VALUES
            (:event_id, :sport, :home_team, :away_team, :market, :outcome,
             :best_book, :best_odds, :true_probability, :ev, :timestamp)
    """
    with get_connection() as conn:
        conn.execute(sql, alert)


def get_recent_odds(event_id: str, market: str, outcome: str,
                    limit: int = 10) -> list[sqlite3.Row]:
    """Return the most recent N snapshots for a given outcome."""
    sql = """
        SELECT bookmaker, odds, point, timestamp
        FROM   odds_snapshots
        WHERE  event_id = ? AND market = ? AND outcome = ?
        ORDER  BY timestamp DESC
        LIMIT  ?
    """
    with get_connection() as conn:
        return conn.execute(sql, (event_id, market, outcome, limit)).fetchall()


def get_previous_best_odds(event_id: str, market: str,
                           outcome: str) -> Optional[float]:
    """Return the best (highest) odds seen for an outcome before the latest
    snapshot batch — used for line-movement detection."""
    sql = """
        SELECT MAX(odds) AS best
        FROM   odds_snapshots
        WHERE  event_id  = ?
          AND  market    = ?
          AND  outcome   = ?
          AND  timestamp < (
              SELECT MAX(timestamp)
              FROM   odds_snapshots
              WHERE  event_id = ? AND market = ? AND outcome = ?
          )
    """
    with get_connection() as conn:
        row = conn.execute(
            sql, (event_id, market, outcome, event_id, market, outcome)
        ).fetchone()
    return row["best"] if row and row["best"] is not None else None


def now_utc() -> str:
    return datetime.now(timezone.utc).isoformat()
