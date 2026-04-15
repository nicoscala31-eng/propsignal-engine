# DEFINIZIONI TECNICHE COMPLETE - PROPSIGNAL ENGINE v11.0

**Versione:** 11.0  
**Data:** Aprile 2026  
**Obiettivo:** Documentazione matematica completa per rendere ogni score riproducibile

---

## INDICE DEI FATTORI

| # | Fattore | Peso BUY | Peso SELL | Output |
|---|---------|----------|-----------|--------|
| 1 | H1 Directional Bias | 20% | 20% | 0-100 |
| 2 | M15 Trend Quality | 8% | 8% | 0-100 |
| 3 | M15 Extension Penalty | PENALTY | PENALTY | 0 to -18 |
| 4 | M5 Trigger Quality | 18% | 18% | 0-100 |
| 5 | Pullback Quality | 8% | 8% | 0-100 |
| 6 | FTA / Clean Space | 12% | 12% | 0-100 (+ reject) |
| 7 | Directional Continuation | 14% | 0% (BUY only) | 0-100 |
| 8 | Rejection Failed Push | 0% | 14% (SELL only) | 0-100 |
| 9 | Session Quality | 14% | 14% | 0-100 |
| 10 | Market Sanity | 6% | 6% | 0-100 (+ reject) |
| 11 | Counter-Trend Penalty | PENALTY | PENALTY | 0 to -18 |

---

## 1. H1 DIRECTIONAL BIAS

### INPUT
- `h1_candles`: Lista OHLC candele H1 (minimo 50 candles)

### LOGICA PASSO-PASSO

```
1. Calcola EMA20_H1:
   EMA = SMA(close[0:20]) iniziale
   multiplier = 2 / (20 + 1) = 0.0952
   Per ogni close successivo:
     EMA = (close - EMA) * multiplier + EMA

2. Calcola EMA50_H1:
   Stessa formula con period=50, multiplier = 0.0392

3. Calcola EMA20_slope:
   ema20_now = EMA20 a candle[-1]
   ema20_prev = EMA20 a candle[-5]
   slope = (ema20_now - ema20_prev) / ema20_prev
   normalized_slope = max(-1, min(1, slope * 100))

4. Trova Swing Highs (ultime 30 candles, lookback=2):
   Per ogni candle[i], è swing high se:
     candle[i].high > candle[i-1].high AND
     candle[i].high > candle[i-2].high AND
     candle[i].high > candle[i+1].high AND
     candle[i].high > candle[i+2].high

5. Trova Swing Lows (stessa logica con .low e <)

6. Valuta condizioni (BUY):
   C1: swing_highs[-1].price > swing_highs[-2].price  # HH
   C2: swing_lows[-1].price > swing_lows[-2].price    # HL
   C3: close > EMA20
   C4: EMA20 > EMA50
   C5: ema20_slope > 0

7. Valuta condizioni (SELL):
   C1: swing_highs[-1].price < swing_highs[-2].price  # LH
   C2: swing_lows[-1].price < swing_lows[-2].price    # LL
   C3: close < EMA20
   C4: EMA20 < EMA50
   C5: ema20_slope < 0
```

### PARAMETRI NUMERICI
- EMA Period 1: 20
- EMA Period 2: 50
- Slope lookback: 5 candles
- Swing point lookback: 2 candles
- Candle range per swings: 30

### OUTPUT (Score Map)
| Condizioni Vere | Score |
|-----------------|-------|
| 5/5 | 100 |
| 4/5 | 85 |
| 3/5 | 70 |
| 2/5 | 50 |
| 1/5 | 30 |
| 0/5 | 30 |

### ESEMPIO REALE (BUY)

