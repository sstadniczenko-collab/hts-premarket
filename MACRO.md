# MACRO — the fundamental context layer

Adds a non-price layer to the premarket scan: graded, sourced macro drivers behind the
"macro backdrop" line that `CLAUDE.md` already asks the briefing to open with.

Three files, flat, matching the repo's existing shape:

| File | Role |
|---|---|
| `macro_drivers.json` | The **contract** — 18 drivers + 8 rejected, keyed to `universe.json` asset codes |
| `macro.py` | The **module** — fetches, computes state, enriches rows. Stdlib only, no API key |
| `MACRO.md` | This file — the rules |

Evidence base: 20 driver packets built from 57 primary full-text sources. Research current
as of 2026-07-20. Every driver carries its mechanism, a magnitude with sample and period,
the regime where it breaks, its decay status, and citations.

---

## 1. Quick start

```bash
python macro.py            # prints the session header, writes macro_state.json
```

In `scan.py`, after rows are built and beside the existing `news_ai` call:

```python
import macro
state = macro.compute_state()
macro.enrich(rows, state)                  # attaches row["macro"], mirrors news_ai.enrich()
header = macro.session_header(state, macro.load_contract())
macro.save_state(state)
```

`enrich()` matches on `row["asset"]` — the vtrade code from `universe.json` (`ES`, `DAX`,
`GC`…). Rows with no contract entry get `coverage: "NONE"` and an empty driver list. Never
a fabricated lean.

---

## 2. The hard rule

**Nothing in this layer is an entry trigger.**

Entries belong to `hts_logic.py`. The evidence base is explicit that these drivers pay in
**asset selection, position sizing and hold duration** — a weekly or monthly driver cannot
improve a low-timeframe entry, and every packet carries a `never: ["entry_trigger"]` field
saying so in the data itself.

Two consequences for `render.py`:

1. **The macro block renders as a session header, above the setup rows — never as a column
   inside them.** Put a macro verdict next to `ENTRY 4,532 · STOP 4,498` and a reader will
   treat it as part of the trigger.
2. **Never let it block a setup.** Record disagreement as a flag; do not suppress the row.
   A hard veto from an unvalidated overlay would remove real winners, and this overlay has
   no proven track record on this system's results. See rejected item **R8**.

---

## 3. Two layers, kept apart

**CONTRACT** (`macro_drivers.json`) — slow, curated, research-backed. Grades, magnitudes,
regime conditions, citations. Changes only when new evidence arrives.

**STATE** (`macro_state.json`) — fast, computed. What is true right now: is the credit
spread widening, is the safe-haven window open, is the real-yield→gold link holding.

`macro.py` **writes state and never writes the contract.** The `status` field shipped in
the contract is a research snapshot at `research_asof`; `compute_state()` is what tells you
whether it still holds. Mix the two and the file rots silently — a regime break recorded as
a constant in 2026 becomes a lie in 2027 with nothing to announce it.

---

## 4. What you get per asset

```json
"macro": {
  "coverage": "full | inherited | partial | STUB | INPUT | NONE",
  "lean": "up | down | conflict | none",
  "confidence": "strong | practitioner | weak | none",
  "drivers": [ { "id", "name", "grade", "status", "lean", "basis", "warning" } ],
  "warnings": [...],
  "scope": "SELECTION_SIZING_HOLD_ONLY"
}
```

**There is no composite score.** `lean` is agreement among drivers that actually voted;
`confidence` is the *best* grade among the agreeing drivers, not an average — so one STRONG
read is never diluted by weak company. Weighted blends are rejected (**R7**): the weights
in circulation are one author's prior with no data behind them, and a weighted average of
individually unproven signals looks scientific without being so.

A driver reports `status: SUSPENDED` and abstains when its regime gate is closed —
including when the gate could not be measured because its input was unreachable. The
`basis` string says which of the two happened.

### Coverage is honest, including where it is empty

| Coverage | Assets | Meaning |
|---|---|---|
| `full` | ES NQ YM DAX NIKKEI VX GC SI | Dedicated researched drivers |
| `inherited` | F40 FESX ES35 | Export channel inherited from DAX (D14), not independently measured — grade one step lower |
| `partial` | FTSE PL WBS CC KC GBPJPY | Some drivers researched, primary drivers not |
| `STUB` | HS HG PA BTC ETH | **No research exists.** Named, not silently skipped |
| `INPUT` | DXY US10 | These *drive* other assets. No lean is emitted for them |

