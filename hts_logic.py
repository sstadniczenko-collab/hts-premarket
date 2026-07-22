"""
HTS Swing - Pro Filter: replikacja logiki Pine Script w Pythonie.

Źródło: HTS_Swing_Pro_Filter 3.0 (Pine v5) — skopiowane 1:1 z hts_scanner/hts_logic.py.
- Fast MA (33) i Slow MA (144) -> wstęgi (high/low/hl2)
- Cross fast/slow definiuje trend_direction
- Setup AAA: pierwszy retest wstęgi po crossie + oddechu
- Setup AA+: kolejne dokładki (piramidowanie)
- Filtr ADX: <20 blokuje, 20-25 = z gwiazdką (UMIARK),
             25-40 = czysty (SILNY), >=40 = z wykrzyknikiem (WYCZERPANY)
- ATR jako informacja (zmiana % vs lookback)

Jedyna różnica vs oryginał: _make_setup zapisuje dodatkowo `bar_index`
(pozycja świecy w oknie) — potrzebne do policzenia `bars_ago` w premarket skanerze.
"""
from __future__ import annotations

import numpy as np
import pandas as pd


# ---------------------------------------------------------------------------
# Moving averages
# ---------------------------------------------------------------------------
def _sma(s: pd.Series, n: int) -> pd.Series:
    return s.rolling(n, min_periods=n).mean()


def _ema(s: pd.Series, n: int) -> pd.Series:
    return s.ewm(span=n, adjust=False).mean()


def _rma(s: pd.Series, n: int) -> pd.Series:
    # Wilder smoothing (Pine ta.rma)
    return s.ewm(alpha=1.0 / n, adjust=False).mean()


def _wma(s: pd.Series, n: int) -> pd.Series:
    weights = np.arange(1, n + 1, dtype=float)
    return s.rolling(n, min_periods=n).apply(
        lambda x: np.dot(x, weights) / weights.sum(), raw=True
    )


_MA = {"SMA": _sma, "EMA": _ema, "RMA": _rma, "WMA": _wma}


def _bands(df: pd.DataFrame, length: int, method: str, smoothing: int):
    f = _MA[method]
    hl2 = (df["high"] + df["low"]) / 2.0
    ma_h = f(df["high"], length)
    ma_l = f(df["low"], length)
    ma_hl2 = f(hl2, length)
    ma_hl2_avg = ma_hl2.rolling(smoothing, min_periods=smoothing).mean()
    return ma_h, ma_l, ma_hl2, ma_hl2_avg


# ---------------------------------------------------------------------------
# ADX (Wilder) i ATR -- Pine ta.dmi(14,14), ta.atr(14)
# ---------------------------------------------------------------------------
def _true_range(df: pd.DataFrame) -> pd.Series:
    h, l, c = df["high"], df["low"], df["close"]
    pc = c.shift(1)
    tr = pd.concat([h - l, (h - pc).abs(), (l - pc).abs()], axis=1).max(axis=1)
    return tr


def _adx(df: pd.DataFrame, length: int = 14) -> pd.Series:
    h, l = df["high"], df["low"]
    up = h.diff()
    dn = -l.diff()
    plus_dm = np.where((up > dn) & (up > 0), up, 0.0)
    minus_dm = np.where((dn > up) & (dn > 0), dn, 0.0)
    plus_dm = pd.Series(plus_dm, index=df.index)
    minus_dm = pd.Series(minus_dm, index=df.index)

    tr = _true_range(df)
    atr = tr.ewm(alpha=1.0 / length, adjust=False).mean()

    plus_di = 100.0 * plus_dm.ewm(alpha=1.0 / length, adjust=False).mean() / atr
    minus_di = 100.0 * minus_dm.ewm(alpha=1.0 / length, adjust=False).mean() / atr
    dx = 100.0 * (plus_di - minus_di).abs() / (plus_di + minus_di).replace(0, np.nan)
    return dx.ewm(alpha=1.0 / length, adjust=False).mean()


def _atr(df: pd.DataFrame, length: int = 14) -> pd.Series:
    return _true_range(df).ewm(alpha=1.0 / length, adjust=False).mean()


# ---------------------------------------------------------------------------
# Klasyfikacja ADX (analog Pine: weak/moderate/strong/exhausted)
# ---------------------------------------------------------------------------
def adx_class(adx_val: float, cfg: dict) -> str:
    if adx_val < cfg["adx_threshold_weak"]:
        return "WEAK"
    if adx_val < cfg["adx_threshold_moderate"]:
        return "MODERATE"  # *
    if adx_val < cfg["adx_threshold_strong"]:
        return "STRONG"  # czysty
    return "EXHAUSTED"  # !


