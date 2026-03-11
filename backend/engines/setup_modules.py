"""
Setup Detection Modules - Multiple pattern recognition strategies
"""
import logging
from typing import List, Optional, Dict, Any
from dataclasses import dataclass
from datetime import datetime
from abc import ABC, abstractmethod
from enum import Enum

from models import Asset, SignalType
from services.scanner_config import SetupType

logger = logging.getLogger(__name__)


@dataclass
class SetupCandidate:
    """A detected setup candidate"""
    setup_type: SetupType
    asset: Asset
    direction: str  # "LONG" or "SHORT"
    entry_price: float
    stop_loss: float
    take_profit_1: float
    take_profit_2: Optional[float] = None
    
    # Quality metrics
    setup_quality_score: float = 0.0  # 0-100
    structure_score: float = 0.0       # 0-100
    momentum_score: float = 0.0        # 0-100
    
    # Metadata
    detected_at: datetime = None
    invalidation_price: float = 0.0
    reason: str = ""
    details: Dict[str, Any] = None
    
    def __post_init__(self):
        if self.detected_at is None:
            self.detected_at = datetime.utcnow()
        if self.details is None:
            self.details = {}


class BaseSetupModule(ABC):
    """Base class for setup detection modules"""
    
    def __init__(self):
        self.name = "BaseModule"
        self.setup_type = SetupType.TREND_CONTINUATION
        self.enabled = True
    
    @abstractmethod
    def detect(self, asset: Asset, candles: List[dict], 
               bias_direction: str) -> Optional[SetupCandidate]:
        """
        Detect setup in the given candles
        
        Args:
            asset: The asset being analyzed
            candles: Recent candle data (M5 timeframe)
            bias_direction: "LONG", "SHORT", or "NONE" from HTF bias
        
        Returns:
            SetupCandidate if a valid setup is found, None otherwise
        """
        pass
    
    def _calculate_atr(self, candles: List[dict], period: int = 14) -> float:
        """Calculate Average True Range"""
        if len(candles) < period + 1:
            return 0
        
        trs = []
        for i in range(1, min(period + 1, len(candles))):
            high = candles[-i].get('high', candles[-i].get('close', 0))
            low = candles[-i].get('low', candles[-i].get('close', 0))
            prev_close = candles[-(i+1)].get('close', 0)
            
            tr = max(
                high - low,
                abs(high - prev_close),
                abs(low - prev_close)
            )
            trs.append(tr)
        
        return sum(trs) / len(trs) if trs else 0


