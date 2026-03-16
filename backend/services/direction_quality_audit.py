"""
Direction Quality Audit Module
==============================

PURPOSE: Track and analyze directional quality (BUY/SELL decisions) for signal_generator_v3.

This module:
- Collects audit data for every generated signal
- Tracks rejection reasons by direction
- Calculates win/loss statistics by direction, session, regime, etc.
- Provides structured data for future calibration

IMPORTANT:
- This is AUDIT ONLY - no strategy changes
- No weight modifications
- No auto-optimization
- Data collection for evidence-based improvements
"""

import json
import logging
import asyncio
from typing import Dict, List, Optional, Any
from datetime import datetime, timedelta
from dataclasses import dataclass, field, asdict
from pathlib import Path
from enum import Enum

logger = logging.getLogger(__name__)

# Storage files
AUDIT_FILE = Path("/app/backend/storage/direction_quality_audit.json")
REJECTION_FILE = Path("/app/backend/storage/direction_rejections.json")


class TradeOutcome(Enum):
    """Trade outcome classification"""
    WIN = "WIN"
    LOSS = "LOSS"
    OPEN = "OPEN"
    EXPIRED = "EXPIRED"
    PENDING = "PENDING"


class ConfidenceBucket(Enum):
    """Confidence score buckets"""
    STRONG = "80+"
    GOOD = "70-79"
    ACCEPTABLE = "60-69"


class FTAQuality(Enum):
    """FTA quality classification"""
    CLEAN = "clean"        # ratio >= 0.80
    MODERATE = "moderate"  # 0.65 <= ratio < 0.80
    WEAK = "weak"          # 0.50 <= ratio < 0.65
    BLOCKED = "blocked"    # ratio < 0.50


class MTFAlignment(Enum):
    """Multi-timeframe alignment quality"""
    FULL = "full"          # All TFs aligned
    PARTIAL = "partial"    # 2/3 aligned
    WEAK = "weak"          # 1/3 aligned
    CONFLICTING = "conflicting"  # None aligned


class NewsRiskBucket(Enum):
    """News risk classification"""
    NONE = "none"
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"


@dataclass
class DirectionContext:
    """
    Structured context explaining why a direction was chosen.
    These are the factors that led to the BUY/SELL decision.
    """
    # Primary bias factors
    h1_bias: str = "neutral"           # bullish, bearish, neutral
    h1_bias_score: float = 0.0
    m15_bias: str = "neutral"
    m15_bias_score: float = 0.0
    m5_momentum: str = "neutral"       # bullish, bearish, neutral
    m5_momentum_score: float = 0.0
    
    # Structure factors
    market_structure: str = "unclear"  # bullish, bearish, unclear
    market_structure_score: float = 0.0
    pullback_quality: str = "weak"     # excellent, good, acceptable, weak
    pullback_quality_score: float = 0.0
    
    # Entry factors
    entry_quality: str = "unknown"     # optimal, good, acceptable, late
    entry_quality_score: float = 0.0
    
    # Risk factors
    fta_quality: str = "unknown"       # clean, moderate, weak
    fta_clean_space_ratio: float = 1.0
    
    # MTF alignment
    mtf_alignment: str = "unknown"     # full, partial, weak, conflicting
    mtf_alignment_score: float = 0.0
    
    # Session and external
    session: str = "unknown"
    session_score: float = 0.0
    news_risk: str = "none"
    news_penalty: float = 0.0
    spread_penalty: float = 0.0
    fta_penalty: float = 0.0
    concentration_penalty: float = 0.0
    
    # Final direction decision
    final_direction_reason: str = ""
    final_direction_score: float = 0.0
    
    def to_dict(self) -> Dict:
        return asdict(self)


