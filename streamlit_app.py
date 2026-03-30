"""
KTP Stock Scanner — Streamlit App
Replaces Flask + HTML/JS/CSS with a single Streamlit application.
Uses Plotly for interactive charts.
"""

import streamlit as st
import pandas as pd
import numpy as np
import time
import threading
import plotly.graph_objects as go
from plotly.subplots import make_subplots
import yfinance as yf

from scanner import scan_stock, calc_stochastic, calc_rsi, FIBO_LEVELS
from stocks import ALL_CATEGORIES
from simulator import (
    record_ready_signals, fill_pending_trades, update_open_trades,
    record_retrace_signals, fill_retrace_trades, update_retrace_trades,
    record_rr1_signals, fill_rr1_trades, update_rr1_trades,
    load_trades, get_summary, get_usdthb, BUDGET_THB
)

# ─── Page config ─────────────────────────────────────────────────────
st.set_page_config(
    page_title="KTP Stock Scanner",
    page_icon="📈",
    layout="wide",
    initial_sidebar_state="collapsed",
)

# ─── Custom CSS ──────────────────────────────────────────────────────
st.markdown("""
<style>
    .block-container { padding-top: 1rem; padding-bottom: 0rem; }
    div[data-testid="stMetric"] {
        background-color: #1e1e1e;
        border: 1px solid #333;
        padding: 8px 12px;
        border-radius: 8px;
    }
    div[data-testid="stMetric"] label { font-size: 0.75rem; }
    div[data-testid="stMetric"] div[data-testid="stMetricValue"] { font-size: 1.1rem; }
    .stTabs [data-baseweb="tab-list"] { gap: 4px; }
    .stTabs [data-baseweb="tab"] {
        padding: 6px 16px;
        font-size: 0.85rem;
    }
    /* Status badges */
    .badge-ut { background: #2e7d32; color: white; padding: 2px 8px; border-radius: 4px; font-size: 0.8rem; }
    .badge-dt { background: #c62828; color: white; padding: 2px 8px; border-radius: 4px; font-size: 0.8rem; }
    .badge-sw { background: #f57f17; color: white; padding: 2px 8px; border-radius: 4px; font-size: 0.8rem; }
    .badge-ready { background: #00c853; color: black; padding: 2px 8px; border-radius: 4px; font-size: 0.8rem; font-weight: bold; }
    .badge-ob { background: #ff5252; color: white; padding: 2px 8px; border-radius: 4px; font-size: 0.75rem; }
    .badge-os { background: #448aff; color: white; padding: 2px 8px; border-radius: 4px; font-size: 0.75rem; }
</style>
""", unsafe_allow_html=True)

# ─── Data cache ──────────────────────────────────────────────────────

def batch_download(symbols_tuple, period="1y"):
    """Download daily data for multiple symbols using yf.download().
    Uses single-stock downloads + delays to avoid Yahoo Finance rate limits on cloud.
    No @st.cache_data — we manage our own cache to avoid caching empty failures.
    """
    symbols = list(symbols_tuple)
    if not symbols:
        return {}

    # Check session-state cache first
    cache_key = f"_dl_cache_{period}"
    if cache_key not in st.session_state:
        st.session_state[cache_key] = {}
    cache = st.session_state[cache_key]

    now = time.time()
    result = {}
    to_fetch = []

    for s in symbols:
        cached = cache.get(s)
        if cached and (now - cached["ts"]) < 900:  # 15 min TTL
            result[s] = cached["data"]
        else:
            to_fetch.append(s)

    if not to_fetch:
        return result

    # Download one stock at a time to minimize rate limit issues
    progress = st.progress(0, text="Downloading stock data...")
    total = len(to_fetch)

    for idx, sym in enumerate(to_fetch):
        progress.progress((idx + 1) / total, text=f"Downloading {sym} ({idx+1}/{total})...")

        for attempt in range(3):
            try:
                raw = yf.download(
                    sym,
                    period=period,
                    interval="1d",
                    progress=False,
                    threads=False,
                    timeout=20,
                )
                if raw.empty:
                    break

                df = raw.copy()
                if isinstance(df.columns, pd.MultiIndex):
                    # Drop ticker level
                    for lvl_idx in range(df.columns.nlevels):
                        vals = df.columns.get_level_values(lvl_idx).unique().tolist()
                        if sym in vals or any(v not in ["Open", "High", "Low", "Close", "Volume", "Adj Close"] for v in vals):
                            df = df.droplevel(lvl_idx, axis=1)
                            break
                df.columns = [str(c) for c in df.columns]

                if "Close" not in df.columns:
                    break
                df = df.dropna(subset=["Close"])
                if df.empty or len(df) < 30:
                    break

                df = df.reset_index()
                date_col = [c for c in df.columns if "date" in c.lower() or "Date" in str(c)]
                if date_col:
                    df = df.rename(columns={date_col[0]: "date"})

                result[sym] = df
                cache[sym] = {"data": df, "ts": now}  # cache success only
                break  # success

            except Exception as e:
                err_str = str(e)
                if "Rate" in err_str or "429" in err_str or "Too Many" in err_str:
                    wait = 15 * (attempt + 1)  # 15, 30, 45 sec for rate limit
                else:
                    wait = 3 * (attempt + 1)
                if attempt < 2:
                    time.sleep(wait)

        # Small delay between stocks
        if idx < total - 1:
            time.sleep(1)

    progress.empty()
    return result


