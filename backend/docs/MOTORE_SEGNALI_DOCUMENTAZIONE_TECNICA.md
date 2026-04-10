# PROPSIGNAL ENGINE v10.0 - DOCUMENTAZIONE TECNICA COMPLETA

**Data:** Aprile 2026
**File Principale:** `/app/backend/services/signal_generator_v3.py`
**Status:** PRODUZIONE ATTIVA - RISCRITTURA COMPLETA

---

## PANORAMICA v10.0

### Filosofia
Il motore valuta ogni trade in 3 livelli:
- **A. CONTEXT** - La direzione di fondo è sensata?
- **B. STRUCTURE** - La struttura del prezzo supporta BUY o SELL?
- **C. TRIGGER** - Il timing d'ingresso è buono adesso?

**Price-action / structure based, NON candle-statistics based.**

### Timeframe Usati
| TF | Candles | Uso |
|----|---------|-----|
| H1 | 120 | Contesto principale (EMA20, EMA50, swing points) |
| M15 | 160 | Struttura e pullback (EMA20, swing points) |
| M5 | 200 | Trigger d'ingresso (EMA20, ATR14) |

### Indicatori Derivati
- EMA20 su H1, M15, M5
- EMA50 su H1, M15
- ATR14 su H1, M15, M5
- Swing highs/lows (pivot lookback = 2)

---

## FATTORI BUY (Total = 100%)

| # | Fattore | Peso | Min Score |
|---|---------|------|-----------|
| 1 | H1 Structural Bias | 20% | 60 |
| 2 | M15 Structure Quality | 18% | - |
| 3 | M5 Trigger Quality | 16% | 60 |
| 4 | Pullback Quality | 14% | - |
| 5 | FTA / Clean Space | 14% | 30 |
| 6 | Directional Continuation | 10% | - |
| 7 | Session Quality | 5% | - |
| 8 | Market Sanity Check | 3% | 40 |

## FATTORI SELL (Total = 100%)

| # | Fattore | Peso | Min Score |
|---|---------|------|-----------|
| 1 | H1 Structural Bias | 22% | 65 |
| 2 | M15 Structure Quality | 20% | - |
| 3 | M5 Trigger Quality | 16% | 60 |
| 4 | Pullback Quality | 12% | - |
| 5 | Rejection / Failed Push | 14% | 60 |
| 6 | FTA / Clean Space | 10% | 30 |
| 7 | Session Quality | 4% | - |
| 8 | Market Sanity Check | 2% | 40 |

---

## DETTAGLIO FATTORI

### 1. H1 Structural Bias

**Condizioni BUY (5 punti):**
1. Ultimo swing high > swing high precedente (HH)
2. Ultimo swing low > swing low precedente (HL)
3. Close > EMA20 H1
4. EMA20 > EMA50
5. Slope EMA20 positiva

**Condizioni SELL (5 punti):**
1. Ultimo swing high < swing high precedente (LH)
2. Ultimo swing low < swing low precedente (LL)
3. Close < EMA20 H1
4. EMA20 < EMA50
5. Slope EMA20 negativa

**Scoring:** 5/5=100, 4/5=85, 3/5=70, 2/5=50, 0-1/5=30

### 2. M15 Structure Quality

**Condizioni BUY (3 punti):**
1. Sequenza HH + HL su M15
2. Prezzo > EMA20 M15
3. Nessun swing low rotto nelle ultime 8 candle

**Condizioni SELL (3 punti):**
1. Sequenza LH + LL su M15
2. Prezzo < EMA20 M15
3. Nessun swing high rotto nelle ultime 8 candle

**Scoring:** 3/3=100, 2/3=80, 1/3=65, 0/3=25

### 3. M5 Trigger Quality

**BUY Triggers:**
- A. Break-and-hold: Close rompe micro high e tiene
- B. Reclaim: Dip sotto EMA20, reclaim con close bullish
- C. Continuation: 2 close bullish consecutive dopo pullback

**SELL Triggers:**
- A. Rejection: Wick superiore >= 35% range, close in bottom 35%
- B. Failed push: Nuovo high negato entro 2 candle
- C. Continuation: 2 close bearish consecutive

**Scoring:** 95 (forte), 80 (buono), 60 (debole), 30 (assente)
**HARD FILTER:** Score < 60 → REJECT

### 4. Pullback Quality

**Calcolo:**
1. Identifica leg impulsivo (M15 swing)
2. Verifica impulso minimo (EURUSD >= 12p, XAUUSD >= $4)
3. Calcola profondità pullback (% del leg)

**Zone:**
- 38.2%-61.8%: Score 100 (Fib ideale)
- 25%-75%: Score 80 (accettabile)
- <25%: Score 60 (shallow)
- >75%: Score 35 (too deep)

**Bonus:** +8 se c'è reazione M5 nella direzione

