"""
Market Structure Engine - Detects MSB, Displacement, and Pullback sequences
==========================================================================

CRITICAL RULE: A signal can ONLY be generated if this sequence occurs:
1. Market Structure Break (MSB) - Price breaks recent swing high/low
2. Displacement - Break happens with strong impulsive move
3. Controlled Pullback - Price retraces to a key technical zone
4. M5 Trigger - Only after pullback is complete

If any step is missing, NO SIGNAL should be generated.
"""

import logging
from typing import List, Optional, Dict, Tuple
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum

from models import Asset

logger = logging.getLogger(__name__)


class StructureType(Enum):
    """Type of market structure"""
    BULLISH_MSB = "bullish_msb"  # Break of swing high
    BEARISH_MSB = "bearish_msb"  # Break of swing low
    NO_BREAK = "no_break"


class DisplacementType(Enum):
    """Type of displacement move"""
    STRONG_BULLISH = "strong_bullish"
    MODERATE_BULLISH = "moderate_bullish"
    STRONG_BEARISH = "strong_bearish"
    MODERATE_BEARISH = "moderate_bearish"
    WEAK = "weak"
    NONE = "none"


class PullbackZoneType(Enum):
    """Type of pullback zone"""
    PREVIOUS_STRUCTURE = "previous_structure"
    SUPPLY_DEMAND = "supply_demand"
    FAIR_VALUE_GAP = "fair_value_gap"
    LIQUIDITY_SWEEP = "liquidity_sweep"
    FIBONACCI = "fibonacci"
    NONE = "none"


@dataclass
class SwingPoint:
    """A swing high or swing low point"""
    index: int
    price: float
    is_high: bool
    strength: int  # How many candles confirm this swing
    timestamp: Optional[datetime] = None


@dataclass
class StructureBreak:
    """A detected market structure break"""
    type: StructureType
    break_price: float
    break_index: int
    broken_swing: SwingPoint
    displacement_strength: float  # 0-100
    displacement_type: DisplacementType
    is_valid: bool = False
    timestamp: datetime = field(default_factory=datetime.utcnow)


@dataclass
class PullbackZone:
    """A valid pullback/retest zone"""
    zone_type: PullbackZoneType
    zone_high: float
    zone_low: float
    strength: float  # 0-100 how strong is this zone
    touches: int = 0  # How many times price has touched this zone


@dataclass
class PullbackValidation:
    """Result of pullback validation"""
    is_valid: bool
    zone: Optional[PullbackZone]
    pullback_depth: float  # How deep into the zone price pulled back
    pullback_type: str  # "shallow", "optimal", "deep"
    reason: str


@dataclass
class MSBSequence:
    """Complete MSB -> Displacement -> Pullback sequence"""
    structure_break: Optional[StructureBreak]
    pullback_zone: Optional[PullbackZone]
    pullback_validation: Optional[PullbackValidation]
    
    is_complete: bool = False
    is_ready_for_trigger: bool = False
    direction: str = "NONE"  # "LONG", "SHORT", "NONE"
    sequence_score: float = 0.0  # 0-100
    rejection_reason: Optional[str] = None
    
    def get_summary(self) -> str:
        """Get human-readable summary"""
        if not self.is_complete:
            return f"Incomplete sequence: {self.rejection_reason}"
        return (f"{self.direction} sequence ready | "
                f"MSB: {self.structure_break.type.value} | "
                f"Displacement: {self.structure_break.displacement_type.value} | "
                f"Pullback: {self.pullback_zone.zone_type.value}")


