"""
macro.py - fundamental (non-price) context layer for the HTS premarket scan.

Fills the macro slot that CLAUDE.md already asks for: "Macro backdrop in one
sentence (VIX, DXY, yields)" - but sourced from a graded driver contract
instead of improvised from charts.

Design rules (see MACRO.md):
  1. NOT an entry layer. Output is selection / sizing / hold context only.
     Entry levels stay in hts_logic.py and are never touched here.
  2. No API keys. FRED CSV and CFTC Socrata are keyless; Yahoo needs only a UA.
     Nothing here touches ANTHROPIC_API_KEY or any secret.
  3. Fail soft, always. Any network or parse failure degrades to a partial
     read. This module must never raise into scan.py.
  4. No composite score. Each driver reports separately and the contract's
     grade travels with it. Weighted blends are explicitly rejected (R7).
  5. Human-facing strings are Polish (every consumer in this repo is);
     driver IDs, grades and status codes stay English.

Stdlib only - no new entries in requirements.txt.
"""

from __future__ import annotations

import json
import math
import os
import ssl
import urllib.error
import urllib.request
from datetime import datetime, timezone

CONTRACT_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "macro_drivers.json")
STATE_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "macro_state.json")

_UA = "Mozilla/5.0 (compatible; hts-premarket/1.0)"
_TIMEOUT = 20
_CHANGE_WINDOW = 20      # trading days for a "recent change" read
_CORR_WINDOW = 60        # trading days for rolling correlations
_MOVE_EPS = 0.02         # 2% relative move = the floor for calling a direction

# Kazdy konsument w tym repo (brief.py, render.py) mowi po polsku — wiec ciagi
# 'basis' sa po polsku. Kody i ID sterownikow zostaja po angielsku.
_PL_DIR = {"up": "rośnie", "down": "spada", "flat": "płasko", "unknown": "brak danych"}
_PL_CREDIT = {"WIDENING": "rozszerzają się", "COMPRESSING": "zawężają się",
              "STABLE": "stabilne", "unknown": "brak danych"}
_PL_GATE = {"BROKEN": "ZŁAMANY", "ALIVE": "działa", "AMBIGUOUS": "niejednoznaczny", "unknown": "nieznany"}
_PL_WIN = {"OPEN": "OTWARTE", "CLOSED": "zamknięte"}
_PL_TS = {"CONTANGO": "contango (spokój)", "BACKWARDATION": "backwardation (stres)"}
_PL_CURVE = {"INVERTED": "odwrócona", "POSITIVE": "dodatnia"}
_PL_GRADE = {"strong": "mocny", "practitioner": "praktyczny", "weak": "słaby", "none": "—"}

# Source chain per logical series: tried in order, first success wins.
# kind: "fred" | "yahoo".  exact=True  -> same underlying series, 1:1 swap.
#                          exact=False -> a labelled SUBSTITUTE; provenance is
#                          reported so a substitute never reads as the real thing.
#
# FRED was verified working 2026-07-13 and was returning 403 / connection
# timeouts to automated clients on 2026-07-30. It is kept as primary because it
# is the correct source and may well work from other networks - run
# probe_fred() from the deploy environment to find out. Where no honest
# fallback exists the reading stays "unknown"; it is never faked from a proxy.
SOURCE_CHAIN: dict[str, list[dict]] = {
    "nom_10y":     [{"kind": "fred",  "code": "DGS10",        "exact": True},
                    {"kind": "yahoo", "code": "^TNX",         "exact": True}],
    "vix":         [{"kind": "fred",  "code": "VIXCLS",       "exact": True},
                    {"kind": "yahoo", "code": "^VIX",         "exact": True}],
    "usd_broad":   [{"kind": "fred",  "code": "DTWEXBGS",     "exact": True},
                    {"kind": "yahoo", "code": "DX-Y.NYB",     "exact": False,
                     "note": "DXY (6 currencies) substituting for the broad trade-weighted USD"}],
    "curve":       [{"kind": "fred",  "code": "T10Y2Y",       "exact": True},
                    {"kind": "yahoo", "code": "^TNX-^IRX",    "exact": False,
                     "note": "10Y minus 13-week bill (~T10Y3M) substituting for 2s10s"}],
    # No honest non-price fallback exists for these two. If FRED is unreachable
    # they stay dark rather than being proxied off an ETF price (which would
    # both violate the non-price rule and be a weaker instrument).
    "real_10y":    [{"kind": "fred",  "code": "DFII10",       "exact": True}],
    "hy_oas":      [{"kind": "fred",  "code": "BAMLH0A0HYM2", "exact": True}],
    "breakeven":   [{"kind": "fred",  "code": "T10YIE",       "exact": True}],
    # Yahoo-native from the start.
    "gold":        [{"kind": "yahoo", "code": "GC=F",         "exact": True}],
    "spx":         [{"kind": "yahoo", "code": "^GSPC",        "exact": True}],
    "usdjpy":      [{"kind": "yahoo", "code": "JPY=X",        "exact": True}],
    "eurusd":      [{"kind": "yahoo", "code": "EURUSD=X",     "exact": True}],
    "gbpusd":      [{"kind": "yahoo", "code": "GBPUSD=X",     "exact": True}],
    "vix_spot":    [{"kind": "yahoo", "code": "^VIX",         "exact": True}],
    "vix_3m":      [{"kind": "yahoo", "code": "^VIX3M",       "exact": True}],
}


