"""Market Regime Detection Engine"""
from typing import List, Tuple
import statistics
from models import Candle, MarketRegime, Asset, Timeframe

class RegimeEngine:
    """Detects market regime based on technical indicators"""
    
    def __init__(self):
        pass
    
    def calculate_ema(self, candles: List[Candle], period: int) -> float:
        """Calculate Exponential Moving Average"""
        if len(candles) < period:
            return candles[-1].close
        
        multiplier = 2 / (period + 1)
        ema = candles[0].close
        
        for candle in candles[1:]:
            ema = (candle.close * multiplier) + (ema * (1 - multiplier))
        
        return ema
    
    def calculate_atr(self, candles: List[Candle], period: int = 14) -> float:
        """Calculate Average True Range"""
        if len(candles) < period + 1:
            return 0.0
        
        true_ranges = []
        for i in range(1, len(candles)):
            high = candles[i].high
            low = candles[i].low
            prev_close = candles[i-1].close
            
            tr = max(
                high - low,
                abs(high - prev_close),
                abs(low - prev_close)
            )
            true_ranges.append(tr)
        
        # Average last 'period' true ranges
        return statistics.mean(true_ranges[-period:])
    
    def calculate_trend_slope(self, candles: List[Candle], period: int = 20) -> float:
        """Calculate trend slope using linear regression"""
        if len(candles) < period:
            return 0.0
        
        recent_candles = candles[-period:]
        closes = [c.close for c in recent_candles]
        
        # Simple slope calculation
        x_mean = (len(closes) - 1) / 2
        y_mean = statistics.mean(closes)
        
        numerator = sum((i - x_mean) * (closes[i] - y_mean) for i in range(len(closes)))
        denominator = sum((i - x_mean) ** 2 for i in range(len(closes)))
        
        if denominator == 0:
            return 0.0
        
        slope = numerator / denominator
        return slope / y_mean  # Normalize by price
    
    def detect_regime(self, candles: List[Candle], asset: Asset) -> Tuple[MarketRegime, dict]:
        """Detect current market regime"""
        if len(candles) < 200:
            return MarketRegime.CHAOTIC, {"reason": "Insufficient data"}
        
        # Calculate indicators
        ema_20 = self.calculate_ema(candles[-20:], 20)
        ema_50 = self.calculate_ema(candles[-50:], 50)
        ema_200 = self.calculate_ema(candles[-200:], 200)
        current_price = candles[-1].close
        atr = self.calculate_atr(candles)
        
        # Calculate volatility expansion
        recent_atr = self.calculate_atr(candles[-20:], 14)
        historical_atr = self.calculate_atr(candles[-100:-20], 14)
        volatility_expansion = recent_atr > historical_atr * 1.3
        
        # Calculate trend slope
        trend_slope = self.calculate_trend_slope(candles)
        
        # Calculate recent range
        recent_candles = candles[-50:]
        recent_high = max(c.high for c in recent_candles)
        recent_low = min(c.low for c in recent_candles)
        recent_range = recent_high - recent_low
        
        # Price position relative to EMAs
        above_ema20 = current_price > ema_20
        above_ema50 = current_price > ema_50
        above_ema200 = current_price > ema_200
        
        # EMA alignment
        emas_aligned_bullish = ema_20 > ema_50 > ema_200
        emas_aligned_bearish = ema_20 < ema_50 < ema_200
        
        metadata = {
            "ema_20": ema_20,
            "ema_50": ema_50,
            "ema_200": ema_200,
            "atr": atr,
            "trend_slope": trend_slope,
            "volatility_expansion": volatility_expansion,
            "current_price": current_price
        }
        
        # Regime detection logic
        
        # Check for BULLISH_TREND
        if emas_aligned_bullish and above_ema20 and trend_slope > 0.0001:
            return MarketRegime.BULLISH_TREND, metadata
        
        # Check for BEARISH_TREND
        if emas_aligned_bearish and not above_ema20 and trend_slope < -0.0001:
            return MarketRegime.BEARISH_TREND, metadata
        
        # Check for BREAKOUT_EXPANSION
        if volatility_expansion and abs(trend_slope) > 0.0002:
            return MarketRegime.BREAKOUT_EXPANSION, metadata
        
        # Check for COMPRESSION (low volatility)
        if recent_atr < historical_atr * 0.7:
            return MarketRegime.COMPRESSION, metadata
        
        # Check for RANGE
        # Price oscillating around EMAs, low slope
        if abs(trend_slope) < 0.0001:
            ema_spread = abs(ema_20 - ema_50) / current_price
            if ema_spread < 0.002:  # EMAs are close together
                return MarketRegime.RANGE, metadata
        
        # Default to CHAOTIC if no clear regime
        return MarketRegime.CHAOTIC, metadata
    
    def is_regime_tradeable(self, regime: MarketRegime) -> bool:
        """Check if regime is suitable for trading"""
        return regime != MarketRegime.CHAOTIC
    
    def get_regime_quality_score(self, regime: MarketRegime, metadata: dict) -> float:
        """Score regime quality (0-100)"""
        base_scores = {
            MarketRegime.BULLISH_TREND: 90,
            MarketRegime.BEARISH_TREND: 90,
            MarketRegime.BREAKOUT_EXPANSION: 85,
            MarketRegime.RANGE: 70,
            MarketRegime.COMPRESSION: 60,
            MarketRegime.CHAOTIC: 20
        }
        
        score = base_scores.get(regime, 50)
        
        # Adjust based on volatility expansion
        if metadata.get("volatility_expansion") and regime in [MarketRegime.BULLISH_TREND, MarketRegime.BEARISH_TREND]:
            score = min(100, score + 5)
        
        return score

regime_engine = RegimeEngine()