The stubs are real gaps: Hang Seng (China policy, property credit), copper (China
construction), palladium (Russia-weighted supply — do **not** apply platinum's D20), crypto
(ETF flows, halving, on-chain — nothing at all). They are listed so they cannot be quietly
filled with invention.

---

## 5. Data sources — verified 2026-07-30

All keyless. Nothing here reads `ANTHROPIC_API_KEY` or any secret.

| Source | Status | Covers |
|---|---|---|
| **Yahoo v8** | ✅ working | prices, FX, VIX, VIX3M, ^TNX, ^IRX, DXY |
| **FRED CSV** | ⚠️ **403 / timeout to automated clients** | real yields, HY OAS, breakevens |
| **CFTC Socrata** | keyless, not yet wired | COT for CC / KC / WBS / GBPJPY |
| Stooq | ⚠️ bot-challenge page | — |

**FRED changed under us.** It was verified working 2026-07-13 and refused automated
requests on 2026-07-30 from at least one network. `macro.py` keeps FRED as the primary
source and falls back per series:

| Series | Fallback | Exact? |
|---|---|---|
| DGS10 | Yahoo `^TNX` | ✅ same series |
| VIXCLS | Yahoo `^VIX` | ✅ same series |
| DTWEXBGS | Yahoo `DX-Y.NYB` | ⚠️ **substitute** — DXY is 6 currencies, not broad trade-weighted |
| T10Y2Y | Yahoo `^TNX − ^IRX` | ⚠️ **substitute** — that is ~10Y−3M, not 2s10s |
| **DFII10** | *(none)* | ❌ **dark** |
| **BAMLH0A0HYM2** | *(none)* | ❌ **dark** |
| T10YIE | *(none)* | ❌ dark |

Every reading carries `source` and `exact` provenance, so a substitute can never be read as
the real thing.

### Run this once from GitHub Actions before trusting the layer

```python
import macro, json; print(json.dumps(macro.probe_fred(), indent=2))
```

FRED may well work from GitHub's network even though it refused elsewhere. **If it does
not**, two things go dark and you should know it rather than discover it:

- **D4 credit spreads** — one of only two STRONG, undecayed, fully automatable drivers
- **D2's real-yield gate** for gold — without it, D11 governs gold by default

There is deliberately **no ETF proxy** for either. `HYG`/`LQD` would be a price-derived
stand-in for a non-price driver — it would violate the layer's whole premise and be a
weaker instrument besides. Dark is more honest than proxied.

---

## 6. The three things most likely to be got wrong

**① Real yields → gold has been broken since 2022.** The cleanest macro-to-gold link in the
literature (correlation −0.82, 1997–2012) collapsed to ~+0.03 as gold rose *with* rising
real yields, overridden by three consecutive >1,000-tonne years of central-bank buying.
D2 and D11 are a **mandatory pair**. Never emit a gold lean from D2 alone, and never
hard-code the pre-2022 sign — a model reasoning from general knowledge will do exactly that.

**② COT is alive on softs, energy and FX — and statistically dead on metals and indices.**
Same method: 2.38%/month in corn (t=1.98) and 2.88%/month in yen (t=2.75), versus
0.19%/month in the S&P (t=0.13, insignificant). On gold, silver and platinum, 2 of ~30
extreme-signal tests reject the null — chance level. `targets_excluded` in D12 is a hard
list, not a suggestion. It applies to **CC, KC, WBS, GBPJPY only.**

**③ VIX describes, it does not predict.** Same-day t-statistic on the VIX change is
110–208; at the first lag it drops to 7–31. Keep it as a state gauge (D3) and a term-structure
carry input (D18). Contango does **not** mean "VIX will fall" — both primary sources
explicitly reject that reading.

---

## 7. Rejected — do not rebuild these

Each carries its sources in `macro_drivers.json`.

| # | Rejected | Why |
|---|---|---|
| R1 | M2 / global liquidity / `WALCL−TGA−RRP` | Liquidity-shock effect on asset prices statistically insignificant; the popular formula has **zero** peer-reviewed test and decoupled after 2022 |
| R2 | COT on metals and indices | Insignificant across two independent samples, 1992–2012 |
| R3 | VIX as a direction forecast | Contemporaneous, not predictive |
| R4 | Gold/silver ratio as a reversion timer | Cointegration rejected; decaying since ~1990 |
| R5 | A standing gold-vs-equities inverse rule | The opposition is tail-only and decays in ~15 trading days — wrong most of the year |
| R6 | Calendar / seasonality edges | Tested and dead: DAX has **zero** persistent calendar anomalies of 188 tested |
| R7 | A weighted composite score | The weights are invented; a blend of unproven signals is not evidence |
| R8 | `CONFLICT = NO TRADE` | A hard veto from an unvalidated overlay removes real winners |

R5 deserves emphasis because it is the intuitive design and it is wrong: a cross-asset
inverse rule fires all year for a relationship that only exists in the equity tail.

---

## 8. Not wired yet

- **D12 COT** — CFTC Socrata is keyless and the datasets are named in the contract; the
  weekly percentile fetch is not written. Four assets, real evidence behind it.
- **D9 policy surprise / D7 CPI salience** — need a release calendar. The highest-value
  addition, and the one piece that can act without a proof period: an event blackout is not
  a prediction, it is a known schedule.
- **D11 / D13 / D20** — quarterly or monthly manual reads (WGC tonnage, ISM direction over
  three prints, WPIC platinum balance). Reported as `NOT_AUTOMATED`, never silently zero.
