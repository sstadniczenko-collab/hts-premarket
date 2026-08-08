// =============================================================================
//  HtsSwingBot v0.1 — natywny cBot HTS Swing "Pro Filter 3.0" (setupy AAA/AA+).
//  Port 1:1 logiki z hts-premarket/hts_logic.py (ta sama, co skaner premarket),
//  żeby cBot i dashboard mówiły dokładnie to samo.
//
//  URUCHAMIAĆ na wykresie D1 lub H4 (strategia swingowa; jeden cBot = jeden
//  symbol + timeframe wykresu). NAJPIERW BACKTEST (cTrader tester lub
//  G2BacktestServer POST /backtest), potem ewentualnie demo. Nie odpalać live
//  bez walidacji edge'u — AAA/AA+ nie było jeszcze potwierdzone na backteście.
//
//  LOGIKA (identyczna z hts_logic.scan):
//   - Wstęgi: SMA(FastMa) i SMA(SlowMa) z High, Low oraz hl2=(H+L)/2.
//   - Trend: szybka nad wolną (fl>sh)=long, pod (fh<sl)=short. Cross = zmiana.
//   - "Oddech": cena wybija poza szybką wstęgę o DistPct% -> uzbrojenie retestu.
//   - Retest: cena wraca w szybką wstęgę (low<=fh && high>=fl) przy trendzie,
//     ADX>=AdxWeak, odstęp wstęg>=MinBandGapPct%, po właściwej stronie
//     (fast hl2 vs slow hl2) -> pierwszy = AAA, kolejne = AA+ (o >=
//     MinPyramidStepPct% od poprzedniego wejścia).
//   UWAGA: parametr 'smoothing' z Pythona jest w ścieżce sygnału MARTWY
//   (liczony, nieużywany) -> tu pominięty; sygnał pozostaje identyczny.
//   ADX = Wilder(14) ewm(alpha=1/n) jak w Pythonie.
//
//  EGZEKUCJA (nadbudowa nad sygnałem):
//   - Wejście po zamknięciu świecy sygnału (market, na otwarciu kolejnej).
//   - SL wg SlMode: 0=wolna wstęga (invalidation skanera; UWAGA w silnym trendzie
//     bywa >10% -> mikro-pozycje), 1=szybka wstęga (default, ciaśniej),
//     2=ATR (SlAtrMult x ATR). Backtest pokaże który sensowny.
//   - Sizing: RiskPercent% salda / dystans SL (jak TrrBot).
//   - AA+ = dokładka (max MaxAdds pozycji łącznie), każda z własnym SL.
//   - Wyjście: ExitOnBandBreak (close przebija szybką wstęgę w kontrę: long
//     close<fl / short close>fh) oraz ExitOnFlip (przeciwny cross). Opcjonalny
//     TpRR (R:R stały; 0 = brak, wyjście strukturalne).
//
//  KOMPILACJA: NOWY projekt cBota "HtsSwingBot" (wklej -> Build).
//  Parametry W KOLEJNOŚCI UI (POST /backtest "params") — 19 pozycji:
//   [FastMa, SlowMa, DistPct, MinBandGapPct, MinPyramidStepPct, AdxWeak,
//    AdxModerate, AdxStrong, AtrLength, RiskPercent, MaxAdds, SlBufferPct,
//    SlMode, SlAtrMult, TpRR, ExitOnBandBreak, ExitOnFlip, Direction, VerboseLog]
//  Domyślne:
//   [33, 144, 0.3, 0.5, 0.5, 20, 25, 40, 14, 1.0, 3, 0.1, 1, 2.0, 0.0, true, true, 0, false]
// =============================================================================

using System;
using cAlgo.API;
using cAlgo.API.Internals;

namespace cAlgo.Robots
{
    [Robot(AccessRights = AccessRights.None, AddIndicators = true)]
    public class HtsSwingBot : Robot
    {
        [Parameter("Szybka MA", DefaultValue = 33, MinValue = 2, Group = "Strategia")]
        public int FastMa { get; set; }

        [Parameter("Wolna MA", DefaultValue = 144, MinValue = 5, Group = "Strategia")]
        public int SlowMa { get; set; }

        [Parameter("Oddech: dystans poza wstęgę (%)", DefaultValue = 0.3, MinValue = 0.0, Group = "Strategia")]
        public double DistPct { get; set; }

        [Parameter("Min odstęp wstęg (%)", DefaultValue = 0.5, MinValue = 0.0, Group = "Strategia")]
        public double MinBandGapPct { get; set; }

        [Parameter("Min krok piramidy AA+ (%)", DefaultValue = 0.5, MinValue = 0.0, Group = "Strategia")]
        public double MinPyramidStepPct { get; set; }

