"""
Multi-Timeframe Bias Engine - Determines directional bias from H1 -> M15 -> M5
"""
import logging
from typing import List, Optional, Dict, Tuple
from dataclasses import dataclass
from datetime import datetime
from enum import Enum

from models import Asset

logger = logging.getLogger(__name__)


class TimeframeBias(Enum):
    """Directional bias states"""
    STRONG_BULLISH = "strong_bullish"
    BULLISH = "bullish"
    WEAK_BULLISH = "weak_bullish"
    NEUTRAL = "neutral"
    WEAK_BEARISH = "weak_bearish"
    BEARISH = "bearish"
    STRONG_BEARISH = "strong_bearish"


@dataclass
class BiasAnalysis:
    """Result of bias analysis for a single timeframe"""
    timeframe: str
    bias: TimeframeBias
    trend_strength: float  # 0-100
    structure: str  # "HH_HL" / "LL_LH" / "MIXED"
    key_level: Optional[float] = None
    momentum_aligned: bool = False


@dataclass
class MultiTimeframeBias:
    """Combined bias from all timeframes"""
    h1_bias: BiasAnalysis
    m15_bias: BiasAnalysis
    m5_bias: BiasAnalysis
    
    overall_bias: TimeframeBias
    alignment_score: float  # 0-100, higher = better alignment
    trade_direction: str  # "LONG", "SHORT", "NONE"
    is_countertrend: bool = False
    analysis_timestamp: datetime = None
    
    def __post_init__(self):
        if self.analysis_timestamp is None:
            self.analysis_timestamp = datetime.utcnow()