def adx_suffix(cls: str) -> str:
    return {"MODERATE": "*", "EXHAUSTED": "!"}.get(cls, "")


def adx_label_pl(cls: str) -> str:
    return {
        "WEAK": "SŁABY",
        "MODERATE": "UMIARKOWANY",
        "STRONG": "SILNY",
        "EXHAUSTED": "WYCZERPANY",
    }.get(cls, cls)


# ---------------------------------------------------------------------------
# Główny detektor setupów - przejście barami z stanem (jak Pine)
# ---------------------------------------------------------------------------
def _run(df: pd.DataFrame, cfg: dict) -> dict | None:
    """Jednokrotne przejście maszyny stanu HTS (jedno źródło prawdy dla setupów
    ORAZ końcowego stanu). Zwraca listę setupów + stan po ostatniej świecy
    (trend/ready/retest_count/last_price) + tablice wstęg — z tego `scan()` bierze
    setupy, a `entry_plan()` buduje plan wejścia na 'teraz'."""
    if len(df) < cfg["slow_ma"] + cfg["smoothing"] + 5:
        return None

    fast_h, fast_l, fast_hl2, fast_hl2_avg = _bands(
        df, cfg["fast_ma"], cfg["ma_method"], cfg["smoothing"]
    )
    slow_h, slow_l, slow_hl2, slow_hl2_avg = _bands(
        df, cfg["slow_ma"], cfg["ma_method"], cfg["smoothing"]
    )
    adx = _adx(df, 14)
    atr = _atr(df, cfg["atr_length"])
    atr_lb = atr.shift(cfg["atr_lookback"])

    # State (jak `var` w Pine)
    retest_count = 0
    ready = False
    last_price = None
    trend = 0  # 1=long, -1=short, 0=brak

    setups: list[dict] = []
    warmup_done = False
    last_valid_i = -1  # ostatnia świeca z policzonymi wstęgami

    close = df["close"].to_numpy()
    high = df["high"].to_numpy()
    low = df["low"].to_numpy()
    fh = fast_h.to_numpy()
    fl = fast_l.to_numpy()
    fhl2 = fast_hl2.to_numpy()
    sh = slow_h.to_numpy()
    sl = slow_l.to_numpy()
    shl2 = slow_hl2.to_numpy()
    adx_a = adx.to_numpy()
    atr_a = atr.to_numpy()
    atr_lb_a = atr_lb.to_numpy()
    times = df.index

    for i in range(1, len(df)):
        if (
            np.isnan(fh[i])
            or np.isnan(sh[i])
            or np.isnan(adx_a[i])
            or np.isnan(fhl2[i])
            or np.isnan(shl2[i])
        ):
            continue
        last_valid_i = i

        c = close[i]
        dist_price = c * cfg["dist_pct"] / 100.0
        min_band_gap = c * cfg["min_band_gap_pct"] / 100.0
        pyramid_step = c * cfg["min_pyramid_step_pct"] / 100.0

        if not warmup_done:
            if fl[i] > sh[i]:
                trend = 1
            elif fh[i] < sl[i]:
                trend = -1
            warmup_done = True

        if trend == 1 and c > fh[i] + dist_price:
            ready = True
        elif trend == -1 and c < fl[i] - dist_price:
            ready = True

        cross_up = (fl[i - 1] <= sh[i - 1]) and (fl[i] > sh[i])
        cross_down = (fh[i - 1] >= sl[i - 1]) and (fh[i] < sl[i])

        if cross_up:
            retest_count = 0
            ready = False
            last_price = None
            trend = 1
        if cross_down:
            retest_count = 0
            ready = False
            last_price = None
            trend = -1

        price_in_band = (low[i] <= fh[i]) and (high[i] >= fl[i])
        if trend == 1:
            gap = fl[i] - sh[i]
        elif trend == -1:
            gap = sl[i] - fh[i]
        else:
            gap = 0.0
        band_wide = gap >= min_band_gap
        adx_not_weak = adx_a[i] >= cfg["adx_threshold_weak"]

        if (
            price_in_band
            and ready
            and band_wide
            and trend != 0
            and adx_not_weak
        ):
            correct_side = (trend == 1 and fhl2[i] > shl2[i]) or (
                trend == -1 and fhl2[i] < shl2[i]
            )
            if correct_side:
                if retest_count == 0:
                    retest_count = 1
                    ready = False
                    last_price = c
                    setups.append(_make_setup("AAA", trend, i, c, times, fh, fl, sh, sl, adx_a, atr_a, atr_lb_a, cfg))
                else:
                    if last_price is None:
                        pyramid_ok = True
                    elif trend == 1:
                        pyramid_ok = (c - last_price) >= pyramid_step
                    else:
                        pyramid_ok = (last_price - c) >= pyramid_step
                    if pyramid_ok:
                        retest_count += 1
                        ready = False
                        last_price = c
                        setups.append(_make_setup("AA+", trend, i, c, times, fh, fl, sh, sl, adx_a, atr_a, atr_lb_a, cfg))

    return {
        "setups": setups,
        "trend": trend,
        "ready": ready,
        "retest_count": retest_count,
        "last_price": last_price,
        "last_valid_i": last_valid_i,
        "arr": {
            "close": close, "high": high, "low": low,
            "fh": fh, "fl": fl, "sh": sh, "sl": sl,
            "adx": adx_a, "atr": atr_a,
        },
        "times": times,
    }


