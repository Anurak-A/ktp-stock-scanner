"""
Stock Scanner — Strategy logic (White Line + Stochastic + Fibonacci)
All calculations on Daily (D1) timeframe.
No Elliott Wave — entry based on UT + WL break only.
"""

import numpy as np
import pandas as pd


# ─── RSI ─────────────────────────────────────────────────────────────

def calc_rsi(df: pd.DataFrame, period=14):
    """Calculate RSI (Relative Strength Index)."""
    delta = df["Close"].diff()
    gain = delta.where(delta > 0, 0.0)
    loss = -delta.where(delta < 0, 0.0)
    avg_gain = gain.rolling(window=period).mean()
    avg_loss = loss.rolling(window=period).mean()
    rs = avg_gain / (avg_loss + 1e-10)
    rsi = 100 - (100 / (1 + rs))
    return pd.DataFrame({"RSI": rsi}, index=df.index)


# ─── Stochastic (9,3,3) ───────────────────────────────────────────────

def calc_stochastic(df: pd.DataFrame, k_period=9, d_period=3, smooth_k=3):
    """Return DataFrame with columns: K, D"""
    low_min = df["Low"].rolling(window=k_period).min()
    high_max = df["High"].rolling(window=k_period).max()
    raw_k = 100 * (df["Close"] - low_min) / (high_max - low_min + 1e-10)
    k = raw_k.rolling(window=smooth_k).mean()
    d = k.rolling(window=d_period).mean()
    return pd.DataFrame({"K": k, "D": d}, index=df.index)


# ─── OB / OS zone detection ──────────────────────────────────────────

OB_THRESHOLD = 79
OS_THRESHOLD = 21


def detect_zones(stoch: pd.DataFrame):
    """
    Walk through K values and mark OB/OS zones.
    Returns list of dicts: {type, start, end}
    """
    zones = []
    current_zone = None
    zone_start = None

    for i in range(len(stoch)):
        k = stoch["K"].iloc[i]
        if pd.isna(k):
            continue

        if current_zone is None:
            if k > OB_THRESHOLD:
                current_zone = "OB"
                zone_start = i
            elif k < OS_THRESHOLD:
                current_zone = "OS"
                zone_start = i
        elif current_zone == "OB":
            if k < OS_THRESHOLD:
                zones.append({"type": "OB", "start": zone_start, "end": i - 1})
                current_zone = "OS"
                zone_start = i
        elif current_zone == "OS":
            if k > OB_THRESHOLD:
                zones.append({"type": "OS", "start": zone_start, "end": i - 1})
                current_zone = "OB"
                zone_start = i

    if current_zone is not None:
        zones.append({"type": current_zone, "start": zone_start, "end": len(stoch) - 1})

    return zones


# ─── Swing High / Low ────────────────────────────────────────────────

def find_swing_in_zone(df: pd.DataFrame, zone: dict):
    """
    Find swing high (OB) or swing low (OS).
    Expand search to include bars just before the zone (up to 3 bars)
    because price extremes often occur before Stochastic confirms the zone.
    """
    start, end = zone["start"], zone["end"]
    # Expand search window: include up to 3 bars before zone start
    expanded_start = max(start - 3, 0)
    subset = df.iloc[expanded_start: end + 1]

    if zone["type"] == "OB":
        idx = subset["High"].idxmax()
        return {"type": "swing_high", "index": df.index.get_loc(idx), "price": df.loc[idx, "High"], "date": idx}
    else:
        idx = subset["Low"].idxmin()
        return {"type": "swing_low", "index": df.index.get_loc(idx), "price": df.loc[idx, "Low"], "date": idx}


# ─── White Line (BUY side only) ──────────────────────────────────────

def calc_white_line(df: pd.DataFrame, swing: dict):
    """
    Find White Line around swing low.
    Check bar before swing (bar-1, bar-2) AND bar after swing (bar+1, bar+2).
    WL = max(open, close) of the FIRST bar (nearest to swing) whose body_high > swing body_high.
    Priority: bar-1 first, then bar-2, then bar+1, then bar+2.
    """
    si = swing["index"]

    swing_bar = df.iloc[si]
    swing_body_high = max(swing_bar["Open"], swing_bar["Close"])

    # Check bars BEFORE swing first (bar-1, bar-2)
    for j in [si - 1, si - 2]:
        if j < 0:
            continue
        bar = df.iloc[j]
        body_high = max(bar["Open"], bar["Close"])
        if body_high > swing_body_high:
            return body_high

    # Then check bars AFTER swing (bar+1, bar+2)
    for j in [si + 1, si + 2]:
        if j >= len(df):
            continue
        bar = df.iloc[j]
        body_high = max(bar["Open"], bar["Close"])
        if body_high > swing_body_high:
            return body_high

    return swing_body_high


