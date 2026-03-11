"""
Advanced Scanner Configuration - Production-grade settings for signal generation
"""
from dataclasses import dataclass, field
from typing import Dict, List
from enum import Enum


class SetupType(Enum):
    """Types of trading setups the scanner can detect"""
    TREND_CONTINUATION = "trend_continuation"
    BREAKOUT_RETEST = "breakout_retest"
    LIQUIDITY_SWEEP = "liquidity_sweep"
    RANGE_EXPANSION = "range_expansion"
    SESSION_BREAKOUT = "session_breakout"


class SignalGrade(Enum):
    """Signal quality grades based on score"""
    A_PLUS = "A+"  # 90-100
    A = "A"        # 80-89
    B = "B"        # 70-79
    C = "C"        # 60-69 (not sent)
    D = "D"        # Below 60 (rejected)


class TimeframeBias(Enum):
    """Higher timeframe directional bias"""
    BULLISH = "bullish"
    BEARISH = "bearish"
    NEUTRAL = "neutral"


@dataclass
class ScoringWeights:
    """Weights for signal scoring components (must sum to 100)"""
    htf_bias_alignment: float = 20.0      # Higher timeframe bias alignment
    market_structure: float = 15.0         # Structure quality (HH/HL or LL/LH)
    setup_quality: float = 20.0            # Breakout/retest/pattern quality
    momentum_confirmation: float = 15.0    # RSI/MACD/Volume alignment
    session_quality: float = 10.0          # Trading session timing
    volatility_quality: float = 10.0       # ATR/expansion quality
    invalidation_cleanliness: float = 10.0 # Clean SL placement
    
    def validate(self) -> bool:
        total = (
            self.htf_bias_alignment +
            self.market_structure +
            self.setup_quality +
            self.momentum_confirmation +
            self.session_quality +
            self.volatility_quality +
            self.invalidation_cleanliness
        )
        return abs(total - 100.0) < 0.01


@dataclass
class SessionScoreAdjustments:
    """Score adjustments based on trading session"""
    london_open: float = 10.0           # +10 during London open (7-9 UTC)
    ny_open: float = 10.0               # +10 during NY open (13-15 UTC)
    london_ny_overlap: float = 15.0     # +15 during overlap (13-16 UTC)
    asian_session: float = -5.0         # -5 during Asian (0-7 UTC)
    dead_hours: float = -15.0           # -15 during dead hours (21-0 UTC)
    weekend_close: float = -20.0        # -20 near weekend close


@dataclass
class DuplicateProtection:
    """Settings for duplicate signal suppression"""
    enabled: bool = True
    price_zone_pips: float = 15.0       # Suppress signals within X pips of recent
    direction_cooldown_minutes: int = 30 # Cooldown per direction
    same_setup_cooldown_minutes: int = 60 # Cooldown for same setup type
    max_signals_per_hour: int = 4        # Max signals per instrument per hour


@dataclass
class ScannerConfig:
    """Master configuration for the advanced scanner"""
    
    # Score thresholds
    min_score_threshold: float = 70.0    # Minimum score to generate signal
    a_plus_threshold: float = 90.0       # A+ grade threshold
    a_threshold: float = 80.0            # A grade threshold
    b_threshold: float = 70.0            # B grade threshold
    
    # Scoring weights
    scoring_weights: ScoringWeights = field(default_factory=ScoringWeights)
    
    # Session adjustments
    session_adjustments: SessionScoreAdjustments = field(default_factory=SessionScoreAdjustments)
    
    # Duplicate protection
    duplicate_protection: DuplicateProtection = field(default_factory=DuplicateProtection)
    
    # Setup modules (enabled/disabled)
    enabled_setups: Dict[SetupType, bool] = field(default_factory=lambda: {
        SetupType.TREND_CONTINUATION: True,
        SetupType.BREAKOUT_RETEST: True,
        SetupType.LIQUIDITY_SWEEP: True,
        SetupType.RANGE_EXPANSION: True,
        SetupType.SESSION_BREAKOUT: True,
    })
    
    # Higher timeframe settings
    htf_bias_timeframes: List[str] = field(default_factory=lambda: ["1h", "15min", "5min"])
    require_htf_alignment: bool = True
    allow_countertrend: bool = False
    countertrend_score_penalty: float = 20.0  # -20 for countertrend signals
    
    # Signal limits
    max_concurrent_signals_per_asset: int = 2
    signal_expiry_minutes: int = 60
    
    # Trigger settings
    trigger_aggressiveness: float = 1.0  # 0.5 = conservative, 1.0 = normal, 1.5 = aggressive
    
    # Logging
    verbose_logging: bool = True
    log_rejected_signals: bool = True
    log_score_breakdown: bool = True


# Default production configuration
DEFAULT_SCANNER_CONFIG = ScannerConfig()

# Conservative configuration (fewer but higher quality signals)
CONSERVATIVE_CONFIG = ScannerConfig(
    min_score_threshold=80.0,
    a_plus_threshold=95.0,
    a_threshold=85.0,
    b_threshold=80.0,
    require_htf_alignment=True,
    allow_countertrend=False,
    trigger_aggressiveness=0.7,
)

# Aggressive configuration (more signals, still quality-filtered)
AGGRESSIVE_CONFIG = ScannerConfig(
    min_score_threshold=65.0,
    a_plus_threshold=85.0,
    a_threshold=75.0,
    b_threshold=65.0,
    require_htf_alignment=True,
    allow_countertrend=True,
    countertrend_score_penalty=15.0,
    trigger_aggressiveness=1.3,
)
