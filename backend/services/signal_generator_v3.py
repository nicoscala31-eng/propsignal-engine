"""
Signal Generator v3 - Technical Structure-Based Signal Engine
==============================================================

*** AUTHORIZED PRODUCTION ENGINE ***
*** SINGLE PRODUCTION PIPELINE - NO PARALLEL ENGINES ***

This is the ONLY engine authorized for production signal generation.
All other engines (market_scanner, advanced_scanner, signal_orchestrator) are DISABLED.

VERSION 3.2 - DATA-DRIVEN OPTIMIZATION (March 2026):
Based on 100-trade performance analysis, this version applies STRICT filters:

DATA-DRIVEN FILTERS (CRITICAL):
1. SCORE: Minimum 75 (was 60) - lower scores had negative expectancy
2. MTF ALIGNMENT: Only >= 80 allowed (-18R on weak MTF vs +7R on strong)
3. SESSION: London ONLY (London=+7R, Overlap=-17R, NY=-2R)
4. ASSETS: EURUSD ONLY (EURUSD=+0.6R, XAUUSD=-12R)
5. SETUPS: Only HTF Continuation (+8R) and Momentum Breakout (+3R)
   DISABLED: Fib Retracement (-10R), Structure Pullback (-4R), Technical Setup (-9R)
6. FTA: Do NOT block, only adjust TP or score

TRADE MANAGEMENT (NEW):
- Partial TP at 0.5R (close 50%) - 69% of losers saw profit first
- Move to BE at 1R
- Trailing stop after 1R

EXPECTED OUTCOME:
- Reduce signals from ~100 to ~15-20
- Transform from -0.12R expectancy to POSITIVE expectancy

PROP TRADING ASSUMPTIONS:
- account_size = 100,000
- max_daily_loss = 3,000
- operational_warning = 1,500
- risk_per_trade = 0.5% to 0.75% (DYNAMIC based on confidence)
- primary instruments = EURUSD ONLY (XAUUSD DISABLED)

CONFIDENCE CLASSIFICATION (UPDATED):
- 80-100: Strong setup (high priority) -> 0.75% risk
- 75-79: Good setup (normal priority) -> 0.65% risk
- Below 75: REJECT - data shows negative expectancy

MINIMUM STOP LOSS ENFORCED:
- EURUSD: 8.5 pips minimum

R:R HARD REJECTION:
- R:R < 1.1 = REJECT (raised from 0.95)
"""

import asyncio
import logging
import json
from typing import Dict, List, Optional, Tuple, Any
from datetime import datetime, timedelta
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path

from models import Asset, SignalType, Timeframe
from services.market_data_cache import market_data_cache
from services.market_validator import market_validator, MarketStatus
from engines.session_detector import session_detector
from services.direction_quality_audit import (
    direction_quality_audit, 
    DirectionContext,
    FTAQuality,
    MTFAlignment,
    NewsRiskBucket
)
from services.missed_opportunity_analyzer import missed_opportunity_analyzer

logger = logging.getLogger(__name__)

# State persistence file
STATE_FILE = Path("/app/backend/storage/signal_generator_state.json")


# ==================== PROP FIRM CONFIGURATION ====================

@dataclass
class PropFirmConfig:
    """Prop firm trading constraints"""
    account_size: float = 100_000.0
    max_daily_loss: float = 3_000.0
    operational_warning: float = 1_500.0
    min_risk_percent: float = 0.5
    max_risk_percent: float = 0.75
    default_risk_percent: float = 0.5


PROP_CONFIG = PropFirmConfig()


# ==================== ASSET CONFIGURATION ====================

@dataclass
class AssetConfig:
    """Asset-specific configuration"""
    pip_size: float
    pip_value: float
    min_sl_pips: float
    min_buffer_pips: float
    tp_buffer_pips: float


ASSET_CONFIGS = {
    Asset.EURUSD: AssetConfig(
        pip_size=0.0001,
        pip_value=10.0,
        min_sl_pips=8.5,      # Minimum SL to avoid noise
        min_buffer_pips=1.5,  # Buffer beyond swing point
        tp_buffer_pips=1.0    # TP placed before target
    ),
    Asset.XAUUSD: AssetConfig(
        pip_size=0.01,
        pip_value=1.0,
        min_sl_pips=85.0,     # Minimum SL for gold
        min_buffer_pips=20.0, # Buffer beyond swing point
        tp_buffer_pips=15.0   # TP placed before target
    )
}


# ==================== NEWS RISK DETECTION ====================

class NewsRiskLevel(Enum):
    """News risk classification"""
    HIGH = "HIGH"
    MEDIUM = "MEDIUM"
    LOW = "LOW"
    NONE = "NONE"


@dataclass
class NewsRiskInfo:
    """News risk information"""
    level: NewsRiskLevel
    event_name: Optional[str] = None
    minutes_until: Optional[int] = None
    score_penalty: float = 0.0
    warning: Optional[str] = None


# High-impact events for EURUSD
HIGH_IMPACT_EVENTS = [
    "NFP", "Non-Farm Payroll", "Nonfarm Payrolls",
    "CPI", "Consumer Price Index",
    "FOMC", "Federal Reserve",
    "ECB", "European Central Bank",
    "Interest Rate Decision", "Rate Decision",
    "GDP", "Retail Sales", "PMI",
    "Unemployment Rate", "Initial Jobless Claims"
]


# ==================== POSITION SIZING ENGINE ====================

@dataclass
class PositionSizeResult:
    """Position sizing calculation result"""
    recommended_lot_size: float
    money_at_risk: float
    risk_percent: float
    pip_risk: float
    pip_value: float
    adjusted: bool = False
    adjustment_reason: Optional[str] = None
    prop_warnings: List[str] = field(default_factory=list)
    daily_risk_used: float = 0.0
    daily_risk_remaining: float = 0.0


class PositionSizingEngine:
    """
    Position Sizing Engine with Dynamic Risk
    
    Uses:
    - Entry price
    - Stop loss price
    - Account size (100k default)
    - Risk percentage (0.5-0.75% DYNAMIC based on confidence)
    - Pip value per asset
    """
    
    def __init__(self, config: PropFirmConfig = PROP_CONFIG):
        self.config = config
        self.daily_risk_used = 0.0
        self.last_reset_date = datetime.utcnow().date()
    
    def _reset_daily_if_needed(self):
        """Reset daily risk counter if new day"""
        today = datetime.utcnow().date()
        if today != self.last_reset_date:
            self.daily_risk_used = 0.0
            self.last_reset_date = today
            logger.info("📅 Daily risk counter reset for new trading day")
    
    def get_dynamic_risk_percent(self, confidence_score: float) -> float:
        """
        Get dynamic risk percentage based on confidence score
        
        Mapping:
        - 80-100: 0.75%
        - 75-79: 0.65%
        - 70-74: 0.60%
        - 60-69: 0.50%
        """
        if confidence_score >= 80:
            return 0.75
        elif confidence_score >= 75:
            return 0.65
        elif confidence_score >= 70:
            return 0.60
        else:
            return 0.50
    
    def calculate(
        self,
        asset: Asset,
        entry_price: float,
        stop_loss: float,
        confidence_score: float = 70.0
    ) -> PositionSizeResult:
        """
        Calculate position size with dynamic risk
        
        Formula:
        1. Pip Risk = |Entry - SL| / pip_size
        2. Risk% = dynamic based on confidence
        3. Money at Risk = Account * Risk%
        4. Lot Size = Money at Risk / (Pip Risk * Pip Value)
        
        NOTE: Daily risk tracking is MANUAL ONLY - no auto-accumulation
        """
        self._reset_daily_if_needed()
        
        # Get asset config
        asset_config = ASSET_CONFIGS.get(asset, ASSET_CONFIGS[Asset.EURUSD])
        pip_size = asset_config.pip_size
        pip_value = asset_config.pip_value
        
        # Calculate pip risk
        pip_risk = abs(entry_price - stop_loss) / pip_size
        
        # Get dynamic risk percentage
        risk_percent = self.get_dynamic_risk_percent(confidence_score)
        
        # Calculate money at risk
        money_at_risk = self.config.account_size * (risk_percent / 100)
        
        # Calculate lot size
        if pip_risk > 0 and pip_value > 0:
            lot_size = money_at_risk / (pip_risk * pip_value)
        else:
            lot_size = 0.01  # Minimum
        
        # Round to 2 decimal places
        lot_size = round(lot_size, 2)
        
        # Ensure minimum lot size
        lot_size = max(0.01, lot_size)
        
        # No automatic daily limit blocking - manual management only
        warnings = []
        adjusted = False
        adjustment_reason = None
        
        # Just track remaining for display purposes (no blocking)
        remaining_daily = self.config.max_daily_loss - self.daily_risk_used
        
        # Show warning if at warning level (informational only)
        if self.daily_risk_used >= self.config.operational_warning:
            warnings.append(f"⚠️ INFO: Daily risk at ${self.daily_risk_used:.0f} (warning: ${self.config.operational_warning:.0f})")
        elif self.daily_risk_used + money_at_risk > self.config.operational_warning:
            warnings.append(f"Trade will reach warning level (${self.config.operational_warning:.0f})")
        
        # Recalculate final money at risk after adjustments
        final_money_at_risk = lot_size * pip_risk * pip_value if lot_size > 0 else 0
        final_risk_percent = (final_money_at_risk / self.config.account_size) * 100 if final_money_at_risk > 0 else 0
        
        return PositionSizeResult(
            recommended_lot_size=lot_size,
            money_at_risk=round(final_money_at_risk, 2),
            risk_percent=round(final_risk_percent, 3),
            pip_risk=round(pip_risk, 1),
            pip_value=pip_value,
            adjusted=adjusted,
            adjustment_reason=adjustment_reason,
            prop_warnings=warnings,
            daily_risk_used=round(self.daily_risk_used, 2),
            daily_risk_remaining=round(remaining_daily, 2)
        )
    
    def record_trade(self, money_at_risk: float):
        """
        Record a trade's risk for daily tracking - MANUAL TRACKING ONLY
        
        NOTE: This now only logs the trade, does NOT auto-accumulate.
        Daily risk is managed manually via reset endpoint.
        """
        self._reset_daily_if_needed()
        # Just log, don't accumulate automatically
        logger.info(f"💰 Trade logged: ${money_at_risk:.2f} (manual tracking mode)")
    
    def get_daily_status(self) -> Dict:
        """Get current daily risk status"""
        self._reset_daily_if_needed()
        remaining = self.config.max_daily_loss - self.daily_risk_used
        
        return {
            "account_size": self.config.account_size,
            "max_daily_loss": self.config.max_daily_loss,
            "operational_warning": self.config.operational_warning,
            "daily_risk_used": round(self.daily_risk_used, 2),
            "daily_risk_remaining": round(remaining, 2),
            "at_warning_level": self.daily_risk_used >= self.config.operational_warning,
            "trades_allowed": remaining > 0,
            "risk_per_trade_range": f"{self.config.min_risk_percent}% - {self.config.max_risk_percent}%"
        }


# ==================== SIGNAL DATA STRUCTURES ====================

class SignalConfidence(Enum):
    """Signal confidence levels - based on user requirements"""
    STRONG = "STRONG"           # 80-100
    GOOD = "GOOD"               # 70-79
    ACCEPTABLE = "ACCEPTABLE"   # 60-69
    REJECTED = "REJECTED"       # Below 60


@dataclass
class ScoreComponent:
    """Individual scoring component"""
    name: str
    weight: float
    score: float  # 0-100
    reason: str
    
    @property
    def weighted_score(self) -> float:
        return (self.score / 100) * self.weight


@dataclass
class SignalScore:
    """Complete signal score breakdown"""
    components: List[ScoreComponent]
    final_score: float
    confidence: SignalConfidence
    
    def to_dict(self) -> Dict:
        return {
            "final_score": round(self.final_score, 1),
            "confidence": self.confidence.value,
            "breakdown": [
                {
                    "factor": c.name,
                    "weight": c.weight,
                    "score": round(c.score, 1),
                    "contribution": round(c.weighted_score, 1),
                    "reason": c.reason
                }
                for c in self.components
            ]
        }


@dataclass
class StructuralLevels:
    """Technical structure levels for SL/TP"""
    swing_sl: Optional[float] = None
    swing_sl_type: str = "none"  # "swing_low", "swing_high", "atr_fallback"
    structural_tp1: Optional[float] = None
    structural_tp2: Optional[float] = None
    tp_type: str = "none"  # "swing_target", "extension", "atr_fallback"


@dataclass
class FirstTroubleArea:
    """
    First Trouble Area (FTA) - first technical obstacle between entry and target
    
    Used to validate if there's enough clean space for the trade to reach target.
    v4: Now a SOFT FILTER - affects score but rarely blocks
    """
    fta_price: Optional[float] = None
    fta_type: str = "none"  # swing_high, swing_low, local_resistance, local_support, 
                            # range_boundary, wick_rejection, congestion_zone
    fta_distance: float = 0.0       # Distance from entry to FTA
    target_distance: float = 0.0    # Distance from entry to target
    clean_space_ratio: float = 1.0  # fta_distance / target_distance (1.0 = no obstacle)
    fta_penalty: float = 0.0        # Score penalty/bonus applied
    fta_blocked_trade: bool = False # If True, trade was rejected due to FTA (RARE in v4)
    obstacles_count: int = 0        # Number of obstacles within 60% of target
    fta_quality: str = "clean"      # NEW v4: clean, moderate, weak
    fta_distance_in_r: float = 0.0  # NEW v4: FTA distance in Risk units
    
    def to_dict(self) -> Dict:
        return {
            "fta_price": self.fta_price,
            "fta_type": self.fta_type,
            "fta_distance": round(self.fta_distance, 5),
            "target_distance": round(self.target_distance, 5),
            "clean_space_ratio": round(self.clean_space_ratio, 3),
            "fta_penalty": self.fta_penalty,
            "fta_blocked_trade": self.fta_blocked_trade,
            "obstacles_count": self.obstacles_count,
            "fta_quality": self.fta_quality,
            "fta_distance_in_r": round(self.fta_distance_in_r, 2)
        }


