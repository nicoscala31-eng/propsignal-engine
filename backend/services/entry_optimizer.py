"""
ENTRY OPTIMIZER V1.0 - NUMERICAL ENTRY RULES
=============================================

Based on operational data analysis:
- MAE medio = 0.99R (entry troppo precoce)
- 57% raggiunge 1R ma solo 30% TP
- SELL direction: 24% WR (disabilitato)
- Asian/London: <35% WR (disabilitato)

GOAL: Ridurre MAE da 0.99R a <0.60R
      Mantenere expectancy positiva

CHANGES:
- ONLY BUY direction
- ONLY New York session
- TP = 1.0R (invece di 1.5R)
- SL = 0.75R (ottimizzato)
- Pullback entry required (no immediate entry)
"""

import logging
from dataclasses import dataclass, field
from datetime import datetime
from typing import Dict, List, Optional, Tuple, Any
from enum import Enum
import json
from pathlib import Path

logger = logging.getLogger(__name__)

# ==================== CONFIGURATION ====================

@dataclass
class EntryOptimizerConfig:
    """
    NUMERICAL configuration - NO vague parameters
    All values are derived from operational data analysis
    """
    
    # DIRECTION FILTER (based on 51.4% BUY vs 24.1% SELL WR)
    ALLOWED_DIRECTIONS: List[str] = field(default_factory=lambda: ["BUY"])
    
    # SESSION FILTER (based on 95.3% NY vs 11.1% Asian WR)
    ALLOWED_SESSIONS: List[str] = field(default_factory=lambda: ["New York"])
    
    # TP/SL CONFIGURATION (based on 57% reaching 1R but only 30% reaching 1.5R)
    TARGET_RR: float = 1.0          # TP at 1.0R (was 1.5R)
    SL_MULTIPLIER: float = 0.75     # SL at 0.75R of structural distance
    MIN_RR_AFTER_SPREAD: float = 1.0  # Minimum acceptable RR after spread
    
    # PULLBACK ENTRY RULES (based on MAE 0.99R analysis)
    # Wait for pullback before entry to reduce MAE
    PULLBACK_MIN_ATR: float = 0.20  # Minimum pullback depth (ATR units)
    PULLBACK_MAX_ATR: float = 0.60  # Maximum pullback depth (ATR units)
    MAX_WAIT_CANDLES: int = 3       # Max candles to wait for pullback
    
    # CONFIRMATION CANDLE RULES (numerical, not descriptive)
    MIN_BODY_RATIO: float = 0.55    # Body must be >= 55% of range
    MIN_CLOSE_POSITION: float = 0.65  # Close must be in top 35% (for BUY)
    
    # ENTRY MODES FOR A/B TESTING
    ACTIVE_ENTRY_MODE: str = "pullback_entry"  # Current mode
    SIMULATION_MODES: List[str] = field(default_factory=lambda: [
        "immediate_entry",
        "delayed_entry",
        "pullback_entry"
    ])
    
    # TRACKING REQUIREMENTS
    MIN_TRADES_FOR_COMPARISON: int = 30


class EntryMode(Enum):
    IMMEDIATE = "immediate_entry"
    DELAYED = "delayed_entry"
    PULLBACK = "pullback_entry"


class RejectionReason(Enum):
    DIRECTION_BLOCKED = "direction_blocked_only_buy"
    SESSION_BLOCKED = "session_blocked_only_ny"
    NO_VALID_PULLBACK = "no_valid_pullback_entry"
    PULLBACK_TOO_SHALLOW = "pullback_too_shallow"
    PULLBACK_TOO_DEEP = "pullback_too_deep"
    NO_CONFIRMATION_CANDLE = "no_confirmation_candle"
    RR_BELOW_MINIMUM = "rr_below_1"
    CANDLE_BODY_TOO_SMALL = "candle_body_ratio_below_55pct"
    CANDLE_CLOSE_POSITION_BAD = "candle_close_position_below_65pct"


# ==================== CANDLE ANALYSIS ====================

@dataclass
class CandleMetrics:
    """Numerical candle metrics"""
    open: float
    high: float
    low: float
    close: float
    range: float
    body: float
    upper_wick: float
    lower_wick: float
    body_ratio: float
    close_position: float
    is_valid_buy: bool
    validation_failures: List[str]


