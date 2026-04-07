"""
Signal Snapshot Service - Complete Decision Logging
====================================================

Captures COMPLETE diagnostic snapshot for EVERY signal (accepted AND rejected).
This is purely observational - does NOT affect signal generation logic.

Each snapshot contains:
- Metadata (symbol, direction, timestamp, entry/sl/tp)
- Score breakdown step-by-step
- All factor contributions
- All penalties applied
- All filters checked
- Final reasoning
"""

import json
import logging
from typing import Dict, List, Optional, Any
from datetime import datetime
from pathlib import Path
from dataclasses import dataclass, field, asdict
from enum import Enum
import asyncio
import aiofiles

logger = logging.getLogger(__name__)


class SignalStatus(Enum):
    ACCEPTED = "accepted"
    REJECTED = "rejected"
    ACTIVE = "active"
    TP_HIT = "tp_hit"
    SL_HIT = "sl_hit"
    EXPIRED = "expired"
    INVALIDATED = "invalidated"


@dataclass
class FactorContribution:
    """Single factor contribution to score"""
    factor_key: str
    factor_name: str
    raw_value: float = 0.0
    normalized_value: float = 0.0  # 0-100
    weight_pct: float = 0.0
    score_contribution: float = 0.0
    status: str = "neutral"  # pass / fail / neutral
    reason: str = ""


@dataclass
class PenaltyApplied:
    """Penalty applied to score"""
    penalty_key: str
    penalty_name: str
    penalty_value: float = 0.0
    trigger_condition: str = ""
    raw_measurement: float = 0.0
    reason: str = ""


@dataclass
class FilterCheck:
    """Filter/gate check result"""
    filter_name: str
    threshold: float = 0.0
    actual_value: float = 0.0
    passed: bool = True
    blocks_trade: bool = False
    reason: str = ""


@dataclass
class ScoreBreakdown:
    """Step-by-step score calculation"""
    base_score: float = 0.0
    factor_contributions: List[Dict] = field(default_factory=list)
    subtotal_after_factors: float = 0.0
    penalties_applied: List[Dict] = field(default_factory=list)
    total_penalty: float = 0.0
    final_score: float = 0.0
    confidence_bucket: str = ""  # 60-64 / 65-69 / 70-74 / 75+


@dataclass 
class SignalSnapshot:
    """Complete decision snapshot for a signal"""
    # === METADATA ===
    signal_id: str
    timestamp: str
    symbol: str
    direction: str
    session: str = ""
    setup_type: str = ""
    
    # === TRADE LEVELS ===
    entry_price: float = 0.0
    stop_loss: float = 0.0
    take_profit: float = 0.0
    rr_ratio: float = 0.0
    
    # === DECISION ===
    status: str = "pending"  # accepted / rejected
    acceptance_source: str = ""  # main_threshold / buffer_zone
    rejection_reason: str = ""
    blocking_filter: str = ""
    
    # === SCORE BREAKDOWN ===
    score_pre_penalty: float = 0.0
    score_post_penalty: float = 0.0
    final_score: float = 0.0
    confidence_bucket: str = ""
    
    # === DETAILED BREAKDOWN ===
    factor_contributions: List[Dict] = field(default_factory=list)
    penalties_applied: List[Dict] = field(default_factory=list)
    filters_checked: List[Dict] = field(default_factory=list)
    
    # === HUMAN READABLE ===
    summary_short: str = ""
    summary_full: str = ""
    notification_title: str = ""
    notification_body: str = ""
    
    # === OUTCOME (updated later) ===
    outcome: str = ""  # tp_hit / sl_hit / expired
    outcome_timestamp: str = ""
    mfe_r: float = 0.0
    mae_r: float = 0.0
    final_r: float = 0.0
    time_to_outcome_minutes: float = 0.0
    
    def to_dict(self) -> Dict:
        return asdict(self)
    
    @classmethod
    def from_dict(cls, data: Dict) -> 'SignalSnapshot':
        return cls(**{k: v for k, v in data.items() if k in cls.__dataclass_fields__})