def run_scan(category):
    """Scan all stocks in a category."""
    symbols = list(dict.fromkeys(ALL_CATEGORIES[category]["symbols"]))
    all_data = batch_download(tuple(symbols))

    results = []
    for symbol in symbols:
        df = all_data.get(symbol)
        if df is None or len(df) < 30:
            continue

        try:
            df_indexed = df.copy()
            if "date" in df_indexed.columns:
                df_indexed["date"] = pd.to_datetime(df_indexed["date"])
                df_indexed = df_indexed.set_index("date")

            scan = scan_stock(df_indexed)
            if scan is None:
                continue

            last = df.iloc[-1]
            prev = df.iloc[-2] if len(df) > 1 else last
            close_val = float(last["Close"])
            prev_close = float(prev["Close"])
            change_pct = ((close_val - prev_close) / prev_close * 100) if prev_close != 0 else 0

            results.append({
                "symbol": symbol,
                "close": round(close_val, 4),
                "change_pct": round(change_pct, 2),
                "volume": int(last["Volume"]) if "Volume" in df.columns else 0,
                **scan,
            })
        except Exception:
            continue

    results.sort(key=lambda x: x.get("symbol", ""))
    return results


def get_chart_data(symbol, period="1y"):
    """Get OHLCV + indicators for charting."""
    data = batch_download((symbol,), period)
    df = data.get(symbol)
    if df is None:
        return None

    df_indexed = df.copy()
    if "date" in df_indexed.columns:
        df_indexed["date"] = pd.to_datetime(df_indexed["date"])
        df_indexed = df_indexed.set_index("date")

    stoch = calc_stochastic(df_indexed)
    rsi = calc_rsi(df_indexed)
    scan_result = None
    try:
        scan_result = scan_stock(df_indexed)
    except Exception:
        pass

    return {
        "df": df_indexed,
        "stoch": stoch,
        "rsi": rsi,
        "scan": scan_result,
    }


# ─── Chart builder ───────────────────────────────────────────────────