def analyze_candle(open_: float, high: float, low: float, close: float) -> CandleMetrics:
    """
    Analyze candle with NUMERICAL rules only.
    
    BUY candle valid if ALL:
    - close > open (bullish)
    - body_ratio >= 0.55
    - close_position >= 0.65
    """
    range_ = high - low
    
    if range_ == 0:
        return CandleMetrics(
            open=open_, high=high, low=low, close=close,
            range=0, body=0, upper_wick=0, lower_wick=0,
            body_ratio=0, close_position=0,
            is_valid_buy=False,
            validation_failures=["range_zero"]
        )
    
    body = abs(close - open_)
    upper_wick = high - max(open_, close)
    lower_wick = min(open_, close) - low
    body_ratio = body / range_
    close_position = (close - low) / range_
    
    # Validate BUY candle
    failures = []
    
    is_bullish = close > open_
    if not is_bullish:
        failures.append("not_bullish")
    
    if body_ratio < 0.55:
        failures.append(f"body_ratio_{body_ratio:.2f}_below_0.55")
    
    if close_position < 0.65:
        failures.append(f"close_position_{close_position:.2f}_below_0.65")
    
    is_valid = len(failures) == 0
    
    return CandleMetrics(
        open=open_, high=high, low=low, close=close,
        range=range_, body=body, upper_wick=upper_wick, lower_wick=lower_wick,
        body_ratio=body_ratio, close_position=close_position,
        is_valid_buy=is_valid,
        validation_failures=failures
    )


# ==================== PULLBACK ANALYSIS ====================

@dataclass
class PullbackAnalysis:
    """Pullback entry analysis result"""
    is_valid: bool
    pullback_depth: float
    pullback_depth_atr: float
    confirmation_candle_index: int
    confirmation_metrics: Optional[CandleMetrics]
    entry_price: float
    signal_price: float
    rejection_reason: Optional[RejectionReason]
    wait_candles: int


def analyze_pullback_entry(
    signal_price: float,
    candles_after_signal: List[Dict],  # List of OHLC dicts
    atr_m5: float,
    config: EntryOptimizerConfig
) -> PullbackAnalysis:
    """
    Analyze if valid pullback entry exists within max_wait_candles.
    
    RULES (NUMERICAL):
    1. Price must retrace >= 0.20 ATR from signal price
    2. Price must NOT retrace > 0.60 ATR from signal price
    3. After pullback, need BUY confirmation candle
    4. Must happen within 3 candles
    """
    if not candles_after_signal:
        return PullbackAnalysis(
            is_valid=False,
            pullback_depth=0,
            pullback_depth_atr=0,
            confirmation_candle_index=-1,
            confirmation_metrics=None,
            entry_price=0,
            signal_price=signal_price,
            rejection_reason=RejectionReason.NO_VALID_PULLBACK,
            wait_candles=0
        )
    
    candles_to_check = candles_after_signal[:config.MAX_WAIT_CANDLES]
    
    # Find lowest low after signal (pullback depth)
    lowest_low = min(c['low'] for c in candles_to_check)
    pullback_depth = signal_price - lowest_low
    pullback_depth_atr = pullback_depth / atr_m5 if atr_m5 > 0 else 0
    
    # Check pullback depth constraints
    if pullback_depth_atr < config.PULLBACK_MIN_ATR:
        return PullbackAnalysis(
            is_valid=False,
            pullback_depth=pullback_depth,
            pullback_depth_atr=pullback_depth_atr,
            confirmation_candle_index=-1,
            confirmation_metrics=None,
            entry_price=0,
            signal_price=signal_price,
            rejection_reason=RejectionReason.PULLBACK_TOO_SHALLOW,
            wait_candles=len(candles_to_check)
        )
    
    if pullback_depth_atr > config.PULLBACK_MAX_ATR:
        return PullbackAnalysis(
            is_valid=False,
            pullback_depth=pullback_depth,
            pullback_depth_atr=pullback_depth_atr,
            confirmation_candle_index=-1,
            confirmation_metrics=None,
            entry_price=0,
            signal_price=signal_price,
            rejection_reason=RejectionReason.PULLBACK_TOO_DEEP,
            wait_candles=len(candles_to_check)
        )
    
    # Look for confirmation candle after pullback
    # Find index where lowest low occurred
    lowest_index = 0
    for i, c in enumerate(candles_to_check):
        if c['low'] == lowest_low:
            lowest_index = i
            break
    
    # Look for confirmation candle AFTER lowest low
    for i in range(lowest_index, len(candles_to_check)):
        candle = candles_to_check[i]
        metrics = analyze_candle(
            candle['open'], candle['high'], candle['low'], candle['close']
        )
        
        if metrics.is_valid_buy:
            return PullbackAnalysis(
                is_valid=True,
                pullback_depth=pullback_depth,
                pullback_depth_atr=pullback_depth_atr,
                confirmation_candle_index=i,
                confirmation_metrics=metrics,
                entry_price=candle['close'],  # Enter at close of confirmation
                signal_price=signal_price,
                rejection_reason=None,
                wait_candles=i + 1
            )
    
    # No valid confirmation candle found
    return PullbackAnalysis(
        is_valid=False,
        pullback_depth=pullback_depth,
        pullback_depth_atr=pullback_depth_atr,
        confirmation_candle_index=-1,
        confirmation_metrics=None,
        entry_price=0,
        signal_price=signal_price,
        rejection_reason=RejectionReason.NO_CONFIRMATION_CANDLE,
        wait_candles=len(candles_to_check)
    )


