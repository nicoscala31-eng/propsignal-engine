"""
DETERMINISTIC PATTERN ENGINE V2.0
=================================

MOTORE DI TRADING COMPLETAMENTE DETERMINISTICO
Basato ESCLUSIVAMENTE su pattern matematici.

NO score, NO checklist, NO penalità, NO logiche fuzzy.

Una trade è valida SOLO se:
- pattern_detected = true
- all_conditions = true
- no_invalid_conditions = true
- RR >= min_rr
- expected_edge_R > 0

REGIMI:
- TREND (Trend Continuation)
- RANGE (Mean Reversion)
- COMPRESSION (Compression Breakout)
- FALSE_BREAKOUT
- NONE

Autore: Math Engine V2.0
"""

import logging
import json
import math
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from typing import Dict, List, Optional, Tuple, Any
from pathlib import Path
from enum import Enum

logger = logging.getLogger(__name__)

# ==================== STORAGE ====================
PATTERN_ENGINE_DATA_FILE = Path("/app/backend/data/pattern_engine_tracking.json")


# ==================== ENUMS ====================

class Regime(Enum):
    TREND = "TREND"
    RANGE = "RANGE"
    COMPRESSION = "COMPRESSION"
    FALSE_BREAKOUT = "FALSE_BREAKOUT"
    NONE = "NONE"


class PatternType(Enum):
    TREND_CONTINUATION = "TREND_CONTINUATION"
    MEAN_REVERSION = "MEAN_REVERSION"
    COMPRESSION_BREAKOUT = "COMPRESSION_BREAKOUT"
    FALSE_BREAKOUT = "FALSE_BREAKOUT"
    NONE = "NONE"


class SignalDirection(Enum):
    BUY = "BUY"
    SELL = "SELL"
    NONE = "NONE"


class ValidationStatus(Enum):
    VALID = "VALID"
    REJECTED = "REJECTED"


class RejectionReason(Enum):
    # === NO PATTERN ===
    NO_PATTERN = "NO_PATTERN"  # Nessun pattern riconosciuto
    
    # === PATTERN_INVALID - Pattern riconosciuto ma invalido ===
    TREND_WEAK = "TREND_WEAK"
    RR_TOO_LOW = "RR_TOO_LOW"
    INVALID_BUY_SELL_GEOMETRY = "INVALID_BUY_SELL_GEOMETRY"  # SL/TP non coerenti con direzione
    EDGE_NEGATIVE = "EDGE_NEGATIVE"
    INSUFFICIENT_DATA = "INSUFFICIENT_DATA"
    INVALID_SWING = "INVALID_SWING"
    RANGE_TOO_TIGHT = "RANGE_TOO_TIGHT"  # range_width/ATR < 1.5
    
    # === MEAN REVERSION SPECIFIC ===
    Z_SCORE_NOT_EXTREME = "Z_SCORE_NOT_EXTREME"  # |Z_t| < threshold
    NOT_NEAR_RANGE_BOUND = "NOT_NEAR_RANGE_BOUND"  # Prezzo non vicino a supporto/resistenza
    MU_NOT_NEUTRAL = "MU_NOT_NEUTRAL"  # mu_t troppo alto (trend presente)
    
    # === TREND CONTINUATION SPECIFIC ===
    NO_HIGHER_HIGHS_LOWS = "NO_HIGHER_HIGHS_LOWS"  # Struttura swing non valida per trend
    NO_MICRO_BREAKOUT = "NO_MICRO_BREAKOUT"  # Nessun breakout del micro pullback
    
    # === COMPRESSION BREAKOUT SPECIFIC ===
    NOT_COMPRESSION = "NOT_COMPRESSION"  # Range non abbastanza stretto
    BREAKOUT_TOO_FAR = "BREAKOUT_TOO_FAR"  # Breakout troppo lontano dal range
    
    # === FALSE BREAKOUT SPECIFIC ===
    NO_WICK_REJECTION = "NO_WICK_REJECTION"  # Wick ratio insufficiente


# ==================== GLOBAL PARAMETERS ====================

@dataclass
class EngineParameters:
    """Parametri numerici globali - tutti configurabili"""
    
    # Trend strength
    trend_strength_threshold: float = 0.6
    mu_neutral_threshold: float = 0.00005
    
    # Z-score
    z_threshold: float = 1.5
    
    # Range detection
    range_proximity_threshold: float = 0.20
    compression_width_multiplier: float = 1.2
    breakout_distance_threshold: float = 0.35  # moltiplicato per ATR
    
    # Wick ratio for false breakout
    wick_ratio_threshold: float = 1.5
    
    # Risk management
    min_rr: float = 1.30
    
    # Swing detection
    K: int = 3  # lookback/forward per swing
    M: int = 3  # periodi per micro pullback
    
    # N for rolling calculations
    N: int = 20  # periodi per statistiche
    
    # ATR period
    atr_period: int = 14
    
    # Swing filter
    min_swing_distance_atr: float = 0.5
    
    # Initial winrates per pattern
    winrate_trend: float = 0.50
    winrate_mean_reversion: float = 0.60
    winrate_breakout: float = 0.45
    winrate_false_breakout: float = 0.55


# ==================== DATA STRUCTURES ====================

@dataclass
class Candle:
    """Single OHLC candle"""
    timestamp: str
    open: float
    high: float
    low: float
    close: float
    
    @property
    def body(self) -> float:
        return abs(self.close - self.open)
    
    @property
    def upper_wick(self) -> float:
        return self.high - max(self.open, self.close)
    
    @property
    def lower_wick(self) -> float:
        return min(self.open, self.close) - self.low
    
    @property
    def range(self) -> float:
        return self.high - self.low
    
    @property
    def is_bullish(self) -> bool:
        return self.close > self.open
    
    @property
    def is_bearish(self) -> bool:
        return self.close < self.open


