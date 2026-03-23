"""
Candidate Trade Audit Service
==============================

FULL THRESHOLD BREAKDOWN logging for ALL candidate trades.
This is ANALYSIS ONLY - does not affect trading decisions.

Purpose:
- Track every candidate trade with full score breakdown
- Compare accepted vs rejected trades
- Analyze which components correlate with profitability
- Enable data-driven threshold optimization
"""

import json
import logging
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Any
from dataclasses import dataclass, field, asdict
from enum import Enum
from pathlib import Path
import statistics

logger = logging.getLogger(__name__)


class CandidateDecision(Enum):
    ACCEPTED = "accepted"
    REJECTED = "rejected"


class TradeOutcome(Enum):
    PENDING = "pending"
    WIN = "win"
    LOSS = "loss"
    EXPIRED = "expired"
    OPEN = "open"


@dataclass
class ScoreBreakdown:
    """Full score breakdown for a candidate trade"""
    # Core scores
    total_score: float = 0.0
    threshold_required: float = 75.0
    score_delta: float = 0.0  # total_score - threshold
    
    # Individual components
    mtf_score: float = 0.0
    structure_score: float = 0.0
    momentum_score: float = 0.0
    session_score: float = 0.0
    pullback_score: float = 0.0
    entry_quality_score: float = 0.0
    key_level_score: float = 0.0
    rr_score: float = 0.0
    volatility_score: float = 0.0
    regime_score: float = 0.0
    spread_score: float = 0.0
    concentration_score: float = 0.0
    h1_bias_score: float = 0.0
    m15_context_score: float = 0.0
    
    # Penalties (negative values)
    fta_penalty: float = 0.0
    news_penalty: float = 0.0
    spread_penalty: float = 0.0
    setup_penalty: float = 0.0
    
    # FTA specific
    fta_distance_r: float = 0.0
    fta_level: float = 0.0
    clean_space_r: float = 0.0
    
    def to_dict(self) -> Dict:
        return asdict(self)


@dataclass
class FilterFlags:
    """Filter pass/fail flags"""
    score_passed: bool = False
    mtf_passed: bool = False
    fta_passed: bool = False
    session_passed: bool = False
    asset_passed: bool = False
    duplicate_blocked: bool = False
    news_blocked: bool = False
    rr_passed: bool = False
    spread_passed: bool = False
    daily_limit_passed: bool = True
    
    def to_dict(self) -> Dict:
        return asdict(self)


@dataclass
class TradeLevels:
    """Trade entry/exit levels"""
    entry: float = 0.0
    stop_loss: float = 0.0
    take_profit_1: float = 0.0
    take_profit_2: float = 0.0
    risk_reward: float = 0.0
    sl_pips: float = 0.0
    tp_pips: float = 0.0
    
    def to_dict(self) -> Dict:
        return asdict(self)


@dataclass
class OutcomeData:
    """Trade outcome data (real or simulated)"""
    outcome: str = "pending"  # win/loss/expired/open/pending
    is_simulated: bool = True
    total_r: float = 0.0
    mfe_r: float = 0.0  # Max Favorable Excursion
    mae_r: float = 0.0  # Max Adverse Excursion
    peak_r: float = 0.0
    time_to_outcome_minutes: float = 0.0
    
    def to_dict(self) -> Dict:
        return asdict(self)


@dataclass
class CandidateTrade:
    """Full candidate trade record with all data"""
    # Identity
    candidate_id: str = ""
    timestamp: str = ""
    
    # Basic info
    symbol: str = ""
    direction: str = ""
    session: str = ""
    setup_type: str = ""
    
    # Decision
    decision: str = "rejected"  # accepted/rejected
    rejection_reason: str = ""
    rejection_details: str = ""
    
    # Scores
    score_breakdown: ScoreBreakdown = field(default_factory=ScoreBreakdown)
    
    # Filters
    filter_flags: FilterFlags = field(default_factory=FilterFlags)
    
    # Levels
    trade_levels: TradeLevels = field(default_factory=TradeLevels)
    
    # Outcome
    outcome_data: OutcomeData = field(default_factory=OutcomeData)
    
    def to_dict(self) -> Dict:
        return {
            "candidate_id": self.candidate_id,
            "timestamp": self.timestamp,
            "symbol": self.symbol,
            "direction": self.direction,
            "session": self.session,
            "setup_type": self.setup_type,
            "decision": self.decision,
            "rejection_reason": self.rejection_reason,
            "rejection_details": self.rejection_details,
            "score_breakdown": self.score_breakdown.to_dict(),
            "filter_flags": self.filter_flags.to_dict(),
            "trade_levels": self.trade_levels.to_dict(),
            "outcome_data": self.outcome_data.to_dict()
        }


