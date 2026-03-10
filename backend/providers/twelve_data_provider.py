"""Twelve Data API Provider - Production market data with validation"""
import os
import asyncio
from typing import Optional, List, Dict
from datetime import datetime, timedelta
import aiohttp
from providers.base_provider import BaseMarketDataProvider, LiveQuote, ProviderStatus
from models import Candle, Asset, Timeframe
import logging

logger = logging.getLogger(__name__)

class TwelveDataProvider(BaseMarketDataProvider):
    """Twelve Data API provider - ENHANCED with validation and symbol discovery"""
    
    def __init__(self, api_key: Optional[str] = None):
        self.api_key = api_key or os.getenv('TWELVE_DATA_API_KEY')
        self.base_url = 'https://api.twelvedata.com'
        self.session: Optional[aiohttp.ClientSession] = None
        self.is_connected = False
        self.last_quotes: Dict[Asset, LiveQuote] = {}
        self.last_update_time: Optional[datetime] = None
        
        # Symbol mapping - Multiple formats to try
        self.symbol_map = {
            Asset.EURUSD: ['EUR/USD', 'EURUSD', 'FX:EURUSD'],
            Asset.XAUUSD: ['XAU/USD', 'XAUUSD', 'GOLD', 'FOREX:XAUUSD', 'OANDA:XAU_USD']
        }
        
        # Successful symbol format (discovered on first connection)
        self.working_symbols: Dict[Asset, str] = {}
        
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
            Asset.EURUSD: (0.9000, 1.3000),  # Min, Max
            Asset.XAUUSD: (1500.0, 6000.0)  # Updated for current gold prices
        }
        
        # Typical spreads for validation
        self.typical_spreads = {
            Asset.EURUSD: (0.5, 3.0),  # Min, Max pips
            Asset.XAUUSD: (15.0, 50.0)  # Min, Max points
        }
    
    async def connect(self) -> bool:
        """Establish connection and discover working symbols"""
        try:
            if not self.api_key:
                logger.warning("Twelve Data API key not configured")
                return False
            
            self.session = aiohttp.ClientSession()
            
            # Test connection with EURUSD
            test_quote = await self.get_live_quote(Asset.EURUSD)
            
            if test_quote:
                self.is_connected = True
                logger.info("✅ Twelve Data provider connected successfully")
                
                # Try to connect XAUUSD as well
                xau_quote = await self.get_live_quote(Asset.XAUUSD)
                if xau_quote:
                    logger.info("✅ XAUUSD symbol discovered and working")
                else:
                    logger.warning("⚠️  XAUUSD symbol not yet discovered")
                
                return True
            else:
                logger.error("❌ Failed to get test quote from Twelve Data")
                return False
                
        except Exception as e:
            logger.error(f"Failed to connect to Twelve Data: {e}")
            return False
    
    async def disconnect(self) -> None:
        """Close connection"""
        if self.session:
            await self.session.close()
            self.session = None
        self.is_connected = False
        logger.info("Twelve Data provider disconnected")
    
    async def _try_symbols(self, asset: Asset) -> Optional[str]:
        """Try different symbol formats to find working one"""
        if asset in self.working_symbols:
            return self.working_symbols[asset]
        
        symbol_variants = self.symbol_map.get(asset, [])
        
        for symbol in symbol_variants:
            try:
                url = f"{self.base_url}/price"
                params = {'symbol': symbol, 'apikey': self.api_key}
                
                async with self.session.get(url, params=params, timeout=aiohttp.ClientTimeout(total=5)) as response:
                    if response.status == 200:
                        data = await response.json()
                        if 'price' in data and data.get('price'):
                            logger.info(f"✅ Found working symbol for {asset.value}: {symbol}")
                            self.working_symbols[asset] = symbol
                            return symbol
            except Exception as e:
                logger.debug(f"Symbol {symbol} failed: {e}")
                continue
        
        logger.error(f"❌ No working symbol found for {asset.value}")
        return None
    
    def _validate_price(self, asset: Asset, price: float) -> bool:
        """Validate price is within realistic range"""
        min_price, max_price = self.price_ranges[asset]
        if not (min_price <= price <= max_price):
            logger.error(f"❌ Price {price} for {asset.value} outside valid range [{min_price}, {max_price}]")
            return False
        return True
    
    def _validate_spread(self, asset: Asset, spread_pips: float) -> bool:
        """Validate spread is realistic"""
        min_spread, max_spread = self.typical_spreads[asset]
        if not (min_spread <= spread_pips <= max_spread):
            logger.warning(f"⚠️  Unusual spread {spread_pips:.1f} for {asset.value} (typical: {min_spread}-{max_spread})")
        return True
    
    def _validate_timestamp(self, timestamp: datetime) -> bool:
        """Validate quote is recent (within 10 seconds)"""
        age_seconds = (datetime.utcnow() - timestamp).total_seconds()
        if age_seconds > 10:
            logger.error(f"❌ Quote too old: {age_seconds:.1f} seconds")
            return False
        return True
    
    async def get_live_quote(self, asset: Asset) -> Optional[LiveQuote]:
        """Get current live quote with bid/ask - ENHANCED WITH VALIDATION"""
        if not self.api_key:
            logger.warning("API key not configured")
            return None
        
        if not self.session:
            self.session = aiohttp.ClientSession()
        
        try:
            # Find working symbol
            symbol = await self._try_symbols(asset)
            if not symbol:
                return None
            
            # Try quote endpoint first (has bid/ask)
            url = f"{self.base_url}/quote"
            params = {'symbol': symbol, 'apikey': self.api_key}
            
            async with self.session.get(url, params=params, timeout=aiohttp.ClientTimeout(total=5)) as response:
                if response.status == 200:
                    data = await response.json()
                    
                    # Check for bid/ask
                    if 'bid' in data and 'ask' in data:
                        bid = float(data['bid'])
                        ask = float(data['ask'])
                    elif 'close' in data or 'price' in data:
                        # Estimate from close price
                        price = float(data.get('close', data.get('price', 0)))
                        if not self._validate_price(asset, price):
                            return None
                        
                        # Estimate bid/ask
                        if asset == Asset.EURUSD:
                            spread_pips = 0.8
                            pip_value = 0.0001
                        else:
                            spread_pips = 25.0
                            pip_value = 0.1
                        
                        half_spread = (spread_pips * pip_value) / 2
                        bid = price - half_spread
                        ask = price + half_spread
                    else:
                        # Try price endpoint fallback
                        return await self._get_price_fallback(asset, symbol)
                    
                    # Validate
                    mid_price = (bid + ask) / 2
                    if not self._validate_price(asset, mid_price):
                        return None
                    
                    # Calculate spread
                    if asset == Asset.EURUSD:
                        spread_pips = (ask - bid) / 0.0001
                    else:
                        spread_pips = (ask - bid) / 0.1
                    
                    self._validate_spread(asset, spread_pips)
                    
                    quote = LiveQuote(
                        asset=asset,
                        bid=round(bid, 5 if asset == Asset.EURUSD else 2),
                        ask=round(ask, 5 if asset == Asset.EURUSD else 2),
                        timestamp=datetime.utcnow(),
                        spread_pips=round(spread_pips, 2)
                    )
                    
                    self.last_quotes[asset] = quote
                    self.last_update_time = datetime.utcnow()
                    
                    logger.info(f"✅ {asset.value} - Bid: {quote.bid}, Ask: {quote.ask}, Spread: {spread_pips:.1f}")
                    
                    return quote
                else:
                    # Fallback to price endpoint
                    return await self._get_price_fallback(asset, symbol)
                
        except Exception as e:
            logger.error(f"Error fetching quote for {asset.value}: {e}")
            return None
    
    async def _get_price_fallback(self, asset: Asset, symbol: str) -> Optional[LiveQuote]:
        """Fallback to basic price endpoint"""
        try:
            url = f"{self.base_url}/price"
            params = {'symbol': symbol, 'apikey': self.api_key}
            
            async with self.session.get(url, params=params, timeout=aiohttp.ClientTimeout(total=5)) as response:
                if response.status != 200:
                    return None
                
                data = await response.json()
                if 'price' not in data:
                    return None
                
                mid_price = float(data['price'])
                
                if not self._validate_price(asset, mid_price):
                    return None
                
                # Estimate bid/ask
                if asset == Asset.EURUSD:
                    spread_pips = 0.8
                    pip_value = 0.0001
                else:
                    spread_pips = 25.0
                    pip_value = 0.1
                
                half_spread = (spread_pips * pip_value) / 2
                bid = mid_price - half_spread
                ask = mid_price + half_spread
                
                quote = LiveQuote(
                    asset=asset,
                    bid=round(bid, 5 if asset == Asset.EURUSD else 2),
                    ask=round(ask, 5 if asset == Asset.EURUSD else 2),
                    timestamp=datetime.utcnow(),
                    spread_pips=spread_pips
                )
                
                self.last_quotes[asset] = quote
                self.last_update_time = datetime.utcnow()
                
                logger.info(f"✅ {asset.value} (fallback) - Price: {mid_price}, Spread: {spread_pips:.1f}")
                
                return quote
        except Exception as e:
            logger.error(f"Fallback price fetch failed for {asset.value}: {e}")
            return None
    
    async def get_candles(self, asset: Asset, timeframe: Timeframe, count: int = 100) -> List[Candle]:
        """Get recent historical candles"""
        if not self.api_key:
            return []
        
        if not self.session:
            self.session = aiohttp.ClientSession()
        
        try:
            symbol = await self._try_symbols(asset)
            if not symbol:
                return []
            
            interval = self.timeframe_map.get(timeframe)
            if not interval:
                return []
            
            url = f"{self.base_url}/time_series"
            params = {
                'symbol': symbol,
                'interval': interval,
                'outputsize': min(count, 5000),
                'apikey': self.api_key
            }
            
            async with self.session.get(url, params=params, timeout=aiohttp.ClientTimeout(total=10)) as response:
                if response.status != 200:
                    logger.error(f"Failed to get candles: {response.status}")
                    return []
                
                data = await response.json()
                
                if 'values' not in data:
                    logger.error(f"Invalid candle data: {data}")
                    return []
                
                candles = []
                for item in data['values'][:count]:
                    candle = Candle(
                        timestamp=datetime.fromisoformat(item['datetime'].replace('Z', '+00:00')),
                        open=float(item['open']),
                        high=float(item['high']),
                        low=float(item['low']),
                        close=float(item['close']),
                        volume=float(item.get('volume', 0))
                    )
                    candles.append(candle)
                
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
        
        try:
            symbol = await self._try_symbols(asset)
            if not symbol:
                return []
            
            interval = self.timeframe_map.get(timeframe)
            if not interval:
                return []
            
            if not self.session:
                self.session = aiohttp.ClientSession()
            
            url = f"{self.base_url}/time_series"
            params = {
                'symbol': symbol,
                'interval': interval,
                'start_date': start_date.strftime('%Y-%m-%d'),
                'end_date': end_date.strftime('%Y-%m-%d'),
                'apikey': self.api_key
            }
            
            async with self.session.get(url, params=params, timeout=aiohttp.ClientTimeout(total=15)) as response:
                if response.status != 200:
                    return []
                
                data = await response.json()
                
                if 'values' not in data:
                    return []
                
                candles = []
                for item in data['values']:
                    candle = Candle(
                        timestamp=datetime.fromisoformat(item['datetime'].replace('Z', '+00:00')),
                        open=float(item['open']),
                        high=float(item['high']),
                        low=float(item['low']),
                        close=float(item['close']),
                        volume=float(item.get('volume', 0))
                    )
                    candles.append(candle)
                
                candles.reverse()
                return candles
                
        except Exception as e:
            logger.error(f"Error fetching historical candles: {e}")
            return []
    
    def get_status(self) -> ProviderStatus:
        """Get provider health status"""
        return ProviderStatus(
            is_connected=self.is_connected and self.session is not None,
            is_streaming=self.is_connected,
            last_update=self.last_update_time,
            provider_name=self.get_provider_name(),
            error_message=None if self.api_key else "API key not configured"
        )
    
    def get_provider_name(self) -> str:
        """Get provider name"""
        return "Twelve Data"