@dataclass
class SwingPoint:
    """Swing High or Swing Low"""
    index: int
    price: float
    timestamp: str
    is_high: bool
    
    
@dataclass
class MathMetrics:
    """Metriche matematiche calcolate"""
    # Returns
    r_t: float = 0.0  # ln(Close_t / Close_t-1)
    
    # Volatility
    sigma_t: float = 0.0  # std(r_t su N)
    
    # Mean return
    mu_t: float = 0.0  # mean(r_t su N)
    
    # Trend strength
    T_t: float = 0.0  # |mu_t| / sigma_t
    
    # True Range
    TR_t: float = 0.0
    ATR_t: float = 0.0
    
    # Z-score
    Z_t: float = 0.0  # (Close_t - mean) / std
    
    # Range bounds
    range_high: float = 0.0
    range_low: float = 0.0
    range_mid: float = 0.0
    range_width: float = 0.0
    range_quality: float = 0.0  # range_width / ATR
    
    # Spread
    spread: float = 0.0
    
    # SL buffer
    sl_buffer: float = 0.0
    
    # Data freshness
    data_freshness_seconds: float = 0.0


@dataclass
class TradeLevels:
    """Entry, SL, TP calcolati"""
    entry: float = 0.0
    stop_loss: float = 0.0
    take_profit: float = 0.0
    risk: float = 0.0
    reward: float = 0.0
    rr: float = 0.0
    is_valid: bool = False


@dataclass 
class PatternResult:
    """Risultato dell'analisi pattern"""
    # Metadata
    timestamp: str = ""
    symbol: str = ""
    
    # Pattern detection
    pattern_detected: bool = False
    pattern_type: str = "NONE"
    regime: str = "NONE"
    direction: str = "NONE"
    
    # Validation
    status: str = "REJECTED"
    rejection_reason: str = ""
    all_conditions_met: bool = False
    
    # Math metrics
    metrics: Dict = field(default_factory=dict)
    
    # Trade levels
    entry: float = 0.0
    stop_loss: float = 0.0
    take_profit: float = 0.0
    rr: float = 0.0
    
    # Edge calculation
    winrate: float = 0.0
    expected_edge_R: float = 0.0
    
    # Swing data
    swings: Dict = field(default_factory=dict)
    
    # Debug - all conditions checked
    conditions: Dict = field(default_factory=dict)
    
    # Outcome tracking
    outcome: str = "pending"
    
    def to_dict(self) -> Dict:
        return asdict(self)


# ==================== DETERMINISTIC PATTERN ENGINE ====================

