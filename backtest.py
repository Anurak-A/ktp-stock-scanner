"""
Backtest — Walk-forward simulation over 12 months.
For each trading day, run scanner. If Ready to Entry → enter next day at open.
Track TP/SL hits. Budget 50,000 THB per trade.
"""

import pandas as pd
import numpy as np
from scanner import calc_stochastic, detect_zones, find_swings_by_type, find_swing_in_zone, calc_white_line


def backtest_stock(df: pd.DataFrame, min_bars=60, rr_ratio=1.0) -> list:
    """
    Run walk-forward backtest on a single stock's daily data.
    Returns list of completed trades.
    """
    if df is None or len(df) < min_bars:
        return []

    trades = []
    pending = None  # pending entry from previous day's Ready to Entry
    open_trade = None  # currently open trade

    # Start from bar 60 to have enough history
    for day_idx in range(min_bars, len(df)):
        today = df.iloc[day_idx]
        today_date = df.index[day_idx]
        today_open = float(today["Open"])
        today_high = float(today["High"])
        today_low = float(today["Low"])
        today_close = float(today["Close"])

        # ─── Fill pending trade at today's open ───
        if pending is not None and open_trade is None:
            sl_dist = abs(today_open - pending["sl"])
            open_trade = {
                "signal_date": pending["signal_date"],
                "entry_date": today_date.strftime("%Y-%m-%d"),
                "entry_price": today_open,
                "sl": pending["sl"],
                "tp": today_open + sl_dist * rr_ratio,
                "white_line": pending["white_line"],
            }
            pending = None

        # ─── Check TP/SL for open trade ───
        if open_trade is not None:
            sl = open_trade["sl"]
            tp = open_trade["tp"]
            entry = open_trade["entry_price"]

            if today_low <= sl:
                # SL hit
                open_trade["close_date"] = today_date.strftime("%Y-%m-%d")
                open_trade["close_price"] = sl
                open_trade["pnl_pct"] = (sl - entry) / entry * 100
                open_trade["result"] = "SL"
                open_trade["bars_held"] = day_idx - df.index.get_loc(pd.Timestamp(open_trade["entry_date"]))
                trades.append(open_trade)
                open_trade = None
            elif today_high >= tp:
                # TP hit
                open_trade["close_date"] = today_date.strftime("%Y-%m-%d")
                open_trade["close_price"] = tp
                open_trade["pnl_pct"] = (tp - entry) / entry * 100
                open_trade["result"] = "TP"
                open_trade["bars_held"] = day_idx - df.index.get_loc(pd.Timestamp(open_trade["entry_date"]))
                trades.append(open_trade)
                open_trade = None

        # ─── Run scanner on data up to today ───
        if open_trade is None and pending is None:
            sub_df = df.iloc[:day_idx + 1]
            signal = _check_ready_to_entry(sub_df)
            if signal:
                pending = {
                    "signal_date": today_date.strftime("%Y-%m-%d"),
                    "sl": signal["sl"],
                    "white_line": signal["white_line"],
                }

    # Close any remaining open trade at last close
    if open_trade is not None:
        last = df.iloc[-1]
        last_close = float(last["Close"])
        entry = open_trade["entry_price"]
        open_trade["close_date"] = df.index[-1].strftime("%Y-%m-%d")
        open_trade["close_price"] = last_close
        open_trade["pnl_pct"] = (last_close - entry) / entry * 100
        open_trade["result"] = "OPEN"
        open_trade["bars_held"] = len(df) - 1 - df.index.get_loc(pd.Timestamp(open_trade["entry_date"]))
        trades.append(open_trade)

    return trades


def _check_ready_to_entry(df: pd.DataFrame) -> dict | None:
    """Check if the latest bar is Ready to Entry. Returns signal dict or None."""
    if len(df) < 30:
        return None

    stoch = calc_stochastic(df)
    zones = detect_zones(stoch)

    if len(zones) < 2:
        return None

    os_swings = find_swings_by_type(df, zones, "OS")
    ob_swings = find_swings_by_type(df, zones, "OB")

    if len(os_swings) < 2 or len(ob_swings) < 2:
        return None

    # Check trend: higher highs + higher lows = UT
    os_higher = os_swings[-1]["price"] > os_swings[-2]["price"]
    ob_higher = ob_swings[-1]["price"] > ob_swings[-2]["price"]

    if not (bool(os_higher) and bool(ob_higher)):
        return None

    latest_os = os_swings[-1]
    white_line = calc_white_line(df, latest_os)

    # Count bars that closed above WL
    si = latest_os["index"]
    wl_start = min(si + 2, len(df))
    first_cross_idx = None
    bars_over = 0

    for i in range(wl_start, len(df)):
        if float(df.iloc[i]["Close"]) > white_line:
            if first_cross_idx is None:
                first_cross_idx = i
            bars_over += 1

    # Ready to Entry: current bar is the FIRST and ONLY bar above WL
    if first_cross_idx == len(df) - 1 and bars_over == 1:
        sl = latest_os["price"] * 0.998

        return {
            "white_line": round(white_line, 4),
            "sl": round(sl, 4),
        }

    return None


