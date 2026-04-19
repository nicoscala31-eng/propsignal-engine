"""
Pattern Signal Generator V1.0 - Orchestrator
=============================================

Orchestrates:
1. Market data fetching (reuses existing infrastructure)
2. Pattern detection via PatternEngine
3. Signal validation
4. Notification sending (reuses push_notification_service)
5. Outcome tracking via PatternTracker

Modes:
- LIVE: Sends real notifications
- FORWARD_TEST: Tracks patterns without sending notifications
- BACKTEST: Replay historical data

Integration:
- Uses market_data_cache for data
- Uses push_notification_service for notifications
- Uses pattern_engine for detection
- Uses pattern_tracker for tracking
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
from services.pattern_engine import pattern_engine, PatternDetection, Session
from services.pattern_tracker import pattern_tracker, TrackedPattern
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
        """Start the generator"""
        if self.is_running:
            logger.warning("Generator already running")
            return
        
        self.is_running = True
        self.start_time = datetime.utcnow()
        
        # Initialize tracker
        await pattern_tracker.initialize()
        
        # Start tracker loop
        await pattern_tracker.start()
        
        # Start scanner loop
        self._scanner_task = asyncio.create_task(self._run_scanner_loop())
        
        logger.info("="*60)
        logger.info("🚀 PATTERN SIGNAL GENERATOR V1.0 STARTED")
        logger.info(f"   Mode: {self.config.mode.value}")
        logger.info(f"   Assets: {self.config.allowed_assets}")
        logger.info(f"   Scan interval: {self.config.scan_interval}s")
        logger.info(f"   Duplicate window: {self.config.duplicate_window_minutes}m")
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
        
        await pattern_tracker.stop()
        
        logger.info("Pattern Signal Generator stopped")
    
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
        """Scan single asset for patterns"""
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
        
        # Scan for patterns
        patterns = pattern_engine.scan_all_patterns(
            symbol=asset.value,
            candles_h1=candles_h1,
            candles_m15=candles_m15,
            candles_m5=candles_m5,
            current_price=current_price
        )
        
        # Process detected patterns
        for pattern in patterns:
            await self._process_pattern(asset, pattern, session)
    
    # ==================== PATTERN PROCESSING ====================
    
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
    
    async def _send_notification(self, asset: Asset, pattern: PatternDetection):
        """Send push notification for pattern signal"""
        try:
            title = f"📊 {asset.value} {pattern.direction}"
            body = (
                f"{pattern.pattern_type.replace('_', ' ').title()}\n"
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
            
            logger.info(f"[PATTERN] Notification sent: {asset.value} {pattern.direction}")
            
        except Exception as e:
            logger.error(f"Error sending notification: {e}")
    
    # ==================== PRICE UPDATES ====================
    
    async def update_prices(self):
        """
        Update tracker with current prices.
        Called from market data engine.
        """
        for asset_str in self.config.allowed_assets:
            try:
                asset = Asset(asset_str)
                price_data = market_data_cache.get_price(asset)
                
                if price_data:
                    mid = price_data.mid if price_data else 0
                    if mid > 0:
                        await pattern_tracker.update_price(asset_str, mid)
            except Exception as e:
                logger.error(f"Error updating price for {asset_str}: {e}")
    
    # ==================== MODE CONTROL ====================
    
    def set_mode(self, mode: OperationMode):
        """Change operation mode"""
        old_mode = self.config.mode
        self.config.mode = mode
        logger.info(f"[PATTERN] Mode changed: {old_mode.value} -> {mode.value}")
    
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
            'version': 'Pattern Engine V1.0',
            'is_running': self.is_running,
            'mode': self.config.mode.value,
            'uptime_seconds': uptime,
            'scan_count': self.scan_count,
            'signal_count': self.signal_count,
            'config': {
                'scan_interval': self.config.scan_interval,
                'allowed_assets': self.config.allowed_assets,
                'duplicate_window_minutes': self.config.duplicate_window_minutes,
                'min_confidence': self.config.min_confidence
            },
            'statistics': self.stats,
            'tracker_status': pattern_tracker.get_status()
        }
    
    def get_performance(self) -> Dict:
        """Get performance statistics"""
        return pattern_tracker.get_all_performance()


# Global instance - starts in FORWARD_TEST mode by default
pattern_signal_generator = PatternSignalGenerator()