### 5. FTA / Clean Space

**Calcolo:**
```
clean_space_ratio = distanza_entry→FTA / distanza_entry→TP
```

**FTA = primo ostacolo** (swing high/low M5/M15, round number)

**Scoring:**
- >= 80%: Score 100
- 65-79%: Score 80
- 50-64%: Score 60
- 30-49%: Score 35
- < 30%: **REJECT**

**FTA Bonus:** +3 BUY, +5 SELL se >= 80%

### 6. Directional Continuation (BUY only)

**Condizioni (4 punti):**
1. Close M15 > EMA20 M15
2. Nessun close M15 sotto ultimo HL
3. M5 mostra ripresa bullish
4. Ultime 3 M5 highs in aumento

**Scoring:** 4/4=100, 3/4=80, 2/4=60, 0-1/4=35

### 7. Rejection / Failed Push (SELL only)

**Pattern A - Rejection Wick:**
- Candle M5 con upper wick >= 35% range
- Close nel bottom 35%
- Candle successiva bearish

**Pattern B - Failed Push:**
- Prezzo rompe micro high
- Entro 2 candle chiude sotto
- Candle successiva chiude sotto low

**HARD FILTER:** Score < 60 → REJECT

### 8. Session Quality

**Sessioni (UTC):**
- London: 07:00-12:59
- Overlap: 13:00-16:00
- NY: 16:01-20:00
- Asian/Other: resto

**BUY Scores:** Overlap=100, NY=90, London=85, Asian=40
**SELL Scores:** Overlap=100, London=65, NY=60, Asian=20

**SELL in London/NY:** Richiede H1>=80, M15>=75, Rejection>=70

### 9. Market Sanity Check

**Soglie EURUSD:**
- ATR min: 2.5 pips
- ATR max: 18 pips
- Spike max: 12 pips

**Soglie XAUUSD:**
- ATR min: $0.9
- ATR max: $9.0
- Spike max: $4.5

**Scoring:** 100 (healthy), 70 (borderline), 40 (caotico)
**HARD FILTER:** Score < 40 → REJECT

---

## THRESHOLD E CONFIDENCE

### BUY
- **min_confidence:** 62
- **preferred_range:** 68-86
- **hard_cap:** 94

### SELL
- **min_confidence:** 60
- **preferred_range:** 64-80
- **hard_cap:** 90

### Extra Confirmation

**BUY (62-67.99):** H1>=70, Trigger>=70, FTA>=60
**SELL (60-63.99):** H1>=75, Rejection>=70, FTA>=60

---

## SESSION MULTIPLIERS (BUY only)

| Sessione | Multiplier |
|----------|------------|
| London | 1.00 |
| NY | 1.05 |
| Overlap | 1.10 |

---

## FORMULE FINALI

### BUY_SCORE
```
(H1_Structural * 0.20) +
(M15_Structure * 0.18) +
(M5_Trigger * 0.16) +
(Pullback * 0.14) +
(FTA_Clean_Space * 0.14) +
(Directional_Continuation * 0.10) +
(Session * 0.05) +
(Market_Sanity * 0.03)
+ fta_bonus
× session_multiplier
= CLAMP(0, 100)
```

### SELL_SCORE
```
(H1_Structural * 0.22) +
(M15_Structure * 0.20) +
(M5_Trigger * 0.16) +
(Pullback * 0.12) +
(Rejection_Failed_Push * 0.14) +
(FTA_Clean_Space * 0.10) +
(Session * 0.04) +
(Market_Sanity * 0.02)
+ fta_bonus
= CLAMP(0, 100)
```

---

## FILTRI E REJECTION

| # | Filtro | Blocca | Reason |
|---|--------|--------|--------|
| 1 | H1 < 60 (BUY) / < 65 (SELL) | Direzione | h1_weak |
| 2 | Trigger < 60 | Entrambi | weak_trigger |
| 3 | Impulso troppo piccolo | Entrambi | impulse_too_small |
| 4 | SELL rejection < 60 | SELL | sell_rejection_missing |
| 5 | FTA clean space < 30% | Entrambi | fta_blocked |
| 6 | Market sanity < 40 | Entrambi | market_not_sane |
| 7 | Session Asian (BUY) | BUY | buy_session_blocked |
| 8 | Session Asian (SELL) | SELL | sell_session_blocked |
| 9 | Concentration 2+ same dir | Entrambi | asset_direction_overconcentrated |
| 10 | Duplicate zona | Entrambi | duplicate |
| 11 | R:R < 1.15 | Entrambi | low_rr |
| 12 | Score < threshold | Entrambi | confidence_below_threshold |
| 13 | Extra confirm failed | Entrambi | extra_confirmation_failed |

---

## CONCENTRATION (Solo Filtro)

**NON fa parte dello score.**