# ==================== ENTRY TRACKING ====================

@dataclass
class EntryTrackingRecord:
    """Complete tracking record for entry analysis"""
    timestamp: str
    symbol: str
    direction: str
    session: str
    
    # Entry mode used
    entry_mode: str
    
    # Prices
    signal_price: float
    entry_price: float
    stop_loss: float
    take_profit: float
    
    # Entry timing
    entry_delay_candles: int
    
    # ATR and pullback
    atr_m5: float
    pullback_depth_atr: float
    
    # Confirmation candle metrics
    confirmation_body_ratio: float
    confirmation_close_position: float
    
    # Outcome (filled after trade closes)
    mae_r: float = 0.0
    mfe_r: float = 0.0
    outcome: str = "pending"  # tp / sl / expired
    outcome_r: float = 0.0
    
    # Simulated outcomes for other entry modes
    sim_immediate_entry_outcome: str = "pending"
    sim_immediate_entry_r: float = 0.0
    sim_delayed_entry_outcome: str = "pending"
    sim_delayed_entry_r: float = 0.0
    sim_pullback_entry_outcome: str = "pending"
    sim_pullback_entry_r: float = 0.0


# Tracking storage
ENTRY_TRACKING_FILE = Path("/app/backend/data/entry_optimization_tracking.json")


def load_entry_tracking() -> List[Dict]:
    """Load entry tracking records"""
    try:
        if ENTRY_TRACKING_FILE.exists():
            with open(ENTRY_TRACKING_FILE, 'r') as f:
                data = json.load(f)
                return data.get('records', [])
    except Exception as e:
        logger.error(f"Error loading entry tracking: {e}")
    return []


def save_entry_tracking(records: List[Dict]):
    """Save entry tracking records"""
    try:
        ENTRY_TRACKING_FILE.parent.mkdir(parents=True, exist_ok=True)
        with open(ENTRY_TRACKING_FILE, 'w') as f:
            json.dump({
                'updated_at': datetime.utcnow().isoformat(),
                'total_records': len(records),
                'records': records
            }, f, indent=2)
    except Exception as e:
        logger.error(f"Error saving entry tracking: {e}")


def create_tracking_record(
    symbol: str,
    direction: str,
    session: str,
    signal_price: float,
    entry_price: float,
    stop_loss: float,
    take_profit: float,
    entry_delay_candles: int,
    atr_m5: float,
    pullback_depth_atr: float,
    confirmation_metrics: Optional[CandleMetrics],
    entry_mode: str = "pullback_entry"
) -> EntryTrackingRecord:
    """Create a new tracking record"""
    return EntryTrackingRecord(
        timestamp=datetime.utcnow().isoformat(),
        symbol=symbol,
        direction=direction,
        session=session,
        entry_mode=entry_mode,
        signal_price=signal_price,
        entry_price=entry_price,
        stop_loss=stop_loss,
        take_profit=take_profit,
        entry_delay_candles=entry_delay_candles,
        atr_m5=atr_m5,
        pullback_depth_atr=pullback_depth_atr,
        confirmation_body_ratio=confirmation_metrics.body_ratio if confirmation_metrics else 0,
        confirmation_close_position=confirmation_metrics.close_position if confirmation_metrics else 0
    )


