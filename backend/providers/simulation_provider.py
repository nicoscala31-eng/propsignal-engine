"""Simulation provider - DEVELOPMENT FALLBACK ONLY"""
import random
from typing import Optional, List
from datetime import datetime, timedelta
import statistics
from providers.base_provider import BaseMarketDataProvider, LiveQuote, ProviderStatus
from models import Candle, Asset, Timeframe
import logging

logger = logging.getLogger(__name__)

class SimulationProvider(BaseMarketDataProvider):
    """Simulation provider - FOR DEVELOPMENT ONLY
    
    WARNING: This provider generates simulated data.
    DO NOT use in production for real trading decisions.
    """
    
    def __init__(self):
        self.is_connected = False
        self.last_update_time: Optional[datetime] = None
        
        # Base prices
        self.base_prices = {
            Asset.EURUSD: 1.08500,
            Asset.XAUUSD: 2650.00
        }
        
        # Current simulated prices
        self.current_prices = self.base_prices.copy()
        
        # Typical spreads
        self.spreads = {
            Asset.EURUSD: 0.8,  # pips
            Asset.XAUUSD: 20.0   # points
        }
        
        # Volatility
        self.volatility = {
            Asset.EURUSD: 0.0002,
            Asset.XAUUSD: 0.50
        }
        
        self.timeframe_multipliers = {
            Timeframe.M5: 1,
            Timeframe.M15: 1.7,
            Timeframe.H1: 3.5,
            Timeframe.H4: 7,
            Timeframe.D1: 14
        }
        
        logger.warning("⚠️  SIMULATION MODE ACTIVE - Using simulated market data")
    
    async def connect(self) -> bool:
        """Establish connection"""
        self.is_connected = True
        self.last_update_time = datetime.utcnow()
        logger.warning("⚠️  Simulation provider connected - NOT REAL DATA")
        return True
    
    async def disconnect(self) -> None:
        """Close connection"""
        self.is_connected = False
    
    async def get_live_quote(self, asset: Asset) -> Optional[LiveQuote]:
        """Get simulated live quote"""
        if not self.is_connected:
            return None
        
        # Random walk
        vol = self.volatility[asset]
        change = random.gauss(0, vol * 2)
        self.current_prices[asset] += change
        
        mid_price = self.current_prices[asset]
        
        # Calculate bid/ask
        if asset == Asset.EURUSD:
            pip_value = 0.0001
        else:
            pip_value = 0.1
        
        spread_pips = self.spreads[asset]
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
        
        self.last_update_time = datetime.utcnow()
        return quote
    
    async def get_candles(self, asset: Asset, timeframe: Timeframe, count: int = 100) -> List[Candle]:
        """Generate simulated candles"""
        candles = []
        base_price = self.base_prices[asset]
        vol = self.volatility[asset] * self.timeframe_multipliers[timeframe]
        
        time_deltas = {
            Timeframe.M5: timedelta(minutes=5),
            Timeframe.M15: timedelta(minutes=15),
            Timeframe.H1: timedelta(hours=1),
            Timeframe.H4: timedelta(hours=4),
            Timeframe.D1: timedelta(days=1)
        }
        delta = time_deltas[timeframe]
        
        current_time = datetime.utcnow()
        current_price = base_price
        
        for i in range(count, 0, -1):
            open_price = current_price
            trend = random.gauss(0, vol * 0.5)
            high_move = abs(random.gauss(0, vol)) + vol * 0.3
            low_move = abs(random.gauss(0, vol)) + vol * 0.3
            
            high_price = open_price + high_move
            low_price = open_price - low_move
            close_price = open_price + trend
            close_price = max(low_price, min(high_price, close_price))
            
            candle = Candle(
                timestamp=current_time - (delta * i),
                open=round(open_price, 5 if asset == Asset.EURUSD else 2),
                high=round(high_price, 5 if asset == Asset.EURUSD else 2),
                low=round(low_price, 5 if asset == Asset.EURUSD else 2),
                close=round(close_price, 5 if asset == Asset.EURUSD else 2),
                volume=random.randint(100, 1000)
            )
            candles.append(candle)
            current_price = close_price
        
        return candles
    
    async def get_historical_candles(self, asset: Asset, timeframe: Timeframe,
                                    start_date: datetime, end_date: datetime) -> List[Candle]:
        """Generate simulated historical candles"""
        time_deltas = {
            Timeframe.M5: timedelta(minutes=5),
            Timeframe.M15: timedelta(minutes=15),
            Timeframe.H1: timedelta(hours=1),
            Timeframe.H4: timedelta(hours=4),
            Timeframe.D1: timedelta(days=1)
        }
        delta = time_deltas[timeframe]
        
        total_time = end_date - start_date
        count = int(total_time / delta)
        count = min(count, 100000)
        
        candles = []
        base_price = self.base_prices[asset]
        vol = self.volatility[asset] * self.timeframe_multipliers[timeframe]
        current_price = base_price * random.uniform(0.95, 1.05)
        current_time = start_date
        
        while current_time < end_date:
            open_price = current_price
            trend = random.gauss(0, vol * 0.5)
            high_move = abs(random.gauss(0, vol)) + vol * 0.3
            low_move = abs(random.gauss(0, vol)) + vol * 0.3
            
            high_price = open_price + high_move
            low_price = open_price - low_move
            close_price = open_price + trend
            close_price = max(low_price, min(high_price, close_price))
            
            candle = Candle(
                timestamp=current_time,
                open=round(open_price, 5 if asset == Asset.EURUSD else 2),
                high=round(high_price, 5 if asset == Asset.EURUSD else 2),
                low=round(low_price, 5 if asset == Asset.EURUSD else 2),
                close=round(close_price, 5 if asset == Asset.EURUSD else 2),
                volume=random.randint(100, 1000)
            )
            candles.append(candle)
            
            current_price = close_price
            current_time += delta
        
        return candles
    
    def get_status(self) -> ProviderStatus:
        """Get provider health status"""
        return ProviderStatus(
            is_connected=self.is_connected,
            is_streaming=self.is_connected,
            last_update=self.last_update_time,
            provider_name=self.get_provider_name(),
            error_message="⚠️  SIMULATION MODE - Not real market data"
        )
    
    def get_provider_name(self) -> str:
        """Get provider name"""
        return "Simulation (Dev Only)"