**Regole:**
- 2+ segnali stesso asset/direzione in 25 min → REJECT
- Segnale stesso asset/direzione/zona in 25 min → REJECT (duplicate)

**Zone:**
- EURUSD: 12 pips
- XAUUSD: $3.0

---

## HELPER FILES

### `/app/backend/services/helpers/technical_indicators.py`

Funzioni pure per calcoli tecnici:
- `calculate_ema(candles, period)`
- `calculate_ema_slope(candles, period, lookback)`
- `calculate_atr(candles, period)`
- `find_swing_points(candles, lookback)`
- `get_pullback_depth(price, high, low, direction)`
- `is_rejection_candle(candle, direction, min_wick_ratio)`
- `is_bullish_candle(candle)` / `is_bearish_candle(candle)`

---

*Documentazione v10.0 - Aprile 2026*

### Flusso Completo Step-by-Step

```
1. ARRIVO DATI DI MERCATO
   └── market_data_cache.get_candles(asset, timeframe)
       └── Provider: Twelve Data API
       └── Timeframes: H1, M15, M5
       └── Candles per TF: ~100 ultime

2. PREPROCESSING / NORMALIZZAZIONE
   └── ATR calculation (14 periodi)
   └── Spread calculation (bid/ask)
   └── Session detection (London/NY/Overlap/Asian)
   └── News risk check (scheduled events)

3. CALCOLO FATTORI CHECKLIST
   └── _score_h1_bias() → 0-100
   └── _score_m15_context() → 0-100
   └── _score_mtf_alignment() → 0-100
   └── _score_momentum() → 0-100
   └── _score_pullback_advanced() → 0-100
   └── _score_market_structure() → 0-100
   └── _score_session_soft() → 0-100
   └── _score_volatility() → 0-100
   └── _score_market_regime() → 0-100
   └── _check_asset_concentration() → 0-100

4. CALCOLO SCORE
   └── Selezione pesi: WEIGHTS_BUY o WEIGHTS_SELL
   └── final_score = Σ (score_i × weight_i / 100)
   └── Range output: 0-100

5. APPLICAZIONE BONUS / PENALTIES
   └── FTA bonus: +3/+5 se clean_space_ratio >= 0.80
   └── News penalty: -5/-15 se evento imminente
   └── Session multiplier (solo BUY): ×1.08 NY, ×1.12 Overlap
   └── MTF penalty: -0.15 per punto sotto 75

6. APPLICAZIONE FILTRI / GATING RULES
   └── Session filter (SELL solo Overlap)
   └── Structural filter (SELL: H1>=70, Conc>=60, PB>=55)
   └── Confidence threshold (BUY>=64, SELL>=58)
   └── Hard cap (BUY<=92, SELL<=78 altrimenti REJECT)
   └── R:R minimum (>=1.1)
   └── Duplicate check (25 min, 15 pips)
   └── MTF hard block (<60)

7. DECISIONE FINALE
   ├── ACCEPTED → passa tutti i filtri
   ├── REJECTED → fallisce un filtro (log reason)
   └── ACTIVE → segnale accettato e notificato

8. SALVATAGGIO DATI
   └── signal_snapshot_service.save_snapshot()
   └── candidate_audit_service.record_candidate()
   └── Storage: /app/backend/storage/*.json

9. INVIO NOTIFICA
   └── fcm_push_service.send_to_all_devices()
   └── to_notification_dict() formatta payload
   └── Token management (rimuove invalidi)
```

---

## PARTE 2 — FILE E FUNZIONI REALI COINVOLTE

### File Principale (PRODUZIONE)
```
/app/backend/services/signal_generator_v3.py
└── Classe: SignalGeneratorV3
└── Linee: ~3900
└── Status: UNICO motore attivo
```

### File di Supporto Attivi
| File | Scopo |
|------|-------|
| `market_data_cache.py` | Cache dati OHLC da Twelve Data |
| `market_validator.py` | Verifica orari forex aperti |
| `session_detector.py` | Rileva sessione corrente |
| `signal_snapshot_service.py` | Salva snapshot segnali |
| `candidate_audit_service.py` | Audit trail candidati |
| `fcm_push_service.py` | Invio push notifications |
| `device_storage_service.py` | Gestione token dispositivi |
| `direction_quality_audit.py` | Audit direzione qualità |

### File Legacy (NON USATI)
```
/app/backend/services/market_scanner.py → DISABILITATO
/app/backend/services/advanced_scanner.py → DISABILITATO
/app/backend/services/signal_orchestrator.py → DISABILITATO
```

### Funzioni Principali in Ordine di Chiamata

