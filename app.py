"""
Stock Scanner — Flask backend
Serves stock data, charts (D1), and scan results.
Uses yf.download() for batch fetching to avoid rate limits.
"""

from flask import Flask, render_template, jsonify, request
import yfinance as yf
import pandas as pd
import time
import threading
from scanner import scan_stock, calc_stochastic, calc_rsi
from stocks import ALL_CATEGORIES
from simulator import (
    record_ready_signals, fill_pending_trades, update_open_trades,
    load_trades, get_summary, get_usdthb, BUDGET_THB
)

app = Flask(__name__)


@app.after_request
def add_no_cache(response):
    """Prevent browser from caching API and static files."""
    response.headers["Cache-Control"] = "no-cache, no-store, must-revalidate"
    response.headers["Pragma"] = "no-cache"
    response.headers["Expires"] = "0"
    return response

# In-memory cache: { "category:symbol": { "data": df, "ts": timestamp } }
_cache: dict[str, dict] = {}
CACHE_TTL = 600  # 10 minutes


def batch_download(symbols: list[str], period: str = "1y") -> dict[str, pd.DataFrame]:
    """
    Download daily data for multiple symbols at once using yf.download().
    Returns dict of symbol -> DataFrame.
    """
    if not symbols:
        return {}

    now = time.time()
    # Check which symbols need fresh data
    to_fetch = []
    cached = {}
    for s in symbols:
        key = f"{s}:{period}"
        if key in _cache and (now - _cache[key]["ts"]) < CACHE_TTL:
            cached[s] = _cache[key]["data"]
        else:
            to_fetch.append(s)

    if not to_fetch:
        return cached

    result = dict(cached)

    # Download in chunks to avoid timeouts
    chunk_size = 10  # smaller chunks to avoid rate limits on cloud
    for i in range(0, len(to_fetch), chunk_size):
        chunk = to_fetch[i:i + chunk_size]
        for attempt in range(3):  # retry up to 3 times
            try:
                raw = yf.download(
                    " ".join(chunk),
                    period=period,
                    interval="1d",
                    group_by="ticker",
                    progress=False,
                    threads=True,
                    timeout=30,
                )

                if raw.empty:
                    break

                for sym in chunk:
                    try:
                        if isinstance(raw.columns, pd.MultiIndex):
                            ticker_level = None
                            for lvl_idx in range(raw.columns.nlevels):
                                vals = raw.columns.get_level_values(lvl_idx).unique().tolist()
                                if sym in vals:
                                    ticker_level = lvl_idx
                                    break

                            if ticker_level is not None:
                                df = raw.xs(sym, level=ticker_level, axis=1).copy()
                            elif len(chunk) == 1:
                                for lvl_idx in range(raw.columns.nlevels):
                                    vals = raw.columns.get_level_values(lvl_idx).unique().tolist()
                                    if any(v in ["Open", "High", "Low", "Close", "Volume"] for v in vals):
                                        continue
                                    df = raw.droplevel(lvl_idx, axis=1).copy()
                                    break
                                else:
                                    continue
                            else:
                                continue
                            df.columns = [str(c) for c in df.columns]
                        else:
                            df = raw.copy()

                        if "Close" not in df.columns:
                            continue
                        df = df.dropna(subset=["Close"])
                        if df.empty or len(df) < 30:
                            continue

                        df = df.reset_index()
                        date_col = [c for c in df.columns if "date" in c.lower() or "Date" in str(c)]
                        if date_col:
                            df = df.rename(columns={date_col[0]: "date"})

                        result[sym] = df
                        _cache[f"{sym}:{period}"] = {"data": df, "ts": now}
                    except Exception as e:
                        print(f"  Parse error {sym}: {e}")

                break  # success, no need to retry

            except Exception as e:
                print(f"Batch download error (attempt {attempt+1}): {e}")
                if attempt < 2:
                    time.sleep(2)

    return result


def fetch_single(symbol: str, period: str = "1y") -> pd.DataFrame | None:
    """Fetch a single symbol (used for chart endpoint)."""
    data = batch_download([symbol], period)
    return data.get(symbol)


@app.route("/")
def index():
    return render_template("index.html", categories=ALL_CATEGORIES)


@app.route("/api/categories")
def api_categories():
    return jsonify({k: {"name": v["name"], "count": len(v["symbols"])} for k, v in ALL_CATEGORIES.items()})


@app.route("/api/scan/<category>")
def api_scan(category):
    """Scan all stocks in a category using batch download."""
    if category not in ALL_CATEGORIES:
        return jsonify({"error": "Unknown category"}), 400

    symbols = ALL_CATEGORIES[category]["symbols"]
    # Remove duplicates while preserving order
    symbols = list(dict.fromkeys(symbols))

    print(f"Scanning {len(symbols)} symbols for {category}...")
    all_data = batch_download(symbols)
    print(f"  Downloaded {len(all_data)} symbols")

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
        except Exception as e:
            print(f"  Scan error {symbol}: {e}")
            continue

    # Default sort: A-Z by symbol
    results.sort(key=lambda x: x.get("symbol", ""))

    return jsonify(results)