# --------------------------------------------------------------------------
# plumbing
# --------------------------------------------------------------------------

def available() -> bool:
    """Mirrors news_ai.available(). No key needed - only the contract file."""
    return os.path.exists(CONTRACT_FILE)


def load_contract() -> dict:
    with open(CONTRACT_FILE, "r", encoding="utf-8") as fh:
        return json.load(fh)


def _get(url: str) -> str | None:
    """One GET. Returns None on any failure - callers degrade, never crash."""
    try:
        req = urllib.request.Request(url, headers={"User-Agent": _UA})
        ctx = ssl.create_default_context()
        with urllib.request.urlopen(req, timeout=_TIMEOUT, context=ctx) as resp:
            return resp.read().decode("utf-8", errors="replace")
    except (urllib.error.URLError, urllib.error.HTTPError, TimeoutError, OSError, ValueError):
        return None


def fetch_fred(series: str) -> list[tuple[str, float]]:
    """
    Keyless FRED CSV. The JSON API needs a key and 400s without one - do not
    switch to it. Returns [(date, value)] oldest first, missing values dropped.
    """
    raw = _get(f"https://fred.stlouisfed.org/graph/fredgraph.csv?id={series}")
    if not raw:
        return []
    out: list[tuple[str, float]] = []
    for line in raw.splitlines()[1:]:          # skip header (DATE or observation_date)
        parts = line.split(",")
        if len(parts) < 2:
            continue
        date, val = parts[0].strip(), parts[1].strip()
        if not val or val == ".":              # FRED marks gaps with a dot
            continue
        try:
            out.append((date, float(val)))
        except ValueError:
            continue
    return out


def fetch_yahoo_closes(ticker: str, rng: str = "6mo") -> list[float]:
    """Daily closes, oldest first. Same host data_yf.py already relies on."""
    url = (f"https://query1.finance.yahoo.com/v8/finance/chart/{ticker}"
           f"?interval=1d&range={rng}")
    raw = _get(url)
    if not raw:
        return []
    try:
        payload = json.loads(raw)
        quote = payload["chart"]["result"][0]["indicators"]["quote"][0]
        return [c for c in quote["close"] if c is not None]
    except (KeyError, IndexError, TypeError, ValueError):
        return []


def resolve_series(key: str) -> tuple[list[float], dict]:
    """
    Walk the source chain for one logical series. First success wins.

    Returns (values, provenance). Provenance always records WHICH source
    served the data and whether it was the exact series or a substitute, so a
    downstream reader can never mistake a stand-in for the real thing.
    """
    for step in SOURCE_CHAIN.get(key, []):
        code, kind = step["code"], step["kind"]
        vals: list[float] = []

        if kind == "fred":
            vals = [v for _, v in fetch_fred(code)]
        elif kind == "yahoo":
            if "-" in code and code.startswith("^"):        # a spread, e.g. ^TNX-^IRX
                a, b = code.split("-", 1)
                va, vb = fetch_yahoo_closes(a), fetch_yahoo_closes(b)
                n = min(len(va), len(vb))
                vals = [va[-n:][i] - vb[-n:][i] for i in range(n)] if n else []
            else:
                vals = fetch_yahoo_closes(code)

        if vals:
            return vals, {"source": f"{kind}:{code}",
                          "exact": step["exact"],
                          "note": step.get("note")}
    return [], {"source": None, "exact": None, "note": None}