```
Dati:
- close = 1.0850
- EMA20 = 1.0840
- EMA50 = 1.0820
- EMA20_slope = +0.15 (positivo)
- swing_highs = [1.0860, 1.0875] → HH (1.0875 > 1.0860) ✓
- swing_lows = [1.0800, 1.0815] → HL (1.0815 > 1.0800) ✓

Condizioni:
- C1 (HH): True ✓
- C2 (HL): True ✓
- C3 (P>EMA20): 1.0850 > 1.0840 = True ✓
- C4 (EMA20>50): 1.0840 > 1.0820 = True ✓
- C5 (Slope+): 0.15 > 0 = True ✓

→ 5/5 condizioni → score = 100
```

---

## 2. M15 TREND QUALITY (v11.0 NEW)

### INPUT
- `m15_candles`: Lista OHLC candele M15 (minimo 50 candles)

### LOGICA PASSO-PASSO

```
1. Calcola EMA20_M15 e EMA50_M15

2. Calcola ATR_M15 (14 periodi):
   TR = max(high-low, |high-prev_close|, |low-prev_close|)
   ATR = SMA(TR, 14)

3. Calcola EMA slopes normalizzate su ATR:
   ema20_values = [EMA20 per ogni candle[-5:]]
   ema20_slope = (ema20[-1] - ema20[0]) / (5 * ATR_M15)
   ema50_slope = (ema50[-1] - ema50[0]) / (5 * ATR_M15)

4. Trova swing points nelle ultime 12 candles

5. Conta HH/HL (BUY) o LH/LL (SELL) negli swing points

6. Valuta condizioni (BUY):
   C1: EMA20 > EMA50
   C2: ema20_slope > +0.03 (ATR-normalized)
   C3: ema50_slope > +0.015 (ATR-normalized)
   C4: close > EMA20
   C5: hh_count >= 2 AND hl_count >= 2

7. Valuta condizioni (SELL):
   C1: EMA20 < EMA50
   C2: ema20_slope < -0.03
   C3: ema50_slope < -0.015
   C4: close < EMA20
   C5: lh_count >= 2 AND ll_count >= 2
```

### PARAMETRI NUMERICI
- EMA Period 1: 20
- EMA Period 2: 50
- ATR Period: 14
- Slope window: 5 candles
- EMA20 slope threshold: ±0.03 ATR/candle
- EMA50 slope threshold: ±0.015 ATR/candle
- Swing count threshold: 2 HH + 2 HL

### OUTPUT (Score Map)
| Condizioni Vere | Score |
|-----------------|-------|
| 5/5 | 100 |
| 4/5 | 85 |
| 3/5 | 70 |
| 2/5 | 55 |
| 1/5 | 40 |
| 0/5 | 25 |

### ESEMPIO REALE (SELL)

```
Dati:
- close = 1.0820
- EMA20 = 1.0835
- EMA50 = 1.0850
- ATR_M15 = 0.0008 (8 pips)
- ema20_slope = -0.05 (normalizzato ATR)
- ema50_slope = -0.02 (normalizzato ATR)
- swing_highs = [1.0880, 1.0860, 1.0845] → LH count = 2
- swing_lows = [1.0830, 1.0815, 1.0800] → LL count = 2

Condizioni:
- C1 (EMA20<50): True ✓
- C2 (slope -0.05 < -0.03): True ✓
- C3 (slope -0.02 < -0.015): True ✓
- C4 (P<EMA20): True ✓
- C5 (2 LH + 2 LL): True ✓

→ 5/5 condizioni → score = 100
```

---

## 3. M15 EXTENSION PENALTY (v11.0 NEW)

### INPUT
- `m15_candles`: Lista OHLC candele M15 (minimo 20 candles)

### LOGICA

```
1. Calcola EMA20_M15

2. Calcola ATR_M15 (14 periodi)

3. Calcola extension_ratio:
   extension = abs(close - EMA20)
   extension_ratio = extension / ATR

4. Applica penalty:
   if ratio <= 0.8: penalty = 0 (normal)
   if 0.8 < ratio <= 1.2: penalty = -3 (slightly extended)
   if 1.2 < ratio <= 1.6: penalty = -7 (extended)
   if 1.6 < ratio <= 2.0: penalty = -12 (overextended)
   if ratio > 2.0: penalty = -18 (severely overextended)
```