class TrendContinuationModule(BaseSetupModule):
    """
    Detects trend continuation pullback setups
    
    Logic:
    1. Identify strong trend (using structure)
    2. Wait for pullback to key level (MA or structure)
    3. Look for reversal candle pattern
    4. Entry on confirmation
    """
    
    def __init__(self):
        super().__init__()
        self.name = "TrendContinuation"
        self.setup_type = SetupType.TREND_CONTINUATION
    
    def detect(self, asset: Asset, candles: List[dict], 
               bias_direction: str) -> Optional[SetupCandidate]:
        
        if len(candles) < 30 or bias_direction == "NONE":
            return None
        
        recent = candles[-30:]
        closes = [c.get('close', 0) for c in recent]
        highs = [c.get('high', c.get('close', 0)) for c in recent]
        lows = [c.get('low', c.get('close', 0)) for c in recent]
        
        # Calculate MAs
        ma_fast = sum(closes[-10:]) / 10
        ma_slow = sum(closes[-20:]) / 20
        current_price = closes[-1]
        atr = self._calculate_atr(candles)
        
        # LONG setup: price pulled back to MA and bouncing
        if bias_direction == "LONG":
            # Check if in uptrend
            if ma_fast <= ma_slow:
                return None
            
            # Check for pullback (price near or below fast MA)
            pullback_zone = current_price <= ma_fast * 1.002
            
            # Check for bounce (current candle bullish)
            last_candle_bullish = closes[-1] > candles[-1].get('open', closes[-1])
            
            # Check structure (higher lows)
            recent_lows = lows[-10:]
            higher_lows = all(recent_lows[i] >= recent_lows[i-2] * 0.998 for i in range(2, len(recent_lows)))
            
            if pullback_zone and last_candle_bullish and higher_lows:
                entry = current_price
                stop_loss = min(lows[-5:]) - atr * 0.5
                risk = entry - stop_loss
                
                return SetupCandidate(
                    setup_type=self.setup_type,
                    asset=asset,
                    direction="LONG",
                    entry_price=entry,
                    stop_loss=stop_loss,
                    take_profit_1=entry + risk * 1.5,
                    take_profit_2=entry + risk * 2.5,
                    setup_quality_score=75,
                    structure_score=70 if higher_lows else 50,
                    momentum_score=70,
                    invalidation_price=stop_loss,
                    reason="Trend continuation pullback to MA support",
                    details={
                        "ma_fast": ma_fast,
                        "ma_slow": ma_slow,
                        "atr": atr,
                        "pullback_depth": (ma_fast - current_price) / ma_fast * 100
                    }
                )
        
        # SHORT setup: price pulled back to MA and rejecting
        elif bias_direction == "SHORT":
            if ma_fast >= ma_slow:
                return None
            
            pullback_zone = current_price >= ma_fast * 0.998
            last_candle_bearish = closes[-1] < candles[-1].get('open', closes[-1])
            
            recent_highs = highs[-10:]
            lower_highs = all(recent_highs[i] <= recent_highs[i-2] * 1.002 for i in range(2, len(recent_highs)))
            
            if pullback_zone and last_candle_bearish and lower_highs:
                entry = current_price
                stop_loss = max(highs[-5:]) + atr * 0.5
                risk = stop_loss - entry
                
                return SetupCandidate(
                    setup_type=self.setup_type,
                    asset=asset,
                    direction="SHORT",
                    entry_price=entry,
                    stop_loss=stop_loss,
                    take_profit_1=entry - risk * 1.5,
                    take_profit_2=entry - risk * 2.5,
                    setup_quality_score=75,
                    structure_score=70 if lower_highs else 50,
                    momentum_score=70,
                    invalidation_price=stop_loss,
                    reason="Trend continuation pullback to MA resistance",
                    details={
                        "ma_fast": ma_fast,
                        "ma_slow": ma_slow,
                        "atr": atr
                    }
                )
        
        return None


