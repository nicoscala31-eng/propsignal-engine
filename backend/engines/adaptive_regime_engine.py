"""Adaptive Regime Weighting Engine - Context-aware strategy prioritization"""
from typing import Dict, List, Tuple
from models import MarketRegime, StrategyType
import logging

logger = logging.getLogger(__name__)

class StrategyWeight:
    """Strategy weighting configuration"""
    def __init__(self, multiplier: float, reason: str, priority: str):
        self.multiplier = multiplier  # Score multiplier (0.0 - 2.0)
        self.reason = reason  # Explanation for weight
        self.priority = priority  # "HIGH", "MEDIUM", "LOW", "BLOCKED"

class AdaptiveRegimeWeightingEngine:
    """Dynamically adjusts strategy scores based on market regime"""
    
    def __init__(self):
        # Regime-Strategy Compatibility Matrix
        self.regime_strategy_weights = self._initialize_weights()
    
    def _initialize_weights(self) -> Dict[MarketRegime, Dict[StrategyType, StrategyWeight]]:
        """Define compatibility matrix for all regime-strategy combinations"""
        
        return {
            # BULLISH TREND: Favor trend-following strategies
            MarketRegime.BULLISH_TREND: {
                StrategyType.TREND_PULLBACK: StrategyWeight(
                    multiplier=1.5,
                    reason="Strong bullish trend - pullbacks are high probability entries",
                    priority="HIGH"
                ),
                StrategyType.STRUCTURE_BREAK: StrategyWeight(
                    multiplier=1.4,
                    reason="Bullish trend - structure breaks aligned with momentum",
                    priority="HIGH"
                ),
                StrategyType.BREAKOUT_RETEST: StrategyWeight(
                    multiplier=1.2,
                    reason="Trend supports breakout continuation",
                    priority="MEDIUM"
                ),
                StrategyType.RANGE_REJECTION: StrategyWeight(
                    multiplier=0.3,
                    reason="Not in range - counter-trend strategy penalized",
                    priority="BLOCKED"
                ),
                StrategyType.VOLATILITY_EXPANSION: StrategyWeight(
                    multiplier=1.1,
                    reason="Expansion can accelerate trend",
                    priority="MEDIUM"
                ),
            },
            
            # BEARISH TREND: Favor trend-following strategies
            MarketRegime.BEARISH_TREND: {
                StrategyType.TREND_PULLBACK: StrategyWeight(
                    multiplier=1.5,
                    reason="Strong bearish trend - pullbacks are high probability entries",
                    priority="HIGH"
                ),
                StrategyType.STRUCTURE_BREAK: StrategyWeight(
                    multiplier=1.4,
                    reason="Bearish trend - structure breaks aligned with momentum",
                    priority="HIGH"
                ),
                StrategyType.BREAKOUT_RETEST: StrategyWeight(
                    multiplier=1.2,
                    reason="Trend supports breakdown continuation",
                    priority="MEDIUM"
                ),
                StrategyType.RANGE_REJECTION: StrategyWeight(
                    multiplier=0.3,
                    reason="Not in range - counter-trend strategy penalized",
                    priority="BLOCKED"
                ),
                StrategyType.VOLATILITY_EXPANSION: StrategyWeight(
                    multiplier=1.1,
                    reason="Expansion can accelerate trend",
                    priority="MEDIUM"
                ),
            },
            
            # RANGE: Favor mean-reversion strategies
            MarketRegime.RANGE: {
                StrategyType.RANGE_REJECTION: StrategyWeight(
                    multiplier=1.8,
                    reason="Range-bound market - boundary rejections are optimal",
                    priority="HIGH"
                ),
                StrategyType.BREAKOUT_RETEST: StrategyWeight(
                    multiplier=1.3,
                    reason="Range breakouts can occur - monitor for retest",
                    priority="MEDIUM"
                ),
                StrategyType.TREND_PULLBACK: StrategyWeight(
                    multiplier=0.5,
                    reason="No clear trend - pullback strategy less reliable",
                    priority="LOW"
                ),
                StrategyType.STRUCTURE_BREAK: StrategyWeight(
                    multiplier=0.6,
                    reason="Range environment - structure breaks less meaningful",
                    priority="LOW"
                ),
                StrategyType.VOLATILITY_EXPANSION: StrategyWeight(
                    multiplier=0.7,
                    reason="Low volatility in range - expansion strategy reduced",
                    priority="LOW"
                ),
            },
            
            # COMPRESSION: Minimal signals, await breakout
            MarketRegime.COMPRESSION: {
                StrategyType.VOLATILITY_EXPANSION: StrategyWeight(
                    multiplier=1.6,
                    reason="Compression often precedes expansion - monitor for breakout",
                    priority="MEDIUM"
                ),
                StrategyType.TREND_PULLBACK: StrategyWeight(
                    multiplier=0.2,
                    reason="Low volatility - pullbacks unreliable",
                    priority="BLOCKED"
                ),
                StrategyType.STRUCTURE_BREAK: StrategyWeight(
                    multiplier=0.2,
                    reason="Compression phase - structure breaks lack follow-through",
                    priority="BLOCKED"
                ),
                StrategyType.BREAKOUT_RETEST: StrategyWeight(
                    multiplier=0.3,
                    reason="Low activity - breakouts lack strength",
                    priority="BLOCKED"
                ),
                StrategyType.RANGE_REJECTION: StrategyWeight(
                    multiplier=0.4,
                    reason="Tight range - rejections lack space",
                    priority="BLOCKED"
                ),
            },
            
            # BREAKOUT_EXPANSION: Favor momentum strategies
            MarketRegime.BREAKOUT_EXPANSION: {
                StrategyType.BREAKOUT_RETEST: StrategyWeight(
                    multiplier=1.7,
                    reason="Strong breakout - retest offers optimal entry",
                    priority="HIGH"
                ),
                StrategyType.VOLATILITY_EXPANSION: StrategyWeight(
                    multiplier=1.6,
                    reason="High volatility expansion - momentum strategy favored",
                    priority="HIGH"
                ),
                StrategyType.STRUCTURE_BREAK: StrategyWeight(
                    multiplier=1.3,
                    reason="Expansion phase - structure breaks gain momentum",
                    priority="MEDIUM"
                ),
                StrategyType.TREND_PULLBACK: StrategyWeight(
                    multiplier=1.1,
                    reason="Early trend formation - pullbacks can work",
                    priority="MEDIUM"
                ),
                StrategyType.RANGE_REJECTION: StrategyWeight(
                    multiplier=0.2,
                    reason="Expansion invalidates range - rejection strategy blocked",
                    priority="BLOCKED"
                ),
            },
            
            # CHAOTIC: Block all strategies
            MarketRegime.CHAOTIC: {
                StrategyType.TREND_PULLBACK: StrategyWeight(
                    multiplier=0.0,
                    reason="Chaotic conditions - all strategies unreliable",
                    priority="BLOCKED"
                ),
                StrategyType.STRUCTURE_BREAK: StrategyWeight(
                    multiplier=0.0,
                    reason="Chaotic conditions - all strategies unreliable",
                    priority="BLOCKED"
                ),
                StrategyType.BREAKOUT_RETEST: StrategyWeight(
                    multiplier=0.0,
                    reason="Chaotic conditions - all strategies unreliable",
                    priority="BLOCKED"
                ),
                StrategyType.RANGE_REJECTION: StrategyWeight(
                    multiplier=0.0,
                    reason="Chaotic conditions - all strategies unreliable",
                    priority="BLOCKED"
                ),
                StrategyType.VOLATILITY_EXPANSION: StrategyWeight(
                    multiplier=0.0,
                    reason="Chaotic conditions - all strategies unreliable",
                    priority="BLOCKED"
                ),
            },
        }
    
    def get_strategy_weight(self, regime: MarketRegime, strategy: StrategyType) -> StrategyWeight:
        """Get weight for a specific strategy in current regime"""
        regime_weights = self.regime_strategy_weights.get(regime, {})
        return regime_weights.get(strategy, StrategyWeight(1.0, "Default weight", "MEDIUM"))
    
    def apply_adaptive_weighting(self, base_score: float, regime: MarketRegime, 
                                 strategy: StrategyType) -> Tuple[float, StrategyWeight]:
        """Apply regime-based weight to strategy score"""
        weight = self.get_strategy_weight(regime, strategy)
        adjusted_score = base_score * weight.multiplier
        
        logger.info(f"📊 Adaptive weighting: {strategy.value} in {regime.value} - "
                   f"Base: {base_score:.1f} × {weight.multiplier} = {adjusted_score:.1f} ({weight.priority})")
        
        return adjusted_score, weight
    
    def get_regime_priorities(self, regime: MarketRegime) -> Dict[str, List[str]]:
        """Get prioritized and penalized strategies for regime"""
        regime_weights = self.regime_strategy_weights.get(regime, {})
        
        high_priority = []
        medium_priority = []
        low_priority = []
        blocked = []
        
        for strategy, weight in regime_weights.items():
            strategy_name = strategy.value.replace('_', ' ').title()
            if weight.priority == "HIGH":
                high_priority.append(strategy_name)
            elif weight.priority == "MEDIUM":
                medium_priority.append(strategy_name)
            elif weight.priority == "LOW":
                low_priority.append(strategy_name)
            elif weight.priority == "BLOCKED":
                blocked.append(strategy_name)
        
        return {
            "high_priority": high_priority,
            "medium_priority": medium_priority,
            "low_priority": low_priority,
            "blocked": blocked
        }
    
    def is_strategy_viable(self, regime: MarketRegime, strategy: StrategyType, 
                          min_multiplier: float = 0.5) -> bool:
        """Check if strategy is viable in current regime"""
        weight = self.get_strategy_weight(regime, strategy)
        return weight.multiplier >= min_multiplier
    
    def get_best_strategies_for_regime(self, regime: MarketRegime, top_n: int = 3) -> List[Tuple[StrategyType, float]]:
        """Get top N strategies for current regime sorted by multiplier"""
        regime_weights = self.regime_strategy_weights.get(regime, {})
        
        strategies = [
            (strategy, weight.multiplier) 
            for strategy, weight in regime_weights.items()
        ]
        
        strategies.sort(key=lambda x: x[1], reverse=True)
        return strategies[:top_n]
    
    def explain_regime_strategy_fit(self, regime: MarketRegime, strategy: StrategyType) -> str:
        """Get human-readable explanation of regime-strategy compatibility"""
        weight = self.get_strategy_weight(regime, strategy)
        
        strategy_name = strategy.value.replace('_', ' ').title()
        regime_name = regime.value.replace('_', ' ').title()
        
        if weight.multiplier >= 1.4:
            fit = "EXCELLENT"
        elif weight.multiplier >= 1.1:
            fit = "GOOD"
        elif weight.multiplier >= 0.8:
            fit = "ACCEPTABLE"
        elif weight.multiplier >= 0.5:
            fit = "POOR"
        else:
            fit = "INCOMPATIBLE"
        
        return f"{strategy_name} in {regime_name}: {fit} ({weight.reason})"

# Global instance
adaptive_regime_engine = AdaptiveRegimeWeightingEngine()