# ==================== TP/SL CALCULATOR ====================

@dataclass
class TPSLResult:
    """TP/SL calculation result"""
    entry_price: float
    stop_loss: float
    take_profit: float
    sl_distance: float
    tp_distance: float
    rr_ratio: float
    is_valid: bool
    rejection_reason: Optional[str]


def calculate_optimized_tpsl(
    entry_price: float,
    structural_sl_price: float,
    config: EntryOptimizerConfig
) -> TPSLResult:
    """
    Calculate optimized TP/SL based on data analysis.
    
    RULES:
    - SL = entry - (structural_distance * 0.75)
    - TP = entry + (risk * 1.0R)
    - RR after spread must be >= 1.0
    """
    structural_distance = abs(entry_price - structural_sl_price)
    sl_distance = structural_distance * config.SL_MULTIPLIER
    
    # For BUY: SL below entry
    stop_loss = entry_price - sl_distance
    
    # TP at 1.0R
    tp_distance = sl_distance * config.TARGET_RR
    take_profit = entry_price + tp_distance
    
    # Calculate actual RR
    if sl_distance > 0:
        rr_ratio = tp_distance / sl_distance
    else:
        rr_ratio = 0
    
    # Validate
    is_valid = rr_ratio >= config.MIN_RR_AFTER_SPREAD
    rejection_reason = None if is_valid else "rr_below_1"
    
    return TPSLResult(
        entry_price=entry_price,
        stop_loss=stop_loss,
        take_profit=take_profit,
        sl_distance=sl_distance,
        tp_distance=tp_distance,
        rr_ratio=rr_ratio,
        is_valid=is_valid,
        rejection_reason=rejection_reason
    )


# ==================== ENTRY MODE COMPARISON ====================

def generate_entry_mode_comparison() -> Dict:
    """
    Generate comparison report between entry modes.
    Call after MIN_TRADES_FOR_COMPARISON trades.
    """
    records = load_entry_tracking()
    
    if len(records) < 30:
        return {
            "status": "insufficient_data",
            "trades_required": 30,
            "trades_collected": len(records),
            "message": f"Need {30 - len(records)} more trades for comparison"
        }
    
    # Group by simulated outcomes
    modes = {
        "immediate_entry": {"wins": 0, "losses": 0, "expired": 0, "mae_sum": 0, "mfe_sum": 0, "r_sum": 0},
        "delayed_entry": {"wins": 0, "losses": 0, "expired": 0, "mae_sum": 0, "mfe_sum": 0, "r_sum": 0},
        "pullback_entry": {"wins": 0, "losses": 0, "expired": 0, "mae_sum": 0, "mfe_sum": 0, "r_sum": 0}
    }
    
    for record in records:
        # Actual pullback entry outcome
        if record.get('outcome') == 'tp':
            modes['pullback_entry']['wins'] += 1
            modes['pullback_entry']['r_sum'] += 1.0  # 1R win
        elif record.get('outcome') == 'sl':
            modes['pullback_entry']['losses'] += 1
            modes['pullback_entry']['r_sum'] -= 1.0  # -1R loss
        elif record.get('outcome') == 'expired':
            modes['pullback_entry']['expired'] += 1
        
        modes['pullback_entry']['mae_sum'] += record.get('mae_r', 0)
        modes['pullback_entry']['mfe_sum'] += record.get('mfe_r', 0)
        
        # Simulated immediate entry
        sim_imm = record.get('sim_immediate_entry_outcome', '')
        if sim_imm == 'tp':
            modes['immediate_entry']['wins'] += 1
            modes['immediate_entry']['r_sum'] += 1.0
        elif sim_imm == 'sl':
            modes['immediate_entry']['losses'] += 1
            modes['immediate_entry']['r_sum'] -= 1.0
        elif sim_imm == 'expired':
            modes['immediate_entry']['expired'] += 1
        
        # Simulated delayed entry
        sim_del = record.get('sim_delayed_entry_outcome', '')
        if sim_del == 'tp':
            modes['delayed_entry']['wins'] += 1
            modes['delayed_entry']['r_sum'] += 1.0
        elif sim_del == 'sl':
            modes['delayed_entry']['losses'] += 1
            modes['delayed_entry']['r_sum'] -= 1.0
        elif sim_del == 'expired':
            modes['delayed_entry']['expired'] += 1
    
    # Calculate metrics
    results = {}
    for mode, stats in modes.items():
        total = stats['wins'] + stats['losses']
        resolved = total + stats['expired']
        
        winrate = (stats['wins'] / total * 100) if total > 0 else 0
        expectancy = (stats['r_sum'] / total) if total > 0 else 0
        avg_mae = (stats['mae_sum'] / resolved) if resolved > 0 else 0
        avg_mfe = (stats['mfe_sum'] / resolved) if resolved > 0 else 0
        expired_rate = (stats['expired'] / resolved * 100) if resolved > 0 else 0
        
        results[mode] = {
            "total_trades": total,
            "wins": stats['wins'],
            "losses": stats['losses'],
            "expired": stats['expired'],
            "winrate": round(winrate, 2),
            "expectancy_r": round(expectancy, 4),
            "avg_mae_r": round(avg_mae, 4),
            "avg_mfe_r": round(avg_mfe, 4),
            "expired_rate": round(expired_rate, 2),
            "net_r": round(stats['r_sum'], 2)
        }
    
    # Determine best mode
    best_mode = max(results.items(), key=lambda x: x[1]['expectancy_r'])[0]
    
    return {
        "status": "complete",
        "total_trades_analyzed": len(records),
        "comparison": results,
        "best_mode": best_mode,
        "recommendation": f"Use {best_mode} - highest expectancy"
    }


