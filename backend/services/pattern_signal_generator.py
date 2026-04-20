"""
Pattern Signal Generator V3.0 - Edge Validator
===============================================

IMPROVEMENTS OVER V2:
- Entry Validation with real-world constraints
- Rejected Pattern Tracking (simulates would-have-been outcomes)
- Market State Engine (CLOSED/LOW_VOL/TRANSITION/ACTIVE)
- Real Execution Simulation (spread, slippage, entry at candle close)
- Anti-Overfitting Check (compares last 20 vs previous 20 trades)
- Real Confidence (based on historical performance, not pattern detection)

Orchestrates:
1. Market data fetching (reuses existing infrastructure)
2. Pattern detection via PatternEngine
3. Entry validation via EntryValidator
4. Rejected pattern tracking (for simulation)
5. ALL PATTERNS logged for each trade
6. Notification sending (reuses push_notification_service)
7. Outcome tracking via PatternTrackerV2

Modes:
- LIVE: Sends real notifications
- FORWARD_TEST: Tracks patterns without sending notifications
- BACKTEST: Replay historical data
"""

import asyncio
import logging
from typing import Dict, List, Optional, Tuple
from dataclasses import dataclass, asdict
from datetime import datetime, timedelta
from enum import Enum
import json

from models import Asset, Timeframe
from services.market_data_cache import market_data_cache
from services.market_validator import market_validator
from services.pattern_engine import pattern_engine, PatternDetection, Session, PatternType
from services.pattern_tracker_v2 import pattern_tracker_v2, PATTERN_TYPES
from services.pattern_entry_validator import entry_validator, market_state_engine, MarketState
from services.push_notification_service import push_service

logger = logging.getLogger(__name__)


class OperationMode(Enum):
    LIVE = "live"                    # Send real notifications
    FORWARD_TEST = "forward_test"    # Track only, no notifications
    BACKTEST = "backtest"            # Historical replay


@dataclass
class GeneratorConfig:
    """Configuration for pattern signal generator"""
    mode: OperationMode = OperationMode.FORWARD_TEST
    scan_interval: int = 5  # seconds
    allowed_assets: List[str] = None
    duplicate_window_minutes: int = 15
    min_confidence: float = 60
    
    def __post_init__(self):
        if self.allowed_assets is None:
            self.allowed_assets = ["EURUSD", "XAUUSD"]


DEFAULT_CONFIG = GeneratorConfig()


