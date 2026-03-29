"""
Simulator — Auto-record trades from Ready to Entry signals.
Entry at next day's open price. Budget 50,000 THB per trade.
"""

import json
import os
from datetime import datetime, timedelta
import yfinance as yf
import pandas as pd

TRADES_FILE = os.path.join(os.path.dirname(__file__), "trades.json")
BUDGET_THB = 50000

# ─── Exchange rate ────────────────────────────────────────────────────

_usdthb_cache = {"rate": None, "ts": 0}

def get_usdthb() -> float:
    """Get current USD/THB rate. Cache for 1 hour."""
    import time
    now = time.time()
    if _usdthb_cache["rate"] and (now - _usdthb_cache["ts"]) < 3600:
        return _usdthb_cache["rate"]
    try:
        tk = yf.download("USDTHB=X", period="5d", interval="1d", progress=False)
        if isinstance(tk.columns, pd.MultiIndex):
            # Find and drop the ticker level, keep price level
            for lvl_idx in range(tk.columns.nlevels):
                vals = tk.columns.get_level_values(lvl_idx).unique().tolist()
                if "USDTHB=X" in vals:
                    tk = tk.droplevel(lvl_idx, axis=1)
                    break
            tk.columns = [str(c) for c in tk.columns]
        rate = float(tk["Close"].dropna().iloc[-1])
        _usdthb_cache["rate"] = rate
        _usdthb_cache["ts"] = now
        return rate
    except Exception:
        return 34.0  # fallback


# ─── Trade storage ────────────────────────────────────────────────────

