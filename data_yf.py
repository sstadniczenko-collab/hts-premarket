"""Warstwa danych chmurowa: yfinance zamiast lokalnego `tv` CLI (TradingView Desktop).

Działa w GitHub Actions (Yahoo nie jest tam blokowany). Zwraca DataFrame
open/high/low/close z DatetimeIndex w UTC, tylko ZAMKNIĘTE świece.

yfinance nie ma natywnego H4 — H4 składamy z 1h (resample).
"""
from __future__ import annotations

import warnings
from datetime import datetime, timezone

import pandas as pd
import yfinance as yf

warnings.filterwarnings("ignore")


def _normalize(df: pd.DataFrame) -> pd.DataFrame:
    if df is None or len(df) == 0:
        return pd.DataFrame()
    # yfinance potrafi zwrócić MultiIndex kolumn dla pojedynczego tickera
    if isinstance(df.columns, pd.MultiIndex):
        df = df.copy()
        df.columns = df.columns.get_level_values(0)
    df = df.rename(columns=str.lower)
    cols = [c for c in ["open", "high", "low", "close"] if c in df.columns]
    if len(cols) < 4:
        return pd.DataFrame()
    df = df[["open", "high", "low", "close"]].copy()
    if df.index.tz is None:
        df.index = df.index.tz_localize("UTC")
    else:
        df.index = df.index.tz_convert("UTC")
    df = df.dropna().sort_index()
    return df


def fetch_daily(yf_symbol: str, period: str = "2y") -> pd.DataFrame:
    """Świece D1. Odcina niezamkniętą świecę dnia bieżącego (UTC)."""
    raw = yf.download(
        yf_symbol, period=period, interval="1d", progress=False, auto_adjust=False
    )
    df = _normalize(raw)
    if df.empty:
        return df
    return _drop_unclosed_daily(df)


def fetch_h4(yf_symbol: str, period: str = "300d") -> pd.DataFrame:
    """Świece H4 złożone z 1h (yfinance nie ma 4h). Best-effort — może być pusto
    dla instrumentów bez danych intraday. Odcina niekompletny ostatni koszyk 4h."""
    raw = yf.download(
        yf_symbol, period=period, interval="1h", progress=False, auto_adjust=False
    )
    df = _normalize(raw)
    if df.empty:
        return df
    agg = pd.DataFrame(
        {
            "open": df["open"].resample("4h").first(),
            "high": df["high"].resample("4h").max(),
            "low": df["low"].resample("4h").min(),
            "close": df["close"].resample("4h").last(),
        }
    ).dropna()
    return _drop_unclosed_intraday(agg, hours=4)


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _drop_unclosed_daily(df: pd.DataFrame) -> pd.DataFrame:
    """Odetnij ostatnią świecę D1 jeśli jej data == dzisiaj (UTC). Skaner biega
    o 06:30 / 13:00 UTC, więc świeca dnia bieżącego na pewno nie jest zamknięta."""
    if df.empty:
        return df
    today = _now().date()
    if df.index[-1].date() >= today:
        return df.iloc[:-1]
    return df


def _drop_unclosed_intraday(df: pd.DataFrame, hours: int) -> pd.DataFrame:
    if df.empty:
        return df
    from datetime import timedelta

    last_start = df.index[-1].to_pydatetime()
    if _now() < last_start + timedelta(hours=hours):
        return df.iloc[:-1]
    return df
