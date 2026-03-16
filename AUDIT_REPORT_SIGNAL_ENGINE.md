# AUDIT TECNICO COMPLETO - Signal Generator V3
## PropSignal Engine - Report di Analisi

**Data Report:** 16 Marzo 2026  
**Versione Engine:** Signal Generator V3 (Enhanced)  
**File Principale:** `/app/backend/services/signal_generator_v3.py`

---

## 1. LOGICA ATTUALE DI STOP LOSS

### Algoritmo Utilizzato
Lo Stop Loss viene calcolato usando una formula basata su **ATR (Average True Range)** con un moltiplicatore fisso.

### Formula Esatta (Righe 839-846)
```python
# Per BUY:
stop_loss = entry_price - (atr * 1.5)

# Per SELL:
stop_loss = entry_price + (atr * 1.5)
```

### Dettagli Implementazione
- **NON** viene usato swing high/low
- **SÌ** viene usato ATR (Average True Range)
- **NON** viene usato un buffer aggiuntivo oltre al moltiplicatore
- **Timeframe:** M5 (candele a 5 minuti) - Riga 773
- **Periodo ATR:** 14 candele M5
- **Moltiplicatore:** 1.5x ATR (FISSO)

### Calcolo ATR (Righe 1514-1527)
```python
def _calculate_atr(self, candles: List, period: int) -> float:
    # True Range = max(High-Low, |High-PrevClose|, |Low-PrevClose|)
    # ATR = Media dei True Range su 14 periodi
```

### Distanza Media SL (Dati Reali)
| Asset  | SL Medio | SL Min | SL Max |
|--------|----------|--------|--------|
| EURUSD | 6.4 pips | 6.0 pips | 6.7 pips |
| XAUUSD | 905.2 pips | 801.8 pips | 974.4 pips |

### ⚠️ PROBLEMA IDENTIFICATO
Lo SL per EURUSD è **molto stretto** (6-7 pips). In condizioni normali di mercato, questo può causare stop-out frequenti anche su movimenti fisiologici del prezzo.

---

## 2. LOGICA ATTUALE DI TAKE PROFIT

### Algoritmo Utilizzato
Il Take Profit viene calcolato usando **ATR con moltiplicatore fisso**, creando un **R:R FISSO di circa 1.33**.

### Formula Esatta (Righe 841-848)
```python
# Per BUY:
take_profit_1 = entry_price + (atr * 2.0)   # TP1
take_profit_2 = entry_price + (atr * 3.0)   # TP2

# Per SELL:
take_profit_1 = entry_price - (atr * 2.0)   # TP1
take_profit_2 = entry_price - (atr * 3.0)   # TP2
```

### Calcolo R:R (Righe 853-855)
```python
risk = abs(entry_price - stop_loss)      # = ATR * 1.5
reward = abs(take_profit_1 - entry_price) # = ATR * 2.0
rr_ratio = reward / risk                  # = 2.0 / 1.5 = 1.333...
```

### Verifica con Dati Reali
- **R:R SEMPRE ≈ 1.33** (tutti i segnali analizzati)
- **Il TP NON deriva da livelli tecnici** (supporti, resistenze, Fibonacci)
- **Il TP è una formula pura** basata su ATR

### Distanza Media TP
| Asset  | TP Medio | TP Min | TP Max |
|--------|----------|--------|--------|
| EURUSD | 8.5 pips | 8.0 pips | 8.9 pips |
| XAUUSD | 1206.9 pips | 1069.1 pips | 1299.3 pips |

### ⚠️ PROBLEMA IDENTIFICATO
Il R:R è **sempre identico (1.33)** indipendentemente dalle condizioni di mercato. Questo indica:
1. Il sistema **non identifica livelli tecnici reali** per il TP
2. Il TP è **arbitrario** - non basato su struttura di mercato
3. In un trend forte, il TP potrebbe essere troppo conservativo
4. In un range, il TP potrebbe essere troppo ambizioso

---

## 3. LOGICA DI ENTRY

### Tipo di Entry
- **Market Entry** (esecuzione immediata al prezzo corrente)
- NON vengono usati ordini pending

### Formula Entry (Riga 836)
```python
entry_price = current_price  # Prezzo mid corrente
```

### Entry Zone (Righe 843-850)
Viene definita una "zona di entry" teorica, ma l'entry effettivo è sempre al prezzo corrente:
```python
# Per BUY:
entry_zone_low = entry_price - (atr * 0.3)
entry_zone_high = entry_price + (atr * 0.1)

# Per SELL:
entry_zone_low = entry_price - (atr * 0.1)
entry_zone_high = entry_price + (atr * 0.3)
```

### Controllo Movimento Eccessivo
**NON ESISTE** un controllo che verifica se il prezzo si è già mosso troppo prima dell'entry.

### Tempo Detection → Notifica
- Scansione ogni **5 secondi** (Riga 493: `self.scan_interval = 5`)
- Tempo stimato tra detection e notifica: **< 1 secondo** (esecuzione sincrona)
- Il ritardo principale è nella **ricezione push notification** sul device