def run_backtest(all_data: dict[str, pd.DataFrame], usdthb: float, budget_thb: float = 50000, rr_ratio: float = 1.0) -> list:
    """
    Run backtest on all stocks. Returns list of trade records.
    """
    all_trades = []

    for symbol, df in all_data.items():
        if df is None or len(df) < 60:
            continue

        try:
            stock_trades = backtest_stock(df, rr_ratio=rr_ratio)
            is_thai = symbol.endswith(".BK")

            for t in stock_trades:
                entry = t["entry_price"]
                if is_thai:
                    shares = int(budget_thb / entry)
                    invested = shares * entry
                    pnl_thb = (t["close_price"] - entry) * shares
                else:
                    price_thb = entry * usdthb
                    shares = int(budget_thb / price_thb)
                    invested = shares * entry * usdthb
                    pnl_thb = (t["close_price"] - entry) * shares * usdthb

                all_trades.append({
                    "symbol": symbol,
                    "is_thai": is_thai,
                    "signal_date": t["signal_date"],
                    "entry_date": t["entry_date"],
                    "entry_price": round(t["entry_price"], 4),
                    "close_date": t["close_date"],
                    "close_price": round(t["close_price"], 4),
                    "shares": shares,
                    "invested_thb": round(invested, 2),
                    "sl": round(t["sl"], 4),
                    "tp": round(t["tp"], 4),
                    "pnl_pct": round(t["pnl_pct"], 2),
                    "pnl_thb": round(pnl_thb, 2),
                    "result": t["result"],
                    "bars_held": t["bars_held"],
                })
        except Exception as e:
            print(f"  Backtest error {symbol}: {e}")

    # Sort by signal date
    all_trades.sort(key=lambda t: t["signal_date"])
    return all_trades


def calc_per_stock_rr(all_data: dict[str, pd.DataFrame], usdthb: float, budget_thb: float = 50000) -> list:
    """
    For each stock, test RR 0.5, 0.75, 1.0, 1.25 and find the best RR.
    Returns list of per-stock analysis.
    """
    rr_options = [0.5, 0.75, 1.0, 1.25]
    results = []

    for symbol, df in all_data.items():
        if df is None or len(df) < 60:
            continue

        is_thai = symbol.endswith(".BK")
        best_rr = None
        best_pnl = float("-inf")
        rr_details = {}

        for rr in rr_options:
            try:
                trades = backtest_stock(df, rr_ratio=rr)
                tp_trades = [t for t in trades if t.get("pnl_pct", 0) > 0 or (t.get("close_price", 0) > t.get("entry_price", 0))]
                sl_trades = [t for t in trades if t.get("pnl_pct", 0) < 0]

                # Calc P/L in THB
                total_pnl_thb = 0
                for t in trades:
                    entry = t["entry_price"]
                    close_p = t["close_price"]
                    if is_thai:
                        shares = int(budget_thb / entry)
                        pnl = (close_p - entry) * shares
                    else:
                        shares = int(budget_thb / (entry * usdthb))
                        pnl = (close_p - entry) * shares * usdthb
                    total_pnl_thb += pnl

                tp_count = len([t for t in trades if t.get("result") == "TP"])
                sl_count = len([t for t in trades if t.get("result") == "SL"])
                total = tp_count + sl_count
                wr = tp_count / total * 100 if total else 0

                rr_details[rr] = {
                    "trades": total,
                    "tp": tp_count,
                    "sl": sl_count,
                    "wr": round(wr, 1),
                    "pnl_thb": round(total_pnl_thb, 2),
                }

                if total_pnl_thb > best_pnl and total > 0:
                    best_pnl = total_pnl_thb
                    best_rr = rr

            except Exception:
                rr_details[rr] = {"trades": 0, "tp": 0, "sl": 0, "wr": 0, "pnl_thb": 0}

        if best_rr is not None:
            results.append({
                "symbol": symbol,
                "best_rr": best_rr,
                "best_pnl_thb": round(best_pnl, 2),
                "rr_details": rr_details,
            })

    results.sort(key=lambda x: -x["best_pnl_thb"])
    return results


def calc_backtest_summary(trades: list) -> dict:
    """Calculate summary statistics from backtest trades."""
    if not trades:
        return {"total": 0}

    tp_trades = [t for t in trades if t["result"] == "TP"]
    sl_trades = [t for t in trades if t["result"] == "SL"]
    closed = tp_trades + sl_trades

    total_pnl = sum(t["pnl_thb"] for t in closed)
    win_rate = len(tp_trades) / len(closed) * 100 if closed else 0
    avg_win = np.mean([t["pnl_thb"] for t in tp_trades]) if tp_trades else 0
    avg_loss = np.mean([t["pnl_thb"] for t in sl_trades]) if sl_trades else 0
    avg_bars = np.mean([t["bars_held"] for t in closed]) if closed else 0
    max_win = max((t["pnl_thb"] for t in tp_trades), default=0)
    max_loss = min((t["pnl_thb"] for t in sl_trades), default=0)

    return {
        "total": len(trades),
        "closed": len(closed),
        "tp": len(tp_trades),
        "sl": len(sl_trades),
        "still_open": len([t for t in trades if t["result"] == "OPEN"]),
        "win_rate": round(win_rate, 1),
        "total_pnl_thb": round(total_pnl, 2),
        "avg_win_thb": round(avg_win, 2),
        "avg_loss_thb": round(avg_loss, 2),
        "max_win_thb": round(max_win, 2),
        "max_loss_thb": round(max_loss, 2),
        "avg_bars_held": round(avg_bars, 1),
        "profit_factor": round(abs(sum(t["pnl_thb"] for t in tp_trades)) / abs(sum(t["pnl_thb"] for t in sl_trades)), 2) if sl_trades and sum(t["pnl_thb"] for t in sl_trades) != 0 else 0,
    }