def build_chart(chart_data, symbol, trade_info=None):
    """Build a Plotly figure with candlestick, volume, RSI, and Stochastic."""
    df = chart_data["df"]
    stoch = chart_data["stoch"]
    rsi = chart_data["rsi"]
    scan = chart_data["scan"]

    fig = make_subplots(
        rows=4, cols=1,
        shared_xaxes=True,
        vertical_spacing=0.03,
        row_heights=[0.45, 0.15, 0.2, 0.2],
        subplot_titles=[symbol, "Volume", "RSI (14)", "Stochastic (9,3,3)"],
    )

    dates = df.index

    # Candlestick
    fig.add_trace(go.Candlestick(
        x=dates,
        open=df["Open"], high=df["High"],
        low=df["Low"], close=df["Close"],
        name="Price",
        increasing_line_color="#26a69a",
        decreasing_line_color="#ef5350",
    ), row=1, col=1)

    # Volume
    colors = ["rgba(38,166,154,0.5)" if c >= o else "rgba(239,83,80,0.5)"
              for c, o in zip(df["Close"], df["Open"])]
    fig.add_trace(go.Bar(
        x=dates, y=df["Volume"], name="Volume",
        marker_color=colors, showlegend=False,
    ), row=2, col=1)

    # RSI
    fig.add_trace(go.Scatter(
        x=dates, y=rsi["RSI"], name="RSI",
        line=dict(color="#ab47bc", width=1.5),
    ), row=3, col=1)
    fig.add_hline(y=70, line_dash="dash", line_color="rgba(255,82,82,0.5)", row=3, col=1)
    fig.add_hline(y=30, line_dash="dash", line_color="rgba(68,138,255,0.5)", row=3, col=1)

    # Stochastic
    fig.add_trace(go.Scatter(
        x=dates, y=stoch["K"], name="K",
        line=dict(color="#2196f3", width=1.5),
    ), row=4, col=1)
    fig.add_trace(go.Scatter(
        x=dates, y=stoch["D"], name="D",
        line=dict(color="#ff9800", width=1.5),
    ), row=4, col=1)
    fig.add_hline(y=80, line_dash="dash", line_color="rgba(255,82,82,0.4)", row=4, col=1)
    fig.add_hline(y=20, line_dash="dash", line_color="rgba(68,138,255,0.4)", row=4, col=1)

    # Reference lines on price chart
    if scan:
        if scan.get("white_line"):
            fig.add_hline(
                y=scan["white_line"], line_dash="dash",
                line_color="white", line_width=1,
                annotation_text=f"WL {scan['white_line']:.2f}",
                annotation_position="right",
                row=1, col=1,
            )
        if scan.get("sl_ref"):
            fig.add_hline(
                y=scan["sl_ref"], line_dash="dot",
                line_color="#ef5350", line_width=1,
                annotation_text=f"SL {scan['sl_ref']:.2f}",
                annotation_position="right",
                row=1, col=1,
            )
        if scan.get("tp_ref"):
            fig.add_hline(
                y=scan["tp_ref"], line_dash="dot",
                line_color="#26a69a", line_width=1,
                annotation_text=f"TP {scan['tp_ref']:.2f}",
                annotation_position="right",
                row=1, col=1,
            )

        # Fibo levels
        if scan.get("fibo_levels"):
            fibo_colors = {
                "0.0": "#ffffff", "0.382": "#ffeb3b", "0.5": "#ff9800",
                "0.618": "#f44336", "0.786": "#e91e63", "1.0": "#9c27b0",
                "1.382": "#673ab7", "1.618": "#3f51b5", "2.0": "#2196f3",
                "2.618": "#00bcd4",
            }
            for lvl_str, price in scan["fibo_levels"].items():
                fig.add_hline(
                    y=price, line_dash="dot",
                    line_color=fibo_colors.get(lvl_str, "#666"),
                    line_width=0.8,
                    annotation_text=f"Fibo {lvl_str}",
                    annotation_position="left",
                    annotation_font_size=9,
                    row=1, col=1,
                )

    # Trade lines (for simulator)
    if trade_info:
        if trade_info.get("entry_price"):
            fig.add_hline(
                y=trade_info["entry_price"], line_dash="solid",
                line_color="#2196f3", line_width=2,
                annotation_text=f"Entry {trade_info['entry_price']:.2f}",
                annotation_position="right",
                row=1, col=1,
            )
        if trade_info.get("sl"):
            fig.add_hline(
                y=trade_info["sl"], line_dash="dot",
                line_color="#ef5350", line_width=2,
                annotation_text=f"SL {trade_info['sl']:.2f}",
                annotation_position="right",
                row=1, col=1,
            )
        if trade_info.get("tp"):
            fig.add_hline(
                y=trade_info["tp"], line_dash="dot",
                line_color="#26a69a", line_width=2,
                annotation_text=f"TP {trade_info['tp']:.2f}",
                annotation_position="right",
                row=1, col=1,
            )

    fig.update_layout(
        height=700,
        template="plotly_dark",
        showlegend=False,
        xaxis_rangeslider_visible=False,
        margin=dict(l=50, r=50, t=40, b=20),
    )

    # Range selector on main chart
    fig.update_xaxes(
        rangeselector=dict(
            buttons=[
                dict(count=1, label="1M", step="month"),
                dict(count=3, label="3M", step="month"),
                dict(count=6, label="6M", step="month"),
                dict(count=1, label="1Y", step="year"),
                dict(step="all", label="All"),
            ],
            bgcolor="#1e1e1e",
        ),
        row=1, col=1,
    )

    # Y-axis ranges for RSI and Stochastic
    fig.update_yaxes(range=[0, 100], row=3, col=1)
    fig.update_yaxes(range=[0, 100], row=4, col=1)

    return fig


