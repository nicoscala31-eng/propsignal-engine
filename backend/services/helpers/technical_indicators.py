"""
Technical Indicators Helper
===========================
Pure price-action based indicators for PropSignal Engine v10.0

Indicators:
- EMA (20, 50)
- ATR (14)
- Swing Points (pivot-based)
- Fibonacci Levels
"""

from typing import List, Dict, Tuple, Optional
from dataclasses import dataclass
import logging

logger = logging.getLogger(__name__)


@dataclass
class SwingPoint:
    """Represents a swing high or low"""
    price: float
    index: int
    candle_time: str = ""


@dataclass
class TechnicalContext:
    """Complete technical context for an asset"""
    ema20: float
    ema50: float
    ema20_slope: float  # Positive = rising, Negative = falling
    atr14: float
    swing_highs: List[SwingPoint]
    swing_lows: List[SwingPoint]
    current_price: float
    
    @property
    def price_above_ema20(self) -> bool:
        return self.current_price > self.ema20
    
    @property
    def price_below_ema20(self) -> bool:
        return self.current_price < self.ema20
    
    @property
    def ema20_above_ema50(self) -> bool:
        return self.ema20 > self.ema50
    
    @property
    def ema20_below_ema50(self) -> bool:
        return self.ema20 < self.ema50


def calculate_ema(candles: List[Dict], period: int, price_key: str = 'close') -> float:
    """
    Calculate Exponential Moving Average
    
    Args:
        candles: List of OHLC candles
        period: EMA period (e.g., 20, 50)
        price_key: Price to use ('close', 'high', 'low')
    
    Returns:
        EMA value
    """
    if len(candles) < period:
        return 0.0
    
    prices = [c.get(price_key, 0) for c in candles]
    
    # Calculate SMA for initial value
    sma = sum(prices[:period]) / period
    
    # EMA multiplier
    multiplier = 2 / (period + 1)
    
    # Calculate EMA
    ema = sma
    for price in prices[period:]:
        ema = (price - ema) * multiplier + ema
    
    return ema


def calculate_ema_series(candles: List[Dict], period: int, price_key: str = 'close') -> List[float]:
    """
    Calculate EMA series for all candles
    
    Returns list of EMA values (same length as candles)
    """
    if len(candles) < period:
        return [0.0] * len(candles)
    
    prices = [c.get(price_key, 0) for c in candles]
    ema_series = []
    
    # SMA for first 'period' values
    sma = sum(prices[:period]) / period
    for i in range(period):
        ema_series.append(sma)
    
    # EMA for rest
    multiplier = 2 / (period + 1)
    ema = sma
    for price in prices[period:]:
        ema = (price - ema) * multiplier + ema
        ema_series.append(ema)
    
    return ema_series


def calculate_ema_slope(candles: List[Dict], period: int, lookback: int = 5) -> float:
    """
    Calculate EMA slope (rate of change)
    
    Positive = rising, Negative = falling
    Returns normalized slope (-1 to +1)
    """
    ema_series = calculate_ema_series(candles, period)
    
    if len(ema_series) < lookback + 1:
        return 0.0
    
    # Calculate slope over lookback period
    ema_now = ema_series[-1]
    ema_prev = ema_series[-lookback]
    
    if ema_prev == 0:
        return 0.0
    
    slope = (ema_now - ema_prev) / ema_prev
    
    # Normalize to -1 to +1 range (scale by 100 for forex)
    normalized = max(-1, min(1, slope * 100))
    
    return normalized


def calculate_atr(candles: List[Dict], period: int = 14) -> float:
    """
    Calculate Average True Range
    
    TR = max(
        high - low,
        abs(high - prev_close),
        abs(low - prev_close)
    )
    ATR = SMA(TR, period)
    """
    if len(candles) < period + 1:
        return 0.0
    
    true_ranges = []
    
    for i in range(1, len(candles)):
        high = candles[i].get('high', 0)
        low = candles[i].get('low', 0)
        prev_close = candles[i-1].get('close', 0)
        
        tr = max(
            high - low,
            abs(high - prev_close),
            abs(low - prev_close)
        )
        true_ranges.append(tr)
    
    # Use last 'period' TRs
    recent_trs = true_ranges[-period:]
    
    if not recent_trs:
        return 0.0
    
    return sum(recent_trs) / len(recent_trs)


def find_swing_points(candles: List[Dict], lookback: int = 2) -> Tuple[List[SwingPoint], List[SwingPoint]]:
    """
    Find swing highs and lows using pivot detection
    
    A swing high requires:
    - High > high of 'lookback' candles before AND after
    
    A swing low requires:
    - Low < low of 'lookback' candles before AND after
    
    Args:
        candles: List of OHLC candles
        lookback: Number of candles to look left and right (default 2)
    
    Returns:
        (swing_highs, swing_lows)
    """
    swing_highs = []
    swing_lows = []
    
    if len(candles) < (lookback * 2 + 1):
        return swing_highs, swing_lows
    
    for i in range(lookback, len(candles) - lookback):
        candle = candles[i]
        high = candle.get('high', 0)
        low = candle.get('low', 0)
        time = candle.get('datetime', '')
        
        # Check for swing high
        is_swing_high = True
        for j in range(1, lookback + 1):
            left_high = candles[i - j].get('high', 0)
            right_high = candles[i + j].get('high', 0)
            if high <= left_high or high <= right_high:
                is_swing_high = False
                break
        
        if is_swing_high:
            swing_highs.append(SwingPoint(price=high, index=i, candle_time=time))
        
        # Check for swing low
        is_swing_low = True
        for j in range(1, lookback + 1):
            left_low = candles[i - j].get('low', 0)
            right_low = candles[i + j].get('low', 0)
            if low >= left_low or low >= right_low:
                is_swing_low = False
                break
        
        if is_swing_low:
            swing_lows.append(SwingPoint(price=low, index=i, candle_time=time))
    
    return swing_highs, swing_lows


