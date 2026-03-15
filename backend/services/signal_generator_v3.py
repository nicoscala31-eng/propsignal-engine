"""
Signal Generator v3 - Confidence-Based Signal Engine
=====================================================

*** AUTHORIZED PRODUCTION ENGINE ***
*** SINGLE PRODUCTION PIPELINE - NO PARALLEL ENGINES ***

This is the ONLY engine authorized for production signal generation.
All other engines (market_scanner, advanced_scanner, signal_orchestrator) are DISABLED.

UPGRADES IMPLEMENTED:
1. Position Sizing Engine - calculates lot_size, money_at_risk, risk_percent, pip_risk
2. Prop Firm Rule Awareness - 100k account, 3000 max daily loss, 1500 warning level
3. News Risk Detection - CPI, NFP, FOMC awareness with soft penalties
4. Session Filter (Soft) - penalties instead of hard blocks
5. Spread Validation (Moderate) - small penalty for elevated, block for extreme
6. Advanced MTF Bias - alignment scoring between H1/M15/M5
7. Advanced Pullback Quality - depth, location, retracement evaluation
8. Invalid Token Cleanup - auto-removal of expired push tokens
9. State Persistence - survives restarts

PROP TRADING ASSUMPTIONS:
- account_size = 100,000
- max_daily_loss = 3,000
- operational_warning = 1,500
- risk_per_trade = 0.5% to 0.75%
- primary instrument = EURUSD intraday

DESIGN PHILOSOPHY:
- Generate signals consistently instead of blocking almost everything
- Use weighted scoring to assign confidence (0-100) to each signal
- Only reject for truly invalid market conditions
- Let confidence score reflect setup quality

CONFIDENCE CLASSIFICATION:
- 80-100: Strong setup (high confidence)
- 65-79: Tradable setup (medium confidence)
- 50-64: Aggressive/weaker setup (low confidence)
- Below 60: Reject (don't send notification) - MANDATORY THRESHOLD

DUPLICATE SUPPRESSION: Light (25 min window)
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


class PositionSizingEngine:
    """
    Position Sizing Engine for EURUSD
    
    Uses:
    - Entry price
    - Stop loss price
    - Account size (100k default)
    - Risk percentage (0.5-0.75%)
    - Pip value for EURUSD (standard lot = $10/pip)
    """
    
    # EURUSD pip value per standard lot
    EURUSD_PIP_VALUE = 10.0  # $10 per pip per standard lot
    XAUUSD_PIP_VALUE = 1.0   # $1 per pip per standard lot (0.01 point)
    
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
    
    def calculate(
        self,
        asset: Asset,
        entry_price: float,
        stop_loss: float,
        risk_percent: Optional[float] = None
    ) -> PositionSizeResult:
        """
        Calculate position size
        
        Formula:
        1. Pip Risk = |Entry - SL| / pip_size
        2. Money at Risk = Account * Risk%
        3. Lot Size = Money at Risk / (Pip Risk * Pip Value)
        """
        self._reset_daily_if_needed()
        
        # Determine pip size and value
        if asset == Asset.EURUSD:
            pip_size = 0.0001
            pip_value = self.EURUSD_PIP_VALUE
        else:  # XAUUSD
            pip_size = 0.01
            pip_value = self.XAUUSD_PIP_VALUE
        
        # Calculate pip risk
        pip_risk = abs(entry_price - stop_loss) / pip_size
        
        # Use default risk if not provided
        if risk_percent is None:
            risk_percent = self.config.default_risk_percent
        
        # Ensure risk is within bounds
        risk_percent = max(
            self.config.min_risk_percent,
            min(self.config.max_risk_percent, risk_percent)
        )
        
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
        
        # Check prop firm constraints
        warnings = []
        adjusted = False
        adjustment_reason = None
        
        # Check if trade would exceed daily limit
        remaining_daily = self.config.max_daily_loss - self.daily_risk_used
        
        if money_at_risk > remaining_daily:
            # Reduce position to fit remaining allowance
            old_lot = lot_size
            money_at_risk = remaining_daily * 0.9  # Use 90% of remaining
            lot_size = money_at_risk / (pip_risk * pip_value) if pip_risk > 0 else 0.01
            lot_size = round(max(0.01, lot_size), 2)
            adjusted = True
            adjustment_reason = f"Reduced from {old_lot:.2f} to fit daily limit"
            warnings.append(f"Position reduced: daily limit ${remaining_daily:.0f} remaining")
        
        # Check if approaching warning level
        if self.daily_risk_used >= self.config.operational_warning:
            warnings.append(f"WARNING: Daily loss at ${self.daily_risk_used:.0f} (warning level: ${self.config.operational_warning:.0f})")
        elif self.daily_risk_used + money_at_risk > self.config.operational_warning:
            warnings.append(f"Trade will reach warning level (${self.config.operational_warning:.0f})")
        
        # Recalculate final money at risk after adjustments
        final_money_at_risk = lot_size * pip_risk * pip_value
        final_risk_percent = (final_money_at_risk / self.config.account_size) * 100
        
        return PositionSizeResult(
            recommended_lot_size=lot_size,
            money_at_risk=round(final_money_at_risk, 2),
            risk_percent=round(final_risk_percent, 3),
            pip_risk=round(pip_risk, 1),
            pip_value=pip_value,
            adjusted=adjusted,
            adjustment_reason=adjustment_reason,
            prop_warnings=warnings
        )
    
    def record_trade(self, money_at_risk: float):
        """Record a trade's risk for daily tracking"""
        self._reset_daily_if_needed()
        self.daily_risk_used += money_at_risk
    
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
    
    # Position sizing (NEW)
    recommended_lot_size: float = 0.0
    money_at_risk: float = 0.0
    risk_percent: float = 0.0
    pip_risk: float = 0.0
    position_adjusted: bool = False
    position_adjustment_reason: Optional[str] = None
    prop_warnings: List[str] = field(default_factory=list)
    
    # News risk (NEW)
    news_risk: NewsRiskLevel = NewsRiskLevel.NONE
    news_event: Optional[str] = None
    news_warning: Optional[str] = None
    
    # Spread info (NEW)
    spread_pips: float = 0.0
    
    def to_notification_dict(self) -> Dict:
        """
        Format for push notification
        
        NOTIFICATION BODY FORMAT:
        - Symbol (in title)
        - Direction (in title)
        - Entry Price
        - Stop Loss (SL)
        - Take Profit (TP)
        - Confidence %
        - Risk/Reward Ratio
        - Lot Size
        - News Warning (if any)
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
        
        # Build notification body
        body_lines = [
            f"Entry: {entry_str}",
            f"SL: {sl_str} | TP: {tp_str}",
            f"Conf: {self.confidence_score:.0f}% | R:R: {self.risk_reward:.1f}",
            f"Lot: {self.recommended_lot_size:.2f} | Risk: ${self.money_at_risk:.0f}"
        ]
        
        # Add news warning if present
        if self.news_risk != NewsRiskLevel.NONE and self.news_warning:
            body_lines.append(f"⚠️ {self.news_warning}")
        
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
                "risk_reward": self.risk_reward,
                "confidence": self.confidence_score,
                "confidence_level": self.confidence_level.value,
                "setup_type": self.setup_type,
                "invalidation": self.invalidation,
                "session": self.session,
                "timestamp": self.timestamp.isoformat(),
                # Position sizing data
                "lot_size": self.recommended_lot_size,
                "money_at_risk": self.money_at_risk,
                "risk_percent": self.risk_percent,
                "pip_risk": self.pip_risk,
                "prop_warnings": self.prop_warnings,
                # News risk data
                "news_risk": self.news_risk.value,
                "news_event": self.news_event,
                "news_warning": self.news_warning,
                # Spread
                "spread_pips": self.spread_pips
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
    Confidence-Based Signal Generator
    
    PRODUCTION ENGINE - Single Pipeline
    
    Features:
    1. Position Sizing Engine
    2. Prop Firm Awareness
    3. News Risk Detection
    4. Session Filter (Soft)
    5. Spread Validation (Moderate)
    6. Advanced MTF Bias
    7. Advanced Pullback Quality
    8. Invalid Token Cleanup
    9. State Persistence
    """
    
    # Scoring weights (must sum to 100)
    WEIGHTS = {
        'h1_bias': 15.0,           # H1 directional bias
        'm15_context': 12.0,       # M15 alignment/context
        'mtf_alignment': 10.0,     # NEW: Multi-timeframe alignment bonus
        'market_structure': 12.0,  # Market structure quality
        'momentum': 10.0,          # Momentum strength
        'pullback_quality': 12.0,  # Enhanced pullback evaluation
        'key_level': 8.0,          # Reaction at key level
        'session': 6.0,            # Session quality (soft penalty)
        'rr_ratio': 5.0,           # Risk/Reward ratio
        'volatility': 3.0,         # Volatility conditions
        'regime_quality': 5.0,     # Market regime
        'spread': 2.0,             # NEW: Spread penalty
    }
    
    # Hard rejection thresholds
    MAX_SPREAD_PIPS_EURUSD = 3.0   # Max spread for EURUSD (moderate)
    MAX_SPREAD_PIPS_XAUUSD = 50.0  # Max spread for XAUUSD
    ELEVATED_SPREAD_EURUSD = 1.5   # Spread penalty threshold
    ELEVATED_SPREAD_XAUUSD = 30.0
    MIN_ATR_MULTIPLIER = 0.3      # Minimum ATR for activity
    MAX_DATA_AGE_SECONDS = 60     # Max age of market data
    
    # Duplicate suppression
    DUPLICATE_WINDOW_MINUTES = 25  # Light duplicate window
    DUPLICATE_PRICE_ZONE_PIPS = 15 # Price zone for EURUSD
    DUPLICATE_PRICE_ZONE_XAU = 200 # Price zone for XAUUSD
    
    def __init__(self, db):
        self.db = db
        self.is_running = False
        self.scan_interval = 5  # seconds
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
        self.invalid_tokens_removed = 0
        self.start_time: Optional[datetime] = None
        
        # Load persisted state
        self._load_state()
        
        logger.info("🚀 Signal Generator v3 initialized (ENHANCED)")
        logger.info(f"   Prop Config: ${PROP_CONFIG.account_size:,.0f} account, ${PROP_CONFIG.max_daily_loss:,.0f} max daily loss")
        logger.info(f"   Risk Range: {PROP_CONFIG.min_risk_percent}% - {PROP_CONFIG.max_risk_percent}%")
        logger.info(f"   Duplicate window: {self.DUPLICATE_WINDOW_MINUTES} minutes")
        logger.info(f"   Min confidence: 60% (MANDATORY)")
    
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
                self.invalid_tokens_removed = state.get("invalid_tokens_removed", 0)
                
                # Restore daily risk tracking
                daily_risk = state.get("daily_risk_used", 0)
                last_reset = state.get("last_reset_date")
                if last_reset:
                    try:
                        saved_date = datetime.fromisoformat(last_reset).date()
                        if saved_date == datetime.utcnow().date():
                            self.position_sizer.daily_risk_used = daily_risk
                    except:
                        pass
                
                logger.info(f"📂 Loaded state: {self.scan_count} scans, {self.signal_count} signals")
        except Exception as e:
            logger.warning(f"Could not load state: {e}")
    
    def _save_state(self):
        """Persist state to file"""
        try:
            # Ensure directory exists
            STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
            
            state = {
                "scan_count": self.scan_count,
                "signal_count": self.signal_count,
                "notification_count": self.notification_count,
                "rejection_count": self.rejection_count,
                "invalid_tokens_removed": self.invalid_tokens_removed,
                "daily_risk_used": self.position_sizer.daily_risk_used,
                "last_reset_date": self.position_sizer.last_reset_date.isoformat(),
                "last_save": datetime.utcnow().isoformat()
            }
            
            with open(STATE_FILE, 'w') as f:
                json.dump(state, f, indent=2)
        except Exception as e:
            logger.warning(f"Could not save state: {e}")
    
    # ==================== LIFECYCLE ====================
    
    async def start(self):
        """Start the generator"""
        if self.is_running:
            return
        
        self.is_running = True
        self.start_time = datetime.utcnow()
        
        logger.info("=" * 60)
        logger.info("🚀 SIGNAL GENERATOR V3 STARTED (ENHANCED)")
        logger.info("   Mode: Confidence-based scoring (NO hidden thresholds)")
        logger.info("   MANDATORY Min confidence: 60%")
        logger.info("   80-100: STRONG | 70-79: GOOD | 60-69: ACCEPTABLE | <60: REJECTED")
        logger.info(f"   Scan interval: {self.scan_interval}s")
        logger.info(f"   Prop: ${PROP_CONFIG.account_size:,.0f} | Max Daily Loss: ${PROP_CONFIG.max_daily_loss:,.0f}")
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
        logger.info("🛑 Signal Generator v3 stopped")
    
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
        """
        Scan all assets with FULL validation and production controls
        
        PRODUCTION PIPELINE SEQUENCE:
        1. Production control check (scanner enabled?)
        2. Market validation (forex open, data fresh, not frozen)
        3. News risk detection
        4. Candidate generation
        5. Scoring (including spread, session, MTF)
        6. Position sizing
        7. Duplicate check
        8. Notification send (if notifications enabled)
        9. Outcome tracking
        
        CRITICAL: All checks must pass BEFORE any signal generation.
        """
        from services.production_control import production_control, EngineType
        
        self.scan_count += 1
        
        # ========== STEP 1: PRODUCTION CONTROL CHECK ==========
        authorized, reason = production_control.authorize_scan(EngineType.SIGNAL_GENERATOR_V3)
        if not authorized:
            if self.scan_count % 60 == 0:
                logger.info(f"🛡️ [PRODUCTION] Scan blocked: {reason}")
            return
        
        # ========== STEP 2: MARKET VALIDATION - FOREX HOURS ==========
        if not market_validator.is_forex_open():
            if self.scan_count % 60 == 0:
                status = market_validator.get_market_status_summary()
                logger.info(f"🌙 [MARKET] Forex closed ({status['day_of_week']} {status['hour_utc']}:00 UTC)")
            return
        
        for asset in [Asset.EURUSD, Asset.XAUUSD]:
            # ========== STEP 2b: FULL MARKET VALIDATION ==========
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
            
            # ========== STEP 3: NEWS RISK DETECTION ==========
            news_risk = await self._detect_news_risk(asset)
            
            # ========== STEP 4-7: ANALYSIS, SCORING, SIZING ==========
            signal = await self._analyze_asset(asset, news_risk)
            
            if signal:
                # ========== STEP 8-9: NOTIFICATION & TRACKING ==========
                await self._process_signal(signal)
    
    # ==================== NEWS RISK DETECTION ====================
    
    async def _detect_news_risk(self, asset: Asset) -> NewsRiskInfo:
        """
        Detect news risk for the asset
        
        Checks macro_news_service for upcoming high-impact events.
        Does NOT block signals - only adds warnings and small score penalties.
        """
        try:
            from services.macro_news_service import macro_news_service
            
            # Check news within 60 minute window
            news_info = await macro_news_service.check_news_risk(asset, minutes_window=60)
            
            if news_info.get("has_risk", False):
                minutes_to_event = news_info.get("minutes_to_event", 999)
                event_name = news_info.get("event_name", "Economic Event")
                
                # Determine risk level based on proximity
                if minutes_to_event <= 15:
                    level = NewsRiskLevel.HIGH
                    penalty = 10.0
                    warning = f"⚠️ {event_name} in {minutes_to_event}m"
                elif minutes_to_event <= 30:
                    level = NewsRiskLevel.MEDIUM
                    penalty = 5.0
                    warning = f"{event_name} in {minutes_to_event}m"
                else:
                    level = NewsRiskLevel.LOW
                    penalty = 2.0
                    warning = f"{event_name} in {minutes_to_event}m"
                
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
    
    # ==================== MAIN ANALYSIS ====================
    
    async def _analyze_asset(self, asset: Asset, news_risk: NewsRiskInfo) -> Optional[GeneratedSignal]:
        """
        Analyze an asset and potentially generate a signal
        
        Returns None only for hard rejection conditions
        """
        # ========== HARD REJECTION CHECKS ==========
        
        # 1. Check data freshness
        if market_data_cache.is_stale(asset):
            logger.debug(f"⏭️  {asset.value}: Stale data")
            return None
        
        # 2. Get candle data
        h1_candles = market_data_cache.get_candles(asset, Timeframe.H1)
        m15_candles = market_data_cache.get_candles(asset, Timeframe.M15)
        m5_candles = market_data_cache.get_candles(asset, Timeframe.M5)
        
        if not h1_candles or not m15_candles or not m5_candles:
            logger.debug(f"⏭️  {asset.value}: Missing candle data")
            return None
        
        if len(m5_candles) < 50:
            logger.debug(f"⏭️  {asset.value}: Insufficient candles")
            return None
        
        # 3. Get current quote and check spread
        price_data = market_data_cache.get_price(asset)
        if not price_data:
            logger.debug(f"⏭️  {asset.value}: No price available")
            return None
        
        # Check spread (MODERATE - only block extreme)
        max_spread = self.MAX_SPREAD_PIPS_EURUSD if asset == Asset.EURUSD else self.MAX_SPREAD_PIPS_XAUUSD
        current_spread = price_data.spread_pips
        
        if current_spread > max_spread:
            logger.info(f"⏭️  {asset.value}: Spread extreme ({current_spread:.1f} pips > {max_spread})")
            return None
        
        # 4. Check minimum volatility (ATR)
        atr = self._calculate_atr(m5_candles, 14)
        if atr == 0:
            logger.debug(f"⏭️  {asset.value}: Zero volatility")
            return None
        
        avg_atr = self._calculate_average_atr(m5_candles, 50)
        if avg_atr > 0 and atr < avg_atr * self.MIN_ATR_MULTIPLIER:
            logger.debug(f"⏭️  {asset.value}: Low volatility")
            return None
        
        # ========== SCORING ANALYSIS ==========
        
        current_price = price_data.mid
        session = session_detector.get_current_session()
        session_name = self._get_session_name(session)
        
        # Analyze direction with advanced MTF bias
        direction, direction_score, direction_reason = self._analyze_direction_advanced(
            h1_candles, m15_candles, m5_candles
        )
        
        if not direction:
            direction = self._fallback_direction(m5_candles)
            if not direction:
                logger.debug(f"⏭️  {asset.value}: No direction found")
                return None
        
        # Calculate all score components
        components = []
        
        # 1. H1 Bias Score
        h1_score, h1_reason = self._score_h1_bias(h1_candles, direction)
        components.append(ScoreComponent("H1 Directional Bias", self.WEIGHTS['h1_bias'], h1_score, h1_reason))
        
        # 2. M15 Context Score
        m15_score, m15_reason = self._score_m15_context(m15_candles, direction)
        components.append(ScoreComponent("M15 Context", self.WEIGHTS['m15_context'], m15_score, m15_reason))
        
        # 3. MTF Alignment Score (NEW - Advanced)
        mtf_score, mtf_reason = self._score_mtf_alignment(h1_candles, m15_candles, m5_candles, direction)
        components.append(ScoreComponent("MTF Alignment", self.WEIGHTS['mtf_alignment'], mtf_score, mtf_reason))
        
        # 4. Market Structure Score
        struct_score, struct_reason = self._score_market_structure(m5_candles, direction)
        components.append(ScoreComponent("Market Structure", self.WEIGHTS['market_structure'], struct_score, struct_reason))
        
        # 5. Momentum Score
        mom_score, mom_reason = self._score_momentum(m5_candles, direction)
        components.append(ScoreComponent("Momentum", self.WEIGHTS['momentum'], mom_score, mom_reason))
        
        # 6. Pullback Quality Score (ENHANCED)
        pb_score, pb_reason = self._score_pullback_advanced(m5_candles, direction, current_price, atr)
        components.append(ScoreComponent("Pullback Quality", self.WEIGHTS['pullback_quality'], pb_score, pb_reason))
        
        # 7. Key Level Score
        kl_score, kl_reason = self._score_key_level(m5_candles, current_price, direction)
        components.append(ScoreComponent("Key Level Reaction", self.WEIGHTS['key_level'], kl_score, kl_reason))
        
        # 8. Session Score (SOFT - no blocking)
        sess_score, sess_reason = self._score_session_soft(session)
        components.append(ScoreComponent("Session Quality", self.WEIGHTS['session'], sess_score, sess_reason))
        
        # 9. Calculate entry, SL, TP
        entry_price = current_price
        pip_size = 0.0001 if asset == Asset.EURUSD else 0.01
        
        if direction == "BUY":
            stop_loss = entry_price - (atr * 1.5)
            take_profit_1 = entry_price + (atr * 2)
            take_profit_2 = entry_price + (atr * 3)
            entry_zone_low = entry_price - (atr * 0.3)
            entry_zone_high = entry_price + (atr * 0.1)
        else:
            stop_loss = entry_price + (atr * 1.5)
            take_profit_1 = entry_price - (atr * 2)
            take_profit_2 = entry_price - (atr * 3)
            entry_zone_low = entry_price - (atr * 0.1)
            entry_zone_high = entry_price + (atr * 0.3)
        
        # Calculate R:R
        risk = abs(entry_price - stop_loss)
        reward = abs(take_profit_1 - entry_price)
        rr_ratio = reward / risk if risk > 0 else 0
        
        # 10. R:R Score
        rr_score, rr_reason = self._score_rr_ratio(rr_ratio)
        components.append(ScoreComponent("Risk/Reward", self.WEIGHTS['rr_ratio'], rr_score, rr_reason))
        
        # 11. Volatility Score
        vol_score, vol_reason = self._score_volatility(atr, avg_atr)
        components.append(ScoreComponent("Volatility", self.WEIGHTS['volatility'], vol_score, vol_reason))
        
        # 12. Market Regime Score
        regime_score, regime_reason = self._score_market_regime(m5_candles, atr, avg_atr)
        components.append(ScoreComponent("Market Regime", self.WEIGHTS['regime_quality'], regime_score, regime_reason))
        
        # 13. Spread Score (NEW - Moderate)
        spread_score, spread_reason = self._score_spread(asset, current_spread)
        components.append(ScoreComponent("Spread", self.WEIGHTS['spread'], spread_score, spread_reason))
        
        # Calculate final score
        final_score = sum(c.weighted_score for c in components)
        
        # Apply news risk penalty (does NOT block)
        if news_risk.score_penalty > 0:
            final_score -= news_risk.score_penalty
            logger.info(f"📰 {asset.value}: News penalty applied (-{news_risk.score_penalty:.1f}): {news_risk.event_name}")
        
        # Ensure score is within bounds
        final_score = max(0, min(100, final_score))
        
        # Determine confidence level - MANDATORY threshold is 60
        if final_score >= 80:
            confidence = SignalConfidence.STRONG
        elif final_score >= 70:
            confidence = SignalConfidence.GOOD
        elif final_score >= 60:
            confidence = SignalConfidence.ACCEPTABLE
        else:
            confidence = SignalConfidence.REJECTED
            self.rejection_count += 1
            logger.info(f"📉 {asset.value} {direction}: Score {final_score:.0f}% < 60% (MANDATORY) - Rejected")
            self._log_score_breakdown(asset, direction, components, final_score)
            return None
        
        # Check duplicate
        if self._is_duplicate(asset, direction, current_price):
            logger.debug(f"⏭️  {asset.value}: Duplicate signal suppressed")
            return None
        
        # ========== POSITION SIZING ==========
        position = self.position_sizer.calculate(
            asset=asset,
            entry_price=entry_price,
            stop_loss=stop_loss
        )
        
        # Generate signal
        signal_id = f"{asset.value}_{direction}_{datetime.utcnow().strftime('%Y%m%d_%H%M%S')}"
        setup_type = self._determine_setup_type(components)
        invalidation = f"{'Below' if direction == 'BUY' else 'Above'} {stop_loss:.5f}"
        
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
            risk_reward=rr_ratio,
            confidence_score=final_score,
            confidence_level=confidence,
            setup_type=setup_type,
            invalidation=invalidation,
            session=session_name,
            score_breakdown=score_obj,
            timestamp=datetime.utcnow(),
            # Position sizing
            recommended_lot_size=position.recommended_lot_size,
            money_at_risk=position.money_at_risk,
            risk_percent=position.risk_percent,
            pip_risk=position.pip_risk,
            position_adjusted=position.adjusted,
            position_adjustment_reason=position.adjustment_reason,
            prop_warnings=position.prop_warnings,
            # News risk
            news_risk=news_risk.level,
            news_event=news_risk.event_name,
            news_warning=news_risk.warning,
            # Spread
            spread_pips=current_spread
        )
        
        return signal
    
    # ==================== SIGNAL PROCESSING ====================
    
    async def _process_signal(self, signal: GeneratedSignal):
        """Process a generated signal"""
        self.signal_count += 1
        
        # Log signal with all details
        emoji = "🟢" if signal.direction == "BUY" else "🔴"
        logger.info("=" * 60)
        logger.info(f"{emoji} SIGNAL GENERATED: {signal.asset.value} {signal.direction}")
        logger.info(f"   Confidence: {signal.confidence_score:.0f}% ({signal.confidence_level.value})")
        logger.info(f"   Entry: {signal.entry_price:.5f}")
        logger.info(f"   Stop Loss: {signal.stop_loss:.5f}")
        logger.info(f"   Take Profit 1: {signal.take_profit_1:.5f}")
        logger.info(f"   Risk/Reward: {signal.risk_reward:.2f}")
        logger.info("-" * 40)
        logger.info(f"   POSITION SIZING (Prop-Aware):")
        logger.info(f"   • Lot Size: {signal.recommended_lot_size:.2f}")
        logger.info(f"   • Money at Risk: ${signal.money_at_risk:.2f}")
        logger.info(f"   • Risk %: {signal.risk_percent:.2f}%")
        logger.info(f"   • Pip Risk: {signal.pip_risk:.1f} pips")
        if signal.prop_warnings:
            for warn in signal.prop_warnings:
                logger.info(f"   ⚠️ {warn}")
        logger.info("-" * 40)
        if signal.news_risk != NewsRiskLevel.NONE:
            logger.info(f"   NEWS RISK: {signal.news_risk.value} - {signal.news_event}")
        logger.info(f"   Session: {signal.session} | Spread: {signal.spread_pips:.1f} pips")
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
        
        # Record trade risk for prop tracking
        self.position_sizer.record_trade(signal.money_at_risk)
        
        # PASSIVE OUTCOME TRACKING
        await self._track_signal_outcome(signal)
        
        # Send notification
        await self._send_notification(signal)
    
    async def _track_signal_outcome(self, signal: GeneratedSignal):
        """Register signal for passive outcome tracking"""
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
                'lot_size': signal.recommended_lot_size,
                'money_at_risk': signal.money_at_risk,
                'news_risk': signal.news_risk.value,
                'score_breakdown': signal.score_breakdown.to_dict() if signal.score_breakdown else {}
            }
            
            await signal_outcome_tracker.track_signal(tracking_data)
        except Exception as e:
            logger.debug(f"Outcome tracking note: {e}")
    
    async def _send_notification(self, signal: GeneratedSignal):
        """Send push notification with invalid token cleanup"""
        from services.production_control import production_control, EngineType
        
        # Check production control
        authorized, reason = production_control.authorize_notification(
            EngineType.SIGNAL_GENERATOR_V3, 
            signal.signal_id
        )
        if not authorized:
            logger.info(f"📵 [PRODUCTION] Notification blocked for {signal.signal_id}: {reason}")
            return
        
        try:
            from services.device_storage_service import device_storage
            from services.push_notification_service import push_service
            
            tokens = await device_storage.get_active_tokens()
            
            if not tokens:
                logger.warning("📭 No devices registered for notifications")
                return
            
            notif = signal.to_notification_dict()
            
            logger.info(f"📤 [signal_generator_v3] Sending notification for signal {signal.signal_id}")
            
            results = await push_service.send_to_all_devices(
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
                    # Check for invalid token errors
                    error_str = str(result.error) if result.error else ""
                    if any(err in error_str for err in ["DeviceNotRegistered", "InvalidCredentials", "Unregistered"]):
                        # Remove invalid token
                        await self._remove_invalid_token(tokens[i])
            
            self.notification_count += 1
            logger.info(f"📤 [signal_generator_v3] Notification sent: {successful}/{len(results)} devices")
            
        except Exception as e:
            logger.error(f"❌ Failed to send notification: {e}")
    
    async def _remove_invalid_token(self, token: str):
        """Remove invalid push token"""
        try:
            from services.device_storage_service import device_storage
            
            # Try to find and deactivate device with this token
            await device_storage.deactivate_by_token(token)
            self.invalid_tokens_removed += 1
            logger.info(f"🧹 Removed invalid push token (total removed: {self.invalid_tokens_removed})")
        except Exception as e:
            logger.debug(f"Could not remove invalid token: {e}")
    
    # ==================== SCORING METHODS ====================
    
    def _analyze_direction_advanced(self, h1: List, m15: List, m5: List) -> Tuple[Optional[str], float, str]:
        """Advanced direction analysis with MTF bias"""
        h1_trend = self._get_trend(h1[-20:]) if len(h1) >= 20 else 0
        m15_trend = self._get_trend(m15[-20:]) if len(m15) >= 20 else 0
        m5_momentum = self._get_momentum(m5[-10:]) if len(m5) >= 10 else 0
        
        # Weighted combination
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
        """
        Score multi-timeframe alignment
        
        Strong alignment: all timeframes agree
        Partial alignment: H1 + M15 agree, M5 mixed
        Conflicting: H1 disagrees with lower timeframes
        """
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
                return 80, "H1 + M15 aligned, M5 mixed"
            else:
                return 65, "Partial alignment"
        elif aligned_count == 1:
            return 40, "Weak alignment"
        else:
            return 20, "Conflicting timeframes"
    
    def _score_pullback_advanced(self, m5: List, direction: str, current_price: float, atr: float) -> Tuple[float, str]:
        """
        Advanced pullback quality scoring
        
        Evaluates:
        - Pullback depth (38.2%-61.8% Fibonacci ideal)
        - Pullback location relative to structure
        - Whether entry is late or efficient
        - Retracement quality
        """
        if len(m5) < 20:
            return 50, "Insufficient data"
        
        # Get recent swing
        highs = [c.get('high', 0) for c in m5[-20:]]
        lows = [c.get('low', 0) for c in m5[-20:]]
        recent_high = max(highs)
        recent_low = min(lows)
        swing_range = recent_high - recent_low
        
        if swing_range == 0:
            return 50, "No swing range"
        
        # Calculate Fibonacci retracement position
        if direction == "BUY":
            # For buy, we want pullback to lower zone
            from_high = (recent_high - current_price) / swing_range
            
            # Ideal: 38.2% to 61.8% retracement
            if 0.382 <= from_high <= 0.618:
                base_score = 95
                reason = "Excellent Fib pullback (38-62%)"
            elif 0.25 <= from_high <= 0.75:
                base_score = 75
                reason = "Good pullback zone"
            elif from_high < 0.25:
                base_score = 40
                reason = "Shallow pullback (may extend)"
            else:
                base_score = 30
                reason = "Deep pullback (risky)"
        else:
            # For sell, we want pullback to higher zone
            from_low = (current_price - recent_low) / swing_range
            
            if 0.382 <= from_low <= 0.618:
                base_score = 95
                reason = "Excellent Fib pullback (38-62%)"
            elif 0.25 <= from_low <= 0.75:
                base_score = 75
                reason = "Good pullback zone"
            elif from_low < 0.25:
                base_score = 40
                reason = "Shallow pullback (may extend)"
            else:
                base_score = 30
                reason = "Deep pullback (risky)"
        
        # Check for entry timing (is price moving back in direction?)
        last_3 = m5[-3:]
        if direction == "BUY":
            resuming = last_3[-1].get('close', 0) > last_3[0].get('open', 0)
        else:
            resuming = last_3[-1].get('close', 0) < last_3[0].get('open', 0)
        
        if resuming:
            base_score = min(100, base_score + 10)
            reason += " + momentum resuming"
        
        return base_score, reason
    
    def _score_session_soft(self, session) -> Tuple[float, str]:
        """
        Score session with SOFT penalties (no blocking)
        
        Major sessions: London, NY, Overlap
        Non-major: small penalty, still tradeable
        """
        hour = datetime.utcnow().hour
        
        # London/NY overlap (optimal)
        if 13 <= hour <= 16:
            return 100, "London/NY overlap - optimal liquidity"
        # London session
        elif 7 <= hour <= 12:
            return 90, "London session - good liquidity"
        # NY session
        elif 13 <= hour <= 20:
            return 85, "NY session - good liquidity"
        # Early Asia / Late NY
        elif 21 <= hour <= 23 or 0 <= hour <= 2:
            return 55, "Transition hours - moderate"
        # Deep Asian session
        elif 3 <= hour <= 6:
            return 40, "Asian session - lower EURUSD activity"
        else:
            return 45, "Off-peak hours"
    
    def _score_spread(self, asset: Asset, spread_pips: float) -> Tuple[float, str]:
        """
        Score spread conditions (MODERATE validation)
        
        - Normal spread: full score
        - Elevated spread: small penalty
        - Extreme: blocked earlier (not reached here)
        """
        if asset == Asset.EURUSD:
            if spread_pips <= 0.8:
                return 100, f"Tight spread ({spread_pips:.1f} pips)"
            elif spread_pips <= 1.2:
                return 85, f"Normal spread ({spread_pips:.1f} pips)"
            elif spread_pips <= self.ELEVATED_SPREAD_EURUSD:
                return 70, f"Acceptable spread ({spread_pips:.1f} pips)"
            else:
                return 40, f"Elevated spread ({spread_pips:.1f} pips)"
        else:  # XAUUSD
            if spread_pips <= 20:
                return 100, f"Tight spread ({spread_pips:.1f} pips)"
            elif spread_pips <= self.ELEVATED_SPREAD_XAUUSD:
                return 75, f"Normal spread ({spread_pips:.1f} pips)"
            else:
                return 50, f"Elevated spread ({spread_pips:.1f} pips)"
    
    # ========== EXISTING SCORING METHODS (unchanged logic) ==========
    
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
        bearish = len(candles) - bullish
        return (bullish - bearish) / len(candles)
    
    def _score_h1_bias(self, h1: List, direction: str) -> Tuple[float, str]:
        """Score H1 bias alignment"""
        if len(h1) < 10:
            return 50, "Insufficient H1 data"
        trend = self._get_trend(h1[-10:])
        if direction == "BUY":
            if trend > 0.5:
                return 100, "Strong H1 bullish trend"
            elif trend > 0.2:
                return 75, "Moderate H1 bullish bias"
            elif trend > 0:
                return 60, "Weak H1 bullish bias"
            elif trend > -0.2:
                return 40, "H1 neutral"
            else:
                return 25, "H1 bearish (counter-trend)"
        else:
            if trend < -0.5:
                return 100, "Strong H1 bearish trend"
            elif trend < -0.2:
                return 75, "Moderate H1 bearish bias"
            elif trend < 0:
                return 60, "Weak H1 bearish bias"
            elif trend < 0.2:
                return 40, "H1 neutral"
            else:
                return 25, "H1 bullish (counter-trend)"
    
    def _score_m15_context(self, m15: List, direction: str) -> Tuple[float, str]:
        """Score M15 context alignment"""
        if len(m15) < 8:
            return 50, "Insufficient M15 data"
        trend = self._get_trend(m15[-8:])
        momentum = self._get_momentum(m15[-4:])
        aligned = (direction == "BUY" and trend > 0) or (direction == "SELL" and trend < 0)
        mom_aligned = (direction == "BUY" and momentum > 0) or (direction == "SELL" and momentum < 0)
        if aligned and mom_aligned:
            return 90, "M15 trend and momentum aligned"
        elif aligned:
            return 70, "M15 trend aligned"
        elif mom_aligned:
            return 55, "M15 momentum aligned only"
        else:
            return 35, "M15 not aligned"
    
    def _score_market_structure(self, m5: List, direction: str) -> Tuple[float, str]:
        """Score market structure quality"""
        if len(m5) < 20:
            return 50, "Insufficient data for structure"
        highs = [c.get('high', 0) for c in m5[-20:]]
        lows = [c.get('low', 0) for c in m5[-20:]]
        swing_highs = self._find_swing_points(highs, 'high')
        swing_lows = self._find_swing_points(lows, 'low')
        if direction == "BUY":
            if len(swing_lows) >= 2 and swing_lows[-1] > swing_lows[-2]:
                return 85, "Higher lows forming"
            elif len(swing_lows) >= 2 and swing_lows[-1] >= swing_lows[-2] * 0.999:
                return 65, "Equal lows holding"
            else:
                return 45, "No clear bullish structure"
        else:
            if len(swing_highs) >= 2 and swing_highs[-1] < swing_highs[-2]:
                return 85, "Lower highs forming"
            elif len(swing_highs) >= 2 and swing_highs[-1] <= swing_highs[-2] * 1.001:
                return 65, "Equal highs holding"
            else:
                return 45, "No clear bearish structure"
    
    def _find_swing_points(self, data: List, point_type: str) -> List:
        """Find swing points in data"""
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
        """Score momentum strength"""
        if len(m5) < 5:
            return 50, "Insufficient data"
        momentum = self._get_momentum(m5[-5:])
        if direction == "BUY":
            if momentum > 0.6:
                return 95, "Strong bullish momentum"
            elif momentum > 0.3:
                return 75, "Moderate bullish momentum"
            elif momentum > 0:
                return 55, "Weak bullish momentum"
            else:
                return 30, "Bearish momentum (divergent)"
        else:
            if momentum < -0.6:
                return 95, "Strong bearish momentum"
            elif momentum < -0.3:
                return 75, "Moderate bearish momentum"
            elif momentum < 0:
                return 55, "Weak bearish momentum"
            else:
                return 30, "Bullish momentum (divergent)"
    
    def _score_key_level(self, m5: List, current_price: float, direction: str) -> Tuple[float, str]:
        """Score reaction at key level"""
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
            return 95, "Strong rejection at round number"
        elif has_rejection:
            return 75, "Price rejection observed"
        elif near_round:
            return 60, "Near round number level"
        else:
            return 45, "No clear key level"
    
    def _score_rr_ratio(self, rr: float) -> Tuple[float, str]:
        """Score risk/reward ratio"""
        if rr >= 3:
            return 100, f"Excellent R:R ({rr:.1f})"
        elif rr >= 2:
            return 80, f"Good R:R ({rr:.1f})"
        elif rr >= 1.5:
            return 60, f"Acceptable R:R ({rr:.1f})"
        elif rr >= 1:
            return 40, f"Low R:R ({rr:.1f})"
        else:
            return 20, f"Poor R:R ({rr:.1f})"
    
    def _score_volatility(self, atr: float, avg_atr: float) -> Tuple[float, str]:
        """Score volatility conditions"""
        if avg_atr == 0:
            return 50, "No ATR reference"
        ratio = atr / avg_atr
        if 0.8 <= ratio <= 1.5:
            return 90, "Normal volatility"
        elif 0.5 <= ratio <= 2:
            return 70, "Acceptable volatility"
        elif ratio > 2:
            return 40, "High volatility risk"
        else:
            return 40, "Low volatility"
    
    def _score_market_regime(self, m5: List, atr: float, avg_atr: float) -> Tuple[float, str]:
        """Lightweight market regime detection"""
        if len(m5) < 20:
            return 50, "Insufficient data for regime"
        atr_ratio = atr / avg_atr if avg_atr > 0 else 1.0
        recent_candles = m5[-10:]
        ranges = [c.get('high', 0) - c.get('low', 0) for c in recent_candles]
        avg_range = sum(ranges) / len(ranges) if ranges else 0
        older_candles = m5[-20:-10]
        older_ranges = [c.get('high', 0) - c.get('low', 0) for c in older_candles]
        older_avg_range = sum(older_ranges) / len(older_ranges) if older_ranges else avg_range
        range_ratio = avg_range / older_avg_range if older_avg_range > 0 else 1.0
        closes = [c.get('close', 0) for c in recent_candles]
        if len(closes) >= 5:
            first_half = sum(closes[:5]) / 5
            second_half = sum(closes[5:]) / 5
            directional_move = abs(second_half - first_half) / avg_range if avg_range > 0 else 0
        else:
            directional_move = 0.5
        overlap_count = 0
        for i in range(1, len(recent_candles)):
            curr = recent_candles[i]
            prev = recent_candles[i-1]
            curr_low, curr_high = curr.get('low', 0), curr.get('high', 0)
            prev_low, prev_high = prev.get('low', 0), prev.get('high', 0)
            overlap = min(curr_high, prev_high) - max(curr_low, prev_low)
            if overlap > 0:
                overlap_count += 1
        overlap_ratio = overlap_count / (len(recent_candles) - 1)
        if atr_ratio >= 1.2 and directional_move > 1.5 and overlap_ratio < 0.7:
            return 95, "Strong trending regime"
        elif atr_ratio >= 0.9 and directional_move > 1.0:
            return 85, "Healthy trend regime"
        elif atr_ratio >= 0.7 and range_ratio >= 0.7:
            return 70, "Normal market regime"
        elif atr_ratio >= 0.5 or range_ratio >= 0.5:
            return 50, "Mixed/neutral regime"
        elif atr_ratio < 0.4 and overlap_ratio > 0.8:
            return 25, "Dead/compressed regime"
        else:
            return 40, "Low activity regime"
    
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
        """Calculate average ATR over longer period"""
        return self._calculate_atr(candles, period)
    
    def _is_duplicate(self, asset: Asset, direction: str, price: float) -> bool:
        """Check if signal is duplicate"""
        cutoff = datetime.utcnow() - timedelta(minutes=self.DUPLICATE_WINDOW_MINUTES)
        price_zone = self.DUPLICATE_PRICE_ZONE_PIPS if asset == Asset.EURUSD else self.DUPLICATE_PRICE_ZONE_XAU
        pip_size = 0.0001 if asset == Asset.EURUSD else 0.01
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
    
    def _determine_setup_type(self, components: List[ScoreComponent]) -> str:
        """Determine setup type based on score components"""
        struct_score = next((c.score for c in components if c.name == "Market Structure"), 0)
        pb_score = next((c.score for c in components if c.name == "Pullback Quality"), 0)
        mom_score = next((c.score for c in components if c.name == "Momentum"), 0)
        mtf_score = next((c.score for c in components if c.name == "MTF Alignment"), 0)
        if mtf_score > 80 and struct_score > 70:
            return "HTF Trend Continuation"
        elif struct_score > 80 and pb_score > 70:
            return "Structure Pullback"
        elif mom_score > 80:
            return "Momentum Breakout"
        elif pb_score > 80:
            return "Fib Retracement"
        else:
            return "Technical Setup"
    
    def _get_session_name(self, session) -> str:
        """Get readable session name"""
        hour = datetime.utcnow().hour
        if 13 <= hour <= 16:
            return "London/NY Overlap"
        elif 7 <= hour <= 12:
            return "London"
        elif 13 <= hour <= 20:
            return "New York"
        elif 0 <= hour <= 7:
            return "Asian"
        else:
            return "Off-Hours"
    
    def _log_score_breakdown(self, asset: Asset, direction: str, components: List[ScoreComponent], final_score: float):
        """Log detailed score breakdown for rejected signals"""
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
            "version": "v3",
            "mode": "confidence_based_enhanced",
            "uptime_seconds": uptime,
            "scan_count": self.scan_count,
            "signal_count": self.signal_count,
            "notification_count": self.notification_count,
            "rejection_count": self.rejection_count,
            "invalid_tokens_removed": self.invalid_tokens_removed,
            "recent_signals": len(self.recent_signals),
            "duplicate_window_minutes": self.DUPLICATE_WINDOW_MINUTES,
            "min_confidence": 60,
            "classification": {
                "strong": "80-100",
                "good": "70-79",
                "acceptable": "60-69",
                "rejected": "<60"
            },
            "prop_config": {
                "account_size": PROP_CONFIG.account_size,
                "max_daily_loss": PROP_CONFIG.max_daily_loss,
                "operational_warning": PROP_CONFIG.operational_warning,
                "risk_per_trade": f"{PROP_CONFIG.min_risk_percent}% - {PROP_CONFIG.max_risk_percent}%"
            },
            "daily_risk_status": self.position_sizer.get_daily_status()
        }


# Global instance
signal_generator_v3: Optional[SignalGeneratorV3] = None

async def init_signal_generator(db) -> SignalGeneratorV3:
    """Initialize the signal generator"""
    global signal_generator_v3
    signal_generator_v3 = SignalGeneratorV3(db)
    return signal_generator_v3
