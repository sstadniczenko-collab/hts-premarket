# HtsSwingBot — natywny cBot HTS Swing (AAA/AA+)

Port 1:1 logiki `hts_logic.py` (tej samej, co skaner premarket) do cBota cTrader.
Sygnał identyczny jak na dashboardzie; doszła egzekucja (wejście/SL/sizing/wyjście).

**Kolejność: NAJPIERW BACKTEST, potem demo, live dopiero po walidacji edge'u.**
AAA/AA+ nie było jeszcze potwierdzone na backteście — to jest właśnie ten krok.

## Kompilacja

1. cTrader → **Algo → cBots → New cBot** → wklej `HtsSwingBot.cs` → **Build**.
2. Dodaj cBota na wykres **D1 lub H4** instrumentu (strategia swingowa; jeden
   cBot = jeden symbol + timeframe wykresu, jak Wasze HTS EA per symbol).

## Backtest

- **Wbudowany tester cTradera** — zakładka Backtesting, ustaw zakres, tick/m1.
- **G2BacktestServer** (port 9877) — po skompilowaniu cBota:
  ```
  POST http://127.0.0.1:9877/backtest
  { "robot":"HtsSwingBot", "symbol":"GER40", "timeframe":"d1",
    "from":"2024-01-01", "to":"2026-07-01", "balance":10000,
    "params":[33,144,0.3,0.5,0.5,20,25,40,14,1.0,3,0.1,1,2.0,0.0,true,true,0,false] }
  ```
  `params` = kolejność z nagłówka `HtsSwingBot.cs` (19 pozycji).

## Parametry (default)

`FastMa 33 · SlowMa 144 · DistPct 0.3 · MinBandGapPct 0.5 · MinPyramidStepPct 0.5
· ADX 20/25/40 · AtrLength 14 · RiskPercent 1.0 · MaxAdds 3 · SlBufferPct 0.1 ·
SlMode 1 · SlAtrMult 2.0 · TpRR 0 · ExitOnBandBreak · ExitOnFlip · Direction 0 ·
VerboseLog off`

**SlMode** (kluczowy do sensownego backtestu):
- `0` wolna wstęga = "invalidation" ze skanera — wierne, ale w silnym trendzie
  SL >10% → mikro-pozycje. Zwykle złe jako realny stop.
- `1` szybka wstęga (**default**) — ciaśniej, praktyczniej.
- `2` ATR × `SlAtrMult` — stały dystans zmiennościowy.

## Parzystość ze skanerem

cBot ma dawać te same setupy AAA/AA+ co `hts_logic.scan`. Baseline do porównania
(D1, dane cTrader z `bars.json`, stan na 2026-07):

- **GER40 (DAX) D1**, ostatnie: 2026-01-20 AAA long @24863 (ADX 30.8),
  2026-02-08 AA+ long @25040.
- **XAUUSD (GC) D1**, ostatnie: 2026-07-20 AAA short @4077 (ADX 39.6),
  2026-07-22 AA+ short @4049, 2026-07-27 AA+ short @4028.
- **US100 (NQ) D1**, 2026-06-04 AAA long @28825 (ADX 37.0) + serie AA+.

Odpal backtest na tym samym zakresie i sprawdź, że wejścia lecą w tych datach/
kierunkach. Rozjazd = błąd portu (zgłoś). Drobne różnice ADX w pierwszych ~30
świecach są OK (seeding Wilder), po rozgrzewce znikają.

## Uwagi

- `smoothing` z `hts_logic.py` jest w ścieżce sygnału martwy → w cBocie pominięty
  (sygnał identyczny).
- Dane cBota = feed brokera, na którym chodzi cTrader (jak reszta projektu).
- To v0.1 — świadomie proste wyjścia (band-break / flip / opcjonalny TP-RR).
  Trailing/BE/część-zamknięć do dołożenia po tym, jak backtest pokaże że warto.