@dataclass
class GeneratedSignal:
    """A generated trading signal with full metadata including position sizing"""
    signal_id: str
    asset: Asset
    direction: str  # BUY or SELL
    entry_price: float
    entry_zone_low: float
    entry_zone_high: float
    stop_loss: float
    take_profit_1: float
    take_profit_2: float
    risk_reward: float
    confidence_score: float
    confidence_level: SignalConfidence
    setup_type: str
    invalidation: str
    session: str
    score_breakdown: SignalScore
    timestamp: datetime
    
    # Position sizing
    recommended_lot_size: float = 0.0
    money_at_risk: float = 0.0
    risk_percent: float = 0.0
    pip_risk: float = 0.0
    position_adjusted: bool = False
    position_adjustment_reason: Optional[str] = None
    prop_warnings: List[str] = field(default_factory=list)
    daily_risk_used: float = 0.0
    daily_risk_remaining: float = 0.0
    
    # Technical structure info
    sl_type: str = "structural"  # "structural" or "atr_fallback"
    tp_type: str = "structural"  # "structural" or "atr_fallback"
    
    # News risk
    news_risk: NewsRiskLevel = NewsRiskLevel.NONE
    news_event: Optional[str] = None
    news_warning: Optional[str] = None
    
    # Spread info
    spread_pips: float = 0.0
    
    # First Trouble Area (FTA)
    fta_price: Optional[float] = None
    fta_type: str = "none"
    fta_distance: float = 0.0
    target_distance: float = 0.0
    clean_space_ratio: float = 1.0
    fta_penalty: float = 0.0
    fta_blocked_trade: bool = False
    fta_obstacles_count: int = 0
    
    def to_notification_dict(self) -> Dict:
        """
        Format for push notification
        """
        emoji = "🟢" if self.direction == "BUY" else "🔴"
        
        # Format prices based on asset
        if self.asset == Asset.EURUSD:
            entry_str = f"{self.entry_price:.5f}"
            sl_str = f"{self.stop_loss:.5f}"
            tp_str = f"{self.take_profit_1:.5f}"
        else:  # XAUUSD
            entry_str = f"{self.entry_price:.2f}"
            sl_str = f"{self.stop_loss:.2f}"
            tp_str = f"{self.take_profit_1:.2f}"
        
        # Build notification body with all required fields
        body_lines = [
            f"Entry: {entry_str}",
            f"SL: {sl_str} | TP: {tp_str}",
            f"Conf: {self.confidence_score:.0f}% | R:R: {self.risk_reward:.2f}",
            f"Lot: {self.recommended_lot_size:.2f} | Risk: ${self.money_at_risk:.0f}"
        ]
        
        # Add news warning if present
        if self.news_risk != NewsRiskLevel.NONE and self.news_warning:
            body_lines.append(f"⚠️ {self.news_warning}")
        
        # Add FTA info only if there's an obstacle
        if self.clean_space_ratio < 0.80 and self.fta_type != "none":
            body_lines.append(f"📊 Ostacolo intermedio ({self.clean_space_ratio:.0%})")
        
        body = "\n".join(body_lines)
        
        return {
            "title": f"{emoji} {self.direction} {self.asset.value}",
            "body": body,
            "data": {
                "type": "signal",
                "signal_id": self.signal_id,
                "asset": self.asset.value,
                "direction": self.direction,
                "entry": self.entry_price,
                "entry_zone": [self.entry_zone_low, self.entry_zone_high],
                "stop_loss": self.stop_loss,
                "take_profit_1": self.take_profit_1,
                "take_profit_2": self.take_profit_2,
                "risk_reward": round(self.risk_reward, 2),
                "confidence": self.confidence_score,
                "confidence_level": self.confidence_level.value,
                "setup_type": self.setup_type,
                "invalidation": self.invalidation,
                "session": self.session,
                "timestamp": self.timestamp.isoformat(),
                # Position sizing data (FIXED - all fields populated)
                "lot_size": self.recommended_lot_size,
                "money_at_risk": self.money_at_risk,
                "risk_percent": self.risk_percent,
                "pip_risk": self.pip_risk,
                "prop_warnings": self.prop_warnings,
                "daily_risk_used": self.daily_risk_used,
                "daily_risk_remaining": self.daily_risk_remaining,
                # Structure info
                "sl_type": self.sl_type,
                "tp_type": self.tp_type,
                # News risk data
                "news_risk": self.news_risk.value,
                "news_event": self.news_event,
                "news_warning": self.news_warning,
                # Spread
                "spread_pips": self.spread_pips,
                # First Trouble Area (FTA)
                "fta_price": self.fta_price,
                "fta_type": self.fta_type,
                "fta_distance": self.fta_distance,
                "target_distance": self.target_distance,
                "clean_space_ratio": self.clean_space_ratio,
                "fta_penalty": self.fta_penalty,
                "fta_obstacles_count": self.fta_obstacles_count
            }
        }


@dataclass
class RecentSignal:
    """Track recent signals for duplicate prevention"""
    signal_id: str
    asset: Asset
    direction: str
    price: float
    timestamp: datetime


# ==================== MAIN SIGNAL GENERATOR ====================