class MultiTimeframeBiasEngine:
    """
    Determines trading bias using multi-timeframe analysis:
    - H1 = Macro bias (overall trend direction)
    - M15 = Setup context (swing structure)
    - M5 = Execution trigger (entry timing)
    
    Trading logic:
    1. Determine bullish/bearish/neutral bias from H1 + M15
    2. Only allow M5 triggers aligned with higher timeframe bias
    3. Reject or penalize countertrend setups
    """
    
    def __init__(self):
        self.last_analysis: Dict[Asset, MultiTimeframeBias] = {}
        self.analysis_cache_seconds = 60  # Cache for 1 minute
    
    def analyze_bias(self, asset: Asset, candles_h1: List[dict], 
                     candles_m15: List[dict], candles_m5: List[dict]) -> MultiTimeframeBias:
        """
        Perform multi-timeframe bias analysis
        
        Args:
            asset: The asset being analyzed
            candles_h1: H1 candle data (at least 20 candles)
            candles_m15: M15 candle data (at least 50 candles)
            candles_m5: M5 candle data (at least 100 candles)
        
        Returns:
            MultiTimeframeBias with complete analysis
        """
        logger.info(f"📊 MTF Bias Analysis for {asset.value}")
        
        # Analyze each timeframe
        h1_bias = self._analyze_timeframe(candles_h1, "H1")
        m15_bias = self._analyze_timeframe(candles_m15, "M15")
        m5_bias = self._analyze_timeframe(candles_m5, "M5")
        
        # Calculate overall bias and alignment
        overall_bias, alignment_score = self._calculate_overall_bias(h1_bias, m15_bias, m5_bias)
        
        # Determine trade direction
        trade_direction = self._determine_trade_direction(overall_bias, alignment_score)
        
        # Check if M5 is countertrend
        is_countertrend = self._is_countertrend(h1_bias, m15_bias, m5_bias)
        
        result = MultiTimeframeBias(
            h1_bias=h1_bias,
            m15_bias=m15_bias,
            m5_bias=m5_bias,
            overall_bias=overall_bias,
            alignment_score=alignment_score,
            trade_direction=trade_direction,
            is_countertrend=is_countertrend
        )
        
        # Cache result
        self.last_analysis[asset] = result
        
        # Log analysis
        logger.info(f"  H1: {h1_bias.bias.value} (strength: {h1_bias.trend_strength:.0f}%)")
        logger.info(f"  M15: {m15_bias.bias.value} (strength: {m15_bias.trend_strength:.0f}%)")
        logger.info(f"  M5: {m5_bias.bias.value} (strength: {m5_bias.trend_strength:.0f}%)")
        logger.info(f"  Overall: {overall_bias.value}, Alignment: {alignment_score:.0f}%")
        logger.info(f"  Direction: {trade_direction}, Countertrend: {is_countertrend}")
        
        return result
    
    def _analyze_timeframe(self, candles: List[dict], timeframe: str) -> BiasAnalysis:
        """Analyze a single timeframe for bias"""
        if not candles or len(candles) < 10:
            return BiasAnalysis(
                timeframe=timeframe,
                bias=TimeframeBias.NEUTRAL,
                trend_strength=0,
                structure="INSUFFICIENT_DATA"
            )
        
        # Get recent candles for analysis
        recent = candles[-20:] if len(candles) >= 20 else candles
        
        # Calculate structure (HH/HL vs LL/LH)
        highs = [c.get('high', c.get('close', 0)) for c in recent]
        lows = [c.get('low', c.get('close', 0)) for c in recent]
        closes = [c.get('close', 0) for c in recent]
        
        # Find swing points
        structure, hh_count, ll_count = self._identify_structure(highs, lows)
        
        # Calculate trend strength using multiple factors
        trend_strength = self._calculate_trend_strength(closes, highs, lows, hh_count, ll_count)
        
        # Determine bias
        bias = self._determine_bias(structure, trend_strength, closes)
        
        # Check momentum alignment (using simple MA comparison)
        momentum_aligned = self._check_momentum(closes)
        
        # Find key level (most recent significant high/low)
        key_level = self._find_key_level(highs, lows, bias)
        
        return BiasAnalysis(
            timeframe=timeframe,
            bias=bias,
            trend_strength=trend_strength,
            structure=structure,
            key_level=key_level,
            momentum_aligned=momentum_aligned
        )
    
    def _identify_structure(self, highs: List[float], lows: List[float]) -> Tuple[str, int, int]:
        """Identify market structure (HH/HL or LL/LH)"""
        if len(highs) < 5:
            return "INSUFFICIENT", 0, 0
        
        # Count higher highs and lower lows
        hh_count = 0
        ll_count = 0
        hl_count = 0
        lh_count = 0
        
        for i in range(2, len(highs)):
            if highs[i] > highs[i-2]:
                hh_count += 1
            if highs[i] < highs[i-2]:
                lh_count += 1
            if lows[i] > lows[i-2]:
                hl_count += 1
            if lows[i] < lows[i-2]:
                ll_count += 1
        
        # Determine structure
        bullish_score = hh_count + hl_count
        bearish_score = ll_count + lh_count
        
        if bullish_score > bearish_score * 1.3:
            return "HH_HL", hh_count, ll_count
        elif bearish_score > bullish_score * 1.3:
            return "LL_LH", hh_count, ll_count
        else:
            return "MIXED", hh_count, ll_count
    
    def _calculate_trend_strength(self, closes: List[float], highs: List[float], 
                                   lows: List[float], hh_count: int, ll_count: int) -> float:
        """Calculate trend strength 0-100"""
        if len(closes) < 5:
            return 0
        
        # Factor 1: Price vs moving average
        ma = sum(closes[-10:]) / 10
        current = closes[-1]
        ma_factor = min(abs(current - ma) / ma * 1000, 30)  # Max 30 points
        
        # Factor 2: Structure consistency
        total_swings = hh_count + ll_count
        if total_swings > 0:
            dominant = max(hh_count, ll_count)
            structure_factor = (dominant / total_swings) * 40  # Max 40 points
        else:
            structure_factor = 0
        
        # Factor 3: Recent momentum
        if len(closes) >= 5:
            recent_change = (closes[-1] - closes[-5]) / closes[-5] * 100
            momentum_factor = min(abs(recent_change) * 5, 30)  # Max 30 points
        else:
            momentum_factor = 0
        
        return min(ma_factor + structure_factor + momentum_factor, 100)
    
    def _determine_bias(self, structure: str, trend_strength: float, closes: List[float]) -> TimeframeBias:
        """Determine bias based on structure and strength"""
        if structure == "HH_HL":
            if trend_strength >= 70:
                return TimeframeBias.STRONG_BULLISH
            elif trend_strength >= 50:
                return TimeframeBias.BULLISH
            else:
                return TimeframeBias.WEAK_BULLISH
        elif structure == "LL_LH":
            if trend_strength >= 70:
                return TimeframeBias.STRONG_BEARISH
            elif trend_strength >= 50:
                return TimeframeBias.BEARISH
            else:
                return TimeframeBias.WEAK_BEARISH
        else:
            # Mixed structure - check recent closes
            if len(closes) >= 10:
                recent_trend = closes[-1] - closes[-10]
                if recent_trend > 0:
                    return TimeframeBias.WEAK_BULLISH
                elif recent_trend < 0:
                    return TimeframeBias.WEAK_BEARISH
            return TimeframeBias.NEUTRAL
    
    def _check_momentum(self, closes: List[float]) -> bool:
        """Check if momentum is aligned (price above short MA)"""
        if len(closes) < 10:
            return False
        ma_short = sum(closes[-5:]) / 5
        ma_long = sum(closes[-10:]) / 10
        return ma_short > ma_long
    
    def _find_key_level(self, highs: List[float], lows: List[float], bias: TimeframeBias) -> float:
        """Find the most relevant key level"""
        if bias in [TimeframeBias.STRONG_BULLISH, TimeframeBias.BULLISH, TimeframeBias.WEAK_BULLISH]:
            return min(lows[-5:]) if len(lows) >= 5 else lows[-1]
        elif bias in [TimeframeBias.STRONG_BEARISH, TimeframeBias.BEARISH, TimeframeBias.WEAK_BEARISH]:
            return max(highs[-5:]) if len(highs) >= 5 else highs[-1]
        return (highs[-1] + lows[-1]) / 2 if highs and lows else 0
    
    def _calculate_overall_bias(self, h1: BiasAnalysis, m15: BiasAnalysis, 
                                 m5: BiasAnalysis) -> Tuple[TimeframeBias, float]:
        """Calculate overall bias from all timeframes"""
        
        # Weight: H1 = 50%, M15 = 30%, M5 = 20%
        bias_scores = {
            TimeframeBias.STRONG_BULLISH: 100,
            TimeframeBias.BULLISH: 75,
            TimeframeBias.WEAK_BULLISH: 55,
            TimeframeBias.NEUTRAL: 50,
            TimeframeBias.WEAK_BEARISH: 45,
            TimeframeBias.BEARISH: 25,
            TimeframeBias.STRONG_BEARISH: 0,
        }
        
        h1_score = bias_scores[h1.bias] * 0.5
        m15_score = bias_scores[m15.bias] * 0.3
        m5_score = bias_scores[m5.bias] * 0.2
        
        combined_score = h1_score + m15_score + m5_score
        
        # Calculate alignment score
        scores = [bias_scores[h1.bias], bias_scores[m15.bias], bias_scores[m5.bias]]
        variance = sum((s - combined_score) ** 2 for s in scores) / 3
        alignment_score = max(0, 100 - variance / 5)
        
        # Determine overall bias
        if combined_score >= 80:
            overall = TimeframeBias.STRONG_BULLISH
        elif combined_score >= 65:
            overall = TimeframeBias.BULLISH
        elif combined_score >= 55:
            overall = TimeframeBias.WEAK_BULLISH
        elif combined_score >= 45:
            overall = TimeframeBias.NEUTRAL
        elif combined_score >= 35:
            overall = TimeframeBias.WEAK_BEARISH
        elif combined_score >= 20:
            overall = TimeframeBias.BEARISH
        else:
            overall = TimeframeBias.STRONG_BEARISH
        
        return overall, alignment_score
    
    def _determine_trade_direction(self, overall_bias: TimeframeBias, alignment_score: float) -> str:
        """Determine if we should look for LONG, SHORT, or NONE"""
        if alignment_score < 40:
            return "NONE"  # Too conflicted
        
        if overall_bias in [TimeframeBias.STRONG_BULLISH, TimeframeBias.BULLISH]:
            return "LONG"
        elif overall_bias in [TimeframeBias.STRONG_BEARISH, TimeframeBias.BEARISH]:
            return "SHORT"
        elif overall_bias == TimeframeBias.WEAK_BULLISH and alignment_score >= 60:
            return "LONG"
        elif overall_bias == TimeframeBias.WEAK_BEARISH and alignment_score >= 60:
            return "SHORT"
        else:
            return "NONE"
    
    def _is_countertrend(self, h1: BiasAnalysis, m15: BiasAnalysis, m5: BiasAnalysis) -> bool:
        """Check if M5 setup would be countertrend"""
        h1_bullish = h1.bias in [TimeframeBias.STRONG_BULLISH, TimeframeBias.BULLISH]
        h1_bearish = h1.bias in [TimeframeBias.STRONG_BEARISH, TimeframeBias.BEARISH]
        m5_bullish = m5.bias in [TimeframeBias.STRONG_BULLISH, TimeframeBias.BULLISH, TimeframeBias.WEAK_BULLISH]
        m5_bearish = m5.bias in [TimeframeBias.STRONG_BEARISH, TimeframeBias.BEARISH, TimeframeBias.WEAK_BEARISH]
        
        return (h1_bullish and m5_bearish) or (h1_bearish and m5_bullish)
    
    def get_bias_for_signal(self, asset: Asset, signal_type: str) -> Tuple[bool, float, str]:
        """
        Check if a signal type aligns with current bias
        
        Returns:
            (is_aligned, alignment_bonus, reason)
        """
        if asset not in self.last_analysis:
            return True, 0, "No bias analysis available"
        
        bias = self.last_analysis[asset]
        
        if signal_type == "BUY":
            if bias.trade_direction == "LONG":
                return True, bias.alignment_score * 0.2, f"Aligned with {bias.overall_bias.value} bias"
            elif bias.trade_direction == "SHORT":
                return False, -20, f"Against {bias.overall_bias.value} bias - BLOCKED"
            else:
                return True, -10, "Neutral bias - reduced score"
        
        elif signal_type == "SELL":
            if bias.trade_direction == "SHORT":
                return True, bias.alignment_score * 0.2, f"Aligned with {bias.overall_bias.value} bias"
            elif bias.trade_direction == "LONG":
                return False, -20, f"Against {bias.overall_bias.value} bias - BLOCKED"
            else:
                return True, -10, "Neutral bias - reduced score"
        
        return True, 0, "Unknown signal type"


# Global instance
mtf_bias_engine = MultiTimeframeBiasEngine()