def get_recent_swing_highs(candles: List[Dict], count: int = 3, lookback: int = 2) -> List[SwingPoint]:
    """Get last N swing highs"""
    highs, _ = find_swing_points(candles, lookback)
    return highs[-count:] if len(highs) >= count else highs


def get_recent_swing_lows(candles: List[Dict], count: int = 3, lookback: int = 2) -> List[SwingPoint]:
    """Get last N swing lows"""
    _, lows = find_swing_points(candles, lookback)
    return lows[-count:] if len(lows) >= count else lows


def calculate_fibonacci_levels(swing_high: float, swing_low: float) -> Dict[str, float]:
    """
    Calculate Fibonacci retracement levels
    
    Returns dict with levels: 0.0, 0.236, 0.382, 0.5, 0.618, 0.786, 1.0
    """
    diff = swing_high - swing_low
    
    return {
        '0.0': swing_low,
        '0.236': swing_low + diff * 0.236,
        '0.382': swing_low + diff * 0.382,
        '0.5': swing_low + diff * 0.5,
        '0.618': swing_low + diff * 0.618,
        '0.786': swing_low + diff * 0.786,
        '1.0': swing_high
    }


def get_pullback_depth(current_price: float, swing_high: float, swing_low: float, direction: str) -> float:
    """
    Calculate pullback depth as percentage of the impulse leg
    
    BUY: measures how far price has pulled back from swing_high toward swing_low
    SELL: measures how far price has pushed up from swing_low toward swing_high
    
    Returns: 0.0 to 1.0+ (can exceed 1.0 if price broke the range)
    """
    leg_size = swing_high - swing_low
    
    if leg_size <= 0:
        return 0.0
    
    if direction == "BUY":
        # For BUY: pullback from high
        pullback = swing_high - current_price
        depth = pullback / leg_size
    else:
        # For SELL: pullback from low (bounce up)
        pullback = current_price - swing_low
        depth = pullback / leg_size
    
    return depth


def get_technical_context(candles: List[Dict]) -> TechnicalContext:
    """
    Build complete technical context for a timeframe
    """
    if len(candles) < 50:
        return TechnicalContext(
            ema20=0, ema50=0, ema20_slope=0, atr14=0,
            swing_highs=[], swing_lows=[],
            current_price=candles[-1].get('close', 0) if candles else 0
        )
    
    ema20 = calculate_ema(candles, 20)
    ema50 = calculate_ema(candles, 50)
    ema20_slope = calculate_ema_slope(candles, 20, lookback=5)
    atr14 = calculate_atr(candles, 14)
    swing_highs, swing_lows = find_swing_points(candles, lookback=2)
    current_price = candles[-1].get('close', 0)
    
    return TechnicalContext(
        ema20=ema20,
        ema50=ema50,
        ema20_slope=ema20_slope,
        atr14=atr14,
        swing_highs=swing_highs[-5:],  # Keep last 5
        swing_lows=swing_lows[-5:],    # Keep last 5
        current_price=current_price
    )


def is_bullish_candle(candle: Dict) -> bool:
    """Check if candle is bullish (close > open)"""
    return candle.get('close', 0) > candle.get('open', 0)


def is_bearish_candle(candle: Dict) -> bool:
    """Check if candle is bearish (close < open)"""
    return candle.get('close', 0) < candle.get('open', 0)


def get_candle_body(candle: Dict) -> float:
    """Get absolute body size"""
    return abs(candle.get('close', 0) - candle.get('open', 0))


def get_upper_wick(candle: Dict) -> float:
    """Get upper wick size"""
    high = candle.get('high', 0)
    body_top = max(candle.get('open', 0), candle.get('close', 0))
    return high - body_top


def get_lower_wick(candle: Dict) -> float:
    """Get lower wick size"""
    low = candle.get('low', 0)
    body_bottom = min(candle.get('open', 0), candle.get('close', 0))
    return body_bottom - low


def get_candle_range(candle: Dict) -> float:
    """Get total candle range (high - low)"""
    return candle.get('high', 0) - candle.get('low', 0)


def is_rejection_candle(candle: Dict, direction: str, min_wick_ratio: float = 0.35) -> bool:
    """
    Check if candle shows rejection
    
    SELL rejection: upper wick >= min_wick_ratio of total range
    BUY rejection: lower wick >= min_wick_ratio of total range
    """
    candle_range = get_candle_range(candle)
    
    if candle_range <= 0:
        return False
    
    if direction == "SELL":
        upper_wick = get_upper_wick(candle)
        return (upper_wick / candle_range) >= min_wick_ratio
    else:
        lower_wick = get_lower_wick(candle)
        return (lower_wick / candle_range) >= min_wick_ratio


def get_close_position_in_range(candle: Dict) -> float:
    """
    Get where the close is within the candle range
    
    Returns 0.0 (at low) to 1.0 (at high)
    """
    candle_range = get_candle_range(candle)
    
    if candle_range <= 0:
        return 0.5
    
    close = candle.get('close', 0)
    low = candle.get('low', 0)
    
    return (close - low) / candle_range
