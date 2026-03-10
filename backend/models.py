from pydantic import BaseModel, Field
from typing import Optional, List, Dict, Any
from datetime import datetime
from enum import Enum

# Enums
class SignalType(str, Enum):
    BUY = "BUY"
    SELL = "SELL"
    NEXT = "NEXT"

class Asset(str, Enum):
    EURUSD = "EURUSD"
    XAUUSD = "XAUUSD"

class Timeframe(str, Enum):
    M5 = "M5"
    M15 = "M15"
    H1 = "H1"
    H4 = "H4"
    D1 = "D1"

class Session(str, Enum):
    LONDON = "LONDON"
    NEW_YORK = "NEW_YORK"
    OVERLAP = "OVERLAP"
    OTHER = "OTHER"

class MarketRegime(str, Enum):
    BULLISH_TREND = "BULLISH_TREND"
    BEARISH_TREND = "BEARISH_TREND"
    RANGE = "RANGE"
    COMPRESSION = "COMPRESSION"
    BREAKOUT_EXPANSION = "BREAKOUT_EXPANSION"
    CHAOTIC = "CHAOTIC"

class StrategyType(str, Enum):
    TREND_PULLBACK = "TREND_PULLBACK"
    BREAKOUT_RETEST = "BREAKOUT_RETEST"
    STRUCTURE_BREAK = "STRUCTURE_BREAK"
    RANGE_REJECTION = "RANGE_REJECTION"
    VOLATILITY_EXPANSION = "VOLATILITY_EXPANSION"

class PropRuleSafety(str, Enum):
    SAFE = "SAFE"
    CAUTION = "CAUTION"
    BLOCKED = "BLOCKED"

class TradeHorizon(str, Enum):
    FAST_INTRADAY = "FAST_INTRADAY"  # 3min - 2hrs
    STANDARD_INTRADAY = "STANDARD_INTRADAY"  # 2hrs - 8hrs
    MULTI_SESSION = "MULTI_SESSION"  # 8hrs - 24hrs
    SWING = "SWING"  # 1-3 days
    EXTENDED_SWING = "EXTENDED_SWING"  # 3-7 days

class ValidationStatus(str, Enum):
    APPROVED = "APPROVED"
    REVIEW = "REVIEW"
    REJECTED = "REJECTED"

class DrawdownType(str, Enum):
    BALANCE = "BALANCE"
    EQUITY = "EQUITY"

class PropPhase(str, Enum):
    CHALLENGE = "CHALLENGE"
    FUNDED = "FUNDED"

# Core Models
class User(BaseModel):
    id: str = Field(default_factory=lambda: str(datetime.utcnow().timestamp()))
    email: Optional[str] = None
    created_at: datetime = Field(default_factory=datetime.utcnow)
    active_prop_profile_id: Optional[str] = None
    notification_token: Optional[str] = None
    preferences: Dict[str, Any] = Field(default_factory=dict)

class PropProfile(BaseModel):
    id: str = Field(default_factory=lambda: str(datetime.utcnow().timestamp()))
    user_id: str
    name: str  # e.g., "Get Leveraged Challenge"
    firm_name: str  # e.g., "Get Leveraged", "GoatFundedTrader"
    phase: PropPhase = PropPhase.CHALLENGE
    
    # Drawdown rules
    daily_drawdown_percent: float = 5.0
    max_drawdown_percent: float = 10.0
    drawdown_type: DrawdownType = DrawdownType.BALANCE
    
    # Exposure rules
    max_lot_exposure: Optional[float] = None
    
    # Trading rules
    news_rule_enabled: bool = False
    weekend_holding_allowed: bool = False
    overnight_holding_allowed: bool = True
    
    # Consistency rules
    consistency_rule_enabled: bool = False
    max_daily_profit_percent: Optional[float] = None
    
    # Payout rules
    minimum_trading_days: int = 5
    minimum_profitable_days: int = 3
    minimum_trade_duration_minutes: int = 3
    
    # Account tracking
    initial_balance: float = 10000.0
    current_balance: float = 10000.0
    current_equity: float = 10000.0
    
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)

class ScoreBreakdown(BaseModel):
    regime_quality: float = 0.0
    structure_clarity: float = 0.0
    trend_alignment: float = 0.0
    entry_quality: float = 0.0
    stop_quality: float = 0.0
    target_quality: float = 0.0
    session_quality: float = 0.0
    volatility_quality: float = 0.0
    prop_rule_safety: float = 0.0
    total: float = 0.0