### ⚠️ PROBLEMA IDENTIFICATO
Non esiste validazione per evitare entry quando:
- Il prezzo ha già fatto un movimento significativo nella direzione del segnale
- Il prezzo è vicino a resistenze/supporti importanti
- Il prezzo è in una zona di "late entry"

---

## 4. POSITION SIZING E GESTIONE RISCHIO

### Formula Position Sizing (Righe 155-206)
```python
# 1. Calcolo pip risk
pip_risk = abs(entry_price - stop_loss) / pip_size

# 2. Money at risk
money_at_risk = account_size * (risk_percent / 100)

# 3. Lot size
lot_size = money_at_risk / (pip_risk * pip_value)
```

### Input Utilizzati
| Parametro | EURUSD | XAUUSD |
|-----------|--------|--------|
| Pip Size | 0.0001 | 0.01 |
| Pip Value (per lot) | $10 | $1 |
| Account Size | $100,000 | $100,000 |
| Risk % Default | 0.5% | 0.5% |
| Risk % Min | 0.5% | 0.5% |
| Risk % Max | 0.75% | 0.75% |

### Prop Firm Configuration (Righe 67-74)
```python
account_size: 100,000
max_daily_loss: 3,000
operational_warning: 1,500
min_risk_percent: 0.5%
max_risk_percent: 0.75%
```

### Rischio Medio Reale per Trade
- **EURUSD:** ~$500 (0.5% di $100k)
- **XAUUSD:** Calcolato sulla stessa base

### ⚠️ PROBLEMA NEI DATI
Nei segnali recenti, **lot_size = 0** e **money_at_risk = 0**. Questo indica che il position sizing non viene eseguito correttamente o i dati non vengono salvati nel tracking.

---

## 5. CONFIDENCE SCORE

### Sistema di Scoring (Righe 461-475)
Il confidence score è composto da **12 fattori** con pesi specifici che sommano a **100%**:

| Fattore | Peso | Descrizione |
|---------|------|-------------|
| H1 Bias | 15% | Direzione trend su H1 |
| M15 Context | 12% | Allineamento M15 |
| MTF Alignment | 10% | Allineamento multi-timeframe |
| Market Structure | 12% | Qualità struttura di mercato |
| Momentum | 10% | Forza momentum |
| Pullback Quality | 12% | Qualità del pullback |
| Key Level | 8% | Reazione a livelli chiave |
| Session | 6% | Qualità sessione trading |
| R:R Ratio | 5% | Risk/Reward |
| Volatility | 3% | Condizioni volatilità |
| Market Regime | 5% | Regime di mercato |
| Spread | 2% | Penalità spread |

### Classificazione Confidence (Righe 884-896)
```python
80-100: STRONG (alta confidenza)
70-79:  GOOD (buona confidenza)
60-69:  ACCEPTABLE (accettabile)
<60:    REJECTED (rifiutato - NON invia notifica)
```

### Range Score Osservato
- **EURUSD:** 68% - 80%
- **XAUUSD:** 63% - 78%
- **Media generale:** ~70%

### ⚠️ NOTA
Il threshold minimo di 60% è **OBBLIGATORIO** (Riga 517). Segnali sotto 60% vengono scartati.

---

## 6. FILTRI DI SEGNALE

### Filtri Attivi nel Sistema

| Filtro | Tipo | Soglia | Azione |
|--------|------|--------|--------|
| Forex Hours | HARD | Weekend/Chiusura | Blocca scansione |
| Data Freshness | HARD | > 60 secondi | Blocca segnale |
| Spread EURUSD | HARD | > 3.0 pips | Blocca segnale |
| Spread XAUUSD | HARD | > 50 pips | Blocca segnale |
| ATR Minimo | HARD | < 0.3x avg ATR | Blocca segnale |
| Confidence | HARD | < 60% | Blocca notifica |
| Duplicate | HARD | 25 min / price zone | Blocca segnale |
| Session | SOFT | Off-hours | Penalità score |
| Spread Elevated | SOFT | > 1.5 pips EUR | Penalità score |
| News Risk | SOFT | Eventi imminenti | Penalità score |

### Duplicate Suppression (Righe 486-488)
```python
DUPLICATE_WINDOW_MINUTES = 25    # Finestra temporale
DUPLICATE_PRICE_ZONE_PIPS = 15   # EURUSD
DUPLICATE_PRICE_ZONE_XAU = 200   # XAUUSD
```

### Session Scoring (Righe 1238-1263)
- London/NY Overlap (13-16 UTC): 100%
- London (7-12 UTC): 90%
- NY (13-20 UTC): 85%
- Asian (3-6 UTC): 40%

### News Risk Detection (Righe 686-728)
- < 15 min: -10 punti (HIGH)
- 15-30 min: -5 punti (MEDIUM)
- 30-60 min: -2 punti (LOW)

---

## 7. STATISTICHE DELLE ULTIME SESSIONI

### Stato Corrente Generator
```json
{
  "scan_count": 5120,
  "signal_count": 60,
  "notification_count": 60,
  "rejection_count": 557,
  "daily_risk_used": $3,342.33
}
```

