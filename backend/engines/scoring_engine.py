"""Scoring Engine - Evaluates setup quality"""
from models import (
    Asset, Timeframe, Session, MarketRegime, 
    StrategyType, ScoreBreakdown
)
from engines.signal_engine import StrategySetup

class ScoringEngine:
    """Scores trading setups on a 0-100 scale"""
    
    def __init__(self):
        # Minimum scores required
        self.min_scores = {
            Asset.EURUSD: 78,
            Asset.XAUUSD: 80
        }
        
        # Scoring weights (must sum to 100)
        self.weights = {
            "regime_quality": 20,
            "structure_clarity": 20,
            "trend_alignment": 15,
            "entry_quality": 10,
            "stop_quality": 10,
            "target_quality": 10,
            "session_quality": 5,
            "volatility_quality": 5,
            "prop_rule_safety": 5
        }
    
    def score_setup(self, setup: StrategySetup, asset: Asset, timeframe: Timeframe,
                   session: Session, regime: MarketRegime, 
                   regime_metadata: dict, regime_quality: float,
                   session_quality: float) -> ScoreBreakdown:
        """Calculate comprehensive score for a setup"""
        
        breakdown = ScoreBreakdown()
        
        # 1. Regime Quality (20 points)
        breakdown.regime_quality = regime_quality * 0.2
        
        # 2. Structure Clarity (20 points)
        breakdown.structure_clarity = setup.structure_quality * 0.2
        
        # 3. Trend Alignment (15 points)
        breakdown.trend_alignment = self._score_trend_alignment(
            setup, regime, regime_metadata
        ) * 0.15
        
        # 4. Entry Quality (10 points)
        breakdown.entry_quality = setup.entry_quality * 0.1
        
        # 5. Stop Quality (10 points)
        breakdown.stop_quality = self._score_stop_placement(
            setup, asset
        ) * 0.1
        
        # 6. Target Quality (10 points)
        breakdown.target_quality = setup.target_feasibility * 0.1
        
        # 7. Session Quality (5 points)
        breakdown.session_quality = session_quality * 0.05
        
        # 8. Volatility Quality (5 points)
        breakdown.volatility_quality = self._score_volatility(
            regime_metadata
        ) * 0.05
        
        # 9. Prop Rule Safety (5 points) - placeholder, will be set by prop engine
        breakdown.prop_rule_safety = 100 * 0.05
        
        # Calculate total
        breakdown.total = (
            breakdown.regime_quality +
            breakdown.structure_clarity +
            breakdown.trend_alignment +
            breakdown.entry_quality +
            breakdown.stop_quality +
            breakdown.target_quality +
            breakdown.session_quality +
            breakdown.volatility_quality +
            breakdown.prop_rule_safety
        )
        
        return breakdown
    
    def _score_trend_alignment(self, setup: StrategySetup, regime: MarketRegime,
                              regime_metadata: dict) -> float:
        """Score how well setup aligns with trend"""
        score = 50.0  # Base score
        
        # Check signal direction vs regime
        if regime == MarketRegime.BULLISH_TREND and setup.signal_type.value == "BUY":
            score = 95.0
        elif regime == MarketRegime.BEARISH_TREND and setup.signal_type.value == "SELL":
            score = 95.0
        elif regime == MarketRegime.RANGE:
            score = 70.0
        elif regime == MarketRegime.BREAKOUT_EXPANSION:
            score = 85.0
        
        # Adjust for trend slope
        trend_slope = regime_metadata.get("trend_slope", 0)
        if abs(trend_slope) > 0.0003:
            score = min(100, score + 5)
        
        return score
    
    def _score_stop_placement(self, setup: StrategySetup, asset: Asset) -> float:
        """Score stop loss placement"""
        score = 50.0
        
        # Check stop distance
        stop_pips = setup.stop_distance_pips
        
        if asset == Asset.EURUSD:
            # Ideal stop: 15-40 pips
            if 15 <= stop_pips <= 40:
                score = 90.0
            elif 10 <= stop_pips < 15:
                score = 75.0
            elif 40 < stop_pips <= 60:
                score = 70.0
            elif stop_pips > 80:
                score = 30.0  # Too wide
            elif stop_pips < 10:
                score = 40.0  # Too tight
        
        elif asset == Asset.XAUUSD:
            # Ideal stop: 50-150 pips (Gold moves more)
            if 50 <= stop_pips <= 150:
                score = 90.0
            elif 30 <= stop_pips < 50:
                score = 75.0
            elif 150 < stop_pips <= 200:
                score = 70.0
            elif stop_pips > 250:
                score = 30.0
            elif stop_pips < 30:
                score = 40.0
        
        # Check risk/reward ratio
        if setup.risk_reward_ratio >= 2.0:
            score = min(100, score + 10)
        elif setup.risk_reward_ratio >= 1.5:
            score = min(100, score + 5)
        
        return score
    
    def _score_volatility(self, regime_metadata: dict) -> float:
        """Score volatility conditions"""
        score = 70.0
        
        # Volatility expansion is good for trading
        if regime_metadata.get("volatility_expansion"):
            score = 85.0
        
        atr = regime_metadata.get("atr", 0)
        if atr > 0:
            # Higher ATR generally better (more opportunity)
            score = min(100, score + 10)
        
        return score
    
    def meets_minimum_threshold(self, score: float, asset: Asset) -> bool:
        """Check if score meets minimum threshold"""
        return score >= self.min_scores[asset]
    
    def get_confidence_level(self, score: float) -> str:
        """Convert score to confidence level"""
        if score >= 90:
            return "VERY HIGH"
        elif score >= 85:
            return "HIGH"
        elif score >= 78:
            return "MODERATE"
        else:
            return "LOW"

scoring_engine = ScoringEngine()
