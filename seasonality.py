# -*- coding: utf-8 -*-
"""seasonality.py — strona SEZONOWOŚCI dla HTS Premarket Scanner (kontekst przedsesyjny).

Przeniesione z projektu sezonowość-backtest (2026-08-08): nakładki cykliczne LW
(Larry Williams) + COT (CFTC) + rzeczywistość per aktywo — jako KONTEKST przed sesją,
nie sygnał (walidacja pokazała słabą przenośność OOS; dlatego wyprowadzone z tabeli
backtestowej tutaj, gdzie służą jako materiał referencyjny).

Reużywa rendererów z sezonowość-backtest (import) — zero duplikacji kodu/danych.
Generacja LOKALNA (czyta dane z sezonowość-backtest/data), zapis do docs/seasonality.html
(statyczna strona commitowana do repo; dane sezonowe są ~miesięczne, nie potrzebują
regeneracji 2×/dobę przez GitHub Action — scan.py/render.py NIE ruszane).

Użycie:  python seasonality.py   → docs/seasonality.html
"""
import os
import sys
from datetime import datetime, timezone

HERE = os.path.dirname(os.path.abspath(__file__))
SEZ = r"Y:\15_AI\02_TRADING\sezonowosc_backtest"
sys.path.insert(0, SEZ)
for s in (sys.stdout, sys.stderr):
    try: s.reconfigure(encoding="utf-8")
    except Exception: pass

import build_report as B   # renderery + load() + PAGE (bez side-effectów: main pod __main__)


def main():
    lw = B.load("lw_seasonal.json")
    cot = B.load("cot_seasonal.json")
    corr = B.load("corr.json")
    fc = B.load("lw_forecast.json")
    reality = B.load("reality_2026.json")

    section = (B.render_corr(corr) + B.render_forecast(fc)
               + B.render_convergence(lw, cot, reality) + B.render_weekly(lw, cot, reality))
    ts = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    sub = ("Sezonowość aktywów 2026 — LW (Larry Williams) + COT (CFTC) + rzeczywistość, jako "
           "<b>kontekst przedsesyjny</b>. Przeniesione z sezonowość-backtest. To nakładki cykliczne "
           "(kontekst), NIE sygnał — walidacja OOS pokazała słabą przenośność. Przewiń osie w bok →")
    html = B.PAGE.format(sub=sub, section=section, ts=ts,
                         lwsrc=(lw or {}).get("source", "LW —"),
                         cotsrc=(cot or {}).get("source", "COT —"))
    # popraw <title> na premarket
    html = html.replace("<title>Sezonowość — backtest</title>",
                        "<title>Sezonowość — HTS Premarket</title>")
    html = html.replace("<h1>Sezonowość — backtest</h1>",
                        "<h1>🗓️ Sezonowość — HTS Premarket Scanner</h1>")
    out = os.path.join(HERE, "docs", "seasonality.html")
    os.makedirs(os.path.dirname(out), exist_ok=True)
    with open(out, "w", encoding="utf-8") as f:
        f.write(html)
    print("OK ->", out, f"| {len(html)} B")


if __name__ == "__main__":
    main()