@app.route("/api/chart/<symbol>")
def api_chart(symbol):
    """Return OHLCV + Stochastic data for charting."""
    period = request.args.get("period", "1y")
    df = fetch_single(symbol, period)
    if df is None:
        return jsonify({"error": "No data"}), 404

    df_indexed = df.copy()
    if "date" in df_indexed.columns:
        df_indexed["date"] = pd.to_datetime(df_indexed["date"])
        df_indexed = df_indexed.set_index("date")

    stoch = calc_stochastic(df_indexed)
    rsi = calc_rsi(df_indexed)

    # Build all series from df_indexed using positional index
    # so candle, stoch, rsi share the exact same date sequence.
    candles = []
    stoch_data = []
    volumes = []
    rsi_data = []

    for i in range(len(df_indexed)):
        dt = df_indexed.index[i]
        ts = dt.strftime("%Y-%m-%d") if hasattr(dt, "strftime") else str(dt)[:10]

        row = df_indexed.iloc[i]
        k_val = stoch["K"].iloc[i]
        d_val = stoch["D"].iloc[i]
        rsi_val = rsi["RSI"].iloc[i]

        # Skip warm-up bars where indicators are NaN
        if pd.isna(k_val) or pd.isna(rsi_val):
            continue

        candles.append({
            "time": ts,
            "open": round(float(row["Open"]), 4),
            "high": round(float(row["High"]), 4),
            "low": round(float(row["Low"]), 4),
            "close": round(float(row["Close"]), 4),
        })
        volumes.append({
            "time": ts,
            "value": int(row["Volume"]) if "Volume" in df_indexed.columns else 0,
            "color": "rgba(38,166,154,0.5)" if float(row["Close"]) >= float(row["Open"]) else "rgba(239,83,80,0.5)",
        })
        stoch_data.append({
            "time": ts,
            "k": round(float(k_val), 2),
            "d": round(float(d_val), 2) if not pd.isna(d_val) else round(float(k_val), 2),
        })
        rsi_data.append({
            "time": ts,
            "value": round(float(rsi_val), 2),
        })

    # Run scan
    scan_result = None
    try:
        scan_result = scan_stock(df_indexed)
    except Exception:
        pass

    return jsonify({
        "symbol": symbol,
        "candles": candles,
        "volumes": volumes,
        "stochastic": stoch_data,
        "rsi": rsi_data,
        "scan": scan_result,
    })


# ─── Simulator API ────────────────────────────────────────────────────

@app.route("/api/simulator/scan")
def api_simulator_scan():
    """Scan all categories for Ready to Entry signals and record them."""
    scan_results = {}
    for cat_key, cat_info in ALL_CATEGORIES.items():
        symbols = list(dict.fromkeys(cat_info["symbols"]))
        all_data = batch_download(symbols)

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

    # Record new ready signals
    record_result = record_ready_signals(scan_results)
    # Fill pending trades with next day open
    fill_result = fill_pending_trades()
    # Update open trades (TP/SL check)
    update_result = update_open_trades()

    return jsonify({
        **record_result,
        **fill_result,
        **update_result,
    })


@app.route("/api/simulator/trades")
def api_simulator_trades():
    """Get all trades with optional category filter."""
    category = request.args.get("category", "all")
    trades = load_trades()

    if category and category != "all":
        trades = [t for t in trades if t["category"] == category]

    # Sort: open first, then pending, then closed
    status_order = {"open": 0, "pending": 1, "tp_hit": 2, "sl_hit": 3, "skipped": 4}
    trades.sort(key=lambda t: (status_order.get(t["status"], 9), t.get("entry_date") or "9999"))

    return jsonify(trades)


@app.route("/api/simulator/summary")
def api_simulator_summary():
    """Get summary stats."""
    category = request.args.get("category", "all")
    summary = get_summary(category)
    summary["budget_per_trade"] = BUDGET_THB
    summary["usdthb"] = get_usdthb()
    return jsonify(summary)


# ─── Auto Scan Scheduler (04:00 Bangkok time daily) ──────────────────

def run_daily_scan():
    """Run simulator scan: record signals, fill pending, update open trades."""
    with app.app_context():
        print(f"[AUTO-SCAN] Starting daily scan...")
        scan_results = {}
        for cat_key, cat_info in ALL_CATEGORIES.items():
            symbols = list(dict.fromkeys(cat_info["symbols"]))
            all_data = batch_download(symbols)
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

        r1 = record_ready_signals(scan_results)
        r2 = fill_pending_trades()
        r3 = update_open_trades()
        print(f"[AUTO-SCAN] Done — new_pending={r1.get('new_pending',0)}, filled={r2.get('filled',0)}, closed={r3.get('closed',0)}")


def scheduler_loop():
    """Run daily scan at 04:00 Bangkok time (UTC+7) = 21:00 UTC."""
    from datetime import datetime, timedelta
    import pytz

    bkk = pytz.timezone("Asia/Bangkok")

    while True:
        now = datetime.now(bkk)
        # Next 04:00
        target = now.replace(hour=4, minute=0, second=0, microsecond=0)
        if now >= target:
            target += timedelta(days=1)

        wait_seconds = (target - now).total_seconds()
        print(f"[SCHEDULER] Next scan at {target.strftime('%Y-%m-%d %H:%M')} BKK ({int(wait_seconds)}s)")
        time.sleep(wait_seconds)

        try:
            run_daily_scan()
        except Exception as e:
            print(f"[SCHEDULER] Error: {e}")


def start_scheduler():
    t = threading.Thread(target=scheduler_loop, daemon=True)
    t.start()
    print("[SCHEDULER] Started — daily scan at 04:00 Bangkok time")




# Start scheduler (only once, avoid duplicate in gunicorn workers)
import os
if os.environ.get("WERKZEUG_RUN_MAIN") == "true" or not os.environ.get("GUNICORN_WORKER"):
    start_scheduler()

if __name__ == "__main__":
    app.run(host="0.0.0.0", debug=False, port=5000)
