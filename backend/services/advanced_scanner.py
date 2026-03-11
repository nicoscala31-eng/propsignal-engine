"""
Advanced Market Scanner v2 - Production-grade signal generation with MTF bias
============================================================================

Implements:
- Multi-Timeframe Bias Engine (H1 -> M15 -> M5)
- Market Structure Break (MSB) Detection
- Displacement Validation
- Pullback Zone Detection
- Multiple Setup Detection Modules
- Weighted Scoring System (0-100)
- Session-Aware Score Adjustments
- Strong Duplicate Protection
- Complete Signal Metadata
- Detailed Logging

CRITICAL RULE: A signal can ONLY be generated if this sequence occurs:
1. Market Structure Break (MSB) - Price breaks recent swing high/low
2. Displacement - Break happens with strong impulsive move
3. Controlled Pullback - Price retraces to a key technical zone
4. M5 Trigger - Only after pullback is complete

Design Goals:
- Signal quality as TOP PRIORITY
- Default threshold: 78 (only A/A+ signals)
- Strict MTF alignment required
- MSB + Displacement + Pullback sequence REQUIRED
- Execution on M5 timeframe
- Fast scanning (<5 seconds per cycle)
"""

import asyncio
import logging
import json
from typing import Dict, Set, Optional, List, Any, Tuple
from datetime import datetime, timedelta
from dataclasses import dataclass, field
from pathlib import Path

from models import (
    Asset, SignalType, Signal, Timeframe, Session,
    MarketRegime, SignalOutcome, SignalLifecycle, ScoreBreakdown
)
from services.scanner_config import (
    ScannerConfig, DEFAULT_SCANNER_CONFIG, SetupType, SignalGrade
)
from engines.mtf_bias_engine import mtf_bias_engine, MultiTimeframeBias, TimeframeBias
from engines.market_structure_engine import market_structure_engine, MSBSequence
from engines.setup_modules import SETUP_MODULES, SetupCandidate
from engines.advanced_scoring_engine import advanced_scoring_engine, SignalScore
from engines.session_detector import session_detector
from services.push_notification_service import push_service
from providers.provider_manager import provider_manager

logger = logging.getLogger(__name__)

# State persistence
STATE_FILE = Path("/app/backend/advanced_scanner_state.json")


@dataclass
class RecentSignal:
    """Track recently sent signals for duplicate prevention"""
    signal_id: str
    asset: Asset
    direction: str
    setup_type: str
    entry_price: float
    timestamp: datetime
    score: float


@dataclass 
class ScanCycleResult:
    """Result of a complete scan cycle"""
    asset: Asset
    scan_duration_ms: float
    mtf_bias: Optional[MultiTimeframeBias]
    candidates_found: int
    candidates_rejected: int
    signal_generated: bool
    signal_score: Optional[float] = None
    signal_grade: Optional[str] = None
    rejection_reasons: List[str] = field(default_factory=list)


