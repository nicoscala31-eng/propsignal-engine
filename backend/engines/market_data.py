"""Market Data Provider - Abstract interface with Mock implementation"""
from abc import ABC, abstractmethod
from typing import List, Optional
from datetime import datetime, timedelta
import random
import math
from models import Candle, Asset, Timeframe

class MarketDataProvider(ABC):
    """Abstract base class for market data providers"""
    
    @abstractmethod
    async def get_current_price(self, asset: Asset) -> float:
        """Get current price for an asset"""
        pass
    
    @abstractmethod
    async def get_candles(self, asset: Asset, timeframe: Timeframe, count: int = 100) -> List[Candle]:
        """Get recent candles for an asset"""
        pass
    
    @abstractmethod
    async def get_historical_candles(self, asset: Asset, timeframe: Timeframe, 
                                    start_date: datetime, end_date: datetime) -> List[Candle]:
        """Get historical candles for backtesting"""
        pass

class MockMarketDataProvider(MarketDataProvider):
    """Mock market data provider with realistic price simulation"""
    
    def __init__(self):
        # Base prices
        self.base_prices = {
            Asset.EURUSD: 1.08500,
            Asset.XAUUSD: 2650.00
        }
        
        # Volatility characteristics
        self.volatility = {
            Asset.EURUSD: 0.0002,  # ~20 pips per candle average
            Asset.XAUUSD: 0.50     # ~$0.50 per candle average
        }
        
        self.timeframe_multipliers = {
            Timeframe.M5: 1,
            Timeframe.M15: 1.7,
            Timeframe.H1: 3.5,
            Timeframe.H4: 7,
            Timeframe.D1: 14
        }
    
    async def get_current_price(self, asset: Asset) -> float:
        """Get simulated current price"""
        base = self.base_prices[asset]
        vol = self.volatility[asset]
        # Random walk
        change = random.gauss(0, vol * 5)
        return base + change
    
    async def get_candles(self, asset: Asset, timeframe: Timeframe, count: int = 100) -> List[Candle]:
        """Generate realistic candles using random walk"""
        candles = []
        base_price = self.base_prices[asset]
        vol = self.volatility[asset] * self.timeframe_multipliers[timeframe]
        
        # Calculate time delta based on timeframe
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
            # Generate OHLC
            open_price = current_price
            
            # Trend component (small drift)
            trend = random.gauss(0, vol * 0.5)
            
            # Intrabar volatility
            high_move = abs(random.gauss(0, vol)) + vol * 0.3
            low_move = abs(random.gauss(0, vol)) + vol * 0.3
            
            high_price = open_price + high_move
            low_price = open_price - low_move
            
            # Close with trend
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
        """Generate historical candles for backtesting"""
        # Calculate number of candles needed
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
        
        # Limit to reasonable size
        count = min(count, 100000)
        
        candles = []
        base_price = self.base_prices[asset]
        vol = self.volatility[asset] * self.timeframe_multipliers[timeframe]
        
        current_price = base_price * random.uniform(0.95, 1.05)  # Start with some variation
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

# Singleton instance
market_data_provider = MockMarketDataProvider()