| Funzione | Scopo | Input | Output |
|----------|-------|-------|--------|
| `start()` | Avvia scanner loop | - | Task async |
| `_scanner_loop()` | Loop principale ogni 5s | - | - |
| `_scan_all_assets()` | Scansiona EURUSD/XAUUSD | - | - |
| `_analyze_asset()` | Analisi completa asset | Asset, candles, spread | GeneratedSignal o None |
| `_analyze_direction_advanced()` | Determina BUY/SELL | H1,M15,M5 candles | direction, score, reason |
| `_calculate_structural_levels()` | Calcola SL/TP | Asset, direction, candles | StructuralLevels |
| `_calculate_fta()` | First Trouble Area | Candles, entry, TP | FirstTroubleArea |
| `_score_*()` | Scoring singolo fattore | Candles specifici | (score, reason) |
| `_process_signal()` | Invia notifica | GeneratedSignal | - |

---

## PARTE 3 — DATI USATI DAL MOTORE

### Provider Dati
```
Twelve Data API
- Endpoint: time_series (OHLC)
- Rate: ~800 calls/giorno (piano base)
- Latenza: 1-3 secondi
```

### Simboli Usati
```python
ALLOWED_ASSETS = [Asset.EURUSD, Asset.XAUUSD]
```

### Timeframe Scaricati
| Timeframe | Candles | Uso |
|-----------|---------|-----|
| H1 | ~100 | Bias direzionale, trend principale |
| M15 | ~100 | Contesto, allineamento |
| M5 | ~100 | Entry, momentum, struttura |

### Formato Dati
```python
{
    "datetime": "2026-04-09 14:30:00",
    "open": 1.08234,
    "high": 1.08256,
    "low": 1.08220,
    "close": 1.08245
}
```

### Campi Usati
- `open`, `high`, `low`, `close` → SEMPRE usati
- `volume` → NON usato
- `bid/ask` → Usato solo per spread (quando disponibile)
- `spread` → Calcolato da bid/ask o stimato

### Indicatori Derivati Calcolati
| Indicatore | Funzione | Periodo |
|------------|----------|---------|
| ATR | `_calculate_atr()` | 14 candles |
| Trend | `_get_trend()` | 5-20 candles |
| Momentum | `_get_momentum()` | 3-10 candles |
| Swing Points | `_find_swing_points_list()` | 5 candles lookback |

---

## PARTE 4 — CHECKLIST COMPLETA DEI FATTORI (SCHEDE DETTAGLIATE)

### FATTORE 1: H1 Directional Bias

| Campo | Valore |
|-------|--------|
| **Nome** | H1 Directional Bias |
| **Cosa misura** | Direzione del trend sul timeframe H1 |
| **Dati base** | Ultime 10 candle H1 |
| **Timeframe** | H1 |
| **Calcolo** | `_get_trend(h1[-10:])` → media prime 5 vs ultime 5 close |
| **Score alto** | trend > 0.5 (BUY) o trend < -0.5 (SELL) → 100 |
| **Score basso** | trend opposto alla direzione → 25 |
| **Peso BUY** | 22% |
| **Peso SELL** | 30% (DOMINANTE) |
| **Range** | 25-100 |
| **Esempio alto** | H1 con 8/10 candle bullish consecutive → "Strong H1 bullish" |
| **Esempio basso** | H1 in ranging → "H1 neutral" (40) |
| **Funzione** | `_score_h1_bias()` (riga 3481) |

**Formula esatta:**
```python
trend = (media_ultime_5_close - media_prime_5_close) / media_prime_5_close
trend = max(-1, min(1, trend * 100))

if direction == "BUY":
    if trend > 0.5: return 100, "Strong H1 bullish"
    elif trend > 0.2: return 75, "Moderate H1 bullish"
    elif trend > 0: return 60, "Weak H1 bullish"
    elif trend > -0.2: return 40, "H1 neutral"
    else: return 25, "H1 bearish"
```

---

### FATTORE 2: M15 Context

| Campo | Valore |
|-------|--------|
| **Nome** | M15 Context |
| **Cosa misura** | Allineamento trend + momentum su M15 |
| **Dati base** | Ultime 8 candle M15 (trend) + ultime 4 (momentum) |
| **Timeframe** | M15 |
| **Calcolo** | `_get_trend(m15[-8:])` + `_get_momentum(m15[-4:])` |
| **Score alto** | Trend E momentum entrambi allineati → 90 |
| **Score basso** | Nessun allineamento → 35 |
| **Peso BUY** | 18% |
| **Peso SELL** | 3% (MINIMALE - anti-predittivo!) |
| **Range** | 35-90 |
| **Esempio alto** | M15 trend up + 3/4 ultime candle bullish → 90 |
| **Esempio basso** | M15 trend down ma momentum up → 35 |
| **Funzione** | `_score_m15_context()` (riga 3507) |

