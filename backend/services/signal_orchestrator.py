"""Signal Orchestration Service - Main signal generation pipeline"""
from typing import Optional
from datetime import datetime
from models import (
    Asset, Timeframe, Signal, SignalType, MarketRegime,
    PropProfile, ScoreBreakdown, PropRuleSafety
)
from engines.market_data import market_data_provider
from engines.regime_engine import regime_engine
from engines.session_detector import session_detector
from engines.signal_engine import signal_engine
from engines.scoring_engine import scoring_engine
from engines.prop_rule_engine import prop_rule_engine
from engines.probability_engine import probability_engine


class SignalOrchestrator:
    """Orchestrates the complete signal generation pipeline"""
    
    def __init__(self):
        self.market_data = market_data_provider
        self.regime_detector = regime_engine
        self.session_detector = session_detector
        self.signal_generator = signal_engine
        self.scorer = scoring_engine
        self.prop_checker = prop_rule_engine
        self.probability_estimator = probability_engine
    
    async def generate_signal(self, user_id: str, asset: Asset, 
                             prop_profile: PropProfile) -> Signal:
        """
        Main signal generation pipeline
        
        Pipeline:
        1. Detect session
        2. Detect market regime
        3. Generate candidate setups
        4. Filter invalid setups
        5. Calculate entry/stop/target
        6. Score setups
        7. Check prop rule safety
        8. Calculate probability
        9. Choose best candidate
        10. Return signal or NEXT
        """
        
        # Step 1: Detect session
        current_session = self.session_detector.get_current_session()
        session_quality = self.session_detector.get_session_quality_score(current_session)
        
        # Check if major session
        if not self.session_detector.is_major_session(current_session):
            return self._create_next_signal(
                user_id, asset, MarketRegime.CHAOTIC, current_session,
                "Not a major trading session. Waiting for London/NY session."
            )
        
        # Step 2: Determine best timeframe and get candles
        # For now, we'll use H1 as default, but in production this should scan all timeframes
        timeframe = Timeframe.H1
        candles = await self.market_data.get_candles(asset, timeframe, count=250)
        
        if len(candles) < 200:
            return self._create_next_signal(
                user_id, asset, MarketRegime.CHAOTIC, current_session,
                "Insufficient market data"
            )
        
        # Step 3: Detect market regime
        regime, regime_metadata = self.regime_detector.detect_regime(candles, asset)
        regime_quality = self.regime_detector.get_regime_quality_score(regime, regime_metadata)
        
        # Check if regime is tradeable
        if not self.regime_detector.is_regime_tradeable(regime):
            return self._create_next_signal(
                user_id, asset, regime, current_session,
                f"Market regime is {regime.value} - not suitable for trading. Waiting for clearer conditions."
            )
        
        # Step 4: Check prop profile health
        can_trade, health_message = self.prop_checker.should_allow_trading(prop_profile)
        if not can_trade:
            return self._create_next_signal(
                user_id, asset, regime, current_session,
                f"Trading blocked: {health_message}"
            )
        
        # Step 5: Generate candidate setups
        candidate_setups = self.signal_generator.generate_candidate_setups(candles, asset, regime)
        
        if not candidate_setups:
            return self._create_next_signal(
                user_id, asset, regime, current_session,
                f"No valid setups detected in current market conditions ({regime.value})"
            )
        
        # Step 6: Score and filter setups
        scored_setups = []
        for setup in candidate_setups:
            # Score the setup
            score_breakdown = self.scorer.score_setup(
                setup, asset, timeframe, current_session, regime,
                regime_metadata, regime_quality, session_quality
            )
            
            # Check minimum threshold
            if not self.scorer.meets_minimum_threshold(score_breakdown.total, asset):
                continue
            
            # Check prop rule safety
            safety_level, warnings = self.prop_checker.check_setup_safety(setup, prop_profile)
            
            if safety_level == PropRuleSafety.BLOCKED:
                continue
            
            # Calculate probability
            success_prob, failure_prob = self.probability_estimator.estimate_probability(
                setup.strategy_type, asset, timeframe, current_session, regime,
                score_breakdown.total
            )
            
            scored_setups.append({
                "setup": setup,
                "score": score_breakdown,
                "safety": safety_level,
                "warnings": warnings,
                "success_prob": success_prob,
                "failure_prob": failure_prob
            })
        
        # Step 7: Choose best setup
        if not scored_setups:
            return self._create_next_signal(
                user_id, asset, regime, current_session,
                f"Setups detected but none met quality threshold (min {self.scorer.min_scores[asset]})"
            )
        
        # Sort by score
        scored_setups.sort(key=lambda x: x["score"].total, reverse=True)
        best = scored_setups[0]
        
        # Step 8: Create signal
        signal = Signal(
            user_id=user_id,
            signal_type=best["setup"].signal_type,
            asset=asset,
            timeframe=timeframe,
            session=current_session,
            strategy_type=best["setup"].strategy_type,
            market_regime=regime,
            entry_price=best["setup"].entry_price,
            entry_zone_low=best["setup"].entry_zone_low,
            entry_zone_high=best["setup"].entry_zone_high,
            stop_loss=best["setup"].stop_loss,
            take_profit_1=best["setup"].take_profit_1,
            take_profit_2=best["setup"].take_profit_2,
            risk_reward_ratio=best["setup"].risk_reward_ratio,
            stop_distance_pips=best["setup"].stop_distance_pips,
            confidence_score=best["score"].total,
            score_breakdown=best["score"],
            success_probability=best["success_prob"],
            failure_probability=best["failure_prob"],
            expected_duration_minutes=best["setup"].expected_duration_minutes,
            trade_horizon=best["setup"].trade_horizon,
            explanation=best["setup"].explanation,
            prop_rule_safety=best["safety"],
            prop_rule_warnings=best["warnings"]
        )
        
        return signal
    
    def _create_next_signal(self, user_id: str, asset: Asset, regime: MarketRegime,
                           session, reason: str) -> Signal:
        """Create a NEXT signal when no trade is recommended"""
        return Signal(
            user_id=user_id,
            signal_type=SignalType.NEXT,
            asset=asset,
            timeframe=Timeframe.H1,
            session=session,
            market_regime=regime,
            next_reason=reason,
            confidence_score=0,
            is_active=False
        )


signal_orchestrator = SignalOrchestrator()