@dataclass
class DirectionAuditRecord:
    """
    Complete audit record for a single signal's directional quality.
    """
    # Identification
    signal_id: str = ""
    symbol: str = ""
    direction: str = ""
    timestamp: str = ""
    
    # Trading parameters
    entry_price: float = 0.0
    stop_loss: float = 0.0
    take_profit: float = 0.0
    risk_reward: float = 0.0
    
    # Scores
    confidence_score: float = 0.0
    confidence_bucket: str = ""
    
    # Context
    session: str = ""
    regime: str = ""  # trending, ranging, mixed
    
    # Direction context (structured)
    direction_context: Dict = field(default_factory=dict)
    
    # Outcome tracking (updated later)
    outcome: str = "PENDING"
    mfe: float = 0.0  # Maximum Favorable Excursion (pips)
    mae: float = 0.0  # Maximum Adverse Excursion (pips)
    exit_price: float = 0.0
    exit_timestamp: str = ""
    pnl_pips: float = 0.0
    
    # Classification for grouping
    mtf_alignment: str = ""
    news_risk_bucket: str = ""
    fta_quality: str = ""
    
    def to_dict(self) -> Dict:
        return asdict(self)


@dataclass
class RejectionAuditRecord:
    """
    Audit record for a rejected signal candidate.
    """
    # Identification
    timestamp: str = ""
    symbol: str = ""
    intended_direction: str = ""
    
    # Rejection details
    rejection_reason: str = ""
    score_before_reject: float = 0.0
    
    # Active penalties at rejection
    active_penalties: Dict = field(default_factory=dict)
    
    # Direction context at rejection
    direction_context: Dict = field(default_factory=dict)
    
    def to_dict(self) -> Dict:
        return asdict(self)


@dataclass
class DirectionStats:
    """Statistics for a direction group"""
    total_trades: int = 0
    wins: int = 0
    losses: int = 0
    open_trades: int = 0
    winrate: float = 0.0
    avg_rr: float = 0.0
    avg_mfe: float = 0.0
    avg_mae: float = 0.0
    expectancy: float = 0.0
    
    def to_dict(self) -> Dict:
        return asdict(self)