class DeterministicPatternEngine:
    """
    Motore di Pattern Deterministico.
    
    Zero interpretazioni soggettive.
    Solo formule matematiche su dati OHLC.
    """
    
    def __init__(self, params: Optional[EngineParameters] = None):
        self.params = params or EngineParameters()
        self.tracking_records: List[Dict] = []
        self._load_tracking()
        
        logger.info("=" * 60)
        logger.info("DETERMINISTIC PATTERN ENGINE V2.0")
        logger.info("=" * 60)
        logger.info(f"  Trend threshold: T_t >= {self.params.trend_strength_threshold}")
        logger.info(f"  Mu neutral: |mu_t| <= {self.params.mu_neutral_threshold}")
        logger.info(f"  Z threshold: |Z_t| >= {self.params.z_threshold}")
        logger.info(f"  Min RR: {self.params.min_rr}")
        logger.info(f"  Swing K: {self.params.K}")
        logger.info(f"  Rolling N: {self.params.N}")
        logger.info("=" * 60)
    
    # ========== PERSISTENCE ==========
    
    def _load_tracking(self):
        """Load tracking records"""
        try:
            if PATTERN_ENGINE_DATA_FILE.exists():
                with open(PATTERN_ENGINE_DATA_FILE, 'r') as f:
                    data = json.load(f)
                    self.tracking_records = data.get('records', [])
                    logger.info(f"📊 Loaded {len(self.tracking_records)} pattern records")
        except Exception as e:
            logger.error(f"Error loading tracking: {e}")
            self.tracking_records = []
    
    def _save_tracking(self):
        """Save tracking records"""
        try:
            PATTERN_ENGINE_DATA_FILE.parent.mkdir(parents=True, exist_ok=True)
            with open(PATTERN_ENGINE_DATA_FILE, 'w') as f:
                json.dump({
                    'updated_at': datetime.utcnow().isoformat(),
                    'total_records': len(self.tracking_records),
                    'records': self.tracking_records[-500:]
                }, f, indent=2)
        except Exception as e:
            logger.error(f"Error saving tracking: {e}")
    
    # ========== CANDLE PARSING ==========
    
    def _parse_candles(self, raw_candles: List[Dict]) -> List[Candle]:
        """Parse raw OHLC data"""
        candles = []
        for c in raw_candles:
            try:
                candle = Candle(
                    timestamp=str(c.get('datetime', c.get('timestamp', ''))),
                    open=float(c.get('open', 0)),
                    high=float(c.get('high', 0)),
                    low=float(c.get('low', 0)),
                    close=float(c.get('close', 0))
                )
                if candle.range > 0:
                    candles.append(candle)
            except Exception as e:
                logger.warning(f"Candle parse error: {e}")
        return candles
    
    # ========== MATH CALCULATIONS ==========
    
    def _calculate_returns(self, candles: List[Candle]) -> List[float]:
        """
        r_t = ln(Close_t / Close_t-1)
        """
        returns = []
        for i in range(1, len(candles)):
            if candles[i-1].close > 0:
                r = math.log(candles[i].close / candles[i-1].close)
                returns.append(r)
        return returns
    
    def _calculate_metrics(self, candles: List[Candle], spread: float = 0.0) -> MathMetrics:
        """
        Calcola tutte le metriche matematiche.
        """
        metrics = MathMetrics()
        metrics.spread = spread
        
        if len(candles) < self.params.N + 1:
            return metrics
        
        N = self.params.N
        recent = candles[-N-1:]
        last_candle = candles[-1]
        
        # Returns
        returns = self._calculate_returns(recent)
        if not returns:
            return metrics
        
        # r_t = ultimo return
        metrics.r_t = returns[-1] if returns else 0
        
        # sigma_t = std(returns)
        if len(returns) >= 2:
            mean_r = sum(returns) / len(returns)
            variance = sum((r - mean_r) ** 2 for r in returns) / len(returns)
            metrics.sigma_t = math.sqrt(variance) if variance > 0 else 0.0001
        else:
            metrics.sigma_t = 0.0001
        
        # mu_t = mean(returns)
        metrics.mu_t = sum(returns) / len(returns) if returns else 0
        
        # T_t = |mu_t| / sigma_t (trend strength)
        if metrics.sigma_t > 0:
            metrics.T_t = abs(metrics.mu_t) / metrics.sigma_t
        
        # True Range e ATR
        tr_values = []
        for i in range(1, len(recent)):
            prev_close = recent[i-1].close
            high = recent[i].high
            low = recent[i].low
            tr = max(high - low, abs(high - prev_close), abs(low - prev_close))
            tr_values.append(tr)
        
        metrics.TR_t = tr_values[-1] if tr_values else 0
        if len(tr_values) >= self.params.atr_period:
            metrics.ATR_t = sum(tr_values[-self.params.atr_period:]) / self.params.atr_period
        elif tr_values:
            metrics.ATR_t = sum(tr_values) / len(tr_values)
        
        # Z-score
        closes = [c.close for c in recent]
        mean_close = sum(closes) / len(closes)
        std_close = math.sqrt(sum((c - mean_close) ** 2 for c in closes) / len(closes))
        if std_close > 0:
            metrics.Z_t = (last_candle.close - mean_close) / std_close
        
        # Range bounds
        metrics.range_high = max(c.high for c in recent)
        metrics.range_low = min(c.low for c in recent)
        metrics.range_mid = (metrics.range_high + metrics.range_low) / 2
        metrics.range_width = metrics.range_high - metrics.range_low
        
        # range_quality = range_width / ATR
        metrics.range_quality = metrics.range_width / metrics.ATR_t if metrics.ATR_t > 0 else 0
        
        # SL buffer = max(spread*2, 0.15*ATR, minimum_tick)
        # Determine minimum tick based on price level (not symbol name)
        price = last_candle.close
        if price < 10:  # Forex pairs like EURUSD (1.xxxx)
            minimum_tick = 0.00001  # 0.1 pips
        elif price < 100:  # Some pairs or indices
            minimum_tick = 0.0001   # 1 pip
        else:  # XAUUSD (~3000), indices, etc
            minimum_tick = 0.01     # 1 cent
        
        metrics.sl_buffer = max(spread * 2, 0.15 * metrics.ATR_t, minimum_tick)
        
        return metrics
    
    # ========== SWING DETECTION ==========
    
    def _find_swings(self, candles: List[Candle], atr: float) -> Tuple[List[SwingPoint], List[SwingPoint]]:
        """
        Swing High: High_i > High_{i-1..i-K} AND High_i > High_{i+1..i+K}
        Swing Low:  Low_i < Low_{i-1..i-K} AND Low_i < Low_{i+1..i+K}
        
        Filtro: |swing - previous_opposite_swing| >= 0.5 * ATR
        """
        K = self.params.K
        swing_highs = []
        swing_lows = []
        
        if len(candles) < K * 2 + 1:
            return swing_highs, swing_lows
        
        for i in range(K, len(candles) - K):
            # Check swing high
            is_swing_high = True
            for j in range(1, K + 1):
                if candles[i].high <= candles[i-j].high or candles[i].high <= candles[i+j].high:
                    is_swing_high = False
                    break
            
            if is_swing_high:
                swing_highs.append(SwingPoint(
                    index=i,
                    price=candles[i].high,
                    timestamp=candles[i].timestamp,
                    is_high=True
                ))
            
            # Check swing low
            is_swing_low = True
            for j in range(1, K + 1):
                if candles[i].low >= candles[i-j].low or candles[i].low >= candles[i+j].low:
                    is_swing_low = False
                    break
            
            if is_swing_low:
                swing_lows.append(SwingPoint(
                    index=i,
                    price=candles[i].low,
                    timestamp=candles[i].timestamp,
                    is_high=False
                ))
        
        # Filter: minimum distance from opposite swing
        min_dist = self.params.min_swing_distance_atr * atr
        
        filtered_highs = []
        filtered_lows = []
        
        for sh in swing_highs:
            # Check distance from nearest swing low
            valid = True
            for sl in swing_lows:
                if abs(sh.price - sl.price) < min_dist:
                    valid = False
                    break
            if valid or not swing_lows:
                filtered_highs.append(sh)
        
        for sl in swing_lows:
            valid = True
            for sh in swing_highs:
                if abs(sl.price - sh.price) < min_dist:
                    valid = False
                    break
            if valid or not swing_highs:
                filtered_lows.append(sl)
        
        return filtered_highs if filtered_highs else swing_highs, filtered_lows if filtered_lows else swing_lows
    
    # ========== REGIME DETECTION ==========
    
    def _detect_regime(self, metrics: MathMetrics) -> Regime:
        """
        Determina il regime di mercato.
        
        TREND: T_t >= threshold AND mu_t != 0
        RANGE: |mu_t| <= mu_neutral AND T_t < threshold
        COMPRESSION: range_width <= compression_multiplier * ATR
        """
        # Compression
        if metrics.range_width <= self.params.compression_width_multiplier * metrics.ATR_t:
            return Regime.COMPRESSION
        
        # Trend
        if metrics.T_t >= self.params.trend_strength_threshold:
            return Regime.TREND
        
        # Range
        if abs(metrics.mu_t) <= self.params.mu_neutral_threshold and metrics.T_t < self.params.trend_strength_threshold:
            return Regime.RANGE
        
        return Regime.NONE
    
    # ========== PATTERN DETECTION ==========
    
    def _detect_trend_continuation(
        self, 
        candles: List[Candle],
        metrics: MathMetrics,
        swing_highs: List[SwingPoint],
        swing_lows: List[SwingPoint]
    ) -> Optional[PatternResult]:
        """
        TREND CONTINUATION
        
        BUY:
        - mu_t > 0
        - T_t >= trend_strength_threshold
        - last_swing_high > previous_swing_high
        - last_swing_low > previous_swing_low
        - Close_t > micro_pullback_high (max High ultimi M periodi)
        
        SL: last_swing_low - sl_buffer
        TP: nearest swing_high above Entry, or Entry + (last_swing_high - last_swing_low)
        """
        M = self.params.M
        last_candle = candles[-1]
        
        conditions = {
            'mu_positive': metrics.mu_t > 0,
            'mu_negative': metrics.mu_t < 0,
            'trend_strong': metrics.T_t >= self.params.trend_strength_threshold,
            'hh_hl_valid': False,
            'lh_ll_valid': False,
            'breakout_up': False,
            'breakout_down': False
        }
        
        # Check swing structure for BUY
        if len(swing_highs) >= 2 and len(swing_lows) >= 2:
            last_sh = swing_highs[-1].price
            prev_sh = swing_highs[-2].price
            last_sl = swing_lows[-1].price
            prev_sl = swing_lows[-2].price
            
            conditions['hh_hl_valid'] = last_sh > prev_sh and last_sl > prev_sl
            conditions['lh_ll_valid'] = last_sh < prev_sh and last_sl < prev_sl
        
        # Micro pullback breakout
        if len(candles) >= M:
            micro_high = max(c.high for c in candles[-M-1:-1])
            micro_low = min(c.low for c in candles[-M-1:-1])
            conditions['breakout_up'] = last_candle.close > micro_high
            conditions['breakout_down'] = last_candle.close < micro_low
        
        # BUY signal
        if (conditions['mu_positive'] and 
            conditions['trend_strong'] and 
            conditions['hh_hl_valid'] and 
            conditions['breakout_up']):
            
            # Calculate levels
            last_swing_low = swing_lows[-1].price if swing_lows else last_candle.low
            last_swing_high = swing_highs[-1].price if swing_highs else last_candle.high
            
            entry = last_candle.close
            sl = last_swing_low - metrics.sl_buffer
            
            # TP: nearest swing high above entry
            tp = None
            for sh in swing_highs:
                if sh.price > entry:
                    tp = sh.price
                    break
            
            if tp is None:
                # Fallback: projected move
                tp = entry + (last_swing_high - last_swing_low)
            
            risk = abs(entry - sl)
            reward = abs(tp - entry)
            rr = reward / risk if risk > 0 else 0
            
            return PatternResult(
                pattern_detected=True,
                pattern_type=PatternType.TREND_CONTINUATION.value,
                regime=Regime.TREND.value,
                direction=SignalDirection.BUY.value,
                entry=entry,
                stop_loss=sl,
                take_profit=tp,
                rr=rr,
                winrate=self.params.winrate_trend,
                conditions=conditions,
                swings={
                    'last_swing_high': last_swing_high,
                    'last_swing_low': last_swing_low
                }
            )
        
        # SELL signal
        if (conditions['mu_negative'] and 
            conditions['trend_strong'] and 
            conditions['lh_ll_valid'] and 
            conditions['breakout_down']):
            
            last_swing_high = swing_highs[-1].price if swing_highs else last_candle.high
            last_swing_low = swing_lows[-1].price if swing_lows else last_candle.low
            
            entry = last_candle.close
            sl = last_swing_high + metrics.sl_buffer
            
            # TP: nearest swing low below entry
            tp = None
            for slo in reversed(swing_lows):
                if slo.price < entry:
                    tp = slo.price
                    break
            
            if tp is None:
                tp = entry - (last_swing_high - last_swing_low)
            
            risk = abs(sl - entry)
            reward = abs(entry - tp)
            rr = reward / risk if risk > 0 else 0
            
            return PatternResult(
                pattern_detected=True,
                pattern_type=PatternType.TREND_CONTINUATION.value,
                regime=Regime.TREND.value,
                direction=SignalDirection.SELL.value,
                entry=entry,
                stop_loss=sl,
                take_profit=tp,
                rr=rr,
                winrate=self.params.winrate_trend,
                conditions=conditions,
                swings={
                    'last_swing_high': last_swing_high,
                    'last_swing_low': last_swing_low
                }
            )
        
        return None
    
    def _detect_mean_reversion(
        self,
        candles: List[Candle],
        metrics: MathMetrics
    ) -> Optional[PatternResult]:
        """
        MEAN REVERSION
        
        PREREQUISITO:
        - range_width / ATR >= 1.5 (altrimenti RANGE_TOO_TIGHT)
        
        BUY:
        - |mu_t| <= mu_neutral_threshold
        - T_t < trend_strength_threshold
        - |Close_t - range_low| <= range_proximity * range_width
        - Z_t <= -z_threshold
        
        SL: range_low - sl_buffer
        TP: range_mid (or range_high - sl_buffer if range_width/ATR >= 2)
        
        REJECTION ESPLICITE:
        - RANGE_TOO_TIGHT: range_quality < 1.5
        - MU_NOT_NEUTRAL: mu_t troppo alto
        - Z_SCORE_NOT_EXTREME: Z_t non raggiunge threshold
        - NOT_NEAR_RANGE_BOUND: prezzo non vicino a supporto/resistenza
        """
        last_candle = candles[-1]
        
        # Calcola range_quality = range_width / ATR
        range_quality = metrics.range_width / metrics.ATR_t if metrics.ATR_t > 0 else 0
        
        # Base conditions
        conditions = {
            'mu_neutral': abs(metrics.mu_t) <= self.params.mu_neutral_threshold,
            'trend_weak': metrics.T_t < self.params.trend_strength_threshold,
            'near_range_low': False,
            'near_range_high': False,
            'z_oversold': metrics.Z_t <= -self.params.z_threshold,
            'z_overbought': metrics.Z_t >= self.params.z_threshold,
            'range_wide_enough': range_quality >= 1.5,
            'range_quality': round(range_quality, 3),
            'Z_t': round(metrics.Z_t, 4),
            'z_threshold': self.params.z_threshold,
            'mu_t': round(metrics.mu_t, 8),
            'mu_threshold': self.params.mu_neutral_threshold
        }
        
        # Proximity to range bounds
        proximity_threshold = self.params.range_proximity_threshold * metrics.range_width
        conditions['near_range_low'] = abs(last_candle.close - metrics.range_low) <= proximity_threshold
        conditions['near_range_high'] = abs(last_candle.close - metrics.range_high) <= proximity_threshold
        
        # Helper per creare rejection con entry/SL/TP teorici
        def create_rejection(reason: RejectionReason, direction: SignalDirection, entry: float, sl: float, tp: float) -> PatternResult:
            risk = abs(entry - sl) if entry and sl else 0
            reward = abs(tp - entry) if entry and tp else 0
            rr = reward / risk if risk > 0 else 0
            return PatternResult(
                pattern_detected=True,
                pattern_type=PatternType.MEAN_REVERSION.value,
                regime=Regime.RANGE.value,
                direction=direction.value,
                entry=entry,
                stop_loss=sl,
                take_profit=tp,
                rr=rr,
                status=ValidationStatus.REJECTED.value,
                rejection_reason=reason.value,
                all_conditions_met=False,
                winrate=self.params.winrate_mean_reversion,
                conditions=conditions
            )
        
        # === REJECTION 1: RANGE_TOO_TIGHT ===
        if range_quality < 1.5:
            return create_rejection(
                RejectionReason.RANGE_TOO_TIGHT,
                SignalDirection.NONE,
                last_candle.close,
                metrics.range_low - metrics.sl_buffer,
                metrics.range_mid
            )
        
        # === REJECTION 2: MU_NOT_NEUTRAL (trend presente) ===
        if not conditions['mu_neutral']:
            return create_rejection(
                RejectionReason.MU_NOT_NEUTRAL,
                SignalDirection.NONE,
                last_candle.close,
                0, 0
            )
        
        # Determina potenziale direzione basata sulla posizione nel range
        near_support = conditions['near_range_low']
        near_resistance = conditions['near_range_high']
        
        # Calcola entry/SL/TP teorici per BUY
        buy_entry = last_candle.close
        buy_sl = metrics.range_low - metrics.sl_buffer
        buy_tp = metrics.range_high - metrics.sl_buffer if range_quality >= 2 else metrics.range_mid
        
        # Calcola entry/SL/TP teorici per SELL
        sell_entry = last_candle.close
        sell_sl = metrics.range_high + metrics.sl_buffer
        sell_tp = metrics.range_low + metrics.sl_buffer if range_quality >= 2 else metrics.range_mid
        
        # === REJECTION 3: NOT_NEAR_RANGE_BOUND ===
        if not near_support and not near_resistance:
            # Prezzo nel mezzo del range
            return create_rejection(
                RejectionReason.NOT_NEAR_RANGE_BOUND,
                SignalDirection.NONE,
                last_candle.close,
                0, 0
            )
        
        # === CHECK BUY CONDITIONS ===
        if near_support:
            # Vicino al supporto - potenziale BUY
            if not conditions['z_oversold']:
                # Z_t non abbastanza oversold
                return create_rejection(
                    RejectionReason.Z_SCORE_NOT_EXTREME,
                    SignalDirection.BUY,
                    buy_entry,
                    buy_sl,
                    buy_tp
                )
            
            if not conditions['trend_weak']:
                return create_rejection(
                    RejectionReason.TREND_WEAK,
                    SignalDirection.BUY,
                    buy_entry,
                    buy_sl,
                    buy_tp
                )
            
            # TUTTE LE CONDIZIONI BUY SODDISFATTE
            risk = abs(buy_entry - buy_sl)
            reward = abs(buy_tp - buy_entry)
            rr = reward / risk if risk > 0 else 0
            
            return PatternResult(
                pattern_detected=True,
                pattern_type=PatternType.MEAN_REVERSION.value,
                regime=Regime.RANGE.value,
                direction=SignalDirection.BUY.value,
                entry=buy_entry,
                stop_loss=buy_sl,
                take_profit=buy_tp,
                rr=rr,
                winrate=self.params.winrate_mean_reversion,
                conditions=conditions
            )
        
        # === CHECK SELL CONDITIONS ===
        if near_resistance:
            # Vicino alla resistenza - potenziale SELL
            if not conditions['z_overbought']:
                # Z_t non abbastanza overbought
                return create_rejection(
                    RejectionReason.Z_SCORE_NOT_EXTREME,
                    SignalDirection.SELL,
                    sell_entry,
                    sell_sl,
                    sell_tp
                )
            
            if not conditions['trend_weak']:
                return create_rejection(
                    RejectionReason.TREND_WEAK,
                    SignalDirection.SELL,
                    sell_entry,
                    sell_sl,
                    sell_tp
                )
            
            # TUTTE LE CONDIZIONI SELL SODDISFATTE
            risk = abs(sell_sl - sell_entry)
            reward = abs(sell_entry - sell_tp)
            rr = reward / risk if risk > 0 else 0
            
            return PatternResult(
                pattern_detected=True,
                pattern_type=PatternType.MEAN_REVERSION.value,
                regime=Regime.RANGE.value,
                direction=SignalDirection.SELL.value,
                entry=sell_entry,
                stop_loss=sell_sl,
                take_profit=sell_tp,
                rr=rr,
                winrate=self.params.winrate_mean_reversion,
                conditions=conditions
            )
        
        # Fallback (non dovrebbe mai arrivare qui)
        return None
    
    def _detect_compression_breakout(
        self,
        candles: List[Candle],
        metrics: MathMetrics
    ) -> Optional[PatternResult]:
        """
        COMPRESSION BREAKOUT
        
        compression_width <= compression_width_multiplier * ATR
        
        BUY:
        - Close_t > range_high
        - (Close_t - range_high) <= breakout_distance_threshold * ATR
        
        SL: range_low - sl_buffer (or range_high - sl_buffer if too wide)
        TP: Entry + compression_width
        """
        last_candle = candles[-1]
        
        # Check compression
        compression_width = metrics.range_width
        is_compression = compression_width <= self.params.compression_width_multiplier * metrics.ATR_t
        
        if not is_compression:
            return None
        
        conditions = {
            'is_compression': is_compression,
            'breakout_up': False,
            'breakout_down': False,
            'distance_valid_up': False,
            'distance_valid_down': False
        }
        
        breakout_threshold = self.params.breakout_distance_threshold * metrics.ATR_t
        
        # BUY breakout
        if last_candle.close > metrics.range_high:
            conditions['breakout_up'] = True
            distance = last_candle.close - metrics.range_high
            conditions['distance_valid_up'] = distance <= breakout_threshold
            
            if conditions['distance_valid_up']:
                entry = last_candle.close
                
                # SL logic
                sl = metrics.range_low - metrics.sl_buffer
                sl_distance = entry - sl
                
                # If SL too wide, use tighter SL
                if sl_distance > 2 * metrics.ATR_t:
                    sl = metrics.range_high - metrics.sl_buffer
                
                tp = entry + compression_width
                
                risk = abs(entry - sl)
                reward = abs(tp - entry)
                rr = reward / risk if risk > 0 else 0
                
                return PatternResult(
                    pattern_detected=True,
                    pattern_type=PatternType.COMPRESSION_BREAKOUT.value,
                    regime=Regime.COMPRESSION.value,
                    direction=SignalDirection.BUY.value,
                    entry=entry,
                    stop_loss=sl,
                    take_profit=tp,
                    rr=rr,
                    winrate=self.params.winrate_breakout,
                    conditions=conditions
                )
        
        # SELL breakout
        if last_candle.close < metrics.range_low:
            conditions['breakout_down'] = True
            distance = metrics.range_low - last_candle.close
            conditions['distance_valid_down'] = distance <= breakout_threshold
            
            if conditions['distance_valid_down']:
                entry = last_candle.close
                
                sl = metrics.range_high + metrics.sl_buffer
                sl_distance = sl - entry
                
                if sl_distance > 2 * metrics.ATR_t:
                    sl = metrics.range_low + metrics.sl_buffer
                
                tp = entry - compression_width
                
                risk = abs(sl - entry)
                reward = abs(entry - tp)
                rr = reward / risk if risk > 0 else 0
                
                return PatternResult(
                    pattern_detected=True,
                    pattern_type=PatternType.COMPRESSION_BREAKOUT.value,
                    regime=Regime.COMPRESSION.value,
                    direction=SignalDirection.SELL.value,
                    entry=entry,
                    stop_loss=sl,
                    take_profit=tp,
                    rr=rr,
                    winrate=self.params.winrate_breakout,
                    conditions=conditions
                )
        
        return None
    
    def _detect_false_breakout(
        self,
        candles: List[Candle],
        metrics: MathMetrics
    ) -> Optional[PatternResult]:
        """
        FALSE BREAKOUT
        
        BUY:
        - Low_t < range_low (wick below)
        - Close_t > range_low (closed back inside)
        - lower_wick / body >= wick_ratio_threshold
        
        SL: Low_t - sl_buffer
        TP: range_mid (or range_high - sl_buffer if range_width/ATR >= 2)
        """
        last_candle = candles[-1]
        
        conditions = {
            'wick_below_range': last_candle.low < metrics.range_low,
            'close_above_range_low': last_candle.close > metrics.range_low,
            'wick_above_range': last_candle.high > metrics.range_high,
            'close_below_range_high': last_candle.close < metrics.range_high,
            'wick_ratio_buy': False,
            'wick_ratio_sell': False
        }
        
        # Wick ratio calculation
        if last_candle.body > 0:
            conditions['wick_ratio_buy'] = last_candle.lower_wick / last_candle.body >= self.params.wick_ratio_threshold
            conditions['wick_ratio_sell'] = last_candle.upper_wick / last_candle.body >= self.params.wick_ratio_threshold
        
        # BUY - false breakdown
        if (conditions['wick_below_range'] and 
            conditions['close_above_range_low'] and 
            conditions['wick_ratio_buy']):
            
            entry = last_candle.close
            sl = last_candle.low - metrics.sl_buffer
            
            if metrics.range_width / metrics.ATR_t >= 2:
                tp = metrics.range_high - metrics.sl_buffer
            else:
                tp = metrics.range_mid
            
            risk = abs(entry - sl)
            reward = abs(tp - entry)
            rr = reward / risk if risk > 0 else 0
            
            return PatternResult(
                pattern_detected=True,
                pattern_type=PatternType.FALSE_BREAKOUT.value,
                regime=Regime.FALSE_BREAKOUT.value,
                direction=SignalDirection.BUY.value,
                entry=entry,
                stop_loss=sl,
                take_profit=tp,
                rr=rr,
                winrate=self.params.winrate_false_breakout,
                conditions=conditions
            )
        
        # SELL - false breakout
        if (conditions['wick_above_range'] and 
            conditions['close_below_range_high'] and 
            conditions['wick_ratio_sell']):
            
            entry = last_candle.close
            sl = last_candle.high + metrics.sl_buffer
            
            if metrics.range_width / metrics.ATR_t >= 2:
                tp = metrics.range_low + metrics.sl_buffer
            else:
                tp = metrics.range_mid
            
            risk = abs(sl - entry)
            reward = abs(entry - tp)
            rr = reward / risk if risk > 0 else 0
            
            return PatternResult(
                pattern_detected=True,
                pattern_type=PatternType.FALSE_BREAKOUT.value,
                regime=Regime.FALSE_BREAKOUT.value,
                direction=SignalDirection.SELL.value,
                entry=entry,
                stop_loss=sl,
                take_profit=tp,
                rr=rr,
                winrate=self.params.winrate_false_breakout,
                conditions=conditions
            )
        
        return None
    
    # ========== VALIDATION ==========
    
    def _validate_trade(self, result: PatternResult) -> PatternResult:
        """
        Valida la trade:
        - pattern_detected = true
        - RR >= min_rr
        - expected_edge_R > 0
        - TP coerente
        - SL coerente
        
        NOTE: Se il pattern è già stato REJECTED dalla detection function,
        NON sovrascrivere la rejection reason.
        """
        # Se già rejected, mantieni la rejection reason originale
        if result.status == ValidationStatus.REJECTED.value and result.rejection_reason:
            return result
        
        if not result.pattern_detected:
            result.status = ValidationStatus.REJECTED.value
            result.rejection_reason = RejectionReason.NO_PATTERN.value
            return result
        
        # RR validation
        if result.rr < self.params.min_rr:
            result.status = ValidationStatus.REJECTED.value
            result.rejection_reason = RejectionReason.RR_TOO_LOW.value
            result.all_conditions_met = False
            return result
        
        # SL/TP coherence - BUY: SL < Entry < TP, SELL: TP < Entry < SL
        if result.direction == SignalDirection.BUY.value:
            if result.stop_loss >= result.entry or result.take_profit <= result.entry:
                result.status = ValidationStatus.REJECTED.value
                result.rejection_reason = RejectionReason.INVALID_BUY_SELL_GEOMETRY.value
                return result
        elif result.direction == SignalDirection.SELL.value:
            if result.stop_loss <= result.entry or result.take_profit >= result.entry:
                result.status = ValidationStatus.REJECTED.value
                result.rejection_reason = RejectionReason.INVALID_BUY_SELL_GEOMETRY.value
                return result
        
        # Expected edge calculation
        # expected_edge_R = (winrate * reward) - ((1-winrate) * risk)
        risk = abs(result.entry - result.stop_loss)
        reward = abs(result.take_profit - result.entry)
        
        expected_edge = (result.winrate * reward) - ((1 - result.winrate) * risk)
        result.expected_edge_R = expected_edge
        
        if expected_edge <= 0:
            result.status = ValidationStatus.REJECTED.value
            result.rejection_reason = RejectionReason.EDGE_NEGATIVE.value
            return result
        
        # All validations passed
        result.status = ValidationStatus.VALID.value
        result.all_conditions_met = True
        
        return result
    
    # ========== MAIN ANALYSIS ==========
    
    def analyze(
        self,
        symbol: str,
        candles_raw: List[Dict],
        spread: float = 0.0
    ) -> PatternResult:
        """
        Analisi completa deterministica.
        
        1. Calcola metriche matematiche
        2. Rileva regime
        3. Cerca pattern in ordine di priorità
        4. Valida trade
        5. Ritorna risultato
        """
        result = PatternResult(
            timestamp=datetime.utcnow().isoformat(),
            symbol=symbol
        )
        
        # Parse candles
        candles = self._parse_candles(candles_raw)
        
        if len(candles) < self.params.N + self.params.K + 1:
            result.status = ValidationStatus.REJECTED.value
            result.rejection_reason = RejectionReason.INSUFFICIENT_DATA.value
            self._track_result(result)
            return result
        
        # Calculate metrics
        metrics = self._calculate_metrics(candles, spread)
        
        # Calculate data freshness
        last_candle_time = candles[-1].timestamp
        try:
            # Parse timestamp (handles multiple formats)
            if 'T' in str(last_candle_time):
                candle_dt = datetime.fromisoformat(str(last_candle_time).replace('Z', '+00:00').replace('+00:00', ''))
            else:
                candle_dt = datetime.strptime(str(last_candle_time)[:19], '%Y-%m-%d %H:%M:%S')
            data_freshness = (datetime.utcnow() - candle_dt).total_seconds()
        except Exception:
            data_freshness = -1  # Unable to calculate
        
        result.metrics = {
            'mu_t': round(metrics.mu_t, 8),
            'sigma_t': round(metrics.sigma_t, 8),
            'T_t': round(metrics.T_t, 4),
            'Z_t': round(metrics.Z_t, 4),
            'ATR_t': round(metrics.ATR_t, 6),
            'range_width': round(metrics.range_width, 6),
            'range_high': round(metrics.range_high, 6),
            'range_low': round(metrics.range_low, 6),
            'range_quality': round(metrics.range_quality, 3),  # range_width / ATR
            'sl_buffer': round(metrics.sl_buffer, 6),
            'spread': round(spread, 6),
            'data_freshness_seconds': round(data_freshness, 1)
        }
        
        # Detect regime
        regime = self._detect_regime(metrics)
        result.regime = regime.value
        
        # Find swings
        swing_highs, swing_lows = self._find_swings(candles, metrics.ATR_t)
        
        if len(swing_highs) < 2 or len(swing_lows) < 2:
            result.status = ValidationStatus.REJECTED.value
            result.rejection_reason = RejectionReason.INVALID_SWING.value
            result.conditions = {'swing_highs': len(swing_highs), 'swing_lows': len(swing_lows)}
            self._track_result(result)
            return result
        
        # Detect patterns in priority order
        pattern_result = None
        
        # 1. False Breakout (highest priority - reversals)
        pattern_result = self._detect_false_breakout(candles, metrics)
        
        # 2. Compression Breakout
        if not pattern_result:
            pattern_result = self._detect_compression_breakout(candles, metrics)
        
        # 3. Mean Reversion
        if not pattern_result:
            pattern_result = self._detect_mean_reversion(candles, metrics)
        
        # 4. Trend Continuation
        if not pattern_result:
            pattern_result = self._detect_trend_continuation(candles, metrics, swing_highs, swing_lows)
        
        # If no pattern detected
        if not pattern_result:
            result.status = ValidationStatus.REJECTED.value
            result.rejection_reason = RejectionReason.NO_PATTERN.value
            self._track_result(result)
            return result
        
        # Merge pattern result
        result.pattern_detected = pattern_result.pattern_detected
        result.pattern_type = pattern_result.pattern_type
        result.regime = pattern_result.regime
        result.direction = pattern_result.direction
        result.entry = round(pattern_result.entry, 6)
        result.stop_loss = round(pattern_result.stop_loss, 6)
        result.take_profit = round(pattern_result.take_profit, 6)
        result.rr = round(pattern_result.rr, 2)
        result.winrate = pattern_result.winrate
        result.conditions = pattern_result.conditions
        result.swings = pattern_result.swings
        
        # IMPORTANT: Copy status and rejection_reason if already set
        if pattern_result.status == ValidationStatus.REJECTED.value:
            result.status = pattern_result.status
            result.rejection_reason = pattern_result.rejection_reason
            result.all_conditions_met = pattern_result.all_conditions_met
        
        # Validate (only if not already rejected)
        result = self._validate_trade(result)
        
        # Track
        self._track_result(result)
        
        return result
    
    def _track_result(self, result: PatternResult):
        """Track result for analysis"""
        self.tracking_records.append(result.to_dict())
        self._save_tracking()
        
        # Log
        status_emoji = "✅" if result.status == ValidationStatus.VALID.value else "❌"
        logger.info(f"[PATTERN] {result.symbol} {result.direction} {status_emoji} {result.pattern_type}")
        if result.rejection_reason:
            logger.info(f"  Reason: {result.rejection_reason}")
        if result.status == ValidationStatus.VALID.value:
            logger.info(f"  Entry: {result.entry} | SL: {result.stop_loss} | TP: {result.take_profit}")
            logger.info(f"  RR: {result.rr:.2f} | Edge: {result.expected_edge_R:.4f}")
    
    # ========== STATISTICS ==========
    
    def get_statistics(self) -> Dict:
        """Get engine statistics"""
        total = len(self.tracking_records)
        valid = sum(1 for r in self.tracking_records if r.get('status') == 'VALID')
        rejected = total - valid
        
        # By pattern type
        by_pattern = {}
        for r in self.tracking_records:
            pt = r.get('pattern_type', 'NONE')
            if pt not in by_pattern:
                by_pattern[pt] = {'total': 0, 'valid': 0}
            by_pattern[pt]['total'] += 1
            if r.get('status') == 'VALID':
                by_pattern[pt]['valid'] += 1
        
        # Rejection reasons
        rejection_counts = {}
        for r in self.tracking_records:
            reason = r.get('rejection_reason', '')
            if reason:
                rejection_counts[reason] = rejection_counts.get(reason, 0) + 1
        
        return {
            'total_analyses': total,
            'valid_signals': valid,
            'rejected_signals': rejected,
            'acceptance_rate': round(valid / total * 100, 2) if total > 0 else 0,
            'by_pattern': by_pattern,
            'rejection_breakdown': dict(sorted(rejection_counts.items(), key=lambda x: x[1], reverse=True)[:10]),
            'parameters': asdict(self.params)
        }


# ==================== GLOBAL INSTANCE ====================

deterministic_engine = DeterministicPatternEngine()
