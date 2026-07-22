#!/usr/bin/env python3
"""HTS Premarket Scanner — chmurowa wersja hts_scanner.

Dla każdego instrumentu z uniwersum vtrade pobiera D1 (+ H4) z yfinance,
odpala sprawdzoną logikę HTS Swing Pro Filter (AAA/AA+), liczy bieżący stan
trendu wstęg i ostatni setup. Wypluwa docs/data.json + docs/index.html.

Uruchamiany 2× dziennie przez GitHub Action (przed otwarciem EU i US).

Użycie:
    python scan.py --out docs                 # pełny skan + HTML
    python scan.py --out docs --only 1d       # tylko D1 (szybciej)
    python scan.py --dry-run                  # drukuje, nie zapisuje
    python scan.py --assets GC,ES,NQ          # podzbiór do testów
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import traceback
from datetime import datetime, timezone

import hts_logic as H
import data_yf as D
import levels as L
import render

HERE = os.path.dirname(os.path.abspath(__file__))


def load_json(name: str) -> dict:
    with open(os.path.join(HERE, name), encoding="utf-8") as f:
        return json.load(f)


def _px(x):
    """Zaokrąglij poziom cenowy sensownie do skali instrumentu."""
    if x is None:
        return None
    ax = abs(x)
    if ax >= 1000:
        return round(x, 1)
    if ax >= 100:
        return round(x, 2)
    if ax >= 10:
        return round(x, 3)
    return round(x, 4)


def _round_plan(plan: dict | None) -> dict | None:
    if not plan:
        return None
    p = dict(plan)
    for k in ("price", "entry_line", "entry_far", "breath_line", "invalidation", "atr", "dist_to_entry"):
        p[k] = _px(p.get(k))
    for k in ("band_gap_pct", "atr_pct", "dist_to_entry_pct"):
        if p.get(k) is not None:
            p[k] = round(p[k], 2)
    if p.get("dist_to_entry_atr") is not None:
        p["dist_to_entry_atr"] = round(p["dist_to_entry_atr"], 2)
    if p.get("adx") is not None:
        p["adx"] = round(p["adx"], 1)
    return p


def _daily_context(daily_df, lvl_cfg: dict) -> dict:
    """Pivot dzienny + gapy (+gap-over-gap) z danych D1, zaokrąglone do skali."""
    piv = L.daily_pivot(daily_df)
    gap = L.gap_analysis(daily_df, lvl_cfg.get("gap_min_pct", 0.15), lvl_cfg.get("gap_lookback", 40))
    if piv:
        for k in ("P", "R1", "R2", "R3", "S1", "S2", "S3", "price"):
            piv[k] = _px(piv[k])
        for side in ("res", "sup"):
            if piv.get(side):
                piv[side]["val"] = _px(piv[side]["val"])
                piv[side]["dist_pct"] = round(piv[side]["dist_pct"], 2)
    if gap and gap.get("last"):
        gap["last"]["top"] = _px(gap["last"]["top"])
        gap["last"]["bottom"] = _px(gap["last"]["bottom"])
    if gap and gap.get("magnet"):
        gap["magnet"]["top"] = _px(gap["magnet"]["top"])
        gap["magnet"]["bottom"] = _px(gap["magnet"]["bottom"])
    return {"pivot": piv, "gap": gap}


def _fetch(yf_symbol: str, tf: str):
    if tf == "1d":
        return D.fetch_daily(yf_symbol)
    if tf == "4h":
        return D.fetch_h4(yf_symbol)
    raise ValueError(f"Nieobsługiwany timeframe: {tf}")


def scan_instrument(inst: dict, timeframes: list[str], strat: dict, fresh_bars: int, lvl_cfg: dict) -> dict:
    out = {
        "asset": inst["asset"],
        "name": inst["name"],
        "ftmo": inst.get("ftmo"),
        "yf": inst["yf"],
        "group": inst.get("group", ""),
        "tf": {},
        "daily": None,
    }
    for tf in timeframes:
        try:
            df = _fetch(inst["yf"], tf)
            if df is None or df.empty or len(df) < strat["slow_ma"] + strat["smoothing"] + 5:
                out["tf"][tf] = {"ok": False, "reason": "za mało danych" if df is not None else "brak danych"}
                continue
            if tf == "1d":
                out["daily"] = _daily_context(df, lvl_cfg)
            state = H.trend_state(df, strat)
            setups = H.scan(df, strat)
            plan = H.entry_plan(df, strat)
            last = setups[-1] if setups else None
            last_bar = len(df) - 1
            last_setup = None
            if last is not None:
                bars_ago = last_bar - last["bar_index"]
                last_setup = {
                    "type": last["type"],
                    "direction": last["direction"],
                    "suffix": last["suffix"],
                    "adx_label": last["adx_label"],
                    "adx": round(last["adx"], 1),
                    "price": last["price"],
                    "bars_ago": bars_ago,
                    "bar_time": last["bar_time"].strftime("%Y-%m-%d %H:%M"),
                    "fresh": bars_ago <= fresh_bars,
                }
            out["tf"][tf] = {
                "ok": True,
                "bars": len(df),
                "trend": state["trend"] if state else "none",
                "price": round(state["price"], 4) if state else None,
                "adx": round(state["adx"], 1) if state and state["adx"] is not None else None,
                "adx_label": state["adx_label"] if state else None,
                "atr_pct": round(state["atr_pct"], 2) if state and state["atr_pct"] is not None else None,
                "last_bar_time": state["last_bar_time"].strftime("%Y-%m-%d %H:%M") if state else None,
                "last_setup": last_setup,
                "plan": _round_plan(plan),
            }
        except Exception as e:  # jeden instrument nie może wywalić całego skanu
            out["tf"][tf] = {"ok": False, "reason": f"błąd: {e}"}
            print(f"  ! {inst['asset']} {tf}: {e}", file=sys.stderr)
            traceback.print_exc(file=sys.stderr)
    return out


def session_hint(now: datetime) -> str:
    h = now.hour
    if h < 10:
        return "przed otwarciem sesji europejskiej"
    if h < 18:
        return "przed / w trakcie sesji US"
    return "po zamknięciu US"


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default="docs", help="katalog wyjściowy (index.html + data.json)")
    ap.add_argument("--only", help="skanuj tylko ten timeframe (1d / 4h)")
    ap.add_argument("--assets", help="przecinkami: podzbiór assetów do skanu (test)")
    ap.add_argument("--dry-run", action="store_true", help="nie zapisuj plików")
    args = ap.parse_args()

    cfg = load_json("config.json")
    uni = load_json("universe.json")
    strat = cfg["strategy"]
    fresh_bars = cfg["scan"]["fresh_bars"]

    timeframes = [args.only] if args.only else uni["timeframes"]
    instruments = uni["instruments"]
    if args.assets:
        want = {a.strip().upper() for a in args.assets.split(",")}
        instruments = [i for i in instruments if i["asset"].upper() in want]

    now = datetime.now(timezone.utc)
    print(f"HTS Premarket Scan · {now:%Y-%m-%d %H:%M} UTC · {len(instruments)} instr. · tf={timeframes}")

    lvl_cfg = cfg.get("levels", {})
    results = []
    for inst in instruments:
        print(f"- {inst['asset']:7} ({inst['yf']}) ...", flush=True)
        results.append(scan_instrument(inst, timeframes, strat, fresh_bars, lvl_cfg))

    # spłaszczona lista świeżych setupów (premarket watchlist)
    fresh = []
    for r in results:
        for tf, d in r["tf"].items():
            ls = d.get("last_setup") if d.get("ok") else None
            if ls and ls.get("fresh"):
                fresh.append({
                    "asset": r["asset"], "name": r["name"], "ftmo": r.get("ftmo"), "tf": tf,
                    **ls,
                })
    # najświeższe najpierw, potem AAA przed AA+
    fresh.sort(key=lambda x: (x["bars_ago"], 0 if x["type"] == "AAA" else 1))

    # plan wejścia: instrumenty uzbrojone lub już w strefie retestu (actionable teraz)
    armed = []
    _rank = {"in_zone": 0, "armed": 1}
    for r in results:
        for tf, d in r["tf"].items():
            pl = d.get("plan") if d.get("ok") else None
            if pl and pl.get("status") in ("in_zone", "armed"):
                armed.append({"asset": r["asset"], "name": r["name"], "ftmo": r.get("ftmo"),
                              "tf": tf, "daily": r.get("daily"), **pl})
    # najpierw w strefie, potem najbliżej linii wejścia
    armed.sort(key=lambda x: (_rank.get(x["status"], 9), abs(x.get("dist_to_entry_pct") or 0)))

    payload = {
        "generated_utc": now.strftime("%Y-%m-%d %H:%M:%S"),
        "session_hint": session_hint(now),
        "timeframes": timeframes,
        "universe_count": len(instruments),
        "fresh_bars": fresh_bars,
        "strategy": strat,
        "armed": armed,
        "fresh": fresh,
        "instruments": results,
    }

    n_ok = sum(1 for r in results for d in r["tf"].values() if d.get("ok"))
    n_tot = sum(len(r["tf"]) for r in results)
    print(f"Gotowe: {n_ok}/{n_tot} (instr,tf) OK · {len(fresh)} świeżych setupów · {len(armed)} w planie wejścia")

    if args.dry_run:
        print(json.dumps({"armed": armed, "fresh": fresh}, indent=2, ensure_ascii=False))
        return 0

    os.makedirs(args.out, exist_ok=True)
    with open(os.path.join(args.out, "data.json"), "w", encoding="utf-8") as f:
        json.dump(payload, f, indent=1, ensure_ascii=False)
    html = render.build_html(payload)
    with open(os.path.join(args.out, "index.html"), "w", encoding="utf-8") as f:
        f.write(html)
    print(f"Zapisano: {args.out}/index.html + data.json")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