class SignalSnapshotService:
    """Service for managing signal snapshots"""
    
    def __init__(self):
        self.data_dir = Path("/app/backend/data")
        self.snapshots_file = self.data_dir / "signal_snapshots.json"
        self.snapshots: List[SignalSnapshot] = []
        self.snapshots_by_id: Dict[str, SignalSnapshot] = {}
        self.max_snapshots = 1000
        self._loaded = False
        
        logger.info("📸 SignalSnapshotService initialized")
    
    async def initialize(self):
        """Load existing snapshots"""
        if self._loaded:
            return
        
        await self._load_snapshots()
        self._loaded = True
        logger.info(f"📸 Loaded {len(self.snapshots)} signal snapshots")
    
    async def _load_snapshots(self):
        """Load snapshots from file"""
        try:
            if self.snapshots_file.exists():
                async with aiofiles.open(self.snapshots_file, 'r') as f:
                    data = json.loads(await f.read())
                    for snap_data in data.get('snapshots', []):
                        snap = SignalSnapshot.from_dict(snap_data)
                        self.snapshots.append(snap)
                        self.snapshots_by_id[snap.signal_id] = snap
        except Exception as e:
            logger.error(f"Error loading snapshots: {e}")
    
    async def _save_snapshots(self):
        """Save snapshots to file"""
        try:
            data = {
                'updated_at': datetime.utcnow().isoformat(),
                'total_count': len(self.snapshots),
                'snapshots': [s.to_dict() for s in self.snapshots[-self.max_snapshots:]]
            }
            async with aiofiles.open(self.snapshots_file, 'w') as f:
                await f.write(json.dumps(data, indent=2))
        except Exception as e:
            logger.error(f"Error saving snapshots: {e}")
    
    async def save_snapshot(self, snapshot: SignalSnapshot):
        """Save a new signal snapshot"""
        self.snapshots.append(snapshot)
        self.snapshots_by_id[snapshot.signal_id] = snapshot
        
        # Trim if too many - Priority: REJECTED first, then CLOSED, NEVER delete ACTIVE
        while len(self.snapshots) > self.max_snapshots:
            removed = False
            
            # PRIORITY 1: Remove REJECTED signals first
            for i, old_snap in enumerate(self.snapshots):
                if old_snap.status == 'rejected':
                    removed_snap = self.snapshots.pop(i)
                    if removed_snap.signal_id in self.snapshots_by_id:
                        del self.snapshots_by_id[removed_snap.signal_id]
                    removed = True
                    break
            
            if removed:
                continue
            
            # PRIORITY 2: Remove CLOSED signals (tp_hit, sl_hit, expired) only if no rejected left
            for i, old_snap in enumerate(self.snapshots):
                if old_snap.status in ['tp_hit', 'sl_hit', 'expired', 'closed']:
                    removed_snap = self.snapshots.pop(i)
                    if removed_snap.signal_id in self.snapshots_by_id:
                        del self.snapshots_by_id[removed_snap.signal_id]
                    removed = True
                    break
            
            # If nothing removed, all are ACTIVE - keep them all
            if not removed:
                logger.warning(f"⚠️ Cannot trim snapshots - all {len(self.snapshots)} are active trades")
                break
        
        await self._save_snapshots()
        logger.info(f"📸 Saved snapshot: {snapshot.signal_id} ({snapshot.status})")
    
    def get_snapshot(self, signal_id: str) -> Optional[SignalSnapshot]:
        """Get snapshot by signal ID"""
        return self.snapshots_by_id.get(signal_id)
    
    async def update_outcome(self, signal_id: str, outcome: str, mfe_r: float = 0, 
                            mae_r: float = 0, final_r: float = 0, time_minutes: float = 0):
        """Update snapshot with trade outcome"""
        snap = self.snapshots_by_id.get(signal_id)
        if snap:
            snap.outcome = outcome
            snap.outcome_timestamp = datetime.utcnow().isoformat()
            snap.mfe_r = mfe_r
            snap.mae_r = mae_r
            snap.final_r = final_r
            snap.time_to_outcome_minutes = time_minutes
            
            # Update status based on outcome
            if outcome == 'tp_hit':
                snap.status = 'tp_hit'
            elif outcome == 'sl_hit':
                snap.status = 'sl_hit'
            elif outcome == 'expired':
                snap.status = 'expired'
            
            await self._save_snapshots()
            logger.info(f"📸 Updated outcome: {signal_id} -> {outcome}")
    
    def get_feed(self, 
                 symbol: Optional[str] = None,
                 direction: Optional[str] = None,
                 status_filter: Optional[str] = None,  # all / accepted / rejected / active / closed
                 limit: int = 100,
                 offset: int = 0) -> List[Dict]:
        """Get signal feed with optional filters"""
        
        filtered = self.snapshots.copy()
        
        # Apply filters
        if symbol:
            filtered = [s for s in filtered if s.symbol == symbol]
        
        if direction:
            filtered = [s for s in filtered if s.direction == direction]
        
        if status_filter and status_filter != 'all':
            if status_filter == 'accepted':
                filtered = [s for s in filtered if s.status == 'accepted' or s.status == 'active']
            elif status_filter == 'rejected':
                filtered = [s for s in filtered if s.status == 'rejected']
            elif status_filter == 'active':
                filtered = [s for s in filtered if s.status == 'active']
            elif status_filter == 'closed':
                filtered = [s for s in filtered if s.status in ['tp_hit', 'sl_hit', 'expired']]
        
        # Sort by timestamp descending
        filtered.sort(key=lambda x: x.timestamp, reverse=True)
        
        # Apply pagination
        filtered = filtered[offset:offset + limit]
        
        # Convert to feed items
        feed_items = []
        for snap in filtered:
            feed_items.append({
                'signal_id': snap.signal_id,
                'timestamp': snap.timestamp,
                'symbol': snap.symbol,
                'direction': snap.direction,
                'status': snap.status,
                'score': snap.final_score,
                'entry': snap.entry_price,
                'sl': snap.stop_loss,
                'tp': snap.take_profit,
                'rr': snap.rr_ratio,
                'session': snap.session,
                'setup_type': snap.setup_type,
                'short_reason': snap.summary_short,
                'rejection_reason': snap.rejection_reason,
                'blocking_filter': snap.blocking_filter,
                'confidence_bucket': snap.confidence_bucket,
                'outcome': snap.outcome,
                'final_r': snap.final_r
            })
        
        return feed_items
    
    def get_detail(self, signal_id: str) -> Optional[Dict]:
        """Get complete signal detail"""
        snap = self.snapshots_by_id.get(signal_id)
        if not snap:
            return None
        
        return {
            # Metadata
            'signal_id': snap.signal_id,
            'timestamp': snap.timestamp,
            'symbol': snap.symbol,
            'direction': snap.direction,
            'session': snap.session,
            'setup_type': snap.setup_type,
            
            # Trade levels
            'trade_levels': {
                'entry': snap.entry_price,
                'stop_loss': snap.stop_loss,
                'take_profit': snap.take_profit,
                'rr_ratio': snap.rr_ratio
            },
            
            # Decision
            'decision': {
                'status': snap.status,
                'acceptance_source': snap.acceptance_source,
                'rejection_reason': snap.rejection_reason,
                'blocking_filter': snap.blocking_filter
            },
            
            # Score breakdown
            'score_breakdown': {
                'score_pre_penalty': snap.score_pre_penalty,
                'score_post_penalty': snap.score_post_penalty,
                'final_score': snap.final_score,
                'confidence_bucket': snap.confidence_bucket
            },
            
            # Detailed breakdowns
            'factor_contributions': snap.factor_contributions,
            'penalties_applied': snap.penalties_applied,
            'filters_checked': snap.filters_checked,
            
            # Reasoning
            'reasoning': {
                'summary_short': snap.summary_short,
                'summary_full': snap.summary_full
            },
            
            # Outcome (if completed)
            'outcome': {
                'result': snap.outcome,
                'timestamp': snap.outcome_timestamp,
                'mfe_r': snap.mfe_r,
                'mae_r': snap.mae_r,
                'final_r': snap.final_r,
                'time_to_outcome_minutes': snap.time_to_outcome_minutes
            } if snap.outcome else None
        }
    
    def get_stats(self) -> Dict:
        """Get snapshot statistics"""
        total = len(self.snapshots)
        accepted = len([s for s in self.snapshots if s.status in ['accepted', 'active', 'tp_hit', 'sl_hit', 'expired']])
        rejected = len([s for s in self.snapshots if s.status == 'rejected'])
        active = len([s for s in self.snapshots if s.status == 'active'])
        closed = len([s for s in self.snapshots if s.status in ['tp_hit', 'sl_hit', 'expired']])
        
        return {
            'total': total,
            'accepted': accepted,
            'rejected': rejected,
            'active': active,
            'closed': closed,
            'by_symbol': {
                'EURUSD': len([s for s in self.snapshots if s.symbol == 'EURUSD']),
                'XAUUSD': len([s for s in self.snapshots if s.symbol == 'XAUUSD'])
            }
        }


