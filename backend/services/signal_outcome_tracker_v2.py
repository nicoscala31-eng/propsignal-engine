"""
Signal Outcome Tracker - Passive Performance Monitoring
========================================================

DESIGN PHILOSOPHY:
- Observational ONLY - does not affect signal generation
- Lightweight - minimal overhead on scanner
- Non-blocking - async tracking that doesn't slow notifications
- Historical analysis - track performance over time

This module tracks:
- Signal lifecycle (generated → notified → active → outcome)
- Price excursions (MFE/MAE)
- Win/Loss statistics
- Performance by asset, session, confidence bucket
"""

import asyncio
import json
import logging
from typing import Dict, List, Optional, Any
from datetime import datetime, timedelta
from dataclasses import dataclass, field, asdict
from enum import Enum
from pathlib import Path
import aiofiles

from services.candidate_audit_service import candidate_audit_service

logger = logging.getLogger(__name__)


class SignalStatus(Enum):
    """Signal lifecycle states"""
    GENERATED = "generated"
    NOTIFIED = "notified"
    ENTRY_TRIGGERED = "entry_triggered"
    ACTIVE = "active"
    TP_HIT = "tp_hit"
    SL_HIT = "sl_hit"
    EXPIRED = "expired"
    INVALIDATED = "invalidated"


@dataclass
class TrackedSignal:
    """A signal being tracked for outcome analysis"""
    # Core signal data
    signal_id: str
    timestamp: str
    asset: str
    direction: str
    entry_price: float
    stop_loss: float
    take_profit_1: float
    take_profit_2: float
    confidence_score: float
    confidence_level: str
    setup_type: str
    session: str
    invalidation: str
    risk_reward: float
    
    # Score breakdown
    score_breakdown: Dict[str, Any] = field(default_factory=dict)
    
    # Lifecycle tracking
    status: str = SignalStatus.GENERATED.value
    notified_at: Optional[str] = None
    entry_triggered_at: Optional[str] = None
    closed_at: Optional[str] = None
    
    # Price tracking
    max_favorable_excursion: float = 0.0  # Best price in signal direction
    max_adverse_excursion: float = 0.0    # Worst price against signal
    highest_price_seen: float = 0.0
    lowest_price_seen: float = 0.0
    
    # Outcome data
    final_outcome: Optional[str] = None  # "win", "loss", "breakeven", "expired"
    pips_gained: float = 0.0
    pips_lost: float = 0.0
    time_to_outcome_seconds: float = 0.0
    moved_favorable_before_fail: bool = False
    
    # === NEW: Trade Management States ===
    # R-multiple tracking (observational)
    reached_half_r: bool = False          # Reached +0.5R
    reached_one_r: bool = False           # Reached +1R
    reached_two_r: bool = False           # Reached +2R
    
    # Management analysis (what could have been)
    breakeven_possible: bool = False      # Could have moved SL to BE
    partial_profit_possible: bool = False # Could have taken partial at +1R
    trailing_would_improve: bool = False  # Trailing SL would have improved outcome
    
    # Time in favorable/adverse territory
    time_in_profit_seconds: float = 0.0
    time_in_drawdown_seconds: float = 0.0
    
    # Peak profit before reversal (if lost)
    peak_r_before_reversal: float = 0.0
    
    def to_dict(self) -> Dict:
        return asdict(self)
    
    @classmethod
    def from_dict(cls, data: Dict) -> 'TrackedSignal':
        return cls(**data)


