"""
Rejected Trade Outcome Tracker
==============================

This module tracks rejected trade candidates and simulates their outcomes
to measure filter quality and identify overly restrictive filters.

PURPOSE: Audit/Analysis ONLY - Does NOT modify live trading logic

FEATURES:
1. Captures full trade snapshot at rejection point
2. Simulates outcomes using same logic as accepted trades
3. Calculates MFE, MAE, peak R, time to outcome
4. Provides per-filter quality analysis

DATA FLOW:
- Signal generator calls record_rejected_candidate() at rejection
- Background simulator processes pending candidates
- Results stored persistently in JSON
- API endpoints provide analytics

IMPORTANT: This is PASSIVE OBSERVATION - no trading decisions are affected
"""

import json
import asyncio
import os
from datetime import datetime, timedelta
from dataclasses import dataclass, field, asdict
from typing import Dict, List, Optional, Any
from enum import Enum
import logging

from services.candidate_audit_service import candidate_audit_service

logger = logging.getLogger(__name__)


class RejectionReason(str, Enum):
    """Rejection reasons tracked for analysis"""
    LOW_CONFIDENCE = "low_confidence"
    LOW_RR = "low_rr"
    WEAK_MTF = "weak_mtf"
    FTA_BLOCKED = "fta_blocked"
    DUPLICATE = "duplicate"
    DAILY_LIMIT = "daily_limit"
    LATE_ENTRY = "late_entry"
    SESSION_BLOCKED = "session_blocked"
    ASSET_BLOCKED = "asset_blocked"
    UNPROFITABLE_SETUP = "unprofitable_setup"
    SPREAD_TOO_HIGH = "spread_too_high"
    DATA_STALE = "data_stale"
    MARKET_CLOSED = "market_closed"
    OTHER = "other"


class SimulationStatus(str, Enum):
    """Status of the rejected trade simulation"""
    PENDING = "pending"           # Waiting for simulation
    SIMULATING = "simulating"     # Currently being simulated
    TP_HIT = "tp_hit"             # Simulated TP hit
    SL_HIT = "sl_hit"             # Simulated SL hit
    EXPIRED = "expired"           # Simulated expiry
    INSUFFICIENT_DATA = "insufficient_data"  # Not enough candles yet
    ERROR = "error"               # Simulation error


@dataclass
class RejectedTradeCandidate:
    """Full snapshot of a rejected trade candidate"""
    # Identity
    candidate_id: str
    timestamp: str
    
    # Trade parameters
    asset: str
    direction: str
    entry_price: float
    stop_loss: float
    take_profit: float
    risk_reward: float
    
    # Scoring info
    confidence_score: float
    mtf_score: float
    session: str
    setup_type: str
    
    # Rejection info
    rejection_reason: str
    rejection_details: str = ""
    
    # FTA/Clean space metrics (if available)
    fta_distance: Optional[float] = None
    clean_space_available: Optional[float] = None
    fta_level: Optional[float] = None
    
    # Full score breakdown (for detailed analysis)
    score_breakdown: Dict = field(default_factory=dict)
    
    # Simulation status
    simulation_status: str = SimulationStatus.PENDING.value
    simulation_started_at: Optional[str] = None
    simulation_completed_at: Optional[str] = None
    
    # Simulation outcomes (populated after simulation)
    simulated_outcome: Optional[str] = None  # tp_hit, sl_hit, expired
    mfe: float = 0.0                          # Max favorable excursion
    mae: float = 0.0                          # Max adverse excursion
    mfe_r: float = 0.0                        # MFE in R-multiples
    mae_r: float = 0.0                        # MAE in R-multiples
    peak_r: float = 0.0                       # Peak R reached before reversal
    time_to_outcome_seconds: float = 0.0      # Time to TP/SL/expiry
    candles_processed: int = 0                # Number of candles used in simulation
    
    # R-milestone tracking
    reached_half_r: bool = False
    reached_one_r: bool = False
    reached_two_r: bool = False
    
    # Additional analysis
    would_have_won: Optional[bool] = None
    r_result: float = 0.0  # Final R result (+1.33 for TP, -1 for SL, 0 for expired)
    
    def to_dict(self) -> Dict:
        return asdict(self)
    
    @classmethod
    def from_dict(cls, data: Dict) -> 'RejectedTradeCandidate':
        return cls(**{k: v for k, v in data.items() if k in cls.__dataclass_fields__})


