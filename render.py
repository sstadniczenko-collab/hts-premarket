"""Render dashboardu HTML dla HTS Premarket Scanner (self-contained, dark)."""
from __future__ import annotations

import html
import re


def _esc(s) -> str:
    return html.escape(str(s), quote=True)


def _dir_arrow(direction: str) -> str:
    return "▲" if direction == "long" else "▼"


def _data_src_line(payload: dict) -> str:
    if payload.get("data_primary") == "ctrader":
        ts = payload.get("bars_generated") or "?"
        # numer konta z bars.json 'source' (np. "...acct 1114771") — nie hardcode
        m = re.search(r"acct\s+(\d+)", payload.get("bars_source") or "")
        acct = f" (konto {m.group(1)})" if m else ""
        return (f'Poziomy: <b class="src-ct">realny feed cTrader</b>{acct} · '
                f'snapshot {_esc(ts)} UTC · fallback yfinance dla braków')
    return 'Poziomy: <b class="src-yf">yfinance</b> (poglądowe — brak snapshotu cTrader; ≠ feed brokera)'


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
      {_daily_block(p.get('daily'))}
      {_news_block(p.get('news'))}
      {_macro_block(p.get('macro'))}
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


def _gap_txt(gap: dict | None) -> str:
    """Zwięzły opis gapu: kierunek, %, wypełnienie, flaga gap-over-gap."""
    if not gap or not gap.get("last"):
        return '<span class="muted">brak luki</span>'
    g = gap["last"]
    arrow = "↑" if g["dir"] == "up" else "↓"
    fill = "wypełniona" if g["filled"] else "OTWARTA"
    fcls = "" if g["filled"] else "gap-open"
    out = f'<span class="{fcls}">luka {arrow} {g["pct"]:.2f}% {fill}</span>'
    if gap.get("gap_over_gap") and gap.get("magnet"):
        m = gap["magnet"]
        out += f' <span class="gog" title="Gap-over-gap: otwarcie ponad starą niewypełnioną luką — magnes {_esc(m["bottom"])}–{_esc(m["top"])}">GoG magnes {_esc(m["bottom"])}–{_esc(m["top"])}</span>'
    return out


def _pivot_txt(piv: dict | None) -> str:
    if not piv:
        return '<span class="muted">—</span>'
    bcls = "up" if piv["bias"] == "byczy" else "down"
    parts = [f'<span class="badge {bcls}">P {_esc(piv["P"])}</span> <span class="age">strefa {_esc(piv["zone"])}</span>']
    if piv.get("res"):
        parts.append(f'<span class="age">opór {_esc(piv["res"]["name"])} {_esc(piv["res"]["val"])} (+{piv["res"]["dist_pct"]:.2f}%)</span>')
    if piv.get("sup"):
        parts.append(f'<span class="age">wsparcie {_esc(piv["sup"]["name"])} {_esc(piv["sup"]["val"])} (−{piv["sup"]["dist_pct"]:.2f}%)</span>')
    return " ".join(parts)


def _daily_cell(daily: dict | None) -> str:
    if not daily:
        return '<span class="muted">—</span>'
    piv = daily.get("pivot")
    gap = daily.get("gap")
    bits = []
    if piv:
        bcls = "up" if piv["bias"] == "byczy" else "down"
        bits.append(f'<span class="badge {bcls}">P {_esc(piv["P"])}</span> <span class="age">{_esc(piv["zone"])}</span>')
    bits.append(_gap_txt(gap))
    return "<br>".join(bits)


def _daily_block(daily: dict | None) -> str:
    """Blok pivot+gap na karcie planu."""
    if not daily:
        return ""
    piv = daily.get("pivot")
    gap = daily.get("gap")
    rows = []
    if piv:
        rows.append(f'<span class="pl-k">pivot D1</span><span class="pl-v">{_pivot_txt(piv)}</span>')
    rows.append(f'<span class="pl-k">gap D1</span><span class="pl-v">{_gap_txt(gap)}</span>')
    return f'<div class="plan-grid daily">{"".join(rows)}</div>'


_NEWS_BIAS_CLS = {"byczy": "nb-up", "niedźwiedzi": "nb-down",
                  "neutralny": "nb-flat", "obustronne ryzyko": "nb-warn"}


