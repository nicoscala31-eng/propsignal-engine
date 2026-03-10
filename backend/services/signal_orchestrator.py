"""Enhanced Signal Orchestration Service - Production-grade with live data and position sizing"""
from typing import Optional
from datetime import datetime
import statistics
from models import (
    Asset, Timeframe, Signal, SignalType, MarketRegime,
    PropProfile, ScoreBreakdown, PropRuleSafety, AccountSettings
)
from providers.provider_manager import provider_manager
from providers.base_provider import LiveQuote
from engines.regime_engine import regime_engine
from engines.session_detector import session_detector
from engines.signal_engine import signal_engine
from engines.scoring_engine import scoring_engine
from engines.prop_rule_engine import prop_rule_engine
from engines.probability_engine import probability_engine
from engines.position_sizing_engine import position_sizing_engine
import logging

logger = logging.getLogger(__name__)

class EnhancedSignalOrchestrator:
    """Production-grade signal orchestrator with live data and institutional filters"""
    
    def __init__(self):
        self.regime_detector = regime_engine
        self.session_detector = session_detector
        self.signal_generator = signal_engine
        self.scorer = scoring_engine
        self.prop_checker = prop_rule_engine
        self.probability_estimator = probability_engine
        self.position_sizer = position_sizing_engine
        
        # Safety filters
        self.max_spreads = {
            Asset.EURUSD: 1.5,  # pips
            Asset.XAUUSD: 30.0   # points
        }
    
    async def generate_signal(self, user_id: str, asset: Asset, 
                             prop_profile: PropProfile,
                             account_settings: AccountSettings,
                             consecutive_losses: int = 0) -> Signal:
        """
        Enhanced signal generation pipeline with institutional-grade filters
        
        🚨 CRITICAL: Will BLOCK BUY/SELL signals if in simulation mode
        
        Pipeline:
        1. Check market data provider health
        2. Get live quote (bid/ask/spread)
        3. Detect session - must be London/NY/Overlap
        4. Get candles with live data
        5. Detect market regime
        6. Check spread filter
        7. Calculate ATR percentile - filter extremes
        8. Generate candidate setups
        9. Score setups (min threshold check)
        10. Check prop rule safety
        11. Calculate position sizing
        12. Calculate probability
        13. Return signal with complete risk data or NEXT
        """
        
        # Step 1: Check provider availability
        provider = provider_manager.get_provider()
        provider_status = provider_manager.get_status()
        
        # 🚨 CRITICAL CHECK: Block signals if simulation mode
        if provider_manager.is_simulation_mode():
            logger.error(f"🚫 BLOCKED {asset.value}: Cannot generate BUY/SELL in SIMULATION MODE")
            return self._create_next_signal(
                user_id, asset, MarketRegime.CHAOTIC, session_detector.get_current_session(),
                "⚠️ SIMULATION MODE - No real market data. "
                "BUY/SELL signals BLOCKED. Add TWELVE_DATA_API_KEY for real data.",
                None, "Simulation (Dev Only)"
            )
        
        if not provider or not provider_status:
            logger.error(f"❌ No provider available for {asset.value}")
            return self._create_next_signal(
                user_id, asset, MarketRegime.CHAOTIC, session_detector.get_current_session(),
                "DATA UNAVAILABLE - Market data provider not initialized",
                None, "N/A"
            )
        
        if not provider_status.is_connected:
            logger.error(f"❌ Provider not connected for {asset.value}")
            return self._create_next_signal(
                user_id, asset, MarketRegime.CHAOTIC, session_detector.get_current_session(),
                "DATA UNAVAILABLE - Market data provider not connected",
                None, provider_status.provider_name
            )
        
        # Warn if simulation mode
        if provider_manager.is_simulation_mode():
            logger.warning("⚠️  SIMULATION MODE - Signals based on simulated data")
        
        # Step 2: Get live quote
        live_quote: Optional[LiveQuote] = await provider.get_live_quote(asset)
        
        if not live_quote:
            return self._create_next_signal(
                user_id, asset, MarketRegime.CHAOTIC, session_detector.get_current_session(),
                "DATA UNAVAILABLE - Could not fetch live market quote",
                None, provider_status.provider_name
            )
        
        # Step 3: Session filter - STRICT
        current_session = self.session_detector.get_current_session()
        
        if not self.session_detector.is_major_session(current_session):
            return self._create_next_signal(
                user_id, asset, MarketRegime.CHAOTIC, current_session,
                f"Outside major trading sessions. Current: {current_session.value}. Wait for London/NY/Overlap.",
                live_quote, provider_status.provider_name
            )
        
        session_quality = self.session_detector.get_session_quality_score(current_session)
        
        # Step 4: Spread filter
        if live_quote.spread_pips > self.max_spreads[asset]:
            return self._create_next_signal(
                user_id, asset, MarketRegime.CHAOTIC, current_session,
                f"Spread too wide: {live_quote.spread_pips:.1f} pips (max {self.max_spreads[asset]})",
                live_quote, provider_status.provider_name
            )
        
        # Step 5: Get candles
        timeframe = Timeframe.H1  # Default timeframe
        candles = await provider.get_candles(asset, timeframe, count=250)
        
        if len(candles) < 200:
            return self._create_next_signal(
                user_id, asset, MarketRegime.CHAOTIC, current_session,
                "Insufficient candle data for analysis",
                live_quote, provider_status.provider_name
            )
        
        # Step 6: Detect market regime
        regime, regime_metadata = self.regime_detector.detect_regime(candles, asset)
        regime_quality = self.regime_detector.get_regime_quality_score(regime, regime_metadata)
        
        # Regime filter
        if not self.regime_detector.is_regime_tradeable(regime):
            return self._create_next_signal(
                user_id, asset, regime, current_session,
                f"Market regime {regime.value} not suitable for trading. Waiting for clearer conditions.",
                live_quote, provider_status.provider_name
            )
        
        # Step 7: ATR percentile filter
        atr_current = regime_metadata.get('atr', 0)
        
        # Calculate ATR percentile from recent candles
        recent_atrs = []
        for i in range(15, len(candles)):
            high = candles[i].high
            low = candles[i].low
            prev_close = candles[i-1].close
            tr = max(high - low, abs(high - prev_close), abs(low - prev_close))
            recent_atrs.append(tr)
        
        if len(recent_atrs) > 50:
            sorted_atrs = sorted(recent_atrs[-100:])
            atr_percentile = (sorted_atrs.index(min(sorted_atrs, key=lambda x: abs(x - atr_current))) / len(sorted_atrs)) * 100
            
            # Filter extreme volatility
            if atr_percentile < 25:
                return self._create_next_signal(
                    user_id, asset, regime, current_session,
                    f"Volatility too low (ATR percentile: {atr_percentile:.0f}%). Waiting for better conditions.",
                    live_quote, provider_status.provider_name
                )
            
            if atr_percentile > 90:
                return self._create_next_signal(
                    user_id, asset, regime, current_session,
                    f"Volatility too high (ATR percentile: {atr_percentile:.0f}%). Market too erratic.",
                    live_quote, provider_status.provider_name
                )
        
        # Step 8: Check prop profile health
        can_trade, health_message = self.prop_checker.should_allow_trading(prop_profile)
        if not can_trade:
            return self._create_next_signal(
                user_id, asset, regime, current_session,
                f"PROP SAFETY: {health_message}",
                live_quote, provider_status.provider_name
            )
        
        # Step 9: Generate candidate setups
        candidate_setups = self.signal_generator.generate_candidate_setups(candles, asset, regime)
        
        if not candidate_setups:
            return self._create_next_signal(
                user_id, asset, regime, current_session,
                f"No valid setups detected in {regime.value} regime",
                live_quote, provider_status.provider_name
            )
        
        # Step 10: Score, filter, and validate setups
        scored_setups = []
        for setup in candidate_setups:
            # Risk/Reward filter
            if setup.risk_reward_ratio < 1.5:
                logger.info(f"Setup rejected: R:R {setup.risk_reward_ratio:.1f} below minimum 1.5")
                continue
            
            # Score the setup
            score_breakdown = self.scorer.score_setup(
                setup, asset, timeframe, current_session, regime,
                regime_metadata, regime_quality, session_quality
            )
            
            # Minimum threshold check
            if not self.scorer.meets_minimum_threshold(score_breakdown.total, asset):
                logger.info(f"Setup rejected: score {score_breakdown.total:.0f} below threshold")
                continue
            
            # Prop rule safety check
            safety_level, warnings = self.prop_checker.check_setup_safety(setup, prop_profile)
            
            if safety_level == PropRuleSafety.BLOCKED:
                logger.info(f"Setup blocked by prop rules: {warnings}")
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
        
        # Step 11: Choose best setup
        if not scored_setups:
            return self._create_next_signal(
                user_id, asset, regime, current_session,
                f"Setups detected but none met quality threshold (min {self.scorer.min_scores[asset]})",
                live_quote, provider_status.provider_name
            )
        
        # Sort by score
        scored_setups.sort(key=lambda x: x["score"].total, reverse=True)
        best = scored_setups[0]
        
        # Step 12: Calculate position sizing
        lot_size, risk_pct, money_risk, risk_explanation = self.position_sizer.calculate_position_size(
            best["setup"],
            asset,
            prop_profile,
            account_settings.risk_mode,
            consecutive_losses
        )
        
        # Validate lot size
        is_valid, validation_msg = self.position_sizer.validate_position_size(lot_size, asset, prop_profile)
        
        if not is_valid:
            return self._create_next_signal(
                user_id, asset, regime, current_session,
                f"Position sizing error: {validation_msg}",
                live_quote, provider_status.provider_name
            )
        
        # Step 13: Create signal with complete data
        signal = Signal(
            user_id=user_id,
            signal_type=best["setup"].signal_type,
            asset=asset,
            timeframe=timeframe,
            session=current_session,
            strategy_type=best["setup"].strategy_type,
            market_regime=regime,
            
            # Live market data
            live_bid=live_quote.bid,
            live_ask=live_quote.ask,
            live_spread_pips=live_quote.spread_pips,
            data_provider=provider_status.provider_name,
            
            # Trade parameters
            entry_price=best["setup"].entry_price,
            entry_zone_low=best["setup"].entry_zone_low,
            entry_zone_high=best["setup"].entry_zone_high,
            stop_loss=best["setup"].stop_loss,
            take_profit_1=best["setup"].take_profit_1,
            take_profit_2=best["setup"].take_profit_2,
            risk_reward_ratio=best["setup"].risk_reward_ratio,
            stop_distance_pips=best["setup"].stop_distance_pips,
            
            # Position sizing
            lot_size=lot_size,
            risk_percentage=risk_pct,
            money_at_risk=money_risk,
            risk_mode=account_settings.risk_mode,
            risk_explanation=risk_explanation,
            
            # Scoring
            confidence_score=best["score"].total,
            score_breakdown=best["score"],
            
            # Probability
            success_probability=best["success_prob"],
            failure_probability=best["failure_prob"],
            
            # Duration
            expected_duration_minutes=best["setup"].expected_duration_minutes,
            trade_horizon=best["setup"].trade_horizon,
            
            # Explanation
            explanation=best["setup"].explanation,
            
            # Prop safety
            prop_rule_safety=best["safety"],
            prop_rule_warnings=best["warnings"]
        )
        
        logger.info(f"✅ {signal.signal_type.value} signal generated: {asset.value} @ {live_quote.mid_price:.5f}, "
                   f"Lot: {lot_size:.2f}, Risk: {risk_pct:.2f}%, Confidence: {best['score'].total:.0f}%")
        
        return signal
    
    def _create_next_signal(self, user_id: str, asset: Asset, regime: MarketRegime,
                           session, reason: str, live_quote: Optional[LiveQuote],
                           provider_name: str) -> Signal:
        """Create a NEXT signal when no trade is recommended"""
        signal = Signal(
            user_id=user_id,
            signal_type=SignalType.NEXT,
            asset=asset,
            timeframe=Timeframe.H1,
            session=session,
            market_regime=regime,
            next_reason=reason,
            confidence_score=0,
            is_active=False,
            data_provider=provider_name
        )
        
        # Include live data if available
        if live_quote:
            signal.live_bid = live_quote.bid
            signal.live_ask = live_quote.ask
            signal.live_spread_pips = live_quote.spread_pips
        
        logger.info(f"⏭️  NEXT signal: {asset.value} - {reason}")
        
        return signal

enhanced_signal_orchestrator = EnhancedSignalOrchestrator()
