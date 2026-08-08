#!/usr/bin/env python3
"""Backtest logiki HtsSwingBot w Pythonie — wierny port reguł egzekucji z cBota,
na REALNYCH danych cTrader (bars.json). Mierzy edge w R (jednostkach ryzyka),
niezależnie od sizingu, żeby odpowiedzieć: czy AAA/AA+ ma przewagę.

Każdy setup (AAA/AA+) = niezależna transakcja 1R:
  - wejście: OPEN świecy PO świecy sygnału (jak OnBar w cBocie),
  - SL wg SlMode (0 wolna wstęga / 1 szybka wstęga [default] / 2 ATR),
  - wyjścia: SL, opcjonalny TP-RR, band-break (close przebija szybką wstęgę
    w kontrę), flip (przeciwny cross) — jak w HtsSwingBot.cs,
  - wynik w R = (exit-entry)/slDist.

Użycie:
    python backtest.py                    # D1, wszystkie symbole, SlMode 1
    python backtest.py --tf 4h
    python backtest.py --slmode 2 --tp 2  # SL=ATR, TP=2R
    python backtest.py --assets DAX,GC,NQ
"""
from __future__ import annotations

import argparse
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import hts_logic as H          # noqa: E402
import data_bars as B          # noqa: E402

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)


def band_arrays(df, cfg):
    fh, fl, fhl2, _ = H._bands(df, cfg["fast_ma"], cfg["ma_method"], cfg["smoothing"])
    sh, sl, shl2, _ = H._bands(df, cfg["slow_ma"], cfg["ma_method"], cfg["smoothing"])
    atr = H._atr(df, cfg["atr_length"])
    return (fh.to_numpy(), fl.to_numpy(), sh.to_numpy(), sl.to_numpy(), atr.to_numpy())


def backtest_symbol(df, cfg, slmode, sl_buf_pct, sl_atr_mult, tp_rr, exit_band, exit_flip):
    setups = H.scan(df, cfg)
    if not setups:
        return []
    o = df["open"].to_numpy()
    h = df["high"].to_numpy()
    l = df["low"].to_numpy()
    c = df["close"].to_numpy()
    fh, fl, sh, sl, atr = band_arrays(df, cfg)
    n = len(df)
    trades = []

    for s in setups:
        sig = s["bar_index"]
        ent_i = sig + 1
        if ent_i >= n:
            continue
        long = s["direction"] == "long"
        entry = o[ent_i]
        buf = entry * sl_buf_pct / 100.0
        if slmode == 2:
            sl_price = entry - sl_atr_mult * atr[sig] - buf if long else entry + sl_atr_mult * atr[sig] + buf
        elif slmode == 1:
            sl_price = fl[sig] - buf if long else fh[sig] + buf
        else:
            sl_price = sh[sig] - buf if long else sl[sig] + buf
        sl_dist = (entry - sl_price) if long else (sl_price - entry)
        if sl_dist <= 0:
            continue
        tp_price = None
        if tp_rr > 0:
            tp_price = entry + tp_rr * sl_dist if long else entry - tp_rr * sl_dist

        exit_price = None
        exit_reason = None
        for j in range(ent_i, n):
            # intrabar: SL / TP (SL pierwszy — konserwatywnie)
            if long:
                if l[j] <= sl_price:
                    exit_price, exit_reason = sl_price, "SL"; break
                if tp_price is not None and h[j] >= tp_price:
                    exit_price, exit_reason = tp_price, "TP"; break
            else:
                if h[j] >= sl_price:
                    exit_price, exit_reason = sl_price, "SL"; break
                if tp_price is not None and l[j] <= tp_price:
                    exit_price, exit_reason = tp_price, "TP"; break
            # na zamknięciu: band-break / flip
            if exit_band:
                if long and c[j] < fl[j]:
                    exit_price, exit_reason = c[j], "band"; break
                if not long and c[j] > fh[j]:
                    exit_price, exit_reason = c[j], "band"; break
            if exit_flip:
                if long and fh[j] < sl[j]:
                    exit_price, exit_reason = c[j], "flip"; break
                if not long and fl[j] > sh[j]:
                    exit_price, exit_reason = c[j], "flip"; break
        if exit_price is None:
            exit_price, exit_reason = c[-1], "open-end"  # jeszcze otwarta na końcu danych
        r = ((exit_price - entry) if long else (entry - exit_price)) / sl_dist
        trades.append({"type": s["type"], "dir": s["direction"], "r": r, "reason": exit_reason,
                       "date": s["bar_time"].strftime("%Y-%m-%d"),
                       "entry": entry, "sl_dist": sl_dist})
    return trades


def _net_r(t, cost_bps):
    # koszt round-trip w bps ceny wejścia -> ubytek w R = cost_price / sl_dist
    if cost_bps <= 0:
        return t["r"]
    return t["r"] - (t["entry"] * cost_bps / 1e4) / t["sl_dist"]