**Formula esatta:**
```python
trend = _get_trend(m15[-8:])
momentum = _get_momentum(m15[-4:])

aligned = (direction == "BUY" and trend > 0) or (direction == "SELL" and trend < 0)
mom_aligned = (direction == "BUY" and momentum > 0) or (direction == "SELL" and momentum < 0)

if aligned and mom_aligned: return 90, "M15 trend + momentum aligned"
elif aligned: return 70, "M15 trend aligned"
elif mom_aligned: return 55, "M15 momentum aligned"
else: return 35, "M15 not aligned"
```

---

### FATTORE 3: MTF Alignment

| Campo | Valore |
|-------|--------|
| **Nome** | MTF Alignment |
| **Cosa misura** | Allineamento direzionale H1 + M15 + M5 |
| **Dati base** | Ultime 15 candle di ogni TF |
| **Timeframe** | H1, M15, M5 (combinati) |
| **Calcolo** | Conta quanti TF sono allineati alla direzione |
| **Score alto** | Tutti e 3 allineati → 100 |
| **Score basso** | Nessuno o 1 solo allineato → 20-40 |
| **Peso BUY** | 12% |
| **Peso SELL** | 6% (ridotto - anti-predittivo) |
| **Range** | 20-100 |
| **Esempio alto** | H1 bullish + M15 bullish + M5 bullish → 100 |
| **Esempio basso** | H1 bullish ma M15/M5 bearish → 40 |
| **Funzione** | `_score_mtf_alignment()` (riga 3349) |

**Formula esatta:**
```python
h1_trend = _get_trend(h1[-15:])
m15_trend = _get_trend(m15[-15:])
m5_trend = _get_trend(m5[-15:])

is_buy = direction == "BUY"
h1_aligned = (h1_trend > 0) == is_buy
m15_aligned = (m15_trend > 0) == is_buy
m5_aligned = (m5_trend > 0) == is_buy

aligned_count = sum([h1_aligned, m15_aligned, m5_aligned])

if aligned_count == 3: return 100, "All timeframes aligned"
elif aligned_count == 2:
    if h1_aligned and m15_aligned: return 80, "H1 + M15 aligned"
    return 65, "Partial alignment"
elif aligned_count == 1: return 40, "Weak alignment"
else: return 20, "Conflicting timeframes"
```

---

### FATTORE 4: Momentum

| Campo | Valore |
|-------|--------|
| **Nome** | Momentum |
| **Cosa misura** | Forza direzionale recente su M5 |
| **Dati base** | Ultime 5 candle M5 |
| **Timeframe** | M5 |
| **Calcolo** | Conta candle bullish vs bearish nelle ultime 5 |
| **Score alto** | 4-5 candle nella direzione → 95 |
| **Score basso** | Momentum opposto alla direzione → 30 |
| **Peso BUY** | 16% (AUMENTATO - best predictor) |
| **Peso SELL** | 4% (ridotto) |
| **Range** | 30-95 |
| **Esempio alto** | 5/5 candle M5 bullish → "Strong bullish momentum" |
| **Esempio basso** | 4/5 candle bearish in setup BUY → 30 |
| **Funzione** | `_score_momentum()` (riga 3559) |

**Formula esatta:**
```python
# _get_momentum() conta candle bullish/bearish
bullish_count = sum(1 for o, c in zip(opens, closes) if c > o)
momentum = (bullish_count - (5 - bullish_count)) / 5  # Range: -1 to +1

if direction == "BUY":
    if momentum > 0.6: return 95, "Strong bullish momentum"  # 4-5 bullish
    elif momentum > 0.3: return 75, "Moderate bullish"       # 3-4 bullish
    elif momentum > 0: return 55, "Weak bullish"             # 3 bullish
    else: return 30, "Bearish momentum"                      # <3 bullish
```

---

### FATTORE 5: Pullback Quality

| Campo | Valore |
|-------|--------|
| **Nome** | Pullback Quality |
| **Cosa misura** | Qualità del ritracciamento prima dell'entry |
| **Dati base** | Ultime 20 candle M5 + prezzo corrente |
| **Timeframe** | M5 |
| **Calcolo** | Posizione del prezzo nel range (Fibonacci) |
| **Score alto** | Ritracciamento 38-62% + ripresa → 95-100 |
| **Score basso** | Ritracciamento troppo profondo (>75%) → 35 |
| **Peso BUY** | 5% (ridotto) |
| **Peso SELL** | 12% |
| **Range** | 35-100 |
| **Esempio alto** | Prezzo a 50% del range + ultime 3 candle in ripresa → 95+ |
| **Esempio basso** | Prezzo ha ritracciato oltre 75% del movimento → 35 |
| **Funzione** | `_score_pullback_advanced()` (riga 3372) |

