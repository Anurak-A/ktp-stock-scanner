"""
Per-stock Fibo + RR Backtest Analysis (12 months)
For each stock in Uptrend: find which Fibo level bounce happens at,
and optimal RR for each fibo level.
"""
import pandas as pd
import numpy as np
import json
from scanner import (
    calc_stochastic, detect_zones, find_swings_by_type,
    find_swing_in_zone, calc_white_line, FIBO_LEVELS
)


def calc_fibo_at_entry(os_swings, ob_swings, latest_os):
    """
    Calculate which fibo level the swing low (entry zone) bounced from.
    Fibo: OB before this OS (0.0) -> OS before that OB (1.0)
    Then see where latest_os falls in that range.
    """
    # Find the OB swing just before this OS
    ob_before = None
    for ob in reversed(ob_swings):
        if ob["index"] < latest_os["index"]:
            ob_before = ob
            break
    if not ob_before:
        return None

    # Find the OS swing before that OB
    os_before = None
    for os_sw in reversed(os_swings):
        if os_sw["index"] < ob_before["index"]:
            os_before = os_sw
            break
    if not os_before:
        return None

    # Fibo: OB (0.0) -> previous OS (1.0)
    ob_price = ob_before["price"]
    os_price = os_before["price"]
    diff = ob_price - os_price

    if abs(diff) < 1e-10:
        return None

    # Where does the current OS low fall?
    ratio = (ob_price - latest_os["price"]) / diff

    # Find nearest fibo level
    nearest = min(FIBO_LEVELS, key=lambda lvl: abs(ratio - lvl))
    return nearest


def backtest_stock_fibo(df, min_bars=60, rr_ratios=None):
    """
    Walk-forward: at each Ready to Entry (UT + WL break),
    record fibo level + test multiple RR ratios.
    """
    if rr_ratios is None:
        rr_ratios = [0.5, 0.75, 1.0, 1.25, 1.5]

    if df is None or len(df) < min_bars:
        return []

    all_trades = []
    last_signal_date = None  # avoid duplicate signals

    for day_idx in range(min_bars, len(df) - 1):
        sub_df = df.iloc[:day_idx + 1]

        stoch = calc_stochastic(sub_df)
        zones = detect_zones(stoch)
        if len(zones) < 2:
            continue

        os_swings = find_swings_by_type(sub_df, zones, "OS")
        ob_swings = find_swings_by_type(sub_df, zones, "OB")

        if len(os_swings) < 2 or len(ob_swings) < 2:
            continue

        # Check UT
        if not (os_swings[-1]["price"] > os_swings[-2]["price"] and
                ob_swings[-1]["price"] > ob_swings[-2]["price"]):
            continue

        latest_os = os_swings[-1]
        wl = calc_white_line(sub_df, latest_os)

        # Check WL break: current bar is first and only bar above WL
        si = latest_os["index"]
        wl_start = min(si + 2, len(sub_df))
        first_cross = None
        bars_over = 0
        for i in range(wl_start, len(sub_df)):
            if float(sub_df.iloc[i]["Close"]) > wl:
                if first_cross is None:
                    first_cross = i
                bars_over += 1

        if not (first_cross == len(sub_df) - 1 and bars_over == 1):
            continue

        signal_date = sub_df.index[day_idx].strftime("%Y-%m-%d")
        if signal_date == last_signal_date:
            continue
        last_signal_date = signal_date

        # Fibo level at entry
        fibo_lvl = calc_fibo_at_entry(os_swings, ob_swings, latest_os)

        # Entry at next day open
        entry_price = float(df.iloc[day_idx + 1]["Open"])
        sl = latest_os["price"] * 0.998
        sl_dist = abs(entry_price - sl)
        if sl_dist < 1e-10:
            continue

        for rr in rr_ratios:
            tp = entry_price + sl_dist * rr
            result = None
            close_price = None
            bars_held = 0

            for fi in range(day_idx + 1, len(df)):
                high = float(df.iloc[fi]["High"])
                low = float(df.iloc[fi]["Low"])
                bars_held = fi - (day_idx + 1)

                if low <= sl:
                    result = "SL"
                    close_price = sl
                    break
                if high >= tp:
                    result = "TP"
                    close_price = tp
                    break

            if result is None:
                continue  # skip open trades

            pnl_pct = (close_price - entry_price) / entry_price * 100

            all_trades.append({
                "signal_date": signal_date,
                "rr": rr,
                "result": result,
                "pnl_pct": round(pnl_pct, 2),
                "bars_held": bars_held,
                "fibo_level": fibo_lvl,
            })

    return all_trades