def stats(trades, cost_bps=0.0):
    if not trades:
        return None
    rs = [_net_r(t, cost_bps) for t in trades]
    # koszt progowy (break-even) w bps: ile round-trip edge zniesie do zera
    mean_e_over_sl = sum(t["entry"] / t["sl_dist"] for t in trades) / len(trades)
    gross_avg = sum(t["r"] for t in trades) / len(trades)
    be_bps = (gross_avg / mean_e_over_sl * 1e4) if mean_e_over_sl > 0 else 0.0
    wins = [r for r in rs if r > 0]
    losses = [r for r in rs if r <= 0]
    tot = sum(rs)
    gross_w = sum(wins)
    gross_l = -sum(losses)
    pf = (gross_w / gross_l) if gross_l > 0 else float("inf")
    # max drawdown w R (equity krzywa)
    eq = 0.0; peak = 0.0; mdd = 0.0
    for r in rs:
        eq += r; peak = max(peak, eq); mdd = min(mdd, eq - peak)
    return {
        "n": len(rs), "win%": 100.0 * len(wins) / len(rs), "totR": tot,
        "avgR": tot / len(rs), "pf": pf, "maxDD_R": mdd, "be_bps": be_bps,
    }


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--tf", default="1d", choices=["1d", "4h"])
    ap.add_argument("--slmode", type=int, default=1, choices=[0, 1, 2])
    ap.add_argument("--slbuf", type=float, default=0.1)
    ap.add_argument("--slatr", type=float, default=2.0)
    ap.add_argument("--tp", type=float, default=0.0, help="TP w R (0=brak)")
    ap.add_argument("--no-band", action="store_true")
    ap.add_argument("--no-flip", action="store_true")
    ap.add_argument("--cost-bps", type=float, default=0.0,
                    help="koszt round-trip w bps ceny (spread+prowizja); odejmowany od R")
    ap.add_argument("--assets")
    ap.add_argument("--bars", default=os.path.join(ROOT, "bars.json"))
    args = ap.parse_args()

    cfg = json.load(open(os.path.join(ROOT, "config.json"), encoding="utf-8"))["strategy"]
    uni = json.load(open(os.path.join(ROOT, "universe.json"), encoding="utf-8"))
    store = B.load(args.bars)
    if not store:
        print("Brak bars.json — najpierw fetch_ctrader.py"); return 1

    assets = [i["asset"] for i in uni["instruments"]]
    if args.assets:
        want = {a.strip().upper() for a in args.assets.split(",")}
        assets = [a for a in assets if a.upper() in want]

    slname = {0: "wolna wstęga", 1: "szybka wstęga", 2: f"ATR×{args.slatr}"}[args.slmode]
    cb = args.cost_bps
    print(f"Backtest HtsSwingBot | tf={args.tf} | SL={slname} buf {args.slbuf}% | "
          f"TP={'brak' if args.tp <= 0 else str(args.tp)+'R'} | "
          f"band-break={not args.no_band} flip={not args.no_flip} | koszt {cb} bps\n")

    all_trades = []
    rows = []
    for a in assets:
        df = B.frame(store, a, args.tf)
        if df is None or len(df) < cfg["slow_ma"] + cfg["smoothing"] + 5:
            continue
        tr = backtest_symbol(df, cfg, args.slmode, args.slbuf, args.slatr, args.tp,
                             not args.no_band, not args.no_flip)
        all_trades += tr
        st = stats(tr, cb)
        if st:
            rows.append((a, st))

    # be_bps = koszt progowy: powyżej niego instrument wychodzi na minus
    hdr = f"{'symbol':8}{'n':>4}{'win%':>7}{'totR':>8}{'avgR':>7}{'PF':>6}{'maxDD_R':>9}{'BEcost_bps':>11}"
    print(hdr); print("-" * len(hdr))
    pos = []
    for a, st in sorted(rows, key=lambda x: -x[1]["totR"]):
        pf = f"{st['pf']:.2f}" if st["pf"] != float("inf") else "inf"
        print(f"{a:8}{st['n']:>4}{st['win%']:>7.1f}{st['totR']:>8.1f}{st['avgR']:>7.2f}{pf:>6}{st['maxDD_R']:>9.1f}{st['be_bps']:>11.1f}")
        if st["totR"] > 0:
            pos.append(a)
    print("-" * len(hdr))
    for typ in ("AAA", "AA+"):
        st = stats([t for t in all_trades if t["type"] == typ], cb)
        if st:
            pf = f"{st['pf']:.2f}" if st["pf"] != float("inf") else "inf"
            print(f"{typ:8}{st['n']:>4}{st['win%']:>7.1f}{st['totR']:>8.1f}{st['avgR']:>7.2f}{pf:>6}{st['maxDD_R']:>9.1f}{st['be_bps']:>11.1f}")
    ov = stats(all_trades, cb)
    if ov:
        pf = f"{ov['pf']:.2f}" if ov["pf"] != float("inf") else "inf"
        print(f"{'RAZEM':8}{ov['n']:>4}{ov['win%']:>7.1f}{ov['totR']:>8.1f}{ov['avgR']:>7.2f}{pf:>6}{ov['maxDD_R']:>9.1f}{ov['be_bps']:>11.1f}")
        from collections import Counter
        print("\nwyjścia:", dict(Counter(t["reason"] for t in all_trades)))
        pos_totR = sum(st["totR"] for a, st in rows if st["totR"] > 0)
        pos_n = sum(st["n"] for a, st in rows if st["totR"] > 0)
        print(f"koszyk DODATNI po koszcie {cb} bps ({len(pos)}): {', '.join(pos) if pos else '—'}")
        if pos:
            print(f"  -> {pos_n} trade'ów, suma {pos_totR:.1f}R (tylko instrumenty dodatnie po koszcie)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
