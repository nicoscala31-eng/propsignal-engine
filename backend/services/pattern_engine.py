"""
Pattern Engine V1.0 - Pattern-Based Signal Detection
=====================================================

MATHEMATICALLY DEFINED PATTERNS:
1. Trend Structure (HH/HL, LH/LL)
2. Fibonacci Pullback (50%-61.8%)
3. Breakout + Retest
4. Liquidity Sweep
5. Flag Pattern

Each pattern has:
- Clear mathematical definition
- No subjective interpretation
- Testable conditions

Usage:
    from services.pattern_engine import pattern_engine
    patterns = pattern_engine.scan_all_patterns(symbol, candles_h1, candles_m15, candles_m5)
"""

import logging
from typing import List, Dict, Optional, Tuple
from dataclasses import dataclass, field, asdict
from datetime import datetime, timedelta
from enum import Enum

from services.helpers.technical_indicators import (
    calculate_atr, calculate_ema, calculate_ema_slope,
    find_swing_points, get_recent_swing_highs, get_recent_swing_lows,
    calculate_fibonacci_levels, SwingPoint
)

logger = logging.getLogger(__name__)


# ==================== ENUMS ====================

class PatternType(Enum):
    TREND_STRUCTURE = "trend_structure"
    FIBONACCI_PULLBACK = "fibonacci_pullback"
    BREAKOUT_RETEST = "breakout_retest"
    LIQUIDITY_SWEEP = "liquidity_sweep"
    FLAG = "flag"


class TrendDirection(Enum):
    BULLISH = "bullish"
    BEARISH = "bearish"
    RANGE = "range"


class Session(Enum):
    LONDON = "London"
    NEW_YORK = "New York"
    OVERLAP = "London/NY Overlap"
    OFF = "Off"


# ==================== DATA CLASSES ====================

@dataclass
class PatternDetection:
    """Result of a pattern detection"""
    pattern_type: str
    direction: str  # BUY or SELL
    confidence: float  # 0-100
    entry_price: float
    stop_loss: float
    take_profit: float
    risk_reward: float
    details: Dict = field(default_factory=dict)
    
    def to_dict(self) -> Dict:
        return asdict(self)


@dataclass
class TrendAnalysis:
    """Trend structure analysis result"""
    direction: TrendDirection
    hh_count: int = 0  # Higher highs
    hl_count: int = 0  # Higher lows
    lh_count: int = 0  # Lower highs
    ll_count: int = 0  # Lower lows
    strength: float = 0.0  # 0-100
    last_swing_high: Optional[SwingPoint] = None
    last_swing_low: Optional[SwingPoint] = None
    

@dataclass 
class MarketContext:
    """Complete market context for pattern detection"""
    symbol: str
    timestamp: datetime
    current_price: float
    session: Session
    
    # Trend by timeframe
    trend_h1: TrendAnalysis
    trend_m15: TrendAnalysis
    trend_m5: TrendAnalysis
    
    # Technical indicators
    atr_m5: float
    atr_h1: float
    ema20_m5: float
    ema50_m5: float
    
    # Data validity
    data_valid: bool = True
    validation_error: str = ""


# ==================== CONFIGURATION ====================

@dataclass
class PatternConfig:
    """Configuration for pattern detection"""
    # ATR minimums (in price units)
    min_atr_eurusd: float = 0.00030  # 3 pips
    min_atr_xauusd: float = 0.50     # 50 cents
    
    # Swing detection
    swing_lookback: int = 2
    min_swing_distance: int = 5  # Minimum candles between swings
    
    # Fibonacci
    fib_zone_start: float = 0.5
    fib_zone_end: float = 0.618
    fib_tolerance: float = 0.03  # 3% tolerance around fib levels
    
    # Breakout
    breakout_atr_multiplier: float = 0.1
    retest_buffer_atr: float = 0.2
    retest_max_candles: int = 5
    
    # Liquidity sweep
    liquidity_lookback: int = 20
    
    # Flag
    flag_impulse_atr: float = 1.5  # Min impulse size in ATR
    flag_consolidation_atr: float = 0.7  # Max consolidation range in ATR
    flag_consolidation_candles: int = 5
    
    # R:R
    min_rr: float = 1.5
    default_rr_target: float = 2.0
    
    # Confluence
    require_trend_alignment: bool = True
    require_session_filter: bool = True