def _news_chip(news: dict | None) -> str:
    """Kompaktowy chip: bias + siła, z notką w title."""
    if not news or news.get("error"):
        return '<span class="muted">—</span>'
    bias = news.get("bias", "neutralny")
    cls = _NEWS_BIAS_CLS.get(bias, "nb-flat")
    tip = f'{news.get("catalyst","")} · {news.get("note","")}'.strip(" ·")
    return (f'<span class="nbias {cls}" title="{_esc(tip)}">{_esc(bias)}</span>'
            f' <span class="age">{_esc(news.get("strength",""))}</span>')


def _news_block(news: dict | None) -> str:
    """Pełna notka newsowa na karcie planu."""
    if not news or news.get("error"):
        return ""
    bias = news.get("bias", "neutralny")
    cls = _NEWS_BIAS_CLS.get(bias, "nb-flat")
    cat = news.get("catalyst", "")
    note = news.get("note", "")
    return (f'<div class="news-block">'
            f'<span class="nbias {cls}">news: {_esc(bias)}</span> '
            f'<span class="age">{_esc(news.get("strength",""))}</span>'
            + (f' <b>{_esc(cat)}</b>' if cat else "")
            + (f'<div class="news-note">{_esc(note)}</div>' if note else "")
            + '</div>')


# --- warstwa makro: cztery kolory, cztery znaczenia, nic wiecej ------------
_MACRO_VERDICT = {
    "up":       ("🟢", "▲ SPRZYJA GÓRZE", "var(--up)",
                 "long: pełny rozmiar · short: mniejszy, szybciej realizuj"),
    "down":     ("🔴", "▼ SPRZYJA DOŁOWI", "var(--down)",
                 "short: pełny rozmiar · long: mniejszy, szybciej realizuj"),
    "conflict": ("🟡", "⇄ SPRZECZNE", "#d4a72d",
                 "mniejszy rozmiar w obie strony"),
    "none":     ("⚪", "— MILCZY", "var(--muted)",
                 "graj jak zwykle — makro nie ma zdania"),
}


def _macro_reason(m: dict) -> str:
    """Krotkie 'dlaczego' + ocena dowodu. Dla milczacych: powod milczenia."""
    drv = m.get("drivers") or []
    voting = [d for d in drv if d.get("lean") in ("up", "down")]
    if voting:
        why = " · ".join(sorted({d.get("basis", "") for d in voting if d.get("basis")}))
        return _esc(f"{why} · dowód {m.get('confidence', '')}")
    susp = [d for d in drv if d.get("status") == "SUSPENDED"]
    if susp:
        return _esc(susp[0].get("basis", "sterownik zawieszony"))
    # sterownik odczytany, ale bez wychylenia — to NIE jest "brak danych"
    _read = ("SUSPENDED", "NOT_AUTOMATED", "MANUAL")
    flat = [d for d in drv if d.get("lean") in ("neutral", "none")
            and d.get("basis") and d.get("status") not in _read]
    if flat:
        return _esc(" · ".join(sorted({d["basis"] for d in flat})[:2]))
    cov = m.get("coverage")
    if cov == "STUB":
        return "brak badań dla tego rynku"
    if cov == "INPUT":
        return "to jest wejście dla innych rynków, nie cel"
    notauto = [d for d in drv if d.get("status") == "NOT_AUTOMATED"]
    if notauto:
        return "sterowniki wymagają odczytu ręcznego / kalendarza"
    return "brak danych"


def _macro_verdict_row(inst: dict) -> str:
    m = inst.get("macro") or {}
    dot, label, colour, action = _MACRO_VERDICT.get(m.get("lean", "none"),
                                                    _MACRO_VERDICT["none"])
    return (
        f'<tr style="border-top:1px solid var(--line);">'
        f'<td style="padding:6px 10px 6px 0;white-space:nowrap;">{dot} '
        f'<b>{_esc(inst["asset"])}</b> <span class="muted">{_esc(inst["name"])}</span></td>'
        f'<td style="padding:6px 10px 6px 0;color:{colour};white-space:nowrap;">'
        f'<b>{_esc(label)}</b></td>'
        f'<td style="padding:6px 10px 6px 0;" class="muted">{_macro_reason(m)}</td>'
        f'<td style="padding:6px 0;white-space:nowrap;">{_esc(action)}</td></tr>'
    )