### Distribuzione Segnali Recenti (ultimi 20)
- **EURUSD:** 4 segnali (20%)
- **XAUUSD:** 16 segnali (80%)
- **BUY:** 12 (60%)
- **SELL:** 8 (40%)

### Metriche Chiave
| Metrica | Valore |
|---------|--------|
| R:R Medio | 1.33 (SEMPRE) |
| Confidence Media | ~70% |
| SL Medio EURUSD | 6.4 pips |
| TP Medio EURUSD | 8.5 pips |

### Performance Storica (da /api/analytics)
```
Total Signals: 122
Win Rate: 62.5%
Winning Trades: 20
Losing Trades: 12
Profit Factor: 3.33
Average R:R: 1.98 (dato storico)
```

---

## 8. SEGNALI RIFIUTATI

### Statistiche Rejection
- **Totale rejection:** 557 segnali
- **Ratio:** 557 rejected / 60 accepted = **9.28:1**

### Motivi di Rifiuto Principali

| Motivo | Descrizione |
|--------|-------------|
| Score < 60% | Confidence insufficiente (MANDATORY) |
| Duplicate | Segnale simile negli ultimi 25 min |
| Stale Data | Dati di mercato > 60 sec |
| Low Volatility | ATR < 30% della media |
| Extreme Spread | Spread > 3 pips EURUSD |
| No Direction | Impossibile determinare direzione |
| Missing Data | Candele mancanti |

### Filtro più Restrittivo
Il **confidence threshold del 60%** è il filtro che blocca più segnali, con ~557 rejection su ~617 candidati totali (~90% rejection rate).

---

## 9. PROBLEMI POTENZIALI IDENTIFICATI

### 🔴 CRITICO

#### 1. R:R FISSO A 1.33
- **Problema:** Il R:R è SEMPRE 1.33, mai variabile
- **Causa:** Formula fissa `TP = ATR * 2.0` e `SL = ATR * 1.5`
- **Impatto:** Il sistema non adatta SL/TP a livelli tecnici reali
- **Raccomandazione:** Implementare SL/TP basati su swing points o supporti/resistenze

#### 2. STOP LOSS TROPPO STRETTO (EURUSD)
- **Problema:** SL medio di 6.4 pips è molto aggressivo
- **Causa:** ATR M5 basso moltiplicato per 1.5
- **Impatto:** Possibili stop-out frequenti su noise di mercato
- **Raccomandazione:** Considerare SL minimo di 10-15 pips o usare ATR su timeframe superiore

#### 3. NESSUN SWING POINT DETECTION
- **Problema:** SL non usa swing high/low
- **Causa:** Formula basata solo su ATR
- **Impatto:** SL posizionato arbitrariamente, non dietro strutture di mercato
- **Raccomandazione:** Identificare swing points e posizionare SL dietro di essi

### 🟡 IMPORTANTE

#### 4. ENTRY SENZA VALIDAZIONE MOVIMENTO
- **Problema:** Non verifica se prezzo si è già mosso nella direzione
- **Impatto:** Possibili entry tardivi ("late entry")
- **Raccomandazione:** Aggiungere check su distanza dal punto di setup

#### 5. POSITION SIZING NON SALVATO
- **Problema:** lot_size e money_at_risk sono 0 nei dati tracciati
- **Impatto:** Impossibile analizzare sizing reale
- **Raccomandazione:** Debug del salvataggio position sizing

#### 6. DOMINANZA XAUUSD
- **Problema:** 80% segnali su XAUUSD, solo 20% su EURUSD
- **Causa:** Possibilmente ATR più alto su gold genera più setup validi
- **Impatto:** Concentrazione rischio su singolo asset

### 🟢 MINORE

#### 7. TIMEFRAME SINGOLO PER ATR
- Il calcolo ATR usa solo M5, potrebbe beneficiare di conferma su H1

#### 8. NEWS RISK SOFT
- Le news applicano solo penalità, non bloccano mai (design choice, non necessariamente problema)

---

## 10. RIEPILOGO FORMULA CORRENTE

### Entry
```
Entry = Prezzo corrente (market order)
```

### Stop Loss
```
SL = Entry ± (ATR_14_M5 × 1.5)
```

### Take Profit
```
TP1 = Entry ± (ATR_14_M5 × 2.0)
TP2 = Entry ± (ATR_14_M5 × 3.0)
```

### Risk/Reward
```
R:R = (ATR × 2.0) / (ATR × 1.5) = 1.333... (SEMPRE FISSO)
```

### Lot Size
```
Lot = (Account × Risk%) / (Pip_Risk × Pip_Value)
```

---

## CONCLUSIONI

Il sistema Signal Generator V3 è tecnicamente funzionante ma presenta alcune **limitazioni strutturali**:

1. **SL/TP non adattivi** - basati su formula fissa, non su struttura di mercato
2. **R:R sempre identico** - indica mancanza di identificazione livelli tecnici
3. **SL potenzialmente troppo stretto** per EURUSD in condizioni normali

Il motore è **conservativo** (90% rejection rate) ma quando genera segnali, questi hanno **parametri rigidi** che non si adattano al contesto specifico del trade.

---

*Report generato il 16/03/2026 - Audit tecnico senza modifiche al codice*