def load_trades() -> list:
    if os.path.exists(TRADES_FILE):
        with open(TRADES_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    return []


def save_trades(trades: list):
    with open(TRADES_FILE, "w", encoding="utf-8") as f:
        json.dump(trades, f, indent=2, ensure_ascii=False)


# ─── Category priority (dedup) ───────────────────────────────────────

CATEGORY_PRIORITY = {
    "nasdaq100": 0,
    "sp500": 1,
    "set100": 2,
    "thai_energy": 3,
}


def get_best_category(symbol: str, categories_found: list[str]) -> str:
    """If symbol appears in multiple categories, pick highest priority."""
    return min(categories_found, key=lambda c: CATEGORY_PRIORITY.get(c, 99))


# ─── Position sizing ─────────────────────────────────────────────────

def calc_shares(price: float, is_thai: bool, usdthb: float) -> int:
    """Calculate whole shares for 50,000 THB budget."""
    if is_thai:
        return int(BUDGET_THB / price)
    else:
        price_thb = price * usdthb
        return int(BUDGET_THB / price_thb)


def is_thai_stock(symbol: str) -> bool:
    return symbol.endswith(".BK")


# ─── Record new signals ──────────────────────────────────────────────

def record_ready_signals(scan_results: dict[str, list]) -> dict:
    """
    scan_results: { category: [{ symbol, status, is_ready_entry, sl_ref, tp_ref, close, ... }] }
    Returns summary of actions taken.
    """
    trades = load_trades()
    usdthb = get_usdthb()
    today = datetime.now().strftime("%Y-%m-%d")

    # Build set of existing pending/open symbols
    active_symbols = set()
    for t in trades:
        if t["status"] in ("pending", "open"):
            active_symbols.add(t["symbol"])

    # Collect all ready signals with dedup
    symbol_categories = {}  # symbol -> [categories]
    symbol_data = {}  # symbol -> scan data

    for category, results in scan_results.items():
        for r in results:
            if r.get("is_ready_entry") and r.get("suitable", False):
                sym = r["symbol"]
                if sym not in symbol_categories:
                    symbol_categories[sym] = []
                    symbol_data[sym] = r
                symbol_categories[sym].append(category)

    new_pending = 0
    for sym, cats in symbol_categories.items():
        if sym in active_symbols:
            continue

        best_cat = get_best_category(sym, cats)
        r = symbol_data[sym]

        trade = {
            "symbol": sym,
            "category": best_cat,
            "signal_date": today,
            "entry_date": None,
            "entry_price": None,
            "shares": 0,
            "budget_thb": BUDGET_THB,
            "sl": r.get("sl_ref"),
            "tp": r.get("tp_ref"),
            "white_line": r.get("white_line"),
            "signal_close": r.get("close"),
            "is_thai": is_thai_stock(sym),
            "usdthb_at_signal": usdthb,
            "status": "pending",
            "close_date": None,
            "close_price": None,
            "pnl": None,
            "pnl_thb": None,
        }
        trades.append(trade)
        new_pending += 1

    save_trades(trades)
    return {"new_pending": new_pending, "total_active": len(active_symbols) + new_pending}


# ─── Fill pending trades with next day's open ────────────────────────

def fill_pending_trades() -> dict:
    """
    For pending trades, check if next trading day data is available.
    If so, fill at open price and calculate shares.
    """
    trades = load_trades()
    usdthb = get_usdthb()
    filled = 0

    for trade in trades:
        if trade["status"] != "pending":
            continue

        sym = trade["symbol"]
        try:
            raw = yf.download(sym, period="5d", interval="1d", progress=False)
            if isinstance(raw.columns, pd.MultiIndex):
                for lvl_idx in range(raw.columns.nlevels):
                    vals = raw.columns.get_level_values(lvl_idx).unique().tolist()
                    if sym in vals:
                        raw = raw.xs(sym, level=lvl_idx, axis=1)
                        break
                else:
                    raw = raw.droplevel(1, axis=1) if raw.columns.nlevels > 1 else raw
            raw.columns = [str(c) for c in raw.columns]

            if raw.empty or "Open" not in raw.columns:
                continue

            signal_date = pd.Timestamp(trade["signal_date"])
            # Find first trading day AFTER signal date
            future_bars = raw[raw.index > signal_date]
            if future_bars.empty:
                continue

            entry_bar = future_bars.iloc[0]
            entry_price = float(entry_bar["Open"])
            entry_date = future_bars.index[0].strftime("%Y-%m-%d")

            thai = trade.get("is_thai", is_thai_stock(sym))
            shares = calc_shares(entry_price, thai, usdthb)

            if shares < 1:
                trade["status"] = "skipped"
                continue

            trade["entry_date"] = entry_date
            trade["entry_price"] = round(entry_price, 4)
            trade["shares"] = shares
            trade["usdthb_at_entry"] = usdthb
            trade["status"] = "open"
            filled += 1

        except Exception as e:
            print(f"  Fill error {sym}: {e}")

    save_trades(trades)
    return {"filled": filled}


# ─── Update open trades (check TP/SL hit) ────────────────────────────

def update_open_trades() -> dict:
    """Check if any open trades hit TP or SL."""
    trades = load_trades()
    usdthb = get_usdthb()
    closed = 0

    open_trades = [t for t in trades if t["status"] == "open"]
    if not open_trades:
        return {"closed": 0}

    for trade in open_trades:
        sym = trade["symbol"]
        tp = trade.get("tp")
        sl = trade.get("sl")
        entry_price = trade["entry_price"]

        if not tp or not sl:
            continue

        try:
            raw = yf.download(sym, period="10d", interval="1d", progress=False)
            if isinstance(raw.columns, pd.MultiIndex):
                for lvl_idx in range(raw.columns.nlevels):
                    vals = raw.columns.get_level_values(lvl_idx).unique().tolist()
                    if sym in vals:
                        raw = raw.xs(sym, level=lvl_idx, axis=1)
                        break
                else:
                    raw = raw.droplevel(1, axis=1) if raw.columns.nlevels > 1 else raw
            raw.columns = [str(c) for c in raw.columns]

            if raw.empty:
                continue

            entry_date = pd.Timestamp(trade["entry_date"])
            bars_after_entry = raw[raw.index >= entry_date]

            for idx, bar in bars_after_entry.iterrows():
                high = float(bar["High"])
                low = float(bar["Low"])
                close = float(bar["Close"])

                # Check SL hit first (worst case)
                if low <= sl:
                    trade["status"] = "sl_hit"
                    trade["close_price"] = round(sl, 4)
                    trade["close_date"] = idx.strftime("%Y-%m-%d")
                    pnl_per_share = sl - entry_price
                    trade["pnl"] = round(pnl_per_share * trade["shares"], 2)
                    if trade.get("is_thai"):
                        trade["pnl_thb"] = trade["pnl"]
                    else:
                        trade["pnl_thb"] = round(trade["pnl"] * usdthb, 2)
                    closed += 1
                    break

                # Check TP hit
                if high >= tp:
                    trade["status"] = "tp_hit"
                    trade["close_price"] = round(tp, 4)
                    trade["close_date"] = idx.strftime("%Y-%m-%d")
                    pnl_per_share = tp - entry_price
                    trade["pnl"] = round(pnl_per_share * trade["shares"], 2)
                    if trade.get("is_thai"):
                        trade["pnl_thb"] = trade["pnl"]
                    else:
                        trade["pnl_thb"] = round(trade["pnl"] * usdthb, 2)
                    closed += 1
                    break

            # Update current price for open trades
            if trade["status"] == "open":
                last_close = float(raw.iloc[-1]["Close"])
                trade["current_price"] = round(last_close, 4)
                unrealized = (last_close - entry_price) * trade["shares"]
                if trade.get("is_thai"):
                    trade["unrealized_thb"] = round(unrealized, 2)
                else:
                    trade["unrealized_thb"] = round(unrealized * usdthb, 2)

        except Exception as e:
            print(f"  Update error {sym}: {e}")

    save_trades(trades)
    return {"closed": closed}


# ─── Summary stats ────────────────────────────────────────────────────

def get_summary(category_filter: str = None) -> dict:
    trades = load_trades()

    if category_filter and category_filter != "all":
        trades = [t for t in trades if t["category"] == category_filter]

    open_trades = [t for t in trades if t["status"] == "open"]
    pending_trades = [t for t in trades if t["status"] == "pending"]
    tp_trades = [t for t in trades if t["status"] == "tp_hit"]
    sl_trades = [t for t in trades if t["status"] == "sl_hit"]

    total_pnl = sum(t.get("pnl_thb", 0) or 0 for t in tp_trades + sl_trades)
    total_unrealized = sum(t.get("unrealized_thb", 0) or 0 for t in open_trades)
    win_rate = len(tp_trades) / (len(tp_trades) + len(sl_trades)) * 100 if (tp_trades or sl_trades) else 0

    return {
        "pending": len(pending_trades),
        "open": len(open_trades),
        "tp_hit": len(tp_trades),
        "sl_hit": len(sl_trades),
        "total_trades": len(tp_trades) + len(sl_trades),
        "win_rate": round(win_rate, 1),
        "total_pnl_thb": round(total_pnl, 2),
        "total_unrealized_thb": round(total_unrealized, 2),
    }