def _macro_block(m: dict | None) -> str:
    """Werdykt makro wewnatrz karty setupu — wyraznie oddzielony od ENTRY/STOP."""
    if not m:
        return ""
    dot, label, colour, action = _MACRO_VERDICT.get(m.get("lean", "none"),
                                                    _MACRO_VERDICT["none"])
    return (
        f'<div style="margin-top:8px;padding-top:7px;border-top:1px dashed var(--line);'
        f'font-size:12px;">'
        f'<span class="muted">makro:</span> {dot} <b style="color:{colour};">{_esc(label)}</b>'
        f'<div class="muted" style="font-size:11px;margin-top:3px;">{_esc(action)}</div>'
        f'<div class="muted" style="font-size:10px;opacity:.7;margin-top:2px;">'
        f'nie zmienia wejścia — zmienia rozmiar i trzymanie</div></div>'
    )


def _macro_strip(payload: dict) -> str:
    """
    Panel makro — warstwa fundamentalna (nie z ceny i wolumenu).

    Naglowek sesji nad tabelami: jeden globalny nastroj + werdykt per rynek.
    Rynki milczace zwiniete — to, ze 21 milczy, jest samo w sobie informacja.
    """
    m = payload.get("macro")
    if not m:
        return ""

    risk = m.get("risk") or {}
    r_lab = {"RISK_ON": ("🟢", "RISK-ON", "var(--up)"),
             "RISK_OFF": ("🔴", "RISK-OFF", "var(--down)"),
             "MIXED": ("🟡", "MIESZANY", "#d4a72d"),
             "UNKNOWN": ("⚪", "NIEZNANY", "var(--muted)")}
    r_dot, r_txt, r_col = r_lab.get(risk.get("label", "UNKNOWN"), r_lab["UNKNOWN"])
    why = " · ".join(risk.get("why") or []) or "brak sygnałów"
    conf = risk.get("confidence", "")
    missing = ('<div style="color:#d4a72d;font-size:12px;margin-top:5px;">'
               '⚠ stres kredytowy: BRAK DANYCH — to najmocniejszy sygnał tła, '
               'dziś ciemny (patrz MACRO.md §5)</div>') if risk.get("missing_credit") else ""

    insts = payload.get("instruments") or []
    speaking = [i for i in insts if (i.get("macro") or {}).get("lean") in ("up", "down", "conflict")]
    loud = {i.get("asset") for i in speaking}
    # milczace, ale z powodem wartym pokazania (np. zloto: link zlamany)
    silent = [i for i in insts if i.get("asset") not in loud and i.get("macro")]

    rows = "".join(_macro_verdict_row(i) for i in speaking)
    if not rows:
        rows = ('<tr><td colspan="4" class="muted" style="padding:8px 0;">'
                'Dziś makro nie ma zdania o żadnym rynku — graj setupy jak zwykle.</td></tr>')
    silent_rows = "".join(_macro_verdict_row(i) for i in silent)

    return f"""
  <div style="margin:16px 0 10px;padding:12px 14px;border:1px solid var(--line);
              border-radius:10px;background:var(--panel);">
    <div style="display:flex;align-items:baseline;gap:10px;flex-wrap:wrap;">
      <div style="font-size:14px;"><b>🌍 KONTEKST MAKRO</b>
        <span class="muted" style="font-size:12px;">fundament, nie cena</span></div>
      <div style="margin-left:auto;font-size:18px;color:{r_col};">
        {r_dot} <b>{_esc(r_txt)}</b>
        <span class="muted" style="font-size:12px;">odczyt {_esc(conf)}</span></div>
    </div>
    <div class="muted" style="font-size:12px;margin-top:4px;">{_esc(why)}</div>
    {missing}

    <table style="width:100%;border-collapse:collapse;font-size:13px;margin-top:12px;">
      <thead><tr class="muted" style="font-size:11px;text-align:left;">
        <th style="padding-bottom:4px;">RYNEK</th><th>MAKRO MÓWI</th>
        <th>DLACZEGO</th><th>CO Z TYM ZROBIĆ</th></tr></thead>
      <tbody>{rows}</tbody>
    </table>

    <details style="margin-top:10px;">
      <summary class="muted" style="cursor:pointer;font-size:12px;">
        ⚪ pozostałe {len(silent)} rynków — makro milczy (rozwiń)</summary>
      <table style="width:100%;border-collapse:collapse;font-size:13px;margin-top:6px;">
        <tbody>{silent_rows}</tbody></table>
    </details>

    <details style="margin-top:8px;">
      <summary class="muted" style="cursor:pointer;font-size:12px;">co to znaczy? (legenda)</summary>
      <div class="muted" style="font-size:12px;margin-top:6px;line-height:1.7;">
        🟢 <b>SPRZYJA GÓRZE</b> — fundament wspiera stronę long.<br>
        🔴 <b>SPRZYJA DOŁOWI</b> — fundament wspiera stronę short.<br>
        🟡 <b>SPRZECZNE</b> — sterowniki idą przeciw sobie; mniejszy rozmiar w obie strony.<br>
        ⚪ <b>MILCZY</b> — brak danych albo brak badań dla tego rynku. Graj jak zwykle.<br><br>
        <b>Ta warstwa nigdy nie mówi „wchodź" ani „nie graj".</b> Mówi, co wybrać,
        ile wziąć i jak długo trzymać. Wejścia zostają w logice HTS.
        Może tylko <b>odejmować</b> (mniejszy rozmiar, szybsza realizacja) — nigdy
        blokować setupu: weto z nieudowodnionej warstwy kasuje realnych wygranych.<br><br>
        <b>dowód mocny / praktyczny / słaby</b> = siła dowodu naukowego za danym
        sterownikiem, nie pewność co do dzisiejszej sesji.
        Źródła i pełne zasady: <b>MACRO.md</b> (18 sterowników, 57 źródeł pierwotnych).
      </div>
    </details>
  </div>"""


