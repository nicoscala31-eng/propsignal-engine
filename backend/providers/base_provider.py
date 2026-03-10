"""Abstract base class for market data providers"""
from abc import ABC, abstractmethod
from typing import Optional, List
from datetime import datetime
from dataclasses import dataclass
from models import Candle, Asset, Timeframe

@dataclass
class LiveQuote:
    """Real-time price quote"""
    asset: Asset
    bid: float
    ask: float
    timestamp: datetime
    spread_pips: float
    
    @property
    def mid_price(self) -> float:
        return (self.bid + self.ask) / 2

@dataclass
class ProviderStatus:
    """Provider health status"""
    is_connected: bool
    is_streaming: bool
    last_update: Optional[datetime]
    provider_name: str
    error_message: Optional[str] = None
    
    @property
    def is_healthy(self) -> bool:
        """Check if provider is healthy - connection status only"""
        # For on-demand providers like Twelve Data, we check connection status
        # The actual data freshness is validated per-request
        return self.is_connected
    
    @property
    def last_update_age_seconds(self) -> float:
        """Get age of last update in seconds"""
        if self.last_update is None:
            return float('inf')
        return (datetime.utcnow() - self.last_update).total_seconds()
    
    @property
    def is_data_fresh(self) -> bool:
        """Check if last update is fresh (within 30 seconds)"""
        return self.last_update_age_seconds < 30

class BaseMarketDataProvider(ABC):
    """Abstract base class for all market data providers"""
    
    @abstractmethod
    async def connect(self) -> bool:
        """Establish connection to data source"""
        pass
    
    @abstractmethod
    async def disconnect(self) -> None:
        """Close connection"""
        pass
    
    @abstractmethod
    async def get_live_quote(self, asset: Asset) -> Optional[LiveQuote]:
        """Get current live quote with bid/ask"""
        pass
    
    @abstractmethod
    async def get_candles(self, asset: Asset, timeframe: Timeframe, count: int = 100) -> List[Candle]:
        """Get recent historical candles"""
        pass
    
    @abstractmethod
    async def get_historical_candles(self, asset: Asset, timeframe: Timeframe,
                                    start_date: datetime, end_date: datetime) -> List[Candle]:
        """Get historical candles for backtesting"""
        pass
    
    @abstractmethod
    def get_status(self) -> ProviderStatus:
        """Get provider health status"""
        pass
    
    @abstractmethod
    def get_provider_name(self) -> str:
        """Get provider name"""
        pass
