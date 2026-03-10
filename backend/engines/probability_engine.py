"""Probability Estimation Engine"""
from typing import Dict
from models import Asset, Timeframe, Session, StrategyType, MarketRegime
import random

class ProbabilityEngine:
    """Estimates success/failure probability for setups"""
    
    def __init__(self):
        # Historical performance database (mock data for now)
        # In production, this would be populated from backtest results
        self.historical_performance = self._initialize_mock_performance()
    
    def _initialize_mock_performance(self) -> Dict:
        """Initialize with realistic mock performance data"""
        # Base win rates by strategy type
        return {
            StrategyType.TREND_PULLBACK: {
                "base_win_rate": 0.58,
                "regime_bonus": {
                    MarketRegime.BULLISH_TREND: 0.08,
                    MarketRegime.BEARISH_TREND: 0.08,
                    MarketRegime.RANGE: -0.15,
                },
                "session_bonus": {
                    Session.OVERLAP: 0.05,
                    Session.LONDON: 0.03,
                    Session.NEW_YORK: 0.03,
                    Session.OTHER: -0.10
                }
            },
            StrategyType.BREAKOUT_RETEST: {
                "base_win_rate": 0.55,
                "regime_bonus": {
                    MarketRegime.BREAKOUT_EXPANSION: 0.10,
                    MarketRegime.BULLISH_TREND: 0.05,
                    MarketRegime.BEARISH_TREND: 0.05,
                },
                "session_bonus": {
                    Session.OVERLAP: 0.07,
                    Session.LONDON: 0.04,
                    Session.NEW_YORK: 0.04,
                }
            },
            StrategyType.RANGE_REJECTION: {
                "base_win_rate": 0.52,
                "regime_bonus": {
                    MarketRegime.RANGE: 0.12,
                    MarketRegime.COMPRESSION: 0.08,
                },
                "session_bonus": {
                    Session.OVERLAP: 0.03,
                    Session.LONDON: 0.02,
                }
            },
            StrategyType.STRUCTURE_BREAK: {
                "base_win_rate": 0.54,
                "regime_bonus": {
                    MarketRegime.BREAKOUT_EXPANSION: 0.09,
                },
                "session_bonus": {
                    Session.OVERLAP: 0.06,
                }
            },
            StrategyType.VOLATILITY_EXPANSION: {
                "base_win_rate": 0.60,
                "regime_bonus": {
                    MarketRegime.BREAKOUT_EXPANSION: 0.12,
                },
                "session_bonus": {
                    Session.OVERLAP: 0.05,
                    Session.NEW_YORK: 0.04,
                }
            }
        }
    
    def estimate_probability(self, strategy_type: StrategyType, asset: Asset,
                           timeframe: Timeframe, session: Session,
                           regime: MarketRegime, score: float) -> tuple[float, float]:
        """Estimate success and failure probability"""
        
        if strategy_type not in self.historical_performance:
            # Default conservative estimate
            return 0.50, 0.50
        
        strategy_data = self.historical_performance[strategy_type]
        
        # Start with base win rate
        win_rate = strategy_data["base_win_rate"]
        
        # Add regime bonus
        regime_bonuses = strategy_data.get("regime_bonus", {})
        win_rate += regime_bonuses.get(regime, 0)
        
        # Add session bonus
        session_bonuses = strategy_data.get("session_bonus", {})
        win_rate += session_bonuses.get(session, 0)
        
        # Adjust based on setup quality score
        # High score = higher probability
        if score >= 90:
            win_rate += 0.08
        elif score >= 85:
            win_rate += 0.05
        elif score >= 80:
            win_rate += 0.03
        elif score < 75:
            win_rate -= 0.05
        
        # Asset-specific adjustments
        if asset == Asset.XAUUSD:
            # Gold is slightly more volatile, reduce win rate slightly
            win_rate -= 0.02
        
        # Timeframe adjustments
        if timeframe in [Timeframe.M5, Timeframe.M15]:
            # Lower timeframes have more noise
            win_rate -= 0.03
        elif timeframe in [Timeframe.H4, Timeframe.D1]:
            # Higher timeframes more reliable
            win_rate += 0.03
        
        # Clamp between 0.35 and 0.75 (realistic range)
        win_rate = max(0.35, min(0.75, win_rate))
        
        # Calculate failure probability
        fail_rate = 1.0 - win_rate
        
        return round(win_rate * 100, 1), round(fail_rate * 100, 1)
    
    def get_expected_value(self, success_prob: float, risk_reward_ratio: float) -> float:
        """Calculate expected value of a trade"""
        # E(x) = (Win% × AvgWin) - (Loss% × AvgLoss)
        # Assuming AvgWin = RR ratio, AvgLoss = 1
        expected_value = (success_prob / 100 * risk_reward_ratio) - ((100 - success_prob) / 100 * 1)
        return round(expected_value, 2)

probability_engine = ProbabilityEngine()