### PARAMETRI NUMERICI
| Extension Ratio | Penalty | Label |
|-----------------|---------|-------|
| ≤ 0.8 ATR | 0 | normal |
| 0.8-1.2 ATR | -3 | slightly_extended |
| 1.2-1.6 ATR | -7 | extended |
| 1.6-2.0 ATR | -12 | overextended |
| > 2.0 ATR | -18 | severely_overextended |

### OUTPUT
- Range: 0 to -18
- Type: PENALTY (sottratto dal raw_quality_score)

### ESEMPIO REALE

```
Dati:
- close = 1.0880
- EMA20 = 1.0850
- ATR_M15 = 0.0008 (8 pips)

Calcolo:
- extension = |1.0880 - 1.0850| = 0.0030 (30 pips)
- extension_ratio = 0.0030 / 0.0008 = 3.75

→ 3.75 > 2.0 → penalty = -18 (severely overextended)
```

---

## 4. M5 TRIGGER QUALITY

### INPUT
- `m5_candles`: Lista OHLC candele M5 (minimo 15 candles)

### LOGICA (BUY)

```
Pattern A - Break-and-Hold:
1. micro_highs = [high per candle in m5[-10:-2]]
2. highest_micro = max(micro_highs)
3. Se close[-2] > highest_micro AND close[-1] > highest_micro:
   → trigger = True, strength = 95, type = "Break-and-hold"

Pattern B - EMA20 Reclaim:
1. Calcola EMA20_M5
2. below_ema = any(candle.low < EMA20 per candle in last_5[:-1])
3. current_above = close[-1] > EMA20
4. Se below_ema AND current_above:
   → trigger = True, strength = 75, type = "EMA20 Reclaim"

Pattern C - Strong Bullish Continuation:
1. ranges = [high - low per candle in last_5]
2. avg_range = mean(ranges)
3. candle_range = last_candle.high - last_candle.low
4. is_strong = candle_range >= 0.6 * avg_range
5. is_bullish = close > open
6. Se is_bullish AND is_strong:
   → trigger = True, strength = 65
7. Se is_bullish (not strong):
   → trigger = True, strength = 55
```

### LOGICA (SELL)

```
Pattern A - Rejection:
1. Per ogni candle in last_3:
   upper_wick = high - max(open, close)
   wick_ratio = upper_wick / (high - low)
   close_position = (close - low) / (high - low)
   
2. Se wick_ratio >= 0.25 AND close_position <= 0.40:
   Se wick_ratio >= 0.35 AND close_position <= 0.30:
     → strength = 90, type = "Strong rejection"
   Altrimenti:
     → strength = 70, type = "Rejection"

Pattern B - Failed Push:
1. micro_highs = [high per candle in m5[-10:-4]]
2. highest_micro = max(micro_highs)
3. Per ogni candle in last_4:
   Se candle.high > highest_micro:
     subsequent = candles dopo questo
     Se all(c.close < highest_micro per c in subsequent):
       → strength = 75, type = "Failed push"

Pattern C - Bearish Continuation:
(Speculare al BUY con is_bearish)
→ strength = 65 (strong) o 55 (weak)
```

### PARAMETRI NUMERICI
- Break-and-hold lookback: 10 candles
- EMA Period: 20
- Rejection wick min ratio: 0.25 (relaxed from 0.35)
- Rejection close max position: 0.40 (relaxed from 0.35)
- Strong candle ratio: 0.60 of avg_range
- Failed push lookback: 10 candles

### OUTPUT (Score by Pattern)
| Pattern | Score |
|---------|-------|
| Break-and-hold | 95 |
| Strong rejection | 90 |
| Rejection | 70 |
| EMA20 Reclaim | 75 |
| Failed push | 75 |
| Strong continuation | 65 |
| Weak continuation | 55 |
| No trigger | 30 |

### ESEMPIO REALE (SELL - Rejection)

