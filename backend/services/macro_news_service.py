"""Macro News Service - High-impact economic news detection for trading signals"""
import asyncio
import aiohttp
import logging
from typing import List, Dict, Optional, Any
from datetime import datetime, timedelta
from dataclasses import dataclass

from models import Asset

logger = logging.getLogger(__name__)


@dataclass
class NewsEvent:
    """Economic news event"""
    event_name: str
    currency: str
    impact: str  # "high", "medium", "low"
    event_time: datetime
    forecast: Optional[str] = None
    previous: Optional[str] = None
    actual: Optional[str] = None


class MacroNewsService:
    """
    Macro news detection service
    
    Features:
    - Detects high-impact economic events
    - Warns when signals are near news events
    - Does NOT block signals - only warns
    - Tracks affected currencies
    """
    
    # Major high-impact events that affect forex markets
    HIGH_IMPACT_EVENTS = [
        "NFP", "Non-Farm Payrolls", "Nonfarm Payrolls",
        "CPI", "Consumer Price Index", "Core CPI",
        "FOMC", "Fed Interest Rate Decision", "Federal Funds Rate",
        "ECB", "ECB Interest Rate Decision", "ECB Press Conference",
        "GDP", "Gross Domestic Product",
        "PPI", "Producer Price Index",
        "Retail Sales", "Core Retail Sales",
        "Unemployment Rate", "Unemployment Claims",
        "ISM Manufacturing", "ISM Services",
        "PCE", "Core PCE Price Index",
        "BOE", "Bank of England",
        "BOJ", "Bank of Japan",
        "SNB", "Swiss National Bank"
    ]
    
    # Currency mapping for assets
    ASSET_CURRENCIES = {
        Asset.EURUSD: ["EUR", "USD"],
        Asset.XAUUSD: ["XAU", "USD", "Gold"]
    }
    
    def __init__(self):
        self.session: Optional[aiohttp.ClientSession] = None
        self.news_cache: List[NewsEvent] = []
        self.cache_time: Optional[datetime] = None
        self.cache_duration = 300  # 5 minutes
        
        # Simulated upcoming events (in production, fetch from API)
        self._simulated_events: List[NewsEvent] = []
        self._init_simulated_events()
    
    def _init_simulated_events(self):
        """Initialize simulated news events for testing"""
        now = datetime.utcnow()
        
        # Add some simulated events
        self._simulated_events = [
            NewsEvent(
                event_name="US CPI",
                currency="USD",
                impact="high",
                event_time=now + timedelta(hours=2)
            ),
            NewsEvent(
                event_name="ECB Press Conference",
                currency="EUR",
                impact="high",
                event_time=now + timedelta(hours=6)
            ),
            NewsEvent(
                event_name="NFP",
                currency="USD",
                impact="high",
                event_time=now + timedelta(days=1)
            )
        ]
    
    async def get_upcoming_news(self, hours_ahead: int = 24) -> List[NewsEvent]:
        """
        Get upcoming high-impact news events
        
        Args:
            hours_ahead: How many hours to look ahead
        
        Returns:
            List of upcoming NewsEvent objects
        """
        # Check cache
        if self.cache_time and (datetime.utcnow() - self.cache_time).total_seconds() < self.cache_duration:
            return self.news_cache
        
        # In production, fetch from forex factory or similar API
        # For now, return simulated events
        now = datetime.utcnow()
        cutoff = now + timedelta(hours=hours_ahead)
        
        upcoming = [
            event for event in self._simulated_events
            if now <= event.event_time <= cutoff
        ]
        
        self.news_cache = upcoming
        self.cache_time = datetime.utcnow()
        
        return upcoming
    
    async def check_news_risk(
        self,
        asset: Asset,
        minutes_window: int = 30
    ) -> Dict[str, Any]:
        """
        Check if there's news risk for a specific asset
        
        Args:
            asset: The trading asset
            minutes_window: Minutes before/after news to consider risky
        
        Returns:
            Dictionary with news risk details
        """
        upcoming = await self.get_upcoming_news(hours_ahead=2)
        
        now = datetime.utcnow()
        asset_currencies = self.ASSET_CURRENCIES.get(asset, [])
        
        for event in upcoming:
            # Check if event affects this asset
            if event.currency not in asset_currencies:
                continue
            
            # Check if within time window
            minutes_to_event = (event.event_time - now).total_seconds() / 60
            
            if abs(minutes_to_event) <= minutes_window:
                return {
                    "has_risk": True,
                    "event_name": event.event_name,
                    "event_time": event.event_time.isoformat(),
                    "minutes_to_event": int(minutes_to_event),
                    "impact": event.impact,
                    "currency": event.currency,
                    "warning_message": f"⚠️ {event.event_name} in {int(minutes_to_event)} minutes"
                }
        
        return {
            "has_risk": False,
            "event_name": None,
            "event_time": None,
            "minutes_to_event": None,
            "impact": None,
            "currency": None,
            "warning_message": None
        }
    
    async def get_news_calendar(self, days: int = 7) -> List[Dict[str, Any]]:
        """
        Get news calendar for specified days
        
        Args:
            days: Number of days to look ahead
        
        Returns:
            List of news events as dictionaries
        """
        upcoming = await self.get_upcoming_news(hours_ahead=days * 24)
        
        return [
            {
                "event_name": e.event_name,
                "currency": e.currency,
                "impact": e.impact,
                "event_time": e.event_time.isoformat(),
                "forecast": e.forecast,
                "previous": e.previous
            }
            for e in upcoming
        ]
    
    def add_simulated_event(
        self,
        event_name: str,
        currency: str,
        minutes_from_now: int,
        impact: str = "high"
    ):
        """Add a simulated news event for testing"""
        event = NewsEvent(
            event_name=event_name,
            currency=currency,
            impact=impact,
            event_time=datetime.utcnow() + timedelta(minutes=minutes_from_now)
        )
        self._simulated_events.append(event)
        self.cache_time = None  # Force cache refresh


# Global instance
macro_news_service = MacroNewsService()
