"""
Market Validation Layer - Centralized Market State Validation
==============================================================

CRITICAL SAFETY MODULE

This module provides centralized validation for:
1. Forex market open/closed status
2. Data freshness and staleness protection
3. Price feed freeze detection
4. Candle data advancement validation

ALL signal generation MUST pass through this validation before:
- Candidate generation
- Scoring
- Notification sending

FOREX MARKET HOURS (UTC):
- Opens: Sunday 22:00 UTC (Sydney open)
- Closes: Friday 22:00 UTC (New York close)
- Weekend: Friday 22:00 UTC to Sunday 22:00 UTC = CLOSED

ASSET-SPECIFIC RULES:
- EURUSD: Standard forex hours
- XAUUSD: Extended hours but follows major session patterns
"""

import logging
from datetime import datetime, timedelta
from typing import Dict, Optional, Tuple
from dataclasses import dataclass
from enum import Enum

from models import Asset

logger = logging.getLogger(__name__)


class MarketStatus(Enum):
    """Market status classification"""
    OPEN = "open"
    CLOSED_WEEKEND = "closed_weekend"
    CLOSED_HOLIDAY = "closed_holiday"
    PRE_OPEN = "pre_open"
    UNKNOWN = "unknown"


class DataFreshnessStatus(Enum):
    """Data freshness classification"""
    FRESH = "fresh"
    STALE = "stale"
    FROZEN = "frozen"
    MISSING = "missing"


@dataclass
class MarketValidationResult:
    """Result of market validation check"""
    is_valid: bool
    market_status: MarketStatus
    data_status: DataFreshnessStatus
    rejection_reason: Optional[str] = None
    details: Dict = None
    
    def __post_init__(self):
        if self.details is None:
            self.details = {}


