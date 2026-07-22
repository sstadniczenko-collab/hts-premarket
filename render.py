"""Render dashboardu HTML dla HTS Premarket Scanner (self-contained, dark)."""
from __future__ import annotations

import html


def _esc(s) -> str:
    return html.escape(str(s), quote=True)


def _dir_arrow(direction: str) -> str:
    return "▲" if direction == "long" else "▼"


def _nm(name: str, ftmo) -> str:
    """Nazwa instrumentu + symbol FTMO w małym nawiasie (jeśli jest)."""
    if ftmo:
        return f'{_esc(name)} <span class="ftmo">({_esc(ftmo)})</span>'
    return _esc(name)


def _trend_badge(trend: str) -> str:
    cls = {"long": "up", "short": "down"}.get(trend, "flat")
    txt = {"long": "LONG", "short": "SHORT", "none": "—"}.get(trend, "—")
    return f'<span class="badge {cls}">{txt}</span>'


def _setup_cell(ls: dict | None) -> str:
    if not ls:
        return '<span class="muted">—</span>'
    d = ls["direction"]
    cls = "up" if d == "long" else "down"
    fresh = " fresh" if ls.get("fresh") else ""
    age = "teraz" if ls["bars_ago"] == 0 else f'{ls["bars_ago"]} św. temu'
    return (
        f'<span class="setup {cls}{fresh}" title="{_esc(ls["bar_time"])} · ADX {_esc(ls["adx"])} {_esc(ls["adx_label"])}">'
        f'{_dir_arrow(d)} {_esc(ls["type"])}{_esc(ls["suffix"])}</span> '
        f'<span class="age">{_esc(age)}</span>'
    )


_STATUS_PL = {
    "in_zone": ("W STREFIE", "Cena w strefie retestu teraz — obserwuj reakcję na wstędze"),
    "armed": ("UZBROJONY", "Czeka na powrót ceny do linii wejścia"),
    "needs_breath": ("BRAK ODDECHU", "Cena musi najpierw wybić powyżej/poniżej wstęgi, potem retest"),
    "deep": ("PRZEGŁĘBIONY", "Cofka przebiła całą szybką wstęgę na wylot — retest niedomknięty, ostrożnie"),
    "blocked_gap": ("WSTĘGI WĄSKIE", "Odstęp wstęg poniżej progu — setup zablokowany"),
    "blocked_adx": ("ADX SŁABY", "Trend za słaby (ADX < 20) — setup zablokowany"),
}


def _plan_card(p: dict) -> str:
    d = p["trend"]
    cls = "up" if d == "long" else "down"
    stat_txt, stat_desc = _STATUS_PL.get(p["status"], (p["status"], ""))
    dp = p.get("dist_to_entry_pct")
    da = p.get("dist_to_entry_atr")
    if p["status"] == "in_zone":
        dist_txt = "w strefie"
    elif dp is not None:
        arrow = "↓" if d == "long" else "↑"
        atr_bit = f" · {abs(da):.2f} ATR" if da is not None else ""
        dist_txt = f"cofka {arrow} {abs(dp):.2f}%{atr_bit}"
    else:
        dist_txt = "—"
    return f"""
    <div class="card {cls}">
      <div class="card-top">
        <span class="tick">{_esc(p['asset'])}</span>
        <span class="tf">{_esc(p['tf'].upper())}</span>
      </div>
      <div class="card-sig">{_dir_arrow(d)} {_esc(p['next_setup'])}{_esc(p.get('suffix',''))} {'LONG' if d=='long' else 'SHORT'}</div>
      <div class="card-name">{_nm(p['name'], p.get('ftmo'))}</div>
      <div class="plan-grid">
        <span class="pl-k">wejście @</span><span class="pl-v hot">{_esc(p['entry_line'])} <span class="tf-tag">{_esc(p['tf'].upper())}</span></span>
        <span class="pl-k">strefa</span><span class="pl-v">{_esc(p['entry_far'])} – {_esc(p['entry_line'])}</span>
        <span class="pl-k">cena</span><span class="pl-v">{_esc(p['price'])} <span class="age">({_esc(dist_txt)})</span></span>
        <span class="pl-k">stop za</span><span class="pl-v cold">{_esc(p['invalidation'])}</span>
      </div>
      <div class="card-meta">
        <span class="stat stat-{_esc(p['status'])}" title="{_esc(stat_desc)}">{_esc(stat_txt)}</span>
        <span>ADX {_esc(p['adx'])} · {_esc(p['adx_label'])}</span>
      </div>
    </div>"""