class CandidateAuditService:
    """
    Service for tracking and analyzing ALL candidate trades.
    
    Stores:
    - Every trade that reaches pre-filter stage
    - Full score breakdowns
    - Filter pass/fail flags
    - Outcome data (real for accepted, simulated for rejected)
    """
    
    STORAGE_FILE = Path("/app/backend/data/candidate_audit.json")
    MAX_RECORDS = 1000  # Keep last N records
    
    def __init__(self):
        self.candidates: List[CandidateTrade] = []
        self._load_data()
        logger.info("📊 Candidate Audit Service initialized")
    
    def _load_data(self):
        """Load persisted candidate data"""
        try:
            if self.STORAGE_FILE.exists():
                with open(self.STORAGE_FILE, 'r') as f:
                    data = json.load(f)
                    for record in data.get('candidates', []):
                        candidate = CandidateTrade(
                            candidate_id=record.get('candidate_id', ''),
                            timestamp=record.get('timestamp', ''),
                            symbol=record.get('symbol', ''),
                            direction=record.get('direction', ''),
                            session=record.get('session', ''),
                            setup_type=record.get('setup_type', ''),
                            decision=record.get('decision', 'rejected'),
                            rejection_reason=record.get('rejection_reason', ''),
                            rejection_details=record.get('rejection_details', '')
                        )
                        
                        # Load score breakdown
                        sb = record.get('score_breakdown', {})
                        candidate.score_breakdown = ScoreBreakdown(**{k: v for k, v in sb.items() if hasattr(ScoreBreakdown, k)})
                        
                        # Load filter flags
                        ff = record.get('filter_flags', {})
                        candidate.filter_flags = FilterFlags(**{k: v for k, v in ff.items() if hasattr(FilterFlags, k)})
                        
                        # Load trade levels
                        tl = record.get('trade_levels', {})
                        candidate.trade_levels = TradeLevels(**{k: v for k, v in tl.items() if hasattr(TradeLevels, k)})
                        
                        # Load outcome data
                        od = record.get('outcome_data', {})
                        candidate.outcome_data = OutcomeData(**{k: v for k, v in od.items() if hasattr(OutcomeData, k)})
                        
                        self.candidates.append(candidate)
                    
                    logger.info(f"📊 Loaded {len(self.candidates)} candidate records")
        except Exception as e:
            logger.error(f"Error loading candidate audit data: {e}")
            self.candidates = []
    
    def _save_data(self):
        """Persist candidate data"""
        try:
            self.STORAGE_FILE.parent.mkdir(parents=True, exist_ok=True)
            
            # Keep only last N records
            if len(self.candidates) > self.MAX_RECORDS:
                self.candidates = self.candidates[-self.MAX_RECORDS:]
            
            data = {
                "updated_at": datetime.utcnow().isoformat(),
                "total_candidates": len(self.candidates),
                "candidates": [c.to_dict() for c in self.candidates]
            }
            
            with open(self.STORAGE_FILE, 'w') as f:
                json.dump(data, f, indent=2)
                
        except Exception as e:
            logger.error(f"Error saving candidate audit data: {e}")
    
    def record_candidate(
        self,
        symbol: str,
        direction: str,
        session: str,
        setup_type: str,
        decision: str,
        rejection_reason: str = "",
        rejection_details: str = "",
        score_breakdown: Dict = None,
        filter_flags: Dict = None,
        trade_levels: Dict = None,
        components: List = None
    ) -> str:
        """
        Record a candidate trade with FULL breakdown.
        
        Called for EVERY candidate that reaches pre-filter stage,
        whether accepted or rejected.
        """
        try:
            candidate_id = f"{symbol}_{direction}_{datetime.utcnow().strftime('%Y%m%d_%H%M%S_%f')}"
            
            candidate = CandidateTrade(
                candidate_id=candidate_id,
                timestamp=datetime.utcnow().isoformat(),
                symbol=symbol,
                direction=direction,
                session=session,
                setup_type=setup_type,
                decision=decision,
                rejection_reason=rejection_reason,
                rejection_details=rejection_details
            )
            
            # Parse score breakdown
            if score_breakdown:
                candidate.score_breakdown = ScoreBreakdown(
                    total_score=score_breakdown.get('total', 0),
                    threshold_required=score_breakdown.get('threshold', 75),
                    score_delta=score_breakdown.get('total', 0) - score_breakdown.get('threshold', 75),
                    mtf_score=score_breakdown.get('mtf', 0),
                    structure_score=score_breakdown.get('structure', 0),
                    momentum_score=score_breakdown.get('momentum', 0),
                    session_score=score_breakdown.get('session', 0),
                    pullback_score=score_breakdown.get('pullback', 0),
                    entry_quality_score=score_breakdown.get('entry_quality', 0),
                    key_level_score=score_breakdown.get('key_level', 0),
                    rr_score=score_breakdown.get('rr', 0),
                    volatility_score=score_breakdown.get('volatility', 0),
                    regime_score=score_breakdown.get('regime', 0),
                    spread_score=score_breakdown.get('spread', 0),
                    concentration_score=score_breakdown.get('concentration', 0),
                    h1_bias_score=score_breakdown.get('h1_bias', 0),
                    m15_context_score=score_breakdown.get('m15_context', 0),
                    fta_penalty=score_breakdown.get('fta_penalty', 0),
                    news_penalty=score_breakdown.get('news_penalty', 0),
                    spread_penalty=score_breakdown.get('spread_penalty', 0),
                    setup_penalty=score_breakdown.get('setup_penalty', 0),
                    fta_distance_r=score_breakdown.get('fta_distance_r', 0),
                    fta_level=score_breakdown.get('fta_level', 0),
                    clean_space_r=score_breakdown.get('clean_space_r', 0)
                )
            
            # Parse from components list if provided
            if components:
                for comp in components:
                    name = comp.get('name', '').lower().replace(' ', '_')
                    score = comp.get('score', 0)
                    
                    if 'mtf' in name:
                        candidate.score_breakdown.mtf_score = score
                    elif 'structure' in name or 'market_structure' in name:
                        candidate.score_breakdown.structure_score = score
                    elif 'momentum' in name:
                        candidate.score_breakdown.momentum_score = score
                    elif 'session' in name:
                        candidate.score_breakdown.session_score = score
                    elif 'pullback' in name:
                        candidate.score_breakdown.pullback_score = score
                    elif 'entry' in name:
                        candidate.score_breakdown.entry_quality_score = score
                    elif 'key_level' in name:
                        candidate.score_breakdown.key_level_score = score
                    elif 'risk' in name or 'reward' in name or 'rr' in name:
                        candidate.score_breakdown.rr_score = score
                    elif 'volatility' in name:
                        candidate.score_breakdown.volatility_score = score
                    elif 'regime' in name:
                        candidate.score_breakdown.regime_score = score
                    elif 'spread' in name:
                        candidate.score_breakdown.spread_score = score
                    elif 'h1' in name:
                        candidate.score_breakdown.h1_bias_score = score
                    elif 'm15' in name:
                        candidate.score_breakdown.m15_context_score = score
            
            # Parse filter flags
            if filter_flags:
                candidate.filter_flags = FilterFlags(
                    score_passed=filter_flags.get('score_passed', False),
                    mtf_passed=filter_flags.get('mtf_passed', False),
                    fta_passed=filter_flags.get('fta_passed', False),
                    session_passed=filter_flags.get('session_passed', False),
                    asset_passed=filter_flags.get('asset_passed', False),
                    duplicate_blocked=filter_flags.get('duplicate_blocked', False),
                    news_blocked=filter_flags.get('news_blocked', False),
                    rr_passed=filter_flags.get('rr_passed', False),
                    spread_passed=filter_flags.get('spread_passed', False),
                    daily_limit_passed=filter_flags.get('daily_limit_passed', True)
                )
            
            # Parse trade levels
            if trade_levels:
                candidate.trade_levels = TradeLevels(
                    entry=trade_levels.get('entry', 0),
                    stop_loss=trade_levels.get('stop_loss', 0),
                    take_profit_1=trade_levels.get('take_profit_1', 0),
                    take_profit_2=trade_levels.get('take_profit_2', 0),
                    risk_reward=trade_levels.get('risk_reward', 0),
                    sl_pips=trade_levels.get('sl_pips', 0),
                    tp_pips=trade_levels.get('tp_pips', 0)
                )
            
            self.candidates.append(candidate)
            
            # Save periodically
            if len(self.candidates) % 10 == 0:
                self._save_data()
            
            # Log summary
            logger.info(f"📊 CANDIDATE AUDIT: {symbol} {direction} | Decision: {decision} | Score: {candidate.score_breakdown.total_score:.1f} | Reason: {rejection_reason or 'N/A'}")
            
            return candidate_id
            
        except Exception as e:
            logger.error(f"Error recording candidate: {e}")
            return ""
    
    def update_outcome(
        self,
        candidate_id: str,
        outcome: str,
        is_simulated: bool,
        total_r: float = 0,
        mfe_r: float = 0,
        mae_r: float = 0,
        peak_r: float = 0,
        time_to_outcome: float = 0
    ):
        """Update outcome data for a candidate"""
        for candidate in self.candidates:
            if candidate.candidate_id == candidate_id:
                candidate.outcome_data = OutcomeData(
                    outcome=outcome,
                    is_simulated=is_simulated,
                    total_r=total_r,
                    mfe_r=mfe_r,
                    mae_r=mae_r,
                    peak_r=peak_r,
                    time_to_outcome_minutes=time_to_outcome
                )
                self._save_data()
                return True
        return False
    
    # ==================== ANALYSIS METHODS ====================
    
    def get_latest_candidates(self, limit: int = 50) -> List[Dict]:
        """Get latest candidate trades with full breakdown"""
        return [c.to_dict() for c in self.candidates[-limit:]]
    
    def get_latest_rejections(self, limit: int = 50) -> List[Dict]:
        """Get latest rejected trades with full breakdown"""
        rejected = [c for c in self.candidates if c.decision == "rejected"]
        return [c.to_dict() for c in rejected[-limit:]]
    
    def get_latest_accepted(self, limit: int = 50) -> List[Dict]:
        """Get latest accepted trades with full breakdown"""
        accepted = [c for c in self.candidates if c.decision == "accepted"]
        return [c.to_dict() for c in accepted[-limit:]]
    
    def get_score_bucket_analysis(self) -> Dict:
        """
        Analyze trades by total score buckets.
        
        Returns performance metrics for each score range.
        """
        buckets = {
            "<70": {"accepted": [], "rejected": []},
            "70-74": {"accepted": [], "rejected": []},
            "75-79": {"accepted": [], "rejected": []},
            "80-84": {"accepted": [], "rejected": []},
            "85+": {"accepted": [], "rejected": []}
        }
        
        for c in self.candidates:
            score = c.score_breakdown.total_score
            
            if score < 70:
                bucket = "<70"
            elif score < 75:
                bucket = "70-74"
            elif score < 80:
                bucket = "75-79"
            elif score < 85:
                bucket = "80-84"
            else:
                bucket = "85+"
            
            if c.decision == "accepted":
                buckets[bucket]["accepted"].append(c)
            else:
                buckets[bucket]["rejected"].append(c)
        
        results = {}
        for bucket_name, data in buckets.items():
            accepted = data["accepted"]
            rejected = data["rejected"]
            
            # Calculate metrics for accepted trades
            wins = [c for c in accepted if c.outcome_data.outcome == "win"]
            losses = [c for c in accepted if c.outcome_data.outcome == "loss"]
            
            total_accepted = len(accepted)
            total_rejected = len(rejected)
            win_count = len(wins)
            loss_count = len(losses)
            
            winrate = (win_count / (win_count + loss_count) * 100) if (win_count + loss_count) > 0 else 0
            total_r = sum(c.outcome_data.total_r for c in accepted if c.outcome_data.outcome in ["win", "loss"])
            expectancy = total_r / (win_count + loss_count) if (win_count + loss_count) > 0 else 0
            
            results[bucket_name] = {
                "accepted_count": total_accepted,
                "rejected_count": total_rejected,
                "wins": win_count,
                "losses": loss_count,
                "winrate": round(winrate, 1),
                "total_r": round(total_r, 2),
                "expectancy": round(expectancy, 3)
            }
        
        return results
    
    def get_component_analysis(self) -> Dict:
        """
        Analyze which score components correlate with winning/losing trades.
        """
        winning_accepted = [c for c in self.candidates if c.decision == "accepted" and c.outcome_data.outcome == "win"]
        losing_accepted = [c for c in self.candidates if c.decision == "accepted" and c.outcome_data.outcome == "loss"]
        
        components = [
            "mtf_score", "structure_score", "momentum_score", "session_score",
            "pullback_score", "entry_quality_score", "key_level_score", "rr_score"
        ]
        
        results = {}
        for comp in components:
            win_scores = [getattr(c.score_breakdown, comp, 0) for c in winning_accepted]
            loss_scores = [getattr(c.score_breakdown, comp, 0) for c in losing_accepted]
            
            avg_in_wins = statistics.mean(win_scores) if win_scores else 0
            avg_in_losses = statistics.mean(loss_scores) if loss_scores else 0
            
            results[comp] = {
                "avg_in_wins": round(avg_in_wins, 1),
                "avg_in_losses": round(avg_in_losses, 1),
                "difference": round(avg_in_wins - avg_in_losses, 1),
                "correlation": "positive" if avg_in_wins > avg_in_losses else "negative" if avg_in_wins < avg_in_losses else "neutral"
            }
        
        return results
    
    def get_rejection_analysis(self) -> Dict:
        """
        Analyze rejection reasons and identify potentially profitable rejects.
        """
        rejected = [c for c in self.candidates if c.decision == "rejected"]
        
        # Group by rejection reason
        by_reason = {}
        for c in rejected:
            reason = c.rejection_reason or "unknown"
            if reason not in by_reason:
                by_reason[reason] = []
            by_reason[reason].append(c)
        
        results = {}
        for reason, candidates in by_reason.items():
            # Count simulated outcomes
            sim_wins = [c for c in candidates if c.outcome_data.outcome == "win"]
            sim_losses = [c for c in candidates if c.outcome_data.outcome == "loss"]
            pending = [c for c in candidates if c.outcome_data.outcome == "pending"]
            
            sim_r = sum(c.outcome_data.total_r for c in candidates if c.outcome_data.outcome in ["win", "loss"])
            
            # Average score of rejected trades
            avg_score = statistics.mean([c.score_breakdown.total_score for c in candidates]) if candidates else 0
            
            # Count "close to threshold" trades
            close_to_threshold = [c for c in candidates if c.score_breakdown.score_delta >= -5]
            
            results[reason] = {
                "count": len(candidates),
                "simulated_wins": len(sim_wins),
                "simulated_losses": len(sim_losses),
                "pending": len(pending),
                "simulated_r": round(sim_r, 2),
                "avg_score": round(avg_score, 1),
                "close_to_threshold": len(close_to_threshold),
                "potentially_profitable": sim_r > 0
            }
        
        return results
    
    def get_filter_effectiveness(self) -> Dict:
        """
        Analyze which filters are correctly blocking losing trades
        vs incorrectly blocking winning trades.
        """
        rejected = [c for c in self.candidates if c.decision == "rejected"]
        
        filters = ["score_passed", "mtf_passed", "fta_passed", "session_passed", "asset_passed", "rr_passed"]
        
        results = {}
        for filter_name in filters:
            # Find candidates blocked by this specific filter
            blocked_by_this = [c for c in rejected if not getattr(c.filter_flags, filter_name, True)]
            
            if blocked_by_this:
                sim_wins = len([c for c in blocked_by_this if c.outcome_data.outcome == "win"])
                sim_losses = len([c for c in blocked_by_this if c.outcome_data.outcome == "loss"])
                
                correctly_blocked = sim_losses  # Blocked trades that would have lost
                incorrectly_blocked = sim_wins  # Blocked trades that would have won
                
                effectiveness = (correctly_blocked / (correctly_blocked + incorrectly_blocked) * 100) if (correctly_blocked + incorrectly_blocked) > 0 else 0
                
                results[filter_name] = {
                    "total_blocked": len(blocked_by_this),
                    "correctly_blocked": correctly_blocked,
                    "incorrectly_blocked": incorrectly_blocked,
                    "effectiveness_pct": round(effectiveness, 1),
                    "verdict": "effective" if effectiveness > 60 else "needs_review" if effectiveness > 40 else "potentially_harmful"
                }
        
        return results
    
    def get_threshold_performance_report(self) -> Dict:
        """
        Comprehensive threshold performance report.
        """
        return {
            "generated_at": datetime.utcnow().isoformat(),
            "total_candidates": len(self.candidates),
            "accepted": len([c for c in self.candidates if c.decision == "accepted"]),
            "rejected": len([c for c in self.candidates if c.decision == "rejected"]),
            "score_bucket_analysis": self.get_score_bucket_analysis(),
            "component_analysis": self.get_component_analysis(),
            "rejection_analysis": self.get_rejection_analysis(),
            "filter_effectiveness": self.get_filter_effectiveness()
        }
    
    def get_mtf_bucket_analysis(self) -> Dict:
        """Analyze by MTF score buckets"""
        return self._analyze_by_component("mtf_score", [
            ("<60", 0, 60),
            ("60-69", 60, 70),
            ("70-79", 70, 80),
            ("80-89", 80, 90),
            ("90+", 90, 101)
        ])
    
    def get_pullback_bucket_analysis(self) -> Dict:
        """Analyze by pullback score buckets"""
        return self._analyze_by_component("pullback_score", [
            ("<50", 0, 50),
            ("50-69", 50, 70),
            ("70-84", 70, 85),
            ("85-99", 85, 100),
            ("100", 100, 101)
        ])
    
    def _analyze_by_component(self, component_name: str, buckets: List[tuple]) -> Dict:
        """Generic component bucket analysis"""
        results = {}
        
        for bucket_name, min_val, max_val in buckets:
            accepted = [c for c in self.candidates 
                       if c.decision == "accepted" 
                       and min_val <= getattr(c.score_breakdown, component_name, 0) < max_val]
            rejected = [c for c in self.candidates 
                       if c.decision == "rejected" 
                       and min_val <= getattr(c.score_breakdown, component_name, 0) < max_val]
            
            wins = len([c for c in accepted if c.outcome_data.outcome == "win"])
            losses = len([c for c in accepted if c.outcome_data.outcome == "loss"])
            
            winrate = (wins / (wins + losses) * 100) if (wins + losses) > 0 else 0
            total_r = sum(c.outcome_data.total_r for c in accepted if c.outcome_data.outcome in ["win", "loss"])
            
            results[bucket_name] = {
                "accepted": len(accepted),
                "rejected": len(rejected),
                "wins": wins,
                "losses": losses,
                "winrate": round(winrate, 1),
                "total_r": round(total_r, 2)
            }
        
        return results


# Global instance
candidate_audit_service = CandidateAuditService()
