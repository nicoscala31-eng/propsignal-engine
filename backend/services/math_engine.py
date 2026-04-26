"""
MATH ENGINE V1.0 - PURE MATHEMATICAL TRADING ENGINE
=====================================================

PRINCIPIO: Zero interpretazioni soggettive.
           Solo formule matematiche su dati OHLC.

Ogni condizione è:
- Numerica
- Verificabile
- Tracciata

NO parole come: "forte", "pulito", "buono", "significativo"
SOLO formule: >=, <=, ==, AND, OR
"""

import logging
import json
from dataclasses import dataclass, field, asdict
from datetime import datetime, timedelta, timezone
from typing import Dict, List, Optional, Tuple, Any
from pathlib import Path
from enum import Enum

logger = logging.getLogger(__name__)

# ==================== STORAGE ====================
MATH_ENGINE_DATA_FILE = Path("/app/backend/data/math_engine_tracking.json")


# ==================== DATA STRUCTURES ====================

@dataclass
class Candle:
    """Single OHLC candle with derived values"""
    timestamp: str
    open: float
    high: float
    low: float
    close: float
    
    # Derived (calculated)
    range: float = 0.0
    body: float = 0.0
    body_ratio: float = 0.0
    close_position: float = 0.0
    is_valid: bool = False
    is_bullish: bool = False
    is_bearish: bool = False
    
    def __post_init__(self):
        self._calculate_derived()
    
    def _calculate_derived(self):
        """Calculate all derived values from OHLC"""
        # range = high - low
        self.range = self.high - self.low
        
        # Validate
        if self.range == 0:
            self.is_valid = False
            return
        
        self.is_valid = True
        
        # body = abs(close - open)
        self.body = abs(self.close - self.open)
        
        # body_ratio = body / range
        self.body_ratio = self.body / self.range
        
        # close_position = (close - low) / range
        self.close_position = (self.close - self.low) / self.range
        
        # Bullish candle:
        # close > open AND body_ratio >= 0.55 AND close_position >= 0.65
        self.is_bullish = (
            self.close > self.open
            and self.body_ratio >= 0.55
            and self.close_position >= 0.65
        )
        
        # Bearish candle:
        # close < open AND body_ratio >= 0.55 AND close_position <= 0.35
        self.is_bearish = (
            self.close < self.open
            and self.body_ratio >= 0.55
            and self.close_position <= 0.35
        )


@dataclass
class SwingPoint:
    """Swing High or Swing Low point"""
    index: int
    price: float
    timestamp: str
    is_high: bool  # True = swing high, False = swing low


@dataclass
class TrendAnalysis:
    """Trend analysis result"""
    higher_highs: int = 0
    higher_lows: int = 0
    lower_highs: int = 0
    lower_lows: int = 0
    bullish_trend_valid: bool = False
    bearish_trend_valid: bool = False
    last_swing_high: float = 0.0
    last_swing_low: float = 0.0
    prev_swing_high: float = 0.0
    prev_swing_low: float = 0.0


@dataclass
class ImpulseAnalysis:
    """Impulse leg analysis"""
    swing_high: float = 0.0
    swing_low: float = 0.0
    impulse_size: float = 0.0
    atr_multiple: float = 0.0
    bullish_impulse: bool = False
    bearish_impulse: bool = False


@dataclass 
class PullbackAnalysis:
    """Fibonacci pullback analysis"""
    pullback_depth: float = 0.0
    pullback_ratio: float = 0.0
    in_valid_zone: bool = False  # 0.38-0.62


@dataclass
class BreakoutAnalysis:
    """Breakout and retest analysis"""
    resistance: float = 0.0
    support: float = 0.0
    breakout_occurred: bool = False
    retest_occurred: bool = False
    breakout_retest_valid: bool = False


@dataclass
class LiquiditySweepAnalysis:
    """Liquidity sweep detection"""
    prev_high: float = 0.0
    prev_low: float = 0.0
    bullish_sweep: bool = False
    bearish_sweep: bool = False


@dataclass
class FlagPatternAnalysis:
    """Flag pattern detection"""
    impulse_valid: bool = False
    consolidation_range: float = 0.0
    consolidation_valid: bool = False
    breakout_valid: bool = False
    flag_valid: bool = False


@dataclass
class DoubleBottomAnalysis:
    """Double bottom pattern detection"""
    bottom1: float = 0.0
    bottom2: float = 0.0
    neckline: float = 0.0
    bottom_similarity: bool = False
    neckline_broken: bool = False
    double_bottom_valid: bool = False


