# dashboard.py
# Streamlit dashboard for the +EV scanner.
# Run with:  streamlit run dashboard.py

import sqlite3
import sys
import threading
import time
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import streamlit as st

# Make sure imports from the project work regardless of cwd
sys.path.insert(0, str(Path(__file__).parent))

import config
import database as db


# ─────────────────────────────────────────────────────────────────────────────
# Page config (must be first Streamlit call)
# ─────────────────────────────────────────────────────────────────────────────

st.set_page_config(
    page_title  = "EV Scanner Dashboard",
    page_icon   = "📈",
    layout      = "wide",
    initial_sidebar_state = "collapsed",
)


# ─────────────────────────────────────────────────────────────────────────────
# Custom CSS
# ─────────────────────────────────────────────────────────────────────────────

st.markdown("""
<style>
    /* Tighten default padding */
    .block-container { padding-top: 1.5rem; padding-bottom: 1rem; }

    /* Metric cards */
    [data-testid="metric-container"] {
        background: #1e2130;
        border: 1px solid #2d3250;
        border-radius: 10px;
        padding: 12px 16px;
    }

    /* Positive EV badge */
    .ev-positive { color: #00e676; font-weight: 700; }
    .ev-neutral  { color: #ffd740; font-weight: 700; }

    /* Alert card */
    .alert-card {
        background: #1a1f36;
        border-left: 4px solid #00e676;
        border-radius: 6px;
        padding: 12px 16px;
        margin-bottom: 10px;
        font-size: 0.9rem;
    }
    .movement-card {
        background: #1a1f36;
        border-left: 4px solid #ff6d00;
        border-radius: 6px;
        padding: 12px 16px;
        margin-bottom: 10px;
        font-size: 0.9rem;
    }

    /* Tab label size */
    button[data-baseweb="tab"] { font-size: 1rem; }
</style>
""", unsafe_allow_html=True)


# ─────────────────────────────────────────────────────────────────────────────
# Background scanner thread (module-level so it survives Streamlit reruns)
# ─────────────────────────────────────────────────────────────────────────────

_stop_event    : threading.Event       = threading.Event()
_scanner_thread: threading.Thread | None = None


def _scanner_loop(interval: int) -> None:
    """Target function for the background thread."""
    from main import run_pipeline
    while not _stop_event.is_set():
        try:
            run_pipeline()
        except Exception as exc:
            # Don't crash the thread on a transient error
            print(f"[scanner thread] error: {exc}")
        _stop_event.wait(interval)


def start_scanner() -> None:
    global _scanner_thread, _stop_event
    if _scanner_thread and _scanner_thread.is_alive():
        return
    _stop_event.clear()
    _scanner_thread = threading.Thread(
        target   = _scanner_loop,
        args     = (config.POLL_INTERVAL_SECONDS,),
        daemon   = True,
        name     = "ev-scanner",
    )
    _scanner_thread.start()


def stop_scanner() -> None:
    _stop_event.set()


def scanner_is_running() -> bool:
    return _scanner_thread is not None and _scanner_thread.is_alive()


# ─────────────────────────────────────────────────────────────────────────────
# Data helpers  (cached so repeated reruns don't hammer the DB)
# ─────────────────────────────────────────────────────────────────────────────

@st.cache_data(ttl=20)
def load_ev_alerts(limit: int = 200) -> pd.DataFrame:
    try:
        with db.get_connection() as conn:
            df = pd.read_sql_query("""
                SELECT
                    datetime(timestamp) AS time,
                    sport,
                    away_team || ' @ ' || home_team AS game,
                    market,
                    outcome,
                    best_book   AS book,
                    best_odds   AS odds,
                    ROUND(true_probability * 100, 1) AS true_prob_pct,
                    ROUND(ev * 100, 2)               AS ev_pct
                FROM ev_alerts
                ORDER BY timestamp DESC
                LIMIT ?
            """, conn, params=(limit,))
    except Exception:
        df = pd.DataFrame()
    return df


@st.cache_data(ttl=20)
def load_summary_stats() -> dict:
    try:
        with db.get_connection() as conn:
            cur = conn.cursor()
            total_alerts = cur.execute(
                "SELECT COUNT(*) FROM ev_alerts"
            ).fetchone()[0]
            alerts_today = cur.execute(
                "SELECT COUNT(*) FROM ev_alerts WHERE date(timestamp) = date('now')"
            ).fetchone()[0]
            best_ev = cur.execute(
                "SELECT MAX(ev) FROM ev_alerts"
            ).fetchone()[0] or 0
            snapshots = cur.execute(
                "SELECT COUNT(*) FROM odds_snapshots"
            ).fetchone()[0]
    except Exception:
        total_alerts = alerts_today = snapshots = 0
        best_ev = 0.0
    return {
        "total_alerts": total_alerts,
        "alerts_today": alerts_today,
        "best_ev":      best_ev,
        "snapshots":    snapshots,
    }


