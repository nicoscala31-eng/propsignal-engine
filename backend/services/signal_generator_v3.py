"""
# Signal Generator v10.5 - REBUILD 1775837202
=============================================================

*** AUTHORIZED PRODUCTION ENGINE ***
*** SINGLE PRODUCTION PIPELINE - NO PARALLEL ENGINES ***

This is the ONLY engine authorized for production signal generation.
All other engines (market_scanner, advanced_scanner, signal_orchestrator) are DISABLED.

VERSION 10.0 - COMPLETE REWRITE (April 2026):
Price-action / structure based scoring, NOT candle-statistics based.

=== PHILOSOPHY ===
The engine evaluates trades in 3 levels:
A. CONTEXT - Is the directional bias sensible?
B. STRUCTURE - Does price structure support BUY or SELL?
C. TRIGGER - Is the entry timing good right now?

=== TIMEFRAMES ===
- H1: Context (120 candles, EMA20, EMA50, ATR14, swing points)
- M15: Structure & Pullback (160 candles, EMA20, swing points)
- M5: Entry Trigger (200 candles, EMA20, ATR14)

=== BUY FACTORS (Total = 100%) ===
1. H1 Structural Bias = 20%
2. M15 Structure Quality = 18%
3. M5 Trigger Quality = 16%
4. Pullback Quality = 14%
5. FTA / Clean Space = 14%
6. Directional Continuation = 10%
7. Session Quality = 5%
8. Market Sanity Check = 3%

=== SELL FACTORS (Total = 100%) ===
1. H1 Structural Bias = 22%
2. M15 Structure Quality = 20%
3. M5 Trigger Quality = 16%
4. Pullback Quality = 12%
5. Rejection / Failed Push = 14%
6. FTA / Clean Space = 10%
7. Session Quality = 4%
8. Market Sanity Check = 2%

=== SESSIONS (UTC) ===
- London: 07:00-12:59
- Overlap: 13:00-16:00
- NY: 16:01-20:00
- Asian/Other: rest

=== THRESHOLDS ===
BUY: min=62, preferred=68-86, hard_cap=94
SELL: min=60, preferred=64-80, hard_cap=90

=== SESSION MULTIPLIERS (BUY only) ===
- London: 1.00
- NY: 1.05
- Overlap: 1.10

=== KEY CHANGES FROM v9.x ===
1. REMOVED: concentration from score (now only filter)
2. REMOVED: old candle-counting momentum
3. REMOVED: old simple EMA comparisons
4. ADDED: EMA20/50 with slope analysis
5. ADDED: Real swing point detection (pivot-based)
6. ADDED: Pullback depth with Fibonacci zones
7. ADDED: Trigger patterns (break-hold, reclaim, rejection, failed push)
8. ADDED: Directional Continuation (BUY only)
9. ADDED: Rejection/Failed Push Quality (SELL only)
10. ADDED: Market Sanity Check (replaces regime/volatility)

R:R HARD REJECTION: < 1.15
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
from services.candidate_audit_service import candidate_audit_service
from services.signal_snapshot_service import signal_snapshot_service, SignalSnapshot, create_snapshot_from_signal_data
from services.helpers.technical_indicators import (
    calculate_ema, calculate_ema_slope, calculate_atr,
    find_swing_points, get_recent_swing_highs, get_recent_swing_lows,
    get_pullback_depth, get_technical_context,
    is_bullish_candle, is_bearish_candle,
    get_upper_wick, get_lower_wick, get_candle_range,
    is_rejection_candle, get_close_position_in_range,
    SwingPoint, TechnicalContext
)

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
    
    # Acceptance source (v3.3 Buffer Zone tracking)
    acceptance_source: str = "main_threshold"  # "main_threshold_strong", "main_threshold_good", "buffer_zone"
    
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
    
    # ==================== v10.0: PRICE-ACTION BASED SCORING ====================
    # PRODUCTION-READY: Complete rewrite with structure-based analysis
    # 
    # Philosophy: CONTEXT -> STRUCTURE -> TRIGGER
    # NOT candle-statistics based, but price-action / structure based
    
    # ==================== BUY WEIGHTS (Total = 100%) ====================
    # v10.0: Structure-based factors
    WEIGHTS_BUY = {
        'h1_structural_bias': 20.0,      # H1 Structural Bias
        'm15_structure_quality': 18.0,   # M15 Structure Quality
        'm5_trigger_quality': 16.0,      # M5 Trigger Quality
        'pullback_quality': 14.0,        # Pullback Quality
        'fta_clean_space': 14.0,         # FTA / Clean Space
        'directional_continuation': 10.0, # Directional Continuation (BUY only)
        'session_quality': 5.0,          # Session Quality
        'market_sanity': 3.0,            # Market Sanity Check
    }
    
    # ==================== SELL WEIGHTS (Total = 100%) ====================
    # v10.0: Structure-based factors with rejection focus
    WEIGHTS_SELL = {
        'h1_structural_bias': 22.0,      # H1 Structural Bias
        'm15_structure_quality': 20.0,   # M15 Structure Quality
        'm5_trigger_quality': 16.0,      # M5 Trigger Quality
        'pullback_quality': 12.0,        # Pullback Quality
        'rejection_failed_push': 14.0,   # Rejection / Failed Push (SELL only)
        'fta_clean_space': 10.0,         # FTA / Clean Space
        'session_quality': 4.0,          # Session Quality
        'market_sanity': 2.0,            # Market Sanity Check
    }
    
    # Legacy weights for backward compatibility
    WEIGHTS = WEIGHTS_BUY.copy()
    
    # ==================== BUY CONFIDENCE RULES ====================
    BUY_MIN_CONFIDENCE = 62        # Minimum score to accept BUY
    BUY_PREFERRED_RANGE = (68, 86) # Preferred score range
    BUY_HARD_CAP = 94              # Clamp BUY scores above this
    
    # ==================== SELL CONFIDENCE RULES ====================
    SELL_MIN_CONFIDENCE = 60       # Minimum score to accept SELL
    SELL_PREFERRED_RANGE = (64, 80)# Preferred score range
    SELL_HARD_CAP = 90             # Clamp SELL scores above this
    
    # ==================== SESSION RULES (UTC) ====================
    # London: 07:00-12:59, Overlap: 13:00-16:00, NY: 16:01-20:00
    BUY_ALLOWED_SESSIONS = ["London", "London/NY Overlap", "Overlap", "New York"]
    
    # BUY Session Multipliers
    BUY_SESSION_MULTIPLIERS = {
        "London": 1.00,
        "London/NY Overlap": 1.10,
        "Overlap": 1.10,
        "New York": 1.05,
    }
    
    # SELL session rules with extra confirmation
    SELL_ALLOWED_SESSIONS = ["London/NY Overlap", "Overlap", "London", "New York"]
    # SELL in London/NY requires extra confirmation (reduced requirements)
    SELL_RESTRICTED_SESSIONS = ["London", "New York"]
    SELL_RESTRICTED_MIN_H1 = 55      # v10.2: Reduced from 70 to 55
    SELL_RESTRICTED_MIN_M15 = 65     # Reduced from 75
    SELL_RESTRICTED_MIN_REJECTION = 60  # Reduced from 70
    
    # ==================== REJECTION REASONS (v10.0) ====================
    REJECTION_BUY_SESSION_BLOCKED = "buy_session_blocked"
    REJECTION_SELL_SESSION_BLOCKED = "sell_session_blocked"
    REJECTION_BUY_CONFIDENCE_LOW = "BUY confidence below threshold"
    REJECTION_SELL_CONFIDENCE_LOW = "SELL confidence below threshold"
    REJECTION_BUY_EXTRA_CONFIRM_FAILED = "buy_extra_confirmation_failed"
    REJECTION_SELL_EXTRA_CONFIRM_FAILED = "sell_extra_confirmation_failed"
    REJECTION_WEAK_TRIGGER = "weak_trigger"
    REJECTION_SELL_REJECTION_MISSING = "sell_rejection_missing"
    REJECTION_IMPULSE_TOO_SMALL = "impulse_too_small"
    REJECTION_FTA_BLOCKED = "fta_blocked"
    REJECTION_MARKET_NOT_SANE = "market_not_sane"
    REJECTION_LOW_RR = "low_rr"
    REJECTION_DUPLICATE = "duplicate"
    REJECTION_ASSET_OVERCONCENTRATED = "asset_direction_overconcentrated"
    
    # ==================== MARKET SANITY THRESHOLDS ====================
    # EURUSD - Relaxed thresholds for low volatility market
    EURUSD_ATR_MIN = 0.00015       # 1.5 pips minimum ATR (reduced from 2.5)
    EURUSD_ATR_MAX = 0.0020        # 20 pips maximum ATR
    EURUSD_SPIKE_MAX = 0.0015      # 15 pips max single candle
    
    # XAUUSD
    XAUUSD_ATR_MIN = 0.6           # $0.6 minimum ATR (reduced from 0.9)
    XAUUSD_ATR_MAX = 12.0          # $12.0 maximum ATR (increased)
    XAUUSD_SPIKE_MAX = 6.0         # $6.0 max single candle (increased)
    
    # ==================== PULLBACK THRESHOLDS ====================
    # EURUSD
    EURUSD_IMPULSE_MIN = 0.0012    # 12 pips minimum impulse
    EURUSD_PULLBACK_MIN = 0.0005   # 5 pips minimum pullback
    EURUSD_PULLBACK_IDEAL_MAX = 0.0018  # 18 pips ideal max
    EURUSD_PULLBACK_DEEP = 0.0024  # 24 pips too deep
    
    # XAUUSD
    XAUUSD_IMPULSE_MIN = 4.0       # $4 minimum impulse
    XAUUSD_PULLBACK_MIN = 1.5      # $1.5 minimum pullback
    XAUUSD_PULLBACK_IDEAL_MAX = 6.5  # $6.5 ideal max
    XAUUSD_PULLBACK_DEEP = 8.5     # $8.5 too deep
    
    # ==================== R:R THRESHOLDS ====================
    MIN_RR_HARD_REJECT = 1.15      # v10.0: Raised from 1.1
    
    # ==================== CONCENTRATION FILTER (Not in score) ====================
    CONCENTRATION_WINDOW_MINUTES = 25
    CONCENTRATION_MAX_SAME_DIRECTION = 2
    EURUSD_DUPLICATE_ZONE = 0.0012  # 12 pips
    XAUUSD_DUPLICATE_ZONE = 3.0     # $3
    
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
    
    # ==================== DATA-DRIVEN FILTERS (v3.3) ====================
    # OPTIMIZED: Controlled signal flow with preserved edge
    # Target: 5-15 signals per day (not over-filtered)
    
    # MINIMUM SCORE - Keep high edge threshold
    # Data: Score 75+ = +46R combined, Score <75 = -15R
    # ========== SCORE THRESHOLD (v5 - DATA COLLECTION MODE) ==========
    # Previous: 75 (edge preservation mode)
    # Current: 65 (aggressive data collection - to generate accepted trades)
    # Will be re-evaluated after collecting 50+ real trades
    # NOTE: This is TEMPORARILY low to unblock the engine
    MIN_CONFIDENCE_SCORE = 60  # v6.0: Lowered from 65 based on rejection analysis (blocked 32% WR trades)
    
    # v7.0: M15 CONTEXT MINIMUM - strongest predictor (+9.2 delta)
    # Data: M15 >= 70 in winners vs M15 < 70 in losers
    MIN_M15_CONTEXT_SCORE = 70  # Hard reject if M15 Context < 70
    
    # MTF ALIGNMENT - Keep strong alignment requirement
    # ========== MTF FILTER (v5) - MORE LENIENT ==========
    # Data: Strong MTF (>=80) = +35R, Weak MTF (<80) = -3R
    # BUT: We need trades to measure edge, so lower hard block threshold
    MIN_MTF_SCORE = 60  # Hard block only below 60
    MTF_SOFT_THRESHOLD = 75  # Penalty only below 75 (not 80)
    MTF_PENALTY_PER_POINT = 0.15  # Reduced from 0.3 - each point below 75 = -0.15 score
    
    # ALLOWED ASSETS - RE-ENABLED XAUUSD (top performer)
    # Data: XAUUSD = +33.53R (66% WR), EURUSD = -2.03R (39% WR)
    # Previous filter was WRONG - XAUUSD is the winner!
    ALLOWED_ASSETS = [Asset.EURUSD, Asset.XAUUSD]
    
    # ALLOWED SESSIONS - v7.0: NY + Overlap ONLY (London blocked!)
    # Data analysis: London = 20.6% WR (-16.69R), NY = 94.3% WR (+47.50R)
    # London BLOCKED - massive underperformance
    ALLOWED_SESSIONS = ["London/NY Overlap", "Overlap", "New York"]
    
    # Session priority configuration - v7.0 UPDATED
    SESSION_PRIORITY = {
        "London": "BLOCKED",          # v7.0: BLOCKED - 20.6% WR disaster
        "London/NY Overlap": "HIGH",  # Good volume, decent performance  
        "Overlap": "HIGH",            # Same as above
        "New York": "HIGH",           # v7.0: UPGRADED - 94.3% WR best session!
        "Asian": "LOW",               # Not allowed
        "Sydney": "LOW"               # Not allowed
    }
    
    # Session score adjustment (applied to final score) - v7.0 UPDATED
    SESSION_SCORE_ADJUSTMENT = {
        "London": -999,               # v7.0: BLOCKED
        "London/NY Overlap": 0,
        "Overlap": 0,
        "New York": +5,               # v7.0: BONUS for best session!
        "Asian": -15,
        "Sydney": -15
    }
    
    # SETUP TYPES - SOFT FILTER (penalty instead of block)
    # All setups allowed, but non-preferred get score penalty
    # Preferred: Technical Setup, HTF Continuation, Momentum Breakout
    PREFERRED_SETUP_PATTERNS = ["Technical Setup", "HTF Continuation", "Momentum Breakout", "HTF Trend Continuation"]
    PENALIZED_SETUP_PATTERNS = ["Fib Retracement", "Structure Pullback"]  # -10 score penalty
    
    # SOFT FILTER PENALTIES (instead of hard blocks)
    PENALTY_WEAK_SESSION = 5      # NY session penalty
    PENALTY_NON_PREFERRED_SETUP = 10  # Fib, Structure Pullback
    PENALTY_WEAK_MOMENTUM = 5     # Low momentum
    
    # MINIMUM SIGNAL TARGET
    MIN_SIGNALS_PER_DAY = 5
    MAX_SIGNALS_PER_DAY = 15
    
    # FTA - SOFT FILTER (never hard block unless <0.3R)
    FTA_HARD_BLOCK_THRESHOLD = 0.3  # Only block if FTA < 0.3R from entry
    
    def __init__(self, db):
        self.db = db
        self.is_running = False
        self.scan_interval = 5
        self.scanner_task: Optional[asyncio.Task] = None
        self.watchdog_task: Optional[asyncio.Task] = None
        
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
        
        # ========== BUFFER ZONE MONITORING (v3.3) ==========
        self.candidates_evaluated = 0
        self.candidates_score_gte_65 = 0  # Main threshold (>=65)
        self.candidates_score_60_64 = 0   # Buffer zone range (60-64)
        self.candidates_score_lt_60 = 0   # Below buffer zone (<60)
        self.accepted_main_threshold = 0  # Accepted via main threshold
        self.accepted_buffer_zone = 0     # Accepted via buffer zone
        self.buffer_zone_failed = 0       # Buffer zone evaluated but failed conditions
        
        # ========== BUFFER ZONE FAILURE DIAGNOSTICS (v5.1) ==========
        self.buffer_fail_by_reason: Dict[str, int] = {
            "mtf_low": 0,        # MTF < 60
            "h1_low": 0,         # H1 < 60
            "rr_low": 0,         # R:R < 1.2
            "mtf_h1": 0,         # MTF + H1 both failed
            "mtf_rr": 0,         # MTF + R:R both failed
            "h1_rr": 0,          # H1 + R:R both failed
            "all_failed": 0      # All three failed
        }
        
        # ========== SELF-HEALING: Heartbeat & Watchdog ==========
        self.last_scan_timestamp: Optional[datetime] = None
        self.last_successful_scan: Optional[datetime] = None
        self.scanner_restart_count = 0
        self.consecutive_failures = 0
        self.max_consecutive_failures = 5
        self.watchdog_interval = 10  # Check every 10 seconds
        self.scan_timeout = 15  # Restart if no scan for 15 seconds
        self.is_degraded = False
        self.degradation_reason: Optional[str] = None
        
        # Load persisted state
        self._load_state()
        
        logger.info("🚀 Signal Generator v3.3 initialized (OPTIMIZED FLOW + EDGE)")
        logger.info(f"   Prop Config: ${PROP_CONFIG.account_size:,.0f} account, ${PROP_CONFIG.max_daily_loss:,.0f} max daily loss")
        logger.info(f"   Dynamic Risk Range: {PROP_CONFIG.min_risk_percent}% - {PROP_CONFIG.max_risk_percent}%")
        logger.info(f"   Min SL: EURUSD={ASSET_CONFIGS[Asset.EURUSD].min_sl_pips}p")
        logger.info(f"   R:R Hard Reject: < {self.MIN_RR_HARD_REJECT}")
        logger.info("   ========== OPTIMIZED FILTERS (v3.3) ==========")
        logger.info(f"   Min confidence: {self.MIN_CONFIDENCE_SCORE}% (edge preserved)")
        logger.info(f"   Min MTF score: {self.MIN_MTF_SCORE}% (strong only)")
        logger.info(f"   Allowed assets: {[a.value for a in self.ALLOWED_ASSETS]} (XAUUSD RE-ENABLED)")
        logger.info(f"   Allowed sessions: {self.ALLOWED_SESSIONS}")
        logger.info(f"   Session priorities: HIGH={[s for s,p in self.SESSION_PRIORITY.items() if p=='HIGH']}, MEDIUM={[s for s,p in self.SESSION_PRIORITY.items() if p=='MEDIUM']}")
        logger.info("   Setup filter: SOFT (penalties, not blocks)")
        logger.info(f"   FTA filter: SOFT (block only if < {self.FTA_HARD_BLOCK_THRESHOLD}R)")
        logger.info(f"   Target signals/day: {self.MIN_SIGNALS_PER_DAY}-{self.MAX_SIGNALS_PER_DAY}")
        logger.info("   =================================================")
        logger.info("   TRADE MANAGEMENT: Partial TP@0.5R, BE@1R, Trailing@1R")
    
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
    
    def _log_candidate_audit(
        self,
        symbol: str,
        direction: str,
        session: str,
        setup_type: str,
        decision: str,
        rejection_reason: str = "",
        rejection_details: str = "",
        components: List[ScoreComponent] = None,
        final_score: float = 0.0,
        threshold: float = 75.0,
        mtf_score: float = 0.0,
        fta: FirstTroubleArea = None,
        entry_price: float = 0.0,
        stop_loss: float = 0.0,
        take_profit: float = 0.0,
        risk_reward: float = 0.0,
        news_penalty: float = 0.0,
        spread_penalty: float = 0.0,
        setup_penalty: float = 0.0,
        buffer_zone_data: Dict = None  # v3.3: Buffer zone tracking data
    ):
        """
        Log candidate trade with FULL THRESHOLD BREAKDOWN.
        
        Called for EVERY trade that reaches evaluation stage,
        whether accepted or rejected.
        
        This is ASYNC-SAFE and does NOT slow down the scanner.
        """
        try:
            # Build score breakdown dict
            score_breakdown = {
                "total": final_score,
                "threshold": threshold,
                "mtf": mtf_score,
                "fta_penalty": fta.fta_penalty if fta else 0,
                "fta_distance_r": fta.fta_distance_in_r if fta else 0,
                "fta_level": fta.fta_price if fta else 0,
                "clean_space_r": fta.clean_space_ratio if fta else 0,
                "news_penalty": news_penalty,
                "spread_penalty": spread_penalty,
                "setup_penalty": setup_penalty
            }
            
            # Extract individual component scores if available
            components_list = None
            if components:
                components_list = [{"name": comp.name, "score": comp.score, "weight": comp.weight, "reason": comp.reason} for comp in components]
                for comp in components:
                    name_key = comp.name.lower().replace(' ', '_').replace('/', '_')
                    score_breakdown[name_key] = comp.score
            
            # Build filter flags based on rejection reason
            filter_flags = {
                "score_passed": final_score >= threshold,
                "mtf_passed": mtf_score >= self.MIN_MTF_SCORE,
                "fta_passed": not (fta and fta.fta_blocked_trade),
                "session_passed": session in self.ALLOWED_SESSIONS,
                "asset_passed": True,  # Already checked at scan level
                "duplicate_blocked": "duplicate" in rejection_reason.lower(),
                "news_blocked": "news" in rejection_reason.lower(),
                "rr_passed": risk_reward >= self.MIN_RR_HARD_REJECT,
                "spread_passed": True,  # Already checked at scan level
                "daily_limit_passed": "daily" not in rejection_reason.lower()
            }
            
            # Build trade levels - use correct pip_size for asset
            # Get pip_size from asset config (EURUSD=0.0001, XAUUSD=0.01)
            pip_size = 0.0001  # default for forex
            try:
                from services.signal_generator_v3 import ASSET_CONFIGS, Asset
                asset_enum = Asset(symbol) if symbol in [a.value for a in Asset] else None
                if asset_enum and asset_enum in ASSET_CONFIGS:
                    pip_size = ASSET_CONFIGS[asset_enum].pip_size
            except:
                pip_size = 0.01 if "XAU" in symbol or "GOLD" in symbol else 0.0001
            
            trade_levels = {
                "entry": entry_price,
                "stop_loss": stop_loss,
                "take_profit_1": take_profit,
                "take_profit_2": 0,  # Will be set if available
                "risk_reward": risk_reward,
                "sl_pips": abs(entry_price - stop_loss) / pip_size if entry_price > 0 and stop_loss > 0 else 0,
                "tp_pips": abs(take_profit - entry_price) / pip_size if entry_price > 0 and take_profit > 0 else 0
            }
            
            # Record in audit service
            candidate_audit_service.record_candidate(
                symbol=symbol,
                direction=direction,
                session=session,
                setup_type=setup_type,
                decision=decision,
                rejection_reason=rejection_reason,
                rejection_details=rejection_details,
                score_breakdown=score_breakdown,
                filter_flags=filter_flags,
                trade_levels=trade_levels,
                components=components_list
            )
            
            # ========== SIGNAL SNAPSHOT (NEW) ==========
            # Create comprehensive snapshot for UI display
            try:
                # Generate signal_id for snapshots
                timestamp_str = datetime.utcnow().strftime("%Y%m%d_%H%M%S")
                snapshot_signal_id = f"{symbol}_{direction}_{timestamp_str}"
                
                # Build factor contributions list
                factor_contributions = []
                total_factor_score = 0
                if components:
                    for comp in components:
                        normalized = comp.score
                        contribution = comp.weighted_score
                        total_factor_score += contribution
                        
                        # Determine status
                        if normalized >= 70:
                            status = "pass"
                        elif normalized >= 50:
                            status = "neutral"
                        else:
                            status = "fail"
                        
                        factor_contributions.append({
                            "factor_key": comp.name.lower().replace(' ', '_').replace('/', '_'),
                            "factor_name": comp.name,
                            "raw_value": comp.score,
                            "normalized_value": normalized,
                            "weight_pct": comp.weight,
                            "score_contribution": round(contribution, 2),
                            "status": status,
                            "reason": comp.reason
                        })
                
                # Build penalties list
                penalties_list = []
                total_penalties = 0
                
                if fta and fta.fta_penalty != 0:
                    penalties_list.append({
                        "penalty_key": "fta_penalty",
                        "penalty_name": "FTA Distance Penalty",
                        "penalty_value": fta.fta_penalty,
                        "trigger_condition": f"FTA at {fta.clean_space_ratio:.2f}R ratio",
                        "raw_measurement": fta.fta_distance_in_r,
                        "reason": f"{fta.fta_type} at {fta.fta_price}, distance {fta.fta_distance_in_r:.2f}R"
                    })
                    total_penalties += abs(fta.fta_penalty)
                
                if news_penalty > 0:
                    penalties_list.append({
                        "penalty_key": "news_penalty",
                        "penalty_name": "News Impact Penalty",
                        "penalty_value": -news_penalty,
                        "trigger_condition": "High-impact news event nearby",
                        "raw_measurement": news_penalty,
                        "reason": f"Score reduced by {news_penalty} points"
                    })
                    total_penalties += news_penalty
                
                # v9.1: spread_penalty REMOVED - no discrimination between W/L
                # Old code removed: if spread_penalty > 0: ...
                
                if setup_penalty > 0:
                    penalties_list.append({
                        "penalty_key": "setup_penalty",
                        "penalty_name": "Setup Type Penalty",
                        "penalty_value": -setup_penalty,
                        "trigger_condition": f"Setup type: {setup_type}",
                        "raw_measurement": setup_penalty,
                        "reason": f"Setup penalty: {setup_penalty} points"
                    })
                    total_penalties += setup_penalty
                
                # Build filters list
                filters_list = []
                blocking_filter = ""
                
                for filter_name, passed in filter_flags.items():
                    filter_threshold = 0
                    actual_value = 0
                    blocks_trade = False
                    
                    if filter_name == "score_passed":
                        filter_threshold = threshold
                        actual_value = final_score
                        blocks_trade = not passed and "low_confidence" in rejection_reason.lower()
                    elif filter_name == "mtf_passed":
                        filter_threshold = self.MIN_MTF_SCORE
                        actual_value = mtf_score
                        blocks_trade = not passed and "weak_mtf" in rejection_reason.lower()
                    elif filter_name == "rr_passed":
                        filter_threshold = self.MIN_RR_HARD_REJECT
                        actual_value = risk_reward
                        blocks_trade = not passed
                    elif filter_name == "duplicate_blocked":
                        blocks_trade = not passed if "duplicate" in filter_name else False
                    
                    if blocks_trade and not blocking_filter:
                        blocking_filter = filter_name
                    
                    filters_list.append({
                        "filter_name": filter_name,
                        "threshold": filter_threshold,
                        "actual_value": actual_value,
                        "passed": passed,
                        "blocks_trade": blocks_trade,
                        "reason": f"{'PASSED' if passed else 'BLOCKED'}: {filter_name}"
                    })
                
                # Create score breakdown for snapshot
                score_breakdown_snap = {
                    "total_score": final_score,
                    "factors": factor_contributions
                }
                
                # Create snapshot
                snapshot = create_snapshot_from_signal_data(
                    signal_id=snapshot_signal_id,
                    symbol=symbol,
                    direction=direction,
                    entry_price=entry_price,
                    stop_loss=stop_loss,
                    take_profit=take_profit,
                    session=session,
                    setup_type=setup_type,
                    score_breakdown=score_breakdown_snap,
                    penalties=penalties_list,
                    filters=filters_list,
                    status=decision,
                    acceptance_source=buffer_zone_data.get('acceptance_source', '') if buffer_zone_data else '',
                    rejection_reason=rejection_reason,
                    blocking_filter=blocking_filter
                )
                
                # Save snapshot asynchronously
                asyncio.create_task(signal_snapshot_service.save_snapshot(snapshot))
                
            except Exception as snap_err:
                logger.debug(f"Snapshot creation error (non-blocking): {snap_err}")
            
        except Exception as e:
            # Never let audit logging crash the scanner
            logger.debug(f"Candidate audit logging error: {e}")
    
    # ==================== LIFECYCLE ====================
    
    async def start(self):
        """Start the generator with self-healing watchdog"""
        if self.is_running:
            return
        
        self.is_running = True
        self.start_time = datetime.utcnow()
        self.last_scan_timestamp = datetime.utcnow()
        self.last_successful_scan = datetime.utcnow()
        
        logger.info("=" * 60)
        logger.info("🚀 SIGNAL GENERATOR V3.3 STARTED (SELF-HEALING)")
        logger.info("   Mode: High-quality, low-frequency signals")
        logger.info("   R:R: DYNAMIC (min 1.1)")
        logger.info("   Risk%: DYNAMIC based on confidence")
        logger.info(f"   Min confidence: {self.MIN_CONFIDENCE_SCORE}%")
        logger.info(f"   Min MTF: {self.MIN_MTF_SCORE}")
        logger.info(f"   Assets: {[a.value for a in self.ALLOWED_ASSETS]}")
        logger.info(f"   Sessions: {self.ALLOWED_SESSIONS}")
        logger.info(f"   Scan interval: {self.scan_interval}s")
        logger.info(f"   Watchdog interval: {self.watchdog_interval}s")
        logger.info(f"   Scan timeout: {self.scan_timeout}s")
        logger.info(f"   Prop: ${PROP_CONFIG.account_size:,.0f} | Max Daily: ${PROP_CONFIG.max_daily_loss:,.0f}")
        logger.info("   MANAGEMENT: Partial@0.5R | BE@1R | Trail@1R")
        logger.info("=" * 60)
        
        # Start scanner loop
        self.scanner_task = asyncio.create_task(self._run_loop())
        
        # Start watchdog
        self.watchdog_task = asyncio.create_task(self._watchdog_loop())
        logger.info("🛡️ Watchdog started - monitoring scanner health")
    
    async def stop(self):
        """Stop the generator"""
        self.is_running = False
        
        # Stop watchdog
        if self.watchdog_task:
            self.watchdog_task.cancel()
            try:
                await self.watchdog_task
            except asyncio.CancelledError:
                pass
        
        # Stop scanner
        if self.scanner_task:
            self.scanner_task.cancel()
            try:
                await self.scanner_task
            except asyncio.CancelledError:
                pass
        
        self._save_state()
        logger.info("🛑 Signal Generator v3.3 stopped")
    
    async def _watchdog_loop(self):
        """
        SELF-HEALING WATCHDOG
        Monitors scanner health and restarts if stalled
        """
        while self.is_running:
            try:
                await asyncio.sleep(self.watchdog_interval)
                
                if not self.is_running:
                    break
                
                # Check if scanner is stalled
                if self.last_scan_timestamp:
                    scan_age = (datetime.utcnow() - self.last_scan_timestamp).total_seconds()
                    
                    if scan_age > self.scan_timeout:
                        # SCANNER STALLED - trigger restart
                        logger.warning("=" * 60)
                        logger.warning("🚨 ALERT: SCANNER_STALLED")
                        logger.warning(f"   Last scan: {scan_age:.1f}s ago (timeout: {self.scan_timeout}s)")
                        logger.warning(f"   Consecutive failures: {self.consecutive_failures}")
                        logger.warning("   Action: Restarting scanner loop...")
                        logger.warning("=" * 60)
                        
                        await self._restart_scanner_loop()
                
                # Check for degraded state
                if self.consecutive_failures >= self.max_consecutive_failures:
                    if not self.is_degraded:
                        self.is_degraded = True
                        self.degradation_reason = f"{self.consecutive_failures} consecutive scan failures"
                        logger.error("🚨 ALERT: SYSTEM_DEGRADED")
                        logger.error(f"   Reason: {self.degradation_reason}")
                elif self.is_degraded and self.consecutive_failures == 0:
                    self.is_degraded = False
                    self.degradation_reason = None
                    logger.info("✅ System recovered from degraded state")
                    
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"Watchdog error: {e}")
    
    async def _restart_scanner_loop(self):
        """Restart the scanner loop (self-healing)"""
        self.scanner_restart_count += 1
        logger.warning(f"🔄 SCANNER_RESTART #{self.scanner_restart_count}")
        
        # Cancel existing scanner task
        if self.scanner_task:
            self.scanner_task.cancel()
            try:
                await self.scanner_task
            except asyncio.CancelledError:
                pass
        
        # Reset failure counters
        self.consecutive_failures = 0
        
        # Start new scanner task
        self.scanner_task = asyncio.create_task(self._run_loop())
        self.last_scan_timestamp = datetime.utcnow()
        
        logger.info("✅ Scanner loop restarted successfully")
    
    async def _run_loop(self):
        """Main loop with heartbeat updates - VERBOSE LOGGING"""
        logger.info("🔁 SCAN LOOP STARTING - entering main loop")
        loop_count = 0
        
        while self.is_running:
            loop_count += 1
            try:
                # Update heartbeat BEFORE scan
                self.last_scan_timestamp = datetime.utcnow()
                
                # VERBOSE: Log every cycle
                if loop_count % 10 == 1:  # Log every 10th cycle (every ~50s)
                    logger.info(f"🔁 SCAN LOOP ACTIVE | Cycle: {loop_count} | Total Scans: {self.scan_count} | Time: {self.last_scan_timestamp.strftime('%H:%M:%S')}")
                
                await self._scan_all_assets()
                
                # Update successful scan timestamp
                self.last_successful_scan = datetime.utcnow()
                self.consecutive_failures = 0
                
                # Periodic state save
                if self.scan_count % 20 == 0:
                    self._save_state()
                    
            except Exception as e:
                self.consecutive_failures += 1
                logger.error(f"Generator error (failure #{self.consecutive_failures}): {e}", exc_info=True)
                
                if self.consecutive_failures >= self.max_consecutive_failures:
                    logger.error("🚨 ALERT: MAX_CONSECUTIVE_FAILURES reached")
            
            await asyncio.sleep(self.scan_interval)
        
        logger.warning("🔁 SCAN LOOP EXITED - is_running is False")
    
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
        
        # ========== v9.0: SESSION FILTER REMOVED FROM SCAN LEVEL ==========
        # Session rules are now DIRECTION-SPECIFIC:
        # - BUY: All sessions allowed (London, NY, Overlap)
        # - SELL: ONLY Overlap allowed
        # The check is now done AFTER direction is determined in _analyze_asset
        current_session = self._get_session_name(session_detector.get_current_session())
        
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
        # - v5: NO HARD BLOCK - penalty only based on fta_distance_r
        
        # Calculate FTA distance in R (Risk units)
        risk = abs(target_price - entry_price) / max(1, fta.target_distance) if fta.target_distance > 0 else 0
        fta_distance_in_r = fta.fta_distance / abs(target_price - entry_price) if abs(target_price - entry_price) > 0 else 0
        
        # ========== FTA PENALTY SYSTEM v5 (NO HARD BLOCK) ==========
        # Penalty based on fta_distance_r:
        # - < 0.2R → -15
        # - 0.2-0.35R → -8
        # - 0.35-0.5R → -4
        # - > 0.5R → 0
        
        if fta_distance_in_r >= 0.5:
            fta.fta_quality = "clear"
            fta.fta_penalty = 0
        elif fta_distance_in_r >= 0.35:
            fta.fta_quality = "moderate"
            fta.fta_penalty = 4
        elif fta_distance_in_r >= 0.2:
            fta.fta_quality = "close"
            fta.fta_penalty = 8
        else:
            fta.fta_quality = "very_close"
            fta.fta_penalty = 15
        
        # v5: NEVER set fta_blocked_trade to True
        fta.fta_blocked_trade = False
        
        # Special case: if FTA nearly coincides with target (>90% clean space), bonus
        if fta.clean_space_ratio >= 0.90:
            fta.fta_penalty = -5  # Bonus
            fta.fta_quality = "excellent"
        
        # Special case: M15 confirmed swing target - reduce concern
        if tp_type == "swing_target" and fta.clean_space_ratio >= 0.25:
            fta.fta_penalty = max(0, fta.fta_penalty - 2)
        
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
        FTA SOFT FILTER EVALUATION (v5 - NO HARD BLOCK)
        
        NEW APPROACH (v5):
        - FTA is PURELY a score modifier - NEVER blocks
        - Penalty based on fta_distance_r:
          * < 0.2R → -15
          * 0.2-0.35R → -8
          * 0.35-0.5R → -4
          * > 0.5R → 0
        
        Returns:
            Tuple[should_block, override_applied, reason]
            should_block is ALWAYS False in v5
        """
        ratio = fta.clean_space_ratio
        fta_distance_r = getattr(fta, 'fta_distance_in_r', 1.0)
        
        # ========== v5: NO HARD BLOCK - ONLY PENALTIES ==========
        # FTA penalty is applied to score, let confidence threshold filter
        
        # Log FTA quality for analysis
        if fta_distance_r >= 0.5:
            reason = f"fta_clear: distance={fta_distance_r:.2f}R (>=0.5R), penalty=0"
        elif fta_distance_r >= 0.35:
            reason = f"fta_moderate: distance={fta_distance_r:.2f}R (0.35-0.5R), penalty=-4"
        elif fta_distance_r >= 0.2:
            reason = f"fta_close: distance={fta_distance_r:.2f}R (0.2-0.35R), penalty=-8"
        else:
            reason = f"fta_very_close: distance={fta_distance_r:.2f}R (<0.2R), penalty=-15"
        
        # NEVER block - let score threshold decide
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
    
    def _check_concentration_filter(self, asset: Asset, direction: str, entry_price: float) -> Tuple[bool, str]:
        """
        v10.0: Concentration as FILTER only (not in score)
        
        Returns: (is_concentrated, reason)
        is_concentrated = True means REJECT the signal
        
        Rules:
        - If 2+ signals same asset/direction in last 25 min -> reject
        - If 1 signal same asset/direction/zone in last 25 min -> reject (duplicate)
        """
        if len(self.recent_signals) == 0:
            return False, "No recent signals"
        
        now = datetime.utcnow()
        window = timedelta(minutes=self.CONCENTRATION_WINDOW_MINUTES)
        
        # Count recent signals same asset + direction
        same_asset_dir_count = 0
        for sig in self.recent_signals:
            if sig.asset == asset and sig.direction == direction:
                if hasattr(sig, 'timestamp') and sig.timestamp:
                    if (now - sig.timestamp) < window:
                        same_asset_dir_count += 1
                        
                        # Check for duplicate (same zone)
                        if hasattr(sig, 'entry_price') and sig.entry_price:
                            if asset == Asset.EURUSD:
                                zone_diff = abs(entry_price - sig.entry_price)
                                if zone_diff < self.EURUSD_DUPLICATE_ZONE:
                                    return True, f"Duplicate: {asset.value} {direction} within {zone_diff*10000:.1f}p"
                            else:  # XAUUSD
                                zone_diff = abs(entry_price - sig.entry_price)
                                if zone_diff < self.XAUUSD_DUPLICATE_ZONE:
                                    return True, f"Duplicate: {asset.value} {direction} within ${zone_diff:.1f}"
        
        # Check overconcentration
        if same_asset_dir_count >= self.CONCENTRATION_MAX_SAME_DIRECTION:
            return True, f"Overconcentrated: {same_asset_dir_count} {asset.value} {direction} in {self.CONCENTRATION_WINDOW_MINUTES}min"
        
        return False, "No concentration issue"
    
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
        
        # ========== v10.0: Session filter moved to scoring section ==========
        # Session rules are now applied AFTER scoring calculation
        
        # ========== ENTRY VALIDATION ==========
        
        entry_valid, entry_score, entry_reason, entry_zone_low, entry_zone_high = self._validate_entry(
            asset, direction, current_price, atr
        )
        
        if not entry_valid:
            self._record_rejection("late_entry")
            logger.info(f"⏭️ {asset.value} {direction}: {entry_reason}")
            # Log candidate audit (early rejection, partial data)
            self._log_candidate_audit(
                symbol=asset.value,
                direction=direction,
                session=session_name,
                setup_type="UNKNOWN",
                decision="rejected",
                rejection_reason="late_entry",
                rejection_details=entry_reason,
                final_score=0,
                threshold=self.MIN_CONFIDENCE_SCORE,
                entry_price=current_price,
                stop_loss=0,
                take_profit=0,
                risk_reward=0
            )
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
            # Log candidate audit (early rejection, partial data)
            self._log_candidate_audit(
                symbol=asset.value,
                direction=direction,
                session=session_name,
                setup_type="UNKNOWN",
                decision="rejected",
                rejection_reason="low_rr",
                rejection_details=f"R:R {rr_ratio:.2f} < {self.MIN_RR_HARD_REJECT}",
                final_score=0,
                threshold=self.MIN_CONFIDENCE_SCORE,
                entry_price=entry_price,
                stop_loss=stop_loss,
                take_profit=take_profit_1,
                risk_reward=rr_ratio
            )
            return None
        
        # ========== v10.0: NEW SCORING ENGINE ==========
        # Philosophy: CONTEXT -> STRUCTURE -> TRIGGER
        
        components = []
        
        # v10.0: Get direction-specific weights
        weights = self.WEIGHTS_BUY if direction == "BUY" else self.WEIGHTS_SELL
        
        # ========== 1. H1 STRUCTURAL BIAS (20% BUY / 22% SELL) ==========
        h1_score, h1_reason = self._score_h1_structural_bias(h1_candles, direction)
        h1_weight = weights.get('h1_structural_bias', 20)
        components.append(ScoreComponent("H1 Structural Bias", h1_weight, h1_score, h1_reason))
        
        # v10.2: Relaxed H1 thresholds
        # BUY: 50, SELL: 50 (equal treatment)
        h1_min = 50  # Same for both directions now
        if h1_score < h1_min:
            self._record_rejection("h1_weak")
            logger.info(f"🚫 {asset.value} {direction}: H1 Structural Bias too weak ({h1_score:.0f}% < {h1_min}%)")
            # Save rejected candidate audit
            self._log_candidate_audit(
                symbol=asset.value,
                direction=direction,
                session=session_name,
                setup_type="STRUCTURAL",
                decision="rejected",
                rejection_reason="h1_weak",
                rejection_details=f"H1 Structural Bias {h1_score:.0f}% < {h1_min}%",
                final_score=h1_score,
                threshold=h1_min,
                entry_price=current_price,
                stop_loss=0,
                take_profit=0,
                risk_reward=0
            )
            return None
        
        # ========== 2. M15 STRUCTURE QUALITY (18% BUY / 20% SELL) ==========
        m15_score, m15_reason = self._score_m15_structure_quality(m15_candles, direction)
        m15_weight = weights.get('m15_structure_quality', 18)
        components.append(ScoreComponent("M15 Structure Quality", m15_weight, m15_score, m15_reason))
        
        # ========== 3. M5 TRIGGER QUALITY (16% BUY / 16% SELL) ==========
        trigger_score, trigger_reason = self._score_m5_trigger_quality(m5_candles, direction)
        trigger_weight = weights.get('m5_trigger_quality', 16)
        components.append(ScoreComponent("M5 Trigger Quality", trigger_weight, trigger_score, trigger_reason))
        
        # v10.0: Hard filter - weak trigger
        # v10.2: Trigger score threshold lowered from 60 to 55
        if trigger_score < 55:
            self._record_rejection(self.REJECTION_WEAK_TRIGGER)
            logger.info(f"🚫 {asset.value} {direction}: {self.REJECTION_WEAK_TRIGGER} (score={trigger_score:.0f}%)")
            # Save rejected candidate audit
            self._log_candidate_audit(
                symbol=asset.value,
                direction=direction,
                session=session_name,
                setup_type="STRUCTURAL",
                decision="rejected",
                rejection_reason=self.REJECTION_WEAK_TRIGGER,
                rejection_details=f"Trigger score {trigger_score:.0f}% < 55%",
                final_score=trigger_score,
                threshold=55,
                entry_price=current_price,
                stop_loss=0,
                take_profit=0,
                risk_reward=0
            )
            return None
        
        # ========== 4. PULLBACK QUALITY (14% BUY / 12% SELL) ==========
        pb_score, pb_reason, pb_valid = self._score_pullback_quality_v10(
            asset, m15_candles, m5_candles, direction, current_price
        )
        pb_weight = weights.get('pullback_quality', 14)
        components.append(ScoreComponent("Pullback Quality", pb_weight, pb_score, pb_reason))
        
        # v10.0: Hard filter - impulse too small
        if not pb_valid:
            self._record_rejection(self.REJECTION_IMPULSE_TOO_SMALL)
            logger.info(f"🚫 {asset.value} {direction}: {self.REJECTION_IMPULSE_TOO_SMALL}: {pb_reason}")
            return None
        
        # ========== 5. DIRECTION-SPECIFIC FACTOR ==========
        if direction == "BUY":
            # DIRECTIONAL CONTINUATION (10%)
            cont_score, cont_reason = self._score_directional_continuation(m15_candles, m5_candles, direction)
            cont_weight = weights.get('directional_continuation', 10)
            components.append(ScoreComponent("Directional Continuation", cont_weight, cont_score, cont_reason))
        else:
            # REJECTION / FAILED PUSH (14%)
            rej_score, rej_reason, rej_valid = self._score_rejection_failed_push(m15_candles, m5_candles, direction)
            rej_weight = weights.get('rejection_failed_push', 14)
            components.append(ScoreComponent("Rejection / Failed Push", rej_weight, rej_score, rej_reason))
            
            # v10.0: Hard filter - SELL rejection missing
            if not rej_valid:
                self._record_rejection(self.REJECTION_SELL_REJECTION_MISSING)
                logger.info(f"🚫 {asset.value} SELL: {self.REJECTION_SELL_REJECTION_MISSING}: {rej_reason}")
                return None
        
        # ========== 6. FTA / CLEAN SPACE (14% BUY / 10% SELL) ==========
        # v10.4: Pass trigger_score for dynamic FTA calculation
        fta_score, fta_reason, fta_valid = self._score_fta_clean_space_v10(
            asset, m15_candles, m5_candles, entry_price, take_profit_1, direction, trigger_score
        )
        fta_weight = weights.get('fta_clean_space', 14)
        components.append(ScoreComponent("FTA / Clean Space", fta_weight, fta_score, fta_reason))
        
        # v10.0: Hard filter - FTA blocked
        if not fta_valid:
            self._record_rejection(self.REJECTION_FTA_BLOCKED)
            logger.info(f"🚫 {asset.value} {direction}: {self.REJECTION_FTA_BLOCKED}: {fta_reason}")
            # Save rejected candidate audit
            self._log_candidate_audit(
                symbol=asset.value,
                direction=direction,
                session=session_name,
                setup_type="STRUCTURAL",
                decision="rejected",
                rejection_reason=self.REJECTION_FTA_BLOCKED,
                rejection_details=fta_reason,
                final_score=fta_score,
                threshold=15,
                entry_price=entry_price,
                stop_loss=stop_loss,
                take_profit=take_profit_1,
                risk_reward=rr_ratio
            )
            return None
        
        # ========== 7. SESSION QUALITY (5% BUY / 4% SELL) ==========
        sess_score, sess_reason = self._score_session_quality_v10(direction)
        sess_weight = weights.get('session_quality', 5)
        components.append(ScoreComponent("Session Quality", sess_weight, sess_score, sess_reason))
        
        # ========== 8. MARKET SANITY CHECK (3% BUY / 2% SELL) ==========
        sanity_score, sanity_reason, sanity_valid = self._score_market_sanity_check(asset, m5_candles)
        sanity_weight = weights.get('market_sanity', 3)
        components.append(ScoreComponent("Market Sanity Check", sanity_weight, sanity_score, sanity_reason))
        
        # v10.0: Hard filter - market not sane
        if not sanity_valid:
            self._record_rejection(self.REJECTION_MARKET_NOT_SANE)
            logger.info(f"🚫 {asset.value} {direction}: {self.REJECTION_MARKET_NOT_SANE}: {sanity_reason}")
            return None
        
        # ========== CALCULATE BASE SCORE ==========
        final_score = sum(c.weighted_score for c in components)
        
        # Store preliminary score for reference
        preliminary_score = final_score
        
        # Get key scores for later use
        h1_score_val = h1_score
        mtf_score_val = m15_score  # Use M15 structure as MTF proxy
        
        # ========== v10.0: FTA BONUS ==========
        fta_bonus = 0
        if fta_score >= 80:  # Clean space >= 65%
            fta_bonus = 5 if direction == "SELL" else 3
            final_score += fta_bonus
            logger.info(f"📈 {asset.value} {direction}: FTA bonus +{fta_bonus}")
        elif fta_score >= 60:  # Clean space >= 50%
            fta_bonus = 2 if direction == "SELL" else 1
            final_score += fta_bonus
        
        # ========== v10.0: SESSION MULTIPLIER (BUY only) ==========
        if direction == "BUY" and session_name in self.BUY_SESSION_MULTIPLIERS:
            session_multiplier = self.BUY_SESSION_MULTIPLIERS[session_name]
            if session_multiplier != 1.0:
                old_score = final_score
                final_score = final_score * session_multiplier
                logger.info(f"📈 {asset.value} BUY: Session multiplier x{session_multiplier:.2f}: {old_score:.1f} -> {final_score:.1f}")
        
        # ========== CLAMP SCORE ==========
        final_score = max(0, min(100, final_score))
        
        # ========== v10.0: CONCENTRATION FILTER (NOT in score) ==========
        is_concentrated, conc_reason = self._check_concentration_filter(asset, direction, entry_price)
        if is_concentrated:
            self._record_rejection(self.REJECTION_ASSET_OVERCONCENTRATED)
            logger.info(f"🚫 {asset.value} {direction}: {self.REJECTION_ASSET_OVERCONCENTRATED}: {conc_reason}")
            return None
        
        # ========== v10.0: SESSION FILTER ==========
        hour = datetime.utcnow().hour
        current_session = "Overlap" if 13 <= hour <= 16 else ("London" if 7 <= hour <= 12 else ("NY" if 16 < hour <= 20 else "Asian/Other"))
        
        if direction == "BUY":
            if current_session == "Asian/Other":
                self._record_rejection(self.REJECTION_BUY_SESSION_BLOCKED)
                logger.info(f"🚫 {asset.value} BUY: {self.REJECTION_BUY_SESSION_BLOCKED} (session={current_session})")
                return None
        else:  # SELL
            if current_session == "Asian/Other":
                self._record_rejection(self.REJECTION_SELL_SESSION_BLOCKED)
                logger.info(f"🚫 {asset.value} SELL: {self.REJECTION_SELL_SESSION_BLOCKED} (session={current_session})")
                return None
            
            # SELL in London/NY needs extra confirmation
            if current_session in self.SELL_RESTRICTED_SESSIONS:
                rej_component = next((c for c in components if "Rejection" in c.name), None)
                rej_score_val = rej_component.score if rej_component else 0
                
                # === DEBUG SELL EXTRA CONFIRMATION ===
                logger.info(f"📊 [SELL EXTRA CONFIRM] Session={current_session}")
                logger.info(f"📊 [SELL EXTRA CONFIRM] H1={h1_score:.0f} (need >={self.SELL_RESTRICTED_MIN_H1})")
                logger.info(f"📊 [SELL EXTRA CONFIRM] M15={m15_score:.0f} (need >={self.SELL_RESTRICTED_MIN_M15})")
                logger.info(f"📊 [SELL EXTRA CONFIRM] Rejection={rej_score_val:.0f} (need >={self.SELL_RESTRICTED_MIN_REJECTION})")
                
                if not (h1_score >= self.SELL_RESTRICTED_MIN_H1 and 
                        m15_score >= self.SELL_RESTRICTED_MIN_M15 and
                        rej_score_val >= self.SELL_RESTRICTED_MIN_REJECTION):
                    failed_conditions = []
                    if h1_score < self.SELL_RESTRICTED_MIN_H1:
                        failed_conditions.append(f"H1={h1_score:.0f}<{self.SELL_RESTRICTED_MIN_H1}")
                    if m15_score < self.SELL_RESTRICTED_MIN_M15:
                        failed_conditions.append(f"M15={m15_score:.0f}<{self.SELL_RESTRICTED_MIN_M15}")
                    if rej_score_val < self.SELL_RESTRICTED_MIN_REJECTION:
                        failed_conditions.append(f"Rej={rej_score_val:.0f}<{self.SELL_RESTRICTED_MIN_REJECTION}")
                    
                    self._record_rejection(self.REJECTION_SELL_EXTRA_CONFIRM_FAILED)
                    logger.info(f"🚫 {asset.value} SELL: {self.REJECTION_SELL_EXTRA_CONFIRM_FAILED} ({', '.join(failed_conditions)})")
                    return None
        
        # ========== v10.0: CONFIDENCE THRESHOLDS ==========
        acceptance_source = None
        
        if direction == "BUY":
            # Apply hard cap
            if final_score > self.BUY_HARD_CAP:
                final_score = self.BUY_HARD_CAP
                logger.info(f"📊 {asset.value} BUY: Score clamped to {self.BUY_HARD_CAP}")
            
            if final_score >= self.BUY_PREFERRED_RANGE[0]:  # >= 68
                confidence = SignalConfidence.STRONG if final_score >= 80 else SignalConfidence.GOOD
                priority = "HIGH" if final_score >= 80 else "NORMAL"
                acceptance_source = "buy_preferred"
            elif final_score >= self.BUY_MIN_CONFIDENCE:  # 62-67.99: Extra confirmation
                # v10.2: Further relaxed requirements
                # H1: 55 → 50, Trigger: 60 → 55, FTA: 50 → 45
                trigger_component = next((c for c in components if "Trigger" in c.name), None)
                trigger_score_val = trigger_component.score if trigger_component else 0
                fta_component = next((c for c in components if "FTA" in c.name), None)
                fta_score_val = fta_component.score if fta_component else 0
                
                # v10.3: Super relaxed extra confirmation
                h1_ok = h1_score >= 50
                trigger_ok = trigger_score_val >= 55
                fta_ok = fta_score_val >= 35  # v10.3: lowered from 45 to 35
                
                logger.info(f"📊 [BUY EXTRA CONFIRM] score={final_score:.0f}%")
                logger.info(f"📊 [BUY EXTRA CONFIRM] H1={h1_score:.0f} (need >=50) {'✓' if h1_ok else '✗'}")
                logger.info(f"📊 [BUY EXTRA CONFIRM] Trigger={trigger_score_val:.0f} (need >=55) {'✓' if trigger_ok else '✗'}")
                logger.info(f"📊 [BUY EXTRA CONFIRM] FTA={fta_score_val:.0f} (need >=35) {'✓' if fta_ok else '✗'}")
                
                if h1_ok and trigger_ok and fta_ok:
                    confidence = SignalConfidence.ACCEPTABLE
                    priority = "BUFFER"
                    acceptance_source = "buy_extra_confirmed"
                    logger.info(f"✅ {asset.value} BUY: Extra confirmation passed (H1={h1_score:.0f}, Trigger={trigger_score_val:.0f}, FTA={fta_score_val:.0f})")
                else:
                    failed_parts = []
                    if not h1_ok:
                        failed_parts.append(f"H1={h1_score:.0f}<50")
                    if not trigger_ok:
                        failed_parts.append(f"Trig={trigger_score_val:.0f}<55")
                    if not fta_ok:
                        failed_parts.append(f"FTA={fta_score_val:.0f}<35")
                    self._record_rejection(self.REJECTION_BUY_EXTRA_CONFIRM_FAILED)
                    logger.info(f"🚫 {asset.value} BUY: {self.REJECTION_BUY_EXTRA_CONFIRM_FAILED} ({', '.join(failed_parts)})")
                    return None
            else:
                self._record_rejection(self.REJECTION_BUY_CONFIDENCE_LOW)
                logger.info(f"🚫 {asset.value} BUY: {self.REJECTION_BUY_CONFIDENCE_LOW} (score={final_score:.0f}% < {self.BUY_MIN_CONFIDENCE})")
                return None
        else:  # SELL
            # Apply hard cap
            if final_score > self.SELL_HARD_CAP:
                final_score = self.SELL_HARD_CAP
                logger.info(f"📊 {asset.value} SELL: Score clamped to {self.SELL_HARD_CAP}")
            
            if final_score >= self.SELL_PREFERRED_RANGE[0]:  # >= 64
                confidence = SignalConfidence.STRONG if final_score >= 75 else SignalConfidence.GOOD
                priority = "HIGH" if final_score >= 75 else "NORMAL"
                acceptance_source = "sell_preferred"
            elif final_score >= self.SELL_MIN_CONFIDENCE:  # 60-63.99: Extra confirmation
                # v10.1: Relaxed requirements
                # Was: H1 >= 75, Rejection >= 70, FTA >= 60
                # Now: H1 >= 60, Rejection >= 55, FTA >= 45
                rej_component = next((c for c in components if "Rejection" in c.name), None)
                rej_score_val = rej_component.score if rej_component else 0
                fta_component = next((c for c in components if "FTA" in c.name), None)
                fta_score_val = fta_component.score if fta_component else 0
                
                # v10.1: Relaxed extra confirmation
                h1_ok = h1_score >= 60
                rej_ok = rej_score_val >= 55
                fta_ok = fta_score_val >= 45
                
                # === DEBUG SELL EXTRA CONFIRMATION (CONFIDENCE LEVEL) ===
                logger.info(f"📊 [SELL CONFIDENCE EXTRA] score={final_score:.0f}% (needs extra confirm 60-63.99)")
                logger.info(f"📊 [SELL CONFIDENCE EXTRA] H1={h1_score:.0f} (need >=60) {'✓' if h1_ok else '✗'}")
                logger.info(f"📊 [SELL CONFIDENCE EXTRA] Rejection={rej_score_val:.0f} (need >=55) {'✓' if rej_ok else '✗'}")
                logger.info(f"📊 [SELL CONFIDENCE EXTRA] FTA={fta_score_val:.0f} (need >=45) {'✓' if fta_ok else '✗'}")
                
                if h1_ok and rej_ok and fta_ok:
                    confidence = SignalConfidence.ACCEPTABLE
                    priority = "BUFFER"
                    acceptance_source = "sell_extra_confirmed"
                    logger.info(f"✅ {asset.value} SELL: Extra confirmation passed (H1={h1_score:.0f}, Rej={rej_score_val:.0f}, FTA={fta_score_val:.0f})")
                else:
                    failed_extra = []
                    if not h1_ok:
                        failed_extra.append(f"H1={h1_score:.0f}<60")
                    if not rej_ok:
                        failed_extra.append(f"Rej={rej_score_val:.0f}<55")
                    if not fta_ok:
                        failed_extra.append(f"FTA={fta_score_val:.0f}<45")
                    self._record_rejection(self.REJECTION_SELL_EXTRA_CONFIRM_FAILED)
                    logger.info(f"🚫 {asset.value} SELL: {self.REJECTION_SELL_EXTRA_CONFIRM_FAILED} ({', '.join(failed_extra)})")
                    return None
            else:
                self._record_rejection(self.REJECTION_SELL_CONFIDENCE_LOW)
                logger.info(f"🚫 {asset.value} SELL: {self.REJECTION_SELL_CONFIDENCE_LOW} (score={final_score:.0f}% < {self.SELL_MIN_CONFIDENCE})")
                return None
        
        # ========== SIGNAL ACCEPTED - Continue with existing logic ==========
        logger.info(f"✅ {asset.value} {direction}: ACCEPTED via {acceptance_source} (score={final_score:.0f}%)")
        
        # Log component breakdown
        for c in components:
            logger.info(f"   • {c.name}: {c.score:.0f}% × {c.weight}% = {c.weighted_score:.1f}")
        
        # Build FTA object for compatibility with existing code
        fta = self._calculate_fta(
            m5_candles, m15_candles, entry_price, take_profit_1, direction, tp_type
        )
        # ========== GENERATE SIGNAL ==========
        
        signal_id = f"{asset.value}_{direction}_{datetime.utcnow().strftime('%Y%m%d_%H%M%S')}"
        setup_type = self._determine_setup_type(components, sl_type, tp_type)
        
        # ========== SETUP TYPE SOFT FILTER (v3.3) ==========
        # All setups allowed, apply score penalty for non-preferred
        is_allowed, setup_penalty = self._is_allowed_setup(setup_type)
        if setup_penalty > 0:
            logger.info(f"⚠️ {asset.value} {direction}: Setup '{setup_type}' penalty: -{setup_penalty} (soft filter)")
            final_score -= setup_penalty
            # Re-check confidence after penalty
            if final_score < self.MIN_CONFIDENCE_SCORE:
                self._record_rejection("setup_penalty_dropped_score")
                logger.info(f"📉 {asset.value} {direction}: Score dropped to {final_score:.0f}% after setup penalty - Rejected")
                self._log_score_breakdown(asset, direction, components, final_score)
                # Log candidate audit
                self._log_candidate_audit(
                    symbol=asset.value,
                    direction=direction,
                    session=session_name,
                    setup_type=setup_type,
                    decision="rejected",
                    rejection_reason="setup_penalty_dropped_score",
                    rejection_details=f"Score dropped from {final_score + setup_penalty:.0f}% to {final_score:.0f}% after setup penalty ({setup_type})",
                    components=components,
                    final_score=final_score,
                    threshold=self.MIN_CONFIDENCE_SCORE,
                    mtf_score=mtf_score_val,
                    fta=fta,
                    entry_price=entry_price,
                    stop_loss=stop_loss,
                    take_profit=take_profit_1,
                    risk_reward=rr_ratio,
                    setup_penalty=setup_penalty
                )
                return None
        
        sl_formatted = f"{stop_loss:.5f}" if asset == Asset.EURUSD else f"{stop_loss:.2f}"
        invalidation = f"{'Below' if direction == 'BUY' else 'Above'} {sl_formatted}"
        
        # Calculate position size using position_sizer
        position = self.position_sizer.calculate(
            asset=asset,
            entry_price=entry_price,
            stop_loss=stop_loss,
            confidence_score=final_score
        )
        
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
            fta_obstacles_count=fta.obstacles_count,
            # Buffer zone tracking
            acceptance_source=acceptance_source
        )
        
        # ========== DIRECTION QUALITY AUDIT ==========
        
        # Define scores from components for DirectionContext
        # Find momentum from trigger component
        trigger_component = next((c for c in components if "Trigger" in c.name), None)
        mom_score = trigger_component.score if trigger_component else 50
        
        # Structure score from M15
        struct_score = m15_score
        
        # Use M15 as MTF proxy
        mtf_score = mtf_score_val
        
        # Entry score (from entry validation)
        entry_score = 70  # Default since we passed entry validation
        
        # Spread/concentration/regime scores - default values
        spread_score = 100  # Assuming no spread penalty since we passed validation
        conc_score = 100    # Assuming no concentration issue
        regime_score = 60   # Default neutral regime
        
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
        
        # Log ACCEPTED candidate for audit
        self._log_candidate_audit(
            symbol=asset.value,
            direction=direction,
            session=session_name,
            setup_type=setup_type,
            decision="accepted",
            rejection_reason="",
            rejection_details="",
            components=components,
            final_score=final_score,
            threshold=self.MIN_CONFIDENCE_SCORE,
            mtf_score=mtf_score_val,
            fta=fta,
            entry_price=entry_price,
            stop_loss=stop_loss,
            take_profit=take_profit_1,
            risk_reward=rr_ratio,
            news_penalty=news_risk.score_penalty,
            spread_penalty=100 - spread_score
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
        logger.info(f"   Priority: {'HIGH' if signal.confidence_score >= 80 else 'BUFFER' if signal.acceptance_source == 'buffer_zone' else 'NORMAL'}")
        logger.info(f"   Acceptance: {signal.acceptance_source.upper()}")
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
        logger.info("   POSITION SIZING:")
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
            logger.info("   FTA: clean path (no obstacles)")
        logger.info(f"   Session: {signal.session} | Spread: {signal.spread_pips:.1f} pips")
        logger.info("-" * 40)
        logger.info("   TRADE MANAGEMENT (v3.2):")
        logger.info("   • Partial TP: 50% at +0.5R")
        logger.info("   • Move to BE: at +1R")
        logger.info("   • Trailing Stop: after +1R")
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
        """Send push notification with full delivery tracking"""
        from services.production_control import production_control, EngineType
        
        # ===== PIPELINE STAGE: AUTHORIZATION CHECK =====
        authorized, reason = production_control.authorize_notification(
            EngineType.SIGNAL_GENERATOR_V3, 
            signal.signal_id
        )
        if not authorized:
            logger.info(f"📵 [PIPELINE] {signal.signal_id} - BLOCKED at authorization: {reason}")
            self._log_delivery_status(signal.signal_id, "BLOCKED", f"Authorization denied: {reason}")
            return
        
        try:
            from services.device_storage_service import device_storage
            from services.fcm_push_service import fcm_push_service
            
            # ===== PIPELINE STAGE: FCM INITIALIZATION =====
            if not fcm_push_service._initialized:
                init_ok = await fcm_push_service.initialize()
                if not init_ok:
                    logger.error(f"❌ [PIPELINE] {signal.signal_id} - FAILED: FCM service initialization failed")
                    self._log_delivery_status(signal.signal_id, "FAILED", "FCM service initialization failed")
                    return
            
            # ===== PIPELINE STAGE: GET DEVICE TOKENS =====
            tokens = await device_storage.get_active_tokens()
            
            if not tokens:
                logger.warning(f"📭 [PIPELINE] {signal.signal_id} - SKIPPED: No devices registered")
                self._log_delivery_status(signal.signal_id, "SKIPPED", "No devices registered")
                return
            
            # Log token validation
            valid_tokens = 0
            invalid_tokens = 0
            for token in tokens:
                is_test = 'TEST' in token.upper() or 'REAL_TOKEN' in token
                if is_test:
                    invalid_tokens += 1
                else:
                    valid_tokens += 1
            
            if valid_tokens == 0 and invalid_tokens > 0:
                logger.warning(f"⚠️ [PIPELINE] {signal.signal_id} - WARNING: Only test tokens registered ({invalid_tokens} tokens)")
            
            # ===== PIPELINE STAGE: SEND NOTIFICATION =====
            notif = signal.to_notification_dict()
            
            logger.info(f"📤 [PIPELINE] {signal.signal_id} - SENDING to {len(tokens)} device(s)")
            
            results = await fcm_push_service.send_to_all_devices(
                tokens=tokens,
                title=notif['title'],
                body=notif['body'],
                data=notif['data']
            )
            
            # ===== PIPELINE STAGE: PROCESS RESULTS =====
            successful = 0
            failed = 0
            failure_reasons = []
            
            for i, result in enumerate(results):
                if result.success:
                    successful += 1
                    logger.info(f"✅ [PIPELINE] {signal.signal_id} - DELIVERED to device {i+1}")
                else:
                    failed += 1
                    error_str = str(result.error) if result.error else "Unknown error"
                    failure_reasons.append(error_str)
                    logger.error(f"❌ [PIPELINE] {signal.signal_id} - FAILED for device {i+1}: {error_str}")
                    
                    # Remove invalid tokens
                    if any(err in error_str.lower() for err in ["not registered", "invalid", "unregistered", "not a valid"]):
                        await self._remove_invalid_token(tokens[i])
            
            self.notification_count += 1
            
            # ===== PIPELINE STAGE: LOG FINAL STATUS =====
            if successful == len(results):
                logger.info(f"✅ [PIPELINE] {signal.signal_id} - ALL DELIVERED ({successful}/{len(results)})")
                self._log_delivery_status(signal.signal_id, "DELIVERED", f"{successful}/{len(results)} devices")
            elif successful > 0:
                logger.warning(f"⚠️ [PIPELINE] {signal.signal_id} - PARTIAL DELIVERY ({successful}/{len(results)})")
                self._log_delivery_status(signal.signal_id, "PARTIAL", f"{successful}/{len(results)} devices, failures: {failure_reasons[:2]}")
            else:
                logger.error(f"❌ [PIPELINE] {signal.signal_id} - ALL FAILED ({len(results)} attempts)")
                self._log_delivery_status(signal.signal_id, "FAILED", f"All {len(results)} attempts failed: {failure_reasons[:2]}")
            
        except Exception as e:
            logger.error(f"❌ [PIPELINE] {signal.signal_id} - EXCEPTION: {e}")
            self._log_delivery_status(signal.signal_id, "ERROR", str(e))
    
    def _log_delivery_status(self, signal_id: str, status: str, details: str):
        """Log delivery status for audit trail"""
        # This creates a clear audit trail in the logs
        logger.info(f"📋 [DELIVERY AUDIT] {signal_id} | Status: {status} | Details: {details}")
    
    async def _remove_invalid_token(self, token: str):
        """Remove invalid push token"""
        try:
            from services.device_storage_service import device_storage
            await device_storage.deactivate_by_token(token)
            self.invalid_tokens_removed += 1
            logger.info("🧹 Removed invalid push token")
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
        """
        v10.3: Advanced direction analysis - INTRADAY OPTIMIZED
        
        NO HARD BLOCK on H1 trend!
        
        Logic:
        1. H1 trend is SOFT SCORE (not blocking)
        2. M15 trend can compensate weak H1
        3. M5 momentum determines final direction
        4. Counter-trend allowed with penalty
        
        Returns: (direction, confidence_score, reason)
        """
        h1_trend = self._get_trend(h1[-20:]) if len(h1) >= 20 else 0
        m15_trend = self._get_trend(m15[-20:]) if len(m15) >= 20 else 0
        m5_momentum = self._get_momentum(m5[-10:]) if len(m5) >= 10 else 0
        
        # === DEBUG ===
        logger.info(f"📊 [DIRECTION v10.3] H1={h1_trend:.3f}, M15={m15_trend:.3f}, M5={m5_momentum:.3f}")
        
        # v10.3: H1 SOFT SCORE (NON-BLOCKING!)
        h1_abs = abs(h1_trend)
        if h1_abs >= 0.3:
            h1_score = 100
            h1_quality = "strong"
        elif h1_abs >= 0.15:
            h1_score = 70
            h1_quality = "moderate"
        elif h1_abs >= 0.05:
            h1_score = 50
            h1_quality = "weak"
        else:
            h1_score = 35
            h1_quality = "very_weak"
        
        # v10.3: M15 PRIORITY - can compensate weak H1
        m15_abs = abs(m15_trend)
        m15_strong = m15_abs >= 0.25
        
        if m15_strong and h1_score < 70:
            h1_score = max(h1_score, 60)  # Bump up if M15 is strong
            logger.info(f"📊 [DIRECTION v10.3] M15 strong ({m15_abs:.3f}) compensates weak H1 -> score bumped to {h1_score}")
        
        # Determine primary direction from M15 + M5 (intraday focus)
        intraday_bias = m15_trend * 0.6 + m5_momentum * 0.4
        
        logger.info(f"📊 [DIRECTION v10.3] H1_score={h1_score} ({h1_quality}), M15_strong={m15_strong}, intraday_bias={intraday_bias:.3f}")
        
        # v10.3: Direction selection - MORE PERMISSIVE
        direction = None
        confidence = 0
        reason = ""
        counter_trend = False
        
        # BUY conditions (relaxed)
        if intraday_bias > 0.05 or (m5_momentum > 0.15 and m15_trend >= 0):
            direction = "BUY"
            confidence = 50 + (intraday_bias * 100)
            
            # Check if counter-trend to H1
            if h1_trend < -0.1:
                counter_trend = True
                confidence = confidence * 0.88  # 12% penalty
                reason = f"BUY counter-trend (H1 bearish {h1_trend:.2f})"
            else:
                reason = f"BUY aligned (H1={h1_quality}, M15={m15_trend:.2f})"
        
        # SELL conditions (relaxed)
        elif intraday_bias < -0.05 or (m5_momentum < -0.15 and m15_trend <= 0):
            direction = "SELL"
            confidence = 50 + (abs(intraday_bias) * 100)
            
            # Check if counter-trend to H1
            if h1_trend > 0.1:
                counter_trend = True
                confidence = confidence * 0.88  # 12% penalty
                reason = f"SELL counter-trend (H1 bullish {h1_trend:.2f})"
            else:
                reason = f"SELL aligned (H1={h1_quality}, M15={m15_trend:.2f})"
        
        # v10.3: Even with very weak bias, allow if M5 is decisive
        elif abs(m5_momentum) > 0.25:
            direction = "BUY" if m5_momentum > 0 else "SELL"
            confidence = 45
            reason = f"{direction} from M5 momentum ({m5_momentum:.2f})"
        
        if direction:
            # Cap confidence and apply H1 quality modifier
            confidence = min(confidence, 95)
            if h1_quality == "very_weak":
                confidence = confidence * 0.9
            
            logger.info(f"✅ [DIRECTION v10.3] {direction} chosen - conf={confidence:.0f}%, counter_trend={counter_trend}, {reason}")
            return direction, confidence, reason
        
        # Last resort: use M5 direction if any movement
        if m5_momentum > 0.05:
            logger.info(f"✅ [DIRECTION v10.3] BUY fallback from M5 ({m5_momentum:.3f})")
            return "BUY", 40, "M5 micro-momentum bullish"
        elif m5_momentum < -0.05:
            logger.info(f"✅ [DIRECTION v10.3] SELL fallback from M5 ({m5_momentum:.3f})")
            return "SELL", 40, "M5 micro-momentum bearish"
        
        logger.info(f"❌ [DIRECTION v10.3] No direction - all signals flat")
        return None, 0, "Market flat - no clear direction"
    
    def _fallback_direction(self, m5: List) -> Optional[str]:
        """
        v10.0: Fallback direction from M5 - BUY + SELL BOTH ENABLED
        
        Simple momentum check on last 5 candles.
        """
        if len(m5) < 5:
            logger.info("❌ [FALLBACK] Insufficient M5 candles")
            return None
        
        closes = [c.get('close', 0) for c in m5[-5:]]
        change_pct = (closes[-1] - closes[0]) / closes[0] if closes[0] > 0 else 0
        
        logger.info(f"📊 [FALLBACK DEBUG] M5 closes: first={closes[0]:.5f}, last={closes[-1]:.5f}, change={change_pct*100:.3f}%")
        
        if closes[-1] > closes[0] * 1.0003:
            logger.info(f"✅ [FALLBACK] BUY chosen (change={change_pct*100:.3f}% > 0.03%)")
            return "BUY"
        elif closes[-1] < closes[0] * 0.9997:
            logger.info(f"✅ [FALLBACK] SELL chosen (change={change_pct*100:.3f}% < -0.03%)")
            return "SELL"
        
        logger.info(f"❌ [FALLBACK] No direction - change too small ({change_pct*100:.3f}%)")
        return None
    
    # ==================== v10.0 NEW SCORING FUNCTIONS ====================
    
    def _score_h1_structural_bias(self, h1: List, direction: str) -> Tuple[float, str]:
        """
        v10.0: H1 Structural Bias scoring
        
        Uses EMA20, EMA50, swing points to determine structural bias.
        
        BUY conditions (all must be true for 100):
        1. Last swing high > previous swing high
        2. Last swing low > previous swing low
        3. Close > EMA20
        4. EMA20 > EMA50
        5. EMA20 slope positive
        
        SELL conditions (all must be true for 100):
        1. Last swing high < previous swing high
        2. Last swing low < previous swing low
        3. Close < EMA20
        4. EMA20 < EMA50
        5. EMA20 slope negative
        """
        if len(h1) < 50:
            logger.info(f"📊 [H1 STRUCTURAL DEBUG] Insufficient data ({len(h1)} < 50)")
            return 50, "Insufficient H1 data"
        
        # Calculate EMAs using helper
        ema20 = calculate_ema(h1, 20)
        ema50 = calculate_ema(h1, 50)
        ema20_slope = calculate_ema_slope(h1, 20, lookback=5)
        
        # Get current price
        current_price = h1[-1].get('close', 0)
        
        # Get swing points
        swing_highs = get_recent_swing_highs(h1[-30:], count=3, lookback=2)
        swing_lows = get_recent_swing_lows(h1[-30:], count=3, lookback=2)
        
        # === DEBUG H1 STRUCTURAL BIAS ===
        logger.info(f"📊 [H1 STRUCTURAL DEBUG] Direction={direction}")
        logger.info(f"📊 [H1 STRUCTURAL DEBUG] close={current_price:.5f}, EMA20={ema20:.5f}, EMA50={ema50:.5f}")
        logger.info(f"📊 [H1 STRUCTURAL DEBUG] EMA20_slope={ema20_slope:.4f}")
        logger.info(f"📊 [H1 STRUCTURAL DEBUG] swing_highs_count={len(swing_highs)}, swing_lows_count={len(swing_lows)}")
        
        if len(swing_highs) >= 2:
            logger.info(f"📊 [H1 STRUCTURAL DEBUG] last_2_swing_highs: {[sh.price for sh in swing_highs[-2:]]}")
        if len(swing_lows) >= 2:
            logger.info(f"📊 [H1 STRUCTURAL DEBUG] last_2_swing_lows: {[sl.price for sl in swing_lows[-2:]]}")
        
        conditions_met = 0
        conditions_bullish = []
        conditions_bearish = []
        details = []
        
        if direction == "BUY":
            # Condition 1: HH (Higher Highs)
            if len(swing_highs) >= 2 and swing_highs[-1].price > swing_highs[-2].price:
                conditions_met += 1
                details.append("HH")
            
            # Condition 2: HL (Higher Lows)
            if len(swing_lows) >= 2 and swing_lows[-1].price > swing_lows[-2].price:
                conditions_met += 1
                details.append("HL")
            
            # Condition 3: Price > EMA20
            if current_price > ema20:
                conditions_met += 1
                details.append("P>EMA20")
            
            # Condition 4: EMA20 > EMA50
            if ema20 > ema50:
                conditions_met += 1
                details.append("EMA20>50")
            
            # Condition 5: EMA20 slope positive
            if ema20_slope > 0:
                conditions_met += 1
                details.append("Slope+")
        else:  # SELL
            # Condition 1: LH (Lower Highs)
            if len(swing_highs) >= 2 and swing_highs[-1].price < swing_highs[-2].price:
                conditions_met += 1
                details.append("LH")
            
            # Condition 2: LL (Lower Lows)
            if len(swing_lows) >= 2 and swing_lows[-1].price < swing_lows[-2].price:
                conditions_met += 1
                details.append("LL")
            
            # Condition 3: Price < EMA20
            if current_price < ema20:
                conditions_met += 1
                details.append("P<EMA20")
            
            # Condition 4: EMA20 < EMA50
            if ema20 < ema50:
                conditions_met += 1
                details.append("EMA20<50")
            
            # Condition 5: EMA20 slope negative
            if ema20_slope < 0:
                conditions_met += 1
                details.append("Slope-")
        
        # Score mapping
        score_map = {5: 100, 4: 85, 3: 70, 2: 50, 1: 30, 0: 30}
        score = score_map.get(conditions_met, 30)
        reason = f"H1 Structural {conditions_met}/5 ({', '.join(details)})"
        
        # === DEBUG H1 FINAL SCORE ===
        logger.info(f"📊 [H1 STRUCTURAL DEBUG] conditions_met={conditions_met}/5, details={details}")
        logger.info(f"📊 [H1 STRUCTURAL DEBUG] FINAL: score={score}, direction={direction}")
        
        return score, reason
    
    def _score_m15_structure_quality(self, m15: List, direction: str) -> Tuple[float, str]:
        """
        v10.0: M15 Structure Quality scoring
        
        Evaluates structure quality on M15:
        - HH + HL sequence (BUY) or LH + LL sequence (SELL)
        - Price vs EMA20
        - No broken swing in last 8 candles
        """
        if len(m15) < 40:
            return 50, "Insufficient M15 data"
        
        ema20 = calculate_ema(m15, 20)
        swing_highs = get_recent_swing_highs(m15[-40:], count=3, lookback=2)
        swing_lows = get_recent_swing_lows(m15[-40:], count=3, lookback=2)
        
        current_price = m15[-1].get('close', 0)
        
        conditions_met = 0
        details = []
        
        if direction == "BUY":
            # Condition 1: HH + HL sequence
            has_hh = len(swing_highs) >= 2 and swing_highs[-1].price > swing_highs[-2].price
            has_hl = len(swing_lows) >= 2 and swing_lows[-1].price > swing_lows[-2].price
            if has_hh and has_hl:
                conditions_met += 1
                details.append("HH+HL")
            elif has_hh or has_hl:
                details.append("Partial structure")
            
            # Condition 2: Price above EMA20
            if current_price > ema20:
                conditions_met += 1
                details.append("P>EMA20")
            
            # Condition 3: No broken swing low in last 8 candles
            if len(swing_lows) >= 1:
                last_swing_low = swing_lows[-1].price
                recent_lows = [c.get('low', float('inf')) for c in m15[-8:]]
                if min(recent_lows) >= last_swing_low * 0.9995:  # Small buffer
                    conditions_met += 1
                    details.append("SL intact")
        else:  # SELL
            # Condition 1: LH + LL sequence
            has_lh = len(swing_highs) >= 2 and swing_highs[-1].price < swing_highs[-2].price
            has_ll = len(swing_lows) >= 2 and swing_lows[-1].price < swing_lows[-2].price
            if has_lh and has_ll:
                conditions_met += 1
                details.append("LH+LL")
            elif has_lh or has_ll:
                details.append("Partial structure")
            
            # Condition 2: Price below EMA20
            if current_price < ema20:
                conditions_met += 1
                details.append("P<EMA20")
            
            # Condition 3: No broken swing high in last 8 candles
            if len(swing_highs) >= 1:
                last_swing_high = swing_highs[-1].price
                recent_highs = [c.get('high', 0) for c in m15[-8:]]
                if max(recent_highs) <= last_swing_high * 1.0005:  # Small buffer
                    conditions_met += 1
                    details.append("SH intact")
        
        # Score mapping
        score_map = {3: 100, 2: 80, 1: 65, 0: 25}
        score = score_map.get(conditions_met, 25)
        reason = f"M15 Structure {conditions_met}/3 ({', '.join(details)})"
        
        return score, reason
    
    def _score_m5_trigger_quality(self, m5: List, direction: str) -> Tuple[float, str]:
        """
        v10.2: M5 Trigger Quality scoring - RELAXED
        
        BUY triggers:
        A. Break-and-hold: M5 close breaks micro high, holds for 1 candle
        B. Reclaim: M5 dips below EMA20, reclaims (NO double confirm needed)
        C. Continuation: 1 strong bullish candle (range >= 0.6 * avg_range)
        
        SELL triggers:
        A. Rejection: Upper wick >= 25% (was 35%), close in bottom 40% (was 35%)
        B. Failed push: New micro high negated within 3 candles (was 2)
        C. Continuation short: 1 strong bearish candle
        """
        if len(m5) < 15:
            logger.info(f"📊 [M5 TRIGGER DEBUG] Insufficient M5 data ({len(m5)} < 15)")
            return 30, "Insufficient M5 data"
        
        ema20 = calculate_ema(m5, 20)
        recent = m5[-15:]
        last_3 = m5[-3:]
        last_5 = m5[-5:]
        
        # Calculate average range for "strong candle" definition
        ranges = [c.get('high', 0) - c.get('low', 0) for c in last_5]
        avg_range = sum(ranges) / len(ranges) if ranges else 0
        
        trigger_found = False
        trigger_strength = 0
        trigger_type = ""
        patterns_checked = []
        
        if direction == "BUY":
            # Pattern A: Break-and-hold (unchanged)
            pattern_a_found = False
            if len(recent) >= 10:
                micro_highs = [c.get('high', 0) for c in recent[-10:-2]]
                if micro_highs:
                    highest_micro = max(micro_highs)
                    close_n2 = last_3[-2].get('close', 0)
                    close_n1 = last_3[-1].get('close', 0)
                    if close_n2 > highest_micro and close_n1 > highest_micro:
                        trigger_found = True
                        trigger_strength = 95
                        trigger_type = "Break-and-hold"
                        pattern_a_found = True
                    patterns_checked.append(f"Break-hold(found={pattern_a_found})")
            
            # Pattern B: Reclaim - SIMPLIFIED v10.2
            # Was: below_ema AND current_above AND current_bullish
            # Now: below_ema AND current_above (no bullish required)
            pattern_b_found = False
            if not trigger_found and len(last_5) >= 3:
                below_ema = any(c.get('low', float('inf')) < ema20 for c in last_5[:-1])
                current_above = last_3[-1].get('close', 0) > ema20
                if below_ema and current_above:
                    trigger_found = True
                    trigger_strength = 75  # Slightly lower since no bullish confirm
                    trigger_type = "EMA20 Reclaim"
                    pattern_b_found = True
                patterns_checked.append(f"Reclaim(below={below_ema}, above={current_above}, found={pattern_b_found})")
            
            # Pattern C: Continuation - SUPER RELAXED v10.2
            # Now: Just need 1 strong bullish candle (range >= 0.6 * avg)
            pattern_c_found = False
            if not trigger_found:
                last_candle = last_3[-1]
                candle_range = last_candle.get('high', 0) - last_candle.get('low', 0)
                is_strong = candle_range >= 0.6 * avg_range if avg_range > 0 else False
                is_bullish = is_bullish_candle(last_candle)
                
                if is_bullish and is_strong:
                    trigger_found = True
                    trigger_strength = 65
                    trigger_type = "Strong bullish continuation"
                    pattern_c_found = True
                elif is_bullish:
                    # Even weak bullish gives minimum trigger
                    trigger_found = True
                    trigger_strength = 55
                    trigger_type = "Bullish continuation"
                    pattern_c_found = True
                patterns_checked.append(f"Continuation(bullish={is_bullish}, strong={is_strong}, found={pattern_c_found})")
        
        else:  # SELL
            # Pattern A: Rejection - RELAXED v10.2
            # Was: wick >= 35%, close in bottom 35%
            # Now: wick >= 25%, close in bottom 40%
            pattern_a_found = False
            for candle in last_3:
                candle_range = candle.get('high', 0) - candle.get('low', 0)
                if candle_range > 0:
                    upper_wick = candle.get('high', 0) - max(candle.get('open', 0), candle.get('close', 0))
                    wick_ratio = upper_wick / candle_range
                    close_pos = get_close_position_in_range(candle)
                    
                    # v10.2: Relaxed from 0.35/0.35 to 0.25/0.40
                    if wick_ratio >= 0.25 and close_pos <= 0.40:
                        trigger_found = True
                        # Score based on quality
                        if wick_ratio >= 0.35 and close_pos <= 0.30:
                            trigger_strength = 90
                            trigger_type = "Strong rejection"
                        else:
                            trigger_strength = 70
                            trigger_type = "Rejection"
                        pattern_a_found = True
                        break
            patterns_checked.append(f"Rejection(found={pattern_a_found})")
            
            # Pattern B: Failed push - RELAXED v10.2
            # Now: Allow 3 candles lookback (was 2)
            pattern_b_found = False
            if not trigger_found and len(recent) >= 10:
                micro_highs = [c.get('high', 0) for c in recent[-10:-4]]  # Changed from -3 to -4
                if micro_highs:
                    highest_micro = max(micro_highs)
                    # Check last 4 candles for failed push (was 3)
                    for i in range(-4, 0):
                        if recent[i].get('high', 0) > highest_micro:
                            subsequent = recent[i+1:] if i < -1 else []
                            if subsequent and all(c.get('close', float('inf')) < highest_micro for c in subsequent):
                                trigger_found = True
                                trigger_strength = 75
                                trigger_type = "Failed push"
                                pattern_b_found = True
                                break
            patterns_checked.append(f"Failed-push(found={pattern_b_found})")
            
            # Pattern C: Continuation short - SUPER RELAXED v10.2
            # Now: Just need 1 strong bearish candle
            pattern_c_found = False
            if not trigger_found:
                last_candle = last_3[-1]
                candle_range = last_candle.get('high', 0) - last_candle.get('low', 0)
                is_strong = candle_range >= 0.6 * avg_range if avg_range > 0 else False
                is_bearish = is_bearish_candle(last_candle)
                
                if is_bearish and is_strong:
                    trigger_found = True
                    trigger_strength = 65
                    trigger_type = "Strong bearish continuation"
                    pattern_c_found = True
                elif is_bearish:
                    # Even weak bearish gives minimum trigger
                    trigger_found = True
                    trigger_strength = 55
                    trigger_type = "Bearish continuation"
                    pattern_c_found = True
                patterns_checked.append(f"Continuation-short(bearish={is_bearish}, strong={is_strong}, found={pattern_c_found})")
        
        # === DEBUG M5 TRIGGER FINAL ===
        logger.info(f"📊 [M5 TRIGGER DEBUG] Direction={direction}, trigger_found={trigger_found}")
        logger.info(f"📊 [M5 TRIGGER DEBUG] patterns: {patterns_checked}")
        
        if trigger_found:
            logger.info(f"📊 [M5 TRIGGER DEBUG] ✅ TRIGGER: {trigger_type}, strength={trigger_strength}")
            return trigger_strength, f"Trigger: {trigger_type}"
        logger.info(f"📊 [M5 TRIGGER DEBUG] ❌ NO TRIGGER: score=30")
        return 30, "No clear trigger"
    
    def _score_pullback_quality_v10(self, asset: Asset, m15: List, m5: List, direction: str, current_price: float) -> Tuple[float, str, bool]:
        """
        v10.0: Pullback Quality scoring
        
        Returns: (score, reason, is_valid)
        is_valid = False means reject the signal
        
        Measures:
        1. Impulse leg size (must meet minimum)
        2. Pullback depth (38.2%-61.8% ideal)
        3. Reaction present (M5 candle in direction)
        """
        if len(m15) < 30:
            return 50, "Insufficient data", True
        
        # Find impulse leg on M15
        swing_highs = get_recent_swing_highs(m15[-30:], count=2, lookback=2)
        swing_lows = get_recent_swing_lows(m15[-30:], count=2, lookback=2)
        
        if direction == "BUY":
            if len(swing_lows) < 1 or len(swing_highs) < 1:
                return 50, "No clear impulse", True
            
            # Impulse leg: last swing low -> last swing high
            impulse_low = min(s.price for s in swing_lows)
            impulse_high = max(s.price for s in swing_highs)
            impulse_size = impulse_high - impulse_low
            
            # Check minimum impulse size
            if asset == Asset.EURUSD:
                if impulse_size < self.EURUSD_IMPULSE_MIN:
                    return 0, f"Impulse too small ({impulse_size*10000:.1f}p < 12p)", False
            else:  # XAUUSD
                if impulse_size < self.XAUUSD_IMPULSE_MIN:
                    return 0, f"Impulse too small (${impulse_size:.1f} < $4)", False
            
            # Calculate pullback depth
            pullback = impulse_high - current_price
            depth = pullback / impulse_size if impulse_size > 0 else 0
            
        else:  # SELL
            if len(swing_lows) < 1 or len(swing_highs) < 1:
                return 50, "No clear impulse", True
            
            # Impulse leg: last swing high -> last swing low
            impulse_high = max(s.price for s in swing_highs)
            impulse_low = min(s.price for s in swing_lows)
            impulse_size = impulse_high - impulse_low
            
            # Check minimum impulse size
            if asset == Asset.EURUSD:
                if impulse_size < self.EURUSD_IMPULSE_MIN:
                    return 0, f"Impulse too small ({impulse_size*10000:.1f}p < 12p)", False
            else:  # XAUUSD
                if impulse_size < self.XAUUSD_IMPULSE_MIN:
                    return 0, f"Impulse too small (${impulse_size:.1f} < $4)", False
            
            # Calculate pullback depth (bounce up for SELL)
            pullback = current_price - impulse_low
            depth = pullback / impulse_size if impulse_size > 0 else 0
        
        # Score based on Fibonacci zones
        if 0.382 <= depth <= 0.618:
            base_score = 100
            zone = "Ideal Fib (38-62%)"
        elif 0.25 <= depth <= 0.75:
            base_score = 80
            zone = "Good zone (25-75%)"
        elif depth < 0.25:
            base_score = 60
            zone = "Shallow pullback"
        else:
            base_score = 35
            zone = "Too deep (>75%)"
        
        # Check for reaction (M5 candle in direction)
        if len(m5) >= 3:
            last_m5 = m5[-1]
            if direction == "BUY" and is_bullish_candle(last_m5):
                base_score = min(100, base_score + 8)
                zone += " + reaction"
            elif direction == "SELL" and is_bearish_candle(last_m5):
                base_score = min(100, base_score + 8)
                zone += " + reaction"
        
        return base_score, f"Pullback: {zone} ({depth*100:.0f}%)", True
    
    def _score_fta_clean_space_v10(self, asset: Asset, m15: List, m5: List, entry_price: float, 
                                   take_profit: float, direction: str, trigger_score: float = 50) -> Tuple[float, str, bool]:
        """
        v10.4: FTA / Clean Space scoring - DYNAMIC ATR-BASED
        
        FTA = First Trouble Area between entry and TP
        
        NEW v10.4:
        - FTA minimum based on ATR_M5 (not fixed threshold)
        - EURUSD: FTA_min = max(5 pips, 0.8 * ATR_M5)
        - XAUUSD: FTA_min = max(50 pips, 0.8 * ATR_M5)
        - Exception: if trigger_score >= 70, allow FTA >= 35% of minimum
        - clean_space_ratio < 0.30 = HARD REJECT
        
        Returns: (score, reason, is_valid)
        is_valid = False if FTA too close or clean_space < 0.30
        """
        # Calculate ATR_M5
        atr_m5 = calculate_atr(m5, 14) if len(m5) >= 14 else 0
        
        # v10.5: Dynamic FTA minimum based on ATR - RELAXED
        # ATR multiplier reduced from 0.8 to 0.3 to allow more signals
        if asset == Asset.EURUSD:
            pip_multiplier = 10000
            min_pips = 3  # Reduced from 5
            fta_min_dynamic = max(min_pips / pip_multiplier, 0.3 * atr_m5)  # 0.3 instead of 0.8
        else:  # XAUUSD
            pip_multiplier = 100
            min_pips = 30  # Reduced from 50
            fta_min_dynamic = max(min_pips / pip_multiplier, 0.3 * atr_m5)  # 0.3 instead of 0.8
        
        # Exception for strong triggers
        if trigger_score >= 70:
            fta_min_dynamic = fta_min_dynamic * 0.35  # Allow closer FTA with strong trigger
        
        # Find FTA (first obstacle) - IMPROVED DETECTION
        fta_price = None
        fta_type = "none"
        tp_distance = abs(take_profit - entry_price)
        
        if tp_distance == 0:
            return 50, "No TP distance", True
        
        # 1. Swing points (lookback 5 as requested)
        swing_highs_m5 = get_recent_swing_highs(m5[-30:], count=5, lookback=2)
        swing_lows_m5 = get_recent_swing_lows(m5[-30:], count=5, lookback=2)
        swing_highs_m15 = get_recent_swing_highs(m15[-30:], count=3, lookback=2)
        swing_lows_m15 = get_recent_swing_lows(m15[-30:], count=3, lookback=2)
        
        # 2. Wick rejection zones - DISABLED in v10.5 (too restrictive)
        # These were causing almost all signals to be rejected
        wick_zones = []  # Disabled for now
        # for candle in m5[-20:]:
        #     candle_range = candle.get('high', 0) - candle.get('low', 0)
        #     if candle_range > 0:
        #         upper_wick = candle.get('high', 0) - max(candle.get('open', 0), candle.get('close', 0))
        #         lower_wick = min(candle.get('open', 0), candle.get('close', 0)) - candle.get('low', 0)
        #         
        #         if upper_wick / candle_range >= 0.40:
        #             wick_zones.append(candle.get('high', 0))
        #         if lower_wick / candle_range >= 0.40:
        #             wick_zones.append(candle.get('low', 0))
        
        # 3. Touch zones (>= 2 touches in last 20 candles)
        touch_zones = self._find_touch_zones(m5[-20:], tolerance=atr_m5 * 0.3 if atr_m5 > 0 else 0.0001)
        
        obstacles = []
        
        if direction == "BUY":
            # FTA = first resistance above entry
            for sh in swing_highs_m15 + swing_highs_m5:
                if entry_price < sh.price < take_profit:
                    obstacles.append((sh.price, "swing_high"))
            
            for wz in wick_zones:
                if entry_price < wz < take_profit:
                    obstacles.append((wz, "wick_rejection"))
            
            for tz in touch_zones:
                if entry_price < tz < take_profit:
                    obstacles.append((tz, "touch_zone"))
            
            # Round numbers
            if asset == Asset.EURUSD:
                round_step = 0.005
                start = int(entry_price * 1000) / 1000
                for r in range(1, 10):
                    round_level = start + r * round_step
                    if entry_price < round_level < take_profit:
                        obstacles.append((round_level, "round_number"))
            else:
                round_step = 10.0
                start = int(entry_price / 10) * 10
                for r in range(1, 10):
                    round_level = start + r * round_step
                    if entry_price < round_level < take_profit:
                        obstacles.append((round_level, "round_number"))
            
            if obstacles:
                obstacles.sort(key=lambda x: x[0])
                fta_price, fta_type = obstacles[0]
                fta_distance = fta_price - entry_price
            else:
                fta_distance = tp_distance  # No FTA = clean
                
        else:  # SELL
            # FTA = first support below entry
            for sl in swing_lows_m15 + swing_lows_m5:
                if take_profit < sl.price < entry_price:
                    obstacles.append((sl.price, "swing_low"))
            
            for wz in wick_zones:
                if take_profit < wz < entry_price:
                    obstacles.append((wz, "wick_rejection"))
            
            for tz in touch_zones:
                if take_profit < tz < entry_price:
                    obstacles.append((tz, "touch_zone"))
            
            # Round numbers
            if asset == Asset.EURUSD:
                round_step = 0.005
                start = int(entry_price * 1000) / 1000
                for r in range(1, 10):
                    round_level = start - r * round_step
                    if take_profit < round_level < entry_price:
                        obstacles.append((round_level, "round_number"))
            else:
                round_step = 10.0
                start = int(entry_price / 10) * 10
                for r in range(1, 10):
                    round_level = start - r * round_step
                    if take_profit < round_level < entry_price:
                        obstacles.append((round_level, "round_number"))
            
            if obstacles:
                obstacles.sort(key=lambda x: -x[0])  # Highest first for SELL
                fta_price, fta_type = obstacles[0]
                fta_distance = entry_price - fta_price
            else:
                fta_distance = tp_distance
        
        # Calculate clean space ratio
        clean_space_ratio = fta_distance / tp_distance if tp_distance > 0 else 0
        
        # Calculate distance in pips for logging
        fta_distance_pips = fta_distance * pip_multiplier
        tp_distance_pips = tp_distance * pip_multiplier
        atr_m5_pips = atr_m5 * pip_multiplier
        fta_min_pips = fta_min_dynamic * pip_multiplier
        
        # === v10.4 STRUCTURED AUDIT LOG ===
        fta_audit = {
            "symbol": asset.value,
            "direction": direction,
            "atr_m5_pips": round(atr_m5_pips, 1),
            "fta_min_pips": round(fta_min_pips, 1),
            "fta_distance_pips": round(fta_distance_pips, 1),
            "tp_distance_pips": round(tp_distance_pips, 1),
            "clean_space_ratio": round(clean_space_ratio, 3),
            "fta_type": fta_type,
            "trigger_score": trigger_score,
            "trigger_exception_applied": trigger_score >= 70,
            "entry_price": entry_price,
            "take_profit": take_profit
        }
        
        # === LOGGING (as requested) ===
        logger.info(f"📊 [FTA v10.4] {asset.value} {direction}")
        logger.info(f"📊 [FTA v10.4] ATR_M5={atr_m5_pips:.1f}p, FTA_min={fta_min_pips:.1f}p (trigger={trigger_score:.0f})")
        logger.info(f"📊 [FTA v10.4] FTA_distance={fta_distance_pips:.1f}p, TP_distance={tp_distance_pips:.1f}p")
        logger.info(f"📊 [FTA v10.4] clean_space_ratio={clean_space_ratio:.2f}, fta_type={fta_type}")
        
        # v10.5 BALANCED: SOFT REJECT with reasonable threshold
        # Wick rejection DISABLED (too sensitive)
        # Clean space threshold: 15% (balanced between quality and quantity)
        if clean_space_ratio < 0.15:
            fta_audit["decision"] = "HARD_REJECT"
            fta_audit["rejection_reason"] = "LOW_CLEAN_SPACE"
            logger.info(f"🚫 [FTA v10.5] HARD REJECT: clean_space {clean_space_ratio*100:.0f}% < 15%")
            logger.info(f"📋 [FTA AUDIT] {json.dumps(fta_audit)}")
            return 0, f"FTA blocked (clean space {clean_space_ratio*100:.0f}% < 15%)", False
        
        # v10.4: Check dynamic FTA minimum
        if fta_distance < fta_min_dynamic and fta_type != "none":
            if trigger_score >= 70:
                # Strong trigger exception - allow but penalize
                logger.info(f"⚠️ [FTA v10.4] FTA close but strong trigger - allowing with penalty")
                score = 40
                reason = f"FTA close ({fta_distance_pips:.1f}p < {fta_min_pips:.1f}p) but strong trigger"
            else:
                logger.info(f"🚫 [FTA v10.4] REJECT: FTA {fta_distance_pips:.1f}p < min {fta_min_pips:.1f}p")
                return 25, f"FTA too close ({fta_distance_pips:.1f}p < {fta_min_pips:.1f}p)", False
        else:
            # Score based on clean space
            if clean_space_ratio >= 0.80:
                score = 100
                reason = f"Excellent clean space ({clean_space_ratio*100:.0f}%)"
            elif clean_space_ratio >= 0.65:
                score = 80
                reason = f"Good clean space ({clean_space_ratio*100:.0f}%)"
            elif clean_space_ratio >= 0.50:
                score = 60
                reason = f"Moderate clean space ({clean_space_ratio*100:.0f}%)"
            elif clean_space_ratio >= 0.30:
                score = 45 - int((0.50 - clean_space_ratio) * 30)  # 30-50% gets penalty
                reason = f"Limited clean space ({clean_space_ratio*100:.0f}%) - penalty applied"
            else:
                score = 25
                reason = f"Very limited clean space ({clean_space_ratio*100:.0f}%)"
        
        # Bonus for very clean space
        if clean_space_ratio >= 0.80 and fta_type == "none":
            score = min(100, score + 3)
            reason += " (+3 bonus)"
        
        return score, reason, True
    
    def _find_touch_zones(self, candles: List, tolerance: float) -> List[float]:
        """Find price levels with >= 2 touches"""
        if len(candles) < 5:
            return []
        
        levels = []
        for c in candles:
            levels.extend([c.get('high', 0), c.get('low', 0)])
        
        # Group similar levels
        touch_zones = []
        for level in levels:
            touches = sum(1 for l in levels if abs(l - level) <= tolerance)
            if touches >= 2:
                # Check if not already in list
                if not any(abs(tz - level) <= tolerance for tz in touch_zones):
                    touch_zones.append(level)
        
        return touch_zones
    
    def _score_directional_continuation(self, m15: List, m5: List, direction: str) -> Tuple[float, str]:
        """
        v10.0: Directional Continuation scoring (BUY ONLY)
        
        Conditions:
        1. Close M15 above EMA20 M15
        2. No close M15 below last HL
        3. M5 shows resumption after pullback
        4. Last 3 M5 highs are increasing
        """
        if direction != "BUY":
            return 0, "Not applicable (SELL)"
        
        if len(m15) < 20 or len(m5) < 15:
            return 50, "Insufficient data"
        
        ema20_m15 = calculate_ema(m15, 20)
        swing_lows_m15 = get_recent_swing_lows(m15[-20:], count=2, lookback=2)
        
        conditions_met = 0
        details = []
        
        # Condition 1: Close M15 above EMA20
        if m15[-1].get('close', 0) > ema20_m15:
            conditions_met += 1
            details.append("M15>EMA")
        
        # Condition 2: No close below last HL
        if len(swing_lows_m15) >= 1:
            last_hl = swing_lows_m15[-1].price
            recent_closes = [c.get('close', float('inf')) for c in m15[-8:]]
            if min(recent_closes) > last_hl:
                conditions_met += 1
                details.append("HL intact")
        
        # Condition 3: M5 resumption (bullish after pullback)
        last_5_m5 = m5[-5:]
        bullish_count = sum(1 for c in last_5_m5 if is_bullish_candle(c))
        if bullish_count >= 3:
            conditions_met += 1
            details.append("M5 resume")
        
        # Condition 4: Last 3 M5 highs increasing
        last_3_highs = [c.get('high', 0) for c in m5[-3:]]
        if len(last_3_highs) == 3 and last_3_highs[2] > last_3_highs[1] > last_3_highs[0]:
            conditions_met += 1
            details.append("HH M5")
        
        score_map = {4: 100, 3: 80, 2: 60, 1: 35, 0: 35}
        score = score_map.get(conditions_met, 35)
        reason = f"Continuation {conditions_met}/4 ({', '.join(details)})"
        
        return score, reason
    
    def _score_rejection_failed_push(self, m15: List, m5: List, direction: str) -> Tuple[float, str, bool]:
        """
        v10.0: Rejection / Failed Push Quality scoring (SELL ONLY)
        
        Pattern A - Rejection wick:
        - M5 candle with upper wick >= 35% of range
        - Close in bottom 35%
        - Next candle bearish
        
        Pattern B - Failed push:
        - Price breaks micro high
        - Within 2 M5 candles closes below that level
        - Next candle closes below low of break candle
        
        Returns: (score, reason, is_valid)
        is_valid = False if score < 60 for SELL
        """
        if direction != "SELL":
            return 0, "Not applicable (BUY)", True
        
        if len(m5) < 12:
            return 30, "Insufficient M5 data", False
        
        pattern_found = False
        pattern_score = 0
        pattern_name = ""
        
        # Pattern A: Rejection wick
        for i in range(-4, -1):
            candle = m5[i]
            candle_range = get_candle_range(candle)
            if candle_range == 0:
                continue
            
            upper_wick = get_upper_wick(candle)
            wick_ratio = upper_wick / candle_range
            close_pos = get_close_position_in_range(candle)
            
            if wick_ratio >= 0.35 and close_pos <= 0.35:
                # Check confirmation
                if i < -1:
                    next_candle = m5[i + 1]
                    if is_bearish_candle(next_candle):
                        pattern_found = True
                        pattern_score = 100
                        pattern_name = "Rejection + confirm"
                        break
                else:
                    pattern_found = True
                    pattern_score = 80
                    pattern_name = "Rejection"
                    break
        
        # Pattern B: Failed push
        if not pattern_found:
            recent_highs = [c.get('high', 0) for c in m5[-12:-3]]
            if recent_highs:
                prev_high = max(recent_highs)
                
                for i in range(-3, 0):
                    if m5[i].get('high', 0) > prev_high:
                        # Found new high - check if failed
                        idx = len(m5) + i
                        subsequent = m5[idx+1:] if idx < len(m5) - 1 else []
                        
                        if subsequent:
                            all_below = all(c.get('close', float('inf')) < prev_high for c in subsequent)
                            if all_below:
                                pattern_found = True
                                pattern_score = 80
                                pattern_name = "Failed push"
                                break
        
        # Pattern C: Simple continuation (weaker)
        if not pattern_found:
            last_3 = m5[-3:]
            if len(last_3) >= 2:
                c1_bearish = is_bearish_candle(last_3[-2])
                c2_bearish = is_bearish_candle(last_3[-1])
                c2_lower = last_3[-1].get('close', 0) < last_3[-2].get('low', 0)
                if c1_bearish and c2_bearish:
                    pattern_found = True
                    pattern_score = 60
                    pattern_name = "Bearish continuation"
        
        if pattern_found:
            is_valid = pattern_score >= 60
            return pattern_score, f"SELL trigger: {pattern_name}", is_valid
        
        return 30, "No SELL rejection pattern", False
    
    def _score_session_quality_v10(self, direction: str) -> Tuple[float, str]:
        """
        v10.0: Session Quality scoring
        
        Sessions (UTC):
        - London: 07:00-12:59
        - Overlap: 13:00-16:00
        - NY: 16:01-20:00
        - Asian/Other: rest
        """
        hour = datetime.utcnow().hour
        
        # Determine session
        if 13 <= hour <= 16:
            session = "Overlap"
        elif 7 <= hour <= 12:
            session = "London"
        elif 16 < hour <= 20:
            session = "NY"
        else:
            session = "Asian/Other"
        
        if direction == "BUY":
            # BUY session scores
            if session == "Overlap":
                return 100, "Overlap session"
            elif session == "NY":
                return 90, "NY session"
            elif session == "London":
                return 85, "London session"
            else:
                return 40, "Asian/Other session"
        else:  # SELL
            # SELL session scores
            if session == "Overlap":
                return 100, "Overlap session"
            elif session == "London":
                return 65, "London session"
            elif session == "NY":
                return 60, "NY session"
            else:
                return 20, "Asian/Other session"
    
    def _score_market_sanity_check(self, asset: Asset, m5: List) -> Tuple[float, str, bool]:
        """
        v10.0: Market Sanity Check
        
        Replaces old regime/volatility scoring.
        
        Checks:
        - ATR not too low (market dead)
        - ATR not too high (chaos)
        - No unconfirmed spikes
        
        Returns: (score, reason, is_valid)
        is_valid = False means reject
        """
        if len(m5) < 20:
            return 50, "Insufficient data", True
        
        atr = calculate_atr(m5, 14)
        
        # Get recent candle ranges
        recent_ranges = [get_candle_range(c) for c in m5[-10:]]
        avg_range = sum(recent_ranges) / len(recent_ranges) if recent_ranges else 0
        
        # Check spike
        max_range = max(recent_ranges) if recent_ranges else 0
        
        if asset == Asset.EURUSD:
            if atr < self.EURUSD_ATR_MIN:
                return 0, f"Market too quiet (ATR {atr*10000:.1f}p < 2.5p)", False
            if atr > self.EURUSD_ATR_MAX:
                return 0, f"Market too volatile (ATR {atr*10000:.1f}p > 18p)", False
            
            # Check spike
            if max_range > self.EURUSD_SPIKE_MAX:
                # Check if confirmed by subsequent candles
                last_3_ranges = recent_ranges[-3:]
                avg_last_3 = sum(last_3_ranges) / 3
                if avg_last_3 > max_range * 0.6:  # Spike confirmed
                    pass  # OK
                else:
                    return 40, f"Unconfirmed spike ({max_range*10000:.0f}p)", True
        else:  # XAUUSD
            if atr < self.XAUUSD_ATR_MIN:
                return 0, f"Market too quiet (ATR ${atr:.1f} < $0.9)", False
            if atr > self.XAUUSD_ATR_MAX:
                return 0, f"Market too volatile (ATR ${atr:.1f} > $9)", False
            
            # Check spike
            if max_range > self.XAUUSD_SPIKE_MAX:
                last_3_ranges = recent_ranges[-3:]
                avg_last_3 = sum(last_3_ranges) / 3
                if avg_last_3 > max_range * 0.6:
                    pass  # OK
                else:
                    return 40, f"Unconfirmed spike (${max_range:.1f})", True
        
        # Normal volatility scoring
        if asset == Asset.EURUSD:
            ideal_atr_min = 0.0004  # 4 pips
            ideal_atr_max = 0.0010  # 10 pips
        else:
            ideal_atr_min = 1.5
            ideal_atr_max = 5.0
        
        if ideal_atr_min <= atr <= ideal_atr_max:
            return 100, "Healthy volatility", True
        elif atr < ideal_atr_min:
            return 70, "Low volatility (OK)", True
        else:
            return 70, "High volatility (OK)", True
    
    # ==================== LEGACY FUNCTIONS (kept for compatibility) ====================
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
    
    def _is_allowed_setup(self, setup_type: str) -> Tuple[bool, int]:
        """
        Check setup type - SOFT FILTER (v3.3)
        
        Returns (is_allowed, score_penalty)
        - All setups allowed, but non-preferred get penalty
        """
        # Check if preferred setup
        for preferred in self.PREFERRED_SETUP_PATTERNS:
            if preferred in setup_type:
                return True, 0  # No penalty
        
        # Check if penalized setup
        for penalized in self.PENALIZED_SETUP_PATTERNS:
            if penalized in setup_type:
                return True, self.PENALTY_NON_PREFERRED_SETUP  # Apply penalty but allow
        
        # Default: allow with small penalty
        return True, 5
    
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
    
    def _get_buffer_fail_diagnostics(self) -> Dict:
        """Get buffer zone failure diagnostics with percentages"""
        total_fails = sum(self.buffer_fail_by_reason.values())
        
        # Calculate percentages
        pct_by_reason = {}
        for reason, count in self.buffer_fail_by_reason.items():
            pct_by_reason[reason] = round((count / max(1, total_fails)) * 100, 1)
        
        # Find most common fail reason
        most_common = "none"
        most_common_count = 0
        for reason, count in self.buffer_fail_by_reason.items():
            if count > most_common_count:
                most_common = reason
                most_common_count = count
        
        return {
            "total_buffer_fails": total_fails,
            "fail_count_by_reason": self.buffer_fail_by_reason,
            "pct_fail_by_reason": pct_by_reason,
            "most_common_fail_reason": most_common,
            "most_common_fail_count": most_common_count,
            "most_common_fail_pct": pct_by_reason.get(most_common, 0),
            "reason_descriptions": {
                "mtf_low": "MTF < 60% (single bottleneck)",
                "h1_low": "H1 < 60% (single bottleneck)",
                "rr_low": "R:R < 1.2 (single bottleneck)",
                "mtf_h1": "MTF + H1 both failed",
                "mtf_rr": "MTF + R:R both failed",
                "h1_rr": "H1 + R:R both failed",
                "all_failed": "All three conditions failed"
            }
        }
    
    # ==================== STATUS & STATS ====================
    
    def get_stats(self) -> Dict:
        """Get generator statistics"""
        uptime = (datetime.utcnow() - self.start_time).total_seconds() if self.start_time else 0
        
        return {
            "is_running": self.is_running,
            "version": "v3.3 (OPTIMIZED FLOW)",
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
            # ========== SELF-HEALING STATUS ==========
            "health": {
                "last_scan_timestamp": self.last_scan_timestamp.isoformat() if self.last_scan_timestamp else None,
                "last_successful_scan": self.last_successful_scan.isoformat() if self.last_successful_scan else None,
                "scan_age_seconds": (datetime.utcnow() - self.last_scan_timestamp).total_seconds() if self.last_scan_timestamp else None,
                "consecutive_failures": self.consecutive_failures,
                "scanner_restart_count": self.scanner_restart_count,
                "is_degraded": self.is_degraded,
                "degradation_reason": self.degradation_reason,
                "watchdog_active": self.watchdog_task is not None and not self.watchdog_task.done() if self.watchdog_task else False
            },
            # v3.3 OPTIMIZED configuration
            "data_driven_filters": {
                "min_confidence": self.MIN_CONFIDENCE_SCORE,
                "min_mtf_score": self.MIN_MTF_SCORE,
                "allowed_assets": [a.value for a in self.ALLOWED_ASSETS],
                "allowed_sessions": self.ALLOWED_SESSIONS,
                "preferred_setups": self.PREFERRED_SETUP_PATTERNS,
                "penalized_setups": self.PENALIZED_SETUP_PATTERNS,
                "min_rr": self.MIN_RR_HARD_REJECT,
                "fta_hard_block_threshold": self.FTA_HARD_BLOCK_THRESHOLD,
                "target_signals_per_day": f"{self.MIN_SIGNALS_PER_DAY}-{self.MAX_SIGNALS_PER_DAY}"
            },
            "trade_management": {
                "partial_tp": "50% at 0.5R",
                "breakeven": "at 1R",
                "trailing_stop": "after 1R"
            },
            "classification": {
                "strong": "80-100 (0.75% risk, HIGH priority)",
                "good": "60-79 (0.65% risk, NORMAL priority)",
                "buffer_zone_relaxed": "60-64 (v6.0: no blocking, diagnostic only)",
                "rejected": "<60 (below minimum)"
            },
            # ========== BUFFER ZONE MONITORING (v6.0) ==========
            "buffer_zone_metrics": {
                "candidates_evaluated": self.candidates_evaluated,
                "score_gte_65": self.candidates_score_gte_65,
                "score_60_64": self.candidates_score_60_64,
                "score_lt_60": self.candidates_score_lt_60,
                "pct_gte_65": round((self.candidates_score_gte_65 / max(1, self.candidates_evaluated)) * 100, 1),
                "pct_60_64": round((self.candidates_score_60_64 / max(1, self.candidates_evaluated)) * 100, 1),
                "pct_lt_60": round((self.candidates_score_lt_60 / max(1, self.candidates_evaluated)) * 100, 1),
                "accepted_main_threshold": self.accepted_main_threshold,
                "accepted_buffer_zone": self.accepted_buffer_zone,
                "buffer_zone_failed": self.buffer_zone_failed,
                "buffer_zone_relaxed_accepted": 0,  # v6.0: trades that would have been blocked
                "total_accepted": self.accepted_main_threshold + self.accepted_buffer_zone,
                "acceptance_rate": round(((self.accepted_main_threshold + self.accepted_buffer_zone) / max(1, self.candidates_evaluated)) * 100, 2),
                "v6_changes": "MIN_CONFIDENCE_SCORE: 65->60, buffer_zone_failed: no longer blocks"
            },
            # ========== BUFFER ZONE FAILURE DIAGNOSTICS (v6.0 - diagnostic only) ==========
            "buffer_fail_diagnostics": self._get_buffer_fail_diagnostics(),
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