@dataclass
class SessionAnalysis:
    """Session time analysis"""
    current_hour_utc: int = 0
    current_hour_italy: int = 0
    ny_optimal: bool = False  # 15:00-18:00 Italy time


@dataclass
class VolatilityAnalysis:
    """ATR and volatility analysis"""
    tr_values: List[float] = field(default_factory=list)
    atr_14: float = 0.0
    atr_20_avg: float = 0.0
    volatility_ok: bool = False


@dataclass
class TradeLevels:
    """Entry, SL, TP calculation"""
    entry_price: float = 0.0
    stop_loss: float = 0.0
    take_profit: float = 0.0
    sl_distance: float = 0.0
    risk: float = 0.0
    reward: float = 0.0
    rr_ratio: float = 0.0
    rr_valid: bool = False  # RR >= 1.0


@dataclass
class SignalResult:
    """Complete signal analysis result"""
    timestamp: str
    symbol: str
    
    # Raw OHLC
    open: float
    high: float
    low: float
    close: float
    
    # Candle metrics
    range: float
    body_ratio: float
    close_position: float
    bullish_candle: bool
    bearish_candle: bool
    
    # Trend
    bullish_trend_valid: bool
    bearish_trend_valid: bool
    higher_highs: int
    higher_lows: int
    
    # Impulse
    impulse_size: float
    impulse_atr_multiple: float
    bullish_impulse: bool
    
    # Pullback
    pullback_ratio: float
    pullback_valid: bool
    
    # Breakout
    breakout_retest_valid: bool
    
    # Liquidity
    liquidity_sweep: bool
    
    # Flag
    flag_valid: bool
    
    # Double Bottom
    double_bottom_valid: bool
    
    # Volatility
    atr_14: float
    volatility_ok: bool
    
    # Session
    session_hour_italy: int
    ny_optimal: bool
    
    # Trade levels
    entry_price: float
    stop_loss: float
    take_profit: float
    rr_ratio: float
    rr_valid: bool
    
    # Final decision
    signal_valid: bool
    direction: str  # BUY / SELL / NONE
    rejection_reasons: List[str]
    
    # Outcome (filled later)
    outcome: str = "pending"  # pending / tp / sl / expired
    mfe: float = 0.0
    mae: float = 0.0
    outcome_r: float = 0.0


# ==================== MATH ENGINE ====================