@st.cache_data(ttl=20)
def load_active_events() -> pd.DataFrame:
    """Events seen in the most recent snapshot batch."""
    try:
        with db.get_connection() as conn:
            df = pd.read_sql_query("""
                SELECT
                    event_id,
                    sport,
                    home_team,
                    away_team,
                    MAX(timestamp) AS last_seen
                FROM odds_snapshots
                GROUP BY event_id
                ORDER BY last_seen DESC
                LIMIT 100
            """, conn)
    except Exception:
        df = pd.DataFrame()
    return df


@st.cache_data(ttl=20)
def load_current_odds(event_id: str) -> pd.DataFrame:
    """Latest odds for every bookmaker × market × outcome for one event."""
    try:
        with db.get_connection() as conn:
            df = pd.read_sql_query("""
                SELECT bookmaker, market, outcome, odds, point, timestamp
                FROM   odds_snapshots
                WHERE  event_id = ?
                  AND  timestamp = (
                      SELECT MAX(timestamp)
                      FROM   odds_snapshots
                      WHERE  event_id = ?
                  )
                ORDER BY market, outcome, bookmaker
            """, conn, params=(event_id, event_id))
    except Exception:
        df = pd.DataFrame()
    return df


@st.cache_data(ttl=20)
def load_line_history(event_id: str, market: str) -> pd.DataFrame:
    try:
        with db.get_connection() as conn:
            df = pd.read_sql_query("""
                SELECT
                    bookmaker,
                    outcome,
                    odds,
                    point,
                    datetime(timestamp) AS timestamp
                FROM odds_snapshots
                WHERE event_id = ? AND market = ?
                ORDER BY timestamp
            """, conn, params=(event_id, market))
    except Exception:
        df = pd.DataFrame()
    return df


@st.cache_data(ttl=20)
def load_ev_over_time() -> pd.DataFrame:
    try:
        with db.get_connection() as conn:
            df = pd.read_sql_query("""
                SELECT
                    strftime('%Y-%m-%d %H:%M', timestamp) AS minute,
                    sport,
                    ROUND(AVG(ev) * 100, 2) AS avg_ev_pct,
                    COUNT(*) AS count
                FROM ev_alerts
                GROUP BY minute, sport
                ORDER BY minute
            """, conn)
    except Exception:
        df = pd.DataFrame()
    return df


# ─────────────────────────────────────────────────────────────────────────────
# Header
# ─────────────────────────────────────────────────────────────────────────────

col_title, col_status, col_refresh = st.columns([5, 3, 2])

with col_title:
    st.markdown("## 📈 Sports Betting +EV Scanner")

with col_status:
    running = scanner_is_running()
    status_color = "#00e676" if running else "#ff5252"
    status_label = "RUNNING" if running else "STOPPED"
    st.markdown(
        f"<div style='padding:10px 0'>"
        f"<span style='color:{status_color};font-weight:700;font-size:1rem;'>"
        f"● Scanner {status_label}</span></div>",
        unsafe_allow_html=True,
    )

with col_refresh:
    if st.button("⟳  Refresh", use_container_width=True):
        st.cache_data.clear()
        st.rerun()

st.divider()


# ─────────────────────────────────────────────────────────────────────────────
# Summary metrics bar
# ─────────────────────────────────────────────────────────────────────────────

stats = load_summary_stats()
m1, m2, m3, m4 = st.columns(4)
m1.metric("Total +EV Alerts",   stats["total_alerts"])
m2.metric("Alerts Today",       stats["alerts_today"])
m3.metric("Best EV Found",      f"{stats['best_ev']*100:.1f}%" if stats["best_ev"] else "—")
m4.metric("Odds Snapshots",     f"{stats['snapshots']:,}")

st.markdown("<br>", unsafe_allow_html=True)


# ─────────────────────────────────────────────────────────────────────────────
# Tabs
# ─────────────────────────────────────────────────────────────────────────────

tab_alerts, tab_odds, tab_lines, tab_settings = st.tabs([
    "🟢  Live Alerts",
    "📊  Odds Explorer",
    "📉  Line Movement",
    "⚙️  Settings",
])


# ══════════════════════════════════════════════════════════════════════════════
# TAB 1 — Live Alerts
# ══════════════════════════════════════════════════════════════════════════════