```
Dati candle:
- open = 1.0855
- high = 1.0870
- low = 1.0840
- close = 1.0845

Calcolo:
- upper_wick = 1.0870 - 1.0855 = 0.0015
- candle_range = 1.0870 - 1.0840 = 0.0030
- wick_ratio = 0.0015 / 0.0030 = 0.50 (≥ 0.35)
- close_position = (1.0845 - 1.0840) / 0.0030 = 0.167 (≤ 0.30)

→ Strong rejection → score = 90
```

---

## 5. PULLBACK QUALITY

### INPUT
- `m15_candles`: Lista OHLC M15 (minimo 30 candles)
- `m5_candles`: Lista OHLC M5
- `direction`: "BUY" o "SELL"
- `current_price`: Prezzo attuale
- `asset`: EURUSD o XAUUSD

### LOGICA

```
1. Trova swing points su M15[-30:]

2. Calcola impulse leg (BUY):
   impulse_low = min(swing_lows)
   impulse_high = max(swing_highs)
   impulse_size = impulse_high - impulse_low

3. Verifica impulse minimo:
   EURUSD: impulse_size >= 0.0012 (12 pips)
   XAUUSD: impulse_size >= 4.0 ($4)
   Se < minimo → REJECT (score = 0, is_valid = False)

4. Calcola pullback depth (BUY):
   pullback = impulse_high - current_price
   depth = pullback / impulse_size

5. Score by Fibonacci zone:
   0.382 <= depth <= 0.618 → base_score = 100 (Ideal Fib)
   0.25 <= depth <= 0.75 → base_score = 80 (Good zone)
   depth < 0.25 → base_score = 60 (Shallow)
   depth > 0.75 → base_score = 35 (Too deep)

6. Bonus reaction:
   Se last_m5 bullish (BUY) o bearish (SELL):
     base_score += 8 (max 100)
```

### PARAMETRI NUMERICI
- Swing lookback: 30 candles
- EURUSD impulse min: 12 pips (0.0012)
- XAUUSD impulse min: $4
- Ideal Fib zone: 38.2% - 61.8%
- Good zone: 25% - 75%
- Reaction bonus: +8

### OUTPUT
| Depth Zone | Score |
|------------|-------|
| 38-62% (Ideal Fib) | 100 |
| 25-75% (Good) | 80 |
| < 25% (Shallow) | 60 |
| > 75% (Too deep) | 35 |
| + Reaction | +8 |
| Impulse too small | REJECT |

### ESEMPIO REALE (BUY)

```
Dati:
- swing_low = 1.0780
- swing_high = 1.0850
- current_price = 1.0820
- last_m5 = bullish candle

Calcolo:
- impulse_size = 1.0850 - 1.0780 = 0.0070 (70 pips) ≥ 12 pips ✓
- pullback = 1.0850 - 1.0820 = 0.0030
- depth = 0.0030 / 0.0070 = 0.428 (42.8%)

→ 0.382 <= 0.428 <= 0.618 → Ideal Fib → score = 100
→ + bullish reaction → score = 100 (già max)
```

---

## 6. FTA / CLEAN SPACE

### INPUT
- `m15_candles`, `m5_candles`: Liste OHLC
- `entry_price`: Prezzo entry proposto
- `take_profit`: Prezzo TP proposto
- `direction`: "BUY" o "SELL"
- `trigger_score`: Score del trigger (per exception)
- `asset`: EURUSD o XAUUSD

### LOGICA

```
1. Calcola ATR_M5 (14 periodi)

2. Calcola FTA minimum dinamico:
   EURUSD: fta_min = max(3 pips, 0.3 * ATR_M5)
   XAUUSD: fta_min = max(30 pips, 0.3 * ATR_M5)
   
   Se trigger_score >= 70:
     fta_min = fta_min * 0.35 (exception)

3. Trova ostacoli tra entry e TP:
   - Swing highs M15 e M5 (BUY)
   - Swing lows M15 e M5 (SELL)
   - Touch zones (≥ 2 touches in 20 candles)
   - Round numbers (EURUSD: ogni 0.005, XAUUSD: ogni $10)

4. FTA = primo ostacolo più vicino a entry

5. Calcola clean_space_ratio:
   fta_distance = |fta_price - entry_price|
   tp_distance = |take_profit - entry_price|
   clean_space_ratio = fta_distance / tp_distance

6. Decision logic:
   Se clean_space_ratio < 0.15 → HARD REJECT
   Se fta_distance < fta_min AND trigger_score < 70 → REJECT
   Altrimenti → score by clean_space_ratio
```