def _plan_cell(pl: dict | None) -> str:
    if not pl:
        return '<span class="muted">—</span>'
    st = pl.get("status")
    if st in ("blocked_gap", "blocked_adx"):
        stat_txt = _STATUS_PL.get(st, (st, ""))[0]
        return f'<span class="muted" title="{_esc(_STATUS_PL.get(st, ("",""))[1])}">{_esc(stat_txt)}</span>'
    d = pl["trend"]
    cls = "up" if d == "long" else "down"
    tag = {"in_zone": "w strefie", "armed": "uzbr.", "needs_breath": "oddech", "deep": "przegł."}.get(st, st)
    tcls = {"in_zone": "t-zone", "armed": "t-armed", "deep": "t-deep"}.get(st, "t-wait")
    dp = pl.get("dist_to_entry_pct")
    dist = "" if st == "in_zone" or dp is None else f' <span class="age">{abs(dp):.2f}%</span>'
    return (
        f'<span class="setup {cls}" title="{_esc(_STATUS_PL.get(st, (st,""))[1])}">'
        f'{_esc(pl["next_setup"])}{_esc(pl.get("suffix",""))} @ {_esc(pl["entry_line"])}</span>'
        f' <span class="ptag {tcls}">{_esc(tag)}</span>{dist}'
    )


def _fresh_card(f: dict) -> str:
    d = f["direction"]
    cls = "up" if d == "long" else "down"
    age = "ostatnia świeca" if f["bars_ago"] == 0 else f'{f["bars_ago"]} św. temu'
    return f"""
    <div class="card {cls}">
      <div class="card-top">
        <span class="tick">{_esc(f['asset'])}</span>
        <span class="tf">{_esc(f['tf'].upper())}</span>
      </div>
      <div class="card-sig">{_dir_arrow(d)} {_esc(f['type'])}{_esc(f['suffix'])} {'LONG' if d=='long' else 'SHORT'}</div>
      <div class="card-name">{_nm(f['name'], f.get('ftmo'))}</div>
      <div class="card-meta">
        <span>@ {_esc(f['price'])}</span>
        <span>ADX {_esc(f['adx'])} · {_esc(f['adx_label'])}</span>
        <span class="age">{_esc(age)}</span>
      </div>
    </div>"""


def _rows(instruments: list[dict], timeframes: list[str]) -> str:
    # grupuj wg 'group'
    groups: dict[str, list[dict]] = {}
    for r in instruments:
        groups.setdefault(r.get("group") or "Inne", []).append(r)

    tf_cols = timeframes
    parts = []
    for gname, items in groups.items():
        parts.append(f'<tr class="grp"><td colspan="{2 + 3*len(tf_cols)}">{_esc(gname)}</td></tr>')
        for r in items:
            cells = [f'<td class="tick">{_esc(r["asset"])}</td><td class="nm">{_nm(r["name"], r.get("ftmo"))}</td>']
            for tf in tf_cols:
                d = r["tf"].get(tf, {})
                if not d.get("ok"):
                    cells.append(f'<td class="muted">{_esc(d.get("reason","—"))}</td><td class="muted">—</td><td class="muted">—</td>')
                else:
                    cells.append(f'<td>{_trend_badge(d["trend"])}</td>')
                    cells.append(f'<td>{_setup_cell(d.get("last_setup"))}</td>')
                    cells.append(f'<td>{_plan_cell(d.get("plan"))}</td>')
            parts.append(f'<tr>{"".join(cells)}</tr>')
    return "\n".join(parts)