class AdvancedMarketScanner:
    """
    Advanced Market Scanner with MTF Bias and Weighted Scoring
    
    Key Features:
    - Analyzes H1, M15, M5 for directional bias
    - Runs multiple setup detection modules
    - Scores signals 0-100 with weighted components
    - Only generates signals above threshold (78)
    - Strong duplicate protection
    - Complete metadata on every signal
    - Detailed logging for transparency
    """
    
    def __init__(self, db, config: ScannerConfig = None):
        self.db = db
        self.config = config or DEFAULT_SCANNER_CONFIG
        self.is_running = False
        self.scan_interval = 30  # seconds
        self.scanner_task: Optional[asyncio.Task] = None
        
        # Recent signals for duplicate prevention
        self.recent_signals: Dict[Asset, List[RecentSignal]] = {
            Asset.EURUSD: [],
            Asset.XAUUSD: []
        }
        
        # Cooldown tracking
        self.last_signal_by_direction: Dict[Tuple[Asset, str], datetime] = {}
        self.signals_this_hour: Dict[Asset, List[datetime]] = {
            Asset.EURUSD: [],
            Asset.XAUUSD: []
        }
        
        # Notification tracking
        self.notification_cooldown: Dict[str, datetime] = {}
        self.min_notification_interval = 60  # seconds
        
        # Statistics
        self.scan_count = 0
        self.signal_count = 0
        self.notification_count = 0
        self.start_time: Optional[datetime] = None
        self.last_scan_time: Optional[datetime] = None
        
        # Error tracking
        self.consecutive_errors = 0
        self.max_consecutive_errors = 5
        
        # Load state
        self._load_state()
        
        logger.info("🚀 Advanced Scanner v2 initialized")
        logger.info(f"   Score threshold: {self.config.min_score_threshold}")
        logger.info(f"   Require HTF alignment: {self.config.require_htf_alignment}")
        logger.info(f"   Enabled setups: {[s.value for s, enabled in self.config.enabled_setups.items() if enabled]}")
    
    def _load_state(self):
        """Load persisted state"""
        try:
            if STATE_FILE.exists():
                with open(STATE_FILE, 'r') as f:
                    state = json.load(f)
                self.scan_count = state.get("scan_count", 0)
                self.signal_count = state.get("signal_count", 0)
                self.notification_count = state.get("notification_count", 0)
                logger.info(f"📂 Loaded state: {self.scan_count} scans, {self.signal_count} signals")
        except Exception as e:
            logger.warning(f"Could not load state: {e}")
    
    def _save_state(self):
        """Persist state"""
        try:
            state = {
                "scan_count": self.scan_count,
                "signal_count": self.signal_count,
                "notification_count": self.notification_count,
                "last_save": datetime.utcnow().isoformat()
            }
            with open(STATE_FILE, 'w') as f:
                json.dump(state, f)
        except Exception as e:
            logger.warning(f"Could not save state: {e}")
    
    async def start(self):
        """Start the scanner"""
        if self.is_running:
            logger.warning("Advanced scanner already running")
            return
        
        self.is_running = True
        self.start_time = datetime.utcnow()
        
        logger.info("=" * 60)
        logger.info("🚀 ADVANCED SCANNER V2 STARTED")
        logger.info(f"   Score Threshold: {self.config.min_score_threshold}")
        logger.info(f"   MTF Required: {self.config.require_htf_alignment}")
        logger.info(f"   Scan Interval: {self.scan_interval}s")
        logger.info("=" * 60)
        
        self.scanner_task = asyncio.create_task(self._run_scanner_loop())
    
    async def stop(self):
        """Stop the scanner"""
        self.is_running = False
        if self.scanner_task:
            self.scanner_task.cancel()
            try:
                await self.scanner_task
            except asyncio.CancelledError:
                pass
        self._save_state()
        logger.info("🛑 Advanced Scanner stopped")
    
    async def _run_scanner_loop(self):
        """Main scanner loop"""
        while self.is_running:
            try:
                await self._scan_all_assets()
                self.consecutive_errors = 0
                
                if self.scan_count % 10 == 0:
                    self._save_state()
                    
            except Exception as e:
                self.consecutive_errors += 1
                logger.error(f"Scanner error ({self.consecutive_errors}): {e}", exc_info=True)
                
                if self.consecutive_errors >= self.max_consecutive_errors:
                    logger.critical("🚨 Max errors reached, waiting 30s...")
                    await asyncio.sleep(30)
                    self.consecutive_errors = 0
            
            await asyncio.sleep(self.scan_interval)
    
    async def _scan_all_assets(self):
        """Scan all tracked assets"""
        self.scan_count += 1
        self.last_scan_time = datetime.utcnow()
        
        # Get devices for notifications
        devices = await self.db.devices.find({"is_active": True}).to_list(1000)
        
        for asset in [Asset.EURUSD, Asset.XAUUSD]:
            result = await self._scan_asset(asset)
            
            if result.signal_generated and devices:
                await self._send_notifications(asset, devices)
            
            # Log scan result
            if self.config.verbose_logging:
                logger.info(f"📊 {asset.value} scan: {result.scan_duration_ms:.0f}ms, "
                           f"candidates: {result.candidates_found}, "
                           f"signal: {result.signal_generated}")
    
    async def _scan_asset(self, asset: Asset) -> ScanCycleResult:
        """Scan a single asset for signals"""
        start_time = datetime.utcnow()
        rejection_reasons = []
        
        # Get provider
        provider = provider_manager.get_provider()
        if not provider or provider_manager.is_simulation_mode():
            return ScanCycleResult(
                asset=asset,
                scan_duration_ms=0,
                mtf_bias=None,
                candidates_found=0,
                candidates_rejected=0,
                signal_generated=False,
                rejection_reasons=["No market data provider"]
            )
        
        # Get current session
        current_session = session_detector.get_current_session()
        session_name = self._get_session_name(current_session)
        
        # Step 1: Fetch candles for all timeframes
        try:
            candles_h1 = await provider.get_candles(asset, Timeframe.H1, count=50)
            candles_m15 = await provider.get_candles(asset, Timeframe.M15, count=100)
            candles_m5 = await provider.get_candles(asset, Timeframe.M5, count=200)
        except Exception as e:
            logger.error(f"Failed to fetch candles for {asset.value}: {e}")
            return ScanCycleResult(
                asset=asset,
                scan_duration_ms=(datetime.utcnow() - start_time).total_seconds() * 1000,
                mtf_bias=None,
                candidates_found=0,
                candidates_rejected=0,
                signal_generated=False,
                rejection_reasons=[f"Candle fetch error: {e}"]
            )
        
        # Validate candle data
        if len(candles_h1) < 20 or len(candles_m15) < 50 or len(candles_m5) < 100:
            return ScanCycleResult(
                asset=asset,
                scan_duration_ms=(datetime.utcnow() - start_time).total_seconds() * 1000,
                mtf_bias=None,
                candidates_found=0,
                candidates_rejected=0,
                signal_generated=False,
                rejection_reasons=["Insufficient candle data"]
            )
        
        # Convert candles to dict format for engines
        h1_data = [{"open": c.open, "high": c.high, "low": c.low, "close": c.close} for c in candles_h1]
        m15_data = [{"open": c.open, "high": c.high, "low": c.low, "close": c.close} for c in candles_m15]
        m5_data = [{"open": c.open, "high": c.high, "low": c.low, "close": c.close} for c in candles_m5]
        
        # Step 2: Analyze MTF bias
        mtf_bias = mtf_bias_engine.analyze_bias(asset, h1_data, m15_data, m5_data)
        
        # Check if we have a clear direction
        if self.config.require_htf_alignment and mtf_bias.trade_direction == "NONE":
            rejection_reasons.append(f"No clear HTF direction (alignment: {mtf_bias.alignment_score:.0f}%)")
            logger.info(f"⏭️  {asset.value}: {rejection_reasons[-1]}")
            return ScanCycleResult(
                asset=asset,
                scan_duration_ms=(datetime.utcnow() - start_time).total_seconds() * 1000,
                mtf_bias=mtf_bias,
                candidates_found=0,
                candidates_rejected=0,
                signal_generated=False,
                rejection_reasons=rejection_reasons
            )
        
        # Step 2.5: CRITICAL - Validate MSB -> Displacement -> Pullback sequence
        # This is the GATEKEEPER - no signal without valid structure sequence
        msb_sequence = market_structure_engine.analyze_sequence(asset, m5_data)
        
        if not msb_sequence.is_complete:
            rejection_reasons.append(f"MSB sequence incomplete: {msb_sequence.rejection_reason}")
            logger.info(f"⏭️  {asset.value}: {rejection_reasons[-1]}")
            return ScanCycleResult(
                asset=asset,
                scan_duration_ms=(datetime.utcnow() - start_time).total_seconds() * 1000,
                mtf_bias=mtf_bias,
                candidates_found=0,
                candidates_rejected=0,
                signal_generated=False,
                rejection_reasons=rejection_reasons
            )
        
        if not msb_sequence.is_ready_for_trigger:
            rejection_reasons.append(f"MSB sequence not ready for trigger - waiting for pullback completion")
            logger.info(f"⏭️  {asset.value}: {rejection_reasons[-1]}")
            return ScanCycleResult(
                asset=asset,
                scan_duration_ms=(datetime.utcnow() - start_time).total_seconds() * 1000,
                mtf_bias=mtf_bias,
                candidates_found=0,
                candidates_rejected=0,
                signal_generated=False,
                rejection_reasons=rejection_reasons
            )
        
        # Verify MSB direction matches MTF bias direction
        if msb_sequence.direction != mtf_bias.trade_direction:
            rejection_reasons.append(f"MSB direction ({msb_sequence.direction}) mismatches MTF bias ({mtf_bias.trade_direction})")
            logger.info(f"⏭️  {asset.value}: {rejection_reasons[-1]}")
            return ScanCycleResult(
                asset=asset,
                scan_duration_ms=(datetime.utcnow() - start_time).total_seconds() * 1000,
                mtf_bias=mtf_bias,
                candidates_found=0,
                candidates_rejected=0,
                signal_generated=False,
                rejection_reasons=rejection_reasons
            )
        
        logger.info(f"✅ {asset.value}: MSB sequence VALID - {msb_sequence.get_summary()}")
        
        # Step 3: Run setup detection modules
        candidates: List[SetupCandidate] = []
        for setup_type, module in SETUP_MODULES.items():
            if not self.config.enabled_setups.get(setup_type, False):
                continue
            
            try:
                candidate = module.detect(asset, m5_data, mtf_bias.trade_direction)
                if candidate:
                    candidates.append(candidate)
                    logger.info(f"   ✓ {module.name} found candidate: {candidate.direction}")
            except Exception as e:
                logger.error(f"Setup module {module.name} error: {e}")
        
        if not candidates:
            rejection_reasons.append("No setup candidates detected")
            return ScanCycleResult(
                asset=asset,
                scan_duration_ms=(datetime.utcnow() - start_time).total_seconds() * 1000,
                mtf_bias=mtf_bias,
                candidates_found=0,
                candidates_rejected=0,
                signal_generated=False,
                rejection_reasons=rejection_reasons
            )
        
        # Step 4: Calculate volatility percentile for scoring
        volatility_percentile = self._calculate_volatility_percentile(m5_data)
        
        # Step 5: Score all candidates
        scored_candidates: List[Tuple[SetupCandidate, SignalScore]] = []
        rejected_count = 0
        
        for candidate in candidates:
            score = advanced_scoring_engine.score_signal(
                candidate, mtf_bias, session_name, volatility_percentile
            )
            
            if score.passes_threshold:
                scored_candidates.append((candidate, score))
            else:
                rejected_count += 1
                if self.config.log_rejected_signals:
                    logger.info(f"   ✗ Rejected {candidate.setup_type.value}: "
                               f"score {score.total_score:.1f} < {self.config.min_score_threshold}")
        
        if not scored_candidates:
            rejection_reasons.append(f"All {len(candidates)} candidates below threshold")
            return ScanCycleResult(
                asset=asset,
                scan_duration_ms=(datetime.utcnow() - start_time).total_seconds() * 1000,
                mtf_bias=mtf_bias,
                candidates_found=len(candidates),
                candidates_rejected=rejected_count,
                signal_generated=False,
                rejection_reasons=rejection_reasons
            )
        
        # Step 6: Select best candidate
        scored_candidates.sort(key=lambda x: x[1].total_score, reverse=True)
        best_candidate, best_score = scored_candidates[0]
        
        # Step 7: Check duplicate protection
        is_duplicate, duplicate_reason = self._check_duplicate(asset, best_candidate)
        if is_duplicate:
            rejection_reasons.append(duplicate_reason)
            logger.info(f"   ⚠️  Duplicate protection: {duplicate_reason}")
            return ScanCycleResult(
                asset=asset,
                scan_duration_ms=(datetime.utcnow() - start_time).total_seconds() * 1000,
                mtf_bias=mtf_bias,
                candidates_found=len(candidates),
                candidates_rejected=rejected_count + 1,
                signal_generated=False,
                rejection_reasons=rejection_reasons
            )
        
        # Step 8: Generate and store signal
        signal = await self._create_signal(asset, best_candidate, best_score, mtf_bias, current_session)
        
        if signal:
            # Track for duplicate protection
            self._record_signal(asset, best_candidate, best_score, signal.id)
            
            # Log success
            logger.info(f"✅ SIGNAL GENERATED: {asset.value} {signal.signal_type.value}")
            logger.info(f"   Score: {best_score.total_score:.1f} ({best_score.grade.value})")
            logger.info(f"   Setup: {best_candidate.setup_type.value}")
            logger.info(f"   Bias: {mtf_bias.overall_bias.value} (align: {mtf_bias.alignment_score:.0f}%)")
            
            return ScanCycleResult(
                asset=asset,
                scan_duration_ms=(datetime.utcnow() - start_time).total_seconds() * 1000,
                mtf_bias=mtf_bias,
                candidates_found=len(candidates),
                candidates_rejected=rejected_count,
                signal_generated=True,
                signal_score=best_score.total_score,
                signal_grade=best_score.grade.value
            )
        
        return ScanCycleResult(
            asset=asset,
            scan_duration_ms=(datetime.utcnow() - start_time).total_seconds() * 1000,
            mtf_bias=mtf_bias,
            candidates_found=len(candidates),
            candidates_rejected=rejected_count,
            signal_generated=False,
            rejection_reasons=["Signal creation failed"]
        )
    
    def _get_session_name(self, session: Session) -> str:
        """Get session name for scoring"""
        session_names = {
            Session.LONDON: "London",
            Session.NEW_YORK: "New York",
            Session.OVERLAP: "London-NY Overlap",
            Session.OTHER: "Off-Hours"
        }
        return session_names.get(session, "Off-Hours")
    
    def _calculate_volatility_percentile(self, candles: List[dict]) -> float:
        """Calculate current volatility percentile"""
        if len(candles) < 50:
            return 50.0
        
        # Calculate ATRs
        atrs = []
        for i in range(1, len(candles)):
            tr = max(
                candles[i]['high'] - candles[i]['low'],
                abs(candles[i]['high'] - candles[i-1]['close']),
                abs(candles[i]['low'] - candles[i-1]['close'])
            )
            atrs.append(tr)
        
        if not atrs:
            return 50.0
        
        current_atr = sum(atrs[-14:]) / 14
        sorted_atrs = sorted(atrs[-100:])
        
        # Find percentile
        for i, atr in enumerate(sorted_atrs):
            if current_atr <= atr:
                return (i / len(sorted_atrs)) * 100
        return 100.0
    
    def _check_duplicate(self, asset: Asset, candidate: SetupCandidate) -> Tuple[bool, str]:
        """Check if signal would be a duplicate"""
        dp = self.config.duplicate_protection
        if not dp.enabled:
            return False, ""
        
        now = datetime.utcnow()
        
        # Check hourly limit
        hour_ago = now - timedelta(hours=1)
        self.signals_this_hour[asset] = [t for t in self.signals_this_hour[asset] if t > hour_ago]
        if len(self.signals_this_hour[asset]) >= dp.max_signals_per_hour:
            return True, f"Hourly limit reached ({dp.max_signals_per_hour}/hour)"
        
        # Check direction cooldown
        direction_key = (asset, candidate.direction)
        if direction_key in self.last_signal_by_direction:
            elapsed = (now - self.last_signal_by_direction[direction_key]).total_seconds() / 60
            if elapsed < dp.direction_cooldown_minutes:
                return True, f"Direction cooldown ({dp.direction_cooldown_minutes - elapsed:.0f}min remaining)"
        
        # Check price zone
        price_zone = dp.price_zone_pips_eurusd if asset == Asset.EURUSD else dp.price_zone_pips_xauusd
        pip_value = 0.0001 if asset == Asset.EURUSD else 1.0
        
        for recent in self.recent_signals[asset]:
            # Skip old signals
            if (now - recent.timestamp).total_seconds() > dp.same_setup_cooldown_minutes * 60:
                continue
            
            # Check if same direction
            if recent.direction != candidate.direction:
                continue
            
            # Check price zone
            price_diff = abs(candidate.entry_price - recent.entry_price)
            pips_diff = price_diff / pip_value
            
            if pips_diff < price_zone:
                return True, f"Within price zone ({pips_diff:.1f} pips from recent signal)"
        
        return False, ""
    
    def _record_signal(self, asset: Asset, candidate: SetupCandidate, 
                       score: SignalScore, signal_id: str):
        """Record signal for duplicate tracking"""
        now = datetime.utcnow()
        
        # Add to recent signals
        recent = RecentSignal(
            signal_id=signal_id,
            asset=asset,
            direction=candidate.direction,
            setup_type=candidate.setup_type.value,
            entry_price=candidate.entry_price,
            timestamp=now,
            score=score.total_score
        )
        self.recent_signals[asset].append(recent)
        
        # Cleanup old signals (keep last hour)
        hour_ago = now - timedelta(hours=2)
        self.recent_signals[asset] = [s for s in self.recent_signals[asset] if s.timestamp > hour_ago]
        
        # Update direction cooldown
        self.last_signal_by_direction[(asset, candidate.direction)] = now
        
        # Track hourly count
        self.signals_this_hour[asset].append(now)
        
        self.signal_count += 1
    
    async def _create_signal(self, asset: Asset, candidate: SetupCandidate,
                            score: SignalScore, mtf_bias: MultiTimeframeBias,
                            session: Session) -> Optional[Signal]:
        """Create and store signal with complete metadata"""
        try:
            # Get live quote for entry refinement
            provider = provider_manager.get_provider()
            live_quote = await provider.get_live_quote(asset) if provider else None
            
            # Calculate R:R
            if candidate.direction == "LONG":
                risk = candidate.entry_price - candidate.stop_loss
                reward = candidate.take_profit_1 - candidate.entry_price
            else:
                risk = candidate.stop_loss - candidate.entry_price
                reward = candidate.entry_price - candidate.take_profit_1
            
            rr_ratio = reward / risk if risk > 0 else 0
            
            # Build score breakdown
            score_breakdown = ScoreBreakdown(
                regime_quality=score.components[0].raw_score if len(score.components) > 0 else 0,
                structure_clarity=score.components[1].raw_score if len(score.components) > 1 else 0,
                trend_alignment=score.components[0].raw_score if len(score.components) > 0 else 0,
                entry_quality=score.components[2].raw_score if len(score.components) > 2 else 0,
                stop_quality=0,
                target_quality=0,
                session_quality=score.components[4].raw_score if len(score.components) > 4 else 0,
                volatility_quality=score.components[5].raw_score if len(score.components) > 5 else 0,
                prop_rule_safety=90,
                total=score.total_score
            )
            
            # Create signal
            signal = Signal(
                user_id="system",
                signal_type=SignalType.BUY if candidate.direction == "LONG" else SignalType.SELL,
                asset=asset,
                timeframe=Timeframe.M5,
                session=session,
                market_regime=self._bias_to_regime(mtf_bias.overall_bias),
                
                # Live data
                live_bid=live_quote.bid if live_quote else None,
                live_ask=live_quote.ask if live_quote else None,
                live_spread_pips=live_quote.spread_pips if live_quote else None,
                data_provider="Twelve Data",
                
                # Trade params
                entry_price=candidate.entry_price,
                stop_loss=candidate.stop_loss,
                take_profit_1=candidate.take_profit_1,
                take_profit_2=candidate.take_profit_2,
                risk_reward_ratio=rr_ratio,
                
                # Scoring
                confidence_score=score.total_score,
                score_breakdown=score_breakdown,
                
                # Explanation with full context
                explanation=self._build_explanation(candidate, score, mtf_bias),
                
                # Lifecycle
                lifecycle_stage=SignalLifecycle.CREATED,
                lifecycle_history=[{
                    "stage": SignalLifecycle.CREATED.value,
                    "timestamp": datetime.utcnow().isoformat()
                }],
                
                # Advanced metadata
                regime_strategy_priorities={
                    "htf_bias": mtf_bias.overall_bias.value,
                    "alignment_score": mtf_bias.alignment_score,
                    "h1_bias": mtf_bias.h1_bias.bias.value,
                    "m15_bias": mtf_bias.m15_bias.bias.value,
                    "m5_bias": mtf_bias.m5_bias.bias.value
                },
                strategy_weight_reason=score.components[0].reason if score.components else "",
                base_score_before_weighting=score.total_score
            )
            
            # Add custom fields for extended metadata
            signal_dict = signal.dict()
            signal_dict["setup_type"] = candidate.setup_type.value
            signal_dict["signal_grade"] = score.grade.value
            signal_dict["mtf_bias_direction"] = mtf_bias.trade_direction
            signal_dict["mtf_alignment_score"] = mtf_bias.alignment_score
            signal_dict["is_countertrend"] = mtf_bias.is_countertrend
            signal_dict["session_name"] = self._get_session_name(session)
            signal_dict["invalidation_price"] = candidate.invalidation_price
            signal_dict["score_breakdown_detailed"] = {
                comp.name: {
                    "raw": comp.raw_score,
                    "weighted": comp.weighted_score,
                    "reason": comp.reason
                } for comp in score.components
            }
            signal_dict["scanner_version"] = "v2_advanced"
            signal_dict["operational_profile"] = "Advanced MTF"
            
            # Store in database
            await self.db.signals.insert_one(signal_dict)
            
            return signal
            
        except Exception as e:
            logger.error(f"Failed to create signal: {e}", exc_info=True)
            return None
    
    def _bias_to_regime(self, bias: TimeframeBias) -> MarketRegime:
        """Convert MTF bias to market regime"""
        if bias in [TimeframeBias.STRONG_BULLISH, TimeframeBias.BULLISH]:
            return MarketRegime.BULLISH_TREND
        elif bias in [TimeframeBias.STRONG_BEARISH, TimeframeBias.BEARISH]:
            return MarketRegime.BEARISH_TREND
        elif bias in [TimeframeBias.WEAK_BULLISH, TimeframeBias.WEAK_BEARISH]:
            return MarketRegime.RANGE
        else:
            return MarketRegime.RANGE
    
    def _build_explanation(self, candidate: SetupCandidate, 
                          score: SignalScore, mtf_bias: MultiTimeframeBias) -> str:
        """Build detailed signal explanation"""
        lines = [
            f"📊 {candidate.setup_type.value.replace('_', ' ').title()} Setup",
            "",
            f"🎯 Entry: {candidate.entry_price:.5f}" if candidate.asset == Asset.EURUSD else f"🎯 Entry: {candidate.entry_price:.2f}",
            f"🛑 Stop Loss: {candidate.stop_loss:.5f}" if candidate.asset == Asset.EURUSD else f"🛑 Stop Loss: {candidate.stop_loss:.2f}",
            f"✅ Take Profit: {candidate.take_profit_1:.5f}" if candidate.asset == Asset.EURUSD else f"✅ Take Profit: {candidate.take_profit_1:.2f}",
            "",
            f"📈 MTF Bias: {mtf_bias.overall_bias.value.replace('_', ' ').title()}",
            f"   H1: {mtf_bias.h1_bias.bias.value} | M15: {mtf_bias.m15_bias.bias.value}",
            f"   Alignment: {mtf_bias.alignment_score:.0f}%",
            "",
            f"📊 Score: {score.total_score:.1f}/100 ({score.grade.value})",
            f"   {candidate.reason}"
        ]
        return "\n".join(lines)
    
    async def _send_notifications(self, asset: Asset, devices: List[Dict]):
        """Send push notifications for new signal"""
        # Get the latest signal
        signal = await self.db.signals.find_one(
            {"asset": asset.value, "scanner_version": "v2_advanced"},
            sort=[("created_at", -1)]
        )
        
        if not signal:
            return
        
        now = datetime.utcnow()
        active_tokens = []
        
        for device in devices:
            device_id = device.get("device_id", "")
            token = device.get("push_token")
            
            if not token:
                continue
            
            last_notif = self.notification_cooldown.get(device_id)
            if last_notif and (now - last_notif).total_seconds() < self.min_notification_interval:
                continue
            
            active_tokens.append((device_id, token))
        
        if not active_tokens:
            return
        
        tokens = [t[1] for t in active_tokens]
        
        # Format notification
        signal_type = signal.get("signal_type", "BUY")
        entry = signal.get("entry_price", 0)
        score = signal.get("confidence_score", 0)
        grade = signal.get("signal_grade", "")
        setup = signal.get("setup_type", "")
        
        title = f"🔔 {signal_type} Signal: {asset.value} ({grade})"
        
        if asset == Asset.EURUSD:
            body = f"Entry: {entry:.5f} | Score: {score:.0f}/100\n{setup.replace('_', ' ').title()}"
        else:
            body = f"Entry: {entry:.2f} | Score: {score:.0f}/100\n{setup.replace('_', ' ').title()}"
        
        # Send
        results = await push_service.send_to_all_devices(
            tokens=tokens,
            title=title,
            body=body,
            data={
                "type": "signal",
                "signalType": signal_type,
                "signalId": signal.get("id", ""),
                "asset": asset.value,
                "score": score,
                "grade": grade
            }
        )
        
        # Update cooldowns
        successful = 0
        for i, result in enumerate(results):
            if result.success:
                successful += 1
                self.notification_cooldown[active_tokens[i][0]] = now
        
        self.notification_count += successful
        logger.info(f"📢 Notifications sent: {successful}/{len(tokens)}")
    
    def get_stats(self) -> Dict[str, Any]:
        """Get scanner statistics"""
        uptime = 0
        if self.start_time:
            uptime = (datetime.utcnow() - self.start_time).total_seconds()
        
        return {
            "version": "v2_advanced",
            "is_running": self.is_running,
            "scan_count": self.scan_count,
            "signal_count": self.signal_count,
            "notification_count": self.notification_count,
            "uptime_seconds": int(uptime),
            "scan_interval": self.scan_interval,
            "config": {
                "score_threshold": self.config.min_score_threshold,
                "require_htf_alignment": self.config.require_htf_alignment,
                "allow_countertrend": self.config.allow_countertrend,
                "enabled_setups": [s.value for s, e in self.config.enabled_setups.items() if e]
            },
            "recent_signals": {
                asset.value: len(signals) for asset, signals in self.recent_signals.items()
            }
        }


# Global instance
advanced_scanner: Optional[AdvancedMarketScanner] = None


def init_advanced_scanner(db, config: ScannerConfig = None) -> AdvancedMarketScanner:
    """Initialize the advanced scanner"""
    global advanced_scanner
    advanced_scanner = AdvancedMarketScanner(db, config)
    return advanced_scanner
