"""
Market Data Cache - Shared in-memory cache for scanner engines
==============================================================

Centralizes all market data storage:
- Latest prices per symbol
- Latest candle data (M5, M15, H1)
- Timestamps for staleness detection
- Thread-safe access

The scanner reads ONLY from this cache, never from external APIs.
"""

import logging
from typing import Dict, List, Optional, Any
from datetime import datetime, timedelta
from dataclasses import dataclass, field
from threading import Lock
from copy import deepcopy

from models import Asset, Timeframe

logger = logging.getLogger(__name__)


@dataclass
class CachedPrice:
    """Cached price data with metadata"""
    bid: float
    ask: float
    mid: float
    spread_pips: float
    timestamp: datetime
    source: str = "twelve_data"
    
    @property
    def age_seconds(self) -> float:
        """Get age of price data in seconds"""
        return (datetime.utcnow() - self.timestamp).total_seconds()
    
    def is_stale(self, max_age_seconds: float = 30.0) -> bool:
        """Check if price data is stale"""
        return self.age_seconds > max_age_seconds
    
    def to_dict(self) -> dict:
        return {
            "bid": self.bid,
            "ask": self.ask,
            "mid": self.mid,
            "spread_pips": self.spread_pips,
            "timestamp": self.timestamp.isoformat(),
            "age_seconds": self.age_seconds,
            "source": self.source,
            "is_stale": self.is_stale()
        }


@dataclass
class CachedCandles:
    """Cached candle data for a specific timeframe"""
    candles: List[dict]  # List of candle dicts
    timestamp: datetime
    timeframe: str
    count: int
    
    @property
    def age_seconds(self) -> float:
        """Get age of candle data in seconds"""
        return (datetime.utcnow() - self.timestamp).total_seconds()
    
    def is_stale(self, max_age_seconds: float = 60.0) -> bool:
        """Check if candle data is stale"""
        return self.age_seconds > max_age_seconds


@dataclass
class SymbolCache:
    """Complete cache for a single symbol"""
    symbol: str
    asset: Asset
    price: Optional[CachedPrice] = None
    candles_m5: Optional[CachedCandles] = None
    candles_m15: Optional[CachedCandles] = None
    candles_h1: Optional[CachedCandles] = None
    last_update: Optional[datetime] = None
    update_count: int = 0
    error_count: int = 0
    
    def get_candles(self, timeframe: Timeframe) -> Optional[List[dict]]:
        """Get candles for specific timeframe"""
        if timeframe == Timeframe.M5 and self.candles_m5:
            return self.candles_m5.candles
        elif timeframe == Timeframe.M15 and self.candles_m15:
            return self.candles_m15.candles
        elif timeframe == Timeframe.H1 and self.candles_h1:
            return self.candles_h1.candles
        return None
    
    def is_ready_for_scanning(self, max_stale_seconds: float = 30.0) -> bool:
        """Check if cache has fresh enough data for scanning"""
        if not self.price:
            return False
        if self.price.is_stale(max_stale_seconds):
            return False
        if not self.candles_m5 or not self.candles_m15 or not self.candles_h1:
            return False
        return True
    
    def get_staleness_info(self) -> dict:
        """Get detailed staleness information"""
        return {
            "symbol": self.symbol,
            "price_age_seconds": self.price.age_seconds if self.price else None,
            "price_stale": self.price.is_stale() if self.price else True,
            "candles_m5_age": self.candles_m5.age_seconds if self.candles_m5 else None,
            "candles_m15_age": self.candles_m15.age_seconds if self.candles_m15 else None,
            "candles_h1_age": self.candles_h1.age_seconds if self.candles_h1 else None,
            "is_ready": self.is_ready_for_scanning(),
            "last_update": self.last_update.isoformat() if self.last_update else None,
            "update_count": self.update_count,
            "error_count": self.error_count
        }


