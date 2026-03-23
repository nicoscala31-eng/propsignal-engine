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
    
    # ==================== THRESHOLD ANALYSIS REPORT ====================
    
    def get_threshold_analysis_report(self) -> Dict:
        """
        Comprehensive threshold analysis report for data-driven optimization.
        
        Groups trades by score buckets, analyzes rejections, and ranks
        component importance based on real outcome data.
        
        This is ANALYTICS ONLY - does not modify strategy.
        """
        return {
            "generated_at": datetime.utcnow().isoformat(),
            "data_summary": self._get_data_summary(),
            "buckets": self._get_bucket_analysis(),
            "rejections": self._get_rejection_performance(),
            "components": self._get_component_importance(),
            "summary": self._get_executive_summary()
        }
    
    def _get_data_summary(self) -> Dict:
        """Summary of available data"""
        total = len(self.candidates)
        accepted = [c for c in self.candidates if c.decision == "accepted"]
        rejected = [c for c in self.candidates if c.decision == "rejected"]
        
        # Outcome counts for accepted trades
        accepted_wins = len([c for c in accepted if c.outcome_data.outcome == "win"])
        accepted_losses = len([c for c in accepted if c.outcome_data.outcome == "loss"])
        accepted_pending = len([c for c in accepted if c.outcome_data.outcome == "pending"])
        
        # Simulated outcome counts for rejected trades
        rejected_sim_wins = len([c for c in rejected if c.outcome_data.outcome == "win"])
        rejected_sim_losses = len([c for c in rejected if c.outcome_data.outcome == "loss"])
        rejected_pending = len([c for c in rejected if c.outcome_data.outcome == "pending"])
        
        return {
            "total_candidates": total,
            "accepted_count": len(accepted),
            "rejected_count": len(rejected),
            "acceptance_rate": round(len(accepted) / total * 100, 1) if total > 0 else 0,
            "accepted_outcomes": {
                "wins": accepted_wins,
                "losses": accepted_losses,
                "pending": accepted_pending,
                "winrate": round(accepted_wins / (accepted_wins + accepted_losses) * 100, 1) if (accepted_wins + accepted_losses) > 0 else 0
            },
            "rejected_simulated": {
                "sim_wins": rejected_sim_wins,
                "sim_losses": rejected_sim_losses,
                "pending": rejected_pending,
                "sim_winrate": round(rejected_sim_wins / (rejected_sim_wins + rejected_sim_losses) * 100, 1) if (rejected_sim_wins + rejected_sim_losses) > 0 else 0
            }
        }
    
    def _get_bucket_analysis(self) -> Dict:
        """
        Analyze trades grouped by total_score buckets:
        <70, 70-74, 75-79, 80-84, 85+
        """
        buckets_config = [
            ("<70", 0, 70),
            ("70-74", 70, 75),
            ("75-79", 75, 80),
            ("80-84", 80, 85),
            ("85+", 85, 200)
        ]
        
        results = {}
        
        for bucket_name, min_score, max_score in buckets_config:
            # Filter candidates in this bucket
            in_bucket = [c for c in self.candidates 
                        if min_score <= c.score_breakdown.total_score < max_score]
            
            accepted = [c for c in in_bucket if c.decision == "accepted"]
            rejected = [c for c in in_bucket if c.decision == "rejected"]
            
            # Real outcomes for accepted trades
            accepted_wins = [c for c in accepted if c.outcome_data.outcome == "win"]
            accepted_losses = [c for c in accepted if c.outcome_data.outcome == "loss"]
            
            # Simulated outcomes for rejected trades
            rejected_sim_wins = [c for c in rejected if c.outcome_data.outcome == "win"]
            rejected_sim_losses = [c for c in rejected if c.outcome_data.outcome == "loss"]
            
            # Calculate metrics
            total_candidates = len(in_bucket)
            acceptance_rate = round(len(accepted) / total_candidates * 100, 1) if total_candidates > 0 else 0
            
            # RR analysis
            all_rr = [c.trade_levels.risk_reward for c in in_bucket if c.trade_levels.risk_reward > 0]
            avg_rr = round(statistics.mean(all_rr), 2) if all_rr else 0
            
            # Real performance (accepted trades only)
            real_wins = len(accepted_wins)
            real_losses = len(accepted_losses)
            real_winrate = round(real_wins / (real_wins + real_losses) * 100, 1) if (real_wins + real_losses) > 0 else 0
            real_total_r = sum(c.outcome_data.total_r for c in accepted if c.outcome_data.outcome in ["win", "loss"])
            
            # Expectancy calculation
            if real_wins + real_losses > 0:
                avg_win_r = sum(c.outcome_data.total_r for c in accepted_wins) / real_wins if real_wins > 0 else 0
                avg_loss_r = sum(c.outcome_data.total_r for c in accepted_losses) / real_losses if real_losses > 0 else -1
                expectancy = (real_winrate / 100 * avg_win_r) + ((100 - real_winrate) / 100 * avg_loss_r)
            else:
                avg_win_r = 0
                avg_loss_r = 0
                expectancy = 0
            
            # Simulated performance (rejected trades)
            sim_wins = len(rejected_sim_wins)
            sim_losses = len(rejected_sim_losses)
            sim_winrate = round(sim_wins / (sim_wins + sim_losses) * 100, 1) if (sim_wins + sim_losses) > 0 else 0
            sim_total_r = sum(c.outcome_data.total_r for c in rejected if c.outcome_data.outcome in ["win", "loss"])
            
            # MFE/MAE for accepted trades
            mfe_values = [c.outcome_data.mfe_r for c in accepted if c.outcome_data.mfe_r > 0]
            mae_values = [c.outcome_data.mae_r for c in accepted if c.outcome_data.mae_r > 0]
            avg_mfe = round(statistics.mean(mfe_values), 2) if mfe_values else 0
            avg_mae = round(statistics.mean(mae_values), 2) if mae_values else 0
            
            results[bucket_name] = {
                "total_candidates": total_candidates,
                "accepted": len(accepted),
                "rejected": len(rejected),
                "acceptance_rate": acceptance_rate,
                "avg_rr": avg_rr,
                "real_performance": {
                    "wins": real_wins,
                    "losses": real_losses,
                    "pending": len([c for c in accepted if c.outcome_data.outcome == "pending"]),
                    "winrate": real_winrate,
                    "total_r": round(real_total_r, 2),
                    "avg_win_r": round(avg_win_r, 2),
                    "avg_loss_r": round(avg_loss_r, 2),
                    "expectancy": round(expectancy, 3),
                    "avg_mfe": avg_mfe,
                    "avg_mae": avg_mae
                },
                "simulated_rejected": {
                    "sim_wins": sim_wins,
                    "sim_losses": sim_losses,
                    "pending": len([c for c in rejected if c.outcome_data.outcome == "pending"]),
                    "sim_winrate": sim_winrate,
                    "sim_total_r": round(sim_total_r, 2),
                    "missed_profit_if_positive": sim_total_r > 0
                }
            }
        
        return results
    
    def _get_rejection_performance(self) -> Dict:
        """
        Analyze rejections by reason with hypothetical performance.
        """
        rejected = [c for c in self.candidates if c.decision == "rejected"]
        
        # Group by rejection reason
        by_reason: Dict[str, List] = {}
        for c in rejected:
            reason = c.rejection_reason or "unknown"
            if reason not in by_reason:
                by_reason[reason] = []
            by_reason[reason].append(c)
        
        results = {}
        for reason, candidates in by_reason.items():
            # Score distribution
            scores = [c.score_breakdown.total_score for c in candidates]
            avg_score = round(statistics.mean(scores), 1) if scores else 0
            min_score = round(min(scores), 1) if scores else 0
            max_score = round(max(scores), 1) if scores else 0
            
            # Simulated outcomes
            sim_wins = [c for c in candidates if c.outcome_data.outcome == "win"]
            sim_losses = [c for c in candidates if c.outcome_data.outcome == "loss"]
            pending = [c for c in candidates if c.outcome_data.outcome == "pending"]
            
            sim_total_r = sum(c.outcome_data.total_r for c in candidates if c.outcome_data.outcome in ["win", "loss"])
            sim_winrate = round(len(sim_wins) / (len(sim_wins) + len(sim_losses)) * 100, 1) if (len(sim_wins) + len(sim_losses)) > 0 else 0
            
            # Average MFE/MAE from simulations
            mfe_values = [c.outcome_data.mfe_r for c in candidates if c.outcome_data.mfe_r > 0]
            mae_values = [c.outcome_data.mae_r for c in candidates if c.outcome_data.mae_r > 0]
            
            # Close to threshold analysis (delta >= -5)
            close_to_threshold = [c for c in candidates if c.score_breakdown.score_delta >= -5]
            close_sim_wins = len([c for c in close_to_threshold if c.outcome_data.outcome == "win"])
            close_sim_losses = len([c for c in close_to_threshold if c.outcome_data.outcome == "loss"])
            
            # Verdict
            if len(sim_wins) + len(sim_losses) >= 5:
                if sim_total_r > 0 and sim_winrate >= 50:
                    verdict = "POTENTIALLY_OVER_FILTERING"
                elif sim_total_r < -2:
                    verdict = "FILTER_WORKING_WELL"
                else:
                    verdict = "NEUTRAL"
            else:
                verdict = "INSUFFICIENT_DATA"
            
            results[reason] = {
                "count": len(candidates),
                "frequency_pct": round(len(candidates) / len(rejected) * 100, 1) if rejected else 0,
                "score_distribution": {
                    "avg": avg_score,
                    "min": min_score,
                    "max": max_score
                },
                "hypothetical_performance": {
                    "sim_wins": len(sim_wins),
                    "sim_losses": len(sim_losses),
                    "pending": len(pending),
                    "sim_winrate": sim_winrate,
                    "sim_total_r": round(sim_total_r, 2),
                    "avg_mfe": round(statistics.mean(mfe_values), 2) if mfe_values else 0,
                    "avg_mae": round(statistics.mean(mae_values), 2) if mae_values else 0
                },
                "close_to_threshold": {
                    "count": len(close_to_threshold),
                    "close_sim_wins": close_sim_wins,
                    "close_sim_losses": close_sim_losses
                },
                "verdict": verdict
            }
        
        return results
    
    def _get_component_importance(self) -> Dict:
        """
        Rank components by their correlation with winning trades.
        Higher delta = stronger edge indicator.
        """
        accepted = [c for c in self.candidates if c.decision == "accepted"]
        wins = [c for c in accepted if c.outcome_data.outcome == "win"]
        losses = [c for c in accepted if c.outcome_data.outcome == "loss"]
        
        # All score components to analyze
        components = [
            ("mtf_score", "MTF Alignment"),
            ("structure_score", "Market Structure"),
            ("momentum_score", "Momentum"),
            ("session_score", "Session Quality"),
            ("pullback_score", "Pullback Quality"),
            ("entry_quality_score", "Entry Quality"),
            ("key_level_score", "Key Level Reaction"),
            ("rr_score", "Risk/Reward"),
            ("volatility_score", "Volatility"),
            ("regime_score", "Market Regime"),
            ("spread_score", "Spread"),
            ("concentration_score", "Concentration"),
            ("h1_bias_score", "H1 Directional Bias"),
            ("m15_context_score", "M15 Context")
        ]
        
        # Penalties to analyze (negative correlation expected)
        penalties = [
            ("fta_penalty", "FTA Penalty"),
            ("news_penalty", "News Penalty"),
            ("spread_penalty", "Spread Penalty"),
            ("setup_penalty", "Setup Penalty")
        ]
        
        results = {}
        
        # Analyze regular components
        for attr_name, display_name in components:
            win_scores = [getattr(c.score_breakdown, attr_name, 0) for c in wins]
            loss_scores = [getattr(c.score_breakdown, attr_name, 0) for c in losses]
            all_scores = [getattr(c.score_breakdown, attr_name, 0) for c in accepted]
            
            avg_win = round(statistics.mean(win_scores), 1) if win_scores else 0
            avg_loss = round(statistics.mean(loss_scores), 1) if loss_scores else 0
            avg_all = round(statistics.mean(all_scores), 1) if all_scores else 0
            delta = round(avg_win - avg_loss, 1)
            
            results[attr_name] = {
                "name": display_name,
                "avg_in_wins": avg_win,
                "avg_in_losses": avg_loss,
                "avg_overall": avg_all,
                "delta": delta,
                "correlation": "STRONG_POSITIVE" if delta >= 10 else "POSITIVE" if delta > 0 else "NEGATIVE" if delta < -10 else "WEAK_NEGATIVE" if delta < 0 else "NEUTRAL"
            }
        
        # Analyze penalties (lower penalty in wins = good filter)
        for attr_name, display_name in penalties:
            win_penalties = [getattr(c.score_breakdown, attr_name, 0) for c in wins]
            loss_penalties = [getattr(c.score_breakdown, attr_name, 0) for c in losses]
            
            avg_win = round(statistics.mean(win_penalties), 1) if win_penalties else 0
            avg_loss = round(statistics.mean(loss_penalties), 1) if loss_penalties else 0
            delta = round(avg_loss - avg_win, 1)  # Inverted: higher loss penalty = good filter
            
            results[attr_name] = {
                "name": display_name,
                "avg_in_wins": avg_win,
                "avg_in_losses": avg_loss,
                "delta": delta,
                "correlation": "GOOD_FILTER" if delta > 5 else "WEAK_FILTER" if delta > 0 else "BAD_FILTER" if delta < -5 else "INEFFECTIVE"
            }
        
        return results
    
    def _get_executive_summary(self) -> Dict:
        """
        Generate actionable insights from the data.
        """
        accepted = [c for c in self.candidates if c.decision == "accepted"]
        rejected = [c for c in self.candidates if c.decision == "rejected"]
        
        wins = [c for c in accepted if c.outcome_data.outcome == "win"]
        losses = [c for c in accepted if c.outcome_data.outcome == "loss"]
        
        # Find best performing score range
        bucket_analysis = self._get_bucket_analysis()
        best_bucket = None
        best_expectancy = -999
        worst_bucket = None
        worst_expectancy = 999
        
        for bucket_name, data in bucket_analysis.items():
            exp = data["real_performance"]["expectancy"]
            if exp > best_expectancy and (data["real_performance"]["wins"] + data["real_performance"]["losses"]) >= 3:
                best_expectancy = exp
                best_bucket = bucket_name
            if exp < worst_expectancy and (data["real_performance"]["wins"] + data["real_performance"]["losses"]) >= 3:
                worst_expectancy = exp
                worst_bucket = bucket_name
        
        # Find potentially over-filtering rejection reasons
        rejection_analysis = self._get_rejection_performance()
        over_filtering = []
        good_filters = []
        
        for reason, data in rejection_analysis.items():
            if data["verdict"] == "POTENTIALLY_OVER_FILTERING":
                over_filtering.append({
                    "reason": reason,
                    "missed_r": data["hypothetical_performance"]["sim_total_r"],
                    "sim_winrate": data["hypothetical_performance"]["sim_winrate"]
                })
            elif data["verdict"] == "FILTER_WORKING_WELL":
                good_filters.append({
                    "reason": reason,
                    "avoided_loss_r": abs(data["hypothetical_performance"]["sim_total_r"]),
                    "sim_winrate": data["hypothetical_performance"]["sim_winrate"]
                })
        
        # Rank components by edge
        component_analysis = self._get_component_importance()
        strongest_edge = sorted(
            [(k, v) for k, v in component_analysis.items() if "penalty" not in k],
            key=lambda x: x[1]["delta"],
            reverse=True
        )[:5]
        
        weakest_components = sorted(
            [(k, v) for k, v in component_analysis.items() if "penalty" not in k],
            key=lambda x: x[1]["delta"]
        )[:3]
        
        # Calculate overall edge
        total_r = sum(c.outcome_data.total_r for c in accepted if c.outcome_data.outcome in ["win", "loss"])
        trade_count = len(wins) + len(losses)
        avg_r_per_trade = round(total_r / trade_count, 3) if trade_count > 0 else 0
        
        return {
            "data_quality": {
                "total_candidates_analyzed": len(self.candidates),
                "trades_with_outcomes": trade_count,
                "sufficient_data": trade_count >= 20
            },
            "overall_performance": {
                "winrate": round(len(wins) / trade_count * 100, 1) if trade_count > 0 else 0,
                "total_r": round(total_r, 2),
                "avg_r_per_trade": avg_r_per_trade,
                "profitable": total_r > 0
            },
            "best_score_range": {
                "bucket": best_bucket or "N/A",
                "expectancy": round(best_expectancy, 3) if best_bucket else 0
            },
            "worst_score_range": {
                "bucket": worst_bucket or "N/A",
                "expectancy": round(worst_expectancy, 3) if worst_bucket else 0
            },
            "potentially_over_filtering": over_filtering,
            "effective_filters": good_filters,
            "strongest_edge_components": [
                {"component": k, "name": v["name"], "delta": v["delta"]}
                for k, v in strongest_edge
            ],
            "weakest_components": [
                {"component": k, "name": v["name"], "delta": v["delta"]}
                for k, v in weakest_components
            ],
            "recommendations": self._generate_recommendations(
                bucket_analysis, rejection_analysis, component_analysis,
                total_r, trade_count, over_filtering
            )
        }
    
    def _generate_recommendations(
        self, 
        buckets: Dict, 
        rejections: Dict, 
        components: Dict,
        total_r: float,
        trade_count: int,
        over_filtering: List
    ) -> List[str]:
        """Generate actionable recommendations based on analysis."""
        recommendations = []
        
        # Check if we have enough data
        if trade_count < 20:
            recommendations.append(
                f"⚠️ Only {trade_count} trades with outcomes. Need 20+ for reliable analysis. Continue collecting data."
            )
            return recommendations
        
        # Overall profitability
        if total_r > 0:
            recommendations.append(
                f"✅ Strategy is profitable (+{total_r:.2f}R over {trade_count} trades). Focus on consistency."
            )
        else:
            recommendations.append(
                f"⚠️ Strategy is negative ({total_r:.2f}R). Review filters and consider tightening thresholds."
            )
        
        # Over-filtering check
        if over_filtering:
            for item in over_filtering[:2]:
                recommendations.append(
                    f"🔍 Consider relaxing '{item['reason']}' filter - simulated {item['sim_winrate']:.1f}% winrate with +{item['missed_r']:.2f}R missed."
                )
        
        # Component-based recommendations
        for comp_name, data in components.items():
            if "penalty" not in comp_name and data["delta"] >= 15:
                recommendations.append(
                    f"✅ '{data['name']}' is a strong edge indicator (+{data['delta']} delta). Prioritize high values."
                )
            elif "penalty" not in comp_name and data["delta"] <= -10:
                recommendations.append(
                    f"⚠️ '{data['name']}' shows negative correlation ({data['delta']} delta). Consider de-weighting."
                )
        
        # Bucket-based recommendations
        for bucket_name, data in buckets.items():
            perf = data["real_performance"]
            if perf["wins"] + perf["losses"] >= 5:
                if perf["expectancy"] >= 0.3:
                    recommendations.append(
                        f"✅ Score range {bucket_name} shows strong edge (expectancy: {perf['expectancy']:.2f}R)."
                    )
                elif perf["expectancy"] <= -0.2:
                    recommendations.append(
                        f"⚠️ Score range {bucket_name} is underperforming (expectancy: {perf['expectancy']:.2f}R). Consider tightening."
                    )
        
        return recommendations[:7]  # Limit to top 7 recommendations


# Global instance
candidate_audit_service = CandidateAuditService()
