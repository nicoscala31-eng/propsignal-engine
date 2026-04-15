"""Market Data Provider Manager - handles provider selection and fallback"""
import os
import logging
import asyncio
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
        self.initialization_error: Optional[str] = None
    
    async def initialize(self) -> bool:
        """Initialize and connect to best available provider with retry logic"""
        
        # Try Twelve Data first (production) with retries
        twelve_data_key = os.getenv('TWELVE_DATA_API_KEY')
        
        if twelve_data_key:
            logger.info(f"🔑 TwelveData API key found: {twelve_data_key[:8]}...{twelve_data_key[-4:]}")
            
            # Try up to 3 times with increasing delays
            for attempt in range(3):
                logger.info(f"📡 Attempting to connect to Twelve Data (attempt {attempt + 1}/3)...")
                
                try:
                    self.twelve_data_provider = TwelveDataProvider(twelve_data_key)
                    connected = await self.twelve_data_provider.connect()
                    
                    if connected:
                        self.current_provider = self.twelve_data_provider
                        self.initialization_error = None
                        logger.info("✅ Connected to Twelve Data (PRODUCTION MODE)")
                        logger.info(f"   Provider: {self.twelve_data_provider.get_provider_name()}")
                        return True
                    else:
                        error_msg = self.twelve_data_provider.error_message or "Unknown connection failure"
                        logger.warning(f"⚠️  TwelveData connect() returned False: {error_msg}")
                        self.initialization_error = error_msg
                        
                        # Check if rate limited - if so, wait and retry
                        if self.twelve_data_provider.is_rate_limited:
                            logger.info("⏳ Rate limited, waiting 60s before retry...")
                            await asyncio.sleep(60)
                        elif attempt < 2:
                            # Wait before retry
                            wait_time = (attempt + 1) * 5
                            logger.info(f"⏳ Waiting {wait_time}s before retry...")
                            await asyncio.sleep(wait_time)
                            
                except Exception as e:
                    logger.error(f"❌ TwelveData connection exception: {type(e).__name__}: {e}")
                    self.initialization_error = str(e)
                    if attempt < 2:
                        await asyncio.sleep(5)
            
            logger.error(f"❌ Failed to connect to TwelveData after 3 attempts. Last error: {self.initialization_error}")
        else:
            logger.warning("⚠️  TWELVE_DATA_API_KEY not configured in environment")
            self.initialization_error = "API key not configured"
        
        # Fallback to simulation if allowed
        if self.use_simulation_fallback:
            logger.warning("=" * 60)
            logger.warning("⚠️  FALLING BACK TO SIMULATION MODE")
            logger.warning("⚠️  PREZZI NON REALI - SOLO PER TESTING")
            logger.warning(f"⚠️  Reason: {self.initialization_error}")
            logger.warning("=" * 60)
            
            self.simulation_provider = SimulationProvider()
            if await self.simulation_provider.connect():
                self.current_provider = self.simulation_provider
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