class Signal(BaseModel):
    id: str = Field(default_factory=lambda: str(datetime.utcnow().timestamp()))
    user_id: str
    
    # Signal basics
    signal_type: SignalType
    asset: Asset
    timeframe: Timeframe
    session: Session
    
    # Strategy info
    strategy_type: Optional[StrategyType] = None
    market_regime: MarketRegime
    
    # Trade details (None if NEXT)
    entry_price: Optional[float] = None
    entry_zone_low: Optional[float] = None
    entry_zone_high: Optional[float] = None
    stop_loss: Optional[float] = None
    take_profit_1: Optional[float] = None
    take_profit_2: Optional[float] = None
    
    # Risk metrics
    risk_reward_ratio: Optional[float] = None
    stop_distance_pips: Optional[float] = None
    
    # Scoring
    confidence_score: float = 0.0
    score_breakdown: Optional[ScoreBreakdown] = None
    
    # Probability
    success_probability: Optional[float] = None
    failure_probability: Optional[float] = None
    
    # Expected duration
    expected_duration_minutes: Optional[int] = None
    trade_horizon: Optional[TradeHorizon] = None
    
    # Explanation
    explanation: Optional[str] = None
    next_reason: Optional[str] = None  # Why NEXT was chosen
    
    # Prop rule safety
    prop_rule_safety: PropRuleSafety = PropRuleSafety.SAFE
    prop_rule_warnings: List[str] = Field(default_factory=list)
    
    # Timestamps
    created_at: datetime = Field(default_factory=datetime.utcnow)
    expires_at: Optional[datetime] = None
    invalidated_at: Optional[datetime] = None
    
    # Status tracking
    is_active: bool = True
    tp1_hit: bool = False
    tp2_hit: bool = False
    sl_hit: bool = False

class SignalHistory(BaseModel):
    id: str = Field(default_factory=lambda: str(datetime.utcnow().timestamp()))
    signal_id: str
    user_id: str
    event_type: str  # "created", "tp1_hit", "tp2_hit", "sl_hit", "invalidated"
    event_data: Dict[str, Any] = Field(default_factory=dict)
    timestamp: datetime = Field(default_factory=datetime.utcnow)

class MarketRegimeData(BaseModel):
    id: str = Field(default_factory=lambda: str(datetime.utcnow().timestamp()))
    asset: Asset
    timeframe: Timeframe
    regime: MarketRegime
    
    # Technical indicators
    ema_20: Optional[float] = None
    ema_50: Optional[float] = None
    ema_200: Optional[float] = None
    atr: Optional[float] = None
    adr: Optional[float] = None
    
    # Regime characteristics
    trend_slope: Optional[float] = None
    volatility_expansion: bool = False
    
    timestamp: datetime = Field(default_factory=datetime.utcnow)

class BacktestRun(BaseModel):
    id: str = Field(default_factory=lambda: str(datetime.utcnow().timestamp()))
    name: str
    asset: Optional[Asset] = None
    timeframe: Optional[Timeframe] = None
    strategy_type: Optional[StrategyType] = None
    
    # Date range
    start_date: datetime
    end_date: datetime
    
    # Results
    total_trades: int = 0
    winning_trades: int = 0
    losing_trades: int = 0
    win_rate: float = 0.0
    
    average_win: float = 0.0
    average_loss: float = 0.0
    expectancy: float = 0.0
    profit_factor: float = 0.0
    
    max_drawdown: float = 0.0
    longest_losing_streak: int = 0
    
    average_trade_duration_minutes: Optional[float] = None
    
    validation_status: ValidationStatus = ValidationStatus.REVIEW
    
    created_at: datetime = Field(default_factory=datetime.utcnow)
    
class Notification(BaseModel):
    id: str = Field(default_factory=lambda: str(datetime.utcnow().timestamp()))
    user_id: str
    title: str
    body: str
    notification_type: str  # "signal", "rule_warning", "tp_hit", "sl_hit"
    data: Dict[str, Any] = Field(default_factory=dict)
    sent: bool = False
    read: bool = False
    created_at: datetime = Field(default_factory=datetime.utcnow)
    sent_at: Optional[datetime] = None

class Candle(BaseModel):
    timestamp: datetime
    open: float
    high: float
    low: float
    close: float
    volume: Optional[float] = None