def probe_fred() -> dict:
    """
    Deployment test. FRED was reachable on 2026-07-13 and was refusing
    automated clients on 2026-07-30 from at least one network. Run this ONCE
    from the environment that will actually execute the scan (GitHub Actions)
    to learn whether the primary source works there.

    If it fails, D4 (credit spreads) and D2's real-yield gate go dark - both
    are named in MACRO.md as having no honest non-price fallback.
    """
    obs = fetch_fred("DGS10")
    return {
        "reachable": bool(obs),
        "observations": len(obs),
        "last": obs[-1] if obs else None,
        "affected_if_down": ["D4 credit spreads", "D2 real-yield gate", "D7 breakeven"],
    }


# --------------------------------------------------------------------------
# small stats (stdlib only - no numpy/pandas dependency added)
# --------------------------------------------------------------------------

def _pct_change(vals: list[float], window: int) -> float | None:
    if len(vals) < window + 1:
        return None
    old, new = vals[-(window + 1)], vals[-1]
    if old == 0:
        return None
    return (new - old) / abs(old)


def _returns(vals: list[float]) -> list[float]:
    return [(vals[i] - vals[i - 1]) / vals[i - 1]
            for i in range(1, len(vals)) if vals[i - 1] != 0]


def _pearson(a: list[float], b: list[float]) -> float | None:
    n = min(len(a), len(b))
    if n < 20:
        return None
    a, b = a[-n:], b[-n:]
    ma, mb = sum(a) / n, sum(b) / n
    num = sum((a[i] - ma) * (b[i] - mb) for i in range(n))
    da = math.sqrt(sum((x - ma) ** 2 for x in a))
    db = math.sqrt(sum((x - mb) ** 2 for x in b))
    if da == 0 or db == 0:
        return None
    return num / (da * db)


def _direction(change: float | None, eps: float = _MOVE_EPS) -> str:
    if change is None:
        return "unknown"
    if change > eps:
        return "up"
    if change < -eps:
        return "down"
    return "flat"


# --------------------------------------------------------------------------
# STATE - the fast layer (see MACRO.md section 3)
# --------------------------------------------------------------------------

def compute_state() -> dict:
    """
    Recomputes every automatable state_check in the contract.

    This is the STATE layer. It never edits macro_drivers.json - the contract
    ships a research snapshot and this function reports what is true now.
    Anything that cannot be fetched comes back "unknown", never guessed.
    """
    state: dict = {
        "asof": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "readings": {},
        "regime": {},
        "failures": [],
    }
    r, fail = state["readings"], state["failures"]

    series: dict[str, list[float]] = {}
    for key in SOURCE_CHAIN:
        vals, prov = resolve_series(key)
        if not vals:
            fail.append(key)
            continue
        series[key] = vals
        chg = _pct_change(vals, _CHANGE_WINDOW)
        r[key] = {
            "source": prov["source"],
            "exact": prov["exact"],
            "last": round(vals[-1], 4),
            "chg_20d": chg,
            "dir_20d": _direction(chg),
        }
        if prov.get("note"):
            r[key]["substitute_note"] = prov["note"]

    # --- D2 regime gate: is the real-yield -> gold link alive or broken? ---
    # The flagship state check. The contract ships status BROKEN (2022-24) and
    # this is what would detect it reasserting. Never assume the textbook sign.
    corr_ry_gold = None
    if "real_10y" in series and "gold" in series:
        n = min(len(series["real_10y"]), len(series["gold"]), _CORR_WINDOW + 1)
        corr_ry_gold = _pearson(_returns(series["real_10y"][-n:]),
                                _returns(series["gold"][-n:]))
    if corr_ry_gold is None:
        state["regime"]["D2_real_yield_gold"] = "unknown"
    elif corr_ry_gold < -0.30:
        state["regime"]["D2_real_yield_gold"] = "ALIVE"       # sign reasserting
    elif corr_ry_gold > -0.10:
        state["regime"]["D2_real_yield_gold"] = "BROKEN"      # D11 governs
    else:
        state["regime"]["D2_real_yield_gold"] = "AMBIGUOUS"
    state["regime"]["D2_corr"] = None if corr_ry_gold is None else round(corr_ry_gold, 3)

    # --- D3 regime gate: is the safe-haven window actually open? -----------
    # Requires BOTH a negative gold-equity correlation AND elevated VIX.
    # Outside that, a standing gold-vs-equities inverse rule is wrong (R5).
    corr_gold_spx = None
    if "gold" in series and "spx" in series:
        n = min(len(series["gold"]), len(series["spx"]), _CORR_WINDOW + 1)
        corr_gold_spx = _pearson(_returns(series["gold"][-n:]),
                                 _returns(series["spx"][-n:]))
    vix_level = series.get("vix", [None])[-1] if series.get("vix") else None
    if corr_gold_spx is None or vix_level is None:
        state["regime"]["D3_safe_haven_window"] = "unknown"
    elif corr_gold_spx < -0.20 and vix_level >= 25:
        state["regime"]["D3_safe_haven_window"] = "OPEN"
    else:
        state["regime"]["D3_safe_haven_window"] = "CLOSED"
    state["regime"]["D3_corr"] = None if corr_gold_spx is None else round(corr_gold_spx, 3)

    # --- D18: VIX term structure (carry, NOT a VIX forecast) --------------
    if series.get("vix_spot") and series.get("vix_3m"):
        basis = series["vix_3m"][-1] - series["vix_spot"][-1]
        state["regime"]["D18_term_structure"] = "CONTANGO" if basis > 0 else "BACKWARDATION"
        state["regime"]["D18_basis"] = round(basis, 3)
    else:
        state["regime"]["D18_term_structure"] = "unknown"

    # --- D4: credit stress direction --------------------------------------
    if "hy_oas" in r:
        chg = r["hy_oas"]["chg_20d"]
        if chg is None:
            state["regime"]["D4_credit"] = "unknown"
        elif chg > 0.10:
            state["regime"]["D4_credit"] = "WIDENING"
        elif chg < -0.10:
            state["regime"]["D4_credit"] = "COMPRESSING"
        else:
            state["regime"]["D4_credit"] = "STABLE"
    else:
        state["regime"]["D4_credit"] = "unknown"

    # --- D5: curve. Reported, never voting, while contract status is BROKEN
    if "curve" in r:
        state["regime"]["D5_curve"] = "INVERTED" if r["curve"]["last"] < 0 else "POSITIVE"
        state["regime"]["D5_note"] = "context only - contract status BROKEN since 2022"

    state["coverage"] = {
        "fetched": len(r),
        "expected": len(SOURCE_CHAIN),
        "degraded": bool(fail),
        "substitutes": [k for k, v in r.items() if v.get("exact") is False],
    }
    return state


