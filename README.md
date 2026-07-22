# HTS Premarket Scanner

Chmurowy skaner setupów **HTS Swing – Pro Filter 3.0** (AAA / AA+) na koszyku
instrumentów, które monitoruje **vtrade**. Odpala się jako **GitHub Action** dwa
razy dziennie — przed otwarciem sesji EU i US — i publikuje statyczny dashboard
na **GitHub Pages**. Gotowa premarket-watchlista zanim usiądziesz do rynku.

**Live:** https://sstadniczenko-collab.github.io/hts-premarket/

## Skąd się wziął

To chmurowa wersja lokalnego `hts_scanner` (`Y:\15_AI\02_TRADING\hts_scanner`).
Lokalny skaner czyta dane z **TradingView Desktop przez CDP** (`tv` CLI) — co nie
działa w GitHub Actions. Tutaj:

- **Logika** (`hts_logic.py`) jest skopiowana 1:1 z lokalnego skanera — ta sama
  replika Pine (wstęgi SMA 33/144, ADX, ATR, detektor AAA/AA+).
- **Dane** pochodzą z **yfinance** (chmurowo; Yahoo nie jest blokowane w Actions).
- **Uniwersum** = 24 instrumenty vtrade (feed regime HTS) zmapowane na tickery
  yfinance — patrz `universe.json`.

## Czym to **nie** jest

To nie są sygnały **regime v-tradera** (Departure / RT1-3 / Cross) z Redisa — tamte
liczy zewnętrzny system Darka na nietypowych TF (2D/3D/8H/12H). Tutaj biegnie
**Twoja własna logika HTS Swing** (AAA/AA+) na D1 i H4, na tym samym koszyku.

## Setupy

- **AAA** — pierwszy retest szybkiej wstęgi po crossie (świeży impuls trendu).
- **AA+** — kolejna dokładka (piramidowanie w trwającym trendzie).
- Sufiks **`*`** = trend umiarkowany (ADX 20–25), **`!`** = wyczerpany (ADX ≥ 40),
  brak sufiksu = silny (ADX 25–40). ADX < 20 blokuje sygnał.
- **Świeży** = setup na ostatnich `fresh_bars+1` zamkniętych świecach (domyślnie 3).
  Te trafiają do sekcji „co już strzeliło".

## Plan wejścia — gdzie szukać wejść teraz

Górna sekcja dashboardu odpowiada wprost: *jakich poziomów szukać i z jakiego
setupu*. Dla każdego instrumentu w trendzie skaner liczy z końcowego stanu
maszyny HTS (`hts_logic.entry_plan`):

- **wejście @** — linia retestu = krawędź szybkiej wstęgi (SMA 33) od strony, z
  której wraca cena (górna dla longa, dolna dla shorta). Tu strategia szuka wejścia.
- **strefa** — cała szybka wstęga (`fast_l … fast_h`); dotyk wystarczy do retestu.
- **z jakiego setupu** — **AAA** jeśli nie było jeszcze retestu po crossie
  (`retest_count == 0`), inaczej **AA+** (dokładka).
- **stop za** — wolna wstęga (SMA 144); przebicie = zagrożenie odwrócenia trendu.
- **cofka %/ATR** — ile cena musi wrócić do linii wejścia.
- **status**:
  - `W STREFIE` — cena już na wstędze teraz, obserwuj reakcję,
  - `UZBROJONY` — zrobiła „oddech", czeka na powrót do linii (trafia na karty),
  - `BRAK ODDECHU` — musi najpierw wybić dalej od wstęgi, potem retest,
  - `PRZEGŁĘBIONY` — cofka przebiła całą wstęgę na wylot (retest niedomknięty),
  - `WSTĘGI WĄSKIE` / `ADX SŁABY` — setup strukturalnie zablokowany.

Karty u góry pokazują tylko `W STREFIE` + `UZBROJONY` (actionable teraz),
posortowane wg odległości do linii. Pełne poziomy dla wszystkich instrumentów są
w tabeli (kolumna *plan*). **To poziomy do obserwacji, nie automatyczne zlecenia.**

## Kontekst dzienny — pivot + gapy (`levels.py`)

Obok setupów HTS każdy instrument dostaje kontekst z ostatniej zamkniętej świecy D1:

- **Pivot dzienny** — klasyczny floor pivot (`P=(H+L+C)/3`, R1/R2/R3, S1/S2/S3)
  rzutowany na następną sesję. Dashboard pokazuje `P`, strefę (między którymi
  poziomami jest cena), bias (zamknięcie nad/pod P) oraz najbliższy opór/wsparcie
  z dystansem %.
- **Gap** — luka otwarcia ostatniej sesji (open vs poprzednie zamknięcie):
  kierunek ↑/↓, wielkość %, oraz czy **OTWARTA** czy już wypełniona.
- **Gap-over-gap (GoG)** — flaga, gdy otwarcie przeskoczyło **starszą, wciąż
  niewypełnioną** lukę w tym samym kierunku, zostawiając **podwójną niewypełnioną
  strefę** jako magnes (poziomy magnesu podane: pod spodem dla luk w górę, nad dla
  luk w dół). Wymaga, by obie luki były otwarte.

Parametry w `config.json` → `levels`: `gap_min_pct` (min. luka % — odsiewa szum),
`gap_lookback` (ile sesji D1 skanować pod niewypełnione luki).

## News + wpływ AI (`news_ai.py`)

Każdy instrument dostaje ocenę **potencjalnego wpływu newsów na cenę** liczoną
przez **Claude Haiku** na świeżych nagłówkach z yfinance (`Ticker.news`):

- **bias** — byczy / niedźwiedzi / neutralny / obustronne ryzyko,
- **siła** — niski / średni / wysoki,
- **katalizator** — najważniejsze wydarzenie w kilku słowach,
- **notka** — jedno zdanie „jak to może ruszyć cenę i na co uważać".

Widoczne jako chip w kolumnie *News (AI)* w tabeli (notka w tooltipie) oraz pełny
blok na kartach planu wejścia.

**Klucz API.** Aktywne tylko gdy w środowisku jest `ANTHROPIC_API_KEY`:
- w GitHub Actions — jako **repo secret** (`Settings → Secrets → Actions`);
  workflow podaje go do kroku skanu przez `env:`,
- lokalnie — z `.env` obok skryptu lub `Y:\15_AI\02_TRADING\.env`.

Bez klucza skaner działa normalnie, tylko pomija sekcję news. `--no-news` wyłącza
ocenę na żądanie (zero wywołań API). Koszt: ~24 wywołania Haiku na run × 2/dobę
(groszowy). To **potencjalny** wpływ z nagłówków, nie prognoza — nagłówki bywają
ogólnorynkowe.

## Harmonogram

| Cron (UTC) | Kiedy | Po co |
|---|---|---|
| `30 6 * * 1-5`  | 06:30 | przed otwarciem sesji EU/DAX |
| `0 13 * * 1-5`  | 13:00 | przed otwarciem sesji US (NYSE 09:30 ET) |

Plus ręcznie: zakładka **Actions → HTS Premarket Scan → Run workflow**.

## Uruchomienie lokalne

```bash
pip install -r requirements.txt
python scan.py --out docs                 # pełny skan (24 instr. × D1+H4) → docs/
python scan.py --only 1d --out docs       # tylko D1 (szybciej)
python scan.py --assets GC,ES,NQ --dry-run  # podzbiór, nic nie zapisuje
```

Otwórz `docs/index.html` w przeglądarce.

## Pliki

```
scan.py          # main: fetch → HTS scan → docs/data.json + docs/index.html
hts_logic.py     # replika Pine (AAA/AA+, ADX, ATR) — 1:1 z hts_scanner
data_yf.py       # yfinance: D1 + H4 (resample z 1h), odcięcie niezamkniętej świecy
render.py        # dashboard HTML (self-contained, dark)
universe.json    # 24 instrumenty vtrade → tickery yfinance (+ uwagi mapowania)
config.json      # parametry strategii + próg 'fresh'
docs/            # wyjście publikowane na GitHub Pages (index.html + data.json)
.github/workflows/scan.yml
```

## Uwagi o danych

- **D1** — pewne, pełna historia (indeksy ~2 lata, ciągłe futures ~1–2 lata).
- **H4** — składane z 1h (yfinance nie ma natywnego 4h). Kotwica sesji może się
  różnić od brokera/TV → traktuj jako pomocnicze, headline to D1.
- **ES35** = IBEX 35 (Spain), nie S&P. **WBS** realnie handluje WTI (`CL=F`).
  **US10** = `^TNX` (rentowność ×10). Szczegóły w `universe.json` → `_mapping_notes`.