        [Parameter("ADX próg słaby (blokuje)", DefaultValue = 20.0, MinValue = 0.0, Group = "ADX")]
        public double AdxWeak { get; set; }

        [Parameter("ADX próg umiarkowany", DefaultValue = 25.0, MinValue = 0.0, Group = "ADX")]
        public double AdxModerate { get; set; }

        [Parameter("ADX próg silny", DefaultValue = 40.0, MinValue = 0.0, Group = "ADX")]
        public double AdxStrong { get; set; }

        [Parameter("ATR length", DefaultValue = 14, MinValue = 1, Group = "ADX")]
        public int AtrLength { get; set; }

        [Parameter("Ryzyko % / wejście", DefaultValue = 1.0, MinValue = 0.01, Group = "Ryzyko")]
        public double RiskPercent { get; set; }

        [Parameter("Max pozycji (AAA + AA+)", DefaultValue = 3, MinValue = 1, Group = "Ryzyko")]
        public int MaxAdds { get; set; }

        [Parameter("Bufor SL (% ceny)", DefaultValue = 0.1, MinValue = 0.0, Group = "Ryzyko")]
        public double SlBufferPct { get; set; }

        [Parameter("Tryb SL (0 wolna wstęga / 1 szybka / 2 ATR)", DefaultValue = 1, MinValue = 0, MaxValue = 2, Group = "Ryzyko")]
        public int SlMode { get; set; }

        [Parameter("SL: mnożnik ATR (tryb 2)", DefaultValue = 2.0, MinValue = 0.1, Group = "Ryzyko")]
        public double SlAtrMult { get; set; }

        [Parameter("TP R:R (0 = brak)", DefaultValue = 0.0, MinValue = 0.0, Group = "Zarzadzanie")]
        public double TpRR { get; set; }

        [Parameter("Wyjście na przebiciu wstęgi", DefaultValue = true, Group = "Zarzadzanie")]
        public bool ExitOnBandBreak { get; set; }

        [Parameter("Wyjście na odwróceniu (cross)", DefaultValue = true, Group = "Zarzadzanie")]
        public bool ExitOnFlip { get; set; }

        [Parameter("Kierunek (0 oba / 1 long / -1 short)", DefaultValue = 0, MinValue = -1, MaxValue = 1, Group = "Zarzadzanie")]
        public int Direction { get; set; }

        [Parameter("Log zdarzeń", DefaultValue = false, Group = "Diagnostyka")]
        public bool VerboseLog { get; set; }

        private const string LabelPrefix = "HTS";

        // --- stan maszyny (jak `var` w Pine / stan w hts_logic.scan) ---
        private int _trend;              // 1 long / -1 short / 0 brak
        private bool _ready;
        private int _retestCount;
        private double _lastPrice;
        private bool _hasLastPrice;
        private bool _warmupDone;

        // poprzednie wartości wstęg (do detekcji cross)
        private double _flPrev = double.NaN, _shPrev = double.NaN,
                       _fhPrev = double.NaN, _slPrev = double.NaN;

        // --- ADX/ATR Wilder ewm(alpha=1/n) — stan bieżący ---
        private double _atr, _pdm, _mdm, _adx;
        private bool _emaSeeded, _adxSeeded;
        private double _prevHigh, _prevLow, _prevClose;
        private bool _hasPrev;

        private int _lastIdx = -1;       // ostatni przetworzony indeks świecy

        protected override void OnStart()
        {
            // rozgrzewka: przejdź całą dostępną historię ZAMKNIĘTYCH świec, żeby
            // odtworzyć stan (trend/ready/retest_count) tak jak skaner na starcie.
            int lastClosed = Bars.Count - 2;
            for (int i = 1; i <= lastClosed; i++)
                Step(i, live: false);
            _lastIdx = lastClosed;

            Print("HtsSwingBot v0.1 | {0} {1} | SMA {2}/{3} dist {4}% gap {5}% pyr {6}% | ADX {7}/{8}/{9} | risk {10}% maxAdds {11} SLbuf {12}% TP-RR {13} | bandBreak {14} flip {15} dir {16} | trend startowy={17} retest={18}",
                  SymbolName, TimeFrame, FastMa, SlowMa, DistPct, MinBandGapPct, MinPyramidStepPct,
                  AdxWeak, AdxModerate, AdxStrong, RiskPercent, MaxAdds, SlBufferPct, TpRR,
                  ExitOnBandBreak, ExitOnFlip, Direction, _trend, _retestCount);
        }

        protected override void OnBar()
        {
            int i = Bars.Count - 2;      // świeca, która właśnie się ZAMKNĘŁA
            if (i <= _lastIdx) return;
            Step(i, live: true);
            _lastIdx = i;
        }

