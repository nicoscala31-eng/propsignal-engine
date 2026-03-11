"""
Advanced Signal Scoring Engine - Weighted score model for signal quality
"""
import logging
from typing import Optional, Dict, List
from dataclasses import dataclass
from datetime import datetime

from models import Asset
from services.scanner_config import (
    ScannerConfig, DEFAULT_SCANNER_CONFIG, SignalGrade,
    ScoringWeights, SessionScoreAdjustments
)
from engines.setup_modules import SetupCandidate
from engines.mtf_bias_engine import MultiTimeframeBias, TimeframeBias

logger = logging.getLogger(__name__)


@dataclass
class ScoreComponent:
    """Individual score component"""
    name: str
    raw_score: float  # 0-100
    weight: float     # From config
    weighted_score: float
    reason: str


@dataclass
class SignalScore:
    """Complete signal score with breakdown"""
    total_score: float
    grade: SignalGrade
    components: List[ScoreComponent]
    passes_threshold: bool
    
    # Metadata
    setup_type: str
    asset: str
    direction: str
    scored_at: datetime = None
    rejection_reason: Optional[str] = None
    
    def __post_init__(self):
        if self.scored_at is None:
            self.scored_at = datetime.utcnow()
    
    def get_breakdown_text(self) -> str:
        """Get human-readable score breakdown"""
        lines = [f"Total Score: {self.total_score:.1f} ({self.grade.value})"]
        lines.append("-" * 40)
        for comp in self.components:
            lines.append(f"{comp.name}: {comp.raw_score:.0f} x {comp.weight:.1f}% = {comp.weighted_score:.1f}")
            lines.append(f"  → {comp.reason}")
        return "\n".join(lines)