class BreakoutRetestModule(BaseSetupModule):
    """
    Detects breakout and retest setups
    
    Logic:
    1. Identify key support/resistance level
    2. Wait for breakout with momentum
    3. Wait for retest of broken level
    4. Entry on confirmation of hold
    """
    
    def __init__(self):
        super().__init__()
        self.name = "BreakoutRetest"
        self.setup_type = SetupType.BREAKOUT_RETEST
    
    def detect(self, asset: Asset, candles: List[dict], 
               bias_direction: str) -> Optional[SetupCandidate]:
        
        if len(candles) < 50:
            return None
        
        recent = candles[-50:]
        closes = [c.get('close', 0) for c in recent]
        highs = [c.get('high', c.get('close', 0)) for c in recent]
        lows = [c.get('low', c.get('close', 0)) for c in recent]
        current = closes[-1]
        atr = self._calculate_atr(candles)
        
        # Find recent swing highs and lows
        swing_highs = self._find_swing_highs(highs)
        swing_lows = self._find_swing_lows(lows)
        
        if not swing_highs or not swing_lows:
            return None
        
        # Check for bullish breakout and retest
        if bias_direction in ["LONG", "NONE"]:
            # Find resistance that was broken
            for sh in swing_highs[-5:]:
                resistance_level = sh['price']
                
                # Check if price broke above and came back to retest
                if current > resistance_level * 0.998 and current < resistance_level * 1.005:
                    # Retest zone
                    last_candle_bullish = closes[-1] > candles[-1].get('open', closes[-1])
                    
                    if last_candle_bullish:
                        entry = current
                        stop_loss = resistance_level - atr
                        risk = entry - stop_loss
                        
                        return SetupCandidate(
                            setup_type=self.setup_type,
                            asset=asset,
                            direction="LONG",
                            entry_price=entry,
                            stop_loss=stop_loss,
                            take_profit_1=entry + risk * 2,
                            take_profit_2=entry + risk * 3,
                            setup_quality_score=80,
                            structure_score=75,
                            momentum_score=70,
                            invalidation_price=stop_loss,
                            reason=f"Breakout retest of resistance at {resistance_level:.5f}",
                            details={
                                "resistance_level": resistance_level,
                                "retest_depth": (resistance_level - current) / resistance_level * 100
                            }
                        )
        
        # Check for bearish breakout and retest
        if bias_direction in ["SHORT", "NONE"]:
            for sl in swing_lows[-5:]:
                support_level = sl['price']
                
                if current < support_level * 1.002 and current > support_level * 0.995:
                    last_candle_bearish = closes[-1] < candles[-1].get('open', closes[-1])
                    
                    if last_candle_bearish:
                        entry = current
                        stop_loss = support_level + atr
                        risk = stop_loss - entry
                        
                        return SetupCandidate(
                            setup_type=self.setup_type,
                            asset=asset,
                            direction="SHORT",
                            entry_price=entry,
                            stop_loss=stop_loss,
                            take_profit_1=entry - risk * 2,
                            take_profit_2=entry - risk * 3,
                            setup_quality_score=80,
                            structure_score=75,
                            momentum_score=70,
                            invalidation_price=stop_loss,
                            reason=f"Breakout retest of support at {support_level:.5f}",
                            details={
                                "support_level": support_level
                            }
                        )
        
        return None
    
    def _find_swing_highs(self, highs: List[float], lookback: int = 5) -> List[dict]:
        """Find swing high points"""
        swings = []
        for i in range(lookback, len(highs) - lookback):
            is_swing = all(highs[i] >= highs[i-j] for j in range(1, lookback + 1))
            is_swing = is_swing and all(highs[i] >= highs[i+j] for j in range(1, min(lookback + 1, len(highs) - i)))
            if is_swing:
                swings.append({'index': i, 'price': highs[i]})
        return swings
    
    def _find_swing_lows(self, lows: List[float], lookback: int = 5) -> List[dict]:
        """Find swing low points"""
        swings = []
        for i in range(lookback, len(lows) - lookback):
            is_swing = all(lows[i] <= lows[i-j] for j in range(1, lookback + 1))
            is_swing = is_swing and all(lows[i] <= lows[i+j] for j in range(1, min(lookback + 1, len(lows) - i)))
            if is_swing:
                swings.append({'index': i, 'price': lows[i]})
        return swings


