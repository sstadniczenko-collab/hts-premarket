#!/usr/bin/env python3
"""Lokalny fetcher OHLC z cTradera → bars.json → push do repo (→ chmura renderuje).

Uruchamiany LOKALNIE na maszynie z cTraderem (plugin na 127.0.0.1:9877, konto
1114770). Pobiera D1+H4 dla całego koszyka, zapisuje bars.json i (domyślnie)
commit+push + odpala workflow, żeby chmurowy dashboard od razu przeliczył się na
świeżych, realnych poziomach brokera.

Harmonogram: Windows Task Scheduler 2× dziennie premarket (np. 08:20 i 14:50
czasu lokalnego). Gdy maszyna nie działa — chmura użyje ostatniego bars.json
(dashboard pokaże znacznik świeżości).

Użycie:
    python fetch_ctrader.py                 # fetch + push + dispatch
    python fetch_ctrader.py --no-push       # tylko zapis bars.json (test)
    python fetch_ctrader.py --no-dispatch   # push bez odpalania Action
    python fetch_ctrader.py --base http://127.0.0.1:9877
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import urllib.parse
import urllib.request
from datetime import datetime, timezone

HERE = os.path.dirname(os.path.abspath(__file__))

# Windows: konsola bywa cp1250 — nie wywalaj się na znakach spoza niej
for _s in (sys.stdout, sys.stderr):
    try:
        _s.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

# ile historii ciągnąć (SMA144+smoothing20 potrzebuje ~170 świec + zapas)
FROM = {"d1": "2024-01-01", "h4": "2025-09-01"}
TF_MAP = {"1d": "d1", "4h": "h4"}


def _get_bars(base: str, symbol: str, tf: str, timeout: int = 90) -> list | None:
    qs = urllib.parse.urlencode({"symbol": symbol, "tf": tf, "from": FROM[tf], "to": "2030-01-01"})
    url = f"{base}/bars?{qs}"
    with urllib.request.urlopen(url, timeout=timeout) as r:
        d = json.loads(r.read().decode())
    if "error" in d:
        raise RuntimeError(d["error"])
    return d.get("bars") or []


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--base", default="http://127.0.0.1:9877", help="adres pluginu cTrader")
    ap.add_argument("--out", default=os.path.join(HERE, "bars.json"))
    ap.add_argument("--no-push", action="store_true", help="nie commituj/pushuj")
    ap.add_argument("--no-dispatch", action="store_true", help="nie odpalaj workflow po pushu")
    args = ap.parse_args()

    with open(os.path.join(HERE, "universe.json"), encoding="utf-8") as f:
        uni = json.load(f)
    tfs = uni.get("timeframes", ["1d", "4h"])

    out_bars: dict = {}
    ok = miss = fail = 0
    for inst in uni["instruments"]:
        asset = inst["asset"]
        sym = inst.get("ctrader")
        if not sym:
            miss += 1
            print(f"- {asset:7} brak symbolu cTrader -> fallback yfinance w chmurze")
            continue
        per_tf = {}
        for tf in tfs:
            tf_c = TF_MAP.get(tf, tf)
            try:
                bars = _get_bars(args.base, sym, tf_c)
                per_tf[tf_c] = bars
                print(f"- {asset:7} {sym:10} {tf_c}: {len(bars)} świec")
            except Exception as e:
                fail += 1
                print(f"! {asset:7} {sym:10} {tf_c}: {e}", file=sys.stderr)
        if per_tf:
            out_bars[asset] = per_tf
            ok += 1

    payload = {
        "generated_utc": datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S"),
        "source": f"ctrader {args.base} acct 1114770",
        "bars": out_bars,
    }
    with open(args.out, "w", encoding="utf-8") as f:
        json.dump(payload, f, separators=(",", ":"))
    print(f"\nZapisano {args.out}: {ok} instr. z cTradera, {miss} bez symbolu, {fail} błędów")

    if args.no_push:
        return 0

    # commit + push tylko bars.json
    try:
        subprocess.run(["git", "-C", HERE, "add", "bars.json"], check=True)
        msg = f"data: snapshot OHLC cTrader {payload['generated_utc']} UTC"
        r = subprocess.run(["git", "-C", HERE, "commit", "-m", msg])
        if r.returncode == 0:
            subprocess.run(["git", "-C", HERE, "push", "origin", "main"], check=True)
            print("Push OK.")
            if not args.no_dispatch:
                subprocess.run(["gh", "workflow", "run", "scan.yml", "-R", "sstadniczenko-collab/hts-premarket"])
                print("Workflow odpalony.")
        else:
            print("Brak zmian w bars.json — nic do pushu.")
    except Exception as e:
        print(f"Push/dispatch nieudany: {e}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