class RejectedTradeOutcomeTracker:
    """
    Tracks and simulates outcomes of rejected trade candidates.
    
    Uses the SAME outcome logic as accepted trades:
    - Same TP/SL detection
    - Same same-candle tie rule (conservative: SL wins if both touched)
    - Same expiry rule (48 hours)
    - Same MFE/MAE calculation
    """
    
    # Configuration
    STORAGE_PATH = "/app/backend/data/rejected_trade_audit.json"
    EXPIRY_HOURS = 48
    SIMULATION_INTERVAL = 60  # Seconds between simulation batches
    MAX_BATCH_SIZE = 10       # Candidates to simulate per batch
    SAME_CANDLE_TIE_RULE = "sl_wins"  # Conservative: if both touched in same candle, SL wins
    
    def __init__(self):
        self.is_running = False
        self.pending_candidates: Dict[str, RejectedTradeCandidate] = {}
        self.completed_simulations: List[RejectedTradeCandidate] = []
        self.stats = {
            "total_rejected": 0,
            "simulations_completed": 0,
            "simulations_pending": 0,
            "by_reason": {},
            "by_asset": {},
            "by_session": {},
            "by_setup": {}
        }
        self._load_data()
        logger.info("📊 Rejected Trade Outcome Tracker initialized")
        logger.info(f"   Loaded: {len(self.pending_candidates)} pending, {len(self.completed_simulations)} completed")
    
    def _load_data(self):
        """Load persisted data from JSON"""
        if os.path.exists(self.STORAGE_PATH):
            try:
                with open(self.STORAGE_PATH, 'r') as f:
                    data = json.load(f)
                
                # Load pending candidates
                for item in data.get('pending', []):
                    candidate = RejectedTradeCandidate.from_dict(item)
                    self.pending_candidates[candidate.candidate_id] = candidate
                
                # Load completed simulations
                for item in data.get('completed', []):
                    self.completed_simulations.append(RejectedTradeCandidate.from_dict(item))
                
                # Load stats
                self.stats = data.get('stats', self.stats)
                
            except Exception as e:
                logger.error(f"Error loading rejected trade data: {e}")
    
    async def _save_data(self):
        """Persist data to JSON"""
        try:
            data = {
                'pending': [c.to_dict() for c in self.pending_candidates.values()],
                'completed': [c.to_dict() for c in self.completed_simulations],
                'stats': self.stats,
                'last_updated': datetime.utcnow().isoformat()
            }
            
            # Atomic write
            temp_path = self.STORAGE_PATH + '.tmp'
            with open(temp_path, 'w') as f:
                json.dump(data, f, indent=2, default=str)
            os.replace(temp_path, self.STORAGE_PATH)
            
        except Exception as e:
            logger.error(f"Error saving rejected trade data: {e}")
    
    def record_rejected_candidate(
        self,
        asset: str,
        direction: str,
        entry_price: float,
        stop_loss: float,
        take_profit: float,
        confidence_score: float,
        mtf_score: float,
        session: str,
        setup_type: str,
        rejection_reason: str,
        rejection_details: str = "",
        risk_reward: float = 0,
        fta_distance: Optional[float] = None,
        clean_space: Optional[float] = None,
        fta_level: Optional[float] = None,
        score_breakdown: Dict = None
    ):
        """
        Record a rejected trade candidate for later simulation.
        
        Called by signal generator at rejection point.
        Does NOT block or modify the rejection - purely observational.
        """
        try:
            candidate_id = f"REJ_{asset}_{direction}_{datetime.utcnow().strftime('%Y%m%d_%H%M%S_%f')}"
            
            candidate = RejectedTradeCandidate(
                candidate_id=candidate_id,
                timestamp=datetime.utcnow().isoformat(),
                asset=asset,
                direction=direction,
                entry_price=entry_price,
                stop_loss=stop_loss,
                take_profit=take_profit,
                risk_reward=risk_reward if risk_reward else abs(take_profit - entry_price) / abs(entry_price - stop_loss) if abs(entry_price - stop_loss) > 0 else 0,
                confidence_score=confidence_score,
                mtf_score=mtf_score,
                session=session,
                setup_type=setup_type,
                rejection_reason=rejection_reason,
                rejection_details=rejection_details,
                fta_distance=fta_distance,
                clean_space_available=clean_space,
                fta_level=fta_level,
                score_breakdown=score_breakdown or {}
            )
            
            self.pending_candidates[candidate_id] = candidate
            self.stats["total_rejected"] += 1
            self.stats["simulations_pending"] = len(self.pending_candidates)
            
            # Update by-reason stats
            if rejection_reason not in self.stats["by_reason"]:
                self.stats["by_reason"][rejection_reason] = {
                    "count": 0, "tp_hit": 0, "sl_hit": 0, "expired": 0,
                    "total_mfe_r": 0, "total_mae_r": 0, "total_r": 0
                }
            self.stats["by_reason"][rejection_reason]["count"] += 1
            
            logger.debug(f"📊 Recorded rejected candidate: {candidate_id} ({rejection_reason})")
            
            # Auto-save every 10 candidates
            if self.stats["total_rejected"] % 10 == 0:
                asyncio.create_task(self._save_data())
            
        except Exception as e:
            logger.error(f"Error recording rejected candidate: {e}")
    
    async def start(self):
        """Start the background simulation loop"""
        if self.is_running:
            logger.warning("Rejected trade tracker already running")
            return
        
        self.is_running = True
        logger.info("🚀 Rejected Trade Outcome Tracker started")
        asyncio.create_task(self._simulation_loop())
    
    async def stop(self):
        """Stop the tracker and save data"""
        self.is_running = False
        await self._save_data()
        logger.info("🛑 Rejected Trade Outcome Tracker stopped")
    
    async def _simulation_loop(self):
        """Background loop to simulate rejected trades"""
        while self.is_running:
            try:
                await self._process_simulation_batch()
            except Exception as e:
                logger.error(f"Simulation loop error: {e}")
            
            await asyncio.sleep(self.SIMULATION_INTERVAL)
    
    async def _process_simulation_batch(self):
        """Process a batch of pending simulations"""
        from services.market_data_cache import market_data_cache
        from models import Asset, Timeframe
        
        # Get candidates that are ready for simulation (at least 1 hour old)
        now = datetime.utcnow()
        ready_candidates = []
        
        for candidate_id, candidate in list(self.pending_candidates.items()):
            try:
                candidate_time = datetime.fromisoformat(candidate.timestamp)
                age_hours = (now - candidate_time).total_seconds() / 3600
                
                # Wait at least 1 hour before simulating (need future candles)
                if age_hours >= 1 and candidate.simulation_status == SimulationStatus.PENDING.value:
                    ready_candidates.append(candidate)
                
                # Mark expired candidates that are too old
                if age_hours > self.EXPIRY_HOURS + 1:
                    if candidate.simulation_status == SimulationStatus.PENDING.value:
                        candidate.simulation_status = SimulationStatus.INSUFFICIENT_DATA.value
                        
            except Exception as e:
                logger.debug(f"Error checking candidate {candidate_id}: {e}")
        
        # Process batch
        batch = ready_candidates[:self.MAX_BATCH_SIZE]
        
        for candidate in batch:
            try:
                await self._simulate_candidate(candidate)
            except Exception as e:
                logger.error(f"Error simulating {candidate.candidate_id}: {e}")
                candidate.simulation_status = SimulationStatus.ERROR.value
        
        # Save after batch
        if batch:
            await self._save_data()
    
    async def _simulate_candidate(self, candidate: RejectedTradeCandidate):
        """
        Simulate a rejected trade using historical candles.
        
        Uses SAME logic as the accepted trade tracker:
        - Same TP/SL detection
        - Same same-candle tie rule
        - Same MFE/MAE calculation
        """
        from services.market_data_cache import market_data_cache
        from models import Asset, Timeframe
        
        candidate.simulation_status = SimulationStatus.SIMULATING.value
        candidate.simulation_started_at = datetime.utcnow().isoformat()
        
        try:
            # Get historical candles from rejection time to now
            asset = Asset.EURUSD if candidate.asset == "EURUSD" else Asset.XAUUSD
            candles = market_data_cache.get_candles(asset, Timeframe.M5)
            
            if not candles or len(candles) < 10:
                candidate.simulation_status = SimulationStatus.INSUFFICIENT_DATA.value
                return
            
            # Find candles after the rejection timestamp
            candidate_time = datetime.fromisoformat(candidate.timestamp)
            future_candles = []
            
            for candle in candles:
                candle_time = candle.get('timestamp') or candle.get('datetime')
                if candle_time:
                    try:
                        if isinstance(candle_time, str):
                            ct = datetime.fromisoformat(candle_time.replace('Z', '+00:00').replace('+00:00', ''))
                        else:
                            ct = candle_time
                        
                        if ct > candidate_time:
                            future_candles.append(candle)
                    except:
                        pass
            
            if len(future_candles) < 5:
                candidate.simulation_status = SimulationStatus.INSUFFICIENT_DATA.value
                return
            
            # Simulate candle by candle
            risk = abs(candidate.entry_price - candidate.stop_loss)
            
            highest_seen = candidate.entry_price
            lowest_seen = candidate.entry_price
            max_favorable = 0.0
            max_adverse = 0.0
            peak_r = 0.0
            
            outcome = None
            candles_processed = 0
            
            for candle in future_candles:
                candles_processed += 1
                
                high = candle.get('high', candidate.entry_price)
                low = candle.get('low', candidate.entry_price)
                close = candle.get('close', candidate.entry_price)
                
                # Update tracking
                highest_seen = max(highest_seen, high)
                lowest_seen = min(lowest_seen, low)
                
                # Calculate excursions based on direction
                if candidate.direction == "BUY":
                    favorable = high - candidate.entry_price
                    adverse = candidate.entry_price - low
                    
                    max_favorable = max(max_favorable, favorable)
                    max_adverse = max(max_adverse, adverse)
                    
                    if risk > 0:
                        current_r = favorable / risk
                        peak_r = max(peak_r, current_r)
                        
                        # Track R milestones
                        if current_r >= 0.5:
                            candidate.reached_half_r = True
                        if current_r >= 1.0:
                            candidate.reached_one_r = True
                        if current_r >= 2.0:
                            candidate.reached_two_r = True
                    
                    # Check TP/SL in this candle
                    tp_touched = high >= candidate.take_profit
                    sl_touched = low <= candidate.stop_loss
                    
                    # Same-candle tie rule
                    if tp_touched and sl_touched:
                        # Conservative: SL wins
                        if self.SAME_CANDLE_TIE_RULE == "sl_wins":
                            outcome = SimulationStatus.SL_HIT.value
                        else:
                            outcome = SimulationStatus.TP_HIT.value
                        break
                    elif tp_touched:
                        outcome = SimulationStatus.TP_HIT.value
                        break
                    elif sl_touched:
                        outcome = SimulationStatus.SL_HIT.value
                        break
                        
                else:  # SELL
                    favorable = candidate.entry_price - low
                    adverse = high - candidate.entry_price
                    
                    max_favorable = max(max_favorable, favorable)
                    max_adverse = max(max_adverse, adverse)
                    
                    if risk > 0:
                        current_r = favorable / risk
                        peak_r = max(peak_r, current_r)
                        
                        if current_r >= 0.5:
                            candidate.reached_half_r = True
                        if current_r >= 1.0:
                            candidate.reached_one_r = True
                        if current_r >= 2.0:
                            candidate.reached_two_r = True
                    
                    # Check TP/SL
                    tp_touched = low <= candidate.take_profit
                    sl_touched = high >= candidate.stop_loss
                    
                    if tp_touched and sl_touched:
                        if self.SAME_CANDLE_TIE_RULE == "sl_wins":
                            outcome = SimulationStatus.SL_HIT.value
                        else:
                            outcome = SimulationStatus.TP_HIT.value
                        break
                    elif tp_touched:
                        outcome = SimulationStatus.TP_HIT.value
                        break
                    elif sl_touched:
                        outcome = SimulationStatus.SL_HIT.value
                        break
                
                # Check expiry (based on candle count - roughly 48 hours in M5 = 576 candles)
                if candles_processed >= 576:
                    outcome = SimulationStatus.EXPIRED.value
                    break
            
            # If no outcome after all candles, mark as expired or pending
            if not outcome:
                # Check time elapsed
                now = datetime.utcnow()
                age_hours = (now - candidate_time).total_seconds() / 3600
                if age_hours >= self.EXPIRY_HOURS:
                    outcome = SimulationStatus.EXPIRED.value
                else:
                    candidate.simulation_status = SimulationStatus.INSUFFICIENT_DATA.value
                    return
            
            # Store results
            candidate.simulated_outcome = outcome
            candidate.mfe = max_favorable
            candidate.mae = max_adverse
            candidate.mfe_r = max_favorable / risk if risk > 0 else 0
            candidate.mae_r = max_adverse / risk if risk > 0 else 0
            candidate.peak_r = peak_r
            candidate.candles_processed = candles_processed
            candidate.time_to_outcome_seconds = candles_processed * 5 * 60  # M5 candles
            
            # Determine win/loss
            if outcome == SimulationStatus.TP_HIT.value:
                candidate.would_have_won = True
                candidate.r_result = candidate.risk_reward  # e.g., 1.33R
                candidate.simulation_status = SimulationStatus.TP_HIT.value
            elif outcome == SimulationStatus.SL_HIT.value:
                candidate.would_have_won = False
                candidate.r_result = -1.0
                candidate.simulation_status = SimulationStatus.SL_HIT.value
            else:  # Expired
                candidate.would_have_won = None
                candidate.r_result = 0.0
                candidate.simulation_status = SimulationStatus.EXPIRED.value
            
            candidate.simulation_completed_at = datetime.utcnow().isoformat()
            
            # Move to completed
            self.pending_candidates.pop(candidate.candidate_id, None)
            self.completed_simulations.append(candidate)
            
            # Update stats
            self._update_stats_for_completed(candidate)
            
            logger.info(f"📊 Simulated {candidate.candidate_id}: {outcome} | MFE: {candidate.mfe_r:.2f}R | MAE: {candidate.mae_r:.2f}R")
            
            # Update candidate_audit_service with simulated outcome
            try:
                # Map simulation outcome to audit outcome
                audit_outcome = "win" if outcome == SimulationStatus.TP_HIT.value else "loss" if outcome == SimulationStatus.SL_HIT.value else "expired"
                
                # Try to find and update matching rejected candidate in audit
                # NOTE: RejectedTradeCandidate uses 'asset' not 'symbol'
                updated = candidate_audit_service.update_rejected_outcome(
                    symbol=candidate.asset,  # Use 'asset' not 'symbol'
                    direction=candidate.direction,
                    rejection_reason=candidate.rejection_reason,
                    outcome=audit_outcome,
                    is_simulated=True,
                    total_r=candidate.r_result,
                    mfe_r=candidate.mfe_r,
                    mae_r=candidate.mae_r,
                    peak_r=candidate.peak_r,
                    time_to_outcome=candidate.time_to_outcome_seconds / 60 if candidate.time_to_outcome_seconds else 0
                )
                if updated:
                    logger.info(f"📊 Updated audit: {candidate.asset} {candidate.direction} [{candidate.rejection_reason}] -> {audit_outcome}")
            except Exception as e:
                logger.warning(f"Could not update candidate audit: {e}")
            
        except Exception as e:
            logger.error(f"Simulation error for {candidate.candidate_id}: {e}")
            candidate.simulation_status = SimulationStatus.ERROR.value
    
    def _update_stats_for_completed(self, candidate: RejectedTradeCandidate):
        """Update statistics after completing a simulation"""
        self.stats["simulations_completed"] += 1
        self.stats["simulations_pending"] = len(self.pending_candidates)
        
        reason = candidate.rejection_reason
        
        # Update by-reason stats
        if reason not in self.stats["by_reason"]:
            self.stats["by_reason"][reason] = {
                "count": 0, "tp_hit": 0, "sl_hit": 0, "expired": 0,
                "total_mfe_r": 0, "total_mae_r": 0, "total_r": 0
            }
        
        stats = self.stats["by_reason"][reason]
        
        if candidate.simulated_outcome == SimulationStatus.TP_HIT.value:
            stats["tp_hit"] += 1
        elif candidate.simulated_outcome == SimulationStatus.SL_HIT.value:
            stats["sl_hit"] += 1
        else:
            stats["expired"] += 1
        
        stats["total_mfe_r"] += candidate.mfe_r
        stats["total_mae_r"] += candidate.mae_r
        stats["total_r"] += candidate.r_result
        
        # Update by-asset
        asset = candidate.asset
        if asset not in self.stats["by_asset"]:
            self.stats["by_asset"][asset] = {"tp_hit": 0, "sl_hit": 0, "expired": 0, "total_r": 0}
        
        if candidate.simulated_outcome == SimulationStatus.TP_HIT.value:
            self.stats["by_asset"][asset]["tp_hit"] += 1
        elif candidate.simulated_outcome == SimulationStatus.SL_HIT.value:
            self.stats["by_asset"][asset]["sl_hit"] += 1
        else:
            self.stats["by_asset"][asset]["expired"] += 1
        self.stats["by_asset"][asset]["total_r"] += candidate.r_result
        
        # Update by-session
        session = candidate.session
        if session not in self.stats["by_session"]:
            self.stats["by_session"][session] = {"tp_hit": 0, "sl_hit": 0, "expired": 0, "total_r": 0}
        
        if candidate.simulated_outcome == SimulationStatus.TP_HIT.value:
            self.stats["by_session"][session]["tp_hit"] += 1
        elif candidate.simulated_outcome == SimulationStatus.SL_HIT.value:
            self.stats["by_session"][session]["sl_hit"] += 1
        else:
            self.stats["by_session"][session]["expired"] += 1
        self.stats["by_session"][session]["total_r"] += candidate.r_result
        
        # Update by-setup
        setup = candidate.setup_type
        if setup not in self.stats["by_setup"]:
            self.stats["by_setup"][setup] = {"tp_hit": 0, "sl_hit": 0, "expired": 0, "total_r": 0}
        
        if candidate.simulated_outcome == SimulationStatus.TP_HIT.value:
            self.stats["by_setup"][setup]["tp_hit"] += 1
        elif candidate.simulated_outcome == SimulationStatus.SL_HIT.value:
            self.stats["by_setup"][setup]["sl_hit"] += 1
        else:
            self.stats["by_setup"][setup]["expired"] += 1
        self.stats["by_setup"][setup]["total_r"] += candidate.r_result
    
    def get_overall_stats(self) -> Dict:
        """Get overall rejected trade statistics"""
        completed = self.completed_simulations
        
        total = len(completed)
        tp_hits = sum(1 for c in completed if c.simulated_outcome == SimulationStatus.TP_HIT.value)
        sl_hits = sum(1 for c in completed if c.simulated_outcome == SimulationStatus.SL_HIT.value)
        expired = sum(1 for c in completed if c.simulated_outcome == SimulationStatus.EXPIRED.value)
        
        trades_with_outcome = tp_hits + sl_hits
        winrate = tp_hits / trades_with_outcome * 100 if trades_with_outcome > 0 else 0
        
        total_r = sum(c.r_result for c in completed)
        expectancy = total_r / trades_with_outcome if trades_with_outcome > 0 else 0
        
        avg_mfe_r = sum(c.mfe_r for c in completed) / total if total > 0 else 0
        avg_mae_r = sum(c.mae_r for c in completed) / total if total > 0 else 0
        avg_peak_r = sum(c.peak_r for c in completed) / total if total > 0 else 0
        
        return {
            "total_rejected_tracked": self.stats["total_rejected"],
            "simulations_completed": total,
            "simulations_pending": len(self.pending_candidates),
            "tp_hit": tp_hits,
            "sl_hit": sl_hits,
            "expired": expired,
            "winrate_pct": round(winrate, 1),
            "total_r": round(total_r, 2),
            "expectancy_r": round(expectancy, 3),
            "avg_mfe_r": round(avg_mfe_r, 2),
            "avg_mae_r": round(avg_mae_r, 2),
            "avg_peak_r": round(avg_peak_r, 2)
        }
    
    def get_stats_by_reason(self) -> Dict:
        """Get statistics broken down by rejection reason"""
        result = {}
        
        for reason, stats in self.stats.get("by_reason", {}).items():
            count = stats.get("count", 0)
            tp = stats.get("tp_hit", 0)
            sl = stats.get("sl_hit", 0)
            expired = stats.get("expired", 0)
            completed = tp + sl + expired
            
            trades_with_outcome = tp + sl
            winrate = tp / trades_with_outcome * 100 if trades_with_outcome > 0 else 0
            
            total_r = stats.get("total_r", 0)
            expectancy = total_r / trades_with_outcome if trades_with_outcome > 0 else 0
            
            avg_mfe_r = stats.get("total_mfe_r", 0) / completed if completed > 0 else 0
            avg_mae_r = stats.get("total_mae_r", 0) / completed if completed > 0 else 0
            
            result[reason] = {
                "total_rejected": count,
                "simulated": completed,
                "pending": count - completed,
                "tp_hit": tp,
                "sl_hit": sl,
                "expired": expired,
                "winrate_pct": round(winrate, 1),
                "total_r": round(total_r, 2),
                "expectancy_r": round(expectancy, 3),
                "avg_mfe_r": round(avg_mfe_r, 2),
                "avg_mae_r": round(avg_mae_r, 2)
            }
        
        return result
    
    def get_filter_quality_report(self) -> Dict:
        """
        Generate filter quality analysis.
        
        For each filter, shows:
        - How many trades it blocked
        - How many would have been winners
        - How many would have been losers
        - Whether it's correctly blocking bad trades
        """
        report = {
            "generated_at": datetime.utcnow().isoformat(),
            "filters": {}
        }
        
        for reason, stats in self.get_stats_by_reason().items():
            tp = stats["tp_hit"]
            sl = stats["sl_hit"]
            expired = stats["expired"]
            winrate = stats["winrate_pct"]
            expectancy = stats["expectancy_r"]
            
            # Determine filter quality
            if stats["simulated"] < 5:
                quality = "insufficient_data"
                assessment = "Need more data to assess"
            elif expectancy < -0.1:
                quality = "good"
                assessment = f"Correctly blocking losing trades (expectancy: {expectancy:+.2f}R)"
            elif expectancy > 0.1:
                quality = "too_strict"
                assessment = f"Blocking profitable trades! (expectancy: {expectancy:+.2f}R)"
            else:
                quality = "neutral"
                assessment = f"Neutral impact (expectancy: {expectancy:+.2f}R)"
            
            report["filters"][reason] = {
                "blocked_count": stats["total_rejected"],
                "simulated_count": stats["simulated"],
                "would_have_won": tp,
                "would_have_lost": sl,
                "would_have_expired": expired,
                "simulated_winrate": winrate,
                "simulated_expectancy": expectancy,
                "quality_rating": quality,
                "assessment": assessment
            }
        
        # Sort by expectancy (most profitable blocked first)
        sorted_filters = sorted(
            report["filters"].items(),
            key=lambda x: x[1].get("simulated_expectancy", 0),
            reverse=True
        )
        
        report["filters_ranked_by_opportunity_cost"] = [
            {"filter": k, **v} for k, v in sorted_filters
        ]
        
        return report
    
    def get_sample_rejections(self, n: int = 5) -> List[Dict]:
        """Get n sample completed rejections with full details"""
        completed = sorted(
            self.completed_simulations,
            key=lambda x: x.simulation_completed_at or "",
            reverse=True
        )
        
        samples = []
        for c in completed[:n]:
            samples.append({
                "candidate_id": c.candidate_id,
                "timestamp": c.timestamp,
                "asset": c.asset,
                "direction": c.direction,
                "entry_price": c.entry_price,
                "stop_loss": c.stop_loss,
                "take_profit": c.take_profit,
                "risk_reward": round(c.risk_reward, 2),
                "confidence_score": c.confidence_score,
                "mtf_score": c.mtf_score,
                "session": c.session,
                "setup_type": c.setup_type,
                "rejection_reason": c.rejection_reason,
                "rejection_details": c.rejection_details,
                "simulated_outcome": c.simulated_outcome,
                "mfe_r": round(c.mfe_r, 2),
                "mae_r": round(c.mae_r, 2),
                "peak_r": round(c.peak_r, 2),
                "r_result": round(c.r_result, 2),
                "would_have_won": c.would_have_won,
                "reached_half_r": c.reached_half_r,
                "reached_one_r": c.reached_one_r,
                "candles_processed": c.candles_processed,
                "time_to_outcome_minutes": round(c.time_to_outcome_seconds / 60, 1)
            })
        
        return samples


# Global instance
rejected_trade_tracker = RejectedTradeOutcomeTracker()