class MarketDataCache:
    """
    Thread-safe shared market data cache
    
    Responsibilities:
    - Store latest prices and candles for all tracked symbols
    - Provide staleness detection
    - Allow concurrent read access for scanners
    - Centralize all market data storage
    
    Usage:
    - Market Data Engine writes to this cache
    - Scanner Engine reads from this cache
    - Never call external APIs from scanner
    """
    
    def __init__(self):
        self._lock = Lock()
        self._cache: Dict[Asset, SymbolCache] = {}
        
        # Configuration - aligned with fetch engine intervals
        self.price_stale_threshold = 60.0  # seconds (was 30)
        self.candle_stale_threshold = 180.0  # seconds (was 120)
        
        # Statistics
        self.total_writes = 0
        self.total_reads = 0
        self.cache_hits = 0
        self.cache_misses = 0
        self.stale_reads = 0
        self.created_at = datetime.utcnow()
        
        # Initialize cache for tracked assets
        for asset in [Asset.EURUSD, Asset.XAUUSD]:
            self._cache[asset] = SymbolCache(
                symbol=asset.value,
                asset=asset
            )
        
        logger.info("📦 Market Data Cache initialized")
    
    # ==================== WRITE OPERATIONS (for Market Data Engine) ====================
    
    def update_price(self, asset: Asset, bid: float, ask: float, 
                     spread_pips: float, source: str = "twelve_data") -> None:
        """Update price for an asset (called by Market Data Engine)"""
        with self._lock:
            if asset not in self._cache:
                self._cache[asset] = SymbolCache(symbol=asset.value, asset=asset)
            
            mid = (bid + ask) / 2
            self._cache[asset].price = CachedPrice(
                bid=bid,
                ask=ask,
                mid=mid,
                spread_pips=spread_pips,
                timestamp=datetime.utcnow(),
                source=source
            )
            self._cache[asset].last_update = datetime.utcnow()
            self._cache[asset].update_count += 1
            self.total_writes += 1
    
    def update_candles(self, asset: Asset, timeframe: Timeframe, 
                       candles: List[dict]) -> None:
        """Update candles for an asset and timeframe (called by Market Data Engine)"""
        with self._lock:
            if asset not in self._cache:
                self._cache[asset] = SymbolCache(symbol=asset.value, asset=asset)
            
            cached = CachedCandles(
                candles=candles,
                timestamp=datetime.utcnow(),
                timeframe=timeframe.value,
                count=len(candles)
            )
            
            if timeframe == Timeframe.M5:
                self._cache[asset].candles_m5 = cached
            elif timeframe == Timeframe.M15:
                self._cache[asset].candles_m15 = cached
            elif timeframe == Timeframe.H1:
                self._cache[asset].candles_h1 = cached
            
            self._cache[asset].last_update = datetime.utcnow()
            self.total_writes += 1
    
    def record_error(self, asset: Asset) -> None:
        """Record a fetch error for an asset"""
        with self._lock:
            if asset in self._cache:
                self._cache[asset].error_count += 1
    
    # ==================== READ OPERATIONS (for Scanner Engine) ====================
    
    def get_price(self, asset: Asset) -> Optional[CachedPrice]:
        """Get cached price for an asset (called by Scanner)"""
        with self._lock:
            self.total_reads += 1
            
            if asset not in self._cache or not self._cache[asset].price:
                self.cache_misses += 1
                return None
            
            price = self._cache[asset].price
            
            if price.is_stale(self.price_stale_threshold):
                self.stale_reads += 1
                logger.debug(f"⚠️  Stale price read for {asset.value} (age: {price.age_seconds:.1f}s)")
            else:
                self.cache_hits += 1
            
            # Return a copy to prevent modification
            return CachedPrice(
                bid=price.bid,
                ask=price.ask,
                mid=price.mid,
                spread_pips=price.spread_pips,
                timestamp=price.timestamp,
                source=price.source
            )
    
    def get_candles(self, asset: Asset, timeframe: Timeframe) -> Optional[List[dict]]:
        """Get cached candles for an asset (called by Scanner)"""
        with self._lock:
            self.total_reads += 1
            
            if asset not in self._cache:
                self.cache_misses += 1
                return None
            
            candles = self._cache[asset].get_candles(timeframe)
            
            if not candles:
                self.cache_misses += 1
                return None
            
            self.cache_hits += 1
            
            # Return a deep copy to prevent modification
            return deepcopy(candles)
    
    def get_all_candles(self, asset: Asset) -> Dict[str, List[dict]]:
        """Get all cached candles for an asset (M5, M15, H1)"""
        with self._lock:
            self.total_reads += 1
            
            if asset not in self._cache:
                return {}
            
            result = {}
            cache = self._cache[asset]
            
            if cache.candles_m5:
                result["m5"] = deepcopy(cache.candles_m5.candles)
            if cache.candles_m15:
                result["m15"] = deepcopy(cache.candles_m15.candles)
            if cache.candles_h1:
                result["h1"] = deepcopy(cache.candles_h1.candles)
            
            return result
    
    def is_data_fresh(self, asset: Asset) -> bool:
        """Check if data is fresh enough for signal generation"""
        with self._lock:
            if asset not in self._cache:
                return False
            return self._cache[asset].is_ready_for_scanning(self.price_stale_threshold)
    
    def is_stale(self, asset: Asset) -> bool:
        """Check if data is stale (should not generate signals)"""
        return not self.is_data_fresh(asset)
    
    # ==================== STATUS AND MONITORING ====================
    
    def get_cache_status(self) -> dict:
        """Get comprehensive cache status"""
        with self._lock:
            uptime = (datetime.utcnow() - self.created_at).total_seconds()
            hit_rate = (self.cache_hits / self.total_reads * 100) if self.total_reads > 0 else 0
            
            symbols = {}
            for asset, cache in self._cache.items():
                symbols[asset.value] = cache.get_staleness_info()
            
            return {
                "uptime_seconds": int(uptime),
                "statistics": {
                    "total_writes": self.total_writes,
                    "total_reads": self.total_reads,
                    "cache_hits": self.cache_hits,
                    "cache_misses": self.cache_misses,
                    "stale_reads": self.stale_reads,
                    "hit_rate_percent": round(hit_rate, 1)
                },
                "configuration": {
                    "price_stale_threshold_seconds": self.price_stale_threshold,
                    "candle_stale_threshold_seconds": self.candle_stale_threshold
                },
                "symbols": symbols
            }
    
    def get_symbol_summary(self, asset: Asset) -> Optional[dict]:
        """Get summary for a specific symbol"""
        with self._lock:
            if asset not in self._cache:
                return None
            
            cache = self._cache[asset]
            return {
                "symbol": cache.symbol,
                "has_price": cache.price is not None,
                "price": cache.price.to_dict() if cache.price else None,
                "has_candles_m5": cache.candles_m5 is not None,
                "has_candles_m15": cache.candles_m15 is not None,
                "has_candles_h1": cache.candles_h1 is not None,
                "candles_m5_count": len(cache.candles_m5.candles) if cache.candles_m5 else 0,
                "candles_m15_count": len(cache.candles_m15.candles) if cache.candles_m15 else 0,
                "candles_h1_count": len(cache.candles_h1.candles) if cache.candles_h1 else 0,
                "is_ready": cache.is_ready_for_scanning(),
                "last_update": cache.last_update.isoformat() if cache.last_update else None
            }


# Global instance - shared across Market Data Engine and Scanner
market_data_cache = MarketDataCache()