class AdvancedScoringEngine:
    """
    Weighted scoring engine for signal quality assessment
    
    Replaces rigid boolean logic with flexible scoring:
    - Each factor contributes to total score
    - Score determines signal grade (A+, A, B, C, D)
    - Only signals above threshold are generated
    """
    
    def __init__(self, config: ScannerConfig = None):
        self.config = config or DEFAULT_SCANNER_CONFIG
    
    def score_signal(self, candidate: SetupCandidate, 
                     mtf_bias: Optional[MultiTimeframeBias],
                     session_name: str,
                     volatility_percentile: float) -> SignalScore:
        """
        Calculate comprehensive signal score
        
        Args:
            candidate: The setup candidate to score
            mtf_bias: Multi-timeframe bias analysis
            session_name: Current trading session
            volatility_percentile: Current volatility vs historical (0-100)
        
        Returns:
            SignalScore with complete breakdown
        """
        components = []
        weights = self.config.scoring_weights
        
        # 1. HTF Bias Alignment Score
        htf_score, htf_reason = self._score_htf_alignment(candidate, mtf_bias)
        components.append(ScoreComponent(
            name="HTF Bias Alignment",
            raw_score=htf_score,
            weight=weights.htf_bias_alignment,
            weighted_score=htf_score * weights.htf_bias_alignment / 100,
            reason=htf_reason
        ))
        
        # 2. Market Structure Score
        structure_score, structure_reason = self._score_market_structure(candidate)
        components.append(ScoreComponent(
            name="Market Structure",
            raw_score=structure_score,
            weight=weights.market_structure,
            weighted_score=structure_score * weights.market_structure / 100,
            reason=structure_reason
        ))
        
        # 3. Setup Quality Score
        setup_score, setup_reason = self._score_setup_quality(candidate)
        components.append(ScoreComponent(
            name="Setup Quality",
            raw_score=setup_score,
            weight=weights.setup_quality,
            weighted_score=setup_score * weights.setup_quality / 100,
            reason=setup_reason
        ))
        
        # 4. Momentum Confirmation Score
        momentum_score, momentum_reason = self._score_momentum(candidate)
        components.append(ScoreComponent(
            name="Momentum Confirmation",
            raw_score=momentum_score,
            weight=weights.momentum_confirmation,
            weighted_score=momentum_score * weights.momentum_confirmation / 100,
            reason=momentum_reason
        ))
        
        # 5. Session Quality Score
        session_score, session_reason = self._score_session(session_name)
        components.append(ScoreComponent(
            name="Session Quality",
            raw_score=session_score,
            weight=weights.session_quality,
            weighted_score=session_score * weights.session_quality / 100,
            reason=session_reason
        ))
        
        # 6. Volatility Quality Score
        vol_score, vol_reason = self._score_volatility(volatility_percentile)
        components.append(ScoreComponent(
            name="Volatility Quality",
            raw_score=vol_score,
            weight=weights.volatility_quality,
            weighted_score=vol_score * weights.volatility_quality / 100,
            reason=vol_reason
        ))
        
        # 7. Invalidation Cleanliness Score
        inv_score, inv_reason = self._score_invalidation(candidate)
        components.append(ScoreComponent(
            name="Invalidation Cleanliness",
            raw_score=inv_score,
            weight=weights.invalidation_cleanliness,
            weighted_score=inv_score * weights.invalidation_cleanliness / 100,
            reason=inv_reason
        ))
        
        # Calculate total
        total_score = sum(c.weighted_score for c in components)
        
        # Apply countertrend penalty if applicable
        if mtf_bias and mtf_bias.is_countertrend and not self.config.allow_countertrend:
            total_score -= self.config.countertrend_score_penalty
            components.append(ScoreComponent(
                name="Countertrend Penalty",
                raw_score=-self.config.countertrend_score_penalty,
                weight=100,
                weighted_score=-self.config.countertrend_score_penalty,
                reason="Setup against higher timeframe bias"
            ))
        
        # Determine grade
        grade = self._determine_grade(total_score)
        
        # Check threshold
        passes_threshold = total_score >= self.config.min_score_threshold
        rejection_reason = None if passes_threshold else f"Score {total_score:.1f} below threshold {self.config.min_score_threshold}"
        
        result = SignalScore(
            total_score=total_score,
            grade=grade,
            components=components,
            passes_threshold=passes_threshold,
            setup_type=candidate.setup_type.value,
            asset=candidate.asset.value,
            direction=candidate.direction,
            rejection_reason=rejection_reason
        )
        
        # Log score breakdown if configured
        if self.config.log_score_breakdown:
            logger.info(f"📊 Score for {candidate.asset.value} {candidate.direction}:")
            for comp in components:
                logger.info(f"   {comp.name}: {comp.raw_score:.0f} → {comp.weighted_score:.1f}")
            logger.info(f"   TOTAL: {total_score:.1f} ({grade.value}) - {'PASS' if passes_threshold else 'REJECT'}")
        
        return result
    
    def _score_htf_alignment(self, candidate: SetupCandidate, 
                              mtf_bias: Optional[MultiTimeframeBias]) -> tuple:
        """Score higher timeframe alignment"""
        if not mtf_bias:
            return 50, "No MTF bias data available"
        
        # Check alignment
        aligned = (
            (candidate.direction == "LONG" and mtf_bias.trade_direction == "LONG") or
            (candidate.direction == "SHORT" and mtf_bias.trade_direction == "SHORT")
        )
        
        if aligned:
            # Bonus for strong alignment
            if mtf_bias.alignment_score >= 80:
                return 100, f"Strong HTF alignment ({mtf_bias.alignment_score:.0f}%)"
            elif mtf_bias.alignment_score >= 60:
                return 85, f"Good HTF alignment ({mtf_bias.alignment_score:.0f}%)"
            else:
                return 70, f"Moderate HTF alignment ({mtf_bias.alignment_score:.0f}%)"
        
        elif mtf_bias.trade_direction == "NONE":
            return 50, "Neutral HTF bias - no clear direction"
        
        else:
            return 20, f"Countertrend to {mtf_bias.overall_bias.value} HTF bias"
    
    def _score_market_structure(self, candidate: SetupCandidate) -> tuple:
        """Score market structure quality"""
        score = candidate.structure_score
        
        if score >= 80:
            return score, "Excellent structure - clear HH/HL or LL/LH"
        elif score >= 60:
            return score, "Good structure with minor imperfections"
        elif score >= 40:
            return score, "Moderate structure - some conflicting signals"
        else:
            return score, "Weak structure - unclear market direction"
    
    def _score_setup_quality(self, candidate: SetupCandidate) -> tuple:
        """Score the setup pattern quality"""
        score = candidate.setup_quality_score
        setup_name = candidate.setup_type.value.replace("_", " ").title()
        
        if score >= 85:
            return score, f"High quality {setup_name} pattern"
        elif score >= 70:
            return score, f"Good {setup_name} pattern"
        elif score >= 55:
            return score, f"Acceptable {setup_name} pattern"
        else:
            return score, f"Weak {setup_name} pattern"
    
    def _score_momentum(self, candidate: SetupCandidate) -> tuple:
        """Score momentum confirmation"""
        score = candidate.momentum_score
        
        if score >= 80:
            return score, "Strong momentum confirmation"
        elif score >= 60:
            return score, "Good momentum alignment"
        elif score >= 40:
            return score, "Mixed momentum signals"
        else:
            return score, "Weak or divergent momentum"
    
    def _score_session(self, session_name: str) -> tuple:
        """Score based on trading session"""
        adjustments = self.config.session_adjustments
        
        session_scores = {
            "London-NY Overlap": (90 + adjustments.london_ny_overlap, "Peak liquidity - London/NY overlap"),
            "London": (80 + adjustments.london_open, "Good liquidity - London session"),
            "New York": (80 + adjustments.ny_open, "Good liquidity - New York session"),
            "Tokyo": (60 + adjustments.asian_session, "Lower liquidity - Asian session"),
            "Sydney": (50 + adjustments.asian_session, "Low liquidity - Sydney session"),
            "Off-Hours": (40 + adjustments.dead_hours, "Poor liquidity - off hours"),
        }
        
        base_score, reason = session_scores.get(session_name, (50, f"Unknown session: {session_name}"))
        return max(0, min(100, base_score)), reason
    
    def _score_volatility(self, percentile: float) -> tuple:
        """Score volatility quality (not too high, not too low)"""
        # Optimal range is 30-70 percentile
        if 30 <= percentile <= 70:
            score = 100 - abs(percentile - 50)  # Peak at 50
            return score, f"Optimal volatility ({percentile:.0f}th percentile)"
        elif 20 <= percentile < 30:
            return 70, f"Slightly low volatility ({percentile:.0f}th percentile)"
        elif 70 < percentile <= 80:
            return 70, f"Slightly high volatility ({percentile:.0f}th percentile)"
        elif percentile < 20:
            return 40, f"Very low volatility ({percentile:.0f}th percentile) - range may be tight"
        else:
            return 40, f"Very high volatility ({percentile:.0f}th percentile) - risky conditions"
    
    def _score_invalidation(self, candidate: SetupCandidate) -> tuple:
        """Score the cleanliness of stop loss placement"""
        # Calculate risk as percentage of entry
        if candidate.direction == "LONG":
            risk_pct = (candidate.entry_price - candidate.stop_loss) / candidate.entry_price * 100
        else:
            risk_pct = (candidate.stop_loss - candidate.entry_price) / candidate.entry_price * 100
        
        # Optimal risk is 0.5-1.5% for forex, 1-3% for gold
        if candidate.asset.value == "EURUSD":
            if 0.3 <= risk_pct <= 1.0:
                return 90, f"Clean SL placement ({risk_pct:.2f}% risk)"
            elif 0.2 <= risk_pct <= 1.5:
                return 70, f"Acceptable SL ({risk_pct:.2f}% risk)"
            else:
                return 50, f"Wide SL ({risk_pct:.2f}% risk) - may be far from structure"
        else:  # XAUUSD
            if 0.5 <= risk_pct <= 2.0:
                return 90, f"Clean SL placement ({risk_pct:.2f}% risk)"
            elif 0.3 <= risk_pct <= 3.0:
                return 70, f"Acceptable SL ({risk_pct:.2f}% risk)"
            else:
                return 50, f"Wide SL ({risk_pct:.2f}% risk)"
    
    def _determine_grade(self, score: float) -> SignalGrade:
        """Determine signal grade from score"""
        if score >= self.config.a_plus_threshold:
            return SignalGrade.A_PLUS
        elif score >= self.config.a_threshold:
            return SignalGrade.A
        elif score >= self.config.b_threshold:
            return SignalGrade.B
        elif score >= 60:
            return SignalGrade.C
        else:
            return SignalGrade.D


# Global instance
advanced_scoring_engine = AdvancedScoringEngine()