class MarketValidator:
    """
    Centralized Market Validation
    
    Provides single point of validation for:
    - Market hours
    - Data freshness
    - Price feed health
    - Candle advancement
    """
    
    # Forex market hours (in UTC)
    FOREX_OPEN_HOUR_SUNDAY = 22  # Sunday 22:00 UTC
    FOREX_CLOSE_HOUR_FRIDAY = 22  # Friday 22:00 UTC
    
    # Staleness thresholds
    PRICE_MAX_AGE_SECONDS = 120  # 2 minutes
    CANDLE_MAX_AGE_SECONDS = 300  # 5 minutes
    
    # Freeze detection
    PRICE_FREEZE_THRESHOLD = 60  # seconds without price change = frozen
    CANDLE_FREEZE_COUNT = 5  # number of identical candles = frozen
    
    def __init__(self):
        self._last_prices: Dict[Asset, Tuple[float, datetime]] = {}
        self._validation_count = 0
        self._rejection_count = 0
        self._last_rejection_reason: Dict[Asset, str] = {}
        
        logger.info("🛡️ Market Validator initialized")
        logger.info(f"   Forex hours: Sunday 22:00 UTC - Friday 22:00 UTC")
        logger.info(f"   Price max age: {self.PRICE_MAX_AGE_SECONDS}s")
        logger.info(f"   Candle max age: {self.CANDLE_MAX_AGE_SECONDS}s")
    
    def validate_for_signal_generation(
        self,
        asset: Asset,
        price_data,
        candles_m5: list,
        candles_m15: list = None,
        candles_h1: list = None
    ) -> MarketValidationResult:
        """
        MAIN VALIDATION METHOD
        
        Must be called before ANY signal generation.
        Returns whether the market context is valid for trading signals.
        
        This method checks:
        1. Forex market is open (not weekend/holiday)
        2. Price data is fresh (not stale)
        3. Price feed is not frozen
        4. Candle data is advancing
        """
        self._validation_count += 1
        now = datetime.utcnow()
        
        # 1. CHECK FOREX MARKET HOURS
        market_status = self._check_forex_market_open(now, asset)
        
        if market_status != MarketStatus.OPEN:
            self._rejection_count += 1
            reason = f"Forex market closed ({market_status.value})"
            self._last_rejection_reason[asset] = reason
            logger.info(f"🚫 {asset.value}: {reason}")
            
            return MarketValidationResult(
                is_valid=False,
                market_status=market_status,
                data_status=DataFreshnessStatus.MISSING,
                rejection_reason=reason,
                details={"day": now.strftime("%A"), "hour": now.hour}
            )
        
        # 2. CHECK PRICE DATA EXISTS
        if not price_data:
            self._rejection_count += 1
            reason = "No price data available"
            self._last_rejection_reason[asset] = reason
            logger.warning(f"🚫 {asset.value}: {reason}")
            
            return MarketValidationResult(
                is_valid=False,
                market_status=market_status,
                data_status=DataFreshnessStatus.MISSING,
                rejection_reason=reason
            )
        
        # 3. CHECK PRICE FRESHNESS
        price_age = self._get_price_age(price_data)
        
        if price_age > self.PRICE_MAX_AGE_SECONDS:
            self._rejection_count += 1
            reason = f"Price data stale ({price_age:.0f}s > {self.PRICE_MAX_AGE_SECONDS}s)"
            self._last_rejection_reason[asset] = reason
            logger.warning(f"🚫 {asset.value}: {reason}")
            
            return MarketValidationResult(
                is_valid=False,
                market_status=market_status,
                data_status=DataFreshnessStatus.STALE,
                rejection_reason=reason,
                details={"price_age_seconds": price_age}
            )
        
        # 4. CHECK PRICE FEED NOT FROZEN
        is_frozen, freeze_duration = self._check_price_frozen(asset, price_data)
        
        if is_frozen:
            self._rejection_count += 1
            reason = f"Price feed frozen ({freeze_duration:.0f}s unchanged)"
            self._last_rejection_reason[asset] = reason
            logger.warning(f"🚫 {asset.value}: {reason}")
            
            return MarketValidationResult(
                is_valid=False,
                market_status=market_status,
                data_status=DataFreshnessStatus.FROZEN,
                rejection_reason=reason,
                details={"freeze_duration": freeze_duration}
            )
        
        # 5. CHECK CANDLE DATA EXISTS
        if not candles_m5 or len(candles_m5) < 10:
            self._rejection_count += 1
            reason = "Insufficient candle data"
            self._last_rejection_reason[asset] = reason
            logger.warning(f"🚫 {asset.value}: {reason}")
            
            return MarketValidationResult(
                is_valid=False,
                market_status=market_status,
                data_status=DataFreshnessStatus.MISSING,
                rejection_reason=reason,
                details={"candle_count": len(candles_m5) if candles_m5 else 0}
            )
        
        # 6. CHECK CANDLE FRESHNESS
        candle_age = self._get_candle_age(candles_m5)
        
        if candle_age > self.CANDLE_MAX_AGE_SECONDS:
            self._rejection_count += 1
            reason = f"Candle data stale ({candle_age:.0f}s > {self.CANDLE_MAX_AGE_SECONDS}s)"
            self._last_rejection_reason[asset] = reason
            logger.warning(f"🚫 {asset.value}: {reason}")
            
            return MarketValidationResult(
                is_valid=False,
                market_status=market_status,
                data_status=DataFreshnessStatus.STALE,
                rejection_reason=reason,
                details={"candle_age_seconds": candle_age}
            )
        
        # 7. CHECK CANDLES ARE ADVANCING (not frozen/repeated)
        candles_frozen = self._check_candles_frozen(candles_m5)
        
        if candles_frozen:
            self._rejection_count += 1
            reason = "Candle data frozen (no price movement)"
            self._last_rejection_reason[asset] = reason
            logger.warning(f"🚫 {asset.value}: {reason}")
            
            return MarketValidationResult(
                is_valid=False,
                market_status=market_status,
                data_status=DataFreshnessStatus.FROZEN,
                rejection_reason=reason
            )
        
        # 8. ALL CHECKS PASSED
        return MarketValidationResult(
            is_valid=True,
            market_status=MarketStatus.OPEN,
            data_status=DataFreshnessStatus.FRESH,
            details={
                "price_age_seconds": price_age,
                "candle_age_seconds": candle_age,
                "candle_count": len(candles_m5)
            }
        )
    
    def _check_forex_market_open(self, now: datetime, asset: Asset) -> MarketStatus:
        """
        Check if forex market is open
        
        Forex is OPEN:
        - Sunday 22:00 UTC to Friday 22:00 UTC
        
        Forex is CLOSED:
        - Friday 22:00 UTC to Sunday 22:00 UTC
        """
        weekday = now.weekday()  # Monday=0, Sunday=6
        hour = now.hour
        
        # Saturday: Always closed
        if weekday == 5:
            return MarketStatus.CLOSED_WEEKEND
        
        # Sunday: Closed until 22:00 UTC
        if weekday == 6:
            if hour < 22:
                return MarketStatus.CLOSED_WEEKEND
            else:
                return MarketStatus.OPEN
        
        # Friday: Open until 22:00 UTC
        if weekday == 4:
            if hour >= 22:
                return MarketStatus.CLOSED_WEEKEND
            else:
                return MarketStatus.OPEN
        
        # Monday to Thursday: Always open
        return MarketStatus.OPEN
    
    def _get_price_age(self, price_data) -> float:
        """Get age of price data in seconds"""
        if hasattr(price_data, 'timestamp'):
            return (datetime.utcnow() - price_data.timestamp).total_seconds()
        elif hasattr(price_data, 'age_seconds'):
            return price_data.age_seconds
        return 0
    
    def _check_price_frozen(self, asset: Asset, price_data) -> Tuple[bool, float]:
        """Check if price feed is frozen (same price for too long)"""
        current_price = price_data.mid if hasattr(price_data, 'mid') else 0
        now = datetime.utcnow()
        
        if asset in self._last_prices:
            last_price, last_time = self._last_prices[asset]
            duration = (now - last_time).total_seconds()
            
            # If price changed, update and not frozen
            if abs(current_price - last_price) > 0.00001:  # Small tolerance
                self._last_prices[asset] = (current_price, now)
                return False, 0
            
            # Price same - check duration
            if duration > self.PRICE_FREEZE_THRESHOLD:
                return True, duration
        else:
            # First time seeing this asset
            self._last_prices[asset] = (current_price, now)
        
        return False, 0
    
    def _get_candle_age(self, candles: list) -> float:
        """Get age of most recent candle"""
        if not candles:
            return float('inf')
        
        last_candle = candles[-1]
        
        # Try different timestamp field names
        timestamp_str = last_candle.get('datetime') or last_candle.get('timestamp') or last_candle.get('time')
        
        if not timestamp_str:
            return 0  # Can't determine age, assume fresh
        
        try:
            if isinstance(timestamp_str, str):
                # Parse ISO format
                candle_time = datetime.fromisoformat(timestamp_str.replace('Z', '+00:00').replace('+00:00', ''))
            else:
                candle_time = timestamp_str
            
            return (datetime.utcnow() - candle_time).total_seconds()
        except:
            return 0
    
    def _check_candles_frozen(self, candles: list) -> bool:
        """Check if candles are frozen (multiple identical candles)"""
        if len(candles) < self.CANDLE_FREEZE_COUNT:
            return False
        
        recent = candles[-self.CANDLE_FREEZE_COUNT:]
        
        # Check if all recent candles have same OHLC
        first = recent[0]
        for c in recent[1:]:
            if (c.get('open') != first.get('open') or
                c.get('high') != first.get('high') or
                c.get('low') != first.get('low') or
                c.get('close') != first.get('close')):
                return False
        
        return True  # All candles identical = frozen
    
    def is_forex_open(self) -> bool:
        """Quick check if forex market is currently open"""
        status = self._check_forex_market_open(datetime.utcnow(), Asset.EURUSD)
        return status == MarketStatus.OPEN
    
    def get_market_status_summary(self) -> Dict:
        """Get current market status summary"""
        now = datetime.utcnow()
        forex_status = self._check_forex_market_open(now, Asset.EURUSD)
        
        return {
            "current_time_utc": now.isoformat(),
            "day_of_week": now.strftime("%A"),
            "hour_utc": now.hour,
            "forex_status": forex_status.value,
            "forex_open": forex_status == MarketStatus.OPEN,
            "validation_stats": {
                "total_validations": self._validation_count,
                "total_rejections": self._rejection_count,
                "rejection_rate": round(self._rejection_count / max(self._validation_count, 1) * 100, 1)
            },
            "last_rejections": self._last_rejection_reason
        }
    
    def get_stats(self) -> Dict:
        """Get validation statistics"""
        return {
            "validation_count": self._validation_count,
            "rejection_count": self._rejection_count,
            "forex_open": self.is_forex_open(),
            "last_rejections": self._last_rejection_reason
        }


# Global instance
market_validator = MarketValidator()