def scan(df: pd.DataFrame, cfg: dict) -> list[dict]:
    """
    df: DataFrame zindeksowany czasem, kolumny open/high/low/close (lowercase).
        WAŻNE: tylko ZAMKNIĘTE świece. Ostatnia formująca się świeca powinna
        zostać odcięta zanim wejdzie tutaj.
    cfg: parametry strategii (sekcja 'strategy' z config.json).

    Zwraca listę dictów z setupami (AAA/AA+) w kolejności chronologicznej.
    """
    res = _run(df, cfg)
    return res["setups"] if res else []


def _make_setup(kind, trend, i, c, times, fh, fl, sh, sl, adx_a, atr_a, atr_lb_a, cfg):
    cls = adx_class(adx_a[i], cfg)
    direction = "long" if trend == 1 else "short"
    atr_change = 0.0
    if not np.isnan(atr_lb_a[i]) and atr_lb_a[i] != 0:
        atr_change = (atr_a[i] / atr_lb_a[i] - 1.0) * 100.0
    return {
        "bar_index": int(i),
        "bar_time": times[i].to_pydatetime() if hasattr(times[i], "to_pydatetime") else times[i],
        "type": kind,
        "direction": direction,
        "adx_class": cls,
        "adx_label": adx_label_pl(cls),
        "suffix": adx_suffix(cls),
        "price": float(c),
        "adx": float(adx_a[i]),
        "atr": float(atr_a[i]),
        "atr_pct_price": float(atr_a[i] / c * 100.0),
        "atr_change_pct": float(atr_change),
        "fast_h": float(fh[i]),
        "fast_l": float(fl[i]),
        "slow_h": float(sh[i]),
        "slow_l": float(sl[i]),
    }


def trend_state(df: pd.DataFrame, cfg: dict) -> dict | None:
    """Bieżący stan trendu wstęg na ostatniej ZAMKNIĘTEJ świecy.
    long = szybka wstęga nad wolną (fl>sh), short = pod (fh<sl), inaczej none."""
    if len(df) < cfg["slow_ma"] + cfg["smoothing"] + 1:
        return None
    fh, fl, _fhl2, _fa = _bands(df, cfg["fast_ma"], cfg["ma_method"], cfg["smoothing"])
    sh, sl, _shl2, _sa = _bands(df, cfg["slow_ma"], cfg["ma_method"], cfg["smoothing"])
    adx = _adx(df, 14)
    atr = _atr(df, cfg["atr_length"])
    fl_v, sh_v, fh_v, sl_v = fl.iloc[-1], sh.iloc[-1], fh.iloc[-1], sl.iloc[-1]
    if np.isnan(fl_v) or np.isnan(sh_v) or np.isnan(fh_v) or np.isnan(sl_v):
        return None
    if fl_v > sh_v:
        t = "long"
    elif fh_v < sl_v:
        t = "short"
    else:
        t = "none"
    close = float(df["close"].iloc[-1])
    adx_v = float(adx.iloc[-1]) if not np.isnan(adx.iloc[-1]) else None
    atr_v = float(atr.iloc[-1]) if not np.isnan(atr.iloc[-1]) else None
    return {
        "trend": t,
        "price": close,
        "adx": adx_v,
        "adx_label": adx_label_pl(adx_class(adx_v, cfg)) if adx_v is not None else None,
        "atr_pct": (atr_v / close * 100.0) if atr_v else None,
        "last_bar_index": len(df) - 1,
        "last_bar_time": df.index[-1].to_pydatetime(),
    }