def _capit_gaps(gaps: list | None) -> str:
    if not gaps:
        return '<span class="muted">brak</span>'
    bits = [f'<span class="gap-open">{_esc(g["bottom"])}–{_esc(g["top"])}</span> '
            f'<span class="age">({g["dist_pct"]:+.1f}%)</span>' for g in gaps]
    return "<br>".join(bits)


def _capit_row(r: dict) -> str:
    if r["event"]:
        badge = '<span class="cap-ev">EVENT</span>'
        if r.get("clustered"):
            badge += ' <span class="ptag t-wait" title="Poprzedni event ≤2 dni temu — wg playbooka pomijamy">klaster</span>'
        levels = (f'wejście @ <b>{_esc(r["entry"])}</b> (close) · SL <b>{_esc(r["sl"])}</b> '
                  f'({_esc(r["risk_pct"])}% risk) · max {_esc(r["hold_days"])} sesje')
        if r.get("gap_fill"):
            levels += ' <span class="gog" title="Flush nakrył starą niedomkniętą lukę. Backtest NQ 2y: takie eventy były GORSZE (n=6, avg -1 041 USD vs +1 004 bez) — częściej kontynuacja trendu niż wyczerpanie paniki.">⚠ gap-fill</span>'
    elif r.get("near"):
        badge = '<span class="cap-near">blisko</span>'
        levels = '<span class="muted">—</span>'
    else:
        badge = '<span class="muted">spokój</span>'
        levels = '<span class="muted">—</span>'
    dcls = "down" if r["drop_pct"] <= -1.5 else ""
    return (f'<tr><td class="tick">{_esc(r["asset"])}</td><td class="nm">{_nm(r["name"], r.get("ftmo"))}</td>'
            f'<td><span class="setup {dcls}">{r["drop_pct"]:+.2f}%</span></td>'
            f'<td>{badge}</td><td class="dcell">{levels}</td>'
            f'<td class="dcell">{_capit_gaps(r.get("gaps_below"))}</td></tr>')