class LiquiditySweepModule(BaseSetupModule):
    """
    Detects liquidity sweep / stop hunt reversal setups
    
    Logic:
    1. Identify obvious liquidity pool (equal highs/lows)
    2. Wait for sweep beyond the pool
    3. Look for rejection / reversal candle
    4. Entry on reversal confirmation
    """
    
    def __init__(self):
        super().__init__()
        self.name = "LiquiditySweep"
        self.setup_type = SetupType.LIQUIDITY_SWEEP
    
    def detect(self, asset: Asset, candles: List[dict], 
               bias_direction: str) -> Optional[SetupCandidate]:
        
        if len(candles) < 30:
            return None
        
        recent = candles[-30:]
        closes = [c.get('close', 0) for c in recent]
        highs = [c.get('high', c.get('close', 0)) for c in recent]
        lows = [c.get('low', c.get('close', 0)) for c in recent]
        current = closes[-1]
        atr = self._calculate_atr(candles)
        
        # Look for equal highs (liquidity above)
        if bias_direction in ["LONG", "NONE"]:
            equal_lows = self._find_equal_levels(lows[:-5], tolerance=atr * 0.3)
            
            for level in equal_lows:
                # Check if price swept below and reversed
                recent_low = min(lows[-3:])
                if recent_low < level and current > level:
                    # Swept and reclaimed - bullish
                    entry = current
                    stop_loss = recent_low - atr * 0.3
                    risk = entry - stop_loss
                    
                    return SetupCandidate(
                        setup_type=self.setup_type,
                        asset=asset,
                        direction="LONG",
                        entry_price=entry,
                        stop_loss=stop_loss,
                        take_profit_1=entry + risk * 2,
                        take_profit_2=entry + risk * 3,
                        setup_quality_score=85,
                        structure_score=80,
                        momentum_score=75,
                        invalidation_price=stop_loss,
                        reason=f"Liquidity sweep below {level:.5f} with reversal",
                        details={
                            "liquidity_level": level,
                            "sweep_low": recent_low,
                            "sweep_depth": (level - recent_low) / level * 100
                        }
                    )
        
        # Look for equal lows swept (liquidity below)
        if bias_direction in ["SHORT", "NONE"]:
            equal_highs = self._find_equal_levels(highs[:-5], tolerance=atr * 0.3)
            
            for level in equal_highs:
                recent_high = max(highs[-3:])
                if recent_high > level and current < level:
                    # Swept and rejected - bearish
                    entry = current
                    stop_loss = recent_high + atr * 0.3
                    risk = stop_loss - entry
                    
                    return SetupCandidate(
                        setup_type=self.setup_type,
                        asset=asset,
                        direction="SHORT",
                        entry_price=entry,
                        stop_loss=stop_loss,
                        take_profit_1=entry - risk * 2,
                        take_profit_2=entry - risk * 3,
                        setup_quality_score=85,
                        structure_score=80,
                        momentum_score=75,
                        invalidation_price=stop_loss,
                        reason=f"Liquidity sweep above {level:.5f} with rejection",
                        details={
                            "liquidity_level": level,
                            "sweep_high": recent_high
                        }
                    )
        
        return None
    
    def _find_equal_levels(self, prices: List[float], tolerance: float) -> List[float]:
        """Find clusters of equal price levels"""
        if not prices:
            return []
        
        levels = []
        used = set()
        
        for i, p1 in enumerate(prices):
            if i in used:
                continue
            
            cluster = [p1]
            for j, p2 in enumerate(prices[i+1:], i+1):
                if abs(p1 - p2) <= tolerance:
                    cluster.append(p2)
                    used.add(j)
            
            if len(cluster) >= 2:
                levels.append(sum(cluster) / len(cluster))
        
        return levels


class RangeExpansionModule(BaseSetupModule):
    """
    Detects range expansion / volatility breakout setups
    
    Logic:
    1. Identify consolidation range
    2. Wait for expansion candle breaking range
    3. Entry on first pullback after expansion
    """
    
    def __init__(self):
        super().__init__()
        self.name = "RangeExpansion"
        self.setup_type = SetupType.RANGE_EXPANSION
    
    def detect(self, asset: Asset, candles: List[dict], 
               bias_direction: str) -> Optional[SetupCandidate]:
        
        if len(candles) < 40:
            return None
        
        recent = candles[-40:]
        closes = [c.get('close', 0) for c in recent]
        highs = [c.get('high', c.get('close', 0)) for c in recent]
        lows = [c.get('low', c.get('close', 0)) for c in recent]
        atr = self._calculate_atr(candles)
        
        # Check for prior consolidation (small range)
        range_candles = 20
        range_high = max(highs[-range_candles-5:-5])
        range_low = min(lows[-range_candles-5:-5])
        range_size = range_high - range_low
        
        # Check if range was tight (less than 2x ATR)
        if range_size > atr * 3:
            return None  # Not a tight range
        
        current = closes[-1]
        current_high = highs[-1]
        current_low = lows[-1]
        
        # Bullish expansion
        if current_high > range_high and current > range_high and bias_direction in ["LONG", "NONE"]:
            entry = current
            stop_loss = range_low - atr * 0.3
            risk = entry - stop_loss
            
            return SetupCandidate(
                setup_type=self.setup_type,
                asset=asset,
                direction="LONG",
                entry_price=entry,
                stop_loss=stop_loss,
                take_profit_1=entry + range_size,
                take_profit_2=entry + range_size * 1.5,
                setup_quality_score=75,
                structure_score=70,
                momentum_score=80,
                invalidation_price=range_low,
                reason=f"Range expansion breakout above {range_high:.5f}",
                details={
                    "range_high": range_high,
                    "range_low": range_low,
                    "range_size": range_size
                }
            )
        
        # Bearish expansion
        if current_low < range_low and current < range_low and bias_direction in ["SHORT", "NONE"]:
            entry = current
            stop_loss = range_high + atr * 0.3
            risk = stop_loss - entry
            
            return SetupCandidate(
                setup_type=self.setup_type,
                asset=asset,
                direction="SHORT",
                entry_price=entry,
                stop_loss=stop_loss,
                take_profit_1=entry - range_size,
                take_profit_2=entry - range_size * 1.5,
                setup_quality_score=75,
                structure_score=70,
                momentum_score=80,
                invalidation_price=range_high,
                reason=f"Range expansion breakdown below {range_low:.5f}",
                details={
                    "range_high": range_high,
                    "range_low": range_low,
                    "range_size": range_size
                }
            )
        
        return None