with tab_alerts:
    alerts_df = load_ev_alerts()

    if alerts_df.empty:
        st.info(
            "No +EV alerts yet.  Start the scanner in the **Settings** tab "
            "and wait for the first poll to complete.",
            icon="ℹ️",
        )
    else:
        # Filters row
        fc1, fc2, fc3 = st.columns([2, 2, 2])
        with fc1:
            sport_opts  = ["All"] + sorted(alerts_df["sport"].unique().tolist())
            sport_filter = st.selectbox("Sport", sport_opts, key="af_sport")
        with fc2:
            market_opts  = ["All"] + sorted(alerts_df["market"].unique().tolist())
            market_filter = st.selectbox("Market", market_opts, key="af_market")
        with fc3:
            min_ev = st.slider(
                "Min EV %", min_value=0.0, max_value=30.0,
                value=float(config.MIN_EV_THRESHOLD * 100),
                step=0.5, key="af_minev",
            )

        view = alerts_df.copy()
        if sport_filter  != "All": view = view[view["sport"]   == sport_filter]
        if market_filter != "All": view = view[view["market"]  == market_filter]
        view = view[view["ev_pct"] >= min_ev]

        st.markdown(f"**{len(view)} alert(s) shown**")
        st.markdown("<br>", unsafe_allow_html=True)

        # Render alert cards for top 10, full table below
        for _, row in view.head(10).iterrows():
            odds_str = (f"+{row['odds']:.0f}" if row["odds"] >= 0
                        else f"{row['odds']:.0f}")
            st.markdown(f"""
            <div class="alert-card">
                <b>{row['game']}</b> &nbsp;|&nbsp; {row['sport'].replace('_',' ').title()}
                &nbsp;|&nbsp; <i>{row['time']}</i><br>
                Market: <b>{row['market'].upper()}</b> &mdash;
                Outcome: <b>{row['outcome']}</b><br>
                Book: <b>{row['book']}</b> &nbsp;
                Odds: <b>{odds_str}</b> &nbsp;
                True Prob: <b>{row['true_prob_pct']}%</b> &nbsp;
                EV: <span class="ev-positive">+{row['ev_pct']}%</span>
            </div>
            """, unsafe_allow_html=True)

        with st.expander("Show full alerts table"):
            st.dataframe(view, use_container_width=True, hide_index=True)

        # EV over time chart
        ev_time_df = load_ev_over_time()
        if not ev_time_df.empty:
            st.markdown("#### EV % Over Time")
            fig = px.scatter(
                ev_time_df,
                x          = "minute",
                y          = "avg_ev_pct",
                color      = "sport",
                size       = "count",
                labels     = {"minute": "Time", "avg_ev_pct": "Avg EV %"},
                template   = "plotly_dark",
            )
            fig.update_layout(margin=dict(l=0, r=0, t=10, b=0), height=300)
            st.plotly_chart(fig, use_container_width=True)


# ══════════════════════════════════════════════════════════════════════════════
# TAB 2 — Odds Explorer
# ══════════════════════════════════════════════════════════════════════════════