# ─── Helper: status badge ────────────────────────────────────────────

def trend_badge(trend):
    if trend == "UT":
        return "🟢 UT"
    elif trend == "DT":
        return "🔴 DT"
    else:
        return "🟡 SW"


def status_text(s):
    if "Ready" in s:
        return "✅ Ready"
    elif "Waiting" in s:
        return "⏳ Wait WL"
    elif "Over" in s:
        return "🔵 Over WL"
    elif "Down" in s:
        return "🔴 DT"
    else:
        return "🟡 SW"


# ─── Scanner page ────────────────────────────────────────────────────

def render_scanner():
    """Render the scanner section with category tabs."""

    cat_keys = list(ALL_CATEGORIES.keys())
    cat_names = [ALL_CATEGORIES[k]["name"] for k in cat_keys]

    tabs = st.tabs(cat_names)

    for tab, cat_key in zip(tabs, cat_keys):
        with tab:
            render_scanner_category(cat_key)


def render_scanner_category(cat_key):
    """Render scanner for one category."""
    state_key = f"scan_{cat_key}"

    if st.button(f"🔍 Scan {ALL_CATEGORIES[cat_key]['name']}", key=f"btn_scan_{cat_key}"):
        with st.spinner(f"Scanning {ALL_CATEGORIES[cat_key]['name']}..."):
            results = run_scan(cat_key)
            st.session_state[state_key] = results

    if state_key not in st.session_state:
        st.info(f"Click 'Scan' to load {ALL_CATEGORIES[cat_key]['name']} stocks.")
        return

    results = st.session_state[state_key]
    if not results:
        st.warning("No results found.")
        return

    # ── Filters ──
    col_filters = st.columns([1, 1, 1, 1, 1, 1, 1, 2])
    with col_filters[0]:
        show_all = st.button("All", key=f"f_all_{cat_key}")
    with col_filters[1]:
        show_ut = st.button("Uptrend", key=f"f_ut_{cat_key}")
    with col_filters[2]:
        show_dt = st.button("Downtrend", key=f"f_dt_{cat_key}")
    with col_filters[3]:
        show_sw = st.button("Sideway", key=f"f_sw_{cat_key}")
    with col_filters[4]:
        show_ready = st.button("Ready", key=f"f_ready_{cat_key}")
    with col_filters[5]:
        show_ob = st.button("OB", key=f"f_ob_{cat_key}")
    with col_filters[6]:
        show_os = st.button("OS", key=f"f_os_{cat_key}")
    with col_filters[7]:
        search = st.text_input("Search", key=f"search_{cat_key}", label_visibility="collapsed", placeholder="Search symbol...")

    # Apply filter
    filter_key = f"filter_{cat_key}"
    if show_ut:
        st.session_state[filter_key] = "UT"
    elif show_dt:
        st.session_state[filter_key] = "DT"
    elif show_sw:
        st.session_state[filter_key] = "SW"
    elif show_ready:
        st.session_state[filter_key] = "Ready"
    elif show_ob:
        st.session_state[filter_key] = "OB"
    elif show_os:
        st.session_state[filter_key] = "OS"
    elif show_all:
        st.session_state[filter_key] = "All"

    active_filter = st.session_state.get(filter_key, "All")

    filtered = results
    if active_filter == "UT":
        filtered = [r for r in filtered if r.get("trend") == "UT"]
    elif active_filter == "DT":
        filtered = [r for r in filtered if r.get("trend") == "DT"]
    elif active_filter == "SW":
        filtered = [r for r in filtered if r.get("trend") == "SW"]
    elif active_filter == "Ready":
        filtered = [r for r in filtered if r.get("is_ready_entry")]
    elif active_filter == "OB":
        filtered = [r for r in filtered if r.get("in_ob")]
    elif active_filter == "OS":
        filtered = [r for r in filtered if r.get("in_os")]

    if search:
        filtered = [r for r in filtered if search.upper() in r["symbol"].upper()]

    st.caption(f"Filter: **{active_filter}** | Showing **{len(filtered)}** / {len(results)} stocks")

    # ── Layout: stock list + chart ──
    col_list, col_chart = st.columns([2, 3])

    with col_list:
        # Build table data
        table_data = []
        for r in filtered:
            chg = r.get("change_pct", 0)
            chg_str = f"+{chg:.2f}%" if chg >= 0 else f"{chg:.2f}%"

            sto_zone = ""
            if r.get("in_ob"):
                sto_zone = "OB"
            elif r.get("in_os"):
                sto_zone = "OS"

            table_data.append({
                "Symbol": r["symbol"],
                "Price": f"{r['close']:.2f}",
                "Chg%": chg_str,
                "Trend": trend_badge(r.get("trend", "")),
                "Status": status_text(r.get("status", "")),
                "Zone": sto_zone,
                "StoDiv": "✓" if r.get("sto_div") else "",
                "RsiDiv": "✓" if r.get("rsi_div") else "",
                "Fibo": r.get("fibo_pos", "-"),
                "K": f"{r.get('stoch_k', 0):.0f}" if r.get("stoch_k") else "-",
            })

        if table_data:
            df_table = pd.DataFrame(table_data)

            # Use st.dataframe with selection
            event = st.dataframe(
                df_table,
                use_container_width=True,
                hide_index=True,
                height=500,
                on_select="rerun",
                selection_mode="single-row",
                key=f"table_{cat_key}",
            )

            # Handle row selection
            selected_rows = event.selection.rows if event.selection else []
            if selected_rows:
                selected_idx = selected_rows[0]
                selected_symbol = filtered[selected_idx]["symbol"]
                st.session_state[f"chart_symbol_{cat_key}"] = selected_symbol
        else:
            st.info("No stocks match the current filter.")

    with col_chart:
        chart_symbol = st.session_state.get(f"chart_symbol_{cat_key}")
        if chart_symbol:
            with st.spinner(f"Loading chart for {chart_symbol}..."):
                chart_data = get_chart_data(chart_symbol)
                if chart_data:
                    fig = build_chart(chart_data, chart_symbol)
                    st.plotly_chart(fig, use_container_width=True, key=f"chart_{cat_key}_{chart_symbol}")

                    # Scan info panel
                    scan = chart_data["scan"]
                    if scan:
                        info_cols = st.columns(4)
                        with info_cols[0]:
                            st.metric("Status", scan.get("status", "-"))
                        with info_cols[1]:
                            st.metric("Stoch K/D", f"{scan.get('stoch_k', '-')} / {scan.get('stoch_d', '-')}")
                        with info_cols[2]:
                            wl = scan.get("white_line")
                            st.metric("White Line", f"{wl:.2f}" if wl else "-")
                        with info_cols[3]:
                            rr = scan.get("rr_ratio")
                            st.metric("R:R", f"{rr:.2f}" if rr else "-")

                        info_cols2 = st.columns(4)
                        with info_cols2[0]:
                            st.metric("SL", f"{scan.get('sl_ref', '-')}")
                        with info_cols2[1]:
                            st.metric("TP", f"{scan.get('tp_ref', '-')}")
                        with info_cols2[2]:
                            st.metric("Swing Low", f"{scan.get('swing_price', '-')}")
                        with info_cols2[3]:
                            st.metric("Fibo Level", scan.get("fibo_pos", "-"))

                        st.caption(f"**Plan:** {scan.get('plan', '-')}")
                else:
                    st.error(f"Could not load data for {chart_symbol}")
        else:
            st.info("Select a stock from the table to view its chart.")