class MathEngine:
    """
    Pure Mathematical Trading Engine
    
    Every decision is based on numerical formulas only.
    No subjective interpretation.
    """
    
    # ========== CONSTANTS (All numerical) ==========
    
    # Candle validation
    MIN_BODY_RATIO = 0.55
    MIN_CLOSE_POSITION_BULL = 0.65
    MAX_CLOSE_POSITION_BEAR = 0.35
    
    # Trend validation
    MIN_TREND_SEQUENCES = 2  # Minimum HH+HL sequences for valid trend
    
    # Impulse validation
    MIN_IMPULSE_ATR_MULTIPLE = 1.5
    
    # Pullback validation (Fibonacci)
    PULLBACK_MIN_RATIO = 0.38
    PULLBACK_MAX_RATIO = 0.62
    
    # Breakout validation
    BREAKOUT_ATR_BUFFER = 0.10
    RETEST_ATR_BUFFER_ABOVE = 0.05
    RETEST_ATR_BUFFER_BELOW = 0.10
    
    # Liquidity sweep lookback
    LIQUIDITY_LOOKBACK = 20
    
    # Flag pattern
    FLAG_CONSOLIDATION_MAX_ATR = 1.0
    FLAG_LOOKBACK = 5
    
    # Double bottom
    DOUBLE_BOTTOM_SIMILARITY_MAX = 0.30  # Max difference as ATR ratio
    
    # Session (Italy time = UTC+2 in summer, UTC+1 in winter)
    # Using UTC+2 for simplicity
    NY_START_HOUR_ITALY = 15
    NY_END_HOUR_ITALY = 18
    ITALY_UTC_OFFSET = 2
    
    # ATR
    ATR_PERIOD = 14
    ATR_AVG_PERIOD = 20
    MIN_VOLATILITY_RATIO = 0.80
    
    # Risk management
    MIN_SL_ATR_MULTIPLE = 0.60
    MIN_SPREAD_MULTIPLE = 3
    TARGET_RR = 1.0
    MIN_RR = 1.0
    
    # Direction
    ALLOWED_DIRECTIONS = ["BUY"]  # SELL calculated but not traded
    
    def __init__(self):
        self.tracking_records: List[Dict] = []
        self._load_tracking()
        
        logger.info("=" * 60)
        logger.info("MATH ENGINE V1.0 - PURE MATHEMATICAL")
        logger.info("=" * 60)
        logger.info(f"  Candle: body_ratio >= {self.MIN_BODY_RATIO}")
        logger.info(f"  Candle: close_position >= {self.MIN_CLOSE_POSITION_BULL} (bull)")
        logger.info(f"  Trend: min {self.MIN_TREND_SEQUENCES} HH+HL sequences")
        logger.info(f"  Impulse: >= {self.MIN_IMPULSE_ATR_MULTIPLE} ATR")
        logger.info(f"  Pullback: {self.PULLBACK_MIN_RATIO}-{self.PULLBACK_MAX_RATIO} Fib")
        logger.info(f"  Session: {self.NY_START_HOUR_ITALY}:00-{self.NY_END_HOUR_ITALY}:00 Italy")
        logger.info(f"  RR: >= {self.MIN_RR}")
        logger.info(f"  Direction: {self.ALLOWED_DIRECTIONS}")
        logger.info("=" * 60)
    
    # ========== DATA LOADING ==========
    
    def _load_tracking(self):
        """Load tracking records from file"""
        try:
            if MATH_ENGINE_DATA_FILE.exists():
                with open(MATH_ENGINE_DATA_FILE, 'r') as f:
                    data = json.load(f)
                    self.tracking_records = data.get('records', [])
                    logger.info(f"📊 Loaded {len(self.tracking_records)} tracking records")
        except Exception as e:
            logger.error(f"Error loading tracking: {e}")
            self.tracking_records = []
    
    def _save_tracking(self):
        """Save tracking records to file"""
        try:
            MATH_ENGINE_DATA_FILE.parent.mkdir(parents=True, exist_ok=True)
            with open(MATH_ENGINE_DATA_FILE, 'w') as f:
                json.dump({
                    'updated_at': datetime.utcnow().isoformat(),
                    'total_records': len(self.tracking_records),
                    'records': self.tracking_records[-1000:]  # Keep last 1000
                }, f, indent=2)
        except Exception as e:
            logger.error(f"Error saving tracking: {e}")
    
    # ========== CANDLE ANALYSIS ==========
    
    def parse_candles(self, raw_candles: List[Dict]) -> List[Candle]:
        """Parse raw OHLC data into Candle objects"""
        candles = []
        for c in raw_candles:
            try:
                candle = Candle(
                    timestamp=c.get('datetime', c.get('timestamp', '')),
                    open=float(c.get('open', 0)),
                    high=float(c.get('high', 0)),
                    low=float(c.get('low', 0)),
                    close=float(c.get('close', 0))
                )
                if candle.is_valid:
                    candles.append(candle)
            except Exception as e:
                logger.warning(f"Error parsing candle: {e}")
        return candles
    
    # ========== SWING POINTS ==========
    
    def find_swing_points(self, candles: List[Candle], lookback: int = 2) -> Tuple[List[SwingPoint], List[SwingPoint]]:
        """
        Find swing highs and swing lows.
        
        swing_high[i] = high[i] > high[i-1] AND high[i] > high[i+1]
        swing_low[i] = low[i] < low[i-1] AND low[i] < low[i+1]
        """
        swing_highs = []
        swing_lows = []
        
        if len(candles) < 3:
            return swing_highs, swing_lows
        
        for i in range(1, len(candles) - 1):
            # Swing High
            if candles[i].high > candles[i-1].high and candles[i].high > candles[i+1].high:
                swing_highs.append(SwingPoint(
                    index=i,
                    price=candles[i].high,
                    timestamp=candles[i].timestamp,
                    is_high=True
                ))
            
            # Swing Low
            if candles[i].low < candles[i-1].low and candles[i].low < candles[i+1].low:
                swing_lows.append(SwingPoint(
                    index=i,
                    price=candles[i].low,
                    timestamp=candles[i].timestamp,
                    is_high=False
                ))
        
        return swing_highs, swing_lows
    
    # ========== TREND ANALYSIS ==========
    
    def analyze_trend(self, swing_highs: List[SwingPoint], swing_lows: List[SwingPoint]) -> TrendAnalysis:
        """
        Analyze trend using swing points.
        
        higher_high = last_swing_high > previous_swing_high
        higher_low = last_swing_low > previous_swing_low
        bullish_trend_valid = at least 2 consecutive (HH AND HL)
        """
        result = TrendAnalysis()
        
        if len(swing_highs) < 2 or len(swing_lows) < 2:
            return result
        
        # Get last 4 swings for analysis
        recent_highs = swing_highs[-4:] if len(swing_highs) >= 4 else swing_highs
        recent_lows = swing_lows[-4:] if len(swing_lows) >= 4 else swing_lows
        
        result.last_swing_high = recent_highs[-1].price if recent_highs else 0
        result.last_swing_low = recent_lows[-1].price if recent_lows else 0
        result.prev_swing_high = recent_highs[-2].price if len(recent_highs) >= 2 else 0
        result.prev_swing_low = recent_lows[-2].price if len(recent_lows) >= 2 else 0
        
        # Count HH, HL, LH, LL
        for i in range(1, len(recent_highs)):
            if recent_highs[i].price > recent_highs[i-1].price:
                result.higher_highs += 1
            else:
                result.lower_highs += 1
        
        for i in range(1, len(recent_lows)):
            if recent_lows[i].price > recent_lows[i-1].price:
                result.higher_lows += 1
            else:
                result.lower_lows += 1
        
        # Bullish trend valid: at least 2 HH AND 2 HL
        result.bullish_trend_valid = (
            result.higher_highs >= self.MIN_TREND_SEQUENCES
            and result.higher_lows >= self.MIN_TREND_SEQUENCES
        )
        
        # Bearish trend valid: at least 2 LH AND 2 LL
        result.bearish_trend_valid = (
            result.lower_highs >= self.MIN_TREND_SEQUENCES
            and result.lower_lows >= self.MIN_TREND_SEQUENCES
        )
        
        return result
    
    # ========== ATR CALCULATION ==========
    
    def calculate_atr(self, candles: List[Candle], period: int = 14) -> VolatilityAnalysis:
        """
        Calculate ATR (Average True Range).
        
        TR = max(high - low, abs(high - prev_close), abs(low - prev_close))
        ATR = SMA(TR, period)
        """
        result = VolatilityAnalysis()
        
        if len(candles) < period + 1:
            return result
        
        tr_values = []
        for i in range(1, len(candles)):
            prev_close = candles[i-1].close
            high = candles[i].high
            low = candles[i].low
            
            tr = max(
                high - low,
                abs(high - prev_close),
                abs(low - prev_close)
            )
            tr_values.append(tr)
        
        result.tr_values = tr_values
        
        # ATR_14
        if len(tr_values) >= period:
            result.atr_14 = sum(tr_values[-period:]) / period
        
        # ATR_20 average (for volatility comparison)
        if len(tr_values) >= self.ATR_AVG_PERIOD:
            result.atr_20_avg = sum(tr_values[-self.ATR_AVG_PERIOD:]) / self.ATR_AVG_PERIOD
        
        # volatility_ok = ATR_14 >= (ATR_20_avg * 0.80)
        if result.atr_20_avg > 0:
            result.volatility_ok = result.atr_14 >= (result.atr_20_avg * self.MIN_VOLATILITY_RATIO)
        
        return result
    
    # ========== IMPULSE ANALYSIS ==========
    
    def analyze_impulse(
        self, 
        swing_highs: List[SwingPoint], 
        swing_lows: List[SwingPoint],
        atr: float
    ) -> ImpulseAnalysis:
        """
        Analyze impulse leg.
        
        impulse_size = swing_high - swing_low
        bullish_impulse = impulse_size >= 1.5 * ATR AND swing_high after swing_low
        """
        result = ImpulseAnalysis()
        
        if not swing_highs or not swing_lows or atr <= 0:
            return result
        
        # Get last swing high and low
        last_high = swing_highs[-1]
        last_low = swing_lows[-1]
        
        result.swing_high = last_high.price
        result.swing_low = last_low.price
        result.impulse_size = abs(last_high.price - last_low.price)
        result.atr_multiple = result.impulse_size / atr if atr > 0 else 0
        
        # Bullish impulse: swing_high after swing_low AND impulse >= 1.5 ATR
        result.bullish_impulse = (
            last_high.index > last_low.index
            and result.atr_multiple >= self.MIN_IMPULSE_ATR_MULTIPLE
        )
        
        # Bearish impulse: swing_low after swing_high AND impulse >= 1.5 ATR
        result.bearish_impulse = (
            last_low.index > last_high.index
            and result.atr_multiple >= self.MIN_IMPULSE_ATR_MULTIPLE
        )
        
        return result
    
    # ========== PULLBACK ANALYSIS ==========
    
    def analyze_pullback(
        self,
        current_price: float,
        impulse: ImpulseAnalysis
    ) -> PullbackAnalysis:
        """
        Analyze Fibonacci pullback.
        
        pullback_depth = swing_high - current_price (for bullish)
        pullback_ratio = pullback_depth / impulse_size
        valid_pullback = 0.38 <= pullback_ratio <= 0.62
        """
        result = PullbackAnalysis()
        
        if impulse.impulse_size <= 0:
            return result
        
        # For bullish setup: price should be pulling back from swing high
        if impulse.bullish_impulse:
            result.pullback_depth = impulse.swing_high - current_price
            result.pullback_ratio = result.pullback_depth / impulse.impulse_size
        
        # For bearish setup: price should be pulling back from swing low
        elif impulse.bearish_impulse:
            result.pullback_depth = current_price - impulse.swing_low
            result.pullback_ratio = result.pullback_depth / impulse.impulse_size
        
        # Valid pullback zone: 38.2% - 61.8% Fibonacci
        result.in_valid_zone = (
            self.PULLBACK_MIN_RATIO <= result.pullback_ratio <= self.PULLBACK_MAX_RATIO
        )
        
        return result
    
    # ========== BREAKOUT ANALYSIS ==========
    
    def analyze_breakout(
        self,
        candles: List[Candle],
        atr: float,
        lookback: int = 20
    ) -> BreakoutAnalysis:
        """
        Analyze breakout and retest.
        
        resistance = max(high last 20)
        breakout = close > resistance + (0.10 * ATR)
        retest = low <= resistance + (0.05 * ATR) AND low >= resistance - (0.10 * ATR)
        """
        result = BreakoutAnalysis()
        
        if len(candles) < lookback + 2 or atr <= 0:
            return result
        
        # Get historical candles (excluding last 2 for breakout detection)
        historical = candles[-(lookback+2):-2]
        recent = candles[-2:]
        
        result.resistance = max(c.high for c in historical)
        result.support = min(c.low for c in historical)
        
        # Check for breakout
        for c in recent:
            if c.close > result.resistance + (self.BREAKOUT_ATR_BUFFER * atr):
                result.breakout_occurred = True
                break
        
        # Check for retest (on last candle)
        last_candle = candles[-1]
        retest_upper = result.resistance + (self.RETEST_ATR_BUFFER_ABOVE * atr)
        retest_lower = result.resistance - (self.RETEST_ATR_BUFFER_BELOW * atr)
        
        result.retest_occurred = (
            last_candle.low <= retest_upper
            and last_candle.low >= retest_lower
        )
        
        result.breakout_retest_valid = result.breakout_occurred and result.retest_occurred
        
        return result
    
    # ========== LIQUIDITY SWEEP ==========
    
    def analyze_liquidity_sweep(
        self,
        candles: List[Candle],
        lookback: int = 20
    ) -> LiquiditySweepAnalysis:
        """
        Detect liquidity sweep.
        
        bullish_sweep = low < prev_low AND close > prev_low
        bearish_sweep = high > prev_high AND close < prev_high
        """
        result = LiquiditySweepAnalysis()
        
        if len(candles) < lookback + 1:
            return result
        
        historical = candles[-(lookback+1):-1]
        last_candle = candles[-1]
        
        result.prev_high = max(c.high for c in historical)
        result.prev_low = min(c.low for c in historical)
        
        # Bullish sweep: wicked below previous low but closed above
        result.bullish_sweep = (
            last_candle.low < result.prev_low
            and last_candle.close > result.prev_low
        )
        
        # Bearish sweep: wicked above previous high but closed below
        result.bearish_sweep = (
            last_candle.high > result.prev_high
            and last_candle.close < result.prev_high
        )
        
        return result
    
    # ========== FLAG PATTERN ==========
    
    def analyze_flag(
        self,
        candles: List[Candle],
        atr: float,
        impulse: ImpulseAnalysis
    ) -> FlagPatternAnalysis:
        """
        Detect flag pattern.
        
        impulse = impulse_size >= 1.5 * ATR
        consolidation = range of last 5 candles <= 1.0 * ATR
        breakout = close > max(high last 5) + (0.10 * ATR)
        """
        result = FlagPatternAnalysis()
        
        if len(candles) < self.FLAG_LOOKBACK + 1 or atr <= 0:
            return result
        
        # Impulse validation
        result.impulse_valid = impulse.bullish_impulse or impulse.bearish_impulse
        
        # Consolidation analysis
        consolidation_candles = candles[-(self.FLAG_LOOKBACK+1):-1]
        consolidation_high = max(c.high for c in consolidation_candles)
        consolidation_low = min(c.low for c in consolidation_candles)
        result.consolidation_range = consolidation_high - consolidation_low
        
        result.consolidation_valid = result.consolidation_range <= (self.FLAG_CONSOLIDATION_MAX_ATR * atr)
        
        # Breakout
        last_candle = candles[-1]
        breakout_level = consolidation_high + (self.BREAKOUT_ATR_BUFFER * atr)
        result.breakout_valid = last_candle.close > breakout_level
        
        # Flag valid: all conditions met
        result.flag_valid = (
            result.impulse_valid
            and result.consolidation_valid
            and result.breakout_valid
        )
        
        return result
    
    # ========== DOUBLE BOTTOM ==========
    
    def analyze_double_bottom(
        self,
        swing_lows: List[SwingPoint],
        swing_highs: List[SwingPoint],
        current_price: float,
        atr: float
    ) -> DoubleBottomAnalysis:
        """
        Detect double bottom pattern.
        
        bottom_similarity = abs(low2 - low1) / ATR <= 0.30
        neckline = swing_high between the two lows
        break_neckline = close > neckline + (0.10 * ATR)
        """
        result = DoubleBottomAnalysis()
        
        if len(swing_lows) < 2 or not swing_highs or atr <= 0:
            return result
        
        # Get last two swing lows
        result.bottom1 = swing_lows[-2].price
        result.bottom2 = swing_lows[-1].price
        
        # Bottom similarity
        similarity_ratio = abs(result.bottom2 - result.bottom1) / atr
        result.bottom_similarity = similarity_ratio <= self.DOUBLE_BOTTOM_SIMILARITY_MAX
        
        # Find neckline (swing high between the two bottoms)
        bottom1_idx = swing_lows[-2].index
        bottom2_idx = swing_lows[-1].index
        
        neckline_candidates = [
            sh for sh in swing_highs 
            if bottom1_idx < sh.index < bottom2_idx
        ]
        
        if neckline_candidates:
            result.neckline = max(sh.price for sh in neckline_candidates)
        
        # Neckline break
        if result.neckline > 0:
            breakout_level = result.neckline + (self.BREAKOUT_ATR_BUFFER * atr)
            result.neckline_broken = current_price > breakout_level
        
        # Double bottom valid
        result.double_bottom_valid = (
            result.bottom_similarity
            and result.neckline_broken
        )
        
        return result
    
    # ========== SESSION ANALYSIS ==========
    
    def analyze_session(self) -> SessionAnalysis:
        """
        Analyze current session.
        
        NY optimal = 15:00-18:00 Italy time
        """
        result = SessionAnalysis()
        
        now_utc = datetime.now(timezone.utc)
        result.current_hour_utc = now_utc.hour
        
        # Convert to Italy time (UTC+2 summer, UTC+1 winter - using +2)
        result.current_hour_italy = (now_utc.hour + self.ITALY_UTC_OFFSET) % 24
        
        # NY optimal session
        result.ny_optimal = (
            self.NY_START_HOUR_ITALY <= result.current_hour_italy <= self.NY_END_HOUR_ITALY
        )
        
        return result
    
    # ========== TRADE LEVELS ==========
    
    def calculate_trade_levels(
        self,
        entry_price: float,
        atr: float,
        spread: float = 0.0
    ) -> TradeLevels:
        """
        Calculate SL, TP, and RR.
        
        sl_distance = max(0.60 * ATR, spread * 3)
        stop_loss = entry - sl_distance
        take_profit = entry + sl_distance * 1.0
        RR = reward / risk
        """
        result = TradeLevels()
        result.entry_price = entry_price
        
        if atr <= 0:
            return result
        
        # SL distance = max(0.60 * ATR, spread * 3)
        atr_based_sl = self.MIN_SL_ATR_MULTIPLE * atr
        spread_based_sl = self.MIN_SPREAD_MULTIPLE * spread if spread > 0 else 0
        result.sl_distance = max(atr_based_sl, spread_based_sl)
        
        # Stop loss (for BUY)
        result.stop_loss = entry_price - result.sl_distance
        
        # Take profit at 1.0 RR
        result.take_profit = entry_price + (result.sl_distance * self.TARGET_RR)
        
        # Risk and reward
        result.risk = abs(entry_price - result.stop_loss)
        result.reward = abs(result.take_profit - entry_price)
        
        # RR ratio
        if result.risk > 0:
            result.rr_ratio = result.reward / result.risk
        
        # RR valid
        result.rr_valid = result.rr_ratio >= self.MIN_RR
        
        return result
    
    # ========== MAIN ANALYSIS ==========
    
    def analyze(
        self,
        symbol: str,
        candles_m5: List[Dict],
        current_price: float,
        spread: float = 0.0
    ) -> SignalResult:
        """
        Complete mathematical analysis.
        
        Returns SignalResult with all calculated values.
        """
        rejection_reasons = []
        
        # Parse candles
        candles = self.parse_candles(candles_m5)
        
        if len(candles) < 30:
            rejection_reasons.append("insufficient_candles")
            return self._create_result(
                symbol=symbol,
                candles=candles,
                current_price=current_price,
                rejection_reasons=rejection_reasons
            )
        
        last_candle = candles[-1]
        
        # Session analysis
        session = self.analyze_session()
        if not session.ny_optimal:
            rejection_reasons.append(f"session_not_optimal_hour_{session.current_hour_italy}")
        
        # ATR / Volatility
        volatility = self.calculate_atr(candles)
        if not volatility.volatility_ok:
            rejection_reasons.append("volatility_too_low")
        
        atr = volatility.atr_14
        
        # Swing points
        swing_highs, swing_lows = self.find_swing_points(candles)
        
        # Trend analysis
        trend = self.analyze_trend(swing_highs, swing_lows)
        if not trend.bullish_trend_valid:
            rejection_reasons.append(f"trend_not_valid_hh{trend.higher_highs}_hl{trend.higher_lows}")
        
        # Impulse analysis
        impulse = self.analyze_impulse(swing_highs, swing_lows, atr)
        if not impulse.bullish_impulse:
            rejection_reasons.append(f"impulse_not_valid_atr_mult_{impulse.atr_multiple:.2f}")
        
        # Pullback analysis
        pullback = self.analyze_pullback(current_price, impulse)
        if not pullback.in_valid_zone:
            rejection_reasons.append(f"pullback_not_valid_ratio_{pullback.pullback_ratio:.2f}")
        
        # Candle validation
        if not last_candle.is_bullish:
            rejection_reasons.append(f"candle_not_bullish_body_{last_candle.body_ratio:.2f}_pos_{last_candle.close_position:.2f}")
        
        # Breakout analysis
        breakout = self.analyze_breakout(candles, atr)
        
        # Liquidity sweep
        liquidity = self.analyze_liquidity_sweep(candles)
        
        # Flag pattern
        flag = self.analyze_flag(candles, atr, impulse)
        
        # Double bottom
        double_bottom = self.analyze_double_bottom(swing_lows, swing_highs, current_price, atr)
        
        # Trade levels
        entry_price = last_candle.close
        levels = self.calculate_trade_levels(entry_price, atr, spread)
        if not levels.rr_valid:
            rejection_reasons.append(f"rr_not_valid_{levels.rr_ratio:.2f}")
        
        # Determine signal validity
        # BUY_signal = ALL conditions true
        signal_valid = (
            last_candle.is_bullish
            and trend.bullish_trend_valid
            and impulse.bullish_impulse
            and pullback.in_valid_zone
            and session.ny_optimal
            and volatility.volatility_ok
            and levels.rr_valid
        )
        
        # Direction
        direction = "BUY" if signal_valid else "NONE"
        
        # Check if direction allowed
        if direction == "BUY" and "BUY" not in self.ALLOWED_DIRECTIONS:
            signal_valid = False
            rejection_reasons.append("direction_buy_not_allowed")
        
        # Create result
        result = SignalResult(
            timestamp=datetime.utcnow().isoformat(),
            symbol=symbol,
            
            # Raw OHLC
            open=last_candle.open,
            high=last_candle.high,
            low=last_candle.low,
            close=last_candle.close,
            
            # Candle metrics
            range=last_candle.range,
            body_ratio=last_candle.body_ratio,
            close_position=last_candle.close_position,
            bullish_candle=last_candle.is_bullish,
            bearish_candle=last_candle.is_bearish,
            
            # Trend
            bullish_trend_valid=trend.bullish_trend_valid,
            bearish_trend_valid=trend.bearish_trend_valid,
            higher_highs=trend.higher_highs,
            higher_lows=trend.higher_lows,
            
            # Impulse
            impulse_size=impulse.impulse_size,
            impulse_atr_multiple=impulse.atr_multiple,
            bullish_impulse=impulse.bullish_impulse,
            
            # Pullback
            pullback_ratio=pullback.pullback_ratio,
            pullback_valid=pullback.in_valid_zone,
            
            # Breakout
            breakout_retest_valid=breakout.breakout_retest_valid,
            
            # Liquidity
            liquidity_sweep=liquidity.bullish_sweep,
            
            # Flag
            flag_valid=flag.flag_valid,
            
            # Double Bottom
            double_bottom_valid=double_bottom.double_bottom_valid,
            
            # Volatility
            atr_14=atr,
            volatility_ok=volatility.volatility_ok,
            
            # Session
            session_hour_italy=session.current_hour_italy,
            ny_optimal=session.ny_optimal,
            
            # Trade levels
            entry_price=levels.entry_price,
            stop_loss=levels.stop_loss,
            take_profit=levels.take_profit,
            rr_ratio=levels.rr_ratio,
            rr_valid=levels.rr_valid,
            
            # Decision
            signal_valid=signal_valid,
            direction=direction,
            rejection_reasons=rejection_reasons
        )
        
        # Track the result
        self._track_result(result)
        
        return result
    
    def _create_result(
        self,
        symbol: str,
        candles: List[Candle],
        current_price: float,
        rejection_reasons: List[str]
    ) -> SignalResult:
        """Create a minimal result when analysis can't be completed"""
        last_candle = candles[-1] if candles else Candle("", 0, 0, 0, 0)
        
        return SignalResult(
            timestamp=datetime.utcnow().isoformat(),
            symbol=symbol,
            open=last_candle.open,
            high=last_candle.high,
            low=last_candle.low,
            close=last_candle.close,
            range=last_candle.range,
            body_ratio=last_candle.body_ratio,
            close_position=last_candle.close_position,
            bullish_candle=last_candle.is_bullish,
            bearish_candle=last_candle.is_bearish,
            bullish_trend_valid=False,
            bearish_trend_valid=False,
            higher_highs=0,
            higher_lows=0,
            impulse_size=0,
            impulse_atr_multiple=0,
            bullish_impulse=False,
            pullback_ratio=0,
            pullback_valid=False,
            breakout_retest_valid=False,
            liquidity_sweep=False,
            flag_valid=False,
            double_bottom_valid=False,
            atr_14=0,
            volatility_ok=False,
            session_hour_italy=0,
            ny_optimal=False,
            entry_price=current_price,
            stop_loss=0,
            take_profit=0,
            rr_ratio=0,
            rr_valid=False,
            signal_valid=False,
            direction="NONE",
            rejection_reasons=rejection_reasons
        )
    
    def _track_result(self, result: SignalResult):
        """Save result to tracking"""
        self.tracking_records.append(asdict(result))
        self._save_tracking()
        
        # Log
        status = "✅ VALID" if result.signal_valid else "❌ REJECTED"
        logger.info(f"[MATH] {result.symbol} {result.direction} {status}")
        if result.rejection_reasons:
            for reason in result.rejection_reasons:
                logger.info(f"  → {reason}")
    
    # ========== STATISTICS ==========
    
    def get_statistics(self) -> Dict:
        """Get engine statistics"""
        total = len(self.tracking_records)
        valid = sum(1 for r in self.tracking_records if r.get('signal_valid'))
        rejected = total - valid
        
        # Outcome stats
        outcomes = {
            'tp': sum(1 for r in self.tracking_records if r.get('outcome') == 'tp'),
            'sl': sum(1 for r in self.tracking_records if r.get('outcome') == 'sl'),
            'pending': sum(1 for r in self.tracking_records if r.get('outcome') == 'pending'),
            'expired': sum(1 for r in self.tracking_records if r.get('outcome') == 'expired')
        }
        
        # Rejection reasons breakdown
        rejection_counts = {}
        for r in self.tracking_records:
            for reason in r.get('rejection_reasons', []):
                rejection_counts[reason] = rejection_counts.get(reason, 0) + 1
        
        return {
            'total_analyses': total,
            'valid_signals': valid,
            'rejected_signals': rejected,
            'acceptance_rate': round(valid / total * 100, 2) if total > 0 else 0,
            'outcomes': outcomes,
            'rejection_breakdown': dict(sorted(
                rejection_counts.items(), 
                key=lambda x: x[1], 
                reverse=True
            )[:10])
        }


# Global instance
math_engine = MathEngine()
