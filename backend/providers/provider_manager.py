"""Market Data Provider Manager - handles provider selection and fallback"""
import os
import logging
from typing import Optional
from providers.base_provider import BaseMarketDataProvider, ProviderStatus
from providers.twelve_data_provider import TwelveDataProvider
from providers.simulation_provider import SimulationProvider

logger = logging.getLogger(__name__)

class ProviderManager:
    """Manages market data provider selection and fallback"""
    
    def __init__(self):
        self.current_provider: Optional[BaseMarketDataProvider] = None
        self.twelve_data_provider: Optional[TwelveDataProvider] = None
        self.simulation_provider: Optional[SimulationProvider] = None
        self.use_simulation_fallback = os.getenv('ALLOW_SIMULATION_FALLBACK', 'true').lower() == 'true'
    
    async def initialize(self) -> bool:
        """Initialize and connect to best available provider"""
        
        # Try Twelve Data first (production)
        twelve_data_key = os.getenv('TWELVE_DATA_API_KEY')
        if twelve_data_key:
            logger.info("Attempting to connect to Twelve Data...")
            self.twelve_data_provider = TwelveDataProvider(twelve_data_key)
            if await self.twelve_data_provider.connect():
                self.current_provider = self.twelve_data_provider
                logger.info("✅ Connected to Twelve Data (PRODUCTION MODE)")
                return True
            else:
                logger.warning("⚠️  Failed to connect to Twelve Data")
        else:
            logger.warning("⚠️  TWELVE_DATA_API_KEY not configured")
        
        # Fallback to simulation if allowed
        if self.use_simulation_fallback:
            logger.warning("⚠️  Falling back to SIMULATION MODE")
            self.simulation_provider = SimulationProvider()
            if await self.simulation_provider.connect():
                self.current_provider = self.simulation_provider
                logger.warning("⚠️  SIMULATION MODE ACTIVE - NOT REAL DATA")
                return True
        else:
            logger.error("❌ No market data provider available and simulation disabled")
            return False
        
        return False
    
    def get_provider(self) -> Optional[BaseMarketDataProvider]:
        """Get current active provider"""
        return self.current_provider
    
    def get_status(self) -> Optional[ProviderStatus]:
        """Get current provider status"""
        if self.current_provider:
            return self.current_provider.get_status()
        return None
    
    def is_simulation_mode(self) -> bool:
        """Check if running in simulation mode"""
        return isinstance(self.current_provider, SimulationProvider)
    
    def is_production_ready(self) -> bool:
        """Check if using production data source"""
        return isinstance(self.current_provider, TwelveDataProvider)
    
    async def shutdown(self):
        """Shutdown all providers"""
        if self.current_provider:
            await self.current_provider.disconnect()
        logger.info("Provider manager shut down")

# Global instance
provider_manager = ProviderManager()
