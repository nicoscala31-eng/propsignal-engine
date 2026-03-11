"""Backend Market Scanner - Production-grade automatic signal generation and push notifications"""
import asyncio
import logging
import json
from typing import Dict, Set, Optional, List, Any
from datetime import datetime, timedelta
from dataclasses import dataclass, field
from pathlib import Path

from models import (
    Asset, SignalType, Signal, PropProfile, AccountSettings, 
    MarketRegime, SignalOutcome, SignalLifecycle
)
from services.signal_orchestrator import enhanced_signal_orchestrator
from services.push_notification_service import push_service
from services.macro_news_service import macro_news_service
from providers.provider_manager import provider_manager

logger = logging.getLogger(__name__)

# State persistence file
STATE_FILE = Path("/app/backend/scanner_state.json")


@dataclass
class ScanResult:
    """Result of a market scan"""
    asset: Asset
    signal_type: SignalType
    signal_id: Optional[str] = None
    confidence: float = 0.0
    regime: Optional[MarketRegime] = None
    notification_sent: bool = False
    pre_alert_sent: bool = False
    news_risk: bool = False
    news_event: Optional[str] = None


@dataclass
class OperationalProfile:
    """Trading operational profile"""
    name: str
    min_confidence: float
    min_rr_ratio: float
    signal_frequency_minutes: int
    regime_filter: List[MarketRegime]
    
    AGGRESSIVE = None
    DEFENSIVE = None
    PROP_FIRM_SAFE = None


# Initialize profiles
OperationalProfile.AGGRESSIVE = OperationalProfile(
    name="Aggressive",
    min_confidence=70.0,
    min_rr_ratio=1.2,
    signal_frequency_minutes=10,
    regime_filter=[
        MarketRegime.BULLISH_TREND, MarketRegime.BEARISH_TREND,
        MarketRegime.BREAKOUT_EXPANSION, MarketRegime.RANGE
    ]
)

OperationalProfile.DEFENSIVE = OperationalProfile(
    name="Defensive",
    min_confidence=82.0,
    min_rr_ratio=2.0,
    signal_frequency_minutes=60,
    regime_filter=[
        MarketRegime.BULLISH_TREND, MarketRegime.BEARISH_TREND
    ]
)

OperationalProfile.PROP_FIRM_SAFE = OperationalProfile(
    name="Prop Firm Safe",
    min_confidence=80.0,
    min_rr_ratio=1.8,
    signal_frequency_minutes=30,
    regime_filter=[
        MarketRegime.BULLISH_TREND, MarketRegime.BEARISH_TREND,
        MarketRegime.RANGE
    ]
)


