"""
MATH ENGINE SIGNAL GENERATOR V1.0
=================================

Questo è l'UNICO motore di trading attivo.
Sostituisce completamente il Signal Generator V3.

REGOLE MATEMATICHE PURE:
- Candela bullish: close > open AND body_ratio >= 0.55 AND close_position >= 0.65
- Trend: almeno 2 HH e 2 HL consecutivi
- Impulso: >= 1.5 ATR
- Pullback: 38-62% Fibonacci
- Sessione: SOLO New York (15:00-18:00 Italy)
- Direzione: SOLO BUY
- RR: >= 1.0
"""

import asyncio
import logging
from datetime import datetime, timezone
from typing import Dict, List, Optional, Any
from dataclasses import asdict

from services.math_engine import math_engine, SignalResult
from services.market_data_cache import market_data_cache
from services.push_notification_service import push_service
from models import Asset, Timeframe

logger = logging.getLogger(__name__)


class MathEngineSignalGenerator:
    """
    Signal Generator basato esclusivamente sul Math Engine.
    
    Loop di scansione automatico ogni 60 secondi.
    Genera segnali SOLO quando TUTTE le condizioni matematiche sono soddisfatte.
    """
    
    def __init__(self):
        self.is_running = False
        self.scan_interval = 60  # secondi
        self.assets = [Asset.EURUSD, Asset.XAUUSD]
        
        # Statistics
        self.total_scans = 0
        self.signals_generated = 0
        self.notifications_sent = 0
        self.last_scan_time: Optional[str] = None
        
        # Duplicate prevention
        self.recent_signals: Dict[str, str] = {}  # symbol -> last_signal_timestamp
        self.duplicate_window_minutes = 30
        
        # Pending signals for outcome tracking
        self.pending_signals: List[Dict] = []
        
        logger.info("=" * 60)
        logger.info("MATH ENGINE SIGNAL GENERATOR V1.0 INITIALIZED")
        logger.info("=" * 60)
        logger.info(f"  Assets: {[a.value for a in self.assets]}")
        logger.info(f"  Scan interval: {self.scan_interval}s")
        logger.info(f"  Duplicate window: {self.duplicate_window_minutes} min")
        logger.info("=" * 60)
    
    async def start(self):
        """Start the scanning loop"""
        if self.is_running:
            logger.warning("Math Engine Signal Generator already running")
            return
        
        self.is_running = True
        logger.info("🚀 MATH ENGINE SIGNAL GENERATOR STARTED")
        
        while self.is_running:
            try:
                await self._scan_all_assets()
                await asyncio.sleep(self.scan_interval)
            except asyncio.CancelledError:
                logger.info("Math Engine Signal Generator cancelled")
                break
            except Exception as e:
                logger.error(f"Error in scan loop: {e}")
                await asyncio.sleep(10)
    
    def stop(self):
        """Stop the scanning loop"""
        self.is_running = False
        logger.info("🛑 MATH ENGINE SIGNAL GENERATOR STOPPED")
    
    async def _scan_all_assets(self):
        """Scan all assets for signals"""
        self.total_scans += 1
        self.last_scan_time = datetime.utcnow().isoformat()
        
        for asset in self.assets:
            try:
                await self._scan_asset(asset)
            except Exception as e:
                logger.error(f"Error scanning {asset.value}: {e}")
    
    async def _scan_asset(self, asset: Asset):
        """Scan single asset using Math Engine"""
        symbol = asset.value
        
        # Get M5 candles
        candles_m5 = market_data_cache.get_candles(asset, Timeframe.M5)
        if not candles_m5 or len(candles_m5) < 30:
            logger.debug(f"[{symbol}] Insufficient candle data")
            return
        
        # Get current price
        price_data = market_data_cache.get_price(asset)
        if not price_data:
            logger.debug(f"[{symbol}] No price data")
            return
        
        current_price = price_data.mid
        spread = getattr(price_data, 'spread', 0)
        
        # Convert candles to dict format
        candles_dict = []
        for c in candles_m5:
            if isinstance(c, dict):
                candles_dict.append(c)
            else:
                candles_dict.append({
                    'datetime': getattr(c, 'datetime', ''),
                    'open': getattr(c, 'open', 0),
                    'high': getattr(c, 'high', 0),
                    'low': getattr(c, 'low', 0),
                    'close': getattr(c, 'close', 0)
                })
        
        # Run Math Engine analysis
        result = math_engine.analyze(
            symbol=symbol,
            candles_m5=candles_dict,
            current_price=current_price,
            spread=spread
        )
        
        # Log result
        self._log_result(result)
        
        # If signal is valid, process it
        if result.signal_valid:
            await self._process_valid_signal(result)
    
    def _log_result(self, result: SignalResult):
        """Log analysis result"""
        status = "✅ VALID SIGNAL" if result.signal_valid else "❌ REJECTED"
        
        # Compact log for rejected (fuori sessione)
        if not result.ny_optimal:
            logger.debug(f"[MATH] {result.symbol} {status} (fuori sessione NY, hour={result.session_hour_italy})")
            return
        
        # Detailed log for NY session
        logger.info(f"[MATH] {result.symbol} {result.direction} {status}")
        logger.info(f"  Session: {result.session} (NY={result.ny_optimal})")
        logger.info(f"  Candle: bullish={result.bullish_candle}, body={result.body_ratio:.2f}, pos={result.close_position:.2f}")
        logger.info(f"  Trend: valid={result.bullish_trend_valid}, HH={result.higher_highs}, HL={result.higher_lows}")
        logger.info(f"  Impulse: valid={result.bullish_impulse}, strength={result.impulse_atr_multiple:.2f}")
        logger.info(f"  Pullback: valid={result.pullback_valid}, ratio={result.pullback_ratio:.3f}")
        logger.info(f"  RR: {result.rr_ratio:.2f}, valid={result.rr_valid}")
        
        if result.rejection_reasons:
            for reason in result.rejection_reasons:
                logger.info(f"  → {reason}")
    
    async def _process_valid_signal(self, result: SignalResult):
        """Process a valid signal - send notification"""
        symbol = result.symbol
        
        # Check for duplicate
        if self._is_duplicate(symbol):
            logger.info(f"[MATH] {symbol} Signal duplicate - skipping notification")
            return
        
        # Update recent signals
        self.recent_signals[symbol] = result.timestamp
        self.signals_generated += 1
        
        # Create notification
        title = f"🎯 {symbol} BUY Signal"
        body = self._format_notification_body(result)
        
        # Signal data for app
        data = {
            "type": "math_engine_signal",
            "signal_id": f"MATH_{symbol}_{datetime.utcnow().strftime('%Y%m%d_%H%M%S')}",
            "symbol": symbol,
            "direction": result.direction,
            "entry": str(result.entry_price),
            "stop_loss": str(result.stop_loss),
            "take_profit": str(result.take_profit),
            "rr": str(round(result.rr_ratio, 2)),
            "impulse_strength": str(round(result.impulse_atr_multiple, 2)),
            "pullback_ratio": str(round(result.pullback_ratio, 3)),
            "timestamp": result.timestamp
        }
        
        # Send push notification
        try:
            await push_service.send_to_all(
                title=title,
                body=body,
                data=data
            )
            self.notifications_sent += 1
            logger.info(f"📤 [MATH] Notification sent for {symbol}")
        except Exception as e:
            logger.error(f"Error sending notification: {e}")
        
        # Add to pending signals for tracking
        self.pending_signals.append({
            "signal_id": data["signal_id"],
            "result": asdict(result),
            "sent_at": datetime.utcnow().isoformat()
        })
    
    def _format_notification_body(self, result: SignalResult) -> str:
        """Format notification body"""
        return (
            f"Entry: {result.entry_price:.5f}\n"
            f"SL: {result.stop_loss:.5f}\n"
            f"TP: {result.take_profit:.5f}\n"
            f"R:R: {result.rr_ratio:.2f}\n"
            f"Impulse: {result.impulse_atr_multiple:.2f}x ATR\n"
            f"Pullback: {result.pullback_ratio:.1%} Fib"
        )
    
    def _is_duplicate(self, symbol: str) -> bool:
        """Check if signal is duplicate within window"""
        if symbol not in self.recent_signals:
            return False
        
        last_signal_time = self.recent_signals[symbol]
        try:
            last_dt = datetime.fromisoformat(last_signal_time.replace('Z', '+00:00'))
            now = datetime.now(timezone.utc)
            diff_minutes = (now - last_dt).total_seconds() / 60
            return diff_minutes < self.duplicate_window_minutes
        except:
            return False
    
    def get_status(self) -> Dict:
        """Get generator status"""
        return {
            "engine": "Math Engine Signal Generator V1.0",
            "is_running": self.is_running,
            "scan_interval_seconds": self.scan_interval,
            "assets": [a.value for a in self.assets],
            "last_scan": self.last_scan_time,
            "statistics": {
                "total_scans": self.total_scans,
                "signals_generated": self.signals_generated,
                "notifications_sent": self.notifications_sent
            },
            "duplicate_window_minutes": self.duplicate_window_minutes,
            "pending_signals_count": len(self.pending_signals),
            "math_engine_stats": math_engine.get_statistics(),
            "config": {
                "session": "New York only (15:00-18:00 Italy)",
                "direction": "BUY only",
                "impulse_threshold": "1.5x ATR",
                "pullback_zone": "38-62% Fibonacci",
                "min_rr": "1.0",
                "candle_body_ratio": ">=0.55",
                "candle_close_position": ">=0.65",
                "trend_requirement": "2+ HH and 2+ HL"
            }
        }


# Global instance
math_signal_generator = MathEngineSignalGenerator()


async def start_math_signal_generator():
    """Start the Math Engine Signal Generator"""
    await math_signal_generator.start()


def stop_math_signal_generator():
    """Stop the Math Engine Signal Generator"""
    math_signal_generator.stop()
