"""Kontekst dzienny dla HTS Premarket Scanner: pivot dzienny + gapy + gap-over-gap.

Wszystko liczone z ZAMKNIĘTYCH świec D1 (yfinance). Pivot rzutuje poziomy na
NAJBLIŻSZĄ sesję z ostatniej zamkniętej świecy; gapy skanują ostatnie N sesji i
oceniają wypełnienie na moment ostatniej świecy.
"""
from __future__ import annotations

import numpy as np
import pandas as pd


def daily_pivot(daily_df: pd.DataFrame) -> dict | None:
    """Klasyczny floor pivot z ostatniej zamkniętej świecy D1 → poziomy na następną
    sesję + gdzie względem nich siedzi cena (ostatnie zamknięcie)."""
    if daily_df is None or len(daily_df) < 2:
        return None
    h = float(daily_df["high"].iloc[-1])
    l = float(daily_df["low"].iloc[-1])
    c = float(daily_df["close"].iloc[-1])
    rng = h - l
    P = (h + l + c) / 3.0
    R1 = 2 * P - l
    S1 = 2 * P - h
    R2 = P + rng
    S2 = P - rng
    R3 = h + 2 * (P - l)
    S3 = l - 2 * (h - P)

    price = c  # premarket: brak live tick, referencją jest ostatnie zamknięcie
    ladder = [("S3", S3), ("S2", S2), ("S1", S1), ("P", P), ("R1", R1), ("R2", R2), ("R3", R3)]

    # strefa: między którymi poziomami jest cena
    above = [name for name, v in ladder if v <= price]
    below_lv = min(((name, v) for name, v in ladder if v > price), key=lambda x: x[1], default=None)
    above_lv = max(((name, v) for name, v in ladder if v <= price), key=lambda x: x[1], default=None)
    zone = f"{above_lv[0]}–{below_lv[0]}" if (above_lv and below_lv) else (
        f">{ladder[-1][0]}" if not below_lv else f"<{ladder[0][0]}")

    bias = "byczy" if price >= P else "niedźwiedzi"  # zamknięcie nad/pod pivotem
    nearest_res = below_lv  # najbliższy opór nad ceną
    nearest_sup = above_lv  # najbliższe wsparcie pod ceną
    return {
        "P": P, "R1": R1, "R2": R2, "R3": R3, "S1": S1, "S2": S2, "S3": S3,
        "price": price,
        "zone": zone,
        "bias": bias,
        "res": {"name": nearest_res[0], "val": nearest_res[1],
                "dist_pct": (nearest_res[1] - price) / price * 100.0} if nearest_res else None,
        "sup": {"name": nearest_sup[0], "val": nearest_sup[1],
                "dist_pct": (price - nearest_sup[1]) / price * 100.0} if nearest_sup else None,
    }


def gap_analysis(daily_df: pd.DataFrame, min_pct: float = 0.15, lookback: int = 40) -> dict | None:
    """Luka otwarcia ostatniej sesji + wykrycie gap-over-gap.

    gap-over-gap (wg definicji użytkownika): ostatnia luka przeskoczyła STARĄ,
    wciąż NIEWYPEŁNIONĄ lukę w tym samym kierunku → zostaje podwójna niewypełniona
    strefa jako magnes (pod spodem dla luk w górę, nad dla luk w dół).
    """
    if daily_df is None or len(daily_df) < 3:
        return None
    o = daily_df["open"].to_numpy(dtype=float)
    c = daily_df["close"].to_numpy(dtype=float)
    h = daily_df["high"].to_numpy(dtype=float)
    l = daily_df["low"].to_numpy(dtype=float)
    n = len(daily_df)
    start = max(1, n - lookback)

    gaps = []  # {i, dir, top, bottom, pct, filled}
    for i in range(start, n):
        prev_c = c[i - 1]
        if prev_c <= 0:
            continue
        if o[i] > prev_c:
            d, top, bot = "up", o[i], prev_c
        elif o[i] < prev_c:
            d, top, bot = "down", prev_c, o[i]
        else:
            continue
        pct = abs(o[i] - prev_c) / prev_c * 100.0
        if pct < min_pct:
            continue
        # wypełniona? cena wróciła do poprzedniego zamknięcia w którejś z późniejszych świec
        if d == "up":
            filled = bool(l[i:n].min() <= bot)
        else:
            filled = bool(h[i:n].max() >= top)
        gaps.append({"i": i, "dir": d, "top": float(top), "bottom": float(bot),
                     "pct": pct, "filled": filled})

    if not gaps:
        return {"last": None, "unfilled_count": 0, "gap_over_gap": False, "magnet": None}

    unfilled = [g for g in gaps if not g["filled"]]
    last = gaps[-1] if gaps[-1]["i"] == n - 1 else None  # luka na ostatniej świecy

    gog = False
    magnet = None
    if last is not None and not last["filled"]:
        # GoG = PODWÓJNA niewypełniona strefa: ostatnia luka otwarta + starsza
        # niewypełniona luka w tym samym kierunku, leżąca PO DRUGIEJ stronie
        # (niżej dla up, wyżej dla down) niż ostatnia luka
        if last["dir"] == "up":
            earlier = [g for g in unfilled if g["i"] < n - 1 and g["dir"] == "up" and g["top"] <= last["bottom"]]
            if earlier:
                gog = True
                m = max(earlier, key=lambda g: g["top"])  # najbliżej pod ostatnią luką
                magnet = {"top": m["top"], "bottom": m["bottom"], "pct": m["pct"]}
        else:
            earlier = [g for g in unfilled if g["i"] < n - 1 and g["dir"] == "down" and g["bottom"] >= last["top"]]
            if earlier:
                gog = True
                m = min(earlier, key=lambda g: g["bottom"])
                magnet = {"top": m["top"], "bottom": m["bottom"], "pct": m["pct"]}

    last_out = None
    if last is not None:
        last_out = {"dir": last["dir"], "pct": round(last["pct"], 2),
                    "filled": last["filled"], "top": last["top"], "bottom": last["bottom"]}
    return {
        "last": last_out,
        "unfilled_count": len(unfilled),
        "gap_over_gap": gog,
        "magnet": magnet,
    }