def _capitulation_section(payload: dict) -> str:
    cap = payload.get("capitulation")
    if not cap or not cap.get("rows"):
        return ""
    p = cap["params"]
    h = cap.get("headline")
    if h and h["event"]:
        head_html = (
            f'<div class="cap-head cap-head-ev">🔴 <b>NQ: DZIEŃ KAPITULACJI</b> — sesja {_esc(h["session"])}, '
            f'spadek intraday {h["drop_pct"]:+.2f}% (Low {_esc(h["low"])} vs prev close {_esc(h["prev_close"])}). '
            f'Playbook: long @ close {_esc(h["entry"])}, SL {_esc(h["sl"])}, max {_esc(h["hold_days"])} sesje. '
            f'<b>Decyzja człowieka: kapitulacja czy początek bessy?</b> (powód spadku / VIX / kalendarz makro)</div>')
    elif h:
        head_html = (
            f'<div class="cap-head">🟢 NQ: ostatnia zamknięta sesja {_esc(h["session"])} — max spadek intraday '
            f'<b>{h["drop_pct"]:+.2f}%</b> (próg {_esc(p["drop_pct"])}%). Brak eventu — czekamy.</div>')
    else:
        head_html = ""
    return f"""
  <h2>Detektor kapitulacji — playbook Darwinex (NQ)</h2>
  {head_html}
  <div class="tbl-scroll">
  <table>
    <thead><tr><th>Ticker</th><th>Instrument</th><th>spadek intraday</th><th>status</th>
    <th>poziomy playbooka</th><th>niedomknięte gapy pod ceną</th></tr></thead>
    <tbody>
    {"".join(_capit_row(r) for r in cap["rows"])}
    </tbody>
  </table>
  </div>
  <p class="muted capnote">EVENT = Low sesji ≤ poprzednie close −{abs(p['drop_pct'])}%. Zagranie (walidowane
  <b>tylko na NQ</b>, 2024–2026): long na close dnia eventowego, SL pod dołkiem −{_esc(p['sl_buf_pct'])}%,
  trzymanie max {_esc(p['hold_days'])} sesje; event ≤{_esc(p['decluster_d'])} dni po poprzednim pomijamy (klaster).
  Skan biega premarket, więc ocenia <b>ostatnią zamkniętą sesję</b> — event widoczny rano oznacza, że wejście
  wypadało wczoraj na close; to karta decyzyjna, nie sygnał w czasie rzeczywistym. Filtr mechaniczny nie odróżnia
  kapitulacji od początku bessy — to decyzja człowieka. Gapy = niedomknięte luki wzrostowe (strefa pod ceną,
  ≥{_esc(p['gap_min_pct'])}%) jako mapa terenu; <span class="gog">⚠ gap-fill</span> przy evencie to flaga
  ostrożności (w backteście takie eventy były gorsze), nie filtr. Rok 2026 w backteście jest na minusie (chop) —
  sizing wg SL, na FTMO 100k max 1 micro (MNQ).</p>"""


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