class MarketScanner:
    """
    Production-grade backend market scanner
    
    Features:
    - Periodic market scanning (every 30 seconds)
    - Automatic signal generation
    - Push notification delivery with retry
    - Signal deduplication
    - Pre-signal alerts
    - News risk detection (warnings, not blocking)
    - Operational profiles
    - State persistence
    - Automatic recovery
    - Invalid token removal
    """
    
    def __init__(self, db):
        self.db = db
        self.is_running = False
        self.scan_interval = 30
        self.scanner_task: Optional[asyncio.Task] = None
        
        # Signal deduplication
        self.last_signal_times: Dict[Asset, datetime] = {}
        self.sent_signal_ids: Set[str] = set()
        self.notified_signal_ids: Set[str] = set()
        
        # Anti-spam cooldowns
        self.notification_cooldown: Dict[str, datetime] = {}  # device_id -> last_notification_time
        self.min_notification_interval = 60  # seconds between notifications per device
        
        # Pre-alert tracking
        self.pre_alert_sent: Dict[Asset, datetime] = {}
        self.pre_alert_cooldown = 300
        
        # Profile
        self.active_profile = OperationalProfile.PROP_FIRM_SAFE
        
        # Statistics
        self.scan_count = 0
        self.signal_count = 0
        self.notification_count = 0
        self.failed_notifications = 0
        self.invalid_tokens_removed = 0
        self.start_time: Optional[datetime] = None
        self.last_scan_time: Optional[datetime] = None  # Track last scan timestamp
        
        # Error tracking for recovery
        self.consecutive_errors = 0
        self.max_consecutive_errors = 5
        
        # Load persisted state
        self._load_state()
    
    def _load_state(self):
        """Load persisted scanner state"""
        try:
            if STATE_FILE.exists():
                with open(STATE_FILE, 'r') as f:
                    state = json.load(f)
                
                self.scan_count = state.get("scan_count", 0)
                self.signal_count = state.get("signal_count", 0)
                self.notification_count = state.get("notification_count", 0)
                
                profile_name = state.get("active_profile", "prop_firm_safe")
                self.set_profile(profile_name)
                
                # Restore sent signal IDs (last 1000)
                self.sent_signal_ids = set(state.get("sent_signal_ids", [])[-1000:])
                
                logger.info(f"📂 Loaded scanner state: {self.scan_count} scans, {self.signal_count} signals")
        except Exception as e:
            logger.warning(f"Could not load scanner state: {e}")
    
    def _save_state(self):
        """Persist scanner state"""
        try:
            state = {
                "scan_count": self.scan_count,
                "signal_count": self.signal_count,
                "notification_count": self.notification_count,
                "active_profile": self.active_profile.name.lower().replace(" ", "_"),
                "sent_signal_ids": list(self.sent_signal_ids)[-1000:],
                "last_save": datetime.utcnow().isoformat()
            }
            
            with open(STATE_FILE, 'w') as f:
                json.dump(state, f)
        except Exception as e:
            logger.warning(f"Could not save scanner state: {e}")
    
    async def start(self):
        """Start the market scanner"""
        if self.is_running:
            logger.warning("Market scanner already running")
            return
        
        self.is_running = True
        self.start_time = datetime.utcnow()
        logger.info("🚀 Market Scanner started")
        logger.info(f"📊 Active profile: {self.active_profile.name}")
        logger.info(f"⏱️  Scan interval: {self.scan_interval}s")
        
        # Create scanner task with error recovery
        self.scanner_task = asyncio.create_task(self._run_scanner_loop())
    
    async def stop(self):
        """Stop the market scanner"""
        self.is_running = False
        
        if self.scanner_task:
            self.scanner_task.cancel()
            try:
                await self.scanner_task
            except asyncio.CancelledError:
                pass
        
        self._save_state()
        logger.info("🛑 Market Scanner stopped")
    
    async def _run_scanner_loop(self):
        """Main scanner loop with error recovery"""
        while self.is_running:
            try:
                await self._scan_markets()
                self.consecutive_errors = 0
                
                # Periodic state save
                if self.scan_count % 10 == 0:
                    self._save_state()
                    
            except Exception as e:
                self.consecutive_errors += 1
                logger.error(f"Scanner error ({self.consecutive_errors}/{self.max_consecutive_errors}): {e}", exc_info=True)
                
                if self.consecutive_errors >= self.max_consecutive_errors:
                    logger.critical("🚨 Max consecutive errors reached, restarting scanner...")
                    await asyncio.sleep(30)
                    self.consecutive_errors = 0
            
            await asyncio.sleep(self.scan_interval)
    
    async def _scan_markets(self):
        """Scan all markets and generate signals"""
        self.scan_count += 1
        self.last_scan_time = datetime.utcnow()  # Update last scan timestamp
        
        # Get all registered devices
        devices = await self.db.devices.find({"is_active": True}).to_list(1000)
        
        # Get default profile and settings
        default_profile = await self._get_default_profile()
        default_settings = await self._get_default_settings()
        
        for asset in [Asset.EURUSD, Asset.XAUUSD]:
            try:
                result = await self._scan_asset(asset, default_profile, default_settings)
                
                # Send notifications for trade signals
                if result.signal_type != SignalType.NEXT and devices:
                    await self._send_signal_notifications(result, devices)
                
                # Check for pre-signal alerts
                elif result.regime and devices:
                    await self._check_pre_signal_alerts(result, devices)
                    
            except Exception as e:
                logger.error(f"Error scanning {asset.value}: {e}")
    
    async def _scan_asset(
        self, 
        asset: Asset, 
        profile: PropProfile,
        settings: AccountSettings
    ) -> ScanResult:
        """Scan a single asset for signals with news risk detection"""
        
        # Check news risk FIRST (but don't block)
        news_info = await macro_news_service.check_news_risk(asset, minutes_window=30)
        has_news_risk = news_info.get("has_risk", False)
        news_event = news_info.get("event_name")
        minutes_to_news = news_info.get("minutes_to_event")
        
        # Generate signal
        signal = await enhanced_signal_orchestrator.generate_signal(
            user_id="system",
            asset=asset,
            prop_profile=profile,
            account_settings=settings,
            consecutive_losses=0
        )
        
        result = ScanResult(
            asset=asset,
            signal_type=signal.signal_type,
            signal_id=signal.id,
            confidence=signal.confidence_score,
            regime=signal.market_regime,
            news_risk=has_news_risk,
            news_event=news_event
        )
        
        if signal.signal_type != SignalType.NEXT:
            # Check deduplication
            if self._is_duplicate_signal(asset, signal):
                logger.debug(f"Duplicate signal for {asset.value}, skipping")
                return result
            
            # Apply profile filter
            if not self._passes_profile_filter(signal):
                logger.debug(f"Signal for {asset.value} filtered by profile")
                return result
            
            # Add news risk to signal (DO NOT BLOCK)
            signal_dict = signal.dict()
            signal_dict["news_risk"] = has_news_risk
            signal_dict["news_event"] = news_event
            signal_dict["minutes_to_news"] = minutes_to_news
            signal_dict["operational_profile"] = self.active_profile.name
            signal_dict["lifecycle_stage"] = SignalLifecycle.CREATED.value
            signal_dict["lifecycle_history"] = [{
                "stage": SignalLifecycle.CREATED.value,
                "timestamp": datetime.utcnow().isoformat()
            }]
            
            # Store signal
            await self.db.signals.insert_one(signal_dict)
            self.signal_count += 1
            
            self.last_signal_times[asset] = datetime.utcnow()
            self.sent_signal_ids.add(signal.id)
            
            news_warning = f" ⚠️ NEWS RISK: {news_event}" if has_news_risk else ""
            logger.info(f"✅ {signal.signal_type.value} signal: {asset.value}{news_warning}")
        
        return result
    
    def _is_duplicate_signal(self, asset: Asset, signal: Signal) -> bool:
        """Check if signal is a duplicate"""
        if signal.id in self.sent_signal_ids:
            return True
        
        if asset in self.last_signal_times:
            elapsed = (datetime.utcnow() - self.last_signal_times[asset]).total_seconds()
            min_interval = self.active_profile.signal_frequency_minutes * 60
            if elapsed < min_interval:
                return True
        
        return False
    
    def _passes_profile_filter(self, signal: Signal) -> bool:
        """Check if signal passes operational profile filter"""
        profile = self.active_profile
        
        if signal.confidence_score < profile.min_confidence:
            return False
        
        if signal.risk_reward_ratio and signal.risk_reward_ratio < profile.min_rr_ratio:
            return False
        
        if signal.market_regime not in profile.regime_filter:
            return False
        
        return True
    
    async def _send_signal_notifications(self, result: ScanResult, devices: List[Dict]):
        """Send push notifications with retry and invalid token handling"""
        if not result.signal_id:
            return
        
        # Check if already notified
        if result.signal_id in self.notified_signal_ids:
            return
        
        signal_data = await self.db.signals.find_one({"id": result.signal_id})
        if not signal_data:
            return
        
        # Filter devices by cooldown
        now = datetime.utcnow()
        active_tokens = []
        for device in devices:
            device_id = device.get("device_id", "")
            token = device.get("push_token")
            
            if not token:
                continue
            
            # Check cooldown
            last_notif = self.notification_cooldown.get(device_id)
            if last_notif and (now - last_notif).total_seconds() < self.min_notification_interval:
                continue
            
            active_tokens.append((device_id, token))
        
        if not active_tokens:
            return
        
        tokens = [t[1] for t in active_tokens]
        
        # Format price
        entry_price = signal_data.get("entry_price", 0)
        asset = result.asset.value
        price_str = f"{entry_price:.5f}" if asset == "EURUSD" else f"{entry_price:.2f}"
        
        # Build notification
        title = f"🔔 {result.signal_type.value} Signal: {asset}"
        body = f"Entry: {price_str} | Confidence: {result.confidence:.0f}%"
        
        if result.news_risk:
            title += " ⚠️"
            body += f"\n⚠️ High News Risk: {result.news_event}"
        
        data = {
            "type": "signal",
            "signalType": result.signal_type.value,
            "signalId": result.signal_id,
            "asset": asset,
            "entry": entry_price,
            "confidence": result.confidence,
            "newsRisk": result.news_risk,
            "newsEvent": result.news_event
        }
        
        # Send with retry
        results = await push_service.send_to_all_devices(
            tokens=tokens,
            title=title,
            body=body,
            data=data
        )
        
        # Process results
        successful = 0
        for i, push_result in enumerate(results):
            device_id = active_tokens[i][0]
            
            if push_result.success:
                successful += 1
                self.notification_cooldown[device_id] = now
            else:
                self.failed_notifications += 1
                
                # Handle invalid tokens
                if "DeviceNotRegistered" in str(push_result.error) or "InvalidCredentials" in str(push_result.error):
                    await self._remove_invalid_token(device_id)
        
        self.notification_count += successful
        self.notified_signal_ids.add(result.signal_id)
        
        # Update signal notification status
        await self.db.signals.update_one(
            {"id": result.signal_id},
            {"$set": {
                "notification_sent": True,
                "notification_sent_at": now
            }}
        )
        
        logger.info(f"📢 Notifications sent: {successful}/{len(tokens)}")
    
    async def _remove_invalid_token(self, device_id: str):
        """Remove invalid push token from database"""
        await self.db.devices.update_one(
            {"device_id": device_id},
            {"$set": {"is_active": False, "deactivated_at": datetime.utcnow()}}
        )
        self.invalid_tokens_removed += 1
        logger.warning(f"🗑️ Removed invalid token for device: {device_id[:20]}...")
    
    async def _check_pre_signal_alerts(self, result: ScanResult, devices: List[Dict]):
        """Check and send pre-signal alerts"""
        asset = result.asset
        regime = result.regime
        
        if asset in self.pre_alert_sent:
            elapsed = (datetime.utcnow() - self.pre_alert_sent[asset]).total_seconds()
            if elapsed < self.pre_alert_cooldown:
                return
        
        alert_message = None
        alert_type = None
        
        if regime == MarketRegime.COMPRESSION:
            alert_message = f"📊 {asset.value}: Market compression - potential breakout forming"
            alert_type = "compression"
        elif regime == MarketRegime.BREAKOUT_EXPANSION:
            alert_message = f"🚀 {asset.value}: Breakout in progress - setup may be forming"
            alert_type = "breakout"
        
        if alert_message:
            tokens = [d["push_token"] for d in devices if d.get("push_token")]
            if tokens:
                await push_service.send_pre_signal_alert(
                    tokens=tokens,
                    alert_type=alert_type,
                    asset=asset.value,
                    message=alert_message
                )
                self.pre_alert_sent[asset] = datetime.utcnow()
    
    async def _get_default_profile(self) -> PropProfile:
        """Get default prop profile"""
        profile_data = await self.db.prop_profiles.find_one({"user_id": "system"})
        
        if not profile_data:
            profile = PropProfile(
                user_id="system",
                name="System Default",
                firm_name="PropSignal",
                initial_balance=100000,
                current_balance=100000,
                current_equity=100000,
                daily_drawdown_percent=5.0,
                max_drawdown_percent=10.0
            )
            await self.db.prop_profiles.insert_one(profile.dict())
            return profile
        
        return PropProfile(**profile_data)
    
    async def _get_default_settings(self) -> AccountSettings:
        """Get default account settings"""
        settings_data = await self.db.account_settings.find_one({"user_id": "system"})
        
        if not settings_data:
            settings = AccountSettings(
                user_id="system",
                account_size=100000,
                risk_mode="BALANCED"
            )
            await self.db.account_settings.insert_one(settings.dict())
            return settings
        
        return AccountSettings(**settings_data)
    
    def set_profile(self, profile_name: str):
        """Set operational profile"""
        profiles = {
            "aggressive": OperationalProfile.AGGRESSIVE,
            "defensive": OperationalProfile.DEFENSIVE,
            "prop_firm_safe": OperationalProfile.PROP_FIRM_SAFE
        }
        
        if profile_name.lower() in profiles:
            self.active_profile = profiles[profile_name.lower()]
            logger.info(f"📊 Profile changed to: {self.active_profile.name}")
            self._save_state()
    
    def get_stats(self) -> Dict[str, Any]:
        """Get comprehensive scanner statistics"""
        uptime_seconds = 0
        if self.start_time:
            uptime_seconds = (datetime.utcnow() - self.start_time).total_seconds()
        
        return {
            "scans": self.scan_count,
            "signals_generated": self.signal_count,
            "notifications_sent": self.notification_count,
            "failed_notifications": self.failed_notifications,
            "invalid_tokens_removed": self.invalid_tokens_removed,
            "active_profile": self.active_profile.name,
            "is_running": self.is_running,
            "scan_interval": self.scan_interval,
            "uptime_seconds": int(uptime_seconds),
            "consecutive_errors": self.consecutive_errors
        }


# Global instance
market_scanner: Optional[MarketScanner] = None


def init_market_scanner(db) -> MarketScanner:
    """Initialize market scanner"""
    global market_scanner
    market_scanner = MarketScanner(db)
    return market_scanner