### PARAMETRI NUMERICI
- ATR Period: 14
- EURUSD min pips: 3
- XAUUSD min pips: 30
- ATR multiplier: 0.3
- Strong trigger threshold: 70
- Strong trigger exception multiplier: 0.35
- Hard reject threshold: 15% clean space
- Touch zone tolerance: 0.3 * ATR

### OUTPUT (Score by Clean Space)
| Clean Space Ratio | Score |
|-------------------|-------|
| ≥ 80% | 100 (Excellent) |
| ≥ 65% | 80 (Good) |
| ≥ 50% | 60 (Moderate) |
| ≥ 30% | 45-39 (Limited, penalty) |
| < 30% | 25 (Very limited) |
| < 15% | REJECT |
| + No FTA | +3 bonus |

### ESEMPIO REALE (BUY)

```
Dati:
- entry_price = 1.0820
- take_profit = 1.0850 (30 pips TP)
- ATR_M5 = 0.0006 (6 pips)
- trigger_score = 65
- swing_high trovato a 1.0838

Calcolo:
- fta_min = max(0.0003, 0.3 * 0.0006) = 0.0003 (3 pips)
- fta_distance = 1.0838 - 1.0820 = 0.0018 (18 pips)
- tp_distance = 1.0850 - 1.0820 = 0.0030 (30 pips)
- clean_space_ratio = 0.0018 / 0.0030 = 0.60 (60%)

→ 60% ≥ 50% → score = 60 (Moderate clean space)
```

---

## 7. DIRECTIONAL CONTINUATION (BUY ONLY)

### INPUT
- `m15_candles`: Lista OHLC M15 (minimo 20 candles)
- `m5_candles`: Lista OHLC M5 (minimo 15 candles)
- `direction`: "BUY" (se SELL → score = 0)

### LOGICA

```
1. Calcola EMA20_M15

2. Trova swing_lows_m15[-20:]

3. Valuta condizioni:
   C1: close_m15[-1] > EMA20_M15
   C2: min(close_m15[-8:]) > last_swing_low (HL intact)
   C3: bullish_count in m5[-5:] >= 3 (M5 resume)
   C4: m5[-3].high > m5[-2].high > m5[-1].high (increasing highs)
```

### PARAMETRI NUMERICI
- EMA Period: 20
- HL intact lookback: 8 candles
- M5 resume threshold: 3 bullish candles in last 5
- HH check: last 3 candles

### OUTPUT
| Condizioni | Score |
|------------|-------|
| 4/4 | 100 |
| 3/4 | 80 |
| 2/4 | 60 |
| 1/4 | 35 |
| 0/4 | 35 |
| SELL direction | 0 |

---

## 8. REJECTION FAILED PUSH (SELL ONLY)

### INPUT
- `m15_candles`, `m5_candles`: Liste OHLC
- `direction`: "SELL" (se BUY → score = 0)

### LOGICA

```
Pattern A - Rejection with confirm:
1. Per candle in m5[-4:-1]:
   wick_ratio = upper_wick / candle_range
   close_pos = close_position_in_range
2. Se wick_ratio >= 0.35 AND close_pos <= 0.35:
   Se next_candle bearish → score = 100
   Altrimenti → score = 80

Pattern B - Failed Push:
1. prev_high = max(m5[-12:-3].high)
2. Per candle in m5[-3:]:
   Se candle.high > prev_high:
     Se all subsequent close < prev_high:
       → score = 80

Pattern C - Bearish Continuation:
Se 2 bearish candles consecutive:
→ score = 60
```