def entry_plan(df: pd.DataFrame, cfg: dict) -> dict | None:
    """Plan wejścia na 'teraz' — na podstawie KOŃCOWEGO stanu maszyny HTS.

    Odpowiada na: jakich poziomów szukać (linia retestu = krawędź szybkiej
    wstęgi), z jakiego setupu (AAA gdy retest_count==0, inaczej AA+) i czy
    setup jest uzbrojony (ready) czy dopiero czeka na 'oddech' nad/pod wstęgą.

    Zwraca None, gdy brak trendu / za mało danych / setup strukturalnie zablokowany
    tak, że nie ma czego pokazać.
    """
    res = _run(df, cfg)
    if res is None or res["trend"] == 0:
        return None
    i = res["last_valid_i"]
    if i < 0:
        return None

    a = res["arr"]
    c = float(a["close"][i])
    fh, fl = float(a["fh"][i]), float(a["fl"][i])
    sh, sl = float(a["sh"][i]), float(a["sl"][i])
    adx_v = float(a["adx"][i]) if not np.isnan(a["adx"][i]) else None
    atr_v = float(a["atr"][i]) if not np.isnan(a["atr"][i]) else None

    trend = res["trend"]
    long = trend == 1
    dist_price = c * cfg["dist_pct"] / 100.0

    # linia retestu = krawędź szybkiej wstęgi od strony, z której wraca cena
    if long:
        entry_line = fh          # górna krawędź — pierwszy dotyk przy cofnięciu z góry
        entry_far = fl           # dolna krawędź strefy
        breath_line = fh + dist_price   # 'oddech' — powyżej tego cena uzbraja retest
        invalidation = sh        # wolna wstęga (SMA slow) — poniżej = zagrożenie flipa
        gap = fl - sh
        dist_to_entry = c - entry_line       # >0 = cena wyżej, musi cofnąć w dół
    else:
        entry_line = fl
        entry_far = fh
        breath_line = fl - dist_price
        invalidation = sl
        gap = sl - fh
        dist_to_entry = entry_line - c       # >0 = cena niżej, musi cofnąć w górę

    min_band_gap = c * cfg["min_band_gap_pct"] / 100.0
    band_wide = gap >= min_band_gap
    adx_ok = adx_v is not None and adx_v >= cfg["adx_threshold_weak"]
    next_type = "AAA" if res["retest_count"] == 0 else "AA+"

    # w strefie? (cena już dotyka szybkiej wstęgi) / przegłębiona? (przebiła całą wstęgę)
    band_lo, band_hi = min(entry_line, entry_far), max(entry_line, entry_far)
    in_zone = band_lo <= c <= band_hi
    deep = (c < band_lo) if long else (c > band_hi)  # cofka przeszła przez całą wstęgę

    # status uzbrojenia
    if not band_wide:
        status = "blocked_gap"      # wstęgi za wąskie
    elif not adx_ok:
        status = "blocked_adx"      # trend za słaby (ADX < weak)
    elif in_zone:
        status = "in_zone"          # cena w strefie retestu TERAZ
    elif deep:
        status = "deep"             # przegłębiony — cena przebiła wstęgę na wylot
    elif res["ready"]:
        status = "armed"            # uzbrojony — czekaj na powrót do linii wejścia
    else:
        status = "needs_breath"     # czekaj aż cena wybije oddech, potem retest

    cls = adx_class(adx_v, cfg) if adx_v is not None else None
    return {
        "trend": "long" if long else "short",
        "next_setup": next_type,
        "suffix": adx_suffix(cls) if cls else "",
        "status": status,
        "ready": bool(res["ready"]),
        "retest_count": int(res["retest_count"]),
        "price": c,
        "entry_line": entry_line,
        "entry_far": entry_far,
        "breath_line": breath_line,
        "invalidation": invalidation,
        "band_gap_pct": gap / c * 100.0,
        "band_wide": band_wide,
        "adx": adx_v,
        "adx_label": adx_label_pl(cls) if cls else None,
        "atr": atr_v,
        "atr_pct": (atr_v / c * 100.0) if atr_v else None,
        # dystans do linii wejścia (dodatni = cena musi się cofnąć do wstęgi)
        "dist_to_entry": dist_to_entry,
        "dist_to_entry_pct": dist_to_entry / c * 100.0,
        "dist_to_entry_atr": (dist_to_entry / atr_v) if atr_v else None,
    }