def _rows(instruments: list[dict], timeframes: list[str], news_on: bool) -> str:
    # grupuj wg 'group'
    groups: dict[str, list[dict]] = {}
    for r in instruments:
        groups.setdefault(r.get("group") or "Inne", []).append(r)

    tf_cols = timeframes
    span = 3 + 3 * len(tf_cols) + (1 if news_on else 0)
    parts = []
    for gname, items in groups.items():
        parts.append(f'<tr class="grp"><td colspan="{span}">{_esc(gname)}</td></tr>')
        for r in items:
            src_mark = ''
            if r.get("src") in ("yfinance", "mieszane"):
                src_mark = f' <span class="srcmark" title="Źródło danych: {_esc(r.get("src"))} (nie feed cTrader)">yf</span>'
            cells = [f'<td class="tick">{_esc(r["asset"])}{src_mark}</td><td class="nm">{_nm(r["name"], r.get("ftmo"))}</td>']
            for tf in tf_cols:
                d = r["tf"].get(tf, {})
                if not d.get("ok"):
                    cells.append(f'<td class="muted">{_esc(d.get("reason","—"))}</td><td class="muted">—</td><td class="muted">—</td>')
                else:
                    cells.append(f'<td>{_trend_badge(d["trend"])}</td>')
                    cells.append(f'<td>{_setup_cell(d.get("last_setup"))}</td>')
                    cells.append(f'<td>{_plan_cell(d.get("plan"))}</td>')
            cells.append(f'<td class="dcell">{_daily_cell(r.get("daily"))}</td>')
            if news_on:
                cells.append(f'<td class="ncell">{_news_chip(r.get("news"))}</td>')
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

    news_on = bool(payload.get("news_enabled"))
    tf_head = "".join(
        f'<th>{tf.upper()} trend</th><th>{tf.upper()} setup</th><th>{tf.upper()} plan (wejście @)</th>' for tf in tfs
    ) + '<th>D1 kontekst (pivot / gap)</th>' + ('<th>News (AI)</th>' if news_on else '')

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
  header .src-line {{ margin-top:3px; font-size:12.5px; }}
  .src-ct {{ color:var(--up); }}
  .src-yf {{ color:#f0b450; }}
  .srcmark {{ font-size:9.5px; font-weight:700; color:#f0b450; background:rgba(240,180,80,.14);
    padding:0 4px; border-radius:3px; vertical-align:super; }}
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
  .plan-grid.daily {{ margin-top:9px; padding-top:9px; border-top:1px dashed var(--line); }}
  .gap-open {{ color:var(--accent); font-weight:600; }}
  .gog {{ background:rgba(247,109,109,.16); color:var(--down); font-weight:700; font-size:11px;
    padding:1px 6px; border-radius:5px; }}
  td.dcell {{ font-size:12px; line-height:1.7; white-space:normal; min-width:210px; }}
  td.ncell {{ font-size:12px; white-space:normal; min-width:120px; }}
  .nbias {{ font-weight:700; font-size:11px; padding:1px 7px; border-radius:20px; letter-spacing:.3px; }}
  .nbias.nb-up {{ background:rgba(45,212,167,.18); color:var(--up); }}
  .nbias.nb-down {{ background:rgba(247,109,109,.16); color:var(--down); }}
  .nbias.nb-flat {{ background:var(--panel2); color:var(--muted); }}
  .nbias.nb-warn {{ background:rgba(240,180,80,.18); color:#f0b450; }}
  .news-block {{ margin-top:9px; padding-top:9px; border-top:1px dashed var(--line); font-size:12.5px; }}
  .news-note {{ color:var(--muted); margin-top:4px; }}
  .empty {{ padding:14px; background:var(--panel); border-radius:10px; }}
  .cap-head {{ padding:12px 14px; background:var(--panel); border:1px solid var(--line);
    border-radius:10px; margin-bottom:14px; font-size:13.5px; }}
  .cap-head-ev {{ border-color:var(--down); background:rgba(247,109,109,.08); }}
  .cap-ev {{ font-weight:700; font-size:11px; padding:2px 8px; border-radius:20px;
    background:rgba(247,109,109,.2); color:var(--down); letter-spacing:.4px; }}
  .cap-near {{ font-weight:700; font-size:11px; padding:2px 8px; border-radius:20px;
    background:rgba(240,180,80,.18); color:#f0b450; letter-spacing:.4px; }}
  .capnote {{ font-size:12.5px; line-height:1.7; margin-top:12px; }}
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
    <div class="sub src-line">{_data_src_line(payload)}</div>
  </header>

  {_macro_strip(payload)}

  <h2>Plan wejścia — gdzie szukać wejść teraz</h2>
  {armed_html}

  <h2>Świeże setupy — co już strzeliło</h2>
  {fresh_html}

  <h2>Pełny stan trendów, setupy i poziomy wejścia</h2>
  <div class="tbl-scroll">
  <table>
    <thead><tr><th>Ticker</th><th>Instrument</th>{tf_head}</tr></thead>
    <tbody>
    {_rows(payload['instruments'], tfs, news_on)}
    </tbody>
  </table>
  </div>

  {_capitulation_section(payload)}

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
    <p><b>Kontekst D1 (pivot / gap).</b> <b>Pivot</b> = klasyczny floor pivot z ostatniej zamkniętej
    świecy dziennej rzutowany na następną sesję (P, R1/R2, S1/S2); „strefa" = między którymi poziomami
    siedzi cena, <span class="badge up">byczy</span>/<span class="badge down">niedźwiedzi</span> = zamknięcie
    nad/pod P. <b>Gap</b> = luka otwarcia ostatniej sesji (kierunek, %, czy <span class="gap-open">OTWARTA</span>
    czy wypełniona). <span class="gog">GoG magnes</span> = gap-over-gap: otwarcie przeskoczyło starszą wciąż
    niewypełnioną lukę → podwójna niewypełniona strefa jako magnes (poziomy podane).</p>
    <p><b>News (AI).</b> Ocena <b>Claude Haiku</b> na świeżych nagłówkach z yfinance:
    <span class="nbias nb-up">byczy</span> / <span class="nbias nb-down">niedźwiedzi</span> /
    <span class="nbias nb-flat">neutralny</span> / <span class="nbias nb-warn">obustronne ryzyko</span>
    + siła (niski/średni/wysoki), katalizator i jedno zdanie „na co uważać" (najedź kursorem / karta planu).
    To <b>potencjalny</b> wpływ z nagłówków, nie prognoza — nagłówki bywają ogólnorynkowe, waż z kontekstem.</p>
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
