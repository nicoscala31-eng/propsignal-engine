"""Twelve Data API Provider - Production market data with rate limiting and caching"""
import os
import asyncio
from typing import Optional, List, Dict
from datetime import datetime, timedelta
import aiohttp
from providers.base_provider import BaseMarketDataProvider, LiveQuote, ProviderStatus
from models import Candle, Asset, Timeframe
import logging
import json

logger = logging.getLogger(__name__)

class TwelveDataProvider(BaseMarketDataProvider):
    """Twelve Data API provider with rate limiting awareness"""
    
    def __init__(self, api_key: Optional[str] = None):
        self.api_key = api_key or os.getenv('TWELVE_DATA_API_KEY')
        self.base_url = 'https://api.twelvedata.com'
        self.session: Optional[aiohttp.ClientSession] = None
        self.is_connected = False
        self.last_quotes: Dict[Asset, LiveQuote] = {}
        self.last_update_time: Optional[datetime] = None
        self.error_message: Optional[str] = None
        
        # Pre-configured symbols (EUR/USD and XAU/USD work on free tier)
        self.working_symbols: Dict[Asset, str] = {
            Asset.EURUSD: 'EUR/USD',
            Asset.XAUUSD: 'XAU/USD'
        }
        
        # Rate limiting - Twelve Data free tier: 8 API credits/minute
        self.rate_limit_reset: Optional[datetime] = None
        self.is_rate_limited = False
        
        # Quote cache to reduce API calls (cache for 5 seconds)
        self.quote_cache: Dict[Asset, tuple] = {}  # {asset: (quote, timestamp)}
        self.cache_ttl_seconds = 5
        
        # Timeframe mapping
        self.timeframe_map = {
            Timeframe.M5: '5min',
            Timeframe.M15: '15min',
            Timeframe.H1: '1h',
            Timeframe.H4: '4h',
            Timeframe.D1: '1day'
        }
        
        # Realistic price ranges for validation
        self.price_ranges = {
            Asset.EURUSD: (0.9000, 1.3000),
            Asset.XAUUSD: (1500.0, 6000.0)
        }
        
        # Typical spreads
        self.typical_spreads = {
            Asset.EURUSD: (0.5, 3.0),
            Asset.XAUUSD: (15.0, 50.0)
        }
    
    async def connect(self) -> bool:
        """Establish connection and test API"""
        try:
            if not self.api_key:
                logger.warning("Twelve Data API key not configured")
                self.error_message = "API key not configured"
                return False
            
            self.session = aiohttp.ClientSession()
            
            # Test connection with a simple price request
            test_quote = await self.get_live_quote(Asset.EURUSD)
            
            if test_quote:
                self.is_connected = True
                self.error_message = None
                logger.info("✅ Twelve Data provider connected successfully")
                
                # Also test XAUUSD
                xau_quote = await self.get_live_quote(Asset.XAUUSD)
                if xau_quote:
                    logger.info("✅ XAUUSD symbol working")
                else:
                    logger.warning("⚠️  XAUUSD test failed (may be rate limited)")
                
                return True
            else:
                if self.is_rate_limited:
                    logger.warning("⚠️  Rate limited during connection test, but API key is valid")
                    self.is_connected = True
                    self.error_message = "Rate limited - will retry"
                    return True
                    
                logger.error("❌ Failed to get test quote from Twelve Data")
                self.error_message = "Failed to fetch test quote"
                return False
                
        except Exception as e:
            logger.error(f"Failed to connect to Twelve Data: {e}")
            self.error_message = str(e)
            return False
    
    async def disconnect(self) -> None:
        """Close connection"""
        if self.session and not self.session.closed:
            await self.session.close()
        self.session = None
        self.is_connected = False
        logger.info("Twelve Data provider disconnected")
    
    def _check_cache(self, asset: Asset) -> Optional[LiveQuote]:
        """Check if we have a valid cached quote"""
        if asset in self.quote_cache:
            quote, timestamp = self.quote_cache[asset]
            age = (datetime.utcnow() - timestamp).total_seconds()
            if age < self.cache_ttl_seconds:
                return quote
        return None
    
    def _cache_quote(self, asset: Asset, quote: LiveQuote):
        """Cache a quote"""
        self.quote_cache[asset] = (quote, datetime.utcnow())
    
    def _validate_price(self, asset: Asset, price: float) -> bool:
        """Validate price is within realistic range"""
        min_price, max_price = self.price_ranges[asset]
        if not (min_price <= price <= max_price):
            logger.error(f"❌ Price {price} for {asset.value} outside valid range [{min_price}, {max_price}]")
            return False
        return True
    
    def _handle_rate_limit_response(self, data: dict) -> bool:
        """Handle rate limit response, returns True if rate limited"""
        if data.get('code') == 429 or 'run out of API credits' in data.get('message', ''):
            self.is_rate_limited = True
            self.rate_limit_reset = datetime.utcnow() + timedelta(seconds=60)
            self.error_message = "API rate limit reached (8/min on free tier)"
            logger.warning(f"⚠️  Rate limited: {data.get('message', 'Rate limit reached')}")
            return True
        return False
    
    async def get_live_quote(self, asset: Asset) -> Optional[LiveQuote]:
        """Get current live quote with bid/ask"""
        if not self.api_key:
            logger.warning("API key not configured")
            return None
        
        # Check cache first
        cached = self._check_cache(asset)
        if cached:
            logger.debug(f"Using cached quote for {asset.value}")
            return cached
        
        # Check if we're rate limited and should wait
        if self.is_rate_limited and self.rate_limit_reset:
            if datetime.utcnow() < self.rate_limit_reset:
                wait_seconds = (self.rate_limit_reset - datetime.utcnow()).total_seconds()
                logger.warning(f"Rate limited, wait {wait_seconds:.0f}s. Using last known quote.")
                if asset in self.last_quotes:
                    return self.last_quotes[asset]
                return None
            else:
                self.is_rate_limited = False
                self.rate_limit_reset = None
                logger.info("Rate limit period ended, resuming API calls")
        
        # Create session if needed
        if not self.session or self.session.closed:
            self.session = aiohttp.ClientSession()
        
        symbol = self.working_symbols.get(asset)
        if not symbol:
            logger.error(f"No symbol configured for {asset.value}")
            return None
        
        try:
            # Use /price endpoint (simpler, uses fewer credits)
            url = f"{self.base_url}/price"
            params = {'symbol': symbol, 'apikey': self.api_key}
            
            async with self.session.get(url, params=params, timeout=aiohttp.ClientTimeout(total=10)) as response:
                data = await response.json()
                
                # Check for rate limiting
                if self._handle_rate_limit_response(data):
                    # Return cached/last quote if available
                    if asset in self.last_quotes:
                        return self.last_quotes[asset]
                    return None
                
                # Check for errors
                if 'code' in data and data.get('status') == 'error':
                    logger.error(f"API error for {asset.value}: {data}")
                    self.error_message = data.get('message', 'Unknown error')
                    return None
                
                # Parse price
                if 'price' not in data:
                    logger.error(f"No price in response for {asset.value}: {data}")
                    return None
                
                price = float(data['price'])
                
                if not self._validate_price(asset, price):
                    return None
                
                # Calculate bid/ask with typical spread
                if asset == Asset.EURUSD:
                    spread_pips = 0.8
                    pip_value = 0.0001
                else:
                    spread_pips = 25.0
                    pip_value = 0.1
                
                half_spread = (spread_pips * pip_value) / 2
                bid = price - half_spread
                ask = price + half_spread
                
                quote = LiveQuote(
                    asset=asset,
                    bid=round(bid, 5 if asset == Asset.EURUSD else 2),
                    ask=round(ask, 5 if asset == Asset.EURUSD else 2),
                    timestamp=datetime.utcnow(),
                    spread_pips=spread_pips
                )
                
                # Store and cache
                self.last_quotes[asset] = quote
                self.last_update_time = datetime.utcnow()
                self._cache_quote(asset, quote)
                self.error_message = None
                self.is_rate_limited = False
                
                logger.info(f"✅ {asset.value} - Price: {price}, Bid: {quote.bid}, Ask: {quote.ask}")
                
                return quote
                
        except asyncio.TimeoutError:
            logger.error(f"Timeout fetching quote for {asset.value}")
            self.error_message = "Request timeout"
            if asset in self.last_quotes:
                return self.last_quotes[asset]
            return None
        except Exception as e:
            logger.error(f"Error fetching quote for {asset.value}: {type(e).__name__}: {e}")
            self.error_message = str(e)
            if asset in self.last_quotes:
                return self.last_quotes[asset]
            return None
    
    async def get_candles(self, asset: Asset, timeframe: Timeframe, count: int = 100) -> List[Candle]:
        """Get recent historical candles"""
        if not self.api_key:
            return []
        
        if not self.session or self.session.closed:
            self.session = aiohttp.ClientSession()
        
        symbol = self.working_symbols.get(asset)
        if not symbol:
            return []
        
        interval = self.timeframe_map.get(timeframe)
        if not interval:
            return []
        
        try:
            url = f"{self.base_url}/time_series"
            params = {
                'symbol': symbol,
                'interval': interval,
                'outputsize': min(count, 500),
                'apikey': self.api_key
            }
            
            async with self.session.get(url, params=params, timeout=aiohttp.ClientTimeout(total=15)) as response:
                data = await response.json()
                
                # Check for rate limiting
                if self._handle_rate_limit_response(data):
                    return []
                
                if 'values' not in data:
                    logger.error(f"Invalid candle data: {data}")
                    return []
                
                candles = []
                for item in data['values'][:count]:
                    try:
                        candle = Candle(
                            timestamp=datetime.fromisoformat(item['datetime'].replace('Z', '+00:00').replace(' ', 'T')),
                            open=float(item['open']),
                            high=float(item['high']),
                            low=float(item['low']),
                            close=float(item['close']),
                            volume=float(item.get('volume', 0))
                        )
                        candles.append(candle)
                    except (ValueError, KeyError) as e:
                        logger.debug(f"Skipping invalid candle: {e}")
                        continue
                
                # Reverse to chronological order
                candles.reverse()
                return candles
                
        except Exception as e:
            logger.error(f"Error fetching candles: {e}")
            return []
    
    async def get_historical_candles(self, asset: Asset, timeframe: Timeframe,
                                    start_date: datetime, end_date: datetime) -> List[Candle]:
        """Get historical candles for backtesting"""
        if not self.api_key:
            return []
        
        symbol = self.working_symbols.get(asset)
        if not symbol:
            return []
        
        interval = self.timeframe_map.get(timeframe)
        if not interval:
            return []
        
        if not self.session or self.session.closed:
            self.session = aiohttp.ClientSession()
        
        try:
            url = f"{self.base_url}/time_series"
            params = {
                'symbol': symbol,
                'interval': interval,
                'start_date': start_date.strftime('%Y-%m-%d'),
                'end_date': end_date.strftime('%Y-%m-%d'),
                'apikey': self.api_key
            }
            
            async with self.session.get(url, params=params, timeout=aiohttp.ClientTimeout(total=15)) as response:
                data = await response.json()
                
                if self._handle_rate_limit_response(data):
                    return []
                
                if 'values' not in data:
                    return []
                
                candles = []
                for item in data['values']:
                    try:
                        candle = Candle(
                            timestamp=datetime.fromisoformat(item['datetime'].replace('Z', '+00:00').replace(' ', 'T')),
                            open=float(item['open']),
                            high=float(item['high']),
                            low=float(item['low']),
                            close=float(item['close']),
                            volume=float(item.get('volume', 0))
                        )
                        candles.append(candle)
                    except (ValueError, KeyError):
                        continue
                
                candles.reverse()
                return candles
                
        except Exception as e:
            logger.error(f"Error fetching historical candles: {e}")
            return []
    
    def get_status(self) -> ProviderStatus:
        """Get provider health status"""
        return ProviderStatus(
            is_connected=self.is_connected,
            is_streaming=self.is_connected and not self.is_rate_limited,
            last_update=self.last_update_time,
            provider_name=self.get_provider_name(),
            error_message=self.error_message
        )
    
    def get_provider_name(self) -> str:
        """Get provider name"""
        if self.is_rate_limited:
            return "Twelve Data (Rate Limited)"
        return "Twelve Data"