**Formula esatta:**
```python
recent_high = max(highs[-20:])
recent_low = min(lows[-20:])
swing_range = recent_high - recent_low

if direction == "BUY":
    from_high = (recent_high - current_price) / swing_range
    
    if 0.382 <= from_high <= 0.618: base_score = 95  # Zona Fib ideale
    elif 0.25 <= from_high <= 0.75: base_score = 75   # Zona accettabile
    elif from_high < 0.25: base_score = 45            # Shallow pullback
    else: base_score = 35                              # Deep pullback

# Bonus se ultime 3 candle mostrano ripresa
if last_3[-1].close > last_3[0].open:
    base_score += 8
```

---

### FATTORE 6: Session Quality

| Campo | Valore |
|-------|--------|
| **Nome** | Session Quality |
| **Cosa misura** | Qualità della sessione di trading corrente |
| **Dati base** | Ora UTC corrente |
| **Timeframe** | N/A (basato su orario) |
| **Calcolo** | Mappatura ora UTC → sessione |
| **Score alto** | London/NY Overlap (13-16 UTC) → 100 |
| **Score basso** | Asian (3-6 UTC) → 40 |
| **Peso BUY** | 10% |
| **Peso SELL** | 20% (ALTO - Overlap critical!) |
| **Range** | 40-100 |
| **Esempio alto** | Trade alle 14:30 UTC → "London/NY overlap" (100) |
| **Esempio basso** | Trade alle 4:00 UTC → "Asian session" (40) |
| **Funzione** | `_score_session_soft()` (riga 3427) |

**Formula esatta:**
```python
hour = datetime.utcnow().hour

if 13 <= hour <= 16: return 100, "London/NY overlap"
elif 7 <= hour <= 12: return 90, "London session"
elif 13 <= hour <= 20: return 85, "NY session"
elif 21 <= hour <= 23 or 0 <= hour <= 2: return 55, "Transition hours"
elif 3 <= hour <= 6: return 40, "Asian session"
else: return 45, "Off-peak hours"
```

---

### FATTORE 7: Concentration

| Campo | Valore |
|-------|--------|
| **Nome** | Concentration |
| **Cosa misura** | Concentrazione segnali recenti sullo stesso asset |
| **Dati base** | Lista ultimi 5 segnali |
| **Timeframe** | N/A (storico segnali) |
| **Calcolo** | Conta segnali stesso asset negli ultimi N |
| **Score alto** | Nessuna concentrazione → 100 |
| **Score basso** | 4+ segnali stesso asset → penalizzato |
| **Peso BUY** | 14% |
| **Peso SELL** | 22% (BEST SELL predictor!) |
| **Range** | 50-100 |
| **Esempio alto** | 1 solo segnale XAUUSD negli ultimi 5 → 100 |
| **Esempio basso** | 4 segnali XAUUSD consecutivi → 50 |
| **Funzione** | `_check_asset_concentration()` |

---

### FATTORE 8: Volatility

| Campo | Valore |
|-------|--------|
| **Nome** | Volatility |
| **Cosa misura** | Volatilità corrente vs media |
| **Dati base** | ATR corrente vs ATR medio |
| **Timeframe** | M5 (14 periodi) |
| **Calcolo** | ratio = ATR_corrente / ATR_medio |
| **Score alto** | Volatilità normale (0.8-1.5x) → 90 |
| **Score basso** | Volatilità estrema (<0.5x o >2x) → 40 |
| **Peso BUY** | 1% (minimale) |
| **Peso SELL** | 1% (minimale) |
| **Range** | 40-90 |
| **Funzione** | `_score_volatility()` (riga 3605) |

---

### FATTORE 9: Market Regime

| Campo | Valore |
|-------|--------|
| **Nome** | Market Regime |
| **Cosa misura** | Stato del mercato (trending/ranging/chaotic) |
| **Dati base** | ATR ratio + direzionalità movimento |
| **Timeframe** | M5 (ultime 10 candle) |
| **Calcolo** | Combina ATR ratio con movimento direzionale |
| **Score alto** | Strong trending (ATR alto + movimento direzionale) → 95 |
| **Score basso** | Low activity → 40 |
| **Peso BUY** | 2% (minimale) |
| **Peso SELL** | 2% (minimale) |
| **Range** | 40-95 |
| **Funzione** | `_score_market_regime()` (riga 3618) |

**Formula esatta:**
```python
atr_ratio = atr / avg_atr
directional_move = abs(second_half_avg - first_half_avg) / avg_range

if atr_ratio >= 1.2 and directional_move > 1.5: return 95, "Strong trending"
elif atr_ratio >= 0.9 and directional_move > 1.0: return 85, "Healthy trend"
elif atr_ratio >= 0.7: return 70, "Normal regime"
elif atr_ratio >= 0.5: return 50, "Mixed regime"
else: return 40, "Low activity"
```

---

## PARTE 5 — SCORE ENGINE