class SignalGeneratorV3:
    """
    Technical Structure-Based Signal Generator
    
    PRODUCTION ENGINE - Single Pipeline (v3.1)
    
    KEY CHANGES FROM v3.0:
    1. Entry validation with late entry detection
    2. Structural SL based on swing points
    3. Technical TP based on market structure
    4. Dynamic R:R (not fixed 1.33)
    5. Dynamic risk% based on confidence
    6. Asset concentration penalty
    7. All position data properly tracked
    """
    
    # Scoring weights (must sum to 100)
    WEIGHTS = {
        'h1_bias': 14.0,           # H1 directional bias
        'm15_context': 11.0,       # M15 alignment/context
        'mtf_alignment': 10.0,     # Multi-timeframe alignment
        'market_structure': 11.0,  # Market structure quality
        'momentum': 9.0,           # Momentum strength
        'pullback_quality': 10.0,  # Pullback evaluation
        'entry_quality': 6.0,      # NEW: Entry timing quality
        'key_level': 7.0,          # Reaction at key level
        'session': 5.0,            # Session quality
        'rr_ratio': 6.0,           # Risk/Reward (DYNAMIC)
        'volatility': 3.0,         # Volatility conditions
        'regime_quality': 4.0,     # Market regime
        'spread': 2.0,             # Spread penalty
        'concentration': 2.0,      # NEW: Asset concentration penalty
    }
    
    # Hard rejection thresholds
    MAX_SPREAD_PIPS_EURUSD = 3.0
    MAX_SPREAD_PIPS_XAUUSD = 50.0  # Not used - XAUUSD disabled
    ELEVATED_SPREAD_EURUSD = 1.5
    ELEVATED_SPREAD_XAUUSD = 30.0  # Not used - XAUUSD disabled
    MIN_ATR_MULTIPLIER = 0.3
    MAX_DATA_AGE_SECONDS = 60
    
    # Entry validation
    ENTRY_REJECT_ATR_MULTIPLIER = 0.35  # Reject if price > 0.35 ATR from ideal
    
    # R:R thresholds - RAISED based on data (low RR = negative expectancy)
    MIN_RR_HARD_REJECT = 1.1  # Raised from 0.95 - data shows low RR underperforms
    
    # Duplicate suppression (unchanged)
    DUPLICATE_WINDOW_MINUTES = 25
    DUPLICATE_PRICE_ZONE_PIPS = 15
    DUPLICATE_PRICE_ZONE_XAU = 200
    
    # Asset concentration
    CONCENTRATION_WINDOW = 5  # Check last N signals
    CONCENTRATION_THRESHOLD = 4  # Penalty if >= N signals same asset
    
    # ==================== DATA-DRIVEN FILTERS (v3.2) ====================
    # Based on 100-trade performance analysis
    
    # MINIMUM SCORE - Raised from 60 to 75
    # Data: Score 60-70 = -10.73R, Score 75+ = +7.63R
    MIN_CONFIDENCE_SCORE = 75
    
    # MTF ALIGNMENT - Only strong alignment allowed
    # Data: Strong MTF (>=80) = +6.91R, Weak MTF (<80) = -18.36R
    MIN_MTF_SCORE = 80
    
    # ALLOWED ASSETS - EURUSD ONLY
    # Data: EURUSD = +0.63R, XAUUSD = -12.08R
    ALLOWED_ASSETS = [Asset.EURUSD]
    
    # ALLOWED SESSIONS - London ONLY
    # Data: London = +7.25R, Overlap = -16.70R, NY = -2.00R
    ALLOWED_SESSIONS = ["London"]
    
    # ALLOWED SETUP TYPES - Only profitable setups
    # Data: HTF Continuation = +8.29R, Momentum Breakout = +2.98R
    # DISABLED: Fib Retracement = -10.34R, Structure Pullback = -4R, Technical Setup = -9R
    ALLOWED_SETUP_PATTERNS = ["HTF Continuation", "Momentum Breakout", "HTF Trend Continuation"]
    
    def __init__(self, db):
        self.db = db
        self.is_running = False
        self.scan_interval = 5
        self.scanner_task: Optional[asyncio.Task] = None
        
        # Recent signals tracking
        self.recent_signals: List[RecentSignal] = []
        
        # Position Sizing Engine
        self.position_sizer = PositionSizingEngine()
        
        # Statistics
        self.scan_count = 0
        self.signal_count = 0
        self.notification_count = 0
        self.rejection_count = 0
        self.rejection_reasons: Dict[str, int] = {}
        self.invalid_tokens_removed = 0
        self.start_time: Optional[datetime] = None
        
        # Load persisted state
        self._load_state()
        
        logger.info("🚀 Signal Generator v3.2 initialized (DATA-DRIVEN OPTIMIZATION)")
        logger.info(f"   Prop Config: ${PROP_CONFIG.account_size:,.0f} account, ${PROP_CONFIG.max_daily_loss:,.0f} max daily loss")
        logger.info(f"   Dynamic Risk Range: {PROP_CONFIG.min_risk_percent}% - {PROP_CONFIG.max_risk_percent}%")
        logger.info(f"   Min SL: EURUSD={ASSET_CONFIGS[Asset.EURUSD].min_sl_pips}p")
        logger.info(f"   R:R Hard Reject: < {self.MIN_RR_HARD_REJECT}")
        logger.info(f"   ========== DATA-DRIVEN FILTERS (v3.2) ==========")
        logger.info(f"   Min confidence: {self.MIN_CONFIDENCE_SCORE}% (raised from 60%)")
        logger.info(f"   Min MTF score: {self.MIN_MTF_SCORE} (only strong alignment)")
        logger.info(f"   Allowed assets: {[a.value for a in self.ALLOWED_ASSETS]}")
        logger.info(f"   Allowed sessions: {self.ALLOWED_SESSIONS}")
        logger.info(f"   Allowed setups: {self.ALLOWED_SETUP_PATTERNS}")
        logger.info(f"   DISABLED: XAUUSD, Fib Retracement, Structure Pullback")
        logger.info(f"   =================================================")
        logger.info(f"   TRADE MANAGEMENT: Partial TP@0.5R, BE@1R, Trailing@1R")
    
    # ==================== STATE PERSISTENCE ====================
    
    def _load_state(self):
        """Load persisted state from file"""
        try:
            if STATE_FILE.exists():
                with open(STATE_FILE, 'r') as f:
                    state = json.load(f)
                
                self.scan_count = state.get("scan_count", 0)
                self.signal_count = state.get("signal_count", 0)
                self.notification_count = state.get("notification_count", 0)
                self.rejection_count = state.get("rejection_count", 0)
                self.rejection_reasons = state.get("rejection_reasons", {})
                self.invalid_tokens_removed = state.get("invalid_tokens_removed", 0)
                
                # Restore daily risk tracking - only if same day
                daily_risk = state.get("daily_risk_used", 0)
                last_reset = state.get("last_reset_date")
                today = datetime.utcnow().date()
                
                logger.info(f"📂 State file: daily_risk={daily_risk}, last_reset={last_reset}, today={today}")
                
                if last_reset:
                    try:
                        saved_date = datetime.fromisoformat(last_reset).date()
                        if saved_date == today:
                            self.position_sizer.daily_risk_used = daily_risk
                            self.position_sizer.last_reset_date = saved_date
                            logger.info(f"📂 Same day - keeping daily risk: ${daily_risk:.2f}")
                        else:
                            # New day - reset risk
                            self.position_sizer.daily_risk_used = 0.0
                            self.position_sizer.last_reset_date = today
                            logger.info(f"📅 New trading day ({saved_date} -> {today}) - daily risk RESET to $0")
                    except Exception as e:
                        logger.warning(f"📂 Could not parse reset date: {e}")
                        self.position_sizer.daily_risk_used = 0.0
                else:
                    self.position_sizer.daily_risk_used = 0.0
                    logger.info("📂 No last_reset_date - setting daily risk to $0")
                
                logger.info(f"📂 Loaded state: {self.scan_count} scans, {self.signal_count} signals, {self.rejection_count} rejections")
                logger.info(f"📂 Final daily risk: ${self.position_sizer.daily_risk_used:.2f}")
        except Exception as e:
            logger.warning(f"Could not load state: {e}")
    
    def _save_state(self):
        """Persist state to file"""
        try:
            STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
            
            state = {
                "scan_count": self.scan_count,
                "signal_count": self.signal_count,
                "notification_count": self.notification_count,
                "rejection_count": self.rejection_count,
                "rejection_reasons": self.rejection_reasons,
                "invalid_tokens_removed": self.invalid_tokens_removed,
                "daily_risk_used": self.position_sizer.daily_risk_used,
                "last_reset_date": self.position_sizer.last_reset_date.isoformat(),
                "last_save": datetime.utcnow().isoformat()
            }
            
            with open(STATE_FILE, 'w') as f:
                json.dump(state, f, indent=2)
        except Exception as e:
            logger.warning(f"Could not save state: {e}")
    
    def _record_rejection(self, reason: str):
        """Record rejection reason for analytics"""
        self.rejection_count += 1
        self.rejection_reasons[reason] = self.rejection_reasons.get(reason, 0) + 1
    
    def _record_rejected_candidate_for_simulation(
        self,
        reason: str,
        asset: Asset,
        direction: str,
        entry_price: float,
        stop_loss: float,
        take_profit: float,
        confidence_score: float,
        mtf_score: float,
        session: str,
        setup_type: str,
        risk_reward: float = 0,
        rejection_details: str = "",
        fta_distance: float = None,
        clean_space: float = None,
        fta_level: float = None,
        score_breakdown: Dict = None
    ):
        """
        Record a rejected candidate for outcome simulation.
        
        This is AUDIT/ANALYSIS ONLY - does not affect rejection decision.
        The candidate is saved and will be simulated in background to determine
        what would have happened if the trade had been taken.
        """
        try:
            from services.rejected_trade_tracker import rejected_trade_tracker
            
            rejected_trade_tracker.record_rejected_candidate(
                asset=asset.value,
                direction=direction,
                entry_price=entry_price,
                stop_loss=stop_loss,
                take_profit=take_profit,
                confidence_score=confidence_score,
                mtf_score=mtf_score,
                session=session,
                setup_type=setup_type,
                rejection_reason=reason,
                rejection_details=rejection_details,
                risk_reward=risk_reward,
                fta_distance=fta_distance,
                clean_space=clean_space,
                fta_level=fta_level,
                score_breakdown=score_breakdown
            )
        except Exception as e:
            logger.debug(f"Error recording rejected candidate: {e}")
    
    def _record_rejection_with_audit(
        self, 
        reason: str, 
        asset: Asset, 
        direction: str, 
        score: float = 0.0,
        penalties: Dict = None,
        context: DirectionContext = None
    ):
        """Record rejection with full directional audit"""
        # Standard rejection tracking
        self._record_rejection(reason)
        
        # Direction quality audit
        direction_quality_audit.record_rejection(
            symbol=asset.value,
            intended_direction=direction,
            rejection_reason=reason,
            score_before_reject=score,
            active_penalties=penalties or {},
            direction_context=context
        )
    
    # ==================== LIFECYCLE ====================
    
    async def start(self):
        """Start the generator"""
        if self.is_running:
            return
        
        self.is_running = True
        self.start_time = datetime.utcnow()
        
        logger.info("=" * 60)
        logger.info("🚀 SIGNAL GENERATOR V3.2 STARTED (DATA-DRIVEN)")
        logger.info("   Mode: High-quality, low-frequency signals")
        logger.info("   R:R: DYNAMIC (min 1.1)")
        logger.info("   Risk%: DYNAMIC based on confidence")
        logger.info(f"   Min confidence: {self.MIN_CONFIDENCE_SCORE}%")
        logger.info(f"   Min MTF: {self.MIN_MTF_SCORE}")
        logger.info(f"   Assets: {[a.value for a in self.ALLOWED_ASSETS]}")
        logger.info(f"   Sessions: {self.ALLOWED_SESSIONS}")
        logger.info(f"   Scan interval: {self.scan_interval}s")
        logger.info(f"   Prop: ${PROP_CONFIG.account_size:,.0f} | Max Daily: ${PROP_CONFIG.max_daily_loss:,.0f}")
        logger.info("   MANAGEMENT: Partial@0.5R | BE@1R | Trail@1R")
        logger.info("=" * 60)
        
        self.scanner_task = asyncio.create_task(self._run_loop())
    
    async def stop(self):
        """Stop the generator"""
        self.is_running = False
        if self.scanner_task:
            self.scanner_task.cancel()
            try:
                await self.scanner_task
            except asyncio.CancelledError:
                pass
        
        self._save_state()
        logger.info("🛑 Signal Generator v3.1 stopped")
    
    async def _run_loop(self):
        """Main loop"""
        while self.is_running:
            try:
                await self._scan_all_assets()
                
                # Periodic state save
                if self.scan_count % 20 == 0:
                    self._save_state()
                    
            except Exception as e:
                logger.error(f"Generator error: {e}", exc_info=True)
            
            await asyncio.sleep(self.scan_interval)
    
    # ==================== MAIN SCAN PIPELINE ====================
    
    async def _scan_all_assets(self):
        """Scan all assets - DATA-DRIVEN FILTERS APPLIED"""
        from services.production_control import production_control, EngineType
        
        self.scan_count += 1
        
        # Production control check
        authorized, reason = production_control.authorize_scan(EngineType.SIGNAL_GENERATOR_V3)
        if not authorized:
            if self.scan_count % 60 == 0:
                logger.info(f"🛡️ [PRODUCTION] Scan blocked: {reason}")
            return
        
        # Market validation
        if not market_validator.is_forex_open():
            if self.scan_count % 60 == 0:
                status = market_validator.get_market_status_summary()
                logger.info(f"🌙 [MARKET] Forex closed ({status['day_of_week']} {status['hour_utc']}:00 UTC)")
            return
        
        # ========== SESSION FILTER (DATA-DRIVEN) ==========
        current_session = self._get_session_name(session_detector.get_current_session())
        if current_session not in self.ALLOWED_SESSIONS:
            if self.scan_count % 60 == 0:
                logger.info(f"🚫 [SESSION FILTER] {current_session} not in {self.ALLOWED_SESSIONS} - skipping")
            return
        
        # ========== ASSET FILTER (DATA-DRIVEN) ==========
        # Only scan allowed assets (EURUSD only based on data)
        for asset in self.ALLOWED_ASSETS:
            price_data = market_data_cache.get_price(asset)
            m5_candles = market_data_cache.get_candles(asset, Timeframe.M5)
            m15_candles = market_data_cache.get_candles(asset, Timeframe.M15)
            h1_candles = market_data_cache.get_candles(asset, Timeframe.H1)
            
            validation_result = market_validator.validate_for_signal_generation(
                asset=asset,
                price_data=price_data,
                candles_m5=m5_candles,
                candles_m15=m15_candles,
                candles_h1=h1_candles
            )
            
            if not validation_result.is_valid:
                continue
            
            # News risk detection
            news_risk = await self._detect_news_risk(asset)
            
            # Main analysis
            signal = await self._analyze_asset(asset, news_risk)
            
            if signal:
                await self._process_signal(signal)
    
    # ==================== NEWS RISK DETECTION ====================
    
    async def _detect_news_risk(self, asset: Asset) -> NewsRiskInfo:
        """
        Detect news risk with UPDATED penalties
        
        HIGH events:
        - <= 15 min: -12 points
        - 15-30 min: -8 points
        - 30-60 min: -4 points
        
        MEDIUM events:
        - <= 15 min: -6 points
        - 15-30 min: -3 points
        """
        try:
            from services.macro_news_service import macro_news_service
            
            news_info = await macro_news_service.check_news_risk(asset, minutes_window=60)
            
            if news_info.get("has_risk", False):
                minutes_to_event = news_info.get("minutes_to_event", 999)
                event_name = news_info.get("event_name", "Economic Event")
                impact = news_info.get("impact", "MEDIUM")
                
                # Determine penalty based on impact and proximity
                if impact == "HIGH":
                    if minutes_to_event <= 15:
                        level = NewsRiskLevel.HIGH
                        penalty = 12.0
                        warning = f"⚠️ {event_name} in {minutes_to_event}m"
                    elif minutes_to_event <= 30:
                        level = NewsRiskLevel.HIGH
                        penalty = 8.0
                        warning = f"⚠️ {event_name} in {minutes_to_event}m"
                    else:
                        level = NewsRiskLevel.MEDIUM
                        penalty = 4.0
                        warning = f"{event_name} in {minutes_to_event}m"
                else:  # MEDIUM impact
                    if minutes_to_event <= 15:
                        level = NewsRiskLevel.MEDIUM
                        penalty = 6.0
                        warning = f"{event_name} in {minutes_to_event}m"
                    elif minutes_to_event <= 30:
                        level = NewsRiskLevel.LOW
                        penalty = 3.0
                        warning = f"{event_name} in {minutes_to_event}m"
                    else:
                        level = NewsRiskLevel.LOW
                        penalty = 0.0
                        warning = None
                
                return NewsRiskInfo(
                    level=level,
                    event_name=event_name,
                    minutes_until=minutes_to_event,
                    score_penalty=penalty,
                    warning=warning
                )
        except Exception as e:
            logger.debug(f"News risk check: {e}")
        
        return NewsRiskInfo(level=NewsRiskLevel.NONE)
    
    # ==================== STRUCTURAL ANALYSIS ====================
    
    def _find_swing_low(self, candles: List, lookback: int = 20) -> Optional[float]:
        """Find most recent significant swing low"""
        if len(candles) < lookback:
            return None
        
        recent = candles[-lookback:]
        lows = [c.get('low', 0) for c in recent]
        
        # Find swing lows (local minima)
        swing_lows = []
        for i in range(2, len(lows) - 2):
            if (lows[i] < lows[i-1] and lows[i] < lows[i-2] and 
                lows[i] < lows[i+1] and lows[i] < lows[i+2]):
                swing_lows.append(lows[i])
        
        if swing_lows:
            return swing_lows[-1]  # Most recent swing low
        
        # Fallback: lowest low in recent period
        return min(lows[-10:]) if len(lows) >= 10 else min(lows)
    
    def _find_swing_high(self, candles: List, lookback: int = 20) -> Optional[float]:
        """Find most recent significant swing high"""
        if len(candles) < lookback:
            return None
        
        recent = candles[-lookback:]
        highs = [c.get('high', 0) for c in recent]
        
        # Find swing highs (local maxima)
        swing_highs = []
        for i in range(2, len(highs) - 2):
            if (highs[i] > highs[i-1] and highs[i] > highs[i-2] and 
                highs[i] > highs[i+1] and highs[i] > highs[i+2]):
                swing_highs.append(highs[i])
        
        if swing_highs:
            return swing_highs[-1]  # Most recent swing high
        
        # Fallback: highest high in recent period
        return max(highs[-10:]) if len(highs) >= 10 else max(highs)
    
    def _find_next_resistance(self, candles: List, current_price: float, lookback: int = 50) -> Optional[float]:
        """Find next resistance level above current price"""
        if len(candles) < lookback:
            return None
        
        recent = candles[-lookback:]
        highs = [c.get('high', 0) for c in recent]
        
        # Find swing highs above current price
        resistances = []
        for i in range(2, len(highs) - 2):
            if (highs[i] > highs[i-1] and highs[i] > highs[i-2] and 
                highs[i] > highs[i+1] and highs[i] > highs[i+2]):
                if highs[i] > current_price:
                    resistances.append(highs[i])
        
        if resistances:
            return min(resistances)  # Nearest resistance
        
        # Fallback: recent high
        recent_high = max(highs[-20:])
        return recent_high if recent_high > current_price else None
    
    def _find_next_support(self, candles: List, current_price: float, lookback: int = 50) -> Optional[float]:
        """Find next support level below current price"""
        if len(candles) < lookback:
            return None
        
        recent = candles[-lookback:]
        lows = [c.get('low', 0) for c in recent]
        
        # Find swing lows below current price
        supports = []
        for i in range(2, len(lows) - 2):
            if (lows[i] < lows[i-1] and lows[i] < lows[i-2] and 
                lows[i] < lows[i+1] and lows[i] < lows[i+2]):
                if lows[i] < current_price:
                    supports.append(lows[i])
        
        if supports:
            return max(supports)  # Nearest support
        
        # Fallback: recent low
        recent_low = min(lows[-20:])
        return recent_low if recent_low < current_price else None
    
    def _calculate_structural_levels(
        self, 
        asset: Asset,
        direction: str, 
        entry_price: float,
        m5_candles: List,
        m15_candles: List,
        atr: float
    ) -> StructuralLevels:
        """
        Calculate SL and TP based on market structure
        
        SL: Based on swing point + buffer
        TP: Based on next structural target - buffer
        """
        asset_config = ASSET_CONFIGS.get(asset, ASSET_CONFIGS[Asset.EURUSD])
        levels = StructuralLevels()
        
        # ========== STOP LOSS CALCULATION ==========
        if direction == "BUY":
            # Find swing low for BUY SL
            swing_low_m5 = self._find_swing_low(m5_candles, 20)
            swing_low_m15 = self._find_swing_low(m15_candles, 15) if m15_candles else None
            
            # Use M5 swing, confirmed by M15 if available
            if swing_low_m5:
                if swing_low_m15 and swing_low_m15 < swing_low_m5:
                    base_sl = swing_low_m15
                else:
                    base_sl = swing_low_m5
                
                # Add buffer
                buffer = max(atr * 0.25, asset_config.min_buffer_pips * asset_config.pip_size)
                levels.swing_sl = base_sl - buffer
                levels.swing_sl_type = "swing_low"
            else:
                # ATR fallback
                levels.swing_sl = entry_price - (atr * 1.8)
                levels.swing_sl_type = "atr_fallback"
        else:  # SELL
            # Find swing high for SELL SL
            swing_high_m5 = self._find_swing_high(m5_candles, 20)
            swing_high_m15 = self._find_swing_high(m15_candles, 15) if m15_candles else None
            
            if swing_high_m5:
                if swing_high_m15 and swing_high_m15 > swing_high_m5:
                    base_sl = swing_high_m15
                else:
                    base_sl = swing_high_m5
                
                buffer = max(atr * 0.25, asset_config.min_buffer_pips * asset_config.pip_size)
                levels.swing_sl = base_sl + buffer
                levels.swing_sl_type = "swing_high"
            else:
                levels.swing_sl = entry_price + (atr * 1.8)
                levels.swing_sl_type = "atr_fallback"
        
        # Enforce minimum SL distance
        sl_distance_pips = abs(entry_price - levels.swing_sl) / asset_config.pip_size
        if sl_distance_pips < asset_config.min_sl_pips:
            # Expand SL to minimum
            min_sl_distance = asset_config.min_sl_pips * asset_config.pip_size
            if direction == "BUY":
                levels.swing_sl = entry_price - min_sl_distance
            else:
                levels.swing_sl = entry_price + min_sl_distance
            levels.swing_sl_type += "_expanded"
        
        # ========== TAKE PROFIT CALCULATION ==========
        if direction == "BUY":
            # Find resistance for TP
            resistance = self._find_next_resistance(m5_candles, entry_price, 50)
            risk_distance = abs(entry_price - levels.swing_sl)
            
            if resistance and resistance > entry_price:
                # Place TP before resistance with buffer
                tp_buffer = asset_config.tp_buffer_pips * asset_config.pip_size
                potential_tp = resistance - tp_buffer
                potential_reward = potential_tp - entry_price
                potential_rr = potential_reward / risk_distance if risk_distance > 0 else 0
                
                # Only use structural TP if it gives acceptable R:R
                if potential_rr >= 1.1:
                    levels.structural_tp1 = potential_tp
                    levels.tp_type = "swing_target"
                    tp1_distance = levels.structural_tp1 - entry_price
                    levels.structural_tp2 = entry_price + (tp1_distance * 1.5)
                else:
                    # Extension fallback for better R:R
                    levels.structural_tp1 = entry_price + (risk_distance * 1.5)
                    levels.structural_tp2 = entry_price + (risk_distance * 2.2)
                    levels.tp_type = "extension_rr"
            else:
                # No resistance found - use R:R based TP
                levels.structural_tp1 = entry_price + (risk_distance * 1.5)
                levels.structural_tp2 = entry_price + (risk_distance * 2.2)
                levels.tp_type = "extension_rr"
        else:  # SELL
            support = self._find_next_support(m5_candles, entry_price, 50)
            risk_distance = abs(entry_price - levels.swing_sl)
            
            if support and support < entry_price:
                tp_buffer = asset_config.tp_buffer_pips * asset_config.pip_size
                potential_tp = support + tp_buffer
                potential_reward = entry_price - potential_tp
                potential_rr = potential_reward / risk_distance if risk_distance > 0 else 0
                
                if potential_rr >= 1.1:
                    levels.structural_tp1 = potential_tp
                    levels.tp_type = "swing_target"
                    tp1_distance = entry_price - levels.structural_tp1
                    levels.structural_tp2 = entry_price - (tp1_distance * 1.5)
                else:
                    levels.structural_tp1 = entry_price - (risk_distance * 1.5)
                    levels.structural_tp2 = entry_price - (risk_distance * 2.2)
                    levels.tp_type = "extension_rr"
            else:
                levels.structural_tp1 = entry_price - (risk_distance * 1.5)
                levels.structural_tp2 = entry_price - (risk_distance * 2.2)
                levels.tp_type = "extension_rr"
        
        return levels
    
    # ==================== FIRST TROUBLE AREA (FTA) DETECTION ====================
    
    def _find_all_obstacles(
        self,
        candles_m5: List,
        candles_m15: List,
        entry_price: float,
        target_price: float,
        direction: str
    ) -> List[Tuple[float, str]]:
        """
        Find all technical obstacles between entry and target.
        
        Returns: List of (price, type) tuples
        """
        obstacles = []
        
        # Determine price range to scan
        if direction == "BUY":
            # Looking for resistances between entry and target (above entry)
            price_min = entry_price
            price_max = target_price
        else:
            # Looking for supports between entry and target (below entry)
            price_min = target_price
            price_max = entry_price
        
        # 1. Find swing highs/lows from M5
        if len(candles_m5) >= 20:
            recent_m5 = candles_m5[-50:] if len(candles_m5) >= 50 else candles_m5
            
            for i in range(2, len(recent_m5) - 2):
                high = recent_m5[i].get('high', 0)
                low = recent_m5[i].get('low', 0)
                
                if direction == "BUY":
                    # Look for swing highs (resistances)
                    if (high > recent_m5[i-1].get('high', 0) and 
                        high > recent_m5[i-2].get('high', 0) and
                        high > recent_m5[i+1].get('high', 0) and 
                        high > recent_m5[i+2].get('high', 0)):
                        if price_min < high < price_max:
                            obstacles.append((high, "swing_high"))
                else:
                    # Look for swing lows (supports)
                    if (low < recent_m5[i-1].get('low', float('inf')) and 
                        low < recent_m5[i-2].get('low', float('inf')) and
                        low < recent_m5[i+1].get('low', float('inf')) and 
                        low < recent_m5[i+2].get('low', float('inf'))):
                        if price_min < low < price_max:
                            obstacles.append((low, "swing_low"))
        
        # 2. Find significant wicks (rejections)
        if len(candles_m5) >= 10:
            for c in candles_m5[-20:]:
                body = abs(c.get('close', 0) - c.get('open', 0))
                high = c.get('high', 0)
                low = c.get('low', 0)
                close = c.get('close', 0)
                open_p = c.get('open', 0)
                
                wick_up = high - max(close, open_p)
                wick_down = min(close, open_p) - low
                
                if direction == "BUY":
                    # Large upper wick = rejection from above = resistance
                    if wick_up > body * 2.0 and body > 0:
                        rejection_level = high - (wick_up * 0.3)  # Zone start
                        if price_min < rejection_level < price_max:
                            obstacles.append((rejection_level, "wick_rejection"))
                else:
                    # Large lower wick = rejection from below = support
                    if wick_down > body * 2.0 and body > 0:
                        rejection_level = low + (wick_down * 0.3)
                        if price_min < rejection_level < price_max:
                            obstacles.append((rejection_level, "wick_rejection"))
        
        # 3. Confirm obstacles with M15
        if candles_m15 and len(candles_m15) >= 10:
            for i in range(2, min(len(candles_m15) - 2, 15)):
                high = candles_m15[-(i+1)].get('high', 0)
                low = candles_m15[-(i+1)].get('low', 0)
                
                if direction == "BUY":
                    if (high > candles_m15[-(i)].get('high', 0) and 
                        high > candles_m15[-(i+2)].get('high', 0)):
                        if price_min < high < price_max:
                            obstacles.append((high, "local_resistance"))
                else:
                    if (low < candles_m15[-(i)].get('low', float('inf')) and 
                        low < candles_m15[-(i+2)].get('low', float('inf'))):
                        if price_min < low < price_max:
                            obstacles.append((low, "local_support"))
        
        # 4. Detect congestion zones (multiple candles at similar price)
        if len(candles_m5) >= 15:
            recent = candles_m5[-15:]
            closes = [c.get('close', 0) for c in recent]
            avg_close = sum(closes) / len(closes) if closes else 0
            
            # Check if there's a congestion area in our path
            if price_min < avg_close < price_max:
                # Count how many candles closed near this level
                threshold = abs(target_price - entry_price) * 0.1
                near_count = sum(1 for c in closes if abs(c - avg_close) < threshold)
                if near_count >= 5:
                    obstacles.append((avg_close, "congestion_zone"))
        
        return obstacles
    
    def _calculate_fta(
        self,
        candles_m5: List,
        candles_m15: List,
        entry_price: float,
        target_price: float,
        direction: str,
        tp_type: str
    ) -> FirstTroubleArea:
        """
        Calculate First Trouble Area (FTA)
        
        Identifies the first technical obstacle between entry and target,
        calculates clean_space_ratio and determines penalties.
        
        Returns: FirstTroubleArea dataclass with all FTA metrics
        """
        fta = FirstTroubleArea()
        
        # Calculate target distance
        fta.target_distance = abs(target_price - entry_price)
        
        if fta.target_distance == 0:
            return fta
        
        # Find all obstacles
        obstacles = self._find_all_obstacles(
            candles_m5, candles_m15, entry_price, target_price, direction
        )
        
        if not obstacles:
            # No obstacles found - clean path
            fta.clean_space_ratio = 1.0
            fta.fta_type = "none"
            return fta
        
        # Sort obstacles by distance from entry
        if direction == "BUY":
            # For BUY, closest obstacle is the one with lowest price above entry
            obstacles_sorted = sorted(obstacles, key=lambda x: x[0])
        else:
            # For SELL, closest obstacle is the one with highest price below entry
            obstacles_sorted = sorted(obstacles, key=lambda x: -x[0])
        
        # Get the first (closest) obstacle
        first_obstacle_price, first_obstacle_type = obstacles_sorted[0]
        
        fta.fta_price = first_obstacle_price
        fta.fta_type = first_obstacle_type
        fta.fta_distance = abs(first_obstacle_price - entry_price)
        fta.clean_space_ratio = fta.fta_distance / fta.target_distance if fta.target_distance > 0 else 1.0
        
        # Count obstacles within 60% of target
        sixty_percent_distance = fta.target_distance * 0.60
        if direction == "BUY":
            obstacles_in_60 = sum(1 for p, t in obstacles if p - entry_price <= sixty_percent_distance)
        else:
            obstacles_in_60 = sum(1 for p, t in obstacles if entry_price - p <= sixty_percent_distance)
        fta.obstacles_count = obstacles_in_60
        
        # ========== FTA SOFT FILTER (v4) ==========
        # NEW LOGIC: FTA is now a SOFT FILTER, NOT a hard blocker
        # FTA affects score but does NOT block trades (except extreme cases)
        # 
        # TARGET: 
        # - Acceptance rate 3-8% (was ~1%)
        # - FTA should NOT be 100% of rejections
        # - Hard block ONLY if FTA distance < 0.5R
        
        # Calculate FTA distance in R (Risk units)
        risk = abs(target_price - entry_price) / max(1, fta.target_distance) if fta.target_distance > 0 else 0
        fta_distance_in_r = fta.fta_distance / abs(target_price - entry_price) if abs(target_price - entry_price) > 0 else 0
        
        # FTA Quality Classification
        if fta.clean_space_ratio >= 0.65:
            fta.fta_quality = "clean"
            fta.fta_penalty = -5  # BONUS for clean space
        elif fta.clean_space_ratio >= 0.35:
            fta.fta_quality = "moderate"
            fta.fta_penalty = 0  # Neutral
        else:
            fta.fta_quality = "weak"
            fta.fta_penalty = 5  # Small penalty (NOT blocking)
        
        # Hard block ONLY if FTA is extremely close (< 0.5R from entry)
        # This is the ONLY case where FTA blocks
        if fta_distance_in_r < 0.5 and fta.clean_space_ratio < 0.20:
            fta.fta_blocked_trade = True
            fta.fta_penalty = 15  # Max penalty
        else:
            fta.fta_blocked_trade = False
        
        # Special case: if FTA nearly coincides with target (>90%), bonus
        if fta.clean_space_ratio >= 0.90:
            fta.fta_penalty = -5  # Bonus
            fta.fta_quality = "clean"
        
        # Special case: M15 confirmed swing target - reduce concern
        if tp_type == "swing_target" and fta.clean_space_ratio >= 0.25:
            fta.fta_penalty = min(0, fta.fta_penalty - 2)
        
        # Store for logging
        fta.fta_distance_in_r = fta_distance_in_r
        
        return fta
    
    def _evaluate_fta_contextual(
        self,
        fta: FirstTroubleArea,
        mtf_score: float,
        mtf_reason: str,
        pullback_score: float,
        pullback_reason: str,
        h1_score: float,
        news_risk_level: str,
        preliminary_score: float
    ) -> Tuple[bool, bool, str]:
        """
        FTA SOFT FILTER EVALUATION (v4)
        
        NEW APPROACH:
        - FTA is primarily a SCORE MODIFIER, not a blocker
        - Hard block ONLY if FTA distance < 0.5R (extremely close)
        - Otherwise, apply score penalty/bonus and let confidence threshold decide
        
        Returns:
            Tuple[should_block, override_applied, reason]
        """
        ratio = fta.clean_space_ratio
        fta_distance_r = getattr(fta, 'fta_distance_in_r', 1.0)
        
        # ========== HARD BLOCK: ONLY if FTA < 0.5R ==========
        if fta.fta_blocked_trade and fta_distance_r < 0.5:
            block_reason = f"hard_block: FTA distance {fta_distance_r:.2f}R < 0.5R (too close)"
            return True, False, block_reason
        
        # ========== SOFT FILTER: All other cases pass with score adjustment ==========
        # FTA penalty is already applied to score, let confidence threshold filter
        
        # Log FTA quality for analysis
        if ratio >= 0.65:
            reason = f"fta_clean: ratio={ratio:.2f}, +5 score bonus"
        elif ratio >= 0.35:
            reason = f"fta_moderate: ratio={ratio:.2f}, neutral"
        else:
            reason = f"fta_weak: ratio={ratio:.2f}, -5 score penalty (soft)"
        
        # Never block - let score threshold decide
        return False, False, reason
    
    # ==================== ENTRY VALIDATION ====================
    
    def _validate_entry(
        self, 
        asset: Asset,
        direction: str, 
        current_price: float, 
        atr: float
    ) -> Tuple[bool, float, str, float, float]:
        """
        Validate entry quality - detect late entries
        
        Returns: (is_valid, score, reason, entry_zone_low, entry_zone_high)
        """
        # Define ideal entry zone
        if direction == "BUY":
            ideal_center = current_price
            entry_zone_low = ideal_center - (atr * 0.20)
            entry_zone_high = ideal_center + (atr * 0.10)
        else:  # SELL
            ideal_center = current_price
            entry_zone_low = ideal_center - (atr * 0.10)
            entry_zone_high = ideal_center + (atr * 0.20)
        
        zone_center = (entry_zone_low + entry_zone_high) / 2
        distance_from_center = abs(current_price - zone_center)
        distance_in_atr = distance_from_center / atr if atr > 0 else 0
        
        # Scoring based on entry position
        if distance_in_atr <= 0.10:
            score = 100
            reason = "Optimal entry zone"
        elif distance_in_atr <= 0.20:
            score = 80
            reason = "Good entry zone"
        elif distance_in_atr <= 0.30:
            score = 60
            reason = "Acceptable entry"
        elif distance_in_atr <= self.ENTRY_REJECT_ATR_MULTIPLIER:
            score = 40
            reason = "Late entry - penalized"
        else:
            # Reject - too late
            return False, 0, f"REJECT: Entry too late ({distance_in_atr:.2f} ATR from zone)", entry_zone_low, entry_zone_high
        
        return True, score, reason, entry_zone_low, entry_zone_high
    
    # ==================== ASSET CONCENTRATION ====================
    
    def _check_asset_concentration(self, asset: Asset) -> Tuple[float, str]:
        """
        Check if there's over-concentration on one asset
        
        Returns: (score, reason)
        """
        if len(self.recent_signals) < self.CONCENTRATION_WINDOW:
            return 100, "No concentration issue"
        
        # Count recent signals by asset
        recent = self.recent_signals[-self.CONCENTRATION_WINDOW:]
        same_asset_count = sum(1 for s in recent if s.asset == asset)
        
        if same_asset_count >= self.CONCENTRATION_THRESHOLD:
            penalty_score = 50
            return penalty_score, f"Concentration penalty: {same_asset_count}/{self.CONCENTRATION_WINDOW} signals on {asset.value}"
        elif same_asset_count >= self.CONCENTRATION_THRESHOLD - 1:
            return 75, f"Moderate concentration: {same_asset_count} recent {asset.value}"
        else:
            return 100, "No concentration issue"
    
    # ==================== MAIN ANALYSIS ====================
    
    async def _analyze_asset(self, asset: Asset, news_risk: NewsRiskInfo) -> Optional[GeneratedSignal]:
        """
        Analyze an asset with structural SL/TP
        """
        asset_config = ASSET_CONFIGS.get(asset, ASSET_CONFIGS[Asset.EURUSD])
        
        # ========== HARD REJECTION CHECKS ==========
        
        if market_data_cache.is_stale(asset):
            return None
        
        h1_candles = market_data_cache.get_candles(asset, Timeframe.H1)
        m15_candles = market_data_cache.get_candles(asset, Timeframe.M15)
        m5_candles = market_data_cache.get_candles(asset, Timeframe.M5)
        
        if not h1_candles or not m15_candles or not m5_candles:
            return None
        
        if len(m5_candles) < 50:
            return None
        
        price_data = market_data_cache.get_price(asset)
        if not price_data:
            return None
        
        max_spread = self.MAX_SPREAD_PIPS_EURUSD if asset == Asset.EURUSD else self.MAX_SPREAD_PIPS_XAUUSD
        current_spread = price_data.spread_pips
        
        if current_spread > max_spread:
            return None
        
        atr = self._calculate_atr(m5_candles, 14)
        if atr == 0:
            return None
        
        avg_atr = self._calculate_average_atr(m5_candles, 50)
        if avg_atr > 0 and atr < avg_atr * self.MIN_ATR_MULTIPLIER:
            return None
        
        # ========== DIRECTION ANALYSIS ==========
        
        current_price = price_data.mid
        session = session_detector.get_current_session()
        session_name = self._get_session_name(session)
        
        direction, direction_score, direction_reason = self._analyze_direction_advanced(
            h1_candles, m15_candles, m5_candles
        )
        
        if not direction:
            direction = self._fallback_direction(m5_candles)
            if not direction:
                return None
        
        # ========== ENTRY VALIDATION ==========
        
        entry_valid, entry_score, entry_reason, entry_zone_low, entry_zone_high = self._validate_entry(
            asset, direction, current_price, atr
        )
        
        if not entry_valid:
            self._record_rejection("late_entry")
            logger.info(f"⏭️ {asset.value} {direction}: {entry_reason}")
            return None
        
        entry_price = current_price
        
        # ========== STRUCTURAL SL/TP CALCULATION ==========
        
        structural_levels = self._calculate_structural_levels(
            asset, direction, entry_price, m5_candles, m15_candles, atr
        )
        
        stop_loss = structural_levels.swing_sl
        take_profit_1 = structural_levels.structural_tp1
        take_profit_2 = structural_levels.structural_tp2
        sl_type = structural_levels.swing_sl_type
        tp_type = structural_levels.tp_type
        
        # ========== DYNAMIC R:R CALCULATION ==========
        
        risk = abs(entry_price - stop_loss)
        reward = abs(take_profit_1 - entry_price)
        rr_ratio = reward / risk if risk > 0 else 0
        
        # Hard reject if R:R too low
        if rr_ratio < self.MIN_RR_HARD_REJECT:
            self._record_rejection("low_rr")
            logger.info(f"⏭️ {asset.value} {direction}: R:R {rr_ratio:.2f} < {self.MIN_RR_HARD_REJECT} (REJECT)")
            return None
        
        # ========== FIRST TROUBLE AREA (FTA) ANALYSIS ==========
        
        fta = self._calculate_fta(
            m5_candles, m15_candles, entry_price, take_profit_1, direction, tp_type
        )
        
        # NOTE: FTA auto-block has been REMOVED (v2 recalibration)
        # FTA blocking is now CONTEXTUAL - decided after scoring
        # This allows high-quality setups to override low FTA ratios
        
        # ========== SCORING ==========
        
        components = []
        
        # 1. H1 Bias
        h1_score, h1_reason = self._score_h1_bias(h1_candles, direction)
        components.append(ScoreComponent("H1 Directional Bias", self.WEIGHTS['h1_bias'], h1_score, h1_reason))
        
        # 2. M15 Context
        m15_score, m15_reason = self._score_m15_context(m15_candles, direction)
        components.append(ScoreComponent("M15 Context", self.WEIGHTS['m15_context'], m15_score, m15_reason))
        
        # 3. MTF Alignment
        mtf_score, mtf_reason = self._score_mtf_alignment(h1_candles, m15_candles, m5_candles, direction)
        components.append(ScoreComponent("MTF Alignment", self.WEIGHTS['mtf_alignment'], mtf_score, mtf_reason))
        
        # 4. Market Structure
        struct_score, struct_reason = self._score_market_structure(m5_candles, direction)
        components.append(ScoreComponent("Market Structure", self.WEIGHTS['market_structure'], struct_score, struct_reason))
        
        # 5. Momentum
        mom_score, mom_reason = self._score_momentum(m5_candles, direction)
        components.append(ScoreComponent("Momentum", self.WEIGHTS['momentum'], mom_score, mom_reason))
        
        # 6. Pullback Quality
        pb_score, pb_reason = self._score_pullback_advanced(m5_candles, direction, current_price, atr)
        components.append(ScoreComponent("Pullback Quality", self.WEIGHTS['pullback_quality'], pb_score, pb_reason))
        
        # 7. Entry Quality (NEW)
        components.append(ScoreComponent("Entry Quality", self.WEIGHTS['entry_quality'], entry_score, entry_reason))
        
        # 8. Key Level
        kl_score, kl_reason = self._score_key_level(m5_candles, current_price, direction)
        components.append(ScoreComponent("Key Level Reaction", self.WEIGHTS['key_level'], kl_score, kl_reason))
        
        # 9. Session
        sess_score, sess_reason = self._score_session_soft(session)
        components.append(ScoreComponent("Session Quality", self.WEIGHTS['session'], sess_score, sess_reason))
        
        # 10. R:R Score (DYNAMIC)
        rr_score, rr_reason = self._score_rr_ratio_dynamic(rr_ratio)
        components.append(ScoreComponent("Risk/Reward", self.WEIGHTS['rr_ratio'], rr_score, rr_reason))
        
        # 11. Volatility
        vol_score, vol_reason = self._score_volatility(atr, avg_atr)
        components.append(ScoreComponent("Volatility", self.WEIGHTS['volatility'], vol_score, vol_reason))
        
        # 12. Market Regime
        regime_score, regime_reason = self._score_market_regime(m5_candles, atr, avg_atr)
        components.append(ScoreComponent("Market Regime", self.WEIGHTS['regime_quality'], regime_score, regime_reason))
        
        # 13. Spread
        spread_score, spread_reason = self._score_spread(asset, current_spread)
        components.append(ScoreComponent("Spread", self.WEIGHTS['spread'], spread_score, spread_reason))
        
        # 14. Concentration (NEW)
        conc_score, conc_reason = self._check_asset_concentration(asset)
        components.append(ScoreComponent("Concentration", self.WEIGHTS['concentration'], conc_score, conc_reason))
        
        # Calculate final score
        final_score = sum(c.weighted_score for c in components)
        
        # Store preliminary score BEFORE penalties for FTA contextual evaluation
        preliminary_score = final_score
        
        # ========== CONTEXTUAL FTA EVALUATION (v2 RECALIBRATION) ==========
        # Now we have all quality metrics - evaluate FTA in context
        
        # Get quality scores for context evaluation
        mtf_component = next((c for c in components if "MTF" in c.name), None)
        pullback_component = next((c for c in components if "Pullback" in c.name), None)
        h1_component = next((c for c in components if "H1" in c.name), None)
        
        mtf_score_val = mtf_component.score if mtf_component else 50
        mtf_reason_val = mtf_component.reason if mtf_component else "unknown"
        pullback_score_val = pullback_component.score if pullback_component else 50
        pullback_reason_val = pullback_component.reason if pullback_component else "unknown"
        h1_score_val = h1_component.score if h1_component else 50
        
        # Evaluate FTA contextually
        should_block_fta, fta_override_applied, fta_decision_reason = self._evaluate_fta_contextual(
            fta=fta,
            mtf_score=mtf_score_val,
            mtf_reason=mtf_reason_val,
            pullback_score=pullback_score_val,
            pullback_reason=pullback_reason_val,
            h1_score=h1_score_val,
            news_risk_level=news_risk.level.value,
            preliminary_score=preliminary_score
        )
        
        # Log FTA decision
        if fta.clean_space_ratio < 0.50:
            fta_price_str = f"{fta.fta_price:.5f}" if asset == Asset.EURUSD else f"{fta.fta_price:.2f}"
            if should_block_fta:
                # ========== FTA CONTEXTUAL BLOCK ==========
                logger.info(f"⛔ {asset.value} {direction}: FTA BLOCKED (CONTEXTUAL)")
                logger.info(f"   ratio={fta.clean_space_ratio:.2f}, FTA={fta.fta_type} @ {fta_price_str}")
                logger.info(f"   Decision: {fta_decision_reason}")
                logger.info(f"   prelim_score={preliminary_score:.0f}, mtf={mtf_score_val:.0f}, pb={pullback_score_val:.0f}")
                
                # Record rejection with full context
                reject_context = DirectionContext(
                    fta_quality="blocked_contextual",
                    fta_clean_space_ratio=fta.clean_space_ratio,
                    session=session_name,
                    final_direction_reason=direction_reason,
                    final_direction_score=direction_score
                )
                
                self._record_rejection_with_audit(
                    reason="fta_blocked",
                    asset=asset,
                    direction=direction,
                    score=preliminary_score,
                    penalties={"fta_blocked": True, "clean_space_ratio": fta.clean_space_ratio, "decision": fta_decision_reason},
                    context=reject_context
                )
                
                # Record for Missed Opportunity Analysis
                missed_opportunity_analyzer.record_rejection(
                    symbol=asset.value,
                    direction=direction,
                    rejection_reason="fta_blocked_contextual",
                    score_before_reject=preliminary_score,
                    entry_price=entry_price,
                    stop_loss=stop_loss,
                    take_profit=take_profit_1,
                    risk_reward=rr_ratio,
                    fta_price=fta.fta_price,
                    fta_type=fta.fta_type,
                    fta_distance=fta.fta_distance,
                    clean_space_ratio=fta.clean_space_ratio,
                    context={
                        "h1_bias": direction_reason,
                        "h1_bias_score": direction_score,
                        "session": session_name,
                        "preliminary_score": preliminary_score,
                        "mtf_score": mtf_score_val,
                        "pullback_score": pullback_score_val,
                        "fta_penalty": fta.fta_penalty,
                        "fta_decision": fta_decision_reason
                    }
                )
                
                # Record for Rejected Trade Outcome Simulation
                self._record_rejected_candidate_for_simulation(
                    reason="fta_blocked",
                    asset=asset,
                    direction=direction,
                    entry_price=entry_price,
                    stop_loss=stop_loss,
                    take_profit=take_profit_1,
                    confidence_score=preliminary_score,
                    mtf_score=mtf_score_val,
                    session=session_name,
                    setup_type="FTA_BLOCKED",
                    risk_reward=rr_ratio,
                    rejection_details=f"FTA {fta.fta_type} @ {fta_price_str}, ratio={fta.clean_space_ratio:.2f}",
                    fta_distance=fta.fta_distance,
                    clean_space=fta.clean_space_ratio,
                    fta_level=fta.fta_price,
                    score_breakdown={
                        "preliminary_score": preliminary_score,
                        "mtf_score": mtf_score_val,
                        "pullback_score": pullback_score_val,
                        "fta_penalty": fta.fta_penalty
                    }
                )
                
                logger.info(f"   📊 Recorded for Missed Opportunity Analysis")
                return None
            else:
                # FTA OVERRIDE - high quality setup passes with penalty
                logger.info(f"🔓 {asset.value} {direction}: FTA OVERRIDE APPLIED")
                logger.info(f"   ratio={fta.clean_space_ratio:.2f}, FTA={fta.fta_type} @ {fta_price_str}")
                logger.info(f"   Override: {fta_decision_reason}")
        
        # Apply FTA penalty (reduced weight in v2)
        if fta.fta_penalty > 0:
            final_score -= fta.fta_penalty
            logger.info(f"📊 {asset.value}: FTA penalty applied (-{fta.fta_penalty:.0f}): {fta.fta_type} @ ratio {fta.clean_space_ratio:.2f}")
        
        # Apply news penalty
        if news_risk.score_penalty > 0:
            final_score -= news_risk.score_penalty
            logger.info(f"📰 {asset.value}: News penalty applied (-{news_risk.score_penalty:.1f}): {news_risk.event_name}")
        
        # Apply warning level penalty
        if self.position_sizer.daily_risk_used >= self.position_sizer.config.operational_warning:
            final_score -= 3
        
        final_score = max(0, min(100, final_score))
        
        # ========== MTF ALIGNMENT FILTER (DATA-DRIVEN) ==========
        # Data: Strong MTF (>=80) = +6.91R, Weak MTF (<80) = -18.36R
        if mtf_score_val < self.MIN_MTF_SCORE:
            self._record_rejection("weak_mtf")
            logger.info(f"🚫 {asset.value} {direction}: MTF score {mtf_score_val:.0f}% < {self.MIN_MTF_SCORE}% (DATA-DRIVEN FILTER)")
            self._log_score_breakdown(asset, direction, components, final_score)
            
            # Record for simulation
            self._record_rejected_candidate_for_simulation(
                reason="weak_mtf",
                asset=asset,
                direction=direction,
                entry_price=entry_price,
                stop_loss=stop_loss,
                take_profit=take_profit_1,
                confidence_score=final_score,
                mtf_score=mtf_score_val,
                session=session_name,
                setup_type=self._determine_setup_type(components, sl_type, tp_type),
                risk_reward=rr_ratio,
                rejection_details=f"MTF {mtf_score_val:.0f}% < {self.MIN_MTF_SCORE}%",
                score_breakdown={"components": [{"name": c.name, "score": c.score} for c in components]}
            )
            return None
        
        # ========== CONFIDENCE CLASSIFICATION (v3.2 - DATA-DRIVEN) ==========
        # Raised threshold from 60 to 75 based on performance data
        if final_score >= 80:
            confidence = SignalConfidence.STRONG
            priority = "HIGH"
        elif final_score >= self.MIN_CONFIDENCE_SCORE:  # 75
            confidence = SignalConfidence.GOOD
            priority = "NORMAL"
        else:
            confidence = SignalConfidence.REJECTED
            self._record_rejection("low_confidence")
            logger.info(f"📉 {asset.value} {direction}: Score {final_score:.0f}% < {self.MIN_CONFIDENCE_SCORE}% - Rejected (DATA-DRIVEN)")
            self._log_score_breakdown(asset, direction, components, final_score)
            
            # Record for simulation
            self._record_rejected_candidate_for_simulation(
                reason="low_confidence",
                asset=asset,
                direction=direction,
                entry_price=entry_price,
                stop_loss=stop_loss,
                take_profit=take_profit_1,
                confidence_score=final_score,
                mtf_score=mtf_score_val,
                session=session_name,
                setup_type=self._determine_setup_type(components, sl_type, tp_type),
                risk_reward=rr_ratio,
                rejection_details=f"Score {final_score:.0f}% < {self.MIN_CONFIDENCE_SCORE}%",
                score_breakdown={"components": [{"name": c.name, "score": c.score} for c in components]}
            )
            return None
        
        # Duplicate check
        if self._is_duplicate(asset, direction, current_price):
            self._record_rejection("duplicate")
            return None
        
        # ========== POSITION SIZING (with confidence-based risk) ==========
        
        position = self.position_sizer.calculate(
            asset=asset,
            entry_price=entry_price,
            stop_loss=stop_loss,
            confidence_score=final_score
        )
        
        # Check if daily limit allows trade
        if position.recommended_lot_size == 0:
            self._record_rejection("daily_limit")
            logger.info(f"⛔ {asset.value} {direction}: Daily risk limit exhausted")
            return None
        
        # ========== GENERATE SIGNAL ==========
        
        signal_id = f"{asset.value}_{direction}_{datetime.utcnow().strftime('%Y%m%d_%H%M%S')}"
        setup_type = self._determine_setup_type(components, sl_type, tp_type)
        
        # ========== SETUP TYPE FILTER (DATA-DRIVEN) ==========
        # Only allow profitable setup types
        if not self._is_allowed_setup(setup_type):
            self._record_rejection("unprofitable_setup")
            logger.info(f"🚫 {asset.value} {direction}: Setup '{setup_type}' not in allowed list (DATA-DRIVEN)")
            logger.info(f"   Allowed: {self.ALLOWED_SETUP_PATTERNS}")
            self._log_score_breakdown(asset, direction, components, final_score)
            
            # Record for simulation
            self._record_rejected_candidate_for_simulation(
                reason="unprofitable_setup",
                asset=asset,
                direction=direction,
                entry_price=entry_price,
                stop_loss=stop_loss,
                take_profit=take_profit_1,
                confidence_score=final_score,
                mtf_score=mtf_score_val,
                session=session_name,
                setup_type=setup_type,
                risk_reward=rr_ratio,
                rejection_details=f"Setup '{setup_type}' not in {self.ALLOWED_SETUP_PATTERNS}",
                score_breakdown={"components": [{"name": c.name, "score": c.score} for c in components]}
            )
            return None
        
        sl_formatted = f"{stop_loss:.5f}" if asset == Asset.EURUSD else f"{stop_loss:.2f}"
        invalidation = f"{'Below' if direction == 'BUY' else 'Above'} {sl_formatted}"
        
        score_obj = SignalScore(
            components=components,
            final_score=final_score,
            confidence=confidence
        )
        
        signal = GeneratedSignal(
            signal_id=signal_id,
            asset=asset,
            direction=direction,
            entry_price=entry_price,
            entry_zone_low=entry_zone_low,
            entry_zone_high=entry_zone_high,
            stop_loss=stop_loss,
            take_profit_1=take_profit_1,
            take_profit_2=take_profit_2,
            risk_reward=round(rr_ratio, 2),
            confidence_score=final_score,
            confidence_level=confidence,
            setup_type=setup_type,
            invalidation=invalidation,
            session=session_name,
            score_breakdown=score_obj,
            timestamp=datetime.utcnow(),
            # Position sizing (ALL FIELDS POPULATED)
            recommended_lot_size=position.recommended_lot_size,
            money_at_risk=position.money_at_risk,
            risk_percent=position.risk_percent,
            pip_risk=position.pip_risk,
            position_adjusted=position.adjusted,
            position_adjustment_reason=position.adjustment_reason,
            prop_warnings=position.prop_warnings,
            daily_risk_used=position.daily_risk_used,
            daily_risk_remaining=position.daily_risk_remaining,
            # Structure info
            sl_type=sl_type,
            tp_type=tp_type,
            # News risk
            news_risk=news_risk.level,
            news_event=news_risk.event_name,
            news_warning=news_risk.warning,
            # Spread
            spread_pips=current_spread,
            # First Trouble Area (FTA)
            fta_price=fta.fta_price,
            fta_type=fta.fta_type,
            fta_distance=fta.fta_distance,
            target_distance=fta.target_distance,
            clean_space_ratio=fta.clean_space_ratio,
            fta_penalty=fta.fta_penalty,
            fta_blocked_trade=fta.fta_blocked_trade,
            fta_obstacles_count=fta.obstacles_count
        )
        
        # ========== DIRECTION QUALITY AUDIT ==========
        
        # Build DirectionContext for audit
        direction_context = DirectionContext(
            # H1 bias
            h1_bias="bullish" if h1_score > 60 else "bearish" if h1_score < 40 else "neutral",
            h1_bias_score=h1_score,
            # M15 bias
            m15_bias="bullish" if m15_score > 60 else "bearish" if m15_score < 40 else "neutral",
            m15_bias_score=m15_score,
            # M5 momentum
            m5_momentum="bullish" if mom_score > 60 else "bearish" if mom_score < 40 else "neutral",
            m5_momentum_score=mom_score,
            # Structure
            market_structure="bullish" if struct_score > 60 else "bearish" if struct_score < 40 else "unclear",
            market_structure_score=struct_score,
            # Pullback
            pullback_quality="excellent" if pb_score > 80 else "good" if pb_score > 60 else "acceptable" if pb_score > 40 else "weak",
            pullback_quality_score=pb_score,
            # Entry
            entry_quality="optimal" if entry_score > 80 else "good" if entry_score > 60 else "acceptable" if entry_score > 40 else "late",
            entry_quality_score=entry_score,
            # FTA
            fta_quality="clean" if fta.clean_space_ratio >= 0.80 else "moderate" if fta.clean_space_ratio >= 0.65 else "weak",
            fta_clean_space_ratio=fta.clean_space_ratio,
            # MTF alignment
            mtf_alignment="full" if mtf_score > 80 else "partial" if mtf_score > 60 else "weak" if mtf_score > 40 else "conflicting",
            mtf_alignment_score=mtf_score,
            # Session
            session=session_name,
            session_score=sess_score,
            # External factors
            news_risk=news_risk.level.value,
            news_penalty=news_risk.score_penalty,
            spread_penalty=100 - spread_score,
            fta_penalty=fta.fta_penalty,
            concentration_penalty=100 - conc_score,
            # Direction reason
            final_direction_reason=direction_reason,
            final_direction_score=direction_score
        )
        
        # Determine regime for audit
        regime = "trending" if regime_score > 70 else "ranging" if regime_score < 40 else "mixed"
        
        # Determine MTF alignment quality
        mtf_alignment_quality = "full" if mtf_score > 80 else "partial" if mtf_score > 60 else "weak" if mtf_score > 40 else "conflicting"
        
        # Determine FTA quality
        fta_quality_str = "clean" if fta.clean_space_ratio >= 0.80 else "moderate" if fta.clean_space_ratio >= 0.65 else "weak"
        
        # News risk bucket
        news_bucket = news_risk.level.value.lower()
        
        # Record the signal for directional audit
        direction_quality_audit.record_signal(
            signal_id=signal.signal_id,
            symbol=asset.value,
            direction=direction,
            entry_price=entry_price,
            stop_loss=stop_loss,
            take_profit=take_profit_1,
            risk_reward=rr_ratio,
            confidence_score=final_score,
            session=session_name,
            regime=regime,
            direction_context=direction_context,
            mtf_alignment=mtf_alignment_quality,
            news_risk=news_bucket,
            fta_quality=fta_quality_str
        )
        
        return signal
    
    # ==================== SIGNAL PROCESSING ====================
    
    async def _process_signal(self, signal: GeneratedSignal):
        """Process a generated signal"""
        self.signal_count += 1
        
        # Detailed logging
        emoji = "🟢" if signal.direction == "BUY" else "🔴"
        asset_config = ASSET_CONFIGS.get(signal.asset, ASSET_CONFIGS[Asset.EURUSD])
        sl_pips = signal.pip_risk
        tp_pips = abs(signal.take_profit_1 - signal.entry_price) / asset_config.pip_size
        
        logger.info("=" * 60)
        logger.info(f"{emoji} SIGNAL GENERATED: {signal.asset.value} {signal.direction}")
        logger.info(f"   Confidence: {signal.confidence_score:.0f}% ({signal.confidence_level.value})")
        logger.info(f"   Priority: {'HIGH' if signal.confidence_score >= 80 else 'NORMAL'}")
        logger.info(f"   Setup: {signal.setup_type}")
        
        if signal.asset == Asset.EURUSD:
            entry_fmt = f"{signal.entry_price:.5f}"
            sl_fmt = f"{signal.stop_loss:.5f}"
            tp_fmt = f"{signal.take_profit_1:.5f}"
        else:
            entry_fmt = f"{signal.entry_price:.2f}"
            sl_fmt = f"{signal.stop_loss:.2f}"
            tp_fmt = f"{signal.take_profit_1:.2f}"
        
        logger.info(f"   Entry: {entry_fmt}")
        logger.info(f"   Stop Loss: {sl_fmt} ({sl_pips:.1f} pips) [{signal.sl_type}]")
        logger.info(f"   Take Profit: {tp_fmt} ({tp_pips:.1f} pips) [{signal.tp_type}]")
        logger.info(f"   R:R: {signal.risk_reward:.2f} (DYNAMIC)")
        logger.info("-" * 40)
        logger.info(f"   POSITION SIZING:")
        logger.info(f"   • Lot Size: {signal.recommended_lot_size:.2f}")
        logger.info(f"   • Money at Risk: ${signal.money_at_risk:.2f}")
        logger.info(f"   • Risk %: {signal.risk_percent:.2f}%")
        logger.info(f"   • Daily Used: ${signal.daily_risk_used:.0f} | Remaining: ${signal.daily_risk_remaining:.0f}")
        if signal.prop_warnings:
            for warn in signal.prop_warnings:
                logger.info(f"   ⚠️ {warn}")
        logger.info("-" * 40)
        if signal.news_risk != NewsRiskLevel.NONE:
            logger.info(f"   NEWS RISK: {signal.news_risk.value} - {signal.news_event}")
        # FTA logging
        if signal.fta_type != "none":
            fta_status = "clean" if signal.clean_space_ratio >= 0.80 else "moderate" if signal.clean_space_ratio >= 0.65 else "obstacle"
            logger.info(f"   FTA: {signal.fta_type} | ratio: {signal.clean_space_ratio:.2f} | penalty: -{signal.fta_penalty:.0f} [{fta_status}]")
        else:
            logger.info(f"   FTA: clean path (no obstacles)")
        logger.info(f"   Session: {signal.session} | Spread: {signal.spread_pips:.1f} pips")
        logger.info("-" * 40)
        logger.info(f"   TRADE MANAGEMENT (v3.2):")
        logger.info(f"   • Partial TP: 50% at +0.5R")
        logger.info(f"   • Move to BE: at +1R")
        logger.info(f"   • Trailing Stop: after +1R")
        logger.info("=" * 60)
        
        # Track for duplicate prevention
        self.recent_signals.append(RecentSignal(
            signal_id=signal.signal_id,
            asset=signal.asset,
            direction=signal.direction,
            price=signal.entry_price,
            timestamp=signal.timestamp
        ))
        
        # Clean old signals
        cutoff = datetime.utcnow() - timedelta(minutes=self.DUPLICATE_WINDOW_MINUTES)
        self.recent_signals = [s for s in self.recent_signals if s.timestamp > cutoff]
        
        # Record trade risk
        self.position_sizer.record_trade(signal.money_at_risk)
        
        # Track outcome
        await self._track_signal_outcome(signal)
        
        # Send notification
        await self._send_notification(signal)
    
    async def _track_signal_outcome(self, signal: GeneratedSignal):
        """Register signal for outcome tracking with ALL fields"""
        try:
            from services.signal_outcome_tracker_v2 import signal_outcome_tracker
            
            tracking_data = {
                'signal_id': signal.signal_id,
                'timestamp': signal.timestamp.isoformat(),
                'asset': signal.asset.value,
                'direction': signal.direction,
                'entry_price': signal.entry_price,
                'stop_loss': signal.stop_loss,
                'take_profit_1': signal.take_profit_1,
                'take_profit_2': signal.take_profit_2,
                'confidence_score': signal.confidence_score,
                'confidence_level': signal.confidence_level.value,
                'setup_type': signal.setup_type,
                'session': signal.session,
                'invalidation': signal.invalidation,
                'risk_reward': signal.risk_reward,
                # Position sizing (FIXED)
                'lot_size': signal.recommended_lot_size,
                'money_at_risk': signal.money_at_risk,
                'risk_percent': signal.risk_percent,
                'pip_risk': signal.pip_risk,
                'daily_risk_used': signal.daily_risk_used,
                'daily_risk_remaining': signal.daily_risk_remaining,
                # Structure
                'sl_type': signal.sl_type,
                'tp_type': signal.tp_type,
                # News
                'news_risk': signal.news_risk.value,
                # First Trouble Area (FTA)
                'fta_price': signal.fta_price,
                'fta_type': signal.fta_type,
                'fta_distance': signal.fta_distance,
                'target_distance': signal.target_distance,
                'clean_space_ratio': signal.clean_space_ratio,
                'fta_penalty': signal.fta_penalty,
                'fta_obstacles_count': signal.fta_obstacles_count,
                # Score breakdown
                'score_breakdown': signal.score_breakdown.to_dict() if signal.score_breakdown else {}
            }
            
            await signal_outcome_tracker.track_signal(tracking_data)
            logger.debug(f"✅ Signal tracked: {signal.signal_id}")
        except Exception as e:
            logger.warning(f"Outcome tracking error: {e}")
    
    async def _send_notification(self, signal: GeneratedSignal):
        """Send push notification"""
        from services.production_control import production_control, EngineType
        
        authorized, reason = production_control.authorize_notification(
            EngineType.SIGNAL_GENERATOR_V3, 
            signal.signal_id
        )
        if not authorized:
            logger.info(f"📵 [PRODUCTION] Notification blocked for {signal.signal_id}: {reason}")
            return
        
        try:
            from services.device_storage_service import device_storage
            from services.fcm_push_service import fcm_push_service
            
            # Initialize FCM service if needed
            if not fcm_push_service._initialized:
                await fcm_push_service.initialize()
            
            tokens = await device_storage.get_active_tokens()
            
            if not tokens:
                logger.warning("📭 No devices registered for notifications")
                return
            
            notif = signal.to_notification_dict()
            
            logger.info(f"📤 Sending notification for {signal.signal_id} via FCM v1")
            
            results = await fcm_push_service.send_to_all_devices(
                tokens=tokens,
                title=notif['title'],
                body=notif['body'],
                data=notif['data']
            )
            
            successful = 0
            for i, result in enumerate(results):
                if result.success:
                    successful += 1
                else:
                    error_str = str(result.error) if result.error else ""
                    if any(err in error_str.lower() for err in ["not registered", "invalid", "unregistered"]):
                        await self._remove_invalid_token(tokens[i])
            
            self.notification_count += 1
            logger.info(f"📤 Notification sent: {successful}/{len(results)} devices")
            
        except Exception as e:
            logger.error(f"❌ Failed to send notification: {e}")
    
    async def _remove_invalid_token(self, token: str):
        """Remove invalid push token"""
        try:
            from services.device_storage_service import device_storage
            await device_storage.deactivate_by_token(token)
            self.invalid_tokens_removed += 1
            logger.info(f"🧹 Removed invalid push token")
        except Exception as e:
            logger.debug(f"Could not remove invalid token: {e}")
    
    # ==================== SCORING METHODS ====================
    
    def _score_rr_ratio_dynamic(self, rr: float) -> Tuple[float, str]:
        """
        Score R:R with NEW dynamic grading
        
        >= 2.0: 100
        1.6-1.99: 85
        1.3-1.59: 70
        1.1-1.29: 50
        0.95-1.09: 25
        < 0.95: rejected earlier
        """
        if rr >= 2.0:
            return 100, f"Excellent R:R ({rr:.2f})"
        elif rr >= 1.6:
            return 85, f"Good R:R ({rr:.2f})"
        elif rr >= 1.3:
            return 70, f"Acceptable R:R ({rr:.2f})"
        elif rr >= 1.1:
            return 50, f"Minimum R:R ({rr:.2f})"
        else:
            return 25, f"Low R:R ({rr:.2f})"
    
    def _analyze_direction_advanced(self, h1: List, m15: List, m5: List) -> Tuple[Optional[str], float, str]:
        """Advanced direction analysis"""
        h1_trend = self._get_trend(h1[-20:]) if len(h1) >= 20 else 0
        m15_trend = self._get_trend(m15[-20:]) if len(m15) >= 20 else 0
        m5_momentum = self._get_momentum(m5[-10:]) if len(m5) >= 10 else 0
        
        total = h1_trend * 0.5 + m15_trend * 0.3 + m5_momentum * 0.2
        
        if total > 0.2:
            return "BUY", total * 100, "Bullish bias across timeframes"
        elif total < -0.2:
            return "SELL", abs(total) * 100, "Bearish bias across timeframes"
        elif abs(m5_momentum) > 0.4:
            direction = "BUY" if m5_momentum > 0 else "SELL"
            return direction, 50, "M5 momentum breakout"
        
        return None, 0, "No clear direction"
    
    def _fallback_direction(self, m5: List) -> Optional[str]:
        """Fallback direction from M5"""
        if len(m5) < 5:
            return None
        
        closes = [c.get('close', 0) for c in m5[-5:]]
        if closes[-1] > closes[0] * 1.0003:
            return "BUY"
        elif closes[-1] < closes[0] * 0.9997:
            return "SELL"
        return None
    
    def _score_mtf_alignment(self, h1: List, m15: List, m5: List, direction: str) -> Tuple[float, str]:
        """Score MTF alignment"""
        h1_trend = self._get_trend(h1[-15:]) if len(h1) >= 15 else 0
        m15_trend = self._get_trend(m15[-15:]) if len(m15) >= 15 else 0
        m5_trend = self._get_trend(m5[-15:]) if len(m5) >= 15 else 0
        
        is_buy = direction == "BUY"
        h1_aligned = (h1_trend > 0) == is_buy
        m15_aligned = (m15_trend > 0) == is_buy
        m5_aligned = (m5_trend > 0) == is_buy
        
        aligned_count = sum([h1_aligned, m15_aligned, m5_aligned])
        
        if aligned_count == 3:
            return 100, "All timeframes aligned"
        elif aligned_count == 2:
            if h1_aligned and m15_aligned:
                return 80, "H1 + M15 aligned"
            return 65, "Partial alignment"
        elif aligned_count == 1:
            return 40, "Weak alignment"
        return 20, "Conflicting timeframes"
    
    def _score_pullback_advanced(self, m5: List, direction: str, current_price: float, atr: float) -> Tuple[float, str]:
        """Score pullback quality"""
        if len(m5) < 20:
            return 50, "Insufficient data"
        
        highs = [c.get('high', 0) for c in m5[-20:]]
        lows = [c.get('low', 0) for c in m5[-20:]]
        recent_high = max(highs)
        recent_low = min(lows)
        swing_range = recent_high - recent_low
        
        if swing_range == 0:
            return 50, "No swing range"
        
        if direction == "BUY":
            from_high = (recent_high - current_price) / swing_range
            if 0.382 <= from_high <= 0.618:
                base_score = 95
                reason = "Excellent Fib pullback (38-62%)"
            elif 0.25 <= from_high <= 0.75:
                base_score = 75
                reason = "Good pullback zone"
            elif from_high < 0.25:
                base_score = 45
                reason = "Shallow pullback"
            else:
                base_score = 35
                reason = "Deep pullback"
        else:
            from_low = (current_price - recent_low) / swing_range
            if 0.382 <= from_low <= 0.618:
                base_score = 95
                reason = "Excellent Fib pullback (38-62%)"
            elif 0.25 <= from_low <= 0.75:
                base_score = 75
                reason = "Good pullback zone"
            elif from_low < 0.25:
                base_score = 45
                reason = "Shallow pullback"
            else:
                base_score = 35
                reason = "Deep pullback"
        
        last_3 = m5[-3:]
        if direction == "BUY":
            resuming = last_3[-1].get('close', 0) > last_3[0].get('open', 0)
        else:
            resuming = last_3[-1].get('close', 0) < last_3[0].get('open', 0)
        
        if resuming:
            base_score = min(100, base_score + 8)
            reason += " + resuming"
        
        return base_score, reason
    
    def _score_session_soft(self, session) -> Tuple[float, str]:
        """Score session quality"""
        hour = datetime.utcnow().hour
        
        if 13 <= hour <= 16:
            return 100, "London/NY overlap"
        elif 7 <= hour <= 12:
            return 90, "London session"
        elif 13 <= hour <= 20:
            return 85, "NY session"
        elif 21 <= hour <= 23 or 0 <= hour <= 2:
            return 55, "Transition hours"
        elif 3 <= hour <= 6:
            return 40, "Asian session"
        return 45, "Off-peak hours"
    
    def _score_spread(self, asset: Asset, spread_pips: float) -> Tuple[float, str]:
        """Score spread"""
        if asset == Asset.EURUSD:
            if spread_pips <= 0.8:
                return 100, f"Tight spread ({spread_pips:.1f}p)"
            elif spread_pips <= 1.2:
                return 85, f"Normal spread ({spread_pips:.1f}p)"
            elif spread_pips <= self.ELEVATED_SPREAD_EURUSD:
                return 70, f"Acceptable ({spread_pips:.1f}p)"
            return 40, f"Elevated ({spread_pips:.1f}p)"
        else:
            if spread_pips <= 20:
                return 100, f"Tight spread ({spread_pips:.1f}p)"
            elif spread_pips <= self.ELEVATED_SPREAD_XAUUSD:
                return 75, f"Normal spread ({spread_pips:.1f}p)"
            return 50, f"Elevated ({spread_pips:.1f}p)"
    
    def _get_trend(self, candles: List) -> float:
        """Get trend direction (-1 to 1)"""
        if len(candles) < 5:
            return 0
        closes = [c.get('close', 0) for c in candles]
        first_avg = sum(closes[:5]) / 5
        last_avg = sum(closes[-5:]) / 5
        if first_avg == 0:
            return 0
        change = (last_avg - first_avg) / first_avg
        return max(-1, min(1, change * 100))
    
    def _get_momentum(self, candles: List) -> float:
        """Get momentum (-1 to 1)"""
        if len(candles) < 3:
            return 0
        opens = [c.get('open', 0) for c in candles]
        closes = [c.get('close', 0) for c in candles]
        bullish = sum(1 for o, c in zip(opens, closes) if c > o)
        return (bullish - (len(candles) - bullish)) / len(candles)
    
    def _score_h1_bias(self, h1: List, direction: str) -> Tuple[float, str]:
        """Score H1 bias"""
        if len(h1) < 10:
            return 50, "Insufficient H1 data"
        trend = self._get_trend(h1[-10:])
        if direction == "BUY":
            if trend > 0.5:
                return 100, "Strong H1 bullish"
            elif trend > 0.2:
                return 75, "Moderate H1 bullish"
            elif trend > 0:
                return 60, "Weak H1 bullish"
            elif trend > -0.2:
                return 40, "H1 neutral"
            return 25, "H1 bearish"
        else:
            if trend < -0.5:
                return 100, "Strong H1 bearish"
            elif trend < -0.2:
                return 75, "Moderate H1 bearish"
            elif trend < 0:
                return 60, "Weak H1 bearish"
            elif trend < 0.2:
                return 40, "H1 neutral"
            return 25, "H1 bullish"
    
    def _score_m15_context(self, m15: List, direction: str) -> Tuple[float, str]:
        """Score M15 context"""
        if len(m15) < 8:
            return 50, "Insufficient M15 data"
        trend = self._get_trend(m15[-8:])
        momentum = self._get_momentum(m15[-4:])
        aligned = (direction == "BUY" and trend > 0) or (direction == "SELL" and trend < 0)
        mom_aligned = (direction == "BUY" and momentum > 0) or (direction == "SELL" and momentum < 0)
        if aligned and mom_aligned:
            return 90, "M15 trend + momentum aligned"
        elif aligned:
            return 70, "M15 trend aligned"
        elif mom_aligned:
            return 55, "M15 momentum aligned"
        return 35, "M15 not aligned"
    
    def _score_market_structure(self, m5: List, direction: str) -> Tuple[float, str]:
        """Score market structure"""
        if len(m5) < 20:
            return 50, "Insufficient data"
        highs = [c.get('high', 0) for c in m5[-20:]]
        lows = [c.get('low', 0) for c in m5[-20:]]
        swing_highs = self._find_swing_points_list(highs, 'high')
        swing_lows = self._find_swing_points_list(lows, 'low')
        
        if direction == "BUY":
            if len(swing_lows) >= 2 and swing_lows[-1] > swing_lows[-2]:
                return 85, "Higher lows"
            elif len(swing_lows) >= 2:
                return 65, "Equal lows"
            return 45, "No clear structure"
        else:
            if len(swing_highs) >= 2 and swing_highs[-1] < swing_highs[-2]:
                return 85, "Lower highs"
            elif len(swing_highs) >= 2:
                return 65, "Equal highs"
            return 45, "No clear structure"
    
    def _find_swing_points_list(self, data: List, point_type: str) -> List:
        """Find swing points"""
        if len(data) < 5:
            return []
        swings = []
        for i in range(2, len(data) - 2):
            if point_type == 'high':
                if data[i] > data[i-1] and data[i] > data[i-2] and data[i] > data[i+1] and data[i] > data[i+2]:
                    swings.append(data[i])
            else:
                if data[i] < data[i-1] and data[i] < data[i-2] and data[i] < data[i+1] and data[i] < data[i+2]:
                    swings.append(data[i])
        return swings[-3:] if len(swings) > 3 else swings
    
    def _score_momentum(self, m5: List, direction: str) -> Tuple[float, str]:
        """Score momentum"""
        if len(m5) < 5:
            return 50, "Insufficient data"
        momentum = self._get_momentum(m5[-5:])
        if direction == "BUY":
            if momentum > 0.6:
                return 95, "Strong bullish momentum"
            elif momentum > 0.3:
                return 75, "Moderate bullish"
            elif momentum > 0:
                return 55, "Weak bullish"
            return 30, "Bearish momentum"
        else:
            if momentum < -0.6:
                return 95, "Strong bearish momentum"
            elif momentum < -0.3:
                return 75, "Moderate bearish"
            elif momentum < 0:
                return 55, "Weak bearish"
            return 30, "Bullish momentum"
    
    def _score_key_level(self, m5: List, current_price: float, direction: str) -> Tuple[float, str]:
        """Score key level reaction"""
        if len(m5) < 20:
            return 50, "Insufficient data"
        round_level_distance = current_price % (0.001 if current_price < 10 else 1)
        near_round = round_level_distance < 0.0003 or round_level_distance > 0.0007
        recent = m5[-3:]
        has_rejection = False
        for c in recent:
            body = abs(c.get('close', 0) - c.get('open', 0))
            wick_up = c.get('high', 0) - max(c.get('close', 0), c.get('open', 0))
            wick_down = min(c.get('close', 0), c.get('open', 0)) - c.get('low', 0)
            if direction == "BUY" and wick_down > body * 1.5:
                has_rejection = True
            elif direction == "SELL" and wick_up > body * 1.5:
                has_rejection = True
        if has_rejection and near_round:
            return 95, "Rejection at round number"
        elif has_rejection:
            return 75, "Price rejection"
        elif near_round:
            return 60, "Near round number"
        return 45, "No key level"
    
    def _score_volatility(self, atr: float, avg_atr: float) -> Tuple[float, str]:
        """Score volatility"""
        if avg_atr == 0:
            return 50, "No ATR reference"
        ratio = atr / avg_atr
        if 0.8 <= ratio <= 1.5:
            return 90, "Normal volatility"
        elif 0.5 <= ratio <= 2:
            return 70, "Acceptable volatility"
        elif ratio > 2:
            return 40, "High volatility"
        return 40, "Low volatility"
    
    def _score_market_regime(self, m5: List, atr: float, avg_atr: float) -> Tuple[float, str]:
        """Score market regime"""
        if len(m5) < 20:
            return 50, "Insufficient data"
        atr_ratio = atr / avg_atr if avg_atr > 0 else 1.0
        recent_candles = m5[-10:]
        ranges = [c.get('high', 0) - c.get('low', 0) for c in recent_candles]
        avg_range = sum(ranges) / len(ranges) if ranges else 0
        
        closes = [c.get('close', 0) for c in recent_candles]
        if len(closes) >= 5:
            first_half = sum(closes[:5]) / 5
            second_half = sum(closes[5:]) / 5
            directional_move = abs(second_half - first_half) / avg_range if avg_range > 0 else 0
        else:
            directional_move = 0.5
        
        if atr_ratio >= 1.2 and directional_move > 1.5:
            return 95, "Strong trending"
        elif atr_ratio >= 0.9 and directional_move > 1.0:
            return 85, "Healthy trend"
        elif atr_ratio >= 0.7:
            return 70, "Normal regime"
        elif atr_ratio >= 0.5:
            return 50, "Mixed regime"
        return 40, "Low activity"
    
    def _calculate_atr(self, candles: List, period: int) -> float:
        """Calculate ATR"""
        if len(candles) < period:
            return 0
        trs = []
        for i in range(1, min(period + 1, len(candles))):
            c = candles[-i]
            prev = candles[-i-1] if i < len(candles) else c
            high = c.get('high', 0)
            low = c.get('low', 0)
            prev_close = prev.get('close', 0)
            tr = max(high - low, abs(high - prev_close), abs(low - prev_close))
            trs.append(tr)
        return sum(trs) / len(trs) if trs else 0
    
    def _calculate_average_atr(self, candles: List, period: int) -> float:
        """Calculate average ATR"""
        return self._calculate_atr(candles, period)
    
    def _is_duplicate(self, asset: Asset, direction: str, price: float) -> bool:
        """Check duplicate"""
        cutoff = datetime.utcnow() - timedelta(minutes=self.DUPLICATE_WINDOW_MINUTES)
        price_zone = self.DUPLICATE_PRICE_ZONE_PIPS if asset == Asset.EURUSD else self.DUPLICATE_PRICE_ZONE_XAU
        pip_size = ASSET_CONFIGS[asset].pip_size
        zone_distance = price_zone * pip_size
        
        for recent in self.recent_signals:
            if recent.timestamp < cutoff:
                continue
            if recent.asset != asset:
                continue
            if recent.direction != direction:
                continue
            if abs(recent.price - price) < zone_distance:
                return True
        return False
    
    def _determine_setup_type(self, components: List[ScoreComponent], sl_type: str, tp_type: str) -> str:
        """
        Determine setup type - DATA-DRIVEN FILTER (v3.2)
        
        ALLOWED (positive expectancy):
        - HTF Continuation: +8.29R (MTF>80, struct>70)
        - Momentum Breakout: +2.98R (momentum-based)
        - HTF Trend Continuation: +8.29R (alias)
        
        DISABLED (negative expectancy):
        - Fib Retracement: -10.34R (pb>80 without strong MTF/struct)
        - Structure Pullback: -4.00R (struct>80, pb>70 but no MTF)
        - Technical Setup: -9.02R (generic fallback)
        """
        struct_score = next((c.score for c in components if c.name == "Market Structure"), 0)
        pb_score = next((c.score for c in components if c.name == "Pullback Quality"), 0)
        mtf_score = next((c.score for c in components if c.name == "MTF Alignment"), 0)
        mom_score = next((c.score for c in components if c.name == "Momentum"), 0)
        
        # PRIORITY 1: HTF Continuation (BEST performer: +8.29R)
        # Requires: Strong MTF alignment AND good structure
        if mtf_score >= 80 and struct_score >= 70:
            base_type = "HTF Trend Continuation"
        # PRIORITY 2: Momentum Breakout (POSITIVE: +2.98R)
        # Requires: Strong momentum signal with good MTF
        elif mom_score >= 75 and mtf_score >= 80:
            base_type = "Momentum Breakout"
        else:
            # FALLBACK: Still classify but will be filtered by setup check
            # This allows logging what would have been generated
            if struct_score > 80 and pb_score > 70:
                base_type = "Structure Pullback"  # Will be REJECTED
            elif pb_score > 80:
                base_type = "Fib Retracement"  # Will be REJECTED
            else:
                base_type = "Technical Setup"  # Will be REJECTED
        
        # Add structure info
        if sl_type == "swing_low" or sl_type == "swing_high":
            base_type += " [Structural SL]"
        
        return base_type
    
    def _is_allowed_setup(self, setup_type: str) -> bool:
        """
        Check if setup type is in the allowed list (DATA-DRIVEN)
        
        Returns True if setup is profitable based on historical data
        """
        for allowed in self.ALLOWED_SETUP_PATTERNS:
            if allowed in setup_type:
                return True
        return False
    
    def _get_session_name(self, session) -> str:
        """Get session name"""
        hour = datetime.utcnow().hour
        if 13 <= hour <= 16:
            return "London/NY Overlap"
        elif 7 <= hour <= 12:
            return "London"
        elif 13 <= hour <= 20:
            return "New York"
        elif 0 <= hour <= 7:
            return "Asian"
        return "Off-Hours"
    
    def _log_score_breakdown(self, asset: Asset, direction: str, components: List[ScoreComponent], final_score: float):
        """Log score breakdown"""
        logger.info(f"   Score breakdown for {asset.value} {direction}:")
        for c in components:
            logger.info(f"   • {c.name}: {c.score:.0f}% × {c.weight}% = {c.weighted_score:.1f}")
        logger.info(f"   TOTAL: {final_score:.1f}%")
    
    # ==================== STATUS & STATS ====================
    
    def get_stats(self) -> Dict:
        """Get generator statistics"""
        uptime = (datetime.utcnow() - self.start_time).total_seconds() if self.start_time else 0
        
        return {
            "is_running": self.is_running,
            "version": "v3.2 (DATA-DRIVEN)",
            "mode": "high_quality_low_frequency",
            "uptime_seconds": uptime,
            "scan_count": self.scan_count,
            "signal_count": self.signal_count,
            "notification_count": self.notification_count,
            "rejection_count": self.rejection_count,
            "rejection_reasons": self.rejection_reasons,
            "invalid_tokens_removed": self.invalid_tokens_removed,
            "recent_signals": len(self.recent_signals),
            "duplicate_window_minutes": self.DUPLICATE_WINDOW_MINUTES,
            # v3.2 DATA-DRIVEN configuration
            "data_driven_filters": {
                "min_confidence": self.MIN_CONFIDENCE_SCORE,
                "min_mtf_score": self.MIN_MTF_SCORE,
                "allowed_assets": [a.value for a in self.ALLOWED_ASSETS],
                "allowed_sessions": self.ALLOWED_SESSIONS,
                "allowed_setups": self.ALLOWED_SETUP_PATTERNS,
                "min_rr": self.MIN_RR_HARD_REJECT
            },
            "trade_management": {
                "partial_tp": "50% at 0.5R",
                "breakeven": "at 1R",
                "trailing_stop": "after 1R"
            },
            "classification": {
                "strong": "80-100 (0.75% risk, HIGH priority)",
                "good": "75-79 (0.65% risk, NORMAL priority)",
                "rejected": "<75 (DATA-DRIVEN FILTER)"
            },
            "prop_config": {
                "account_size": PROP_CONFIG.account_size,
                "max_daily_loss": PROP_CONFIG.max_daily_loss,
                "operational_warning": PROP_CONFIG.operational_warning,
                "risk_per_trade": f"{PROP_CONFIG.min_risk_percent}% - {PROP_CONFIG.max_risk_percent}% (dynamic)"
            },
            "daily_risk_status": self.position_sizer.get_daily_status(),
            "optimization_applied": "2026-03-18 based on 100-trade analysis"
        }


# Global instance
signal_generator_v3: Optional[SignalGeneratorV3] = None

async def init_signal_generator(db) -> SignalGeneratorV3:
    """Initialize the signal generator"""
    global signal_generator_v3
    signal_generator_v3 = SignalGeneratorV3(db)
    return signal_generator_v3
