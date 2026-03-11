"""
Market Data Fetch Engine - Centralized data fetching for PropSignal
===================================================================

Responsibilities:
- Fetch market data from external API (Twelve Data) every 10-15 seconds
- Fetch all symbols in batch when possible
- Store data in shared cache (market_data_cache)
- Handle rate limits and errors gracefully
- NEVER called by scanner - scanner reads only from cache

Architecture:
┌─────────────────────┐      ┌──────────────────┐      ┌─────────────────┐
│   Twelve Data API   │─────▶│  Fetch Engine    │─────▶│  Market Cache   │
│   (External)        │      │  (every 10-15s)  │      │  (Shared)       │
└─────────────────────┘      └──────────────────┘      └────────┬────────┘
                                                                 │
                                                                 ▼
                                                       ┌─────────────────┐
                                                       │  Scanner Engine │
                                                       │  (every 5s)     │
                                                       │  READ ONLY      │
                                                       └─────────────────┘
"""

import asyncio
import logging
from datetime import datetime, timedelta
from typing import Dict, Optional, List
from dataclasses import dataclass

from models import Asset, Timeframe
from providers.provider_manager import provider_manager
from services.market_data_cache import market_data_cache, CachedPrice

logger = logging.getLogger(__name__)


@dataclass
class FetchCycleStats:
    """Statistics for a single fetch cycle"""
    start_time: datetime
    end_time: Optional[datetime] = None
    symbols_fetched: int = 0
    candles_fetched: int = 0
    errors: int = 0
    duration_ms: float = 0
    api_calls_made: int = 0
    
    def complete(self):
        self.end_time = datetime.utcnow()
        self.duration_ms = (self.end_time - self.start_time).total_seconds() * 1000


