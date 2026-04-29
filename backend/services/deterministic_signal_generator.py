"""
DETERMINISTIC PATTERN SIGNAL GENERATOR V2.0
============================================

Questo è l'UNICO motore di trading attivo.
Sostituisce completamente Math Engine V1.0 e tutti i precedenti.

REGOLE:
- Pattern deterministico: TREND, RANGE, COMPRESSION, FALSE_BREAKOUT
- NO score, NO checklist, NO penalità, NO fuzzy logic
- Segnale valido SOLO se tutte le condizioni matematiche sono vere
- RR >= 1.30
- Expected Edge > 0

Loop di scansione automatico ogni 60 secondi.
"""

import asyncio
import logging
from datetime import datetime, timezone
from typing import Dict, List, Optional, Any

from services.deterministic_pattern_engine import (
    deterministic_engine, 
    PatternResult, 
    ValidationStatus,
    PatternType,
    SignalDirection
)
from services.market_data_cache import market_data_cache
from services.push_notification_service import push_service
from services.signal_snapshot_service import signal_snapshot_service
from models import Asset, Timeframe

logger = logging.getLogger(__name__)


class DeterministicPatternSignalGenerator:
    """
    Signal Generator basato sul Deterministic Pattern Engine.
    
    Loop di scansione automatico.
    Genera segnali SOLO quando pattern deterministico è valido.
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
        self.recent_signals: Dict[str, str] = {}
        self.duplicate_window_minutes = 30
        
        # Pending signals
        self.pending_signals: List[Dict] = []
        
        logger.info("=" * 60)
        logger.info("DETERMINISTIC PATTERN SIGNAL GENERATOR V2.0")
        logger.info("=" * 60)
        logger.info(f"  Assets: {[a.value for a in self.assets]}")
        logger.info(f"  Scan interval: {self.scan_interval}s")
        logger.info(f"  Duplicate window: {self.duplicate_window_minutes} min")
        logger.info(f"  Min RR: {deterministic_engine.params.min_rr}")
        logger.info("=" * 60)
    
    async def start(self):
        """Start the scanning loop"""
        if self.is_running:
            logger.warning("Deterministic Pattern Generator already running")
            return
        
        self.is_running = True
        logger.info("🚀 DETERMINISTIC PATTERN SIGNAL GENERATOR STARTED")
        
        while self.is_running:
            try:
                await self._scan_all_assets()
                await asyncio.sleep(self.scan_interval)
            except asyncio.CancelledError:
                logger.info("Deterministic Pattern Generator cancelled")
                break
            except Exception as e:
                logger.error(f"Error in scan loop: {e}")
                await asyncio.sleep(10)
    
    def stop(self):
        """Stop the scanning loop"""
        self.is_running = False
        logger.info("🛑 DETERMINISTIC PATTERN SIGNAL GENERATOR STOPPED")
    
    async def _scan_all_assets(self):
        """Scan all assets"""
        self.total_scans += 1
        self.last_scan_time = datetime.utcnow().isoformat()
        
        for asset in self.assets:
            try:
                await self._scan_asset(asset)
            except Exception as e:
                logger.error(f"Error scanning {asset.value}: {e}")
    
    async def _scan_asset(self, asset: Asset):
        """Scan single asset using Deterministic Pattern Engine"""
        symbol = asset.value
        
        # Get M5 candles
        candles_m5 = market_data_cache.get_candles(asset, Timeframe.M5)
        if not candles_m5 or len(candles_m5) < 30:
            logger.debug(f"[{symbol}] Insufficient candle data")
            return
        
        # Get current price and spread
        price_data = market_data_cache.get_price(asset)
        spread = 0.0
        if price_data:
            spread = getattr(price_data, 'spread', 0) or 0.0
        
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
        
        # Run Deterministic Pattern Engine analysis
        result = deterministic_engine.analyze(
            symbol=symbol,
            candles_raw=candles_dict,
            spread=spread
        )
        
        # Log result
        self._log_result(result)
        
        # Save snapshot (for both valid and rejected)
        await self._save_snapshot(result)
        
        # If signal is valid, process it
        if result.status == ValidationStatus.VALID.value:
            await self._process_valid_signal(result)
    
    def _log_result(self, result: PatternResult):
        """Log analysis result"""
        status = "✅ VALID" if result.status == ValidationStatus.VALID.value else "❌ REJECTED"
        
        logger.info(f"[PATTERN] {result.symbol} {result.direction} {status}")
        logger.info(f"  Pattern: {result.pattern_type} | Regime: {result.regime}")
        
        if result.status == ValidationStatus.VALID.value:
            logger.info(f"  Entry: {result.entry:.5f} | SL: {result.stop_loss:.5f} | TP: {result.take_profit:.5f}")
            logger.info(f"  RR: {result.rr:.2f} | Winrate: {result.winrate:.0%} | Edge: {result.expected_edge_R:.4f}")
        else:
            logger.info(f"  Rejection: {result.rejection_reason}")
        
        # Log key metrics
        if result.metrics:
            logger.info(f"  Metrics: T={result.metrics.get('T_t', 0):.3f} Z={result.metrics.get('Z_t', 0):.2f} ATR={result.metrics.get('ATR_t', 0):.5f}")
    
    async def _save_snapshot(self, result: PatternResult):
        """Save signal snapshot for feed"""
        try:
            signal_id = f"PAT_{result.symbol}_{datetime.utcnow().strftime('%Y%m%d_%H%M%S')}"
            
            # Convert to SignalSnapshot object with correct fields
            from services.signal_snapshot_service import SignalSnapshot
            snapshot = SignalSnapshot(
                signal_id=signal_id,
                timestamp=result.timestamp,
                symbol=result.symbol,
                direction=result.direction,
                session='Any',
                setup_type=result.pattern_type,
                entry_price=result.entry,
                stop_loss=result.stop_loss,
                take_profit=result.take_profit,
                rr_ratio=result.rr,
                status='accepted' if result.status == ValidationStatus.VALID.value else 'rejected',
                rejection_reason=result.rejection_reason if result.status != ValidationStatus.VALID.value else '',
                blocking_filter='',
                score_pre_penalty=0.0,
                score_post_penalty=0.0,
                final_score=0.0,
                confidence_bucket='0',
                # Pattern Engine V2.0 data
                pattern_type=result.pattern_type,
                regime=result.regime,
                winrate=result.winrate,
                expected_edge=result.expected_edge_R,
                metrics=result.metrics,
                conditions=result.conditions,
            )
            # Add pattern-specific data to short_reason and summary fields
            if result.status == ValidationStatus.VALID.value:
                snapshot.summary_short = f"{result.pattern_type} | RR {result.rr:.2f} | Edge {result.expected_edge_R:.4f}"
                snapshot.summary_full = f"Pattern: {result.pattern_type}, Regime: {result.regime}, Direction: {result.direction}, Entry: {result.entry}, SL: {result.stop_loss}, TP: {result.take_profit}, RR: {result.rr:.2f}, Winrate: {result.winrate:.0%}, Expected Edge: {result.expected_edge_R:.4f}R"
            else:
                snapshot.summary_short = result.rejection_reason
                snapshot.summary_full = f"Signal rejected: {result.rejection_reason}. Pattern: {result.pattern_type}, Regime: {result.regime}"
            
            await signal_snapshot_service.save_snapshot(snapshot)
            
        except Exception as e:
            logger.error(f"Error saving snapshot: {e}")
    
    async def _process_valid_signal(self, result: PatternResult):
        """Process a valid signal - send notification"""
        symbol = result.symbol
        
        # Check for duplicate
        if self._is_duplicate(symbol):
            logger.info(f"[PATTERN] {symbol} Signal duplicate - skipping notification")
            return
        
        # Update recent signals
        self.recent_signals[symbol] = result.timestamp
        self.signals_generated += 1
        
        # Create notification
        direction_emoji = "🟢" if result.direction == SignalDirection.BUY.value else "🔴"
        title = f"{direction_emoji} {symbol} {result.direction} — {result.pattern_type.replace('_', ' ')}"
        body = self._format_notification_body(result)
        
        # Signal data for app
        signal_id = f"PAT_{symbol}_{datetime.utcnow().strftime('%Y%m%d_%H%M%S')}"
        data = {
            "type": "pattern_signal",
            "signal_id": signal_id,
            "symbol": symbol,
            "direction": result.direction,
            "pattern": result.pattern_type,
            "regime": result.regime,
            "entry": str(round(result.entry, 6)),
            "stop_loss": str(round(result.stop_loss, 6)),
            "take_profit": str(round(result.take_profit, 6)),
            "rr": str(round(result.rr, 2)),
            "expected_edge": str(round(result.expected_edge_R, 4)),
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
            logger.info(f"📤 [PATTERN] Notification sent for {symbol}")
        except Exception as e:
            logger.error(f"Error sending notification: {e}")
        
        # Add to pending signals
        self.pending_signals.append({
            "signal_id": signal_id,
            "result": result.to_dict(),
            "sent_at": datetime.utcnow().isoformat()
        })
    
    def _format_notification_body(self, result: PatternResult) -> str:
        """Format notification body"""
        # Determine precision based on symbol
        if 'XAU' in result.symbol:
            price_fmt = ".2f"
        else:
            price_fmt = ".5f"
        
        return (
            f"Entry: {result.entry:{price_fmt}}\n"
            f"SL: {result.stop_loss:{price_fmt}}\n"
            f"TP: {result.take_profit:{price_fmt}}\n"
            f"RR: {result.rr:.2f}\n"
            f"Edge: {result.expected_edge_R:.4f}R"
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
        except Exception:
            return False
    
    def get_status(self) -> Dict:
        """Get generator status"""
        return {
            "engine": "Deterministic Pattern Signal Generator V2.0",
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
            "engine_stats": deterministic_engine.get_statistics(),
            "config": {
                "patterns": ["TREND_CONTINUATION", "MEAN_REVERSION", "COMPRESSION_BREAKOUT", "FALSE_BREAKOUT"],
                "min_rr": deterministic_engine.params.min_rr,
                "trend_threshold": deterministic_engine.params.trend_strength_threshold,
                "z_threshold": deterministic_engine.params.z_threshold,
                "swing_K": deterministic_engine.params.K,
                "rolling_N": deterministic_engine.params.N,
                "winrates": {
                    "trend": deterministic_engine.params.winrate_trend,
                    "mean_reversion": deterministic_engine.params.winrate_mean_reversion,
                    "breakout": deterministic_engine.params.winrate_breakout,
                    "false_breakout": deterministic_engine.params.winrate_false_breakout
                }
            }
        }


# Global instance
deterministic_signal_generator = DeterministicPatternSignalGenerator()


async def start_deterministic_signal_generator():
    """Start the Deterministic Pattern Signal Generator"""
    await deterministic_signal_generator.start()


def stop_deterministic_signal_generator():
    """Stop the Deterministic Pattern Signal Generator"""
    deterministic_signal_generator.stop()