### OUTPUT
| Pattern | Score | is_valid |
|---------|-------|----------|
| Rejection + confirm | 100 | True |
| Rejection | 80 | True |
| Failed push | 80 | True |
| Bearish continuation | 60 | True |
| No pattern | 30 | False |

---

## 9. SESSION QUALITY

### INPUT
- `direction`: "BUY" o "SELL"
- `current_time`: UTC time

### LOGICA

```
1. Determina sessione (UTC):
   13:00-16:00 → "Overlap"
   07:00-12:59 → "London"
   16:01-20:00 → "NY"
   altro → "Asian/Other"

2. Score by direction and session:
```

### OUTPUT

**BUY Scores:**
| Session | Score |
|---------|-------|
| Overlap | 100 |
| NY | 90 |
| London | 85 |
| Asian/Other | 40 |

**SELL Scores:**
| Session | Score |
|---------|-------|
| Overlap | 100 |
| London | 65 |
| NY | 60 |
| Asian/Other | 20 |

---

## 10. MARKET SANITY CHECK

### INPUT
- `m5_candles`: Lista OHLC M5 (minimo 20 candles)
- `asset`: EURUSD o XAUUSD

### LOGICA

```
1. Calcola ATR_M5 (14 periodi)

2. Check ATR limits:
   EURUSD:
     ATR < 0.00025 (2.5 pips) → REJECT "too quiet"
     ATR > 0.0018 (18 pips) → REJECT "too volatile"
   XAUUSD:
     ATR < 0.9 ($0.9) → REJECT "too quiet"
     ATR > 9.0 ($9) → REJECT "too volatile"

3. Check spike:
   max_range = max(candle_range per m5[-10:])
   EURUSD spike limit: 0.0015 (15 pips)
   XAUUSD spike limit: 6.0 ($6)
   
   Se max_range > limit:
     avg_last_3 = mean(range per m5[-3:])
     Se avg_last_3 < max_range * 0.6:
       → score = 40 "Unconfirmed spike"

4. Score by ideal volatility:
   EURUSD ideal: 4-10 pips ATR
   XAUUSD ideal: $1.5-$5 ATR
```

### PARAMETRI NUMERICI
| Asset | ATR Min | ATR Max | Spike Max | Ideal Min | Ideal Max |
|-------|---------|---------|-----------|-----------|-----------|
| EURUSD | 2.5 pips | 18 pips | 15 pips | 4 pips | 10 pips |
| XAUUSD | $0.9 | $9 | $6 | $1.5 | $5 |

### OUTPUT
| Condition | Score | is_valid |
|-----------|-------|----------|
| Too quiet | 0 | False |
| Too volatile | 0 | False |
| Unconfirmed spike | 40 | True |
| Ideal volatility | 100 | True |
| Low/High (OK) | 70 | True |

---

## 11. COUNTER-TREND PENALTY (v11.0 NEW)

### INPUT
- `h1_candles`: Lista OHLC H1
- `direction`: "BUY" o "SELL"

### LOGICA

```
1. Calcola H1 trend:
   closes = [close per candle in h1[-20:]]
   h1_trend = (closes[-1] - closes[0]) / closes[0]

2. Determina se counter-trend:
   BUY counter-trend se h1_trend < -0.05
   SELL counter-trend se h1_trend > +0.05

3. Calcola penalty by H1 strength:
   h1_abs = abs(h1_trend)
   
   Se h1_abs >= 0.35 → penalty = -18 (Strong H1)
   Se h1_abs >= 0.15 → penalty = -10 (Moderate H1)
   Se h1_abs < 0.15 → penalty = -5 (Weak H1)
   Se non counter-trend → penalty = 0
```

### PARAMETRI NUMERICI
| H1 Strength | Range | Penalty |
|-------------|-------|---------|
| Weak | < 0.15 | -5 |
| Moderate | 0.15-0.35 | -10 |
| Strong | > 0.35 | -18 |

### OUTPUT
- Range: 0 to -18
- Type: PENALTY