class SessionBreakoutModule(BaseSetupModule):
    """
    Detects session open breakout setups
    
    Logic:
    1. Define session open range (first 30-60 mins)
    2. Wait for breakout of session range
    3. Entry on confirmed break with momentum
    """
    
    def __init__(self):
        super().__init__()
        self.name = "SessionBreakout"
        self.setup_type = SetupType.SESSION_BREAKOUT
    
    def detect(self, asset: Asset, candles: List[dict], 
               bias_direction: str) -> Optional[SetupCandidate]:
        
        if len(candles) < 20:
            return None
        
        # Use last 12 candles as "session open range" (1 hour on M5)
        session_candles = candles[-12:-1]  # Exclude current
        
        session_high = max(c.get('high', c.get('close', 0)) for c in session_candles)
        session_low = min(c.get('low', c.get('close', 0)) for c in session_candles)
        
        current = candles[-1]
        current_close = current.get('close', 0)
        current_high = current.get('high', current_close)
        current_low = current.get('low', current_close)
        
        atr = self._calculate_atr(candles)
        session_range = session_high - session_low
        
        # Only valid if session range is reasonable
        if session_range < atr * 0.5 or session_range > atr * 4:
            return None
        
        # Bullish session breakout
        if current_close > session_high and bias_direction in ["LONG", "NONE"]:
            entry = current_close
            stop_loss = session_low - atr * 0.2
            risk = entry - stop_loss
            
            return SetupCandidate(
                setup_type=self.setup_type,
                asset=asset,
                direction="LONG",
                entry_price=entry,
                stop_loss=stop_loss,
                take_profit_1=entry + session_range,
                take_profit_2=entry + session_range * 1.5,
                setup_quality_score=70,
                structure_score=65,
                momentum_score=75,
                invalidation_price=session_low,
                reason=f"Session breakout above {session_high:.5f}",
                details={
                    "session_high": session_high,
                    "session_low": session_low,
                    "session_range": session_range
                }
            )
        
        # Bearish session breakout
        if current_close < session_low and bias_direction in ["SHORT", "NONE"]:
            entry = current_close
            stop_loss = session_high + atr * 0.2
            risk = stop_loss - entry
            
            return SetupCandidate(
                setup_type=self.setup_type,
                asset=asset,
                direction="SHORT",
                entry_price=entry,
                stop_loss=stop_loss,
                take_profit_1=entry - session_range,
                take_profit_2=entry - session_range * 1.5,
                setup_quality_score=70,
                structure_score=65,
                momentum_score=75,
                invalidation_price=session_high,
                reason=f"Session breakdown below {session_low:.5f}",
                details={
                    "session_high": session_high,
                    "session_low": session_low,
                    "session_range": session_range
                }
            )
        
        return None


# Module registry
SETUP_MODULES = {
    SetupType.TREND_CONTINUATION: TrendContinuationModule(),
    SetupType.BREAKOUT_RETEST: BreakoutRetestModule(),
    SetupType.LIQUIDITY_SWEEP: LiquiditySweepModule(),
    SetupType.RANGE_EXPANSION: RangeExpansionModule(),
    SetupType.SESSION_BREAKOUT: SessionBreakoutModule(),
}