# --------------------------------------------------------------------------
# per-driver reads
# --------------------------------------------------------------------------

def _read_driver(driver: dict, state: dict) -> dict | None:
    """
    Turn one contract driver + live state into a single read.

    Returns a 'lean' only where the state actually supports one. A driver whose
    contract status is BROKEN, or whose regime gate is closed, reports itself
    as suspended rather than voting. No scoring, no weighting (R7).
    """
    did = driver["id"]
    r, regime = state["readings"], state["regime"]
    lean, basis = "none", None

    if did == "D4":
        c = regime.get("D4_credit")
        basis = f"spready HY: {_PL_CREDIT.get(c, c)}"
        lean = {"WIDENING": "down", "COMPRESSING": "up"}.get(c, "neutral")

    elif did == "D2":
        gate = regime.get("D2_real_yield_gold")
        if gate != "ALIVE":
            # Two different situations, and conflating them would be dishonest:
            # the gate measured a broken link, or the input was unreachable so
            # the gate could not be measured at all. Either way D2 does not
            # vote - but the reader is told which.
            if gate == "unknown":
                why = "brak danych o realnych rentownościach — nie da się zmierzyć; rządzi D11 (skup banków centralnych)"
            else:
                why = f"link realne rentowności→złoto: {_PL_GATE.get(gate, gate)} (korelacja {regime.get('D2_corr')}) — rządzi D11"
            return {"id": did, "name": driver["name"], "grade": driver["grade"],
                    "status": "SUSPENDED", "lean": "none", "basis": why,
                    "warning": driver.get("warning")}
        d = r.get("real_10y", {}).get("dir_20d")
        basis = f"realne rentowności 10Y {_PL_DIR.get(d, d)}"
        lean = {"up": "down", "down": "up"}.get(d, "neutral")

    elif did == "D11":
        return {"id": did, "name": driver["name"], "grade": driver["grade"],
                "status": "MANUAL", "lean": "none",
                "basis": "skup banków centralnych — odczyt kwartalny, ręczny (MACRO.md)",
                "warning": driver.get("warning")}

    elif did == "D1":
        d = r.get("usd_broad", {}).get("dir_20d")
        basis = f"dolar (szeroki) {_PL_DIR.get(d, d)}"
        lean = {"up": "down", "down": "up"}.get(d, "neutral")

    elif did == "D3":
        w = regime.get("D3_safe_haven_window")
        basis = f"okno safe-haven {_PL_WIN.get(w, w)} (korelacja złoto/S&P {regime.get('D3_corr')})"
        lean = "none"   # a state tag, never a direction - see R5

    elif did == "D6":
        d = r.get("nom_10y", {}).get("dir_20d")
        basis = f"rentowność 10Y {_PL_DIR.get(d, d)}"
        lean = {"up": "down", "down": "up"}.get(d, "neutral")

    elif did == "D15":
        d = r.get("usdjpy", {}).get("dir_20d")
        basis = f"USD/JPY {_PL_DIR.get(d, d)}"
        lean = {"up": "up", "down": "down"}.get(d, "neutral")   # weak yen lifts Nikkei

    elif did == "D14":
        d = r.get("eurusd", {}).get("dir_20d")
        basis = f"EUR/USD {_PL_DIR.get(d, d)}"
        lean = {"down": "up", "up": "down"}.get(d, "neutral")   # weak euro lifts exporters

    elif did == "D16":
        d = r.get("gbpusd", {}).get("dir_20d")
        basis = f"GBP/USD {_PL_DIR.get(d, d)} (znak niestabilny — nie głosuje)"
        lean = "neutral"   # sign is unstable (Brexit flip) - reported, never votes

    elif did == "D18":
        ts = regime.get("D18_term_structure")
        basis = f"struktura terminowa zmienności: {_PL_TS.get(ts, ts)}"
        lean = "none"      # carry, not direction

    elif did == "D5":
        basis = f"krzywa {_PL_CURVE.get(regime.get('D5_curve'), '—')} (sygnał zawieszony od 2022)"
        return {"id": did, "name": driver["name"], "grade": driver["grade"],
                "status": "SUSPENDED", "lean": "none", "basis": basis,
                "warning": driver.get("warning")}

    else:
        # D7 D9 D12 D13 D17 D19 D20 - manual, event-driven, or derived.
        # Reported as present-but-not-automated rather than silently dropped.
        return {"id": did, "name": driver["name"], "grade": driver["grade"],
                "status": "NOT_AUTOMATED", "lean": "none",
                "basis": "sterownik nie zautomatyzowany (odczyt ręczny/kalendarz) — MACRO.md §8",
                "warning": driver.get("warning")}

    if basis is None:
        return None
    return {"id": did, "name": driver["name"], "grade": driver["grade"],
            "status": driver["status"], "lean": lean, "basis": basis,
            "warning": driver.get("warning")}