class MarketDataFetchEngine:
    """
    Centralized Market Data Fetch Engine
    
    Key Principles:
    - Single source of truth for external API calls
    - Fetch interval: 10-15 seconds (configurable)
    - All data stored in shared cache
    - Scanner NEVER calls this directly
    - Graceful degradation on API failures
    
    API Usage Optimization:
    - Batch symbol fetches when possible
    - Cache candles longer (they change less frequently)
    - Use quote cache for price stability
    """
    
    def __init__(self):
        # Configuration - OPTIMIZED for Twelve Data free tier (8 credits/min)
        self.price_fetch_interval = 30  # seconds - fetch prices (reduced to avoid rate limits)
        self.candle_fetch_interval = 120  # seconds - fetch candles less often
        self.max_stale_seconds = 60  # flag data as stale after this
        
        # State
        self.is_running = False
        self.fetch_task: Optional[asyncio.Task] = None
        self.candle_task: Optional[asyncio.Task] = None
        
        # Tracked assets
        self.tracked_assets = [Asset.EURUSD, Asset.XAUUSD]
        
        # Statistics
        self.total_fetch_cycles = 0
        self.total_candle_fetches = 0
        self.total_api_calls = 0
        self.total_errors = 0
        self.consecutive_errors = 0
        self.start_time: Optional[datetime] = None
        self.last_price_fetch: Optional[datetime] = None
        self.last_candle_fetch: Optional[datetime] = None
        self.last_cycle_stats: Optional[FetchCycleStats] = None
        
        # Health monitoring
        self.watchdog_last_heartbeat: Optional[datetime] = None
        self.rate_limit_hits = 0
        
        logger.info("📡 Market Data Fetch Engine initialized")
        logger.info(f"   Price fetch interval: {self.price_fetch_interval}s")
        logger.info(f"   Candle fetch interval: {self.candle_fetch_interval}s")
    
    async def start(self):
        """Start the fetch engine"""
        if self.is_running:
            logger.warning("Fetch engine already running")
            return
        
        self.is_running = True
        self.start_time = datetime.utcnow()
        
        logger.info("=" * 60)
        logger.info("🚀 MARKET DATA FETCH ENGINE STARTED")
        logger.info(f"   Tracking: {[a.value for a in self.tracked_assets]}")
        logger.info(f"   Price fetch: every {self.price_fetch_interval}s")
        logger.info(f"   Candle fetch: every {self.candle_fetch_interval}s")
        logger.info("=" * 60)
        
        # Start fetch loops
        self.fetch_task = asyncio.create_task(self._run_price_fetch_loop())
        self.candle_task = asyncio.create_task(self._run_candle_fetch_loop())
        
        # Initial fetch
        await self._fetch_all_data()
    
    async def stop(self):
        """Stop the fetch engine"""
        self.is_running = False
        
        if self.fetch_task:
            self.fetch_task.cancel()
            try:
                await self.fetch_task
            except asyncio.CancelledError:
                pass
        
        if self.candle_task:
            self.candle_task.cancel()
            try:
                await self.candle_task
            except asyncio.CancelledError:
                pass
        
        logger.info("🛑 Market Data Fetch Engine stopped")
    
    async def _run_price_fetch_loop(self):
        """Main loop for fetching prices"""
        while self.is_running:
            try:
                self.watchdog_last_heartbeat = datetime.utcnow()
                await self._fetch_all_prices()
                self.consecutive_errors = 0
                
            except Exception as e:
                self.consecutive_errors += 1
                self.total_errors += 1
                logger.error(f"❌ Price fetch error ({self.consecutive_errors}): {e}")
                
                if self.consecutive_errors > 5:
                    wait_time = min(60, self.price_fetch_interval * 2)
                    logger.warning(f"⚠️  Multiple failures, waiting {wait_time}s")
                    await asyncio.sleep(wait_time)
                    self.consecutive_errors = 0
            
            await asyncio.sleep(self.price_fetch_interval)
    
    async def _run_candle_fetch_loop(self):
        """Separate loop for fetching candles (less frequent)"""
        while self.is_running:
            try:
                await self._fetch_all_candles()
                
            except Exception as e:
                logger.error(f"❌ Candle fetch error: {e}")
                market_data_cache.record_error(Asset.EURUSD)
                market_data_cache.record_error(Asset.XAUUSD)
            
            await asyncio.sleep(self.candle_fetch_interval)
    
    async def _fetch_all_data(self):
        """Fetch all data (prices + candles) - used for initial load"""
        await self._fetch_all_prices()
        await self._fetch_all_candles()
    
    async def _fetch_all_prices(self):
        """Fetch prices for all tracked assets"""
        stats = FetchCycleStats(start_time=datetime.utcnow())
        
        provider = provider_manager.get_provider()
        if not provider:
            logger.error("❌ No market data provider available")
            return
        
        for asset in self.tracked_assets:
            try:
                quote = await provider.get_live_quote(asset)
                stats.api_calls_made += 1
                self.total_api_calls += 1
                
                if quote and quote.bid and quote.ask:
                    # Update cache
                    market_data_cache.update_price(
                        asset=asset,
                        bid=quote.bid,
                        ask=quote.ask,
                        spread_pips=quote.spread_pips,
                        source="twelve_data"
                    )
                    stats.symbols_fetched += 1
                    
                    logger.info(f"📈 {asset.value}: {quote.bid:.5f}/{quote.ask:.5f} "
                               f"(spread: {quote.spread_pips:.1f} pips)")
                else:
                    stats.errors += 1
                    market_data_cache.record_error(asset)
                    logger.warning(f"⚠️  {asset.value}: No quote received")
                    
            except Exception as e:
                stats.errors += 1
                market_data_cache.record_error(asset)
                logger.error(f"❌ {asset.value} price fetch error: {e}")
        
        stats.complete()
        self.last_price_fetch = datetime.utcnow()
        self.total_fetch_cycles += 1
        self.last_cycle_stats = stats
        
        logger.debug(f"📊 Price fetch cycle: {stats.symbols_fetched}/{len(self.tracked_assets)} "
                    f"symbols in {stats.duration_ms:.0f}ms")
    
    async def _fetch_all_candles(self):
        """Fetch candles for all assets and timeframes"""
        provider = provider_manager.get_provider()
        if not provider:
            return
        
        candles_fetched = 0
        
        for asset in self.tracked_assets:
            for timeframe in [Timeframe.M5, Timeframe.M15, Timeframe.H1]:
                try:
                    # Determine count based on timeframe
                    count = 200 if timeframe == Timeframe.M5 else 100 if timeframe == Timeframe.M15 else 50
                    
                    candles = await provider.get_candles(asset, timeframe, count=count)
                    self.total_api_calls += 1
                    
                    if candles:
                        # Convert to dict format for cache
                        candle_dicts = [
                            {
                                "open": c.open,
                                "high": c.high,
                                "low": c.low,
                                "close": c.close,
                                "volume": c.volume if hasattr(c, 'volume') else 0,
                                "timestamp": c.timestamp.isoformat() if hasattr(c, 'timestamp') else None
                            }
                            for c in candles
                        ]
                        
                        market_data_cache.update_candles(asset, timeframe, candle_dicts)
                        candles_fetched += 1
                        
                        logger.debug(f"📊 {asset.value} {timeframe.value}: {len(candles)} candles cached")
                    
                except Exception as e:
                    logger.error(f"❌ {asset.value} {timeframe.value} candle fetch error: {e}")
        
        self.last_candle_fetch = datetime.utcnow()
        self.total_candle_fetches += 1
        
        logger.info(f"📦 Candle fetch complete: {candles_fetched} timeframes updated")
    
    def get_status(self) -> dict:
        """Get comprehensive engine status"""
        uptime = 0
        if self.start_time:
            uptime = (datetime.utcnow() - self.start_time).total_seconds()
        
        # Calculate API usage
        api_calls_per_minute = 0
        if uptime > 60:
            api_calls_per_minute = self.total_api_calls / (uptime / 60)
        
        cache_status = market_data_cache.get_cache_status()
        
        return {
            "engine": "market_data_fetch_engine",
            "is_running": self.is_running,
            "uptime_seconds": int(uptime),
            
            "configuration": {
                "price_fetch_interval_seconds": self.price_fetch_interval,
                "candle_fetch_interval_seconds": self.candle_fetch_interval,
                "max_stale_seconds": self.max_stale_seconds,
                "tracked_assets": [a.value for a in self.tracked_assets]
            },
            
            "statistics": {
                "total_fetch_cycles": self.total_fetch_cycles,
                "total_candle_fetches": self.total_candle_fetches,
                "total_api_calls": self.total_api_calls,
                "api_calls_per_minute": round(api_calls_per_minute, 2),
                "total_errors": self.total_errors,
                "consecutive_errors": self.consecutive_errors,
                "rate_limit_hits": self.rate_limit_hits
            },
            
            "timing": {
                "last_price_fetch": self.last_price_fetch.isoformat() if self.last_price_fetch else None,
                "last_candle_fetch": self.last_candle_fetch.isoformat() if self.last_candle_fetch else None,
                "last_cycle_duration_ms": self.last_cycle_stats.duration_ms if self.last_cycle_stats else None
            },
            
            "cache": cache_status
        }
    
    def get_estimated_api_usage(self) -> dict:
        """Get estimated API usage per minute"""
        # Price fetches: 2 symbols * (60 / price_interval) per minute
        price_calls = len(self.tracked_assets) * (60 / self.price_fetch_interval)
        
        # Candle fetches: 2 symbols * 3 timeframes * (60 / candle_interval) per minute
        candle_calls = len(self.tracked_assets) * 3 * (60 / self.candle_fetch_interval)
        
        total = price_calls + candle_calls
        
        return {
            "price_calls_per_minute": round(price_calls, 2),
            "candle_calls_per_minute": round(candle_calls, 2),
            "total_calls_per_minute": round(total, 2),
            "estimated_hourly_calls": round(total * 60, 0),
            "within_free_tier": total <= 8  # Twelve Data free tier: 8 credits/min
        }


# Global instance
market_data_fetch_engine = MarketDataFetchEngine()
