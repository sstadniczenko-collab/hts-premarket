"""Detektor dnia kapitulacji — playbook z analizy konta Darwinex 4000089496.

EVENT = Low ostatniej ZAMKNIĘTEJ sesji <= poprzednie Close * (1 + drop_pct/100)
(spadek intraday >= 2%). Zagranie: long na close dnia eventowego, SL pod dołkiem
- bufor, trzymanie max 3 sesje. Spec + backtest: STRATEGIA_KAPITULACJA.md
(Y:\\15_AI\\02_TRADING\\01_MATERIALY\\13_DARWINEX\\ANALIZA_2026-07-08).

Walidowane WYŁĄCZNIE na NQ (2024–2026). Pozostałe indeksy liczone tą samą
regułą czysto informacyjnie.

Warstwa gapów: rejestr niedomkniętych luk wzrostowych (strefa [prev close,
open] pod ceną) jako mapa terenu dla flushu. UWAGA z backtestu NQ 2y: eventy,
w których flush domykał stary gap (n=6), były GORSZE (avg -1 041 USD) niż bez
(n=60, avg +1 004) — flaga ostrożności, nie filtr wejścia.

Skaner biega PREMARKET, więc ocenia wczorajszą (ostatnią zamkniętą) sesję:
sekcja odpowiada na pytanie "czy wczoraj był dzień kapitulacji i gdzie są
poziomy", nie strzela w trakcie sesji.
"""
from __future__ import annotations

import pandas as pd

DEFAULTS = {
    "drop_pct": -2.0,      # próg kapitulacji (Low vs prev Close, %)
    "near_pct": -1.5,      # "zbliża się" — podświetlenie bez eventu
    "sl_buf_pct": 0.15,    # bufor SL pod dołkiem dnia eventowego
    "hold_days": 3,        # max sesji trzymania
    "decluster_d": 2,      # pomiń event <=2 dni po poprzednim
    "gap_min_pct": 0.30,   # minimalna luka wzrostowa do rejestru
    "gap_lookback": 250,   # ile sesji wstecz skanować gapy
}


def _px(x: float) -> float:
    ax = abs(x)
    if ax >= 1000:
        return round(x, 1)
    if ax >= 100:
        return round(x, 2)
    return round(x, 3)


def unfilled_up_gaps(df: pd.DataFrame, min_pct: float, lookback: int) -> list[dict]:
    """Niedomknięte luki wzrostowe pod ostatnim close (magnesy dla flushu),
    od najbliższej. Luka domknięta, gdy Low którejś sesji zszedł do jej dna."""
    o = df["open"].to_numpy(dtype=float)
    c = df["close"].to_numpy(dtype=float)
    l = df["low"].to_numpy(dtype=float)
    n = len(df)
    last_close = c[-1]
    out = []
    for i in range(max(1, n - lookback), n):
        prev_c = c[i - 1]
        if prev_c <= 0 or o[i] <= prev_c:
            continue
        pct = (o[i] - prev_c) / prev_c * 100.0
        if pct < min_pct:
            continue
        bot, top = prev_c, o[i]
        if l[i:n].min() <= bot:      # domknięta
            continue
        if top >= last_close:        # nie jest "pod ceną"
            continue
        out.append({
            "date": df.index[i].strftime("%Y-%m-%d"),
            "top": _px(top), "bottom": _px(bot), "pct": round(pct, 2),
            "dist_pct": round((top - last_close) / last_close * 100.0, 1),
        })
    out.sort(key=lambda g: -g["top"])
    return out


