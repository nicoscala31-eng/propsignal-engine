"""Twelve Data API Provider - Production market data"""
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
    """Twelve Data API provider for real-time forex and commodities data"""
    
    def __init__(self, api_key: Optional[str] = None):
        self.api_key = api_key or os.getenv('TWELVE_DATA_API_KEY')
        self.base_url = 'https://api.twelvedata.com'
        self.session: Optional[aiohttp.ClientSession] = None
        self.is_connected = False
        self.last_quotes: Dict[Asset, LiveQuote] = {}
        self.last_update_time: Optional[datetime] = None
        
        # Symbol mapping
        self.symbol_map = {
            Asset.EURUSD: 'EUR/USD',
            Asset.XAUUSD: 'XAU/USD'
        }
        
        # Timeframe mapping
        self.timeframe_map = {
            Timeframe.M5: '5min',
            Timeframe.M15: '15min',
            Timeframe.H1: '1h',
            Timeframe.H4: '4h',
            Timeframe.D1: '1day'
        }
    
    async def connect(self) -> bool:
        """Establish connection"""
        try:
            if not self.api_key:
                logger.warning("Twelve Data API key not configured")
                return False
            
            self.session = aiohttp.ClientSession()
            
            # Test connection with a simple quote request
            test_quote = await self.get_live_quote(Asset.EURUSD)
            
            if test_quote:
                self.is_connected = True
                logger.info("Twelve Data provider connected successfully")
                return True
            else:
                logger.error("Failed to get test quote from Twelve Data")
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
    
    async def get_live_quote(self, asset: Asset) -> Optional[LiveQuote]:
        """Get current live quote with bid/ask"""
        if not self.api_key:
            logger.warning("API key not configured, cannot fetch live quote")
            return None
        
        if not self.session:
            self.session = aiohttp.ClientSession()
        
        try:
            symbol = self.symbol_map.get(asset)
            if not symbol:
                logger.error(f"Unknown asset: {asset}")
                return None
            
            # Get real-time price
            url = f"{self.base_url}/price"
            params = {
                'symbol': symbol,
                'apikey': self.api_key
            }
            
            async with self.session.get(url, params=params) as response:
                if response.status != 200:
                    logger.error(f"Twelve Data API error: {response.status}")
                    return None
                
                data = await response.json()
                
                if 'price' not in data:
                    logger.error(f"Invalid response from Twelve Data: {data}")
                    return None
                
                mid_price = float(data['price'])
                
                # Calculate bid/ask from mid price using typical spreads
                # In production, use quote endpoint which provides bid/ask
                # For now, estimate based on typical spreads
                if asset == Asset.EURUSD:
                    spread_pips = 0.8  # Typical EURUSD spread
                    pip_value = 0.0001
                else:  # XAUUSD
                    spread_pips = 20.0  # Typical Gold spread
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
                
                return quote
                
        except Exception as e:
            logger.error(f"Error fetching live quote: {e}")
            return None
    
    async def get_candles(self, asset: Asset, timeframe: Timeframe, count: int = 100) -> List[Candle]:
        """Get recent historical candles"""
        if not self.api_key:
            return []
        
        if not self.session:
            self.session = aiohttp.ClientSession()
        
        try:
            symbol = self.symbol_map.get(asset)
            interval = self.timeframe_map.get(timeframe)
            
            if not symbol or not interval:
                return []
            
            url = f"{self.base_url}/time_series"
            params = {
                'symbol': symbol,
                'interval': interval,
                'outputsize': min(count, 5000),
                'apikey': self.api_key
            }
            
            async with self.session.get(url, params=params) as response:
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
                
                # Reverse to get chronological order
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
            symbol = self.symbol_map.get(asset)
            interval = self.timeframe_map.get(timeframe)
            
            if not symbol or not interval:
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
            
            async with self.session.get(url, params=params) as response:
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