# ─── Simulator page ──────────────────────────────────────────────────

def render_simulator():
    """Render the simulator section with 3 mode tabs."""
    sim_tabs = st.tabs(["Sim - Entry Now", "Sim - WhiteLine", "Sim - RR1"])

    with sim_tabs[0]:
        render_sim_mode("entry")
    with sim_tabs[1]:
        render_sim_mode("retrace")
    with sim_tabs[2]:
        render_sim_mode("rr1")


def render_sim_mode(mode):
    """Render a single simulator mode."""
    mode_labels = {"entry": "Entry Now", "retrace": "WhiteLine", "rr1": "RR1"}
    mode_label = mode_labels[mode]

    # ── Scan button ──
    if st.button(f"🔄 Scan & Update ({mode_label})", key=f"btn_sim_scan_{mode}"):
        with st.spinner("Scanning all categories and updating trades..."):
            # Fetch USDTHB once and cache in session
            try:
                st.session_state["cached_usdthb"] = get_usdthb()
            except Exception:
                pass

            scan_results = _run_full_scan_cached()

            if mode == "entry":
                record_ready_signals(scan_results)
                fill_pending_trades()
                update_open_trades()
            elif mode == "retrace":
                record_retrace_signals(scan_results)
                fill_retrace_trades()
                update_retrace_trades()
            elif mode == "rr1":
                record_rr1_signals(scan_results)
                fill_rr1_trades()
                update_rr1_trades()

            st.success("Scan complete!")

    # ── Summary stats (no API calls on page load) ──
    summary = get_summary(mode=mode)
    # Use cached USDTHB or fallback — don't call Yahoo on every page render
    usdthb = st.session_state.get("cached_usdthb", 34.0)

    stat_cols = st.columns(8)
    with stat_cols[0]:
        st.metric("Budget/Trade", f"฿{BUDGET_THB:,.0f}")
    with stat_cols[1]:
        st.metric("USD/THB", f"{usdthb:.2f}")
    with stat_cols[2]:
        st.metric("Pending", summary["pending"])
    with stat_cols[3]:
        st.metric("Open", summary["open"])
    with stat_cols[4]:
        st.metric("TP / SL", f"{summary['tp_hit']} / {summary['sl_hit']}")
    with stat_cols[5]:
        st.metric("Win Rate", f"{summary['win_rate']:.1f}%")
    with stat_cols[6]:
        pnl = summary["total_pnl_thb"]
        st.metric("Realized P/L", f"฿{pnl:+,.0f}", delta_color="normal")
    with stat_cols[7]:
        unr = summary["total_unrealized_thb"]
        st.metric("Unrealized", f"฿{unr:+,.0f}")

    # ── Filters ──
    filter_cols = st.columns([1, 1, 1, 1, 1, 1, 1, 1])
    filter_key = f"sim_filter_{mode}"
    filter_options = [
        ("All", "all"), ("NASDAQ", "nasdaq100"), ("S&P500", "sp500"),
        ("SET", "set100"), ("Energy", "thai_energy"),
        ("Open", "open"), ("Pending", "pending"), ("Closed", "closed"),
    ]

    for i, (label, value) in enumerate(filter_options):
        with filter_cols[i]:
            if st.button(label, key=f"sim_f_{mode}_{value}"):
                st.session_state[filter_key] = value

    active_filter = st.session_state.get(filter_key, "all")

    # ── Load trades ──
    trades = load_trades(mode)

    # Apply filter
    if active_filter in ("nasdaq100", "sp500", "set100", "thai_energy"):
        trades = [t for t in trades if t["category"] == active_filter]
    elif active_filter == "open":
        trades = [t for t in trades if t["status"] == "open"]
    elif active_filter == "pending":
        trades = [t for t in trades if t["status"] == "pending"]
    elif active_filter == "closed":
        trades = [t for t in trades if t["status"] in ("tp_hit", "sl_hit")]

    # Sort
    status_order = {"open": 0, "pending": 1, "tp_hit": 2, "sl_hit": 3, "skipped": 4}
    trades.sort(key=lambda t: (status_order.get(t["status"], 9), t.get("entry_date") or "9999"))

    st.caption(f"Filter: **{active_filter}** | Showing **{len(trades)}** trades")

    if not trades:
        st.info("No trades found. Click 'Scan & Update' to record signals.")
        return

    # ── Layout: trade table + chart ──
    col_trades, col_chart = st.columns([3, 2])

    with col_trades:
        table_data = []
        for t in trades:
            status = t["status"]
            status_emoji = {
                "pending": "⏳", "open": "🟢", "tp_hit": "✅",
                "sl_hit": "❌", "skipped": "⏭️"
            }.get(status, "")

            cat_label = {
                "nasdaq100": "NASDAQ", "sp500": "S&P500",
                "set100": "SET", "thai_energy": "Energy"
            }.get(t.get("category", ""), "")

            pnl_val = ""
            if status in ("tp_hit", "sl_hit"):
                pnl_thb = t.get("pnl_thb", 0) or 0
                pnl_val = f"฿{pnl_thb:+,.0f}"
            elif status == "open":
                unr = t.get("unrealized_thb", 0) or 0
                pnl_val = f"฿{unr:+,.0f}"

            entry_display = t.get("entry_price", t.get("entry_target", "-"))
            if isinstance(entry_display, (int, float)):
                entry_display = f"{entry_display:.2f}"

            table_data.append({
                "Status": f"{status_emoji} {status}",
                "Market": cat_label,
                "Symbol": t["symbol"],
                "Signal": t.get("signal_date", "-"),
                "Entry": entry_display,
                "Shares": t.get("shares", 0),
                "SL": f"{t.get('sl', 0):.2f}" if t.get("sl") else "-",
                "TP": f"{t.get('tp', 0):.2f}" if t.get("tp") else "-",
                "P/L": pnl_val,
            })

        df_trades = pd.DataFrame(table_data)

        event = st.dataframe(
            df_trades,
            use_container_width=True,
            hide_index=True,
            height=450,
            on_select="rerun",
            selection_mode="single-row",
            key=f"sim_table_{mode}",
        )

        selected_rows = event.selection.rows if event.selection else []
        if selected_rows:
            selected_trade = trades[selected_rows[0]]
            st.session_state[f"sim_chart_{mode}"] = selected_trade

    with col_chart:
        selected_trade = st.session_state.get(f"sim_chart_{mode}")
        if selected_trade:
            sym = selected_trade["symbol"]
            with st.spinner(f"Loading chart for {sym}..."):
                chart_data = get_chart_data(sym)
                if chart_data:
                    fig = build_chart(chart_data, sym, trade_info=selected_trade)
                    st.plotly_chart(fig, use_container_width=True, key=f"sim_chart_fig_{mode}_{sym}")

                    # Trade details
                    det_cols = st.columns(4)
                    with det_cols[0]:
                        st.metric("Entry", selected_trade.get("entry_price") or selected_trade.get("entry_target") or "-")
                    with det_cols[1]:
                        st.metric("SL", selected_trade.get("sl", "-"))
                    with det_cols[2]:
                        st.metric("TP", selected_trade.get("tp", "-"))
                    with det_cols[3]:
                        st.metric("Status", selected_trade.get("status", "-"))
                else:
                    st.error(f"Could not load data for {sym}")
        else:
            st.info("Select a trade from the table to view its chart.")


def _run_full_scan_cached():
    """Run full scan across all categories."""
    scan_results = {}
    for cat_key, cat_info in ALL_CATEGORIES.items():
        symbols = list(dict.fromkeys(cat_info["symbols"]))
        all_data = batch_download(tuple(symbols))

        results = []
        for sym in symbols:
            df = all_data.get(sym)
            if df is None or len(df) < 30:
                continue
            try:
                df_indexed = df.copy()
                if "date" in df_indexed.columns:
                    df_indexed["date"] = pd.to_datetime(df_indexed["date"])
                    df_indexed = df_indexed.set_index("date")
                scan = scan_stock(df_indexed)
                if scan:
                    scan["symbol"] = sym
                    results.append(scan)
            except Exception:
                continue
        scan_results[cat_key] = results
    return scan_results


# ─── Main app ────────────────────────────────────────────────────────

st.title("KTP Stock Scanner")

main_tabs = st.tabs(["📊 Scanner", "💰 Simulator"])

with main_tabs[0]:
    render_scanner()

with main_tabs[1]:
    render_simulator()
