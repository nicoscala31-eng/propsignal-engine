"""Signal Outcome Tracker - Automatic trade outcome monitoring and lifecycle management"""
import asyncio
import logging
from typing import Dict, List, Optional, Any
from datetime import datetime, timedelta
from dataclasses import dataclass

from models import Asset, Signal, SignalType, SignalOutcome, SignalLifecycle
from providers.provider_manager import provider_manager

logger = logging.getLogger(__name__)


@dataclass
class OutcomeResult:
    """Result of outcome check"""
    signal_id: str
    outcome: SignalOutcome
    outcome_price: Optional[float] = None
    outcome_pips: Optional[float] = None
    outcome_rr: Optional[float] = None
    lifecycle_stage: Optional[SignalLifecycle] = None


class SignalOutcomeTracker:
    """
    Automatic signal outcome tracking service
    
    Features:
    - Monitors active signals
    - Detects TP/SL hits automatically
    - Updates signal outcomes in database
    - Tracks full signal lifecycle
    - Invalidates stale signals
    """
    
    def __init__(self, db):
        self.db = db
        self.is_running = False
        self.check_interval = 10  # seconds between checks
        self.max_signal_age_hours = 24  # Invalidate signals older than this
        
        # Statistics
        self.checks_performed = 0
        self.tp_hits = 0
        self.sl_hits = 0
        self.invalidations = 0
    
    async def start(self):
        """Start the outcome tracker"""
        if self.is_running:
            logger.warning("Outcome tracker already running")
            return
        
        self.is_running = True
        logger.info("📈 Signal Outcome Tracker started")
        asyncio.create_task(self._run_tracker_loop())
    
    async def stop(self):
        """Stop the outcome tracker"""
        self.is_running = False
        logger.info("🛑 Signal Outcome Tracker stopped")
    
    async def _run_tracker_loop(self):
        """Main tracking loop"""
        while self.is_running:
            try:
                await self._check_active_signals()
            except Exception as e:
                logger.error(f"Outcome tracker error: {e}", exc_info=True)
            
            await asyncio.sleep(self.check_interval)
    
    async def _check_active_signals(self):
        """Check all active signals for outcome"""
        self.checks_performed += 1
        
        # Get active BUY/SELL signals
        active_signals = await self.db.signals.find({
            "is_active": True,
            "is_resolved": {"$ne": True},
            "signal_type": {"$in": ["BUY", "SELL"]}
        }).to_list(1000)
        
        if not active_signals:
            return
        
        logger.debug(f"Checking {len(active_signals)} active signals")
        
        for signal_data in active_signals:
            try:
                await self._check_signal_outcome(signal_data)
            except Exception as e:
                logger.error(f"Error checking signal {signal_data.get('id')}: {e}")
    
    async def _check_signal_outcome(self, signal_data: Dict[str, Any]):
        """
        Check a single signal for TP/SL hit or invalidation
        
        Args:
            signal_data: Signal document from database
        """
        signal_id = signal_data.get("id")
        asset_str = signal_data.get("asset")
        signal_type = signal_data.get("signal_type")
        entry_price = signal_data.get("entry_price")
        stop_loss = signal_data.get("stop_loss")
        take_profit_1 = signal_data.get("take_profit_1")
        take_profit_2 = signal_data.get("take_profit_2")
        created_at = signal_data.get("created_at")
        
        if not all([asset_str, entry_price, stop_loss]):
            return
        
        # Get current price
        try:
            asset = Asset(asset_str)
        except ValueError:
            return
        
        provider = provider_manager.get_provider()
        if not provider:
            return
        
        quote = await provider.get_live_quote(asset)
        if not quote:
            return
        
        current_price = quote.mid_price
        
        # Check for invalidation (too old)
        if created_at:
            age_hours = (datetime.utcnow() - created_at).total_seconds() / 3600
            if age_hours > self.max_signal_age_hours:
                await self._mark_invalidated(signal_id, "Signal expired - max age exceeded")
                self.invalidations += 1
                return
        
        # Calculate pip value
        pip_value = 0.0001 if asset == Asset.EURUSD else 0.1
        
        # Check entry trigger (if not already triggered)
        lifecycle_stage = signal_data.get("lifecycle_stage", "signal_created")
        if lifecycle_stage == "signal_created":
            entry_zone_low = signal_data.get("entry_zone_low", entry_price * 0.9999)
            entry_zone_high = signal_data.get("entry_zone_high", entry_price * 1.0001)
            
            if entry_zone_low <= current_price <= entry_zone_high:
                await self._update_lifecycle(signal_id, SignalLifecycle.ENTRY_TRIGGERED, current_price)
                lifecycle_stage = "entry_triggered"
        
        # Only check TP/SL after entry triggered
        if lifecycle_stage in ["signal_created"]:
            return
        
        # Check for TP1 hit
        if take_profit_1:
            if signal_type == "BUY" and current_price >= take_profit_1:
                pips = (current_price - entry_price) / pip_value
                rr = pips / ((entry_price - stop_loss) / pip_value) if stop_loss else 0
                await self._mark_tp_hit(signal_id, 1, current_price, pips, rr)
                self.tp_hits += 1
                return
            elif signal_type == "SELL" and current_price <= take_profit_1:
                pips = (entry_price - current_price) / pip_value
                rr = pips / ((stop_loss - entry_price) / pip_value) if stop_loss else 0
                await self._mark_tp_hit(signal_id, 1, current_price, pips, rr)
                self.tp_hits += 1
                return
        
        # Check for SL hit
        if signal_type == "BUY" and current_price <= stop_loss:
            pips = (entry_price - current_price) / pip_value
            await self._mark_sl_hit(signal_id, current_price, -pips)
            self.sl_hits += 1
            return
        elif signal_type == "SELL" and current_price >= stop_loss:
            pips = (current_price - entry_price) / pip_value
            await self._mark_sl_hit(signal_id, current_price, -pips)
            self.sl_hits += 1
            return
        
        # Update to trade_active if entry triggered
        if lifecycle_stage == "entry_triggered":
            await self._update_lifecycle(signal_id, SignalLifecycle.TRADE_ACTIVE, current_price)
    
    async def _mark_tp_hit(
        self,
        signal_id: str,
        tp_level: int,
        price: float,
        pips: float,
        rr: float
    ):
        """Mark a signal as TP hit"""
        now = datetime.utcnow()
        
        update = {
            "is_active": False,
            "is_resolved": True,
            "outcome": SignalOutcome.TP1_HIT.value if tp_level == 1 else SignalOutcome.TP2_HIT.value,
            "outcome_price": price,
            "outcome_pips": round(pips, 1),
            "outcome_rr_achieved": round(rr, 2),
            "lifecycle_stage": SignalLifecycle.TP1_HIT.value if tp_level == 1 else SignalLifecycle.TP2_HIT.value,
            f"tp{tp_level}_hit": True,
            f"tp{tp_level}_hit_at": now,
            "resolved_at": now
        }
        
        # Add lifecycle history entry
        lifecycle_entry = {
            "stage": SignalLifecycle.TP1_HIT.value if tp_level == 1 else SignalLifecycle.TP2_HIT.value,
            "timestamp": now.isoformat(),
            "price": price,
            "pips": round(pips, 1),
            "rr": round(rr, 2)
        }
        
        await self.db.signals.update_one(
            {"id": signal_id},
            {
                "$set": update,
                "$push": {"lifecycle_history": lifecycle_entry}
            }
        )
        
        logger.info(f"✅ Signal {signal_id[:10]}... TP{tp_level} HIT @ {price} (+{pips:.1f} pips, {rr:.2f}R)")
    
    async def _mark_sl_hit(self, signal_id: str, price: float, pips: float):
        """Mark a signal as SL hit"""
        now = datetime.utcnow()
        
        update = {
            "is_active": False,
            "is_resolved": True,
            "outcome": SignalOutcome.SL_HIT.value,
            "outcome_price": price,
            "outcome_pips": round(pips, 1),
            "outcome_rr_achieved": -1.0,
            "lifecycle_stage": SignalLifecycle.SL_HIT.value,
            "sl_hit": True,
            "sl_hit_at": now,
            "resolved_at": now
        }
        
        lifecycle_entry = {
            "stage": SignalLifecycle.SL_HIT.value,
            "timestamp": now.isoformat(),
            "price": price,
            "pips": round(pips, 1)
        }
        
        await self.db.signals.update_one(
            {"id": signal_id},
            {
                "$set": update,
                "$push": {"lifecycle_history": lifecycle_entry}
            }
        )
        
        logger.info(f"❌ Signal {signal_id[:10]}... SL HIT @ {price} ({pips:.1f} pips)")
    
    async def _mark_invalidated(self, signal_id: str, reason: str):
        """Mark a signal as invalidated"""
        now = datetime.utcnow()
        
        update = {
            "is_active": False,
            "is_resolved": True,
            "outcome": SignalOutcome.INVALIDATED.value,
            "lifecycle_stage": SignalLifecycle.INVALIDATED.value,
            "invalidated_at": now,
            "resolved_at": now
        }
        
        lifecycle_entry = {
            "stage": SignalLifecycle.INVALIDATED.value,
            "timestamp": now.isoformat(),
            "reason": reason
        }
        
        await self.db.signals.update_one(
            {"id": signal_id},
            {
                "$set": update,
                "$push": {"lifecycle_history": lifecycle_entry}
            }
        )
        
        logger.info(f"⚠️ Signal {signal_id[:10]}... INVALIDATED: {reason}")
    
    async def _update_lifecycle(
        self,
        signal_id: str,
        stage: SignalLifecycle,
        price: Optional[float] = None
    ):
        """Update signal lifecycle stage"""
        now = datetime.utcnow()
        
        update = {"lifecycle_stage": stage.value}
        
        if stage == SignalLifecycle.ENTRY_TRIGGERED:
            update["entry_triggered_at"] = now
        elif stage == SignalLifecycle.TRADE_ACTIVE:
            update["trade_active_at"] = now
        
        lifecycle_entry = {
            "stage": stage.value,
            "timestamp": now.isoformat()
        }
        if price:
            lifecycle_entry["price"] = price
        
        await self.db.signals.update_one(
            {"id": signal_id},
            {
                "$set": update,
                "$push": {"lifecycle_history": lifecycle_entry}
            }
        )
        
        logger.debug(f"📊 Signal {signal_id[:10]}... lifecycle: {stage.value}")
    
    def get_stats(self) -> Dict[str, Any]:
        """Get tracker statistics"""
        return {
            "is_running": self.is_running,
            "checks_performed": self.checks_performed,
            "tp_hits": self.tp_hits,
            "sl_hits": self.sl_hits,
            "invalidations": self.invalidations,
            "check_interval_seconds": self.check_interval,
            "max_signal_age_hours": self.max_signal_age_hours
        }


# Global instance
outcome_tracker: Optional[SignalOutcomeTracker] = None


def init_outcome_tracker(db) -> SignalOutcomeTracker:
    """Initialize the outcome tracker with database connection"""
    global outcome_tracker
    outcome_tracker = SignalOutcomeTracker(db)
    return outcome_tracker