with tab_odds:
    events_df = load_active_events()

    if events_df.empty:
        st.info("No events in the database yet.  Run the scanner first.", icon="ℹ️")
    else:
        # Event selector
        events_df["label"] = (
            events_df["away_team"] + " @ " + events_df["home_team"]
            + "  [" + events_df["sport"] + "]"
        )
        selected_label = st.selectbox(
            "Select game", events_df["label"].tolist(), key="oe_event"
        )
        selected_event_id = events_df.loc[
            events_df["label"] == selected_label, "event_id"
        ].iloc[0]

        odds_df = load_current_odds(selected_event_id)

        if odds_df.empty:
            st.warning("No current odds found for this event.")
        else:
            for market in odds_df["market"].unique():
                st.markdown(f"#### {market.upper()}")
                mdf = odds_df[odds_df["market"] == market].copy()

                # Pivot: rows = outcome, columns = bookmaker
                pivot = mdf.pivot_table(
                    index   = "outcome",
                    columns = "bookmaker",
                    values  = "odds",
                    aggfunc = "first",
                )

                # Highlight best odds in each row (green = highest decimal)
                def highlight_best(row):
                    from probability import american_to_decimal
                    styles = [""] * len(row)
                    valid  = row.dropna()
                    if valid.empty:
                        return styles
                    best_book = valid.index[
                        valid.apply(american_to_decimal).argmax()
                    ]
                    return [
                        "background-color: #1b5e20; color: #a5d6a7; font-weight:700"
                        if col == best_book else ""
                        for col in row.index
                    ]

                def fmt_american(val):
                    if pd.isna(val):
                        return "—"
                    return f"+{val:.0f}" if val >= 0 else f"{val:.0f}"

                styled = (
                    pivot.style
                    .apply(highlight_best, axis=1)
                    .format(fmt_american)
                )
                st.dataframe(styled, use_container_width=True)

                # Bar chart of best odds per outcome
                best_rows = []
                for outcome in mdf["outcome"].unique():
                    sub = mdf[mdf["outcome"] == outcome]
                    from probability import american_to_decimal
                    best_idx  = sub["odds"].apply(american_to_decimal).idxmax()
                    best_row  = sub.loc[best_idx]
                    best_rows.append({
                        "outcome":  outcome,
                        "bookmaker": best_row["bookmaker"],
                        "odds":      best_row["odds"],
                    })
                best_df = pd.DataFrame(best_rows)
                best_df["odds_display"] = best_df["odds"].apply(
                    lambda o: f"+{o:.0f}" if o >= 0 else f"{o:.0f}"
                )

                fig = px.bar(
                    best_df,
                    x          = "outcome",
                    y          = best_df["odds"].apply(american_to_decimal),
                    color      = "bookmaker",
                    text       = "odds_display",
                    labels     = {"y": "Decimal Odds", "x": "Outcome"},
                    template   = "plotly_dark",
                    title      = f"Best Available Odds — {market.upper()}",
                )
                fig.update_layout(
                    margin     = dict(l=0, r=0, t=35, b=0),
                    height     = 260,
                    showlegend = True,
                )
                st.plotly_chart(fig, use_container_width=True)


# ══════════════════════════════════════════════════════════════════════════════
# TAB 3 — Line Movement
# ══════════════════════════════════════════════════════════════════════════════

with tab_lines:
    lm_events = load_active_events()

    if lm_events.empty:
        st.info("No events in the database yet.", icon="ℹ️")
    else:
        lm_events["label"] = (
            lm_events["away_team"] + " @ " + lm_events["home_team"]
            + "  [" + lm_events["sport"] + "]"
        )

        lc1, lc2 = st.columns(2)
        with lc1:
            lm_label = st.selectbox(
                "Game", lm_events["label"].tolist(), key="lm_event"
            )
        lm_event_id = lm_events.loc[
            lm_events["label"] == lm_label, "event_id"
        ].iloc[0]

        with lc2:
            lm_market = st.selectbox(
                "Market", ["h2h", "spreads", "totals"], key="lm_market"
            )

        hist_df = load_line_history(lm_event_id, lm_market)

        if hist_df.empty:
            st.warning("No line history for this selection yet.")
        else:
            outcomes = hist_df["outcome"].unique().tolist()
            selected_outcomes = st.multiselect(
                "Outcomes to display", outcomes, default=outcomes, key="lm_outcomes"
            )

            plot_df = hist_df[hist_df["outcome"].isin(selected_outcomes)].copy()
            plot_df["label"] = plot_df["outcome"] + " (" + plot_df["bookmaker"] + ")"

            fig = px.line(
                plot_df,
                x          = "timestamp",
                y          = "odds",
                color      = "label",
                markers    = True,
                labels     = {"timestamp": "Time", "odds": "American Odds", "label": ""},
                template   = "plotly_dark",
                title      = f"Line Movement — {lm_market.upper()}",
            )
            fig.update_layout(
                margin     = dict(l=0, r=0, t=40, b=0),
                height     = 400,
                legend     = dict(orientation="h", yanchor="bottom", y=1.02),
            )
            # Add a horizontal reference line at 0
            fig.add_hline(
                y          = -110,
                line_dash  = "dot",
                line_color = "gray",
                annotation_text = "-110 (vig baseline)",
            )
            st.plotly_chart(fig, use_container_width=True)

            # Biggest movers table
            st.markdown("#### Biggest Movers")
            if len(hist_df) >= 2:
                first_odds = hist_df.groupby(["outcome", "bookmaker"])["odds"].first()
                last_odds  = hist_df.groupby(["outcome", "bookmaker"])["odds"].last()
                movers     = (last_odds - first_odds).reset_index()
                movers.columns = ["outcome", "bookmaker", "move"]
                movers["move"] = movers["move"].round(1)
                movers = movers.reindex(
                    movers["move"].abs().sort_values(ascending=False).index
                )

                def color_move(val):
                    if val > config.LINE_MOVEMENT_THRESHOLD:
                        return "color: #ff6d00; font-weight:700"
                    if val < -config.LINE_MOVEMENT_THRESHOLD:
                        return "color: #64b5f6; font-weight:700"
                    return ""

                st.dataframe(
                    movers.style.applymap(color_move, subset=["move"]),
                    use_container_width=True,
                    hide_index=True,
                )
            else:
                st.caption("Need more than one snapshot to compute moves.")