# ─── Fibonacci ────────────────────────────────────────────────────────

FIBO_LEVELS = [0.0, 0.382, 0.5, 0.618, 0.786, 1.0, 1.382, 1.618, 2.0, 2.618]


def calc_fibo_levels(swing_start_price: float, swing_end_price: float, direction: str):
    diff = abs(swing_start_price - swing_end_price)
    levels = {}
    for lvl in FIBO_LEVELS:
        if direction == "sell":
            levels[lvl] = swing_start_price - diff * lvl
        else:
            levels[lvl] = swing_start_price + diff * lvl
    return levels


def detect_structure(price: float, fibo_levels: dict, direction: str):
    lvl_0 = fibo_levels[0.0]
    lvl_1 = fibo_levels[1.0]
    low_bound = min(lvl_0, lvl_1)
    high_bound = max(lvl_0, lvl_1)

    if low_bound <= price <= high_bound:
        return "sideway"

    lvl_50 = fibo_levels[0.5]
    lvl_1382 = fibo_levels[1.382]
    trend_low = min(lvl_50, lvl_1382)
    trend_high = max(lvl_50, lvl_1382)

    if trend_low <= price <= trend_high:
        return "trend"

    return "extended"


def calc_fibo_position(price: float, level0_price: float, level1_price: float) -> str:
    """
    Calculate which Fibo level the current price is nearest to.
    level0_price = price at Fibo 0.0, level1_price = price at Fibo 1.0.
    Returns string like "0.618" or ">2.618".
    """
    diff = level1_price - level0_price
    if abs(diff) < 1e-10:
        return "-"
    ratio = (price - level0_price) / diff

    if ratio < -1.618:
        return "Lower than 2.618"
    if ratio < 0:
        return "<0"
    if ratio > 2.618:
        return ">2.618"

    # Find nearest fibo level
    nearest = min(FIBO_LEVELS, key=lambda lvl: abs(ratio - lvl))
    return str(nearest)


# ─── Bullish Divergence Detection ────────────────────────────────────

def detect_sto_divergence(df: pd.DataFrame, stoch: pd.DataFrame, zones: list) -> bool:
    """Stochastic bullish divergence: price lower low but Stoch K higher low."""
    os_zones = [z for z in zones if z["type"] == "OS"]
    if len(os_zones) >= 2:
        z1, z2 = os_zones[-2], os_zones[-1]
        price_low1 = df.iloc[max(z1["start"]-3, 0):z1["end"]+1]["Low"].min()
        price_low2 = df.iloc[max(z2["start"]-3, 0):z2["end"]+1]["Low"].min()
        sto_low1 = stoch["K"].iloc[z1["start"]:z1["end"]+1].min()
        sto_low2 = stoch["K"].iloc[z2["start"]:z2["end"]+1].min()
        if price_low2 < price_low1 and sto_low2 > sto_low1:
            return True
    return False


def detect_rsi_divergence(df: pd.DataFrame, rsi: pd.DataFrame, zones: list) -> bool:
    """RSI bullish divergence: price lower low but RSI higher low."""
    os_zones = [z for z in zones if z["type"] == "OS"]
    if len(os_zones) >= 2:
        z1, z2 = os_zones[-2], os_zones[-1]
        price_low1 = df.iloc[max(z1["start"]-3, 0):z1["end"]+1]["Low"].min()
        price_low2 = df.iloc[max(z2["start"]-3, 0):z2["end"]+1]["Low"].min()
        rsi_low1 = rsi["RSI"].iloc[max(z1["start"]-3, 0):z1["end"]+1].min()
        rsi_low2 = rsi["RSI"].iloc[max(z2["start"]-3, 0):z2["end"]+1].min()
        if pd.isna(rsi_low1) or pd.isna(rsi_low2):
            return False
        if price_low2 < price_low1 and rsi_low2 > rsi_low1:
            return True
    return False