        // ---------- SMA pomocnicze (0=high, 1=low, 2=hl2) ----------
        private double Sma(int kind, int period, int i)
        {
            if (i < period - 1) return double.NaN;
            double s = 0;
            for (int k = i - period + 1; k <= i; k++)
            {
                double v = kind == 0 ? Bars.HighPrices[k]
                         : kind == 1 ? Bars.LowPrices[k]
                         : (Bars.HighPrices[k] + Bars.LowPrices[k]) / 2.0;
                s += v;
            }
            return s / period;
        }

        // ---------- ADX Wilder ewm(alpha=1/n) — krok inkrementalny ----------
        private void StepAdx(int i)
        {
            double h = Bars.HighPrices[i], l = Bars.LowPrices[i], c = Bars.ClosePrices[i];
            if (!_hasPrev) { _prevHigh = h; _prevLow = l; _prevClose = c; _hasPrev = true; return; }

            double up = h - _prevHigh;
            double dn = _prevLow - l;
            double plusDm = (up > dn && up > 0) ? up : 0.0;
            double minusDm = (dn > up && dn > 0) ? dn : 0.0;
            double tr = Math.Max(h - l, Math.Max(Math.Abs(h - _prevClose), Math.Abs(l - _prevClose)));

            double a = 1.0 / AtrLength;
            if (!_emaSeeded)
            {
                _atr = tr; _pdm = plusDm; _mdm = minusDm; _emaSeeded = true;
            }
            else
            {
                _atr += a * (tr - _atr);
                _pdm += a * (plusDm - _pdm);
                _mdm += a * (minusDm - _mdm);
            }

            if (_atr > 0)
            {
                double pdi = 100.0 * _pdm / _atr;
                double mdi = 100.0 * _mdm / _atr;
                double sum = pdi + mdi;
                double dx = sum > 0 ? 100.0 * Math.Abs(pdi - mdi) / sum : 0.0;
                if (!_adxSeeded) { _adx = dx; _adxSeeded = true; }
                else _adx += a * (dx - _adx);
            }

            _prevHigh = h; _prevLow = l; _prevClose = c;
        }

        // ---------- jeden krok maszyny stanu (port hts_logic.scan) ----------
        private void Step(int i, bool live)
        {
            StepAdx(i);   // ADX zawsze aktualizowany (jak precompute w pandas)

            double fh = Sma(0, FastMa, i), fl = Sma(1, FastMa, i), fhl2 = Sma(2, FastMa, i);
            double sh = Sma(0, SlowMa, i), sl = Sma(1, SlowMa, i), shl2 = Sma(2, SlowMa, i);

            // odpowiednik NaN-continue w Pythonie: brak wstęg/ADX -> tylko zapamiętaj prev
            bool valid = !double.IsNaN(fh) && !double.IsNaN(sh) && _adxSeeded
                         && !double.IsNaN(fhl2) && !double.IsNaN(shl2);
            if (!valid) { _flPrev = fl; _shPrev = sh; _fhPrev = fh; _slPrev = sl; return; }

            double c = Bars.ClosePrices[i], hi = Bars.HighPrices[i], lo = Bars.LowPrices[i];
            double distPrice = c * DistPct / 100.0;
            double minGap = c * MinBandGapPct / 100.0;
            double pyrStep = c * MinPyramidStepPct / 100.0;

            if (!_warmupDone)
            {
                if (fl > sh) _trend = 1;
                else if (fh < sl) _trend = -1;
                _warmupDone = true;
            }

            if (_trend == 1 && c > fh + distPrice) _ready = true;
            else if (_trend == -1 && c < fl - distPrice) _ready = true;

            bool crossUp = (_flPrev <= _shPrev) && (fl > sh);
            bool crossDown = (_fhPrev >= _slPrev) && (fh < sl);
            int trendBefore = _trend;

            if (crossUp) { _retestCount = 0; _ready = false; _hasLastPrice = false; _trend = 1; }
            if (crossDown) { _retestCount = 0; _ready = false; _hasLastPrice = false; _trend = -1; }

            // wyjścia (tylko live) — flip i przebicie wstęgi
            if (live)
            {
                if (ExitOnFlip && ((crossUp && trendBefore == -1) || (crossDown && trendBefore == 1)))
                    CloseAll("flip");
                else if (ExitOnBandBreak && CountMine() > 0)
                {
                    if (_trend == 1 && c < fl) CloseAll("band-break");
                    else if (_trend == -1 && c > fh) CloseAll("band-break");
                }
            }

            bool priceInBand = (lo <= fh) && (hi >= fl);
            double gap = _trend == 1 ? (fl - sh) : (_trend == -1 ? (sl - fh) : 0.0);
            bool bandWide = gap >= minGap;
            bool adxNotWeak = _adx >= AdxWeak;

            if (priceInBand && _ready && bandWide && _trend != 0 && adxNotWeak)
            {
                bool correctSide = (_trend == 1 && fhl2 > shl2) || (_trend == -1 && fhl2 < shl2);
                if (correctSide)
                {
                    if (_retestCount == 0)
                    {
                        _retestCount = 1; _ready = false; _lastPrice = c; _hasLastPrice = true;
                        if (live) Fire("AAA", _trend, fh, fl, sh, sl);
                    }
                    else
                    {
                        bool pyrOk = !_hasLastPrice
                            || (_trend == 1 ? (c - _lastPrice) >= pyrStep : (_lastPrice - c) >= pyrStep);
                        if (pyrOk)
                        {
                            _retestCount++; _ready = false; _lastPrice = c; _hasLastPrice = true;
                            if (live) Fire("AA+", _trend, fh, fl, sh, sl);
                        }
                    }
                }
            }

            _flPrev = fl; _shPrev = sh; _fhPrev = fh; _slPrev = sl;
        }