### Formula Esatta BUY
```
BUY_SCORE = 
    (H1_score × 0.22) +
    (M15_score × 0.18) +
    (Momentum_score × 0.16) +
    (Concentration_score × 0.14) +
    (MTF_score × 0.12) +
    (Session_score × 0.10) +
    (Pullback_score × 0.05) +
    (Regime_score × 0.02) +
    (Volatility_score × 0.01)

# Dopo calcolo base:
+ FTA_bonus (0/+1/+2/+3 se clean_space >= 0.50)
- News_penalty (0/-5/-15)
× Session_multiplier (1.00/1.08/1.12)
- MTF_penalty (se MTF < 75: -0.15 per punto)
= CLAMP(0, 100)
```

### Formula Esatta SELL
```
SELL_SCORE = 
    (H1_score × 0.30) +
    (Concentration_score × 0.22) +
    (Session_score × 0.20) +
    (Pullback_score × 0.12) +
    (MTF_score × 0.06) +
    (Momentum_score × 0.04) +
    (M15_score × 0.03) +
    (Regime_score × 0.02) +
    (Volatility_score × 0.01)

# Dopo calcolo base:
+ FTA_bonus (0/+2/+5 se clean_space >= 0.50)
- News_penalty (0/-5/-15)
# NO session multiplier per SELL
= CLAMP(0, 100)
```

### Ordine Esatto di Applicazione
```
1. Calcolo score base (somma pesata fattori)
2. Valutazione FTA contextual (può bloccare)
3. Applicazione FTA bonus (+3/+5 se favorevole)
4. Applicazione News penalty
5. Applicazione Session multiplier (solo BUY)
6. Applicazione MTF penalty (se <75)
7. CLAMP score a [0, 100]
8. Controllo threshold direction-specific
9. Controllo hard cap (BUY ≤92, SELL ≤78)
```

### Soglie Attuali

| Parametro | BUY | SELL |
|-----------|-----|------|
| MIN_CONFIDENCE | 64 | 58 |
| PREFERRED_RANGE | 68-85 | 58-72 |
| HARD_CAP | 92 | 78 (REJECT sopra!) |
| EXTRA_CONFIRM_RANGE | 64-67.99 | 58-62.99 |

---

## PARTE 6 — FILTRI E REJECTION LOGIC

### Lista Completa Filtri

| # | Nome | Controllo | Blocca | Reason |
|---|------|-----------|--------|--------|
| 1 | Session SELL | session ∉ Overlap | SELL | "SELL blocked outside overlap" |
| 2 | Session BUY | session ∉ [London,NY,Overlap] | BUY | "buy_session_blocked" |
| 3 | Structural SELL | H1<70 OR Conc<60 OR PB<55 | SELL | "SELL weak structure" |
| 4 | Confidence Low BUY | score < 64 | BUY | "BUY confidence below threshold" |
| 5 | Confidence Low SELL | score < 58 | SELL | "SELL confidence below threshold" |
| 6 | Confidence High SELL | score > 78 | SELL | "SELL confidence too high / distorted zone" |
| 7 | Extra Confirm BUY | score 64-67 senza H1≥70 + Mom≥60 | BUY | "BUY missing directional confirmation" |
| 8 | Extra Confirm SELL | score 58-62 senza H1≥75 + Conc≥65 | SELL | "SELL low confidence weak" |
| 9 | R:R Low | R:R < 1.1 | Entrambi | "low_rr" |
| 10 | MTF Weak | MTF score < 60 | Entrambi | "weak_mtf" |
| 11 | Duplicate | Stesso asset/dir/zona in 25 min | Entrambi | "duplicate" |
| 12 | FTA Block | clean_space < 0.3 (contextual) | Entrambi | "fta_blocked" |
| 13 | Spread High | spread > 3 pips EURUSD | EURUSD | "high_spread" |
| 14 | News High | evento in <30 min | Entrambi | "news_blocked" |

---

## PARTE 7 — ESEMPI CONCRETI DI TRADE

### Esempio 1: BUY ACCEPTED

```
=== XAUUSD BUY - 9 Apr 2026 14:32 UTC ===

DATI MERCATO:
- Prezzo: 4765.50
- Spread: 28 pips
- Sessione: London/NY Overlap
- ATR M5: 4.2

FATTORI CALCOLATI:
- H1 Directional Bias: 85 (Moderate H1 bullish) × 22% = 18.7
- M15 Context: 90 (trend + momentum aligned) × 18% = 16.2
- Momentum: 75 (Moderate bullish) × 16% = 12.0
- Concentration: 100 (No concentration) × 14% = 14.0
- MTF Alignment: 80 (H1 + M15 aligned) × 12% = 9.6
- Session Quality: 100 (London/NY overlap) × 10% = 10.0
- Pullback Quality: 75 (Good pullback zone) × 5% = 3.75
- Market Regime: 85 (Healthy trend) × 2% = 1.7
- Volatility: 90 (Normal) × 1% = 0.9

SCORE BASE: 86.85

BONUS/PENALTIES:
+ FTA bonus: +3 (clean_space 0.82)
- News: 0
× Session multiplier: ×1.12 (Overlap)

SCORE FINALE: (86.85 + 3) × 1.12 = 100.6 → CLAMPED a 92 (hard cap)

FILTRI:
✅ Session OK (Overlap)
✅ Confidence 92 ≥ 64
✅ Hard cap applicato (92 ≤ 92)
✅ R:R 1.52 ≥ 1.1
✅ MTF 80 ≥ 60
✅ No duplicate

→ ACCEPTED (acceptance_source: "buy_strong")
```