# ══════════════════════════════════════════════════════════════════════════════
# TAB 4 — Settings
# ══════════════════════════════════════════════════════════════════════════════

with tab_settings:
    st.markdown("### Scanner Control")

    sc1, sc2 = st.columns(2)
    with sc1:
        if scanner_is_running():
            if st.button("⏹  Stop Scanner", type="primary", use_container_width=True):
                stop_scanner()
                st.success("Scanner stopped.")
                st.rerun()
        else:
            if st.button("▶  Start Scanner", type="primary", use_container_width=True):
                db.init_db()
                start_scanner()
                st.success("Scanner started in background.")
                st.rerun()

    with sc2:
        status_txt = "🟢 Running" if scanner_is_running() else "🔴 Stopped"
        st.markdown(f"**Status:** {status_txt}")
        st.caption(f"Poll interval: every {config.POLL_INTERVAL_SECONDS}s")

    st.divider()
    st.markdown("### API Key")

    current_key = config.API_KEY
    masked = (
        current_key[:6] + "••••••" + current_key[-4:]
        if len(current_key) > 10 and current_key != "YOUR_API_KEY_HERE"
        else "Not set"
    )
    st.caption(f"Current key: `{masked}`")

    new_key = st.text_input(
        "Enter new API key (saved to config.py)",
        type="password",
        placeholder="Paste your Odds API key here",
        key="s_apikey",
    )
    if st.button("Save API Key", key="s_save_key"):
        if new_key.strip():
            cfg_path = Path(__file__).parent / "config.py"
            cfg_text = cfg_path.read_text()
            cfg_text = cfg_text.replace(
                f'"{config.API_KEY}"',
                f'"{new_key.strip()}"',
            )
            cfg_path.write_text(cfg_text)
            st.success("API key saved to config.py.  Restart the dashboard to apply.")
        else:
            st.warning("Key was empty — nothing saved.")

    st.divider()
    st.markdown("### Thresholds")

    th1, th2, th3 = st.columns(3)
    with th1:
        new_ev = st.number_input(
            "Min EV % to alert",
            min_value=0.5, max_value=50.0,
            value=float(config.MIN_EV_THRESHOLD * 100),
            step=0.5, key="s_ev",
        )
    with th2:
        new_lmt = st.number_input(
            "Line movement threshold",
            min_value=1, max_value=50,
            value=config.LINE_MOVEMENT_THRESHOLD,
            step=1, key="s_lmt",
        )
    with th3:
        new_interval = st.number_input(
            "Poll interval (seconds)",
            min_value=60, max_value=3600,
            value=config.POLL_INTERVAL_SECONDS,
            step=60, key="s_interval",
        )

    if st.button("Apply Thresholds (this session)", key="s_apply"):
        config.MIN_EV_THRESHOLD         = new_ev / 100
        config.LINE_MOVEMENT_THRESHOLD  = new_lmt
        config.POLL_INTERVAL_SECONDS    = new_interval
        st.success("Applied for this session.  Edit config.py to make permanent.")

    st.divider()
    st.markdown("### Sports Monitored")
    st.code("\n".join(config.SPORTS), language="text")
    st.caption("Edit the `SPORTS` list in `config.py` to add or remove sports.")

    st.divider()
    st.markdown("### Database")
    db_path = Path(config.DB_PATH).resolve()
    st.caption(f"Location: `{db_path}`")

    if st.button("Clear alert cache", key="s_clear_cache"):
        st.cache_data.clear()
        st.success("Cache cleared — next view will reload from DB.")

    st.divider()
    st.markdown("### Auto Refresh")
    auto_refresh = st.toggle("Auto-refresh every 30 seconds", key="s_autorefresh")


# ─────────────────────────────────────────────────────────────────────────────
# Auto-refresh (bottom of script so it doesn't interrupt tab rendering)
# ─────────────────────────────────────────────────────────────────────────────

if st.session_state.get("s_autorefresh", False):
    placeholder = st.empty()
    for remaining in range(30, 0, -1):
        placeholder.caption(f"Auto-refreshing in {remaining}s  |  toggle off in Settings")
        time.sleep(1)
    placeholder.empty()
    st.cache_data.clear()
    st.rerun()