DEFAULT_CONFIG = PatternConfig()


# ==================== PATTERN ENGINE ====================

class PatternEngine:
    """
    Pattern-based signal detection engine.
    
    All patterns are mathematically defined with no subjective interpretation.
    """
    
    def __init__(self, config: PatternConfig = None):
        self.config = config or DEFAULT_CONFIG
        self.detection_count = 0
        self.last_detection_time: Dict[str, datetime] = {}
        
        logger.info("Pattern Engine V1.0 initialized")
    
    # ==================== SESSION DETECTION ====================
    
    def get_current_session(self, utc_time: datetime = None) -> Session:
        """
        Determine current trading session.
        
        Sessions (UTC):
        - London: 07:00-10:00
        - London/NY Overlap: 12:00-16:00
        - New York: 16:00-21:00
        - Off: All other times
        """
        if utc_time is None:
            utc_time = datetime.utcnow()
        
        hour = utc_time.hour
        weekday = utc_time.weekday()  # 0=Monday, 6=Sunday
        
        # Weekend check
        if weekday == 5 and hour >= 21:  # Friday after 21:00
            return Session.OFF
        if weekday == 6:  # Saturday
            return Session.OFF
        if weekday == 0 and hour < 21:  # Sunday before 21:00
            return Session.OFF
        
        # Session detection
        if 7 <= hour < 12:
            return Session.LONDON
        elif 12 <= hour < 16:
            return Session.OVERLAP
        elif 16 <= hour < 21:
            return Session.NEW_YORK
        else:
            return Session.OFF
    
    def is_session_valid(self, session: Session) -> bool:
        """Check if session allows trading"""
        return session != Session.OFF
    
    # ==================== DATA VALIDATION ====================
    
    def validate_market_data(self, candles: List[Dict], symbol: str) -> Tuple[bool, str]:
        """
        Validate market data quality.
        
        Checks:
        1. Data freshness (< 90 seconds old)
        2. Price movement (last 3 closes not identical)
        3. Sufficient data (>= 150 candles)
        4. Market open (Sunday 21:00 - Friday 21:00 UTC)
        """
        if not candles or len(candles) < 10:
            return False, "Insufficient candles"
        
        # Check sufficient data
        if len(candles) < 150:
            return False, f"Need 150 candles, got {len(candles)}"
        
        # Check data freshness
        last_candle = candles[-1]
        last_time_str = last_candle.get('datetime', '')
        
        try:
            if last_time_str:
                last_time = datetime.fromisoformat(last_time_str.replace('Z', '+00:00'))
                age = datetime.utcnow() - last_time.replace(tzinfo=None)
                if age.total_seconds() > 90:
                    return False, f"Data stale: {age.total_seconds():.0f}s old"
        except:
            pass  # Skip freshness check if parsing fails
        
        # Check for frozen prices (last 3 closes identical)
        if len(candles) >= 3:
            last_3_closes = [c.get('close', 0) for c in candles[-3:]]
            if len(set(last_3_closes)) == 1:
                return False, "Frozen prices detected"
        
        # Check market hours
        now = datetime.utcnow()
        weekday = now.weekday()
        hour = now.hour
        
        # Market closed: Friday 21:00 - Sunday 21:00 UTC
        if (weekday == 4 and hour >= 21) or weekday == 5 or (weekday == 6 and hour < 21):
            return False, "Forex market closed"
        
        return True, "OK"
    
    # ==================== TREND STRUCTURE ====================
    
    def detect_trend_structure(self, candles: List[Dict]) -> TrendAnalysis:
        """
        Detect trend structure using swing points.
        
        BULLISH: At least 2 consecutive HH+HL sequences
        BEARISH: At least 2 consecutive LH+LL sequences
        RANGE: Neither condition met
        
        Math:
        - HH: swing_high[i] > swing_high[i-1]
        - HL: swing_low[i] > swing_low[i-1]
        - LH: swing_high[i] < swing_high[i-1]
        - LL: swing_low[i] < swing_low[i-1]
        """
        result = TrendAnalysis(direction=TrendDirection.RANGE)
        
        if len(candles) < 30:
            return result
        
        # Find swing points
        swing_highs, swing_lows = find_swing_points(candles, self.config.swing_lookback)
        
        if len(swing_highs) < 3 or len(swing_lows) < 3:
            return result
        
        # Store last swings
        result.last_swing_high = swing_highs[-1] if swing_highs else None
        result.last_swing_low = swing_lows[-1] if swing_lows else None
        
        # Count HH/HL and LH/LL sequences
        hh_count = 0
        hl_count = 0
        lh_count = 0
        ll_count = 0
        
        # Analyze last 5 swing highs
        for i in range(1, min(5, len(swing_highs))):
            if swing_highs[-i].price > swing_highs[-i-1].price:
                hh_count += 1
            elif swing_highs[-i].price < swing_highs[-i-1].price:
                lh_count += 1
        
        # Analyze last 5 swing lows
        for i in range(1, min(5, len(swing_lows))):
            if swing_lows[-i].price > swing_lows[-i-1].price:
                hl_count += 1
            elif swing_lows[-i].price < swing_lows[-i-1].price:
                ll_count += 1
        
        result.hh_count = hh_count
        result.hl_count = hl_count
        result.lh_count = lh_count
        result.ll_count = ll_count
        
        # Determine trend
        # BULLISH: HH >= 2 AND HL >= 2
        if hh_count >= 2 and hl_count >= 2:
            result.direction = TrendDirection.BULLISH
            result.strength = min(100, (hh_count + hl_count) * 15)
        # BEARISH: LH >= 2 AND LL >= 2
        elif lh_count >= 2 and ll_count >= 2:
            result.direction = TrendDirection.BEARISH
            result.strength = min(100, (lh_count + ll_count) * 15)
        else:
            result.direction = TrendDirection.RANGE
            result.strength = 0
        
        return result
    
    # ==================== FIBONACCI PULLBACK ====================
    
    def detect_fibonacci_pullback(self, candles: List[Dict], trend: TrendAnalysis, 
                                   current_price: float) -> Optional[PatternDetection]:
        """
        Detect Fibonacci pullback in the 50%-61.8% zone.
        
        BUY condition:
        - trend = BULLISH
        - price between fib50 and fib618 of last swing
        - swing_high > swing_low (valid impulse)
        
        SELL condition:
        - trend = BEARISH
        - price between fib50 and fib618 of last swing
        - swing_low < swing_high (valid impulse)
        
        Entry: current price
        SL: Beyond swing point + buffer
        TP: 2R target
        """
        if trend.direction == TrendDirection.RANGE:
            return None
        
        if not trend.last_swing_high or not trend.last_swing_low:
            return None
        
        swing_high = trend.last_swing_high.price
        swing_low = trend.last_swing_low.price
        
        if swing_high <= swing_low:
            return None
        
        # Calculate Fibonacci levels
        fib_range = swing_high - swing_low
        fib50 = swing_high - (fib_range * 0.5)
        fib618 = swing_high - (fib_range * 0.618)
        
        # Tolerance
        tolerance = fib_range * self.config.fib_tolerance
        
        if trend.direction == TrendDirection.BULLISH:
            # BUY: Price should be in fib zone (pulled back from high)
            # fib50 is higher, fib618 is lower
            zone_top = fib50 + tolerance
            zone_bottom = fib618 - tolerance
            
            if zone_bottom <= current_price <= zone_top:
                # Valid pullback - calculate trade levels
                entry = current_price
                sl = swing_low - (fib_range * 0.1)  # 10% below swing low
                risk = entry - sl
                tp = entry + (risk * self.config.default_rr_target)
                
                return PatternDetection(
                    pattern_type=PatternType.FIBONACCI_PULLBACK.value,
                    direction="BUY",
                    confidence=60 + (trend.strength * 0.3),
                    entry_price=entry,
                    stop_loss=sl,
                    take_profit=tp,
                    risk_reward=self.config.default_rr_target,
                    details={
                        'swing_high': swing_high,
                        'swing_low': swing_low,
                        'fib50': fib50,
                        'fib618': fib618,
                        'pullback_depth': (swing_high - current_price) / fib_range
                    }
                )
        
        elif trend.direction == TrendDirection.BEARISH:
            # SELL: Price should be in fib zone (bounced from low)
            # For bearish, fib levels are from bottom
            fib50_bear = swing_low + (fib_range * 0.5)
            fib618_bear = swing_low + (fib_range * 0.618)
            
            zone_bottom = fib50_bear - tolerance
            zone_top = fib618_bear + tolerance
            
            if zone_bottom <= current_price <= zone_top:
                entry = current_price
                sl = swing_high + (fib_range * 0.1)  # 10% above swing high
                risk = sl - entry
                tp = entry - (risk * self.config.default_rr_target)
                
                return PatternDetection(
                    pattern_type=PatternType.FIBONACCI_PULLBACK.value,
                    direction="SELL",
                    confidence=60 + (trend.strength * 0.3),
                    entry_price=entry,
                    stop_loss=sl,
                    take_profit=tp,
                    risk_reward=self.config.default_rr_target,
                    details={
                        'swing_high': swing_high,
                        'swing_low': swing_low,
                        'fib50': fib50_bear,
                        'fib618': fib618_bear,
                        'pullback_depth': (current_price - swing_low) / fib_range
                    }
                )
        
        return None
    
    # ==================== BREAKOUT + RETEST ====================
    
    def detect_breakout_retest(self, candles: List[Dict], atr: float) -> Optional[PatternDetection]:
        """
        Detect breakout followed by retest pattern.
        
        Conditions:
        1. Price breaks a key level (recent swing high/low)
        2. Breakout confirms: close > level + (0.1 * ATR)
        3. Price returns to level within 5 candles
        4. Rejection candle forms (wick > 50% of body)
        
        Entry: After rejection candle
        SL: Beyond the level
        TP: 2R target
        """
        if len(candles) < 25 or atr <= 0:
            return None
        
        # Find recent key levels (swing highs/lows)
        swing_highs, swing_lows = find_swing_points(candles[:-5], self.config.swing_lookback)
        
        if not swing_highs and not swing_lows:
            return None
        
        current_price = candles[-1].get('close', 0)
        breakout_threshold = atr * self.config.breakout_atr_multiplier
        retest_buffer = atr * self.config.retest_buffer_atr
        
        # Check for BULLISH breakout + retest (break above resistance)
        for sh in swing_highs[-3:]:
            level = sh.price
            
            # Check if breakout occurred in recent candles
            breakout_candle_idx = None
            for i in range(-10, -1):
                if candles[i].get('close', 0) > level + breakout_threshold:
                    breakout_candle_idx = i
                    break
            
            if breakout_candle_idx is None:
                continue
            
            # Check for retest (price came back to level)
            retest_found = False
            for i in range(breakout_candle_idx + 1, 0):
                low = candles[i].get('low', 0)
                if abs(low - level) <= retest_buffer:
                    retest_found = True
                    
                    # Check for rejection candle
                    candle = candles[i]
                    body = abs(candle.get('close', 0) - candle.get('open', 0))
                    lower_wick = min(candle.get('open', 0), candle.get('close', 0)) - candle.get('low', 0)
                    
                    if lower_wick > body * 0.5 and candle.get('close', 0) > candle.get('open', 0):
                        # Valid BUY signal
                        entry = current_price
                        sl = level - retest_buffer - (atr * 0.5)
                        risk = entry - sl
                        tp = entry + (risk * self.config.default_rr_target)
                        
                        return PatternDetection(
                            pattern_type=PatternType.BREAKOUT_RETEST.value,
                            direction="BUY",
                            confidence=70,
                            entry_price=entry,
                            stop_loss=sl,
                            take_profit=tp,
                            risk_reward=self.config.default_rr_target,
                            details={
                                'level': level,
                                'breakout_candle': breakout_candle_idx,
                                'retest_candle': i
                            }
                        )
                    break
        
        # Check for BEARISH breakout + retest (break below support)
        for sl_point in swing_lows[-3:]:
            level = sl_point.price
            
            # Check if breakout occurred
            breakout_candle_idx = None
            for i in range(-10, -1):
                if candles[i].get('close', 0) < level - breakout_threshold:
                    breakout_candle_idx = i
                    break
            
            if breakout_candle_idx is None:
                continue
            
            # Check for retest
            for i in range(breakout_candle_idx + 1, 0):
                high = candles[i].get('high', 0)
                if abs(high - level) <= retest_buffer:
                    candle = candles[i]
                    body = abs(candle.get('close', 0) - candle.get('open', 0))
                    upper_wick = candle.get('high', 0) - max(candle.get('open', 0), candle.get('close', 0))
                    
                    if upper_wick > body * 0.5 and candle.get('close', 0) < candle.get('open', 0):
                        # Valid SELL signal
                        entry = current_price
                        sl_price = level + retest_buffer + (atr * 0.5)
                        risk = sl_price - entry
                        tp = entry - (risk * self.config.default_rr_target)
                        
                        return PatternDetection(
                            pattern_type=PatternType.BREAKOUT_RETEST.value,
                            direction="SELL",
                            confidence=70,
                            entry_price=entry,
                            stop_loss=sl_price,
                            take_profit=tp,
                            risk_reward=self.config.default_rr_target,
                            details={
                                'level': level,
                                'breakout_candle': breakout_candle_idx,
                                'retest_candle': i
                            }
                        )
                    break
        
        return None
    
    # ==================== LIQUIDITY SWEEP ====================
    
    def detect_liquidity_sweep(self, candles: List[Dict], atr: float) -> Optional[PatternDetection]:
        """
        Detect liquidity sweep pattern.
        
        BEARISH SWEEP:
        - Current high > max(last 20 highs)
        - BUT close is BELOW the previous high
        - Indicates stop hunt above resistance
        
        BULLISH SWEEP:
        - Current low < min(last 20 lows)
        - BUT close is ABOVE the previous low
        - Indicates stop hunt below support
        
        Entry: After sweep candle
        SL: Beyond the sweep wick
        TP: 2R target
        """
        lookback = self.config.liquidity_lookback
        
        if len(candles) < lookback + 5 or atr <= 0:
            return None
        
        # Get ranges
        prev_highs = [c.get('high', 0) for c in candles[-(lookback+1):-1]]
        prev_lows = [c.get('low', 0) for c in candles[-(lookback+1):-1]]
        
        prev_high = max(prev_highs)
        prev_low = min(prev_lows)
        
        current = candles[-1]
        current_high = current.get('high', 0)
        current_low = current.get('low', 0)
        current_close = current.get('close', 0)
        current_open = current.get('open', 0)
        
        # BEARISH SWEEP: swept highs but closed below
        if current_high > prev_high and current_close < prev_high:
            # Check for bearish rejection (upper wick)
            body = abs(current_close - current_open)
            upper_wick = current_high - max(current_close, current_open)
            
            if upper_wick > body * 0.3:  # Significant wick
                entry = current_close
                sl = current_high + (atr * 0.3)
                risk = sl - entry
                tp = entry - (risk * self.config.default_rr_target)
                
                return PatternDetection(
                    pattern_type=PatternType.LIQUIDITY_SWEEP.value,
                    direction="SELL",
                    confidence=75,
                    entry_price=entry,
                    stop_loss=sl,
                    take_profit=tp,
                    risk_reward=self.config.default_rr_target,
                    details={
                        'sweep_type': 'bearish_sweep',
                        'prev_high': prev_high,
                        'swept_to': current_high,
                        'sweep_depth': current_high - prev_high
                    }
                )
        
        # BULLISH SWEEP: swept lows but closed above
        if current_low < prev_low and current_close > prev_low:
            # Check for bullish rejection (lower wick)
            body = abs(current_close - current_open)
            lower_wick = min(current_close, current_open) - current_low
            
            if lower_wick > body * 0.3:  # Significant wick
                entry = current_close
                sl = current_low - (atr * 0.3)
                risk = entry - sl
                tp = entry + (risk * self.config.default_rr_target)
                
                return PatternDetection(
                    pattern_type=PatternType.LIQUIDITY_SWEEP.value,
                    direction="BUY",
                    confidence=75,
                    entry_price=entry,
                    stop_loss=sl,
                    take_profit=tp,
                    risk_reward=self.config.default_rr_target,
                    details={
                        'sweep_type': 'bullish_sweep',
                        'prev_low': prev_low,
                        'swept_to': current_low,
                        'sweep_depth': prev_low - current_low
                    }
                )
        
        return None
    
    # ==================== FLAG PATTERN ====================
    
    def detect_flag(self, candles: List[Dict], atr: float) -> Optional[PatternDetection]:
        """
        Detect flag continuation pattern.
        
        Conditions:
        1. Impulse leg > 1.5 * ATR
        2. Consolidation with tight range (< 0.7 * ATR)
        3. Breakout in direction of impulse
        
        Entry: On breakout
        SL: Beyond consolidation
        TP: Impulse leg projected from breakout
        """
        if len(candles) < 20 or atr <= 0:
            return None
        
        impulse_atr = self.config.flag_impulse_atr
        consol_atr = self.config.flag_consolidation_atr
        consol_candles = self.config.flag_consolidation_candles
        
        # Look for impulse in candles[-15:-5]
        impulse_section = candles[-15:-consol_candles]
        consol_section = candles[-consol_candles:]
        
        if len(impulse_section) < 5:
            return None
        
        # Calculate impulse
        impulse_start = impulse_section[0].get('open', 0)
        impulse_high = max(c.get('high', 0) for c in impulse_section)
        impulse_low = min(c.get('low', 0) for c in impulse_section)
        impulse_end = impulse_section[-1].get('close', 0)
        
        bullish_impulse = impulse_end - impulse_start > impulse_atr * atr
        bearish_impulse = impulse_start - impulse_end > impulse_atr * atr
        
        if not bullish_impulse and not bearish_impulse:
            return None
        
        # Check consolidation
        consol_high = max(c.get('high', 0) for c in consol_section)
        consol_low = min(c.get('low', 0) for c in consol_section)
        consol_range = consol_high - consol_low
        
        if consol_range > consol_atr * atr:
            return None  # Consolidation too wide
        
        current = candles[-1]
        current_close = current.get('close', 0)
        
        # Check for breakout
        if bullish_impulse:
            # Bullish flag - expect upward breakout
            if current_close > consol_high:
                entry = current_close
                sl = consol_low - (atr * 0.2)
                impulse_size = impulse_end - impulse_start
                tp = entry + impulse_size  # Project impulse
                risk = entry - sl
                rr = (tp - entry) / risk if risk > 0 else 0
                
                if rr >= self.config.min_rr:
                    return PatternDetection(
                        pattern_type=PatternType.FLAG.value,
                        direction="BUY",
                        confidence=70,
                        entry_price=entry,
                        stop_loss=sl,
                        take_profit=tp,
                        risk_reward=rr,
                        details={
                            'impulse_size': impulse_size,
                            'consol_range': consol_range,
                            'flag_type': 'bull_flag'
                        }
                    )
        
        elif bearish_impulse:
            # Bearish flag - expect downward breakout
            if current_close < consol_low:
                entry = current_close
                sl = consol_high + (atr * 0.2)
                impulse_size = impulse_start - impulse_end
                tp = entry - impulse_size  # Project impulse
                risk = sl - entry
                rr = (entry - tp) / risk if risk > 0 else 0
                
                if rr >= self.config.min_rr:
                    return PatternDetection(
                        pattern_type=PatternType.FLAG.value,
                        direction="SELL",
                        confidence=70,
                        entry_price=entry,
                        stop_loss=sl,
                        take_profit=tp,
                        risk_reward=rr,
                        details={
                            'impulse_size': impulse_size,
                            'consol_range': consol_range,
                            'flag_type': 'bear_flag'
                        }
                    )
        
        return None
    
    # ==================== CONFLUENCE CHECK ====================
    
    def check_confluence(self, pattern: PatternDetection, context: MarketContext) -> Tuple[bool, str]:
        """
        Check if pattern has required confluence.
        
        Required:
        1. Trend H1 aligns with pattern direction
        2. Trend M15 aligns with pattern direction  
        3. Valid trading session
        4. ATR above minimum
        """
        reasons = []
        
        # Trend alignment
        if self.config.require_trend_alignment:
            expected_trend = TrendDirection.BULLISH if pattern.direction == "BUY" else TrendDirection.BEARISH
            
            if context.trend_h1.direction != expected_trend:
                reasons.append(f"H1 trend mismatch: {context.trend_h1.direction.value}")
            
            if context.trend_m15.direction != expected_trend:
                reasons.append(f"M15 trend mismatch: {context.trend_m15.direction.value}")
        
        # Session filter
        if self.config.require_session_filter:
            if not self.is_session_valid(context.session):
                reasons.append(f"Invalid session: {context.session.value}")
        
        # ATR minimum
        min_atr = self.config.min_atr_eurusd if 'EUR' in context.symbol else self.config.min_atr_xauusd
        if context.atr_m5 < min_atr:
            reasons.append(f"ATR too low: {context.atr_m5:.6f} < {min_atr:.6f}")
        
        if reasons:
            return False, "; ".join(reasons)
        
        return True, "All confluence met"
    
    # ==================== MAIN SCAN METHOD ====================
    
    def build_market_context(self, symbol: str, candles_h1: List[Dict], 
                             candles_m15: List[Dict], candles_m5: List[Dict],
                             current_price: float) -> MarketContext:
        """
        Build complete market context for pattern detection.
        """
        # Validate data
        valid, error = self.validate_market_data(candles_m5, symbol)
        
        # Get current session
        session = self.get_current_session()
        
        # Analyze trends
        trend_h1 = self.detect_trend_structure(candles_h1)
        trend_m15 = self.detect_trend_structure(candles_m15)
        trend_m5 = self.detect_trend_structure(candles_m5)
        
        # Calculate indicators
        atr_m5 = calculate_atr(candles_m5, 14) if len(candles_m5) >= 15 else 0
        atr_h1 = calculate_atr(candles_h1, 14) if len(candles_h1) >= 15 else 0
        ema20_m5 = calculate_ema(candles_m5, 20) if len(candles_m5) >= 20 else 0
        ema50_m5 = calculate_ema(candles_m5, 50) if len(candles_m5) >= 50 else 0
        
        return MarketContext(
            symbol=symbol,
            timestamp=datetime.utcnow(),
            current_price=current_price,
            session=session,
            trend_h1=trend_h1,
            trend_m15=trend_m15,
            trend_m5=trend_m5,
            atr_m5=atr_m5,
            atr_h1=atr_h1,
            ema20_m5=ema20_m5,
            ema50_m5=ema50_m5,
            data_valid=valid,
            validation_error=error
        )
    
    def scan_all_patterns(self, symbol: str, candles_h1: List[Dict], 
                          candles_m15: List[Dict], candles_m5: List[Dict],
                          current_price: float) -> List[PatternDetection]:
        """
        Scan for all patterns with confluence check.
        
        Returns list of valid patterns that pass all filters.
        """
        patterns = []
        
        # Build market context
        context = self.build_market_context(symbol, candles_h1, candles_m15, candles_m5, current_price)
        
        # Skip if data invalid
        if not context.data_valid:
            logger.warning(f"[PATTERN] Data invalid for {symbol}: {context.validation_error}")
            return patterns
        
        # Skip if session invalid
        if not self.is_session_valid(context.session):
            logger.debug(f"[PATTERN] Session off for {symbol}")
            return patterns
        
        atr = context.atr_m5
        
        # 1. Fibonacci Pullback
        fib_h1 = self.detect_fibonacci_pullback(candles_h1, context.trend_h1, current_price)
        if fib_h1:
            valid, reason = self.check_confluence(fib_h1, context)
            if valid:
                patterns.append(fib_h1)
                logger.info(f"[PATTERN] Fibonacci Pullback detected: {symbol} {fib_h1.direction}")
            else:
                logger.debug(f"[PATTERN] Fib rejected: {reason}")
        
        # 2. Breakout + Retest
        breakout = self.detect_breakout_retest(candles_m15, atr)
        if breakout:
            valid, reason = self.check_confluence(breakout, context)
            if valid:
                patterns.append(breakout)
                logger.info(f"[PATTERN] Breakout Retest detected: {symbol} {breakout.direction}")
            else:
                logger.debug(f"[PATTERN] Breakout rejected: {reason}")
        
        # 3. Liquidity Sweep
        sweep = self.detect_liquidity_sweep(candles_m5, atr)
        if sweep:
            valid, reason = self.check_confluence(sweep, context)
            if valid:
                patterns.append(sweep)
                logger.info(f"[PATTERN] Liquidity Sweep detected: {symbol} {sweep.direction}")
            else:
                logger.debug(f"[PATTERN] Sweep rejected: {reason}")
        
        # 4. Flag Pattern
        flag = self.detect_flag(candles_m15, atr)
        if flag:
            valid, reason = self.check_confluence(flag, context)
            if valid:
                patterns.append(flag)
                logger.info(f"[PATTERN] Flag detected: {symbol} {flag.direction}")
            else:
                logger.debug(f"[PATTERN] Flag rejected: {reason}")
        
        self.detection_count += len(patterns)
        
        return patterns
    
    def get_stats(self) -> Dict:
        """Get engine statistics"""
        return {
            'total_detections': self.detection_count,
            'config': asdict(self.config)
        }


# Global instance
pattern_engine = PatternEngine()
