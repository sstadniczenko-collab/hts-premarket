"""Czytnik lokalnego snapshotu OHLC z cTradera (bars.json).

Snapshot produkuje `fetch_ctrader.py` LOKALNIE (hit na 127.0.0.1:9877/bars) i
pushuje do repo. Chmurowy scan.py czyta go stąd zamiast yfinance — dzięki temu
poziomy = realny feed brokera. Brakujący symbol → None (scan spada na yfinance).

Format bars.json:
{
  "generated_utc": "2026-07-23 06:15:02",
  "source": "ctrader 9877 acct 1114770",
  "bars": { "<asset>": { "d1": [[unixSec,o,h,l,c],...], "h4": [...] }, ... }
}
"""
from __future__ import annotations

import json
import os
from datetime import datetime, timezone

import pandas as pd

_TF_KEY = {"1d": "d1", "4h": "h4"}
_TF_SECONDS = {"1d": 86400, "4h": 14400}


def load(path: str) -> dict | None:
    if path and os.path.exists(path):
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    return None


def frame(store: dict | None, asset: str, tf: str) -> pd.DataFrame | None:
    """DataFrame OHLC dla (asset, tf) z snapshotu, z odciętą niezamkniętą świecą.
    None gdy brak danych → caller robi fallback na yfinance."""
    if not store:
        return None
    tf_key = _TF_KEY.get(tf)
    rows = (store.get("bars", {}).get(asset, {}) or {}).get(tf_key)
    if not rows:
        return None

    dur = _TF_SECONDS[tf]
    now = datetime.now(timezone.utc).timestamp()
    data = list(rows)
    # odetnij niezamknięte: świeca zamknięta gdy open_ts + dur <= now
    while data and (data[-1][0] + dur) > now:
        data.pop()
    if not data:
        return None

    idx = pd.to_datetime([r[0] for r in data], unit="s", utc=True)
    df = pd.DataFrame(
        {
            "open": [float(r[1]) for r in data],
            "high": [float(r[2]) for r in data],
            "low": [float(r[3]) for r in data],
            "close": [float(r[4]) for r in data],
        },
        index=idx,
    )
    return df