def run_analysis(all_data, symbols):
    """Run per-stock fibo+RR analysis."""
    rr_ratios = [0.5, 0.75, 1.0, 1.25, 1.5]
    results = []

    for sym in symbols:
        df = all_data.get(sym)
        if df is None or len(df) < 60:
            continue

        df_idx = df.copy()
        if "date" in df_idx.columns:
            df_idx["date"] = pd.to_datetime(df_idx["date"])
            df_idx = df_idx.set_index("date")

        trades = backtest_stock_fibo(df_idx, rr_ratios=rr_ratios)
        if not trades:
            continue

        # Group by fibo_level + rr
        fibo_rr_stats = {}
        for t in trades:
            key = (t["fibo_level"], t["rr"])
            if key not in fibo_rr_stats:
                fibo_rr_stats[key] = {"tp": 0, "sl": 0}
            if t["result"] == "TP":
                fibo_rr_stats[key]["tp"] += 1
            else:
                fibo_rr_stats[key]["sl"] += 1

        # Best RR per fibo level (highest EV with WR >= 50%)
        # EV = WR * RR - (1-WR) * 1  (per unit risk)
        fibo_best = {}
        for (fibo, rr), stats in fibo_rr_stats.items():
            total = stats["tp"] + stats["sl"]
            if total == 0:
                continue
            wr = stats["tp"] / total
            ev = wr * rr - (1 - wr) * 1  # expected value per trade
            wr_pct = wr * 100
            if wr_pct < 50:
                continue  # skip low WR combos
            fibo_key = str(fibo) if fibo is not None else "N/A"
            if fibo_key not in fibo_best or ev > fibo_best[fibo_key]["ev"]:
                fibo_best[fibo_key] = {
                    "rr": rr, "wr": round(wr_pct, 1), "ev": round(ev, 3),
                    "tp": stats["tp"], "sl": stats["sl"], "total": total,
                }

        # Overall best RR (highest EV with WR >= 50%)
        best_rr = None
        best_ev = -999
        best_wr = 0
        for rr in rr_ratios:
            rr_trades = [t for t in trades if t["rr"] == rr]
            if not rr_trades:
                continue
            tp_c = sum(1 for t in rr_trades if t["result"] == "TP")
            total_c = len(rr_trades)
            wr = tp_c / total_c
            ev = wr * rr - (1 - wr) * 1
            if wr >= 0.5 and ev > best_ev:
                best_ev = ev
                best_wr = wr * 100
                best_rr = rr

        if not fibo_best:
            continue

        results.append({
            "symbol": sym,
            "total_signals": len(set(t["signal_date"] for t in trades)),
            "best_rr": best_rr,
            "best_wr": round(best_wr, 1),
            "fibo_breakdown": fibo_best,
        })

    return results


if __name__ == "__main__":
    from app import batch_download
    from stocks import NASDAQ_100

    symbols = NASDAQ_100
    print(f"Downloading {len(symbols)} symbols...")
    all_data = batch_download(symbols, period="1y")
    print(f"Got {len(all_data)}\n")

    print("Running per-stock Fibo + RR analysis (12 months)...\n")
    results = run_analysis(all_data, symbols)

    results.sort(key=lambda x: -x["best_wr"])

    print(f"{'Symbol':<8} {'Sigs':>4} {'BestRR':>6} {'WR%':>6}  Fibo Breakdown (best EV per level, WR>=50%)")
    print("=" * 110)

    for r in results:
        parts = []
        for fibo_lvl in sorted(r["fibo_breakdown"].keys(), key=lambda x: float(x) if x != "N/A" else 99):
            fb = r["fibo_breakdown"][fibo_lvl]
            parts.append(f"Fib{fibo_lvl}:RR{fb['rr']}={fb['wr']}%({fb['tp']}W/{fb['sl']}L)EV{fb['ev']}")

        fibo_str = "  ".join(parts) if parts else "-"
        rr_str = f"{r['best_rr']}" if r['best_rr'] is not None else "-"
        print(f"{r['symbol']:<8} {r['total_signals']:>4} {rr_str:>6} {r['best_wr']:>5.1f}%  {fibo_str}")

    with open("backtest_fibo_rr_result.json", "w") as f:
        json.dump(results, f, indent=2, default=str)

    print(f"\nTotal: {len(results)} stocks with trades")
    print("Saved to backtest_fibo_rr_result.json")
