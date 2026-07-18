"""Render dashboardu HTML dla HTS Premarket Scanner (self-contained, dark)."""
from __future__ import annotations

import html


def _esc(s) -> str:
    return html.escape(str(s), quote=True)


def _dir_arrow(direction: str) -> str:
    return "▲" if direction == "long" else "▼"


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
      <div class="card-name">{_esc(f['name'])}</div>
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
        parts.append(f'<tr class="grp"><td colspan="{2 + 2*len(tf_cols)}">{_esc(gname)}</td></tr>')
        for r in items:
            cells = [f'<td class="tick">{_esc(r["asset"])}</td><td class="nm">{_esc(r["name"])}</td>']
            for tf in tf_cols:
                d = r["tf"].get(tf, {})
                if not d.get("ok"):
                    cells.append(f'<td class="muted">{_esc(d.get("reason","—"))}</td><td class="muted">—</td>')
                else:
                    cells.append(f'<td>{_trend_badge(d["trend"])}</td>')
                    cells.append(f'<td>{_setup_cell(d.get("last_setup"))}</td>')
            parts.append(f'<tr>{"".join(cells)}</tr>')
    return "\n".join(parts)


def build_html(payload: dict) -> str:
    tfs = payload["timeframes"]
    fresh = payload["fresh"]
    strat = payload["strategy"]

    if fresh:
        fresh_html = '<div class="cards">' + "".join(_fresh_card(f) for f in fresh) + "</div>"
    else:
        fresh_html = '<p class="muted empty">Brak świeżych setupów AAA/AA+ w oknie skanu. Poniżej pełny stan trendów.</p>'

    tf_head = "".join(
        f'<th>{tf.upper()} trend</th><th>{tf.upper()} setup</th>' for tf in tfs
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
    font-size:12px; color:var(--muted); }}
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

  <h2>Świeże setupy — premarket watchlist</h2>
  {fresh_html}

  <h2>Pełny stan trendów i ostatnie setupy</h2>
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