# --------------------------------------------------------------------------
# public surface
# --------------------------------------------------------------------------

def risk_state(state: dict) -> dict:
    """
    Jeden globalny odczyt nastroju: RISK_ON / RISK_OFF / MIXED / UNKNOWN.

    Skladany z sygnalow, ktore sa dostepne. Uwaga na uczciwosc odczytu:
    najmocniejszy skladnik to spready kredytowe (D4). Bez nich odczyt jest
    slaby i jest tak oznaczony - nie udajemy pewnosci, ktorej nie ma.

    VIX wchodzi tu tylko jako OPIS stanu (D3), nigdy jako prognoza (R3).
    """
    reg, r = state.get("regime", {}), state.get("readings", {})
    on, off, used = 0, 0, []

    credit = reg.get("D4_credit")
    if credit == "WIDENING":
        off += 2; used.append("spready rozszerzają się")
    elif credit == "COMPRESSING":
        on += 2; used.append("spready zawężają się")
    elif credit == "STABLE":
        used.append("spready stabilne")

    vix = (r.get("vix") or {}).get("last")
    if vix is not None:
        if vix < 16:
            on += 1; used.append(f"VIX {vix} spokojny")
        elif vix > 22:
            off += 1; used.append(f"VIX {vix} nerwowy")
        else:
            used.append(f"VIX {vix} neutralny")

    ts = reg.get("D18_term_structure")
    if ts == "CONTANGO":
        on += 1; used.append("zmienność w contango")
    elif ts == "BACKWARDATION":
        off += 1; used.append("zmienność w backwardation")

    if reg.get("D3_safe_haven_window") == "OPEN":
        off += 1; used.append("okno safe-haven otwarte")

    if on == 0 and off == 0:
        label = "UNKNOWN"
    elif on > off:
        label = "RISK_ON"
    elif off > on:
        label = "RISK_OFF"
    else:
        label = "MIXED"

    # Bez spreadow kredytowych odczyt jest slaby - mowimy to wprost.
    strong = credit in ("WIDENING", "COMPRESSING", "STABLE")
    return {
        "label": label,
        "confidence": "mocny" if strong else "słaby",
        "why": used,
        "missing_credit": not strong,
    }