def analyze(df: pd.DataFrame, cfg: dict) -> dict | None:
    """Stan detektora dla jednego instrumentu na ZAMKNIĘTYCH świecach D1."""
    if df is None or len(df) < 30:
        return None
    c = df["close"]
    l = df["low"]
    prev_c = float(c.iloc[-2])
    low = float(l.iloc[-1])
    close = float(c.iloc[-1])
    drop = (low - prev_c) / prev_c * 100.0
    event = drop <= cfg["drop_pct"]

    out = {
        "session": df.index[-1].strftime("%Y-%m-%d"),
        "prev_close": _px(prev_c),
        "low": _px(low),
        "close": _px(close),
        "drop_pct": round(drop, 2),
        "event": event,
        "near": (not event) and drop <= cfg["near_pct"],
        "gaps_below": unfilled_up_gaps(df, cfg["gap_min_pct"], cfg["gap_lookback"])[:3],
    }

    if not event:
        return out

    # de-klastrowanie: poprzedni event <= decluster_d dni kalendarzowych temu
    dd = (l - c.shift(1)) / c.shift(1) * 100.0
    earlier = dd.iloc[:-1]
    prior = earlier[earlier <= cfg["drop_pct"]]
    if len(prior):
        days_since = (df.index[-1] - prior.index[-1]).days
        out["clustered"] = days_since <= cfg["decluster_d"]
    else:
        out["clustered"] = False

    sl = low * (1 - cfg["sl_buf_pct"] / 100.0)
    risk = close - sl
    out.update({
        "entry": _px(close),
        "sl": _px(sl),
        "risk": _px(risk),
        "risk_pct": round(risk / close * 100.0, 2),
        "hold_days": cfg["hold_days"],
        # flush wszedł w strefę niedomkniętego gapu? (Low <= top którejś luki
        # otwartej na start sesji — tu aproksymacja: luki sprzed sesji eventowej)
        "gap_fill": _event_gap_fill(df, cfg),
    })
    return out


def _event_gap_fill(df: pd.DataFrame, cfg: dict) -> bool:
    """Czy dzisiejszy flush nakrył lukę niedomkniętą przed startem sesji."""
    if len(df) < 3:
        return False
    hist = df.iloc[:-1]
    low = float(df["low"].iloc[-1])
    o = hist["open"].to_numpy(dtype=float)
    c = hist["close"].to_numpy(dtype=float)
    l = hist["low"].to_numpy(dtype=float)
    n = len(hist)
    for i in range(max(1, n - cfg["gap_lookback"]), n):
        prev_c = c[i - 1]
        if prev_c <= 0 or o[i] <= prev_c:
            continue
        if (o[i] - prev_c) / prev_c * 100.0 < cfg["gap_min_pct"]:
            continue
        if l[i:n].min() <= prev_c:   # domknięta już wcześniej
            continue
        if low <= o[i]:              # flush wszedł w strefę
            return True
    return False


def compute(daily_frames: dict[str, pd.DataFrame], instruments: list[dict],
            cfg: dict | None = None, headline_asset: str = "NQ",
            skip_assets: tuple = ("VX",)) -> dict:
    """Sekcja detektora dla instrumentów z grupy Indeksy.

    daily_frames: {asset: df D1 (zamknięte świece)} zebrane w trakcie skanu.
    """
    c = dict(DEFAULTS)
    if cfg:
        c.update(cfg)
    rows = []
    for inst in instruments:
        a = inst["asset"]
        if inst.get("group") != "Indeksy" or a in skip_assets:
            continue
        df = daily_frames.get(a)
        try:
            st = analyze(df, c)
        except Exception:
            st = None
        if st is None:
            continue
        rows.append({"asset": a, "name": inst["name"], "ftmo": inst.get("ftmo"), **st})
    # eventy najpierw, potem najgłębsze spadki
    rows.sort(key=lambda r: (not r["event"], r["drop_pct"]))
    headline = next((r for r in rows if r["asset"] == headline_asset), None)
    return {
        "params": {k: c[k] for k in ("drop_pct", "sl_buf_pct", "hold_days", "decluster_d", "gap_min_pct")},
        "headline": headline,
        "rows": rows,
        "any_event": any(r["event"] for r in rows),
    }