### Esempio 2: SELL REJECTED

```
=== EURUSD SELL - 9 Apr 2026 10:15 UTC ===

DATI MERCATO:
- Prezzo: 1.08234
- Spread: 1.1 pips
- Sessione: London (NON Overlap!)
- ATR M5: 0.00045

FILTRO APPLICATO:
❌ Session = "London" ∉ ["London/NY Overlap", "Overlap"]

→ REJECTED immediatamente
→ Reason: "SELL blocked outside overlap"

(Il resto del calcolo non viene nemmeno eseguito)
```

### Esempio 3: SELL REJECTED (Distorted Zone)

```
=== XAUUSD SELL - 9 Apr 2026 14:45 UTC ===

DATI MERCATO:
- Sessione: London/NY Overlap ✓

FATTORI CALCOLATI:
- H1 Directional: 95 × 30% = 28.5
- Concentration: 90 × 22% = 19.8
- Session: 100 × 20% = 20.0
- Pullback: 85 × 12% = 10.2
- MTF: 90 × 6% = 5.4
- ... altri

SCORE BASE: 89.5

FILTRI:
✅ Session OK
✅ Structural filter: H1=95≥70, Conc=90≥60, PB=85≥55
❌ Score 89.5 > SELL_HARD_CAP (78)

→ REJECTED
→ Reason: "SELL confidence too high / distorted zone"
```

### Esempio 4: SELL ACCEPTED

```
=== XAUUSD SELL - 9 Apr 2026 15:20 UTC ===

DATI MERCATO:
- Prezzo: 4758.30
- Sessione: London/NY Overlap ✓

FATTORI CALCOLATI:
- H1 Directional: 75 (Moderate bearish) × 30% = 22.5
- Concentration: 80 × 22% = 17.6
- Session: 100 × 20% = 20.0
- Pullback: 70 × 12% = 8.4
- MTF: 65 × 6% = 3.9
- Momentum: 55 × 4% = 2.2
- M15: 55 × 3% = 1.65
- Regime: 70 × 2% = 1.4
- Volatility: 90 × 1% = 0.9

SCORE BASE: 68.55 + FTA_bonus(+5) = 73.55

FILTRI:
✅ Session = Overlap
✅ Structural: H1=75≥70, Conc=80≥60, PB=70≥55
✅ Score 73.55 in range [58, 78]
✅ R:R 1.45 ≥ 1.1
✅ No duplicate

→ ACCEPTED (acceptance_source: "sell_preferred")
```

---

## PARTE 8 — GLOSSARIO TECNICO

| Termine | Significato |
|---------|-------------|
| **ATR** | Average True Range - misura volatilità (14 periodi) |
| **FTA** | First Trouble Area - primo ostacolo tecnico tra entry e TP |
| **MTF** | Multi-TimeFrame - allineamento H1+M15+M5 |
| **R:R** | Risk/Reward ratio - reward/risk |
| **Structural SL** | Stop Loss basato su swing point |
| **Clean Space** | Rapporto distanza_FTA / distanza_TP |
| **Concentration** | Densità segnali stesso asset |
| **Buffer Zone** | Range score 60-64 (richiede extra confirm) |
| **Hard Cap** | Limite massimo score (BUY 92, SELL 78) |
| **Distorted Zone** | SELL con score >78 (anti-predittivo) |
| **Session Multiplier** | Bonus moltiplicativo per sessione (solo BUY) |
| **Overlap** | London/NY Overlap (13-16 UTC) |

---

## APPENDICE: PESI COMPLETI v9.1

### BUY WEIGHTS (sum = 100%)
```
h1_bias: 22%
m15_context: 18%
momentum: 16%
concentration: 14%
mtf_alignment: 12%
session: 10%
pullback_quality: 5%
regime_quality: 2%
volatility: 1%
```

### SELL WEIGHTS (sum = 100%)
```
h1_bias: 30%
concentration: 22%
session: 20%
pullback_quality: 12%
mtf_alignment: 6%
momentum: 4%
m15_context: 3%
regime_quality: 2%
volatility: 1%
```

---

*Documentazione generata automaticamente dal codice sorgente di signal_generator_v3.py*