# ==================== FILTER FUNCTIONS ====================

def filter_direction(direction: str, config: EntryOptimizerConfig) -> Tuple[bool, Optional[RejectionReason]]:
    """Filter by direction (BUY only)"""
    if direction not in config.ALLOWED_DIRECTIONS:
        return False, RejectionReason.DIRECTION_BLOCKED
    return True, None


def filter_session(session: str, config: EntryOptimizerConfig) -> Tuple[bool, Optional[RejectionReason]]:
    """Filter by session (New York only)"""
    if session not in config.ALLOWED_SESSIONS:
        return False, RejectionReason.SESSION_BLOCKED
    return True, None


# ==================== MAIN OPTIMIZER ====================

class EntryOptimizer:
    """
    Entry Optimizer V1.0
    
    Applies NUMERICAL rules to optimize entry timing.
    Tracks all entries for statistical comparison.
    """
    
    def __init__(self, config: Optional[EntryOptimizerConfig] = None):
        self.config = config or EntryOptimizerConfig()
        self.tracking_records = load_entry_tracking()
        
        logger.info("=" * 60)
        logger.info("ENTRY OPTIMIZER V1.0 INITIALIZED")
        logger.info("=" * 60)
        logger.info(f"  Allowed directions: {self.config.ALLOWED_DIRECTIONS}")
        logger.info(f"  Allowed sessions: {self.config.ALLOWED_SESSIONS}")
        logger.info(f"  TP target: {self.config.TARGET_RR}R")
        logger.info(f"  SL multiplier: {self.config.SL_MULTIPLIER}")
        logger.info(f"  Entry mode: {self.config.ACTIVE_ENTRY_MODE}")
        logger.info(f"  Pullback range: {self.config.PULLBACK_MIN_ATR}-{self.config.PULLBACK_MAX_ATR} ATR")
        logger.info(f"  Max wait candles: {self.config.MAX_WAIT_CANDLES}")
        logger.info(f"  Min body ratio: {self.config.MIN_BODY_RATIO}")
        logger.info(f"  Min close position: {self.config.MIN_CLOSE_POSITION}")
        logger.info("=" * 60)
    
    def validate_entry(
        self,
        symbol: str,
        direction: str,
        session: str,
        signal_price: float,
        structural_sl: float,
        candles_after_signal: List[Dict],
        atr_m5: float
    ) -> Tuple[bool, Optional[EntryTrackingRecord], Optional[str]]:
        """
        Validate entry with all NUMERICAL rules.
        
        Returns:
        - is_valid: bool
        - tracking_record: if valid, complete tracking record
        - rejection_reason: if invalid, reason string
        """
        
        # 1. Filter direction
        dir_ok, dir_reason = filter_direction(direction, self.config)
        if not dir_ok:
            logger.info(f"❌ Entry rejected: {dir_reason.value}")
            return False, None, dir_reason.value
        
        # 2. Filter session
        sess_ok, sess_reason = filter_session(session, self.config)
        if not sess_ok:
            logger.info(f"❌ Entry rejected: {sess_reason.value}")
            return False, None, sess_reason.value
        
        # 3. Analyze pullback entry
        pullback = analyze_pullback_entry(
            signal_price=signal_price,
            candles_after_signal=candles_after_signal,
            atr_m5=atr_m5,
            config=self.config
        )
        
        if not pullback.is_valid:
            logger.info(f"❌ Entry rejected: {pullback.rejection_reason.value}")
            logger.info(f"   Pullback depth: {pullback.pullback_depth_atr:.2f} ATR")
            logger.info(f"   Wait candles: {pullback.wait_candles}")
            return False, None, pullback.rejection_reason.value
        
        # 4. Calculate optimized TP/SL
        tpsl = calculate_optimized_tpsl(
            entry_price=pullback.entry_price,
            structural_sl_price=structural_sl,
            config=self.config
        )
        
        if not tpsl.is_valid:
            logger.info(f"❌ Entry rejected: {tpsl.rejection_reason}")
            logger.info(f"   RR ratio: {tpsl.rr_ratio:.2f}")
            return False, None, tpsl.rejection_reason
        
        # 5. Create tracking record
        record = create_tracking_record(
            symbol=symbol,
            direction=direction,
            session=session,
            signal_price=signal_price,
            entry_price=pullback.entry_price,
            stop_loss=tpsl.stop_loss,
            take_profit=tpsl.take_profit,
            entry_delay_candles=pullback.confirmation_candle_index + 1,
            atr_m5=atr_m5,
            pullback_depth_atr=pullback.pullback_depth_atr,
            confirmation_metrics=pullback.confirmation_metrics,
            entry_mode=self.config.ACTIVE_ENTRY_MODE
        )
        
        logger.info(f"✅ Entry VALIDATED with pullback entry")
        logger.info(f"   Signal: {signal_price:.5f} → Entry: {pullback.entry_price:.5f}")
        logger.info(f"   Pullback: {pullback.pullback_depth_atr:.2f} ATR")
        logger.info(f"   Confirmation candle: body={pullback.confirmation_metrics.body_ratio:.2f}, close_pos={pullback.confirmation_metrics.close_position:.2f}")
        logger.info(f"   SL: {tpsl.stop_loss:.5f}, TP: {tpsl.take_profit:.5f}, RR: {tpsl.rr_ratio:.2f}")
        
        return True, record, None
    
    def save_record(self, record: EntryTrackingRecord):
        """Save tracking record"""
        self.tracking_records.append(record.__dict__)
        save_entry_tracking(self.tracking_records)
        logger.info(f"📊 Entry tracking saved: {len(self.tracking_records)} total records")
    
    def get_comparison_report(self) -> Dict:
        """Get entry mode comparison report"""
        return generate_entry_mode_comparison()
    
    def get_stats(self) -> Dict:
        """Get optimizer statistics"""
        return {
            "config": {
                "allowed_directions": self.config.ALLOWED_DIRECTIONS,
                "allowed_sessions": self.config.ALLOWED_SESSIONS,
                "target_rr": self.config.TARGET_RR,
                "sl_multiplier": self.config.SL_MULTIPLIER,
                "entry_mode": self.config.ACTIVE_ENTRY_MODE,
                "pullback_range_atr": f"{self.config.PULLBACK_MIN_ATR}-{self.config.PULLBACK_MAX_ATR}",
                "max_wait_candles": self.config.MAX_WAIT_CANDLES,
                "min_body_ratio": self.config.MIN_BODY_RATIO,
                "min_close_position": self.config.MIN_CLOSE_POSITION
            },
            "tracking": {
                "total_records": len(self.tracking_records),
                "trades_needed_for_comparison": max(0, 30 - len(self.tracking_records))
            }
        }


# Global instance
entry_optimizer = EntryOptimizer()