# Global instance
signal_snapshot_service = SignalSnapshotService()


def create_snapshot_from_signal_data(
    signal_id: str,
    symbol: str,
    direction: str,
    entry_price: float,
    stop_loss: float,
    take_profit: float,
    session: str,
    setup_type: str,
    score_breakdown: Dict,
    penalties: List[Dict],
    filters: List[Dict],
    status: str,
    acceptance_source: str = "",
    rejection_reason: str = "",
    blocking_filter: str = ""
) -> SignalSnapshot:
    """Helper function to create a snapshot from signal generation data"""
    
    # Calculate score pre/post penalty
    factor_total = sum(f.get('score_contribution', 0) for f in score_breakdown.get('factors', []))
    penalty_total = sum(p.get('penalty_value', 0) for p in penalties)
    final_score = score_breakdown.get('total_score', factor_total - penalty_total)
    
    # Determine confidence bucket
    if final_score >= 75:
        bucket = "75+"
    elif final_score >= 70:
        bucket = "70-74"
    elif final_score >= 65:
        bucket = "65-69"
    elif final_score >= 60:
        bucket = "60-64"
    else:
        bucket = "<60"
    
    # Calculate RR
    risk = abs(entry_price - stop_loss)
    reward = abs(take_profit - entry_price)
    rr_ratio = reward / risk if risk > 0 else 0
    
    # Generate summaries
    if status == 'accepted':
        strong_factors = [f for f in score_breakdown.get('factors', []) if f.get('normalized_value', 0) >= 70]
        strong_names = [f.get('factor_name', '') for f in strong_factors[:3]]
        summary_short = f"Score {final_score:.1f} | {session} | " + ", ".join(strong_names) if strong_names else f"Score {final_score:.1f}"
        summary_full = f"Accepted because score {final_score:.1f} met threshold. Strong factors: {', '.join(strong_names)}. " \
                      f"Session: {session}. Setup: {setup_type}. RR: {rr_ratio:.2f}"
    else:
        summary_short = f"Score {final_score:.1f} | Blocked by {blocking_filter or rejection_reason}"
        summary_full = f"Rejected with score {final_score:.1f}. Reason: {rejection_reason}. " \
                      f"Blocking filter: {blocking_filter}. Pre-penalty score: {factor_total:.1f}, penalty: {penalty_total:.1f}"
    
    snapshot = SignalSnapshot(
        signal_id=signal_id,
        timestamp=datetime.utcnow().isoformat(),
        symbol=symbol,
        direction=direction,
        session=session,
        setup_type=setup_type,
        entry_price=entry_price,
        stop_loss=stop_loss,
        take_profit=take_profit,
        rr_ratio=rr_ratio,
        status=status if status == 'rejected' else 'active',
        acceptance_source=acceptance_source,
        rejection_reason=rejection_reason,
        blocking_filter=blocking_filter,
        score_pre_penalty=factor_total,
        score_post_penalty=final_score,
        final_score=final_score,
        confidence_bucket=bucket,
        factor_contributions=score_breakdown.get('factors', []),
        penalties_applied=penalties,
        filters_checked=filters,
        summary_short=summary_short,
        summary_full=summary_full,
        notification_title=f"{symbol} {direction}" if status == 'accepted' else "",
        notification_body=summary_short if status == 'accepted' else ""
    )
    
    return snapshot