class PatternSignalGenerator:
    """
    Pattern-based signal generator.
    
    Replaces the checklist-based approach with mathematical pattern detection.
    """
    
    def __init__(self, config: GeneratorConfig = None):
        self.config = config or DEFAULT_CONFIG
        
        # State
        self.is_running = False
        self.scan_count = 0
        self.signal_count = 0
        self.last_signals: Dict[str, datetime] = {}  # For duplicate detection
        
        # Tasks
        self._scanner_task: Optional[asyncio.Task] = None
        self._tracker_task: Optional[asyncio.Task] = None
        
        # Statistics
        self.stats = {
            'scans': 0,
            'patterns_detected': 0,
            'signals_sent': 0,
            'duplicates_blocked': 0,
            'confluence_failures': 0,
            'by_pattern_type': {},
            'by_session': {}
        }
        
        self.start_time: Optional[datetime] = None
        
        logger.info(f"Pattern Signal Generator initialized | Mode: {self.config.mode.value}")
    
    # ==================== LIFECYCLE ====================
    
    async def start(self):
        """Start the generator with V2 tracker and Entry Validator"""
        if self.is_running:
            logger.warning("Generator already running")
            return
        
        self.is_running = True
        self.start_time = datetime.utcnow()
        
        # Initialize Entry Validator
        await entry_validator.initialize()
        
        # Initialize V2 tracker
        await pattern_tracker_v2.initialize()
        
        # Start V2 tracker loop
        await pattern_tracker_v2.start()
        
        # Start scanner loop
        self._scanner_task = asyncio.create_task(self._run_scanner_loop())
        
        logger.info("="*60)
        logger.info("🚀 PATTERN SIGNAL GENERATOR V3.0 STARTED")
        logger.info(f"   Mode: {self.config.mode.value}")
        logger.info(f"   Assets: {self.config.allowed_assets}")
        logger.info(f"   Scan interval: {self.config.scan_interval}s")
        logger.info("   📊 TRACKING: ALL patterns simultaneously")
        logger.info("   📈 ANALYSIS: Per-pattern + Combinations + Pattern Count")
        logger.info("   ✅ ENTRY VALIDATION: Enabled")
        logger.info("   🔄 REJECTED SIMULATION: Enabled")
        logger.info("   📉 ANTI-OVERFITTING: Enabled")
        if self.config.mode == OperationMode.FORWARD_TEST:
            logger.info("   ⚠️ FORWARD TEST MODE - No notifications will be sent")
        logger.info("="*60)
    
    async def stop(self):
        """Stop the generator"""
        self.is_running = False
        
        if self._scanner_task:
            self._scanner_task.cancel()
            try:
                await self._scanner_task
            except asyncio.CancelledError:
                pass
        
        await pattern_tracker_v2.stop()
        
        logger.info("Pattern Signal Generator V2.0 stopped")
    
    # ==================== SCANNER LOOP ====================
    
    async def _run_scanner_loop(self):
        """Main scanner loop"""
        logger.info("Scanner loop started")
        
        while self.is_running:
            try:
                await self._scan_cycle()
                await asyncio.sleep(self.config.scan_interval)
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"Scanner error: {e}")
                await asyncio.sleep(5)
    
    async def _scan_cycle(self):
        """Single scan cycle"""
        self.scan_count += 1
        self.stats['scans'] += 1
        
        # Check if market is open
        if not market_validator.is_forex_open():
            if self.scan_count % 60 == 0:  # Log every 5 minutes
                logger.info("[PATTERN] Market closed, skipping scan")
            return
        
        # Check session
        session = pattern_engine.get_current_session()
        if not pattern_engine.is_session_valid(session):
            if self.scan_count % 60 == 0:
                logger.debug(f"[PATTERN] Session off ({session.value}), skipping")
            return
        
        # Scan each asset
        for asset_str in self.config.allowed_assets:
            try:
                asset = Asset(asset_str)
                await self._scan_asset(asset, session)
            except Exception as e:
                logger.error(f"Error scanning {asset_str}: {e}")
    
    async def _scan_asset(self, asset: Asset, session: Session):
        """Scan single asset for ALL patterns"""
        # Get candle data
        candles_h1 = market_data_cache.get_candles(asset, Timeframe.H1)
        candles_m15 = market_data_cache.get_candles(asset, Timeframe.M15)
        candles_m5 = market_data_cache.get_candles(asset, Timeframe.M5)
        
        # Validate data
        if not candles_h1 or len(candles_h1) < 150:
            return
        if not candles_m15 or len(candles_m15) < 150:
            return
        if not candles_m5 or len(candles_m5) < 150:
            return
        
        # Get current price
        price_data = market_data_cache.get_price(asset)
        if not price_data:
            return
        
        current_price = price_data.mid if price_data else 0
        if current_price <= 0:
            return
        
        # Build context for pattern detection
        context = pattern_engine.build_market_context(
            symbol=asset.value,
            candles_h1=candles_h1,
            candles_m15=candles_m15,
            candles_m5=candles_m5,
            current_price=current_price
        )
        
        # Scan for ALL patterns
        detected_patterns = pattern_engine.scan_all_patterns(
            symbol=asset.value,
            candles_h1=candles_h1,
            candles_m15=candles_m15,
            candles_m5=candles_m5,
            current_price=current_price
        )
        
        if not detected_patterns:
            return
        
        # Collect ALL active patterns
        all_pattern_flags = {pt: False for pt in PATTERN_TYPES}
        primary_pattern = None
        best_confidence = 0
        best_pattern = None
        
        for pattern in detected_patterns:
            pt = pattern.pattern_type
            all_pattern_flags[pt] = True
            
            # Track best pattern by confidence
            if pattern.confidence > best_confidence:
                best_confidence = pattern.confidence
                best_pattern = pattern
                primary_pattern = pt
        
        # Process the best pattern (but log ALL active patterns)
        if best_pattern:
            await self._process_pattern_v2(
                asset=asset,
                pattern=best_pattern,
                session=session,
                all_patterns=all_pattern_flags,
                primary_pattern=primary_pattern,
                context=context
            )
    
    # ==================== PATTERN PROCESSING V3 (with Entry Validation) ====================
    
    async def _process_pattern_v2(self, asset: Asset, pattern: PatternDetection, 
                                   session: Session, all_patterns: Dict[str, bool],
                                   primary_pattern: str, context):
        """
        Process detected pattern with Entry Validation and FULL pattern logging.
        
        V3 Flow:
        1. Detect patterns (done by caller)
        2. VALIDATE ENTRY (new)
        3. If rejected -> track as rejected (but simulate outcome)
        4. If valid -> track and optionally send notification
        
        Args:
            all_patterns: Dict of ALL patterns {pattern_name: active_bool}
            primary_pattern: The main trigger pattern
        """
        self.stats['patterns_detected'] += 1
        
        # Count active patterns
        active_count = sum(1 for v in all_patterns.values() if v)
        active_names = [k for k, v in all_patterns.items() if v]
        
        # Track pattern types
        for pt, active in all_patterns.items():
            if active:
                if pt not in self.stats['by_pattern_type']:
                    self.stats['by_pattern_type'][pt] = 0
                self.stats['by_pattern_type'][pt] += 1
        
        # Check for duplicates
        dup_key = f"{asset.value}_{pattern.direction}_{'+'.join(sorted(active_names))}"
        if self._is_duplicate(dup_key):
            self.stats['duplicates_blocked'] += 1
            logger.debug(f"[PATTERN V3] Duplicate blocked: {dup_key}")
            return
        
        # Mark as not duplicate
        self.last_signals[dup_key] = datetime.utcnow()
        
        # Get current spread
        price_data = market_data_cache.get_price(asset)
        spread = price_data.spread if price_data else 0.00010  # Default 1 pip
        
        # Get M5 candles for entry validation
        candles_m5 = market_data_cache.get_candles(asset, Timeframe.M5) or []
        
        # ========== ENTRY VALIDATION (NEW in V3) ==========
        validation = entry_validator.validate_entry(
            pattern_type=primary_pattern,
            direction=pattern.direction,
            entry_price=pattern.entry_price,
            stop_loss=pattern.stop_loss,
            take_profit=pattern.take_profit,
            confidence=pattern.confidence,
            candles=candles_m5,
            spread=spread,
            atr=context.atr_m5,
            symbol=asset.value
        )
        
        # Track validation stats
        if 'entry_validations' not in self.stats:
            self.stats['entry_validations'] = {'valid': 0, 'rejected': 0, 'by_reason': {}}
        
        if not validation.is_valid:
            # ========== REJECTED ENTRY ==========
            self.stats['entry_validations']['rejected'] += 1
            
            # Track rejection reason
            reason = validation.reason
            if reason not in self.stats['entry_validations']['by_reason']:
                self.stats['entry_validations']['by_reason'][reason] = 0
            self.stats['entry_validations']['by_reason'][reason] += 1
            
            # Track rejected pattern (for simulation)
            await entry_validator.track_rejected_pattern(
                pattern_type=primary_pattern,
                direction=pattern.direction,
                symbol=asset.value,
                entry_price=pattern.entry_price,
                stop_loss=pattern.stop_loss,
                take_profit=pattern.take_profit,
                confidence=pattern.confidence,
                rejection_reason=reason,
                market_state=validation.market_state,
                atr=context.atr_m5,
                spread=spread
            )
            
            logger.info(f"[PATTERN V3] ❌ Entry REJECTED: {asset.value} {pattern.direction} | "
                       f"Reason: {reason} | Real Confidence: {validation.real_confidence:.1f}")
            return
        
        # ========== VALID ENTRY ==========
        self.stats['entry_validations']['valid'] += 1
        
        # Use ADJUSTED levels (with slippage/spread)
        executed = self.config.mode == OperationMode.LIVE
        
        trade_id = await pattern_tracker_v2.track_trade(
            symbol=asset.value,
            direction=pattern.direction,
            patterns=all_patterns,  # ALL patterns logged!
            primary_pattern=primary_pattern,
            entry_price=validation.adjusted_entry,  # Use adjusted entry
            stop_loss=validation.adjusted_sl,       # Use adjusted SL
            take_profit=validation.adjusted_tp,     # Use adjusted TP
            atr=context.atr_m5,
            session=session.value,
            trend_h1=context.trend_h1.direction.value,
            trend_m15=context.trend_m15.direction.value,
            confidence=validation.real_confidence,  # Use REAL confidence
            executed=executed
        )
        
        self.signal_count += 1
        
        # Update pattern performance history
        entry_validator.update_pattern_performance(
            pattern_type=primary_pattern,
            won=False,  # Will be updated when trade closes
            final_r=0   # Will be updated when trade closes
        )
        
        # Send notification if LIVE mode
        if self.config.mode == OperationMode.LIVE:
            await self._send_notification(asset, pattern, active_names, validation)
            self.stats['signals_sent'] += 1
        
        logger.info(f"[PATTERN V3] ✅ Entry VALID: {asset.value} {pattern.direction} | "
                   f"Patterns: {active_names} ({active_count} active) | "
                   f"Real Confidence: {validation.real_confidence:.1f} | "
                   f"Real R:R: {validation.real_rr:.2f} | "
                   f"Mode: {self.config.mode.value}")
    
    # Keep old method for compatibility
    async def _process_pattern(self, asset: Asset, pattern: PatternDetection, session: Session):
        """Process a detected pattern"""
        self.stats['patterns_detected'] += 1
        
        # Track pattern type
        pt = pattern.pattern_type
        if pt not in self.stats['by_pattern_type']:
            self.stats['by_pattern_type'][pt] = 0
        self.stats['by_pattern_type'][pt] += 1
        
        # Check for duplicates
        dup_key = f"{asset.value}_{pattern.direction}_{pattern.pattern_type}"
        if self._is_duplicate(dup_key):
            self.stats['duplicates_blocked'] += 1
            logger.debug(f"[PATTERN] Duplicate blocked: {dup_key}")
            return
        
        # Check minimum confidence
        if pattern.confidence < self.config.min_confidence:
            logger.debug(f"[PATTERN] Low confidence: {pattern.confidence}")
            return
        
        # Build market context for tracker
        candles_h1 = market_data_cache.get_candles(asset, Timeframe.H1)
        candles_m15 = market_data_cache.get_candles(asset, Timeframe.M15)
        candles_m5 = market_data_cache.get_candles(asset, Timeframe.M5)
        
        context = pattern_engine.build_market_context(
            symbol=asset.value,
            candles_h1=candles_h1 or [],
            candles_m15=candles_m15 or [],
            candles_m5=candles_m5 or [],
            current_price=pattern.entry_price
        )
        
        # Mark as not duplicate
        self.last_signals[dup_key] = datetime.utcnow()
        
        # Track the pattern
        executed = self.config.mode == OperationMode.LIVE
        
        pattern_id = await pattern_tracker.track_pattern(
            symbol=asset.value,
            pattern_type=pattern.pattern_type,
            direction=pattern.direction,
            entry_price=pattern.entry_price,
            stop_loss=pattern.stop_loss,
            take_profit=pattern.take_profit,
            atr=context.atr_m5,
            session=session.value,
            trend_h1=context.trend_h1.direction.value,
            trend_m15=context.trend_m15.direction.value,
            confidence=pattern.confidence,
            executed=executed
        )
        
        self.signal_count += 1
        
        # Send notification if LIVE mode
        if self.config.mode == OperationMode.LIVE:
            await self._send_notification(asset, pattern)
            self.stats['signals_sent'] += 1
        
        logger.info(f"[PATTERN] ✅ {asset.value} {pattern.direction} | {pattern.pattern_type} | "
                   f"Confidence: {pattern.confidence:.1f} | R:R: {pattern.risk_reward:.2f} | "
                   f"Mode: {self.config.mode.value}")
    
    def _is_duplicate(self, key: str) -> bool:
        """Check if signal is duplicate within window"""
        if key not in self.last_signals:
            return False
        
        last_time = self.last_signals[key]
        window = timedelta(minutes=self.config.duplicate_window_minutes)
        
        return datetime.utcnow() - last_time < window
    
    # ==================== NOTIFICATIONS ====================
    
    async def _send_notification(self, asset: Asset, pattern: PatternDetection, 
                                  active_patterns: List[str] = None,
                                  validation = None):
        """Send push notification for pattern signal with all active patterns and validation data"""
        try:
            active_str = ", ".join(active_patterns) if active_patterns else pattern.pattern_type
            
            # Use validation data if available
            if validation:
                title = f"📊 {asset.value} {pattern.direction}"
                body = (
                    f"Patterns: {active_str}\n"
                    f"Entry: {validation.adjusted_entry:.5f}\n"
                    f"SL: {validation.adjusted_sl:.5f}\n"
                    f"TP: {validation.adjusted_tp:.5f}\n"
                    f"R:R: {validation.real_rr:.2f}\n"
                    f"Confidence: {validation.real_confidence:.0f}%"
                )
                
                data = {
                    'type': 'PATTERN_SIGNAL',
                    'symbol': asset.value,
                    'direction': pattern.direction,
                    'pattern_type': pattern.pattern_type,
                    'active_patterns': ",".join(active_patterns) if active_patterns else pattern.pattern_type,
                    'pattern_count': str(len(active_patterns)) if active_patterns else "1",
                    'entry': str(validation.adjusted_entry),
                    'sl': str(validation.adjusted_sl),
                    'tp': str(validation.adjusted_tp),
                    'rr': str(validation.real_rr),
                    'confidence': str(validation.real_confidence),
                    'market_state': validation.market_state
                }
            else:
                title = f"📊 {asset.value} {pattern.direction}"
                body = (
                    f"Patterns: {active_str}\n"
                    f"Entry: {pattern.entry_price:.5f}\n"
                    f"SL: {pattern.stop_loss:.5f}\n"
                    f"TP: {pattern.take_profit:.5f}\n"
                    f"R:R: {pattern.risk_reward:.2f}"
                )
                
                data = {
                    'type': 'PATTERN_SIGNAL',
                    'symbol': asset.value,
                    'direction': pattern.direction,
                    'pattern_type': pattern.pattern_type,
                    'active_patterns': ",".join(active_patterns) if active_patterns else pattern.pattern_type,
                    'pattern_count': str(len(active_patterns)) if active_patterns else "1",
                    'entry': str(pattern.entry_price),
                    'sl': str(pattern.stop_loss),
                    'tp': str(pattern.take_profit),
                    'rr': str(pattern.risk_reward),
                    'confidence': str(pattern.confidence)
                }
            
            await push_service.send_to_all(
                title=title,
                body=body,
                data=data
            )
            
            logger.info(f"[PATTERN V3] Notification sent: {asset.value} {pattern.direction}")
            
        except Exception as e:
            logger.error(f"Error sending notification: {e}")
    
    # ==================== PRICE UPDATES ====================
    
    async def update_prices(self):
        """
        Update tracker V2 and rejected patterns with current prices.
        """
        for asset_str in self.config.allowed_assets:
            try:
                asset = Asset(asset_str)
                price_data = market_data_cache.get_price(asset)
                
                if price_data:
                    mid = price_data.mid if price_data else 0
                    if mid > 0:
                        # Update tracked trades
                        await pattern_tracker_v2.update_price(asset_str, mid)
                        # Update rejected pattern simulations
                        await entry_validator.update_prices_for_rejections(asset_str, mid)
            except Exception as e:
                logger.error(f"Error updating price for {asset_str}: {e}")
    
    # ==================== MODE CONTROL ====================
    
    def set_mode(self, mode: OperationMode):
        """Change operation mode"""
        old_mode = self.config.mode
        self.config.mode = mode
        logger.info(f"[PATTERN V2] Mode changed: {old_mode.value} -> {mode.value}")
    
    def enable_live_mode(self):
        """Enable live notifications"""
        self.set_mode(OperationMode.LIVE)
    
    def enable_forward_test(self):
        """Enable forward test mode (no notifications)"""
        self.set_mode(OperationMode.FORWARD_TEST)
    
    # ==================== STATUS & STATS ====================
    
    def get_status(self) -> Dict:
        """Get generator status"""
        uptime = 0
        if self.start_time:
            uptime = (datetime.utcnow() - self.start_time).total_seconds()
        
        return {
            'version': 'Pattern Engine V3.0 (Edge Validator)',
            'is_running': self.is_running,
            'mode': self.config.mode.value,
            'uptime_seconds': uptime,
            'scan_count': self.scan_count,
            'signal_count': self.signal_count,
            'market_state': market_state_engine.current_state.value,
            'config': {
                'scan_interval': self.config.scan_interval,
                'allowed_assets': self.config.allowed_assets,
                'duplicate_window_minutes': self.config.duplicate_window_minutes,
                'min_confidence': self.config.min_confidence
            },
            'statistics': self.stats,
            'tracker_status': pattern_tracker_v2.get_status(),
            'entry_validation': {
                'enabled': True,
                'rejected_patterns': len(entry_validator.rejected_patterns),
                'pattern_history': len(entry_validator.pattern_history)
            }
        }
    
    def get_performance(self) -> Dict:
        """
        Get FULL performance statistics from V3 engine.
        
        Includes:
        - Performance by individual pattern
        - Performance by pattern combination
        - Performance by pattern count (1, 2, 3+)
        - Rejected pattern analysis
        - Anti-overfitting status
        - Recommendations
        """
        tracker_analysis = pattern_tracker_v2.get_full_analysis()
        validator_report = entry_validator.get_full_validation_report()
        
        return {
            'version': '3.0',
            'report_generated': datetime.utcnow().isoformat(),
            'tracker_analysis': tracker_analysis,
            'entry_validation': validator_report,
            'note': 'EDGE VALIDATOR - Compares executed vs rejected pattern performance'
        }


# Global instance - starts in FORWARD_TEST mode by default
pattern_signal_generator = PatternSignalGenerator()
