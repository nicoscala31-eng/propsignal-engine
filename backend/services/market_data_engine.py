"""
Live Market Data Engine - Continuous price updates for production
Handles automatic refresh, caching, and resilience for EURUSD and XAUUSD
"""
import asyncio
import logging
from datetime import datetime, timedelta
from typing import Dict, Optional
from dataclasses import dataclass, field
from models import Asset
from providers.provider_manager import provider_manager

logger = logging.getLogger(__name__)


@dataclass
class PriceData:
    """Cached price data with metadata"""
    bid: float
    ask: float
    mid: float
    spread_pips: float
    timestamp: datetime
    source: str = "twelve_data"
    is_stale: bool = False
    
    def to_dict(self) -> dict:
        return {
            "bid": self.bid,
            "ask": self.ask,
            "mid": self.mid,
            "spread_pips": self.spread_pips,
            "timestamp": self.timestamp.isoformat(),
            "age_seconds": (datetime.utcnow() - self.timestamp).total_seconds(),
            "source": self.source,
            "is_stale": self.is_stale
        }


class LiveMarketDataEngine:
    """
    Production-grade market data engine with:
    - Automatic refresh every 30 seconds
    - Price caching and staleness detection
    - Resilient to API failures
    - Watchdog for health monitoring
    - Rate limit and credit tracking
    """
    
    def __init__(self):
        self.is_running = False
        self.refresh_interval = 30  # seconds (optimized for rate limits)
        self.max_stale_seconds = 120  # mark as stale after this
        
        # Price cache
        self.prices: Dict[Asset, PriceData] = {}
        
        # Health metrics
        self.last_successful_update: Dict[Asset, datetime] = {}
        self.last_update_attempt: Optional[datetime] = None
        self.consecutive_failures = 0
        self.total_updates = 0
        self.total_failures = 0
        
        # Rate limit tracking
        self.rate_limit_hits = 0
        self.api_credits_used = 0
        
        # Watchdog
        self.watchdog_last_heartbeat: Optional[datetime] = None
        
        # Assets to track
        self.tracked_assets = [Asset.EURUSD, Asset.XAUUSD]
    
    async def start(self):
        """Start the live market data engine"""
        if self.is_running:
            logger.warning("Market data engine already running")
            return
        
        self.is_running = True
        logger.info("🚀 Live Market Data Engine starting...")
        logger.info(f"📊 Tracking: {[a.value for a in self.tracked_assets]}")
        logger.info(f"⏱️  Refresh interval: {self.refresh_interval}s")
        
        # Start the main loop
        asyncio.create_task(self._run_update_loop())
        
        # Start watchdog
        asyncio.create_task(self._run_watchdog())
        
        logger.info("✅ Live Market Data Engine started")
    
    async def stop(self):
        """Stop the engine"""
        self.is_running = False
        logger.info("🛑 Live Market Data Engine stopped")
    
    async def _run_update_loop(self):
        """Main update loop - runs continuously"""
        while self.is_running:
            try:
                self.watchdog_last_heartbeat = datetime.utcnow()
                self.last_update_attempt = datetime.utcnow()
                
                await self._update_all_prices()
                
                # Reset failure counter on success
                if self.consecutive_failures > 0:
                    logger.info(f"✅ Price updates recovered after {self.consecutive_failures} failures")
                    self.consecutive_failures = 0
                    
            except Exception as e:
                self.consecutive_failures += 1
                self.total_failures += 1
                logger.error(f"❌ Price update loop error (attempt #{self.consecutive_failures}): {e}")
                
                # Exponential backoff on repeated failures
                if self.consecutive_failures > 5:
                    wait_time = min(60, self.refresh_interval * self.consecutive_failures)
                    logger.warning(f"⚠️  Too many failures, waiting {wait_time}s before retry")
                    await asyncio.sleep(wait_time)
                    continue
            
            await asyncio.sleep(self.refresh_interval)
    
    async def _run_watchdog(self):
        """Watchdog to monitor engine health"""
        while self.is_running:
            await asyncio.sleep(30)  # Check every 30 seconds
            
            if self.watchdog_last_heartbeat:
                age = (datetime.utcnow() - self.watchdog_last_heartbeat).total_seconds()
                if age > 60:
                    logger.error(f"🚨 WATCHDOG ALERT: No heartbeat for {age:.0f}s - engine may be stuck!")
                    
                    # Try to restart the update loop
                    if self.is_running:
                        logger.info("🔄 Watchdog attempting to restart update loop...")
                        asyncio.create_task(self._run_update_loop())
    
    async def _update_all_prices(self):
        """Update prices for all tracked assets"""
        provider = provider_manager.get_provider()
        
        if not provider:
            logger.error("❌ No market data provider available")
            return
        
        self.api_credits_used += len(self.tracked_assets)  # Track API credits used
        
        for asset in self.tracked_assets:
            try:
                quote = await provider.get_live_quote(asset)
                
                if quote and quote.bid and quote.ask:
                    self.prices[asset] = PriceData(
                        bid=quote.bid,
                        ask=quote.ask,
                        mid=quote.mid_price,
                        spread_pips=quote.spread_pips,
                        timestamp=quote.timestamp or datetime.utcnow(),
                        source=provider_manager.get_status().provider_name if provider_manager.get_status() else "unknown"
                    )
                    self.last_successful_update[asset] = datetime.utcnow()
                    self.total_updates += 1
                    
                    # Log successful price update
                    logger.info(f"✅ {asset.value}: {quote.bid:.5f}/{quote.ask:.5f} (spread: {quote.spread_pips:.1f} pips) - Last update: {datetime.utcnow().strftime('%H:%M:%S')}")
                else:
                    # Check if rate limited
                    if hasattr(provider, 'is_rate_limited') and provider.is_rate_limited:
                        self.rate_limit_hits += 1
                        logger.warning(f"⚠️  {asset.value}: Rate limited (hit #{self.rate_limit_hits})")
                    else:
                        logger.warning(f"⚠️  {asset.value}: No quote received from provider")
                    
                    # Mark existing price as stale if we fail to update
                    if asset in self.prices:
                        self.prices[asset].is_stale = True
                    
            except Exception as e:
                logger.error(f"❌ Failed to update {asset.value}: {e}")
                if asset in self.prices:
                    self.prices[asset].is_stale = True
    
    def get_price(self, asset: Asset) -> Optional[PriceData]:
        """Get current price for an asset"""
        price = self.prices.get(asset)
        
        if price:
            # Check staleness
            age = (datetime.utcnow() - price.timestamp).total_seconds()
            if age > self.max_stale_seconds:
                price.is_stale = True
        
        return price
    
    def get_all_prices(self) -> Dict[str, dict]:
        """Get all current prices"""
        result = {}
        for asset in self.tracked_assets:
            price = self.get_price(asset)
            if price:
                result[asset.value] = price.to_dict()
            else:
                result[asset.value] = None
        return result
    
    def get_health_status(self) -> dict:
        """Get engine health status with rate limit and credit tracking"""
        return {
            "is_running": self.is_running,
            "refresh_interval_seconds": self.refresh_interval,
            "total_updates": self.total_updates,
            "total_failures": self.total_failures,
            "consecutive_failures": self.consecutive_failures,
            "rate_limit_hits": self.rate_limit_hits,
            "api_credits_used": self.api_credits_used,
            "last_update_attempt": self.last_update_attempt.isoformat() if self.last_update_attempt else None,
            "watchdog_last_heartbeat": self.watchdog_last_heartbeat.isoformat() if self.watchdog_last_heartbeat else None,
            "prices": {
                asset.value: {
                    "last_successful_update": self.last_successful_update.get(asset).isoformat() if self.last_successful_update.get(asset) else None,
                    "has_data": asset in self.prices,
                    "is_stale": self.prices[asset].is_stale if asset in self.prices else True,
                    "current_price": {
                        "bid": self.prices[asset].bid,
                        "ask": self.prices[asset].ask
                    } if asset in self.prices else None
                }
                for asset in self.tracked_assets
            }
        }


# Global instance
market_data_engine = LiveMarketDataEngine()