class DirectionQualityAudit:
    """
    Direction Quality Audit System
    
    Tracks and analyzes directional quality without modifying strategy.
    Pure observation and data collection.
    """
    
    def __init__(self):
        self.audit_records: List[DirectionAuditRecord] = []
        self.rejection_records: List[RejectionAuditRecord] = []
        self._load_data()
        logger.info("📊 Direction Quality Audit initialized")
    
    def _load_data(self):
        """Load persisted audit data"""
        try:
            if AUDIT_FILE.exists():
                with open(AUDIT_FILE, 'r') as f:
                    data = json.load(f)
                    self.audit_records = [
                        DirectionAuditRecord(**r) for r in data.get('records', [])
                    ]
                logger.info(f"📂 Loaded {len(self.audit_records)} audit records")
            
            if REJECTION_FILE.exists():
                with open(REJECTION_FILE, 'r') as f:
                    data = json.load(f)
                    self.rejection_records = [
                        RejectionAuditRecord(**r) for r in data.get('rejections', [])
                    ]
                logger.info(f"📂 Loaded {len(self.rejection_records)} rejection records")
        except Exception as e:
            logger.warning(f"Could not load audit data: {e}")
    
    def _save_data(self):
        """Persist audit data"""
        try:
            AUDIT_FILE.parent.mkdir(parents=True, exist_ok=True)
            
            # Keep last 500 records to prevent file bloat
            recent_records = self.audit_records[-500:]
            with open(AUDIT_FILE, 'w') as f:
                json.dump({
                    'records': [r.to_dict() for r in recent_records],
                    'last_save': datetime.utcnow().isoformat()
                }, f, indent=2)
            
            # Keep last 1000 rejections
            recent_rejections = self.rejection_records[-1000:]
            with open(REJECTION_FILE, 'w') as f:
                json.dump({
                    'rejections': [r.to_dict() for r in recent_rejections],
                    'last_save': datetime.utcnow().isoformat()
                }, f, indent=2)
        except Exception as e:
            logger.warning(f"Could not save audit data: {e}")
    
    def record_signal(
        self,
        signal_id: str,
        symbol: str,
        direction: str,
        entry_price: float,
        stop_loss: float,
        take_profit: float,
        risk_reward: float,
        confidence_score: float,
        session: str,
        regime: str,
        direction_context: DirectionContext,
        mtf_alignment: str,
        news_risk: str,
        fta_quality: str
    ):
        """
        Record a generated signal for directional audit.
        Called when a signal passes all filters and is generated.
        """
        # Determine confidence bucket
        if confidence_score >= 80:
            confidence_bucket = ConfidenceBucket.STRONG.value
        elif confidence_score >= 70:
            confidence_bucket = ConfidenceBucket.GOOD.value
        else:
            confidence_bucket = ConfidenceBucket.ACCEPTABLE.value
        
        record = DirectionAuditRecord(
            signal_id=signal_id,
            symbol=symbol,
            direction=direction,
            timestamp=datetime.utcnow().isoformat(),
            entry_price=entry_price,
            stop_loss=stop_loss,
            take_profit=take_profit,
            risk_reward=risk_reward,
            confidence_score=confidence_score,
            confidence_bucket=confidence_bucket,
            session=session,
            regime=regime,
            direction_context=direction_context.to_dict(),
            outcome="PENDING",
            mtf_alignment=mtf_alignment,
            news_risk_bucket=news_risk,
            fta_quality=fta_quality
        )
        
        self.audit_records.append(record)
        self._save_data()
        
        logger.debug(f"📊 Direction audit recorded: {symbol} {direction}")
    
    def record_rejection(
        self,
        symbol: str,
        intended_direction: str,
        rejection_reason: str,
        score_before_reject: float,
        active_penalties: Dict,
        direction_context: Optional[DirectionContext] = None
    ):
        """
        Record a rejected signal candidate for analysis.
        """
        record = RejectionAuditRecord(
            timestamp=datetime.utcnow().isoformat(),
            symbol=symbol,
            intended_direction=intended_direction,
            rejection_reason=rejection_reason,
            score_before_reject=score_before_reject,
            active_penalties=active_penalties,
            direction_context=direction_context.to_dict() if direction_context else {}
        )
        
        self.rejection_records.append(record)
        
        # Save periodically
        if len(self.rejection_records) % 50 == 0:
            self._save_data()
    
    def update_outcome(
        self,
        signal_id: str,
        outcome: str,
        mfe: float,
        mae: float,
        exit_price: float,
        pnl_pips: float
    ):
        """
        Update the outcome of a tracked signal.
        Called when signal reaches SL, TP, or expires.
        """
        for record in self.audit_records:
            if record.signal_id == signal_id:
                record.outcome = outcome
                record.mfe = mfe
                record.mae = mae
                record.exit_price = exit_price
                record.exit_timestamp = datetime.utcnow().isoformat()
                record.pnl_pips = pnl_pips
                self._save_data()
                logger.info(f"📊 Outcome updated: {signal_id} -> {outcome}")
                return
    
    def _calculate_stats(self, records: List[DirectionAuditRecord]) -> DirectionStats:
        """Calculate statistics for a group of records"""
        stats = DirectionStats()
        
        if not records:
            return stats
        
        stats.total_trades = len(records)
        stats.wins = sum(1 for r in records if r.outcome == "WIN")
        stats.losses = sum(1 for r in records if r.outcome == "LOSS")
        stats.open_trades = sum(1 for r in records if r.outcome in ["OPEN", "PENDING"])
        
        completed = [r for r in records if r.outcome in ["WIN", "LOSS"]]
        if completed:
            stats.winrate = (stats.wins / len(completed)) * 100
        
        # Averages
        rrs = [r.risk_reward for r in records if r.risk_reward > 0]
        mfes = [r.mfe for r in records if r.mfe > 0]
        maes = [r.mae for r in records if r.mae > 0]
        
        if rrs:
            stats.avg_rr = sum(rrs) / len(rrs)
        if mfes:
            stats.avg_mfe = sum(mfes) / len(mfes)
        if maes:
            stats.avg_mae = sum(maes) / len(maes)
        
        # Expectancy = (Win% × Avg Win) - (Loss% × Avg Loss)
        if completed and stats.avg_rr > 0:
            win_pct = stats.wins / len(completed)
            loss_pct = stats.losses / len(completed)
            stats.expectancy = (win_pct * stats.avg_rr) - loss_pct
        
        return stats
    
    def get_stats_by_symbol_direction(self) -> Dict:
        """
        Get win/loss statistics broken down by symbol + direction.
        
        Returns stats for:
        - EURUSD BUY
        - EURUSD SELL
        - XAUUSD BUY
        - XAUUSD SELL
        """
        groups = {
            "EURUSD_BUY": [],
            "EURUSD_SELL": [],
            "XAUUSD_BUY": [],
            "XAUUSD_SELL": []
        }
        
        for record in self.audit_records:
            key = f"{record.symbol}_{record.direction}"
            if key in groups:
                groups[key].append(record)
        
        return {
            key: self._calculate_stats(records).to_dict()
            for key, records in groups.items()
        }
    
    def get_stats_by_session(self) -> Dict:
        """Get statistics broken down by session"""
        sessions = {}
        
        for record in self.audit_records:
            session = record.session or "unknown"
            direction = record.direction
            key = f"{session}_{direction}"
            
            if key not in sessions:
                sessions[key] = []
            sessions[key].append(record)
        
        return {
            key: self._calculate_stats(records).to_dict()
            for key, records in sessions.items()
        }
    
    def get_stats_by_confidence_bucket(self) -> Dict:
        """Get statistics broken down by confidence bucket"""
        buckets = {}
        
        for record in self.audit_records:
            bucket = record.confidence_bucket or "unknown"
            direction = record.direction
            key = f"{bucket}_{direction}"
            
            if key not in buckets:
                buckets[key] = []
            buckets[key].append(record)
        
        return {
            key: self._calculate_stats(records).to_dict()
            for key, records in buckets.items()
        }
    
    def get_stats_by_mtf_alignment(self) -> Dict:
        """Get statistics broken down by MTF alignment quality"""
        alignments = {}
        
        for record in self.audit_records:
            alignment = record.mtf_alignment or "unknown"
            direction = record.direction
            key = f"{alignment}_{direction}"
            
            if key not in alignments:
                alignments[key] = []
            alignments[key].append(record)
        
        return {
            key: self._calculate_stats(records).to_dict()
            for key, records in alignments.items()
        }
    
    def get_stats_by_fta_quality(self) -> Dict:
        """Get statistics broken down by FTA quality"""
        fta_groups = {}
        
        for record in self.audit_records:
            fta = record.fta_quality or "unknown"
            direction = record.direction
            key = f"{fta}_{direction}"
            
            if key not in fta_groups:
                fta_groups[key] = []
            fta_groups[key].append(record)
        
        return {
            key: self._calculate_stats(records).to_dict()
            for key, records in fta_groups.items()
        }
    
    def get_stats_by_news_risk(self) -> Dict:
        """Get statistics broken down by news risk"""
        news_groups = {}
        
        for record in self.audit_records:
            news = record.news_risk_bucket or "none"
            direction = record.direction
            key = f"{news}_{direction}"
            
            if key not in news_groups:
                news_groups[key] = []
            news_groups[key].append(record)
        
        return {
            key: self._calculate_stats(records).to_dict()
            for key, records in news_groups.items()
        }
    
    def get_rejection_analysis(self) -> Dict:
        """
        Analyze rejection patterns by direction.
        """
        buy_rejections = [r for r in self.rejection_records if r.intended_direction == "BUY"]
        sell_rejections = [r for r in self.rejection_records if r.intended_direction == "SELL"]
        
        # Count by reason
        buy_reasons = {}
        for r in buy_rejections:
            reason = r.rejection_reason
            buy_reasons[reason] = buy_reasons.get(reason, 0) + 1
        
        sell_reasons = {}
        for r in sell_rejections:
            reason = r.rejection_reason
            sell_reasons[reason] = sell_reasons.get(reason, 0) + 1
        
        # By symbol
        buy_by_symbol = {}
        for r in buy_rejections:
            symbol = r.symbol
            buy_by_symbol[symbol] = buy_by_symbol.get(symbol, 0) + 1
        
        sell_by_symbol = {}
        for r in sell_rejections:
            symbol = r.symbol
            sell_by_symbol[symbol] = sell_by_symbol.get(symbol, 0) + 1
        
        return {
            "total_rejections": len(self.rejection_records),
            "buy_rejections": len(buy_rejections),
            "sell_rejections": len(sell_rejections),
            "buy_rejection_ratio": len(buy_rejections) / len(self.rejection_records) if self.rejection_records else 0,
            "sell_rejection_ratio": len(sell_rejections) / len(self.rejection_records) if self.rejection_records else 0,
            "buy_reasons": buy_reasons,
            "sell_reasons": sell_reasons,
            "buy_by_symbol": buy_by_symbol,
            "sell_by_symbol": sell_by_symbol
        }
    
    def get_top_patterns(self) -> Dict:
        """
        Identify top winning and losing directional patterns.
        """
        # Group by pattern: symbol + direction + regime
        patterns = {}
        
        for record in self.audit_records:
            if record.outcome not in ["WIN", "LOSS"]:
                continue
            
            # Create pattern key
            pattern_key = f"{record.symbol}_{record.direction}_{record.regime}_{record.session}"
            
            if pattern_key not in patterns:
                patterns[pattern_key] = {"wins": 0, "losses": 0, "records": []}
            
            if record.outcome == "WIN":
                patterns[pattern_key]["wins"] += 1
            else:
                patterns[pattern_key]["losses"] += 1
            patterns[pattern_key]["records"].append(record)
        
        # Calculate winrate per pattern
        pattern_stats = []
        for key, data in patterns.items():
            total = data["wins"] + data["losses"]
            if total >= 3:  # Minimum sample size
                winrate = (data["wins"] / total) * 100
                pattern_stats.append({
                    "pattern": key,
                    "wins": data["wins"],
                    "losses": data["losses"],
                    "total": total,
                    "winrate": round(winrate, 1)
                })
        
        # Sort by winrate
        sorted_patterns = sorted(pattern_stats, key=lambda x: x["winrate"], reverse=True)
        
        return {
            "top_winning_patterns": sorted_patterns[:5] if sorted_patterns else [],
            "top_losing_patterns": sorted_patterns[-5:][::-1] if sorted_patterns else []
        }
    
    def get_full_report(self) -> Dict:
        """
        Generate comprehensive direction quality report.
        """
        return {
            "report_generated": datetime.utcnow().isoformat(),
            "total_audit_records": len(self.audit_records),
            "total_rejection_records": len(self.rejection_records),
            
            "by_symbol_direction": self.get_stats_by_symbol_direction(),
            "by_session": self.get_stats_by_session(),
            "by_confidence_bucket": self.get_stats_by_confidence_bucket(),
            "by_mtf_alignment": self.get_stats_by_mtf_alignment(),
            "by_fta_quality": self.get_stats_by_fta_quality(),
            "by_news_risk": self.get_stats_by_news_risk(),
            
            "rejection_analysis": self.get_rejection_analysis(),
            "top_patterns": self.get_top_patterns(),
            
            "note": "AUDIT ONLY - No strategy weights modified"
        }


# Global instance
direction_quality_audit = DirectionQualityAudit()