class MarketStructureEngine:
    """
    Engine for detecting and validating MSB -> Displacement -> Pullback sequences
    
    CRITICAL: This engine acts as a GATEKEEPER. No signal can be generated
    without a valid, complete sequence.
    """
    
    def __init__(self):
        # Configuration
        self.swing_lookback = 5  # Candles to confirm swing
        self.min_displacement_atr_multiplier = 1.5  # Min displacement = 1.5x ATR
        self.strong_displacement_atr_multiplier = 2.5  # Strong = 2.5x ATR
        self.pullback_min_depth = 0.382  # Minimum 38.2% retracement
        self.pullback_max_depth = 0.786  # Maximum 78.6% retracement
        self.fvg_min_size_atr = 0.3  # FVG must be at least 0.3x ATR
        
        # Cache for recent analysis
        self.last_analysis: Dict[Asset, MSBSequence] = {}
    
    def analyze_sequence(self, asset: Asset, candles: List[dict]) -> MSBSequence:
        """
        Analyze candles for complete MSB -> Displacement -> Pullback sequence
        
        Args:
            asset: The asset being analyzed
            candles: M5 candle data (at least 100 candles recommended)
        
        Returns:
            MSBSequence with validation results
        """
        if len(candles) < 50:
            return MSBSequence(
                structure_break=None,
                pullback_zone=None,
                pullback_validation=None,
                rejection_reason="Insufficient candle data"
            )
        
        # Step 1: Find swing points
        swings = self._find_swing_points(candles)
        
        if len(swings) < 4:
            return MSBSequence(
                structure_break=None,
                pullback_zone=None,
                pullback_validation=None,
                rejection_reason="Insufficient swing points"
            )
        
        # Step 2: Detect Market Structure Break
        structure_break = self._detect_structure_break(candles, swings)
        
        if not structure_break or structure_break.type == StructureType.NO_BREAK:
            return MSBSequence(
                structure_break=structure_break,
                pullback_zone=None,
                pullback_validation=None,
                rejection_reason="No market structure break detected"
            )
        
        # Step 3: Validate Displacement
        if structure_break.displacement_type in [DisplacementType.WEAK, DisplacementType.NONE]:
            return MSBSequence(
                structure_break=structure_break,
                pullback_zone=None,
                pullback_validation=None,
                rejection_reason=f"Weak displacement ({structure_break.displacement_strength:.0f}%) - no impulsive break"
            )
        
        # Step 4: Find valid pullback zones
        pullback_zones = self._find_pullback_zones(candles, structure_break, swings)
        
        if not pullback_zones:
            return MSBSequence(
                structure_break=structure_break,
                pullback_zone=None,
                pullback_validation=None,
                rejection_reason="No valid pullback zones identified"
            )
        
        # Step 5: Validate pullback into zone
        best_zone = pullback_zones[0]  # Already sorted by strength
        pullback_validation = self._validate_pullback(candles, structure_break, best_zone)
        
        if not pullback_validation.is_valid:
            return MSBSequence(
                structure_break=structure_break,
                pullback_zone=best_zone,
                pullback_validation=pullback_validation,
                rejection_reason=pullback_validation.reason
            )
        
        # Step 6: Determine if ready for M5 trigger
        is_ready = self._check_trigger_ready(candles, structure_break, pullback_validation)
        
        # Calculate sequence score
        sequence_score = self._calculate_sequence_score(
            structure_break, best_zone, pullback_validation
        )
        
        # Determine direction
        direction = "LONG" if structure_break.type == StructureType.BULLISH_MSB else "SHORT"
        
        result = MSBSequence(
            structure_break=structure_break,
            pullback_zone=best_zone,
            pullback_validation=pullback_validation,
            is_complete=True,
            is_ready_for_trigger=is_ready,
            direction=direction,
            sequence_score=sequence_score
        )
        
        # Cache result
        self.last_analysis[asset] = result
        
        # Log the analysis
        logger.info(f"📐 MSB Sequence for {asset.value}:")
        logger.info(f"   Structure Break: {structure_break.type.value}")
        logger.info(f"   Displacement: {structure_break.displacement_type.value} ({structure_break.displacement_strength:.0f}%)")
        logger.info(f"   Pullback Zone: {best_zone.zone_type.value}")
        logger.info(f"   Pullback Depth: {pullback_validation.pullback_type} ({pullback_validation.pullback_depth:.1%})")
        logger.info(f"   Ready for Trigger: {is_ready}")
        logger.info(f"   Sequence Score: {sequence_score:.0f}/100")
        
        return result
    
    def _find_swing_points(self, candles: List[dict]) -> List[SwingPoint]:
        """Find swing highs and lows in the candle data"""
        swings = []
        lookback = self.swing_lookback
        
        highs = [c.get('high', c.get('close', 0)) for c in candles]
        lows = [c.get('low', c.get('close', 0)) for c in candles]
        
        for i in range(lookback, len(candles) - lookback):
            # Check for swing high
            is_swing_high = True
            for j in range(1, lookback + 1):
                if highs[i] <= highs[i - j] or highs[i] <= highs[i + j]:
                    is_swing_high = False
                    break
            
            if is_swing_high:
                # Calculate strength (how many candles confirm)
                strength = 0
                for j in range(1, min(10, len(candles) - i)):
                    if highs[i + j] < highs[i]:
                        strength += 1
                    else:
                        break
                
                swings.append(SwingPoint(
                    index=i,
                    price=highs[i],
                    is_high=True,
                    strength=max(strength, lookback)
                ))
            
            # Check for swing low
            is_swing_low = True
            for j in range(1, lookback + 1):
                if lows[i] >= lows[i - j] or lows[i] >= lows[i + j]:
                    is_swing_low = False
                    break
            
            if is_swing_low:
                strength = 0
                for j in range(1, min(10, len(candles) - i)):
                    if lows[i + j] > lows[i]:
                        strength += 1
                    else:
                        break
                
                swings.append(SwingPoint(
                    index=i,
                    price=lows[i],
                    is_high=False,
                    strength=max(strength, lookback)
                ))
        
        # Sort by index
        swings.sort(key=lambda x: x.index)
        return swings
    
    def _detect_structure_break(self, candles: List[dict], 
                                 swings: List[SwingPoint]) -> Optional[StructureBreak]:
        """Detect if market structure has been broken"""
        if len(swings) < 2:
            return None
        
        # Calculate ATR for displacement measurement
        atr = self._calculate_atr(candles)
        
        # Get recent swings
        recent_swing_highs = [s for s in swings[-20:] if s.is_high]
        recent_swing_lows = [s for s in swings[-20:] if not s.is_high]
        
        current_price = candles[-1].get('close', 0)
        
        # Check for bullish MSB (break of swing high)
        for swing in reversed(recent_swing_highs[-5:]):
            if current_price > swing.price:
                # Found a break - measure displacement
                break_candles = candles[swing.index:]
                displacement = self._measure_displacement(break_candles, swing.price, True, atr)
                
                if displacement['strength'] > 30:  # Minimum threshold
                    return StructureBreak(
                        type=StructureType.BULLISH_MSB,
                        break_price=swing.price,
                        break_index=swing.index,
                        broken_swing=swing,
                        displacement_strength=displacement['strength'],
                        displacement_type=displacement['type'],
                        is_valid=displacement['strength'] >= 50
                    )
        
        # Check for bearish MSB (break of swing low)
        for swing in reversed(recent_swing_lows[-5:]):
            if current_price < swing.price:
                break_candles = candles[swing.index:]
                displacement = self._measure_displacement(break_candles, swing.price, False, atr)
                
                if displacement['strength'] > 30:
                    return StructureBreak(
                        type=StructureType.BEARISH_MSB,
                        break_price=swing.price,
                        break_index=swing.index,
                        broken_swing=swing,
                        displacement_strength=displacement['strength'],
                        displacement_type=displacement['type'],
                        is_valid=displacement['strength'] >= 50
                    )
        
        return StructureBreak(
            type=StructureType.NO_BREAK,
            break_price=0,
            break_index=0,
            broken_swing=swings[-1],
            displacement_strength=0,
            displacement_type=DisplacementType.NONE,
            is_valid=False
        )
    
    def _measure_displacement(self, candles: List[dict], break_level: float,
                               is_bullish: bool, atr: float) -> dict:
        """Measure the strength and type of displacement"""
        if len(candles) < 2 or atr == 0:
            return {'strength': 0, 'type': DisplacementType.NONE}
        
        # Find the impulse candles that broke the level
        max_displacement = 0
        impulse_candles = 0
        consecutive_impulse = 0
        
        for i, candle in enumerate(candles):
            if is_bullish:
                if candle.get('close', 0) > candle.get('open', 0):  # Bullish candle
                    body_size = candle.get('close', 0) - candle.get('open', 0)
                    if body_size > atr * 0.5:  # Significant body
                        impulse_candles += 1
                        consecutive_impulse += 1
                        displacement = candle.get('high', 0) - break_level
                        max_displacement = max(max_displacement, displacement)
                    else:
                        consecutive_impulse = 0
                else:
                    consecutive_impulse = 0
            else:
                if candle.get('close', 0) < candle.get('open', 0):  # Bearish candle
                    body_size = candle.get('open', 0) - candle.get('close', 0)
                    if body_size > atr * 0.5:
                        impulse_candles += 1
                        consecutive_impulse += 1
                        displacement = break_level - candle.get('low', 0)
                        max_displacement = max(max_displacement, displacement)
                    else:
                        consecutive_impulse = 0
                else:
                    consecutive_impulse = 0
        
        # Calculate strength (0-100)
        displacement_in_atr = max_displacement / atr if atr > 0 else 0
        
        if displacement_in_atr >= self.strong_displacement_atr_multiplier:
            strength = min(100, 70 + displacement_in_atr * 10)
            disp_type = DisplacementType.STRONG_BULLISH if is_bullish else DisplacementType.STRONG_BEARISH
        elif displacement_in_atr >= self.min_displacement_atr_multiplier:
            strength = min(70, 50 + displacement_in_atr * 10)
            disp_type = DisplacementType.MODERATE_BULLISH if is_bullish else DisplacementType.MODERATE_BEARISH
        else:
            strength = min(50, displacement_in_atr * 30)
            disp_type = DisplacementType.WEAK
        
        # Bonus for consecutive impulse candles
        if consecutive_impulse >= 3:
            strength = min(100, strength + 15)
        elif consecutive_impulse >= 2:
            strength = min(100, strength + 8)
        
        return {'strength': strength, 'type': disp_type}
    
    def _find_pullback_zones(self, candles: List[dict], 
                              structure_break: StructureBreak,
                              swings: List[SwingPoint]) -> List[PullbackZone]:
        """Find valid pullback zones after structure break"""
        zones = []
        atr = self._calculate_atr(candles)
        
        # 1. Previous structure zone (broken level becomes support/resistance)
        broken_price = structure_break.break_price
        zone_buffer = atr * 0.3
        
        zones.append(PullbackZone(
            zone_type=PullbackZoneType.PREVIOUS_STRUCTURE,
            zone_high=broken_price + zone_buffer,
            zone_low=broken_price - zone_buffer,
            strength=80  # Strong zone
        ))
        
        # 2. Supply/Demand zones from recent swings
        for swing in swings[-10:]:
            if structure_break.type == StructureType.BULLISH_MSB and not swing.is_high:
                # For bullish, look for demand zones (swing lows)
                zones.append(PullbackZone(
                    zone_type=PullbackZoneType.SUPPLY_DEMAND,
                    zone_high=swing.price + atr * 0.2,
                    zone_low=swing.price - atr * 0.2,
                    strength=60 + swing.strength * 2
                ))
            elif structure_break.type == StructureType.BEARISH_MSB and swing.is_high:
                # For bearish, look for supply zones (swing highs)
                zones.append(PullbackZone(
                    zone_type=PullbackZoneType.SUPPLY_DEMAND,
                    zone_high=swing.price + atr * 0.2,
                    zone_low=swing.price - atr * 0.2,
                    strength=60 + swing.strength * 2
                ))
        
        # 3. Fair Value Gaps (FVG / Imbalances)
        fvg_zones = self._find_fvg_zones(candles, structure_break.break_index, atr)
        zones.extend(fvg_zones)
        
        # 4. Fibonacci zones (50% and 61.8% retracement)
        fib_zones = self._find_fibonacci_zones(candles, structure_break, atr)
        zones.extend(fib_zones)
        
        # Sort by strength
        zones.sort(key=lambda x: x.strength, reverse=True)
        
        return zones
    
    def _find_fvg_zones(self, candles: List[dict], break_index: int, 
                         atr: float) -> List[PullbackZone]:
        """Find Fair Value Gaps (imbalances) in the move"""
        fvg_zones = []
        
        # Look at candles around the break
        start_idx = max(0, break_index - 5)
        end_idx = min(len(candles), break_index + 20)
        
        for i in range(start_idx + 2, end_idx):
            # FVG is when candle 3's low > candle 1's high (bullish)
            # or candle 3's high < candle 1's low (bearish)
            
            c1 = candles[i - 2]
            c3 = candles[i]
            
            # Bullish FVG
            if c3.get('low', 0) > c1.get('high', 0):
                gap_size = c3.get('low', 0) - c1.get('high', 0)
                if gap_size >= atr * self.fvg_min_size_atr:
                    fvg_zones.append(PullbackZone(
                        zone_type=PullbackZoneType.FAIR_VALUE_GAP,
                        zone_high=c3.get('low', 0),
                        zone_low=c1.get('high', 0),
                        strength=70 + min(20, gap_size / atr * 10)
                    ))
            
            # Bearish FVG
            if c3.get('high', 0) < c1.get('low', 0):
                gap_size = c1.get('low', 0) - c3.get('high', 0)
                if gap_size >= atr * self.fvg_min_size_atr:
                    fvg_zones.append(PullbackZone(
                        zone_type=PullbackZoneType.FAIR_VALUE_GAP,
                        zone_high=c1.get('low', 0),
                        zone_low=c3.get('high', 0),
                        strength=70 + min(20, gap_size / atr * 10)
                    ))
        
        return fvg_zones
    
    def _find_fibonacci_zones(self, candles: List[dict],
                               structure_break: StructureBreak,
                               atr: float) -> List[PullbackZone]:
        """Find Fibonacci retracement zones"""
        zones = []
        
        # Find the impulse move high and low
        break_idx = structure_break.break_index
        recent_candles = candles[max(0, break_idx - 20):min(len(candles), break_idx + 10)]
        
        if not recent_candles:
            return zones
        
        highs = [c.get('high', 0) for c in recent_candles]
        lows = [c.get('low', 0) for c in recent_candles]
        
        impulse_high = max(highs)
        impulse_low = min(lows)
        impulse_range = impulse_high - impulse_low
        
        if impulse_range < atr:
            return zones
        
        # Calculate Fib levels
        fib_levels = [0.382, 0.5, 0.618, 0.705]
        
        for fib in fib_levels:
            if structure_break.type == StructureType.BULLISH_MSB:
                # Pullback from high
                level = impulse_high - (impulse_range * fib)
            else:
                # Pullback from low
                level = impulse_low + (impulse_range * fib)
            
            zones.append(PullbackZone(
                zone_type=PullbackZoneType.FIBONACCI,
                zone_high=level + atr * 0.15,
                zone_low=level - atr * 0.15,
                strength=65 if fib in [0.5, 0.618] else 55
            ))
        
        return zones
    
    def _validate_pullback(self, candles: List[dict],
                            structure_break: StructureBreak,
                            zone: PullbackZone) -> PullbackValidation:
        """Validate that price has pulled back into the zone correctly"""
        
        # Check recent candles for pullback
        recent = candles[-20:]
        current_price = candles[-1].get('close', 0)
        
        # For bullish MSB, we need price to pull back DOWN into zone
        # For bearish MSB, we need price to pull back UP into zone
        
        entered_zone = False
        deepest_point = current_price
        candles_in_zone = 0
        
        for candle in recent:
            low = candle.get('low', 0)
            high = candle.get('high', 0)
            close = candle.get('close', 0)
            
            # Check if candle touched the zone
            if low <= zone.zone_high and high >= zone.zone_low:
                entered_zone = True
                candles_in_zone += 1
                
                if structure_break.type == StructureType.BULLISH_MSB:
                    deepest_point = min(deepest_point, low)
                else:
                    deepest_point = max(deepest_point, high)
        
        if not entered_zone:
            return PullbackValidation(
                is_valid=False,
                zone=zone,
                pullback_depth=0,
                pullback_type="none",
                reason="Price has not pulled back into the zone yet"
            )
        
        # Calculate pullback depth
        if structure_break.type == StructureType.BULLISH_MSB:
            impulse_high = max(c.get('high', 0) for c in candles[structure_break.break_index:])
            pullback_depth = (impulse_high - deepest_point) / (impulse_high - structure_break.break_price) if impulse_high > structure_break.break_price else 0
        else:
            impulse_low = min(c.get('low', 0) for c in candles[structure_break.break_index:])
            pullback_depth = (deepest_point - impulse_low) / (structure_break.break_price - impulse_low) if structure_break.break_price > impulse_low else 0
        
        # Validate depth
        if pullback_depth < self.pullback_min_depth:
            return PullbackValidation(
                is_valid=False,
                zone=zone,
                pullback_depth=pullback_depth,
                pullback_type="shallow",
                reason=f"Pullback too shallow ({pullback_depth:.1%}) - needs at least {self.pullback_min_depth:.1%}"
            )
        
        if pullback_depth > self.pullback_max_depth:
            return PullbackValidation(
                is_valid=False,
                zone=zone,
                pullback_depth=pullback_depth,
                pullback_type="deep",
                reason=f"Pullback too deep ({pullback_depth:.1%}) - structure may be broken"
            )
        
        # Determine pullback type
        if 0.5 <= pullback_depth <= 0.618:
            pullback_type = "optimal"
        elif pullback_depth < 0.5:
            pullback_type = "shallow"
        else:
            pullback_type = "deep"
        
        return PullbackValidation(
            is_valid=True,
            zone=zone,
            pullback_depth=pullback_depth,
            pullback_type=pullback_type,
            reason=f"Valid {pullback_type} pullback into {zone.zone_type.value}"
        )
    
    def _check_trigger_ready(self, candles: List[dict],
                              structure_break: StructureBreak,
                              pullback: PullbackValidation) -> bool:
        """Check if price is ready for M5 trigger after pullback"""
        if not pullback.is_valid:
            return False
        
        # Get last few candles
        recent = candles[-5:]
        current = candles[-1]
        
        current_close = current.get('close', 0)
        current_open = current.get('open', 0)
        
        zone = pullback.zone
        
        if structure_break.type == StructureType.BULLISH_MSB:
            # For bullish, we need price to start moving up from zone
            # Current candle should be bullish and above zone low
            is_bullish_candle = current_close > current_open
            is_above_zone = current_close > zone.zone_low
            is_reclaiming = current_close > (zone.zone_low + zone.zone_high) / 2
            
            return is_bullish_candle and is_above_zone and is_reclaiming
        
        else:  # Bearish MSB
            # For bearish, we need price to start moving down from zone
            is_bearish_candle = current_close < current_open
            is_below_zone = current_close < zone.zone_high
            is_rejecting = current_close < (zone.zone_low + zone.zone_high) / 2
            
            return is_bearish_candle and is_below_zone and is_rejecting
    
    def _calculate_sequence_score(self, structure_break: StructureBreak,
                                   zone: PullbackZone,
                                   pullback: PullbackValidation) -> float:
        """Calculate overall sequence quality score"""
        score = 0
        
        # Displacement strength (0-40 points)
        score += structure_break.displacement_strength * 0.4
        
        # Zone strength (0-30 points)
        score += zone.strength * 0.3
        
        # Pullback quality (0-30 points)
        if pullback.pullback_type == "optimal":
            score += 30
        elif pullback.pullback_type == "shallow":
            score += 20
        else:
            score += 15
        
        return min(100, score)
    
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
    
    def is_sequence_valid(self, asset: Asset) -> Tuple[bool, str]:
        """Quick check if asset has a valid sequence ready"""
        if asset not in self.last_analysis:
            return False, "No analysis available"
        
        seq = self.last_analysis[asset]
        
        if not seq.is_complete:
            return False, seq.rejection_reason or "Incomplete sequence"
        
        if not seq.is_ready_for_trigger:
            return False, "Waiting for M5 trigger confirmation"
        
        return True, f"Valid {seq.direction} sequence (score: {seq.sequence_score:.0f})"


# Global instance
market_structure_engine = MarketStructureEngine()