def session_header(state: dict, contract: dict) -> dict:
    """
    The one-line macro backdrop CLAUDE.md asks for - as codes, so render.py
    can word it in Polish. Sits ABOVE the setup rows, never inside them.
    """
    r, regime = state["readings"], state["regime"]
    return {
        "asof": state["asof"],
        "risk": risk_state(state),
        "vix": r.get("vix", {}).get("last"),
        "vix_dir_20d": r.get("vix", {}).get("dir_20d"),
        "usd_dir_20d": r.get("usd_broad", {}).get("dir_20d"),
        "yield_10y": r.get("nom_10y", {}).get("last"),
        "yield_dir_20d": r.get("nom_10y", {}).get("dir_20d"),
        "credit": regime.get("D4_credit"),
        "safe_haven_window": regime.get("D3_safe_haven_window"),
        "gold_regime": regime.get("D2_real_yield_gold"),
        "vol_term_structure": regime.get("D18_term_structure"),
        "degraded": state["coverage"]["degraded"],
        "scope": "SELECTION_SIZING_HOLD_ONLY",
    }


def enrich(rows: list[dict], state: dict | None = None) -> int:
    """
    Mirrors news_ai.enrich(). Attaches a 'macro' field to each instrument row
    and returns how many were enriched.

    `rows` must carry the vtrade asset code (the 'asset' field from
    universe.json). Rows without a contract entry get coverage "NONE" and an
    empty driver list - never a fabricated lean.
    """
    if not available():
        return 0
    try:
        contract = load_contract()
    except (OSError, json.JSONDecodeError):
        return 0

    if state is None:
        state = compute_state()

    by_id = {d["id"]: d for d in contract["drivers"]}
    assets = contract["assets"]
    n = 0

    for row in rows:
        code = row.get("asset")
        entry = assets.get(code)
        if not entry:
            row["macro"] = {"coverage": "NONE", "drivers": [], "lean": "none"}
            continue

        reads = []
        for did in entry["drivers"]:
            d = by_id.get(did)
            if not d:
                continue
            got = _read_driver(d, state)
            if got:
                reads.append(got)

        # Lean by agreement among drivers that actually voted - NOT a weighted
        # score. Confidence is the best grade among the agreeing drivers, so a
        # single STRONG read is never diluted by weak company (R7).
        voting = [x for x in reads if x["lean"] in ("up", "down")]
        ups = [x for x in voting if x["lean"] == "up"]
        downs = [x for x in voting if x["lean"] == "down"]
        if ups and not downs:
            lean, agreeing = "up", ups
        elif downs and not ups:
            lean, agreeing = "down", downs
        elif ups and downs:
            lean, agreeing = "conflict", voting
        else:
            lean, agreeing = "none", []

        order = {"STRONG": 3, "PRACTITIONER": 2, "WEAK": 1}
        confidence = max((order.get(x["grade"], 0) for x in agreeing), default=0)

        row["macro"] = {
            "coverage": entry["coverage"],
            "lean": lean,
            "confidence": _PL_GRADE[{3: "strong", 2: "practitioner", 1: "weak", 0: "none"}[confidence]],
            "drivers": reads,
            "note": entry.get("note"),
            "warnings": [x["warning"] for x in reads if x.get("warning")],
            "scope": "SELECTION_SIZING_HOLD_ONLY",
        }
        n += 1

    return n


def save_state(state: dict) -> None:
    """Persist the STATE layer. The contract file is never written to."""
    try:
        with open(STATE_FILE, "w", encoding="utf-8") as fh:
            json.dump(state, fh, indent=2, ensure_ascii=False)
    except OSError:
        pass


if __name__ == "__main__":
    st = compute_state()
    ct = load_contract()
    print(json.dumps(session_header(st, ct), indent=2, ensure_ascii=False))
    if st["failures"]:
        print("\ndegraded, could not fetch:", ", ".join(st["failures"]))
    save_state(st)