def build_html(payload: dict) -> str:
    tfs = payload["timeframes"]
    fresh = payload["fresh"]
    armed = payload.get("armed", [])
    strat = payload["strategy"]

    if armed:
        armed_html = '<div class="cards">' + "".join(_plan_card(p) for p in armed) + "</div>"
    else:
        armed_html = '<p class="muted empty">Żaden instrument nie jest teraz uzbrojony ani w strefie retestu. Pełny stan i poziomy — w tabeli niżej (kolumna „plan").</p>'

    if fresh:
        fresh_html = '<div class="cards">' + "".join(_fresh_card(f) for f in fresh) + "</div>"
    else:
        fresh_html = '<p class="muted empty">Brak świeżych setupów AAA/AA+ w oknie skanu. Poniżej pełny stan trendów.</p>'

    tf_head = "".join(
        f'<th>{tf.upper()} trend</th><th>{tf.upper()} setup</th><th>{tf.upper()} plan (wejście @)</th>' for tf in tfs
    )

    return f"""<!DOCTYPE html>
<html lang="pl">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<meta http-equiv="refresh" content="900">
<title>HTS Premarket Scanner</title>
<style>
  :root {{
    --bg:#0d1117; --panel:#161b22; --panel2:#1c2230; --line:#2b3444;
    --txt:#e6edf3; --muted:#8b98a8; --up:#2dd4a7; --down:#f76d6d; --accent:#6ea8fe;
  }}
  * {{ box-sizing:border-box; }}
  body {{ margin:0; background:var(--bg); color:var(--txt);
    font:15px/1.5 -apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,Helvetica,Arial,sans-serif; }}
  .wrap {{ max-width:1100px; margin:0 auto; padding:24px 18px 60px; }}
  header h1 {{ margin:0 0 4px; font-size:24px; letter-spacing:.2px; }}
  header .sub {{ color:var(--muted); font-size:13.5px; }}
  header .sub b {{ color:var(--accent); }}
  h2 {{ font-size:14px; text-transform:uppercase; letter-spacing:1px; color:var(--muted);
    margin:34px 0 12px; border-bottom:1px solid var(--line); padding-bottom:8px; }}
  .cards {{ display:grid; grid-template-columns:repeat(auto-fill,minmax(190px,1fr)); gap:12px; }}
  .card {{ background:var(--panel); border:1px solid var(--line); border-left-width:4px;
    border-radius:10px; padding:12px 13px; }}
  .card.up {{ border-left-color:var(--up); }}
  .card.down {{ border-left-color:var(--down); }}
  .card-top {{ display:flex; justify-content:space-between; align-items:center; }}
  .card .tick {{ font-weight:700; font-size:16px; }}
  .card .tf {{ font-size:11px; color:var(--muted); background:var(--panel2);
    padding:2px 7px; border-radius:20px; }}
  .card-sig {{ font-weight:700; margin:8px 0 2px; font-size:15px; }}
  .card.up .card-sig {{ color:var(--up); }}
  .card.down .card-sig {{ color:var(--down); }}
  .card-name {{ color:var(--muted); font-size:12.5px; }}
  .card-meta {{ display:flex; flex-wrap:wrap; gap:4px 12px; margin-top:8px;
    font-size:12px; color:var(--muted); align-items:center; }}
  .plan-grid {{ display:grid; grid-template-columns:auto 1fr; gap:3px 10px; margin-top:9px;
    font-size:12.5px; }}
  .plan-grid .pl-k {{ color:var(--muted); }}
  .plan-grid .pl-v {{ font-weight:600; font-variant-numeric:tabular-nums; }}
  .plan-grid .pl-v.hot {{ color:var(--accent); }}
  .plan-grid .pl-v.cold {{ color:var(--muted); }}
  .tf-tag {{ font-size:10px; font-weight:700; padding:1px 5px; border-radius:4px;
    background:var(--panel2); color:var(--muted); letter-spacing:.4px; vertical-align:middle; }}
  .stat {{ font-weight:700; font-size:11px; padding:2px 8px; border-radius:20px;
    letter-spacing:.4px; }}
  .stat-in_zone {{ background:rgba(45,212,167,.18); color:var(--up); }}
  .stat-armed {{ background:rgba(110,168,254,.18); color:var(--accent); }}
  .stat-needs_breath {{ background:var(--panel2); color:var(--muted); }}
  .stat-deep {{ background:rgba(247,109,109,.16); color:var(--down); }}
  .ptag {{ font-size:10.5px; font-weight:700; padding:1px 6px; border-radius:5px; letter-spacing:.3px;
    text-transform:uppercase; vertical-align:middle; }}
  .ptag.t-zone {{ background:rgba(45,212,167,.18); color:var(--up); }}
  .ptag.t-armed {{ background:rgba(110,168,254,.18); color:var(--accent); }}
  .ptag.t-deep {{ background:rgba(247,109,109,.16); color:var(--down); }}
  .ptag.t-wait {{ background:var(--panel2); color:var(--muted); }}
  .empty {{ padding:14px; background:var(--panel); border-radius:10px; }}
  .tbl-scroll {{ overflow-x:auto; border:1px solid var(--line); border-radius:10px; }}
  table {{ width:100%; border-collapse:collapse; font-size:13.5px; min-width:640px; }}
  th, td {{ text-align:left; padding:9px 12px; border-bottom:1px solid var(--line); white-space:nowrap; }}
  thead th {{ background:var(--panel2); color:var(--muted); font-weight:600; font-size:12px;
    text-transform:uppercase; letter-spacing:.5px; position:sticky; top:0; }}
  tbody tr:hover {{ background:var(--panel); }}
  tr.grp td {{ background:var(--panel); color:var(--accent); font-weight:700; font-size:12px;
    text-transform:uppercase; letter-spacing:1px; }}
  td.tick {{ font-weight:700; }}
  td.nm {{ color:var(--muted); }}
  .ftmo {{ color:var(--accent); font-size:11.5px; font-weight:600; opacity:.85; }}
  .badge {{ font-weight:700; font-size:11.5px; padding:2px 9px; border-radius:20px;
    background:var(--panel2); }}
  .badge.up {{ color:var(--up); }}
  .badge.down {{ color:var(--down); }}
  .badge.flat {{ color:var(--muted); }}
  .setup {{ font-weight:700; }}
  .setup.up {{ color:var(--up); }}
  .setup.down {{ color:var(--down); }}
  .setup.fresh {{ background:rgba(110,168,254,.16); padding:1px 6px; border-radius:5px; }}
  .age {{ color:var(--muted); font-size:12px; }}
  .muted {{ color:var(--muted); }}
  footer {{ margin-top:36px; color:var(--muted); font-size:12.5px; line-height:1.7; }}
  footer code {{ background:var(--panel2); padding:1px 6px; border-radius:4px; color:var(--txt); }}
</style>
</head>
<body>
<div class="wrap">
  <header>
    <h1>HTS Premarket Scanner</h1>
    <div class="sub">
      Wygenerowano <b>{_esc(payload['generated_utc'])} UTC</b> · {_esc(payload['session_hint'])} ·
      {_esc(payload['universe_count'])} instrumentów (uniwersum vtrade) · logika HTS Swing Pro Filter 3.0 (AAA/AA+)
    </div>
  </header>

  <h2>Plan wejścia — gdzie szukać wejść teraz</h2>
  {armed_html}

  <h2>Świeże setupy — co już strzeliło</h2>
  {fresh_html}

  <h2>Pełny stan trendów, setupy i poziomy wejścia</h2>
  <div class="tbl-scroll">
  <table>
    <thead><tr><th>Ticker</th><th>Instrument</th>{tf_head}</tr></thead>
    <tbody>
    {_rows(payload['instruments'], tfs)}
    </tbody>
  </table>
  </div>

  <footer>
    <p><b>Jak czytać.</b> <span class="badge up">LONG</span>/<span class="badge down">SHORT</span> = bieżący
    stan wstęg SMA{_esc(strat['fast_ma'])}/SMA{_esc(strat['slow_ma'])} na zamkniętej świecy.
    <b>AAA</b> = pierwszy retest po crossie, <b>AA+</b> = dokładka. Sufiks
    <b>*</b> = trend umiarkowany (ADX 20–25), <b>!</b> = wyczerpany (ADX ≥40). „Świeży" = setup na
    ostatnich {_esc(payload.get('fresh_bars', 2) + 1)} zamkniętych świecach.</p>
    <p><b>Plan wejścia.</b> <b>wejście @</b> = linia retestu = krawędź szybkiej wstęgi (SMA{_esc(strat['fast_ma'])})
    od strony, z której wraca cena — tu strategia szuka wejścia. <b>strefa</b> = cała szybka wstęga
    (dotyk wystarczy). <b>stop za</b> = wolna wstęga (SMA{_esc(strat['slow_ma'])}); przebicie = zagrożenie odwrócenia trendu.
    Status: <span class="stat stat-in_zone">W STREFIE</span> cena już na wstędze (patrz na reakcję) ·
    <span class="stat stat-armed">UZBROJONY</span> zrobiła oddech, czeka na powrót do linii ·
    <span class="stat stat-needs_breath">BRAK ODDECHU</span> najpierw musi wybić dalej od wstęgi.
    <b>cofka %</b> = ile cena musi wrócić do linii wejścia. To poziomy do OBSERWACJI, nie automatyczne zlecenia.</p>
    <p><b>Uwaga o danych.</b> Źródło: yfinance (chmurowo). D1 = pewne; H4 składane z 1h (resample) —
    kotwica sesji może różnić się od brokera/TV, traktuj jako pomocnicze. To <b>nie</b> są sygnały regime
    v-tradera (Departure/RT/Cross) — to Twoja własna logika HTS Swing na koszyku instrumentów vtrade.</p>
    <p>Params: <code>SMA {_esc(strat['fast_ma'])}/{_esc(strat['slow_ma'])}</code> ·
    <code>dist {_esc(strat['dist_pct'])}%</code> · <code>band_gap {_esc(strat['min_band_gap_pct'])}%</code> ·
    <code>ADX {_esc(strat['adx_threshold_weak'])}/{_esc(strat['adx_threshold_moderate'])}/{_esc(strat['adx_threshold_strong'])}</code>.
    Odświeżanie strony co 15 min · dane z GitHub Action 2×/dobę (przed EU i US).</p>
  </footer>
</div>
</body>
</html>
"""
