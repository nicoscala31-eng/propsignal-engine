"""Backend Market Scanner - Automatic signal generation and push notifications"""
import asyncio
import logging
from typing import Dict, Set, Optional, List
from datetime import datetime, timedelta
from dataclasses import dataclass, field

from models import Asset, SignalType, Signal, PropProfile, AccountSettings, MarketRegime
from services.signal_orchestrator import enhanced_signal_orchestrator
from services.push_notification_service import push_service
from providers.provider_manager import provider_manager

logger = logging.getLogger(__name__)


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


@dataclass
class OperationalProfile:
    """Trading operational profile"""
    name: str
    min_confidence: float
    min_rr_ratio: float
    signal_frequency_minutes: int  # Minimum time between signals
    regime_filter: List[MarketRegime]  # Allowed regimes
    
    # Profiles
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
    Backend market scanner that runs independently of the mobile app
    
    Features:
    - Periodic market scanning (every 30 seconds)
    - Automatic signal generation
    - Push notification delivery
    - Signal deduplication
    - Pre-signal alerts
    - News filtering
    - Operational profiles
    """
    
    def __init__(self, db):
        self.db = db
        self.is_running = False
        self.scan_interval = 30  # seconds
        
        # Signal deduplication
        self.last_signal_times: Dict[Asset, datetime] = {}
        self.sent_signal_ids: Set[str] = set()
        
        # Pre-alert tracking
        self.pre_alert_sent: Dict[Asset, datetime] = {}
        self.pre_alert_cooldown = 300  # 5 minutes
        
        # Default operational profile
        self.active_profile = OperationalProfile.PROP_FIRM_SAFE
        
        # Statistics
        self.scan_count = 0
        self.signal_count = 0
        self.notification_count = 0
        
        # News events cache
        self.upcoming_news: List[Dict] = []
        self.news_cache_time: Optional[datetime] = None
    
    async def start(self):
        """Start the market scanner"""
        if self.is_running:
            logger.warning("Market scanner already running")
            return
        
        self.is_running = True
        logger.info("🚀 Market Scanner started")
        logger.info(f"📊 Active profile: {self.active_profile.name}")
        logger.info(f"⏱️  Scan interval: {self.scan_interval}s")
        
        asyncio.create_task(self._run_scanner_loop())
    
    async def stop(self):
        """Stop the market scanner"""
        self.is_running = False
        logger.info("🛑 Market Scanner stopped")
    
    async def _run_scanner_loop(self):
        """Main scanner loop"""
        while self.is_running:
            try:
                await self._scan_markets()
            except Exception as e:
                logger.error(f"Scanner error: {e}", exc_info=True)
            
            await asyncio.sleep(self.scan_interval)
    
    async def _scan_markets(self):
        """Scan all markets and generate signals"""
        self.scan_count += 1
        logger.debug(f"🔍 Market scan #{self.scan_count}")
        
        # Get all registered devices
        devices = await self.db.devices.find({"is_active": True}).to_list(1000)
        
        if not devices:
            logger.debug("No registered devices, skipping notifications")
        
        # Get a default prop profile and account settings
        # In production, this would be per-user
        default_profile = await self._get_default_profile()
        default_settings = await self._get_default_settings()
        
        for asset in [Asset.EURUSD, Asset.XAUUSD]:
            try:
                result = await self._scan_asset(asset, default_profile, default_settings)
                
                # Send notifications if applicable
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
        """Scan a single asset for signals"""
        
        # Generate signal using the orchestrator
        signal = await enhanced_signal_orchestrator.generate_signal(
            user_id="system",  # System-generated signal
            asset=asset,
            prop_profile=profile,
            account_settings=settings,
            consecutive_losses=0
        )
        
        # Create scan result
        result = ScanResult(
            asset=asset,
            signal_type=signal.signal_type,
            signal_id=signal.id,
            confidence=signal.confidence_score,
            regime=signal.market_regime
        )
        
        # Check if this is a tradeable signal
        if signal.signal_type != SignalType.NEXT:
            # Check deduplication
            if self._is_duplicate_signal(asset, signal):
                logger.debug(f"Duplicate signal for {asset.value}, skipping")
                return result
            
            # Apply operational profile filter
            if not self._passes_profile_filter(signal):
                logger.debug(f"Signal for {asset.value} filtered by profile")
                return result
            
            # Check news filter
            if await self._has_news_risk(asset):
                logger.warning(f"⚠️ High-impact news near {asset.value}")
                # Could add news_warning flag to signal
            
            # Store signal in database
            await self.db.signals.insert_one(signal.dict())
            self.signal_count += 1
            
            # Update last signal time
            self.last_signal_times[asset] = datetime.utcnow()
            self.sent_signal_ids.add(signal.id)
            
            logger.info(f"✅ {signal.signal_type.value} signal generated for {asset.value}")
        
        return result
    
    def _is_duplicate_signal(self, asset: Asset, signal: Signal) -> bool:
        """Check if signal is a duplicate"""
        # Check if signal ID was already sent
        if signal.id in self.sent_signal_ids:
            return True
        
        # Check minimum time between signals
        if asset in self.last_signal_times:
            elapsed = (datetime.utcnow() - self.last_signal_times[asset]).total_seconds()
            min_interval = self.active_profile.signal_frequency_minutes * 60
            if elapsed < min_interval:
                return True
        
        return False
    
    def _passes_profile_filter(self, signal: Signal) -> bool:
        """Check if signal passes the active operational profile filter"""
        profile = self.active_profile
        
        # Confidence check
        if signal.confidence_score < profile.min_confidence:
            return False
        
        # R:R check
        if signal.risk_reward_ratio and signal.risk_reward_ratio < profile.min_rr_ratio:
            return False
        
        # Regime check
        if signal.market_regime not in profile.regime_filter:
            return False
        
        return True
    
    async def _has_news_risk(self, asset: Asset) -> bool:
        """Check if there's high-impact news risk"""
        # Simple implementation - check if we have upcoming news
        # In production, integrate with a news API
        
        # Refresh news cache every 5 minutes
        if (not self.news_cache_time or 
            (datetime.utcnow() - self.news_cache_time).total_seconds() > 300):
            await self._refresh_news_cache()
        
        # Check for news affecting this asset
        now = datetime.utcnow()
        for event in self.upcoming_news:
            event_time = event.get("time")
            currencies = event.get("currencies", [])
            
            # Check if news is within 30 minutes
            if event_time:
                time_diff = abs((event_time - now).total_seconds())
                if time_diff < 1800:  # 30 minutes
                    # Check if this asset is affected
                    asset_currencies = ["EUR", "USD"] if asset == Asset.EURUSD else ["XAU", "USD"]
                    if any(c in currencies for c in asset_currencies):
                        return True
        
        return False
    
    async def _refresh_news_cache(self):
        """Refresh the news events cache"""
        # In production, integrate with ForexFactory, Investing.com, or similar
        # For now, use a simple placeholder
        self.upcoming_news = []
        self.news_cache_time = datetime.utcnow()
    
    async def _send_signal_notifications(self, result: ScanResult, devices: List[Dict]):
        """Send push notifications for a signal"""
        if result.signal_id in self.sent_signal_ids:
            return
        
        # Get the full signal
        signal_data = await self.db.signals.find_one({"id": result.signal_id})
        if not signal_data:
            return
        
        signal = Signal(**signal_data)
        
        # Get device tokens
        tokens = [d["push_token"] for d in devices if d.get("push_token")]
        
        if not tokens:
            return
        
        # Check news risk
        has_news = await self._has_news_risk(result.asset)
        
        # Send notification
        results = await push_service.send_signal_notification(
            tokens=tokens,
            signal_type=signal.signal_type.value,
            asset=signal.asset.value,
            entry_price=signal.entry_price or 0,
            confidence=signal.confidence_score,
            signal_id=signal.id,
            stop_loss=signal.stop_loss,
            take_profit=signal.take_profit_1,
            news_warning=has_news
        )
        
        # Count successful sends
        successful = sum(1 for r in results if r.success)
        self.notification_count += successful
        
        result.notification_sent = True
        logger.info(f"📢 Notifications sent: {successful}/{len(tokens)}")
        
        # Mark signal ID as notified
        self.sent_signal_ids.add(signal.id)
    
    async def _check_pre_signal_alerts(self, result: ScanResult, devices: List[Dict]):
        """Check and send pre-signal alerts"""
        asset = result.asset
        regime = result.regime
        
        # Check cooldown
        if asset in self.pre_alert_sent:
            elapsed = (datetime.utcnow() - self.pre_alert_sent[asset]).total_seconds()
            if elapsed < self.pre_alert_cooldown:
                return
        
        # Determine alert message based on regime
        alert_message = None
        alert_type = None
        
        if regime == MarketRegime.COMPRESSION:
            alert_message = f"📊 {asset.value}: Market compression detected. Potential breakout forming."
            alert_type = "compression"
        
        elif regime == MarketRegime.BREAKOUT_EXPANSION:
            alert_message = f"🚀 {asset.value}: Breakout in progress. Setup may be forming."
            alert_type = "breakout"
        
        elif regime == MarketRegime.CHAOTIC:
            # Only alert if transitioning
            alert_message = f"⚠️ {asset.value}: Market volatile. Waiting for clearer conditions."
            alert_type = "volatility"
        
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
                result.pre_alert_sent = True
    
    async def _get_default_profile(self) -> PropProfile:
        """Get default prop profile for system scans"""
        profile_data = await self.db.prop_profiles.find_one({"user_id": "system"})
        
        if not profile_data:
            # Create default system profile
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
        """Get default account settings for system scans"""
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
        """Set the active operational profile"""
        profiles = {
            "aggressive": OperationalProfile.AGGRESSIVE,
            "defensive": OperationalProfile.DEFENSIVE,
            "prop_firm_safe": OperationalProfile.PROP_FIRM_SAFE
        }
        
        if profile_name.lower() in profiles:
            self.active_profile = profiles[profile_name.lower()]
            logger.info(f"📊 Operational profile changed to: {self.active_profile.name}")
        else:
            logger.warning(f"Unknown profile: {profile_name}")
    
    def get_stats(self) -> Dict:
        """Get scanner statistics"""
        return {
            "scans": self.scan_count,
            "signals_generated": self.signal_count,
            "notifications_sent": self.notification_count,
            "active_profile": self.active_profile.name,
            "is_running": self.is_running,
            "scan_interval": self.scan_interval
        }


# Global instance (initialized with db in server.py)
market_scanner: Optional[MarketScanner] = None


def init_market_scanner(db) -> MarketScanner:
    """Initialize the market scanner with database connection"""
    global market_scanner
    market_scanner = MarketScanner(db)
    return market_scanner