---

## CALCOLO SCORE FINALE

### FORMULA

```
1. raw_quality_score = Σ (factor_score × factor_weight / 100)
   
   BUY: h1(20) + m15_trend(8) + m5_trigger(18) + pullback(8) + 
        fta(12) + continuation(14) + session(14) + sanity(6)
   
   SELL: h1(20) + m15_trend(8) + m5_trigger(18) + pullback(8) + 
         rejection(14) + fta(12) + session(14) + sanity(6)

2. total_penalties = m15_extension_penalty + counter_trend_penalty

3. final_trade_score = raw_quality_score + total_penalties

4. Bonuses (applicati dopo):
   - FTA score >= 80 → +5 (SELL) o +3 (BUY)
   - FTA score >= 60 → +2 (SELL) o +1 (BUY)
   - Session multiplier (BUY only)

5. Acceptance:
   final_trade_score >= 60 → ACCEPTED
   final_trade_score < 60 → REJECTED
```

### ESEMPIO COMPLETO (BUY)

```
FATTORI:
- H1 Structural Bias: 85 × 0.20 = 17.0
- M15 Trend Quality: 70 × 0.08 = 5.6
- M5 Trigger: 75 × 0.18 = 13.5
- Pullback Quality: 80 × 0.08 = 6.4
- FTA Clean Space: 60 × 0.12 = 7.2
- Directional Continuation: 60 × 0.14 = 8.4
- Session Quality: 100 × 0.14 = 14.0
- Market Sanity: 100 × 0.06 = 6.0

raw_quality_score = 78.1

PENALTIES:
- M15 Extension: -7 (extension ratio 1.4)
- Counter-Trend: 0 (non counter-trend)

total_penalties = -7

BONUSES:
- FTA Bonus: +1 (score 60)

final_trade_score = 78.1 - 7 + 1 = 72.1

→ 72.1 >= 60 → ACCEPTED
```

---

## ANALISI CRITICITÀ

### 1. FATTORI NON BEN DEFINITI MATEMATICAMENTE

| Fattore | Problema |
|---------|----------|
| H1 EMA Slope | Normalizzazione con `slope * 100` è arbitraria |
| MTF Alignment (legacy) | Usa `_get_trend()` che non è documentata |

### 2. FATTORI CON LOGICA DEBOLE/SOGGETTIVA

| Fattore | Problema |
|---------|----------|
| Session Quality | Score assegnati senza base statistica |
| Touch Zones | Tolerance di 0.3*ATR è arbitraria |
| Round Numbers | Step fissi (0.005 EUR, $10 XAU) senza validazione |

### 3. FATTORI CHE SI SOVRAPPONGONO

| Sovrapposizione | Descrizione |
|-----------------|-------------|
| H1 Bias + M15 Trend | Entrambi usano EMA + swing structure |
| M5 Trigger + Continuation | Pattern continuation appare in entrambi |
| FTA + Pullback | Entrambi considerano swing points |

### 4. POSSIBILI INCONSISTENZE SCORE

| Issue | Descrizione |
|-------|-------------|
| Counter-trend + strong H1 | Penalty -18 può rendere score < 60 anche con tutti altri fattori alti |
| Extension penalty + shallow pullback | Trade early nel trend penalizzato per pullback shallow E extension bassa |
| SELL rejection = 0 for BUY | Alcuni fattori danno 0 invece di "not applicable", distorcendo medie |

---

## RACCOMANDAZIONI

1. **Standardizzare output "not applicable"**: Usare `None` o escludere dal calcolo invece di 0

2. **Validare soglie staticamente**: Ogni soglia numerica dovrebbe avere backtest di supporto

3. **Separare meglio MTF**: H1, M15, M5 dovrebbero avere ruoli più distinti

4. **Documentare `_get_trend()`**: Funzione legacy non documentata

5. **Aggiungere confidence intervals**: Per ogni score, indicare range di incertezza

---

*Documento generato automaticamente da PropSignal Engine v11.0*