        // ---------- egzekucja ----------
        private void Fire(string kind, int trend, double fh, double fl, double sh, double sl)
        {
            var side = trend == 1 ? TradeType.Buy : TradeType.Sell;
            if (Direction == 1 && side != TradeType.Buy) return;
            if (Direction == -1 && side != TradeType.Sell) return;
            if (CountMine() >= MaxAdds) { if (VerboseLog) Print("[HTS] {0} pominięty — limit {1} pozycji", kind, MaxAdds); return; }

            double entry = side == TradeType.Buy ? Symbol.Ask : Symbol.Bid;
            double buf = entry * (SlBufferPct / 100.0);
            // baza SL wg trybu: 0 wolna wstęga (invalidation skanera, szeroki),
            // 1 szybka wstęga (ciaśniej), 2 ATR-owy dystans od wejścia
            double slPrice;
            if (SlMode == 2)
                slPrice = side == TradeType.Buy ? entry - SlAtrMult * _atr - buf
                                                : entry + SlAtrMult * _atr + buf;
            else if (SlMode == 1)
                slPrice = side == TradeType.Buy ? fl - buf : fh + buf;
            else
                slPrice = side == TradeType.Buy ? sh - buf : sl + buf;
            double slDist = side == TradeType.Buy ? entry - slPrice : slPrice - entry;
            double slPips = slDist / Symbol.PipSize;
            if (slPips < 1) { if (VerboseLog) Print("[HTS] {0} skip — SL<1p (slPrice {1})", kind, slPrice); return; }

            double riskAmount = Account.Balance * (RiskPercent / 100.0);
            double perUnit = slPips * Symbol.PipValue;
            if (perUnit <= 0) return;
            if (Symbol.VolumeInUnitsMin * perUnit > riskAmount)
            { Print("[HTS] {0} skip — min lot > ryzyko (SL {1:F1}p)", kind, slPips); return; }
            double vol = Symbol.NormalizeVolumeInUnits(riskAmount / perUnit, RoundingMode.Down);
            if (vol < Symbol.VolumeInUnitsMin) return;

            double? tpPips = TpRR > 0 ? (double?)(slPips * TpRR) : null;
            string label = LabelPrefix + (side == TradeType.Buy ? "_L" : "_S");
            var res = ExecuteMarketOrder(side, SymbolName, vol, label, slPips, tpPips);
            if (res == null || !res.IsSuccessful)
            { if (VerboseLog) Print("[HTS] {0} order fail: {1}", kind, res == null ? "null" : res.Error.ToString()); return; }

            Print(">>> {0} {1} {2} @ {3:F2} SL {4:F1}p ({5:F2}) TP {6} vol {7} ADX {8:F1} retest#{9}",
                  kind, label, side, entry, slPips, slPrice, tpPips.HasValue ? tpPips.Value.ToString("F1") + "p" : "—",
                  vol, _adx, _retestCount);
        }

        private void CloseAll(string reason)
        {
            int n = 0;
            foreach (var p in Positions)
                if (IsMine(p)) { ClosePosition(p); n++; }
            if (n > 0 && VerboseLog) Print("[HTS] zamknięto {0} poz. ({1})", n, reason);
        }

        private bool IsMine(Position p)
        {
            return p.Label != null && p.Label.StartsWith(LabelPrefix) && p.SymbolName == SymbolName;
        }

        private int CountMine()
        {
            int n = 0;
            foreach (var p in Positions) if (IsMine(p)) n++;
            return n;
        }
    }
}
