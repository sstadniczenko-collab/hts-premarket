#!/usr/bin/env python3
"""HTS Premarket Brief — samodzielny briefing do czytania przez Claude.

To NIE jest generator dashboardu (to robi scan.py → docs/). To lekki tryb
"odpal i przeczytaj": czysty yfinance, BEZ wtyczki cTradera (bars.json) i BEZ
klucza API (news AI). Zero sekretów, zero zapisu do docs/ — nie ruszy strony.

Dla każdego instrumentu z uniwersum vtrade liczy tę samą sprawdzoną logikę HTS
Swing Pro Filter (wstęgi SMA33/144, setupy AAA/AA+, ADX) na D1 (nagłówek) i H4
(best-effort). Wypluwa czytelny markdown na ekran ORAZ do premarket_<data>.md.

Użycie:
    python brief.py                     # pełny skan D1+H4, markdown na ekran + do pliku
    python brief.py --only 1d           # tylko D1 (szybciej)
    python brief.py --assets GC,ES,NQ   # podzbiór (test)
    python brief.py --no-save           # nie zapisuj pliku, tylko ekran
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

HERE = os.path.dirname(os.path.abspath(__file__))


def load_json(name: str) -> dict:
    with open(os.path.join(HERE, name), encoding="utf-8") as f:
        return json.load(f)


def _px(x):
    """Zaokrąglij poziom cenowy do skali instrumentu."""
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


def scan_instrument(inst: dict, timeframes: list[str], strat: dict, fresh_bars: int) -> dict:
    out = {"asset": inst["asset"], "name": inst["name"], "ftmo": inst.get("ftmo"),
           "yf": inst["yf"], "group": inst.get("group", ""), "tf": {}}
    for tf in timeframes:
        try:
            df = D.fetch_daily(inst["yf"]) if tf == "1d" else D.fetch_h4(inst["yf"])
            if df is None or df.empty or len(df) < strat["slow_ma"] + strat["smoothing"] + 5:
                out["tf"][tf] = {"ok": False, "reason": "za mało danych"}
                continue
            state = H.trend_state(df, strat)
            setups = H.scan(df, strat)
            plan = H.entry_plan(df, strat)
            last_bar = len(df) - 1
            last_setup = None
            if setups:
                last = setups[-1]
                bars_ago = last_bar - last["bar_index"]
                last_setup = {
                    "type": last["type"], "direction": last["direction"],
                    "suffix": last["suffix"], "adx_label": last["adx_label"],
                    "adx": round(last["adx"], 1), "price": _px(last["price"]),
                    "bars_ago": bars_ago,
                    "bar_time": last["bar_time"].strftime("%Y-%m-%d %H:%M"),
                    "fresh": bars_ago <= fresh_bars,
                }
            out["tf"][tf] = {
                "ok": True, "bars": len(df),
                "trend": state["trend"] if state else "none",
                "price": _px(state["price"]) if state else None,
                "adx": round(state["adx"], 1) if state and state["adx"] is not None else None,
                "adx_label": state["adx_label"] if state else None,
                "atr_pct": round(state["atr_pct"], 2) if state and state["atr_pct"] is not None else None,
                "last_bar_time": state["last_bar_time"].strftime("%Y-%m-%d %H:%M") if state else None,
                "last_setup": last_setup,
                "plan": _round_plan(plan),
            }
        except Exception as e:  # jeden instrument nie wywala całego skanu
            out["tf"][tf] = {"ok": False, "reason": f"błąd: {e}"}
            print(f"  ! {inst['asset']} {tf}: {e}", file=sys.stderr)
            traceback.print_exc(file=sys.stderr)
    return out


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


# ---------------------------------------------------------------------------
# Render markdown
# ---------------------------------------------------------------------------
_TREND_EMOJI = {"long": "🟢 LONG", "short": "🔴 SHORT", "none": "⚪ brak"}
_STATUS_PL = {
    "in_zone": "🎯 w strefie retestu TERAZ",
    "armed": "🔫 uzbrojony (czeka na powrót do linii)",
    "needs_breath": "⏳ czeka na oddech nad/pod wstęgą",
    "deep": "🕳️ przegłębiony (cena przebiła wstęgę)",
    "blocked_gap": "⛔ wstęgi za wąskie",
    "blocked_adx": "⛔ trend za słaby (ADX)",
}


def _session_hint(now: datetime) -> str:
    h = now.hour
    if h < 10:
        return "przed otwarciem sesji europejskiej"
    if h < 18:
        return "przed / w trakcie sesji US"
    return "po zamknięciu US"


def _fmt_dist(pl: dict) -> str:
    d = pl.get("dist_to_entry_pct")
    if d is None:
        return "—"
    atr = pl.get("dist_to_entry_atr")
    side = "cofka w dół" if d > 0 and pl["trend"] == "long" else \
           "cofka w górę" if d > 0 and pl["trend"] == "short" else "cena już poniżej/powyżej"
    tail = f" ({atr:+.2f} ATR)" if atr is not None else ""
    return f"{d:+.2f}%{tail} · {side}"


_GRADE_PL = {"strong": "mocny", "practitioner": "praktyczny", "weak": "słaby"}
_LEAN_PL = {"up": "w górę", "down": "w dół", "conflict": "sprzeczne"}


def _macro_fundamental(state: dict | None) -> list[str]:
    """
    Warstwa fundamentalna (nie z ceny i wolumenu) — z macro_drivers.json.
    To jest kontekst SELEKCJI / WIELKOŚCI / TRZYMANIA, nigdy sygnał wejścia.
    Zasady i źródła: MACRO.md.
    """
    if not state:
        return []
    reg, r = state.get("regime", {}), state.get("readings", {})
    out = []

    credit = reg.get("D4_credit")
    if credit and credit != "unknown":
        pl = {"WIDENING": "🟥 rozszerzają się (stres rośnie)",
              "COMPRESSING": "🟩 zawężają się (apetyt na ryzyko)",
              "STABLE": "🟨 stabilne"}.get(credit, credit)
        out.append(f"- **Spready kredytowe HY** (D4, dowód: mocny): {pl} "
                   f"— wyprzedzają słabość akcji o kwartały")

    gold = reg.get("D2_real_yield_gold")
    if gold == "ALIVE":
        out.append(f"- **Złoto — realne rentowności** (D2, dowód: mocny): link ODZYSKANY "
                   f"(korelacja {reg.get('D2_corr')}) — klasyczna zależność znów działa")
    elif gold == "BROKEN":
        out.append(f"- **Złoto — realne rentowności** (D2): link ZŁAMANY "
                   f"(korelacja {reg.get('D2_corr')}) — rządzi skup banków centralnych (D11), "
                   f"NIE czytaj złota z realnych rentowności")
    elif gold == "unknown":
        out.append("- **Złoto — realne rentowności** (D2): brak danych (FRED niedostępny) "
                   "→ domyślnie rządzi D11 (skup banków centralnych)")

    haven = reg.get("D3_safe_haven_window")
    if haven and haven != "unknown":
        pl = "OTWARTE" if haven == "OPEN" else "ZAMKNIĘTE"
        out.append(f"- **Okno safe-haven** (D3): {pl} (korelacja złoto/S&P {reg.get('D3_corr')}) "
                   f"— reguła „złoto w górę = akcje w dół\" działa TYLKO gdy otwarte")

    ts = reg.get("D18_term_structure")
    if ts and ts != "unknown":
        out.append(f"- **Struktura terminowa VIX** (D18, dowód: mocny): {ts} "
                   f"(baza {reg.get('D18_basis')}) — to carry, NIE prognoza kierunku VIX")

    if state.get("failures"):
        out.append(f"- ⚠️ _dane niepełne — brak: {', '.join(state['failures'])}_")
    subs = state.get("coverage", {}).get("substitutes") or []
    if subs:
        out.append(f"- ⚠️ _zamienniki (nie seria źródłowa): {', '.join(subs)}_")
    return out


def _macro_radar(results: list[dict], state: dict | None = None) -> list[str]:
    by = {r["asset"]: r for r in results}
    fundamental = _macro_fundamental(state)
    lines: list[str] = []
    labels = {"VX": "VIX (strach)", "DXY": "Dollar Index", "US10": "US 10Y (rentowność ×10)"}
    for a, lbl in labels.items():
        r = by.get(a)
        d = r["tf"].get("1d") if r else None
        if not d or not d.get("ok"):
            continue
        tr = _TREND_EMOJI.get(d["trend"], d["trend"])
        adx = f" · ADX {d['adx_label']}" if d.get("adx_label") else ""
        lines.append(f"- **{lbl}**: {d['price']} · {tr}{adx}")
    # prosty odczyt risk-on/off z VIX
    vx = by.get("VX")
    vxd = vx["tf"].get("1d") if vx else None
    if vxd and vxd.get("ok"):
        p = vxd["price"] or 0
        mood = "🟩 risk-ON (spokój)" if p < 16 else "🟨 neutralnie" if p < 22 else "🟥 risk-OFF (nerwowo)"
        lines.append(f"- **Nastrój z VIX**: {mood} (VIX {p})")
    # nagłówek sekcji wykresowej tylko gdy naprawdę są pod nim linie
    if fundamental and lines:
        return fundamental + ["", "_Odczyt z wykresu (cena/wolumen, nie fundament):_"] + lines
    return fundamental + lines


def build_markdown(results: list[dict], now: datetime, timeframes: list[str],
                   fresh_bars: int, macro_state: dict | None = None) -> str:
    # actionable teraz: in_zone / armed (D1 pierwsze, potem H4)
    _rank = {"in_zone": 0, "armed": 1}
    armed = []
    for r in results:
        for tf, d in r["tf"].items():
            pl = d.get("plan") if d.get("ok") else None
            if pl and pl.get("status") in ("in_zone", "armed"):
                armed.append({"asset": r["asset"], "name": r["name"], "ftmo": r.get("ftmo"), "tf": tf, **pl})
    armed.sort(key=lambda x: (_rank.get(x["status"], 9), 0 if x["tf"] == "1d" else 1,
                              abs(x.get("dist_to_entry_pct") or 0)))

    # świeże setupy
    fresh = []
    for r in results:
        for tf, d in r["tf"].items():
            ls = d.get("last_setup") if d.get("ok") else None
            if ls and ls.get("fresh"):
                fresh.append({"asset": r["asset"], "name": r["name"], "tf": tf, **ls})
    fresh.sort(key=lambda x: (x["bars_ago"], 0 if x["type"] == "AAA" else 1))

    L = []
    L.append(f"# 🌅 HTS Premarket Brief — {now:%Y-%m-%d %H:%M} UTC")
    L.append(f"_{_session_hint(now)} · {len(results)} instrumentów · dane: yfinance "
             f"(D1+H4, tylko świece zamknięte) · tf={'+'.join(timeframes)}_\n")

    L.append("## 🌍 Radar makro")
    radar = _macro_radar(results, macro_state)
    L += radar if radar else ["- (brak danych makro)"]
    L.append("")
    if macro_state:
        L.append("_Warstwa fundamentalna = kontekst selekcji / wielkości pozycji / trzymania. "
                 "**Nigdy sygnał wejścia i nigdy weto dla setupu.** Źródła i oceny: MACRO.md._")
        L.append("")

    L.append(f"## 🔥 Do zagrania TERAZ ({len(armed)})")
    if not armed:
        L.append("_Żaden instrument nie jest w strefie retestu ani uzbrojony. Cierpliwość — to normalne._\n")
    else:
        L.append("Instrumenty w strefie retestu lub uzbrojone (cena blisko linii wejścia HTS).\n")
        for a in armed:
            head = f"### {a['asset']} · {a['name']} · [{a['tf']}] · {_TREND_EMOJI[a['trend']]} · setup **{a['next_setup']}{a['suffix']}**"
            L.append(head)
            L.append(f"- **{_STATUS_PL.get(a['status'], a['status'])}**")
            L.append(f"- cena **{a['price']}** · linia wejścia (retest wstęgi) **{a['entry_line']}** · oddech **{a['breath_line']}**")
            L.append(f"- 🛑 stop / invalidacja (wolna wstęga) **{a['invalidation']}**")
            L.append(f"- dystans do wejścia: **{_fmt_dist(a)}**")
            extra = []
            if a.get("adx_label"):
                extra.append(f"ADX {a['adx_label']} ({a.get('adx')})")
            if a.get("atr_pct") is not None:
                extra.append(f"ATR {a['atr_pct']}%")
            if a.get("band_gap_pct") is not None:
                extra.append(f"rozstaw wstęg {a['band_gap_pct']}%")
            if a.get("ftmo"):
                extra.append(f"FTMO: {a['ftmo']}")
            if extra:
                L.append(f"- {' · '.join(extra)}")
            L.append("")

    L.append(f"## 🆕 Świeże setupy (ostatnie ≤{fresh_bars} świece)")
    if not fresh:
        L.append("_Brak świeżych setupów w oknie._\n")
    else:
        L.append("| Asset | Nazwa | TF | Setup | Kier. | ADX | Cena | Kiedy |")
        L.append("|---|---|---|---|---|---|---|---|")
        for f in fresh:
            kier = "🟢 long" if f["direction"] == "long" else "🔴 short"
            ago = "ostatnia" if f["bars_ago"] == 0 else f"{f['bars_ago']} świece temu"
            L.append(f"| {f['asset']} | {f['name']} | {f['tf']} | {f['type']}{f['suffix']} | {kier} "
                     f"| {f['adx_label']} ({f['adx']}) | {f['price']} | {ago} |")
        L.append("")

    L.append("## 📊 Pełna mapa trendów (D1)")
    L.append("| Asset | Nazwa | Trend | Cena | ADX | ATR% | Plan wejścia |")
    L.append("|---|---|---|---|---|---|---|")
    for r in sorted(results, key=lambda r: (r.get("group", ""), r["asset"])):
        d = r["tf"].get("1d")
        if not d or not d.get("ok"):
            reason = d.get("reason", "brak") if d else "brak"
            L.append(f"| {r['asset']} | {r['name']} | ⚠️ {reason} | — | — | — | — |")
            continue
        pl = d.get("plan")
        plan_txt = "—"
        if pl:
            plan_txt = f"{_STATUS_PL.get(pl['status'], pl['status']).split(' ', 1)[-1]}"
            if pl.get("dist_to_entry_pct") is not None and pl["status"] in ("armed", "needs_breath"):
                plan_txt += f" ({pl['dist_to_entry_pct']:+.1f}%)"
        L.append(f"| {r['asset']} | {r['name']} | {_TREND_EMOJI[d['trend']]} | {d['price']} "
                 f"| {d.get('adx_label') or '—'} ({d.get('adx') or '—'}) | {d.get('atr_pct') or '—'} | {plan_txt} |")
    L.append("")

    L.append("---")
    L.append("### Jak to czytać (skrót gramatyki HTS)")
    L.append("- **Wstęgi**: szybka SMA33 + wolna SMA144. Trend = szybka nad wolną (long) / pod (short).")
    L.append("- **AAA** = pierwszy retest wstęgi po przecięciu i oddechu; **AA+** = kolejne dokładki (piramida).")
    L.append("- **Linia wejścia** = krawędź szybkiej wstęgi (miejsce retestu). **Stop** = wolna wstęga.")
    L.append("- **ADX**: <20 SŁABY (blok), 20–25 UMIARKOWANY (*), 25–40 SILNY (czysty), ≥40 WYCZERPANY (!).")
    L.append("- **Statusy**: 🎯 w strefie / 🔫 uzbrojony / ⏳ czeka na oddech / 🕳️ przegłębiony / ⛔ zablokowany.")
    L.append("")
    L.append("> ⚠️ Setupy liczone na **zamkniętych świecach D1/H4**. Dane z yfinance są darmowe i opóźnione, "
             "indeksy nie są 24h. To **wsparcie decyzji, nie sygnały do klikania** — zweryfikuj poziom na "
             "swoim wykresie/brokerze przed wejściem. Futures (=F) mają ~rok historii, więc część może wyjść jako 'za mało danych'.")
    return "\n".join(L)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--only", help="tylko ten timeframe (1d / 4h)")
    ap.add_argument("--assets", help="przecinkami: podzbiór assetów (test)")
    ap.add_argument("--no-save", action="store_true", help="nie zapisuj pliku premarket_<data>.md")
    ap.add_argument("--no-macro", action="store_true", help="pomiń warstwę fundamentalną (macro.py)")
    args = ap.parse_args()

    # konsola Windows bywa cp1250 → wymuś UTF-8 na wyjściu (emoji/PL)
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8")
        except Exception:
            pass

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
    print(f"HTS Premarket Brief · {now:%Y-%m-%d %H:%M} UTC · {len(instruments)} instr. · tf={timeframes} · yfinance",
          file=sys.stderr)

    results = []
    for inst in instruments:
        print(f"- {inst['asset']:7} ({inst['yf']}) ...", file=sys.stderr, flush=True)
        results.append(scan_instrument(inst, timeframes, strat, fresh_bars))

    # warstwa fundamentalna (nie z ceny/wolumenu) — bez kluczy API, fail-soft
    macro_state = None
    if not args.no_macro:
        try:
            import macro as M
            print("- warstwa makro (FRED/Yahoo) ...", file=sys.stderr, flush=True)
            macro_state = M.compute_state()
            M.enrich(results, macro_state)
        except Exception as e:
            print(f"  ! makro pominięte: {e}", file=sys.stderr)
            macro_state = None

    md = build_markdown(results, now, timeframes, fresh_bars, macro_state)
    print(md)  # stdout = markdown do przeczytania przez Claude

    if not args.no_save:
        path = os.path.join(HERE, f"premarket_{now:%Y-%m-%d}.md")
        with open(path, "w", encoding="utf-8") as f:
            f.write(md)
        print(f"\n(zapisano: {os.path.basename(path)})", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