class SignalOutcomeTracker:
    """
    Passive Signal Outcome Tracking System
    
    This tracker:
    - Receives signals AFTER they are generated
    - Does NOT affect signal generation or scoring
    - Monitors price action to track outcomes
    - Stores historical performance data
    - Provides analytics endpoints
    """
    
    # Tracking parameters
    EXPIRY_HOURS = 24  # Signal expires after 24 hours if no outcome
    PRICE_CHECK_INTERVAL = 30  # Seconds between price checks
    MAX_TRACKED_SIGNALS = 500  # Keep last 500 signals in memory
    
    def __init__(self, data_dir: str = "/app/backend/data"):
        self.data_dir = Path(data_dir)
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self.signals_file = self.data_dir / "tracked_signals.json"
        self.stats_file = self.data_dir / "signal_stats.json"
        
        # In-memory tracking
        self.active_signals: Dict[str, TrackedSignal] = {}
        self.completed_signals: List[TrackedSignal] = []
        
        # Statistics
        self.stats = {
            "total_tracked": 0,
            "wins": 0,
            "losses": 0,
            "expired": 0,
            "invalidated": 0,
            "by_asset": {},
            "by_session": {},
            "by_confidence": {
                "strong_80_100": {"wins": 0, "losses": 0},
                "good_70_79": {"wins": 0, "losses": 0},
                "acceptable_60_69": {"wins": 0, "losses": 0}
            }
        }
        
        self.is_running = False
        self.tracker_task: Optional[asyncio.Task] = None
        self._loaded = False
        
        logger.info("📊 Signal Outcome Tracker initialized")
    
    async def start(self):
        """Start the tracker"""
        if self.is_running:
            return
        
        await self._load_data()
        self.is_running = True
        self.tracker_task = asyncio.create_task(self._tracking_loop())
        logger.info("📊 Signal Outcome Tracker started")
    
    async def stop(self):
        """Stop the tracker and save data"""
        self.is_running = False
        if self.tracker_task:
            self.tracker_task.cancel()
            try:
                await self.tracker_task
            except asyncio.CancelledError:
                pass
        await self._save_data()
        logger.info("📊 Signal Outcome Tracker stopped")
    
    async def track_signal(self, signal_data: Dict):
        """
        Register a new signal for tracking
        
        Called AFTER signal is generated - does not affect generation
        """
        try:
            tracked = TrackedSignal(
                signal_id=signal_data.get('signal_id', f"sig_{datetime.utcnow().timestamp()}"),
                timestamp=signal_data.get('timestamp', datetime.utcnow().isoformat()),
                asset=signal_data.get('asset', ''),
                direction=signal_data.get('direction', ''),
                entry_price=signal_data.get('entry_price', 0),
                stop_loss=signal_data.get('stop_loss', 0),
                take_profit_1=signal_data.get('take_profit_1', 0),
                take_profit_2=signal_data.get('take_profit_2', 0),
                confidence_score=signal_data.get('confidence_score', 0),
                confidence_level=signal_data.get('confidence_level', ''),
                setup_type=signal_data.get('setup_type', ''),
                session=signal_data.get('session', ''),
                invalidation=signal_data.get('invalidation', ''),
                risk_reward=signal_data.get('risk_reward', 0),
                score_breakdown=signal_data.get('score_breakdown', {}),
                highest_price_seen=signal_data.get('entry_price', 0),
                lowest_price_seen=signal_data.get('entry_price', 0)
            )
            
            self.active_signals[tracked.signal_id] = tracked
            self.stats["total_tracked"] += 1
            
            logger.info(f"📊 Tracking signal: {tracked.signal_id} ({tracked.asset} {tracked.direction})")
            
            # Save immediately when new signal is added
            await self._save_data()
            logger.info(f"📊 Saved tracking data (active: {len(self.active_signals)})")
            
        except Exception as e:
            logger.error(f"❌ Error tracking signal: {e}")
    
    def mark_notified(self, signal_id: str):
        """Mark signal as notified"""
        if signal_id in self.active_signals:
            self.active_signals[signal_id].status = SignalStatus.NOTIFIED.value
            self.active_signals[signal_id].notified_at = datetime.utcnow().isoformat()
    
    async def _tracking_loop(self):
        """Background loop to check signal outcomes"""
        while self.is_running:
            try:
                await self._check_all_signals()
            except Exception as e:
                logger.error(f"Tracker loop error: {e}")
            
            await asyncio.sleep(self.PRICE_CHECK_INTERVAL)
    
    async def _check_all_signals(self):
        """Check price action for all active signals"""
        from services.market_data_cache import market_data_cache
        from models import Asset
        
        now = datetime.utcnow()
        signals_to_complete = []
        
        self.stats["total_checks"] = self.stats.get("total_checks", 0) + 1
        
        for signal_id, signal in list(self.active_signals.items()):
            try:
                # Get current price
                asset = Asset.EURUSD if signal.asset == "EURUSD" else Asset.XAUUSD
                price_data = market_data_cache.get_price(asset)
                
                if not price_data:
                    continue
                
                current_price = price_data.mid
                
                # Update price tracking
                signal.highest_price_seen = max(signal.highest_price_seen, current_price)
                signal.lowest_price_seen = min(signal.lowest_price_seen, current_price)
                
                # Calculate risk (1R)
                risk = abs(signal.entry_price - signal.stop_loss)
                
                # Calculate excursions and R-multiples
                if signal.direction == "BUY":
                    favorable_move = current_price - signal.entry_price
                    adverse_move = signal.entry_price - current_price
                    
                    signal.max_favorable_excursion = max(signal.max_favorable_excursion, favorable_move)
                    signal.max_adverse_excursion = max(signal.max_adverse_excursion, adverse_move)
                    
                    # Track R-multiples
                    if risk > 0:
                        r_multiple = favorable_move / risk
                        if r_multiple >= 0.5 and not signal.reached_half_r:
                            signal.reached_half_r = True
                        if r_multiple >= 1.0 and not signal.reached_one_r:
                            signal.reached_one_r = True
                            signal.breakeven_possible = True
                            signal.partial_profit_possible = True
                        if r_multiple >= 2.0 and not signal.reached_two_r:
                            signal.reached_two_r = True
                        
                        # Track peak R before any reversal
                        signal.peak_r_before_reversal = max(signal.peak_r_before_reversal, r_multiple)
                    
                    # Track time in profit vs drawdown
                    if favorable_move > 0:
                        signal.time_in_profit_seconds += self.PRICE_CHECK_INTERVAL
                    else:
                        signal.time_in_drawdown_seconds += self.PRICE_CHECK_INTERVAL
                        
                else:  # SELL
                    favorable_move = signal.entry_price - current_price
                    adverse_move = current_price - signal.entry_price
                    
                    signal.max_favorable_excursion = max(signal.max_favorable_excursion, favorable_move)
                    signal.max_adverse_excursion = max(signal.max_adverse_excursion, adverse_move)
                    
                    # Track R-multiples
                    if risk > 0:
                        r_multiple = favorable_move / risk
                        if r_multiple >= 0.5 and not signal.reached_half_r:
                            signal.reached_half_r = True
                        if r_multiple >= 1.0 and not signal.reached_one_r:
                            signal.reached_one_r = True
                            signal.breakeven_possible = True
                            signal.partial_profit_possible = True
                        if r_multiple >= 2.0 and not signal.reached_two_r:
                            signal.reached_two_r = True
                        
                        signal.peak_r_before_reversal = max(signal.peak_r_before_reversal, r_multiple)
                    
                    if favorable_move > 0:
                        signal.time_in_profit_seconds += self.PRICE_CHECK_INTERVAL
                    else:
                        signal.time_in_drawdown_seconds += self.PRICE_CHECK_INTERVAL
                
                # Check outcomes
                outcome = self._check_outcome(signal, current_price, now)
                
                # Log every price check for active signals (ogni 30 secondi per non spammare)
                if self.stats.get("total_checks", 0) % 6 == 0:  # Log every ~30 seconds (5s interval * 6)
                    risk = abs(signal.entry_price - signal.stop_loss)
                    distance_to_tp = abs(signal.take_profit_1 - current_price)
                    distance_to_sl = abs(signal.stop_loss - current_price)
                    # Calculate MFE/MAE in R-multiples for logging
                    mfe_r = signal.max_favorable_excursion / risk if risk > 0 else 0
                    mae_r = signal.max_adverse_excursion / risk if risk > 0 else 0
                    logger.info(f"📊 TRACKER UPDATE: {signal.asset} {signal.direction}")
                    logger.info(f"   Price: {current_price:.5f} | Entry: {signal.entry_price:.5f}")
                    logger.info(f"   TP: {signal.take_profit_1:.5f} ({distance_to_tp:.5f} away) | SL: {signal.stop_loss:.5f} ({distance_to_sl:.5f} away)")
                    logger.info(f"   MFE: {mfe_r:.2f}R | MAE: {mae_r:.2f}R")
                    if risk > 0:
                        r_multiple = (signal.entry_price - current_price) / risk if signal.direction == "SELL" else (current_price - signal.entry_price) / risk
                        logger.info(f"   Current R: {r_multiple:.2f}R | Peak R: {signal.peak_r_before_reversal:.2f}R")
                
                if outcome:
                    # Determine if trailing would have helped
                    if outcome == "sl_hit" and signal.reached_one_r:
                        signal.trailing_would_improve = True
                    
                    # Calculate MFE/MAE in R-multiples for final log
                    final_risk = abs(signal.entry_price - signal.stop_loss)
                    final_mfe_r = signal.max_favorable_excursion / final_risk if final_risk > 0 else 0
                    final_mae_r = signal.max_adverse_excursion / final_risk if final_risk > 0 else 0
                    
                    # Log outcome
                    logger.info(f"🎯 TRADE CLOSED: {signal.asset} {signal.direction} -> {outcome.upper()}")
                    logger.info(f"   Entry: {signal.entry_price:.5f} | Close: {current_price:.5f}")
                    logger.info(f"   Final MFE: {final_mfe_r:.2f}R | Final MAE: {final_mae_r:.2f}R")
                    
                    signals_to_complete.append((signal_id, outcome))
                
            except Exception as e:
                logger.debug(f"Error checking signal {signal_id}: {e}")
        
        # Process completed signals
        for signal_id, outcome in signals_to_complete:
            await self._complete_signal(signal_id, outcome)
        
        # Save data periodically (every 6 checks = ~60 seconds)
        if self.stats.get("total_checks", 0) % 6 == 0:
            await self._save_data()
    
    def _check_outcome(self, signal: TrackedSignal, current_price: float, now: datetime) -> Optional[str]:
        """Check if signal has reached an outcome"""
        # Parse signal timestamp
        try:
            signal_time = datetime.fromisoformat(signal.timestamp.replace('Z', '+00:00').replace('+00:00', ''))
        except:
            signal_time = datetime.utcnow() - timedelta(hours=1)
        
        age_hours = (now - signal_time).total_seconds() / 3600
        
        # Check expiry
        if age_hours > self.EXPIRY_HOURS:
            return "expired"
        
        if signal.direction == "BUY":
            # Check TP hit
            if current_price >= signal.take_profit_1:
                return "tp_hit"
            # Check SL hit
            if current_price <= signal.stop_loss:
                # Did it move favorable first?
                if signal.max_favorable_excursion > 0:
                    signal.moved_favorable_before_fail = True
                return "sl_hit"
        else:  # SELL
            # Check TP hit
            if current_price <= signal.take_profit_1:
                return "tp_hit"
            # Check SL hit
            if current_price >= signal.stop_loss:
                if signal.max_favorable_excursion > 0:
                    signal.moved_favorable_before_fail = True
                return "sl_hit"
        
        return None
    
    async def _complete_signal(self, signal_id: str, outcome: str):
        """Complete a signal and update statistics"""
        if signal_id not in self.active_signals:
            return
        
        signal = self.active_signals.pop(signal_id)
        signal.status = outcome
        signal.closed_at = datetime.utcnow().isoformat()
        
        # Calculate outcome metrics
        try:
            signal_time = datetime.fromisoformat(signal.timestamp.replace('Z', '+00:00').replace('+00:00', ''))
            closed_time = datetime.fromisoformat(signal.closed_at)
            signal.time_to_outcome_seconds = (closed_time - signal_time).total_seconds()
        except:
            pass
        
        # Determine win/loss
        if outcome == "tp_hit":
            signal.final_outcome = "win"
            self.stats["wins"] += 1
            signal.pips_gained = abs(signal.take_profit_1 - signal.entry_price)
        elif outcome == "sl_hit":
            signal.final_outcome = "loss"
            self.stats["losses"] += 1
            signal.pips_lost = abs(signal.entry_price - signal.stop_loss)
        elif outcome == "expired":
            signal.final_outcome = "expired"
            self.stats["expired"] += 1
        else:
            signal.final_outcome = outcome
            self.stats["invalidated"] += 1
        
        # Update by-asset stats
        if signal.asset not in self.stats["by_asset"]:
            self.stats["by_asset"][signal.asset] = {"wins": 0, "losses": 0, "expired": 0}
        
        if signal.final_outcome == "win":
            self.stats["by_asset"][signal.asset]["wins"] += 1
        elif signal.final_outcome == "loss":
            self.stats["by_asset"][signal.asset]["losses"] += 1
        else:
            self.stats["by_asset"][signal.asset]["expired"] += 1
        
        # Update by-session stats
        if signal.session not in self.stats["by_session"]:
            self.stats["by_session"][signal.session] = {"wins": 0, "losses": 0}
        
        if signal.final_outcome == "win":
            self.stats["by_session"][signal.session]["wins"] += 1
        elif signal.final_outcome == "loss":
            self.stats["by_session"][signal.session]["losses"] += 1
        
        # Update by-confidence stats
        conf = signal.confidence_score
        if conf >= 80:
            bucket = "strong_80_100"
        elif conf >= 70:
            bucket = "good_70_79"
        else:
            bucket = "acceptable_60_69"
        
        if signal.final_outcome == "win":
            self.stats["by_confidence"][bucket]["wins"] += 1
        elif signal.final_outcome == "loss":
            self.stats["by_confidence"][bucket]["losses"] += 1
        
        # Store completed signal
        self.completed_signals.append(signal)
        
        # Trim if too many
        if len(self.completed_signals) > self.MAX_TRACKED_SIGNALS:
            self.completed_signals = self.completed_signals[-self.MAX_TRACKED_SIGNALS:]
        
        # Calculate MFE/MAE in R-multiples
        risk = abs(signal.entry_price - signal.stop_loss)
        mfe_r = signal.max_favorable_excursion / risk if risk > 0 else 0
        mae_r = signal.max_adverse_excursion / risk if risk > 0 else 0
        total_r = signal.peak_r_before_reversal if outcome == "tp_hit" else -1.0 if outcome == "sl_hit" else 0
        
        # Update candidate audit service with outcome data
        try:
            # Find matching candidate by symbol, direction, and approximate timestamp
            updated = candidate_audit_service.update_outcome(
                symbol=signal.asset,
                direction=signal.direction,
                outcome="win" if outcome == "tp_hit" else "loss" if outcome == "sl_hit" else "expired",
                is_simulated=False,
                total_r=total_r,
                exit_price=signal.highest_price_seen if outcome == "tp_hit" else signal.lowest_price_seen if outcome == "sl_hit" else 0,
                mfe_r=mfe_r,
                mae_r=mae_r,
                peak_r=signal.peak_r_before_reversal,
                time_to_outcome=(datetime.utcnow() - datetime.fromisoformat(signal.timestamp.replace('Z', ''))).total_seconds() / 60
            )
            if updated:
                logger.info(f"📊 Updated candidate audit: {signal.asset} {signal.direction} -> {outcome} | MFE: {mfe_r:.2f}R | MAE: {mae_r:.2f}R")
            else:
                logger.warning(f"⚠️ No matching candidate found for: {signal.asset} {signal.direction}")
        except Exception as e:
            logger.error(f"❌ Error updating candidate audit: {e}")
        
        # Log outcome
        emoji = "✅" if signal.final_outcome == "win" else "❌" if signal.final_outcome == "loss" else "⏰"
        logger.info(f"{emoji} Signal {signal_id} outcome: {outcome} (MFE: {mfe_r:.2f}R, MAE: {mae_r:.2f}R)")
        
        # Save periodically
        await self._save_data()
    
    async def _load_data(self):
        """Load persisted data"""
        if self._loaded:
            return
        
        try:
            if self.signals_file.exists():
                async with aiofiles.open(self.signals_file, 'r') as f:
                    data = json.loads(await f.read())
                    for sig_data in data.get('completed', []):
                        self.completed_signals.append(TrackedSignal.from_dict(sig_data))
                    for sig_data in data.get('active', []):
                        sig = TrackedSignal.from_dict(sig_data)
                        self.active_signals[sig.signal_id] = sig
                logger.info(f"📊 Loaded {len(self.completed_signals)} completed, {len(self.active_signals)} active signals")
            
            if self.stats_file.exists():
                async with aiofiles.open(self.stats_file, 'r') as f:
                    self.stats = json.loads(await f.read())
                logger.info(f"📊 Loaded stats: {self.stats['wins']}W / {self.stats['losses']}L")
        except Exception as e:
            logger.error(f"Error loading tracker data: {e}")
        
        self._loaded = True
    
    async def _save_data(self):
        """Save data to files"""
        try:
            # Save signals
            data = {
                'completed': [s.to_dict() for s in self.completed_signals[-100:]],  # Last 100
                'active': [s.to_dict() for s in self.active_signals.values()],
                'saved_at': datetime.utcnow().isoformat()
            }
            async with aiofiles.open(self.signals_file, 'w') as f:
                await f.write(json.dumps(data, indent=2))
            
            # Save stats
            async with aiofiles.open(self.stats_file, 'w') as f:
                await f.write(json.dumps(self.stats, indent=2))
        except Exception as e:
            logger.error(f"Error saving tracker data: {e}")
    
    def get_stats(self) -> Dict:
        """Get current statistics"""
        total_decided = self.stats["wins"] + self.stats["losses"]
        win_rate = (self.stats["wins"] / total_decided * 100) if total_decided > 0 else 0
        
        # Calculate average excursions from completed signals
        mfe_values = [s.max_favorable_excursion for s in self.completed_signals if s.max_favorable_excursion > 0]
        mae_values = [s.max_adverse_excursion for s in self.completed_signals if s.max_adverse_excursion > 0]
        
        avg_mfe = sum(mfe_values) / len(mfe_values) if mfe_values else 0
        avg_mae = sum(mae_values) / len(mae_values) if mae_values else 0
        
        # Trade management statistics
        all_signals = list(self.active_signals.values()) + self.completed_signals
        reached_half_r = sum(1 for s in all_signals if s.reached_half_r)
        reached_one_r = sum(1 for s in all_signals if s.reached_one_r)
        reached_two_r = sum(1 for s in all_signals if s.reached_two_r)
        be_possible = sum(1 for s in all_signals if s.breakeven_possible)
        trailing_would_help = sum(1 for s in self.completed_signals if s.trailing_would_improve)
        
        return {
            "summary": {
                "total_tracked": self.stats["total_tracked"],
                "wins": self.stats["wins"],
                "losses": self.stats["losses"],
                "expired": self.stats["expired"],
                "win_rate_percent": round(win_rate, 1),
                "active_signals": len(self.active_signals)
            },
            "excursions": {
                "avg_max_favorable": round(avg_mfe, 6),
                "avg_max_adverse": round(avg_mae, 6)
            },
            "trade_management": {
                "reached_half_r": reached_half_r,
                "reached_one_r": reached_one_r,
                "reached_two_r": reached_two_r,
                "breakeven_possible_count": be_possible,
                "trailing_would_improve_count": trailing_would_help
            },
            "by_asset": self.stats["by_asset"],
            "by_session": self.stats["by_session"],
            "by_confidence": self.stats["by_confidence"]
        }
    
    def get_recent_signals(self, limit: int = 20) -> List[Dict]:
        """Get recent tracked signals"""
        recent = list(self.active_signals.values()) + self.completed_signals[-limit:]
        recent.sort(key=lambda x: x.timestamp, reverse=True)
        return [s.to_dict() for s in recent[:limit]]
    
    def get_performance_report(self) -> Dict:
        """Generate a comprehensive performance report"""
        stats = self.get_stats()
        
        # Calculate confidence bucket performance
        conf_performance = {}
        for bucket, data in self.stats["by_confidence"].items():
            total = data["wins"] + data["losses"]
            win_rate = (data["wins"] / total * 100) if total > 0 else 0
            conf_performance[bucket] = {
                "total": total,
                "wins": data["wins"],
                "losses": data["losses"],
                "win_rate": round(win_rate, 1)
            }
        
        return {
            "generated_at": datetime.utcnow().isoformat(),
            "overall": stats["summary"],
            "excursions": stats["excursions"],
            "by_asset": stats["by_asset"],
            "by_session": stats["by_session"],
            "by_confidence_bucket": conf_performance
        }


# Global instance
signal_outcome_tracker = SignalOutcomeTracker()