# ─── Trend detection: compare OS (Low) and OB (High) ────────────────

def find_swings_by_type(df: pd.DataFrame, zones: list, zone_type: str) -> list:
    """Find all swings from zones of given type, ordered by time."""
    swings = []
    for z in zones:
        if z["type"] == zone_type:
            sw = find_swing_in_zone(df, z)
            swings.append(sw)
    return swings


# ─── Full scan for one stock ─────────────────────────────────────────

def scan_stock(df: pd.DataFrame) -> dict | None:
    if df is None or len(df) < 30:
        return None

    stoch = calc_stochastic(df)
    zones = detect_zones(stoch)

    if len(zones) < 2:
        return None

    last_bar = df.iloc[-1]
    last_close = float(last_bar["Close"])
    last_k = stoch["K"].iloc[-1]
    last_d = stoch["D"].iloc[-1]

    # Current zone info
    last_zone = zones[-1]
    in_ob = last_zone["type"] == "OB"
    in_os = last_zone["type"] == "OS"

    # ─── Trend detection: compare last 2 OS (Low) and last 2 OB (High) ───
    os_swings = find_swings_by_type(df, zones, "OS")
    ob_swings = find_swings_by_type(df, zones, "OB")

    if len(os_swings) < 1:
        return None

    latest_os_swing = os_swings[-1]

    # Determine trend: need at least 2 of each
    # OS checks Low: higher low = UT condition, lower low = DT condition
    # OB checks High: higher high = UT condition, lower high = DT condition
    os_higher = None  # True = higher low, False = lower low
    ob_higher = None  # True = higher high, False = lower high

    if len(os_swings) >= 2:
        os_prev = os_swings[-2]["price"]  # older
        os_last = os_swings[-1]["price"]  # latest
        os_higher = os_last > os_prev

    if len(ob_swings) >= 2:
        ob_prev = ob_swings[-2]["price"]  # older
        ob_last = ob_swings[-1]["price"]  # latest
        ob_higher = ob_last > ob_prev

    # DT: lower lows + lower highs
    # UT: higher lows + higher highs
    # SW: mixed or not enough data
    if os_higher is not None and ob_higher is not None:
        if bool(os_higher) == False and bool(ob_higher) == False:
            trend = "DT"
        elif bool(os_higher) == True and bool(ob_higher) == True:
            trend = "UT"
        else:
            trend = "SW"
    else:
        trend = "SW"

    # ─── Status logic ───
    status = "Downtrend" if trend == "DT" else "Sideway" if trend == "SW" else ""
    white_line = None
    sl_ref = None
    tp_ref = None
    bars_over_wl = 0

    is_ready_entry = False

    if trend == "UT":
        white_line = calc_white_line(df, latest_os_swing)

        # Walk bars after swing to find first close above WL
        swing_idx = latest_os_swing["index"]
        wl_start = min(swing_idx + 2, len(df))
        first_cross_idx = None  # index of the FIRST bar that closed above WL

        for i in range(wl_start, len(df)):
            bar_close = float(df.iloc[i]["Close"])
            if bar_close > white_line:
                if first_cross_idx is None:
                    first_cross_idx = i
                bars_over_wl += 1

        if bars_over_wl == 0:
            status = "UT -> Waiting Whiteline"
        elif first_cross_idx == len(df) - 1 and bars_over_wl == 1:
            # Tentative ready — will confirm after wave check
            status = "UT -> Ready to Entry"
            is_ready_entry = True  # may be overridden by wave check below
        else:
            status = f"UT -> Over Whiteline {bars_over_wl} bars"

        # SL / TP for uptrend (RR 0.5)
        sl_ref = latest_os_swing["price"] * 0.998
        sl_dist = abs(last_close - sl_ref)
        if sl_dist > 0:
            tp_ref = last_close + sl_dist * 0.5

    # ─── Fibonacci ───
    fibo_levels = None
    structure = None
    fibo_zone_valid = False

    # Find latest OB swing
    last_ob_swing = None
    for z in reversed(zones):
        if z["type"] == "OB":
            last_ob_swing = find_swing_in_zone(df, z)
            break

    # Determine fibo anchor swings:
    # Normal: OB1 (0.0) → OS1 (1.0)
    # If OS1 is after OB1 (no new OB yet): use OS2 (1.0) → OB1 (0.0)
    fibo_ob = last_ob_swing
    fibo_os = latest_os_swing
    fibo_start_date = None  # date where fibo lines start on chart

    if fibo_ob and fibo_os:
        if fibo_os["index"] > fibo_ob["index"]:
            # OS1 came after OB1 → no new OB yet, use OS2 + OB1
            if len(os_swings) >= 2:
                fibo_os = os_swings[-2]
                fibo_start_date = fibo_os["date"]
            else:
                fibo_ob = None  # not enough swings
        else:
            fibo_start_date = fibo_os["date"]

    if fibo_ob and fibo_os:
        # Fibo: Swing High (0.0) → Swing Low (1.0)
        fibo_levels = calc_fibo_levels(fibo_ob["price"], fibo_os["price"], "sell")
        structure = detect_structure(last_close, fibo_levels, "sell")

        if structure == "trend" and trend == "UT" and bars_over_wl > 0:
            ratio = abs(last_close - fibo_levels[0.0]) / (abs(fibo_levels[1.0] - fibo_levels[0.0]) + 1e-10)
            if 0.3 <= ratio <= 0.85:
                fibo_zone_valid = True

    # ─── Fibo Position: OB (0.0) → OS (1.0) ───
    fibo_pos = "-"
    if fibo_ob and fibo_os:
        fibo_pos = calc_fibo_position(last_close, fibo_ob["price"], fibo_os["price"])

    # ─── Divergence ───
    rsi = calc_rsi(df)
    sto_div = detect_sto_divergence(df, stoch, zones)
    rsi_div = detect_rsi_divergence(df, rsi, zones)
    div_parts = []
    if sto_div:
        div_parts.append("StoDiv")
    if rsi_div:
        div_parts.append("RsiDiv")
    div_text = " +" + "+".join(div_parts) if div_parts else ""

    # ─── Trading Plan + Suitability (WL-based only) ───
    plan = ""
    suitable = False

    if trend == "UT" and is_ready_entry:
        plan = f"BUY: UT + WL break{div_text}"
        suitable = True
    elif trend == "UT" and "Waiting" in status:
        plan = f"WAIT: UT, waiting WL break{div_text}"
        suitable = True
    elif trend == "UT" and bars_over_wl > 0:
        plan = f"RUNNING: UT + Over WL {bars_over_wl} bars{div_text}"
        suitable = True
    elif trend == "DT":
        plan = f"NO ENTRY: Downtrend{div_text}"
    elif trend == "SW":
        plan = f"WAIT: Sideway{div_text}"
    else:
        plan = f"WAIT: no clear setup{div_text}"

    return {
        "status": status,
        "trend": trend,
        "is_ready_entry": bool(is_ready_entry),
        "sto_div": bool(sto_div),
        "rsi_div": bool(rsi_div),
        "fibo_pos": fibo_pos,
        "fibo_start_date": fibo_start_date.strftime("%Y-%m-%d") if fibo_start_date and hasattr(fibo_start_date, "strftime") else str(fibo_start_date)[:10] if fibo_start_date else None,
        "plan": plan,
        "suitable": bool(suitable),
        "structure": structure,
        "fibo_zone_valid": bool(fibo_zone_valid),
        "white_line": round(float(white_line), 4) if white_line else None,
        "bars_over_wl": int(bars_over_wl),
        "swing_type": latest_os_swing["type"],
        "swing_price": round(float(latest_os_swing["price"]), 4),
        "swing_date": latest_os_swing["date"].strftime("%Y-%m-%d") if hasattr(latest_os_swing["date"], "strftime") else str(latest_os_swing["date"]),
        "stoch_k": round(float(last_k), 2) if not pd.isna(last_k) else None,
        "stoch_d": round(float(last_d), 2) if not pd.isna(last_d) else None,
        "in_ob": bool(in_ob),
        "in_os": bool(in_os),
        "close": round(float(last_close), 4),
        "sl_ref": round(float(sl_ref), 4) if sl_ref else None,
        "tp_ref": round(float(tp_ref), 4) if tp_ref else None,
        "rr_ratio": round(float(abs(tp_ref - last_close) / abs(last_close - sl_ref)), 2) if sl_ref and tp_ref and abs(last_close - sl_ref) > 0 else None,
        "fibo_levels": {str(k): round(float(v), 4) for k, v in fibo_levels.items()} if fibo_levels else None,
    }
