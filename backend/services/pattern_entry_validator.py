"""
Pattern Entry Validator V1.0 - Real Edge Validation
====================================================

Transforms the system from "pattern detector" to "edge validator"

Features:
1. Entry Validation - confirms directional candle, spread, R:R
2. Market State Engine - CLOSED/LOW_VOL/TRANSITION/ACTIVE
3. Real Execution Simulation - spread, slippage, entry at next candle close
4. Anti-Overfitting Check - compares last 20 vs previous 20 trades
5. Real Confidence Calculation - based on historical performance

Usage:
    from services.pattern_entry_validator import entry_validator
    
    result = entry_validator.validate_entry(
        pattern=pattern,
        candles=candles_m5,
        spread=current_spread,
        symbol="EURUSD"
    )
    
    if result.is_valid:
        # Execute trade
    else:
        # Track as rejected (but simulate outcome)
"""

import logging
from typing import Dict, List, Optional, Tuple
from dataclasses import dataclass, field, asdict
from datetime import datetime, timedelta
from enum import Enum
import json
from pathlib import Path
import aiofiles
import asyncio

logger = logging.getLogger(__name__)


# ==================== ENUMS ====================

class MarketState(Enum):
    CLOSED = "closed"              # Market closed - block all
    LOW_VOLATILITY = "low_vol"     # ATR too low - no trades
    TRANSITION = "transition"       # Between sessions - reduce signals
    ACTIVE = "active"              # London/NY - normal trading


class EntryRejectionReason(Enum):
    NO_CONFIRMATION = "no_confirmation"       # No directional candle close
    BAD_RR = "bad_rr"                         # R:R < 1.2
    SPREAD_ISSUE = "spread_issue"             # SL < spread * 2
    LOW_VOLATILITY = "low_volatility"         # ATR too low
    MARKET_CLOSED = "market_closed"           # Market not open
    TRANSITION_PERIOD = "transition_period"   # Off-session
    UNSTABLE_PATTERN = "unstable_pattern"     # Pattern failing overfitting check
    CONFIDENCE_TOO_LOW = "confidence_too_low" # Historical confidence < threshold


# ==================== DATA CLASSES ====================

@dataclass
class EntryValidation:
    """Result of entry validation"""
    is_valid: bool
    reason: str = ""
    adjusted_entry: float = 0.0      # Entry with slippage
    adjusted_sl: float = 0.0         # SL with spread buffer
    adjusted_tp: float = 0.0         # TP adjusted
    real_rr: float = 0.0             # After adjustments
    spread_pips: float = 0.0
    slippage_pips: float = 0.0
    market_state: str = ""
    real_confidence: float = 0.0      # Based on historical
    
    # Entry timing
    entry_candle_close: bool = False  # Will enter at candle close
    confirmation_candle: bool = False # Directional confirmation
    
    def to_dict(self) -> Dict:
        return asdict(self)


@dataclass
class RejectedPattern:
    """Pattern that was detected but not executed"""
    id: str
    timestamp: str
    symbol: str
    direction: str
    pattern_type: str
    
    # Why rejected
    rejection_reason: str
    
    # Original levels
    original_entry: float
    original_sl: float
    original_tp: float
    original_rr: float
    original_confidence: float
    
    # Would-have-been outcome (simulated)
    would_have_won: Optional[bool] = None
    would_have_rr: float = 0.0
    simulated_mfe: float = 0.0
    simulated_mae: float = 0.0
    simulation_complete: bool = False
    
    # Market context
    market_state: str = ""
    atr: float = 0.0
    spread: float = 0.0
    
    def to_dict(self) -> Dict:
        return asdict(self)
    
    @classmethod
    def from_dict(cls, data: Dict) -> 'RejectedPattern':
        return cls(**{k: v for k, v in data.items() if k in cls.__dataclass_fields__})


@dataclass
class PatternPerformanceHistory:
    """Historical performance for a pattern type"""
    pattern_type: str
    total_trades: int = 0
    wins: int = 0
    losses: int = 0
    total_r: float = 0.0
    
    # Rolling windows
    last_20_wins: int = 0
    last_20_losses: int = 0
    previous_20_wins: int = 0
    previous_20_losses: int = 0
    
    # Stability check
    is_stable: bool = True
    stability_flag: str = ""
    
    @property
    def winrate(self) -> float:
        total = self.wins + self.losses
        return (self.wins / total * 100) if total > 0 else 0
    
    @property
    def expectancy(self) -> float:
        total = self.wins + self.losses
        return (self.total_r / total) if total > 0 else 0
    
    @property
    def real_confidence(self) -> float:
        """
        Real confidence based on historical performance.
        
        Formula: base + (winrate_bonus) + (expectancy_bonus) - (instability_penalty)
        """
        if self.total_trades < 10:
            return 50.0  # Default for insufficient data
        
        # Base confidence from winrate (0-40 points)
        wr_bonus = min(40, self.winrate * 0.6)
        
        # Expectancy bonus (0-30 points)
        exp_bonus = min(30, max(0, self.expectancy * 20))
        
        # Stability penalty
        stability_penalty = 0 if self.is_stable else 15
        
        # Sample size bonus (0-20 points)
        sample_bonus = min(20, self.total_trades / 5)
        
        confidence = 30 + wr_bonus + exp_bonus + sample_bonus - stability_penalty
        return min(100, max(0, confidence))
    
    @property
    def last_20_winrate(self) -> float:
        total = self.last_20_wins + self.last_20_losses
        return (self.last_20_wins / total * 100) if total > 0 else 0
    
    @property
    def previous_20_winrate(self) -> float:
        total = self.previous_20_wins + self.previous_20_losses
        return (self.previous_20_wins / total * 100) if total > 0 else 0


# ==================== CONFIGURATION ====================

@dataclass
class EntryValidatorConfig:
    """Configuration for entry validation"""
    # R:R requirements
    min_rr: float = 1.2
    
    # Spread requirements
    min_sl_spread_multiplier: float = 2.0  # SL must be > spread * 2
    
    # ATR thresholds (in price)
    min_atr_eurusd: float = 0.00025  # 2.5 pips
    min_atr_xauusd: float = 0.40      # 40 cents
    
    # Slippage simulation
    slippage_pips_eurusd: float = 0.5
    slippage_pips_xauusd: float = 5.0
    
    # Confidence thresholds
    min_confidence_to_trade: float = 55.0
    
    # Anti-overfitting
    overfitting_wr_diff_threshold: float = 20.0  # 20% difference = unstable
    
    # Confirmation candle
    require_confirmation_candle: bool = True


DEFAULT_CONFIG = EntryValidatorConfig()


# ==================== MARKET STATE ENGINE ====================

class MarketStateEngine:
    """
    Determines current market state for trading decisions.
    """
    
    def __init__(self):
        self.current_state = MarketState.CLOSED
        self.state_history: List[Dict] = []
    
    def get_market_state(self, utc_time: datetime = None, atr: float = 0, 
                         symbol: str = "EURUSD") -> MarketState:
        """
        Determine current market state.
        
        Returns:
            CLOSED - market closed, block all
            LOW_VOLATILITY - ATR too low, no trades
            TRANSITION - between sessions, reduce signals
            ACTIVE - London/NY, normal trading
        """
        if utc_time is None:
            utc_time = datetime.utcnow()
        
        hour = utc_time.hour
        weekday = utc_time.weekday()
        
        # 1. Check if market is CLOSED
        # Weekend: Friday 21:00 - Sunday 21:00 UTC
        if weekday == 4 and hour >= 21:  # Friday after 21:00
            self.current_state = MarketState.CLOSED
            return MarketState.CLOSED
        if weekday == 5:  # Saturday
            self.current_state = MarketState.CLOSED
            return MarketState.CLOSED
        if weekday == 6 and hour < 21:  # Sunday before 21:00
            self.current_state = MarketState.CLOSED
            return MarketState.CLOSED
        
        # 2. Check ATR for LOW_VOLATILITY
        min_atr = DEFAULT_CONFIG.min_atr_eurusd if 'EUR' in symbol else DEFAULT_CONFIG.min_atr_xauusd
        if atr > 0 and atr < min_atr:
            self.current_state = MarketState.LOW_VOLATILITY
            return MarketState.LOW_VOLATILITY
        
        # 3. Check session for ACTIVE vs TRANSITION
        # ACTIVE: London 07:00-16:00, NY 12:00-21:00
        if 7 <= hour < 21:  # Main trading hours
            if 7 <= hour < 12:
                self.current_state = MarketState.ACTIVE  # London
            elif 12 <= hour < 16:
                self.current_state = MarketState.ACTIVE  # London/NY Overlap
            elif 16 <= hour < 21:
                self.current_state = MarketState.ACTIVE  # NY
            else:
                self.current_state = MarketState.TRANSITION
        else:
            # Asian session / Off hours
            self.current_state = MarketState.TRANSITION
        
        return self.current_state
    
    def should_trade(self, state: MarketState = None) -> Tuple[bool, str]:
        """Check if trading is allowed in current state"""
        state = state or self.current_state
        
        if state == MarketState.CLOSED:
            return False, "Market closed"
        if state == MarketState.LOW_VOLATILITY:
            return False, "Low volatility"
        if state == MarketState.TRANSITION:
            return True, "Transition period - reduced signals"  # Allow but log
        if state == MarketState.ACTIVE:
            return True, "Active session"
        
        return False, "Unknown state"


# Global market state engine
market_state_engine = MarketStateEngine()


# ==================== ENTRY VALIDATOR ====================

class PatternEntryValidator:
    """
    Validates pattern entries with real-world constraints.
    
    Transforms pattern detection into edge validation.
    """
    
    def __init__(self, config: EntryValidatorConfig = None):
        self.config = config or DEFAULT_CONFIG
        
        # Pattern performance history
        self.pattern_history: Dict[str, PatternPerformanceHistory] = {}
        
        # Rejected patterns (for simulation)
        self.rejected_patterns: List[RejectedPattern] = []
        
        # Data persistence
        self.data_dir = Path("/app/backend/data")
        self.rejected_file = self.data_dir / "pattern_rejections.json"
        self.history_file = self.data_dir / "pattern_performance_history.json"
        
        self._loaded = False
        
        logger.info("Pattern Entry Validator V1.0 initialized")
    
    async def initialize(self):
        """Load persisted data"""
        if self._loaded:
            return
        
        self.data_dir.mkdir(parents=True, exist_ok=True)
        await self._load_data()
        self._loaded = True
    
    async def _load_data(self):
        """Load rejected patterns and performance history"""
        try:
            if self.rejected_file.exists():
                async with aiofiles.open(self.rejected_file, 'r') as f:
                    data = json.loads(await f.read())
                    self.rejected_patterns = [
                        RejectedPattern.from_dict(r) for r in data.get('rejected', [])
                    ]
            
            if self.history_file.exists():
                async with aiofiles.open(self.history_file, 'r') as f:
                    data = json.loads(await f.read())
                    for pt, hist in data.get('history', {}).items():
                        self.pattern_history[pt] = PatternPerformanceHistory(
                            pattern_type=pt,
                            total_trades=hist.get('total_trades', 0),
                            wins=hist.get('wins', 0),
                            losses=hist.get('losses', 0),
                            total_r=hist.get('total_r', 0),
                            last_20_wins=hist.get('last_20_wins', 0),
                            last_20_losses=hist.get('last_20_losses', 0),
                            previous_20_wins=hist.get('previous_20_wins', 0),
                            previous_20_losses=hist.get('previous_20_losses', 0),
                            is_stable=hist.get('is_stable', True),
                            stability_flag=hist.get('stability_flag', '')
                        )
        except Exception as e:
            logger.error(f"Error loading validator data: {e}")
    
    async def _save_data(self):
        """Save rejected patterns and performance history"""
        try:
            # Save rejected (keep last 500)
            rejected_data = {
                'updated_at': datetime.utcnow().isoformat(),
                'rejected': [r.to_dict() for r in self.rejected_patterns[-500:]]
            }
            async with aiofiles.open(self.rejected_file, 'w') as f:
                await f.write(json.dumps(rejected_data, indent=2))
            
            # Save history
            history_data = {
                'updated_at': datetime.utcnow().isoformat(),
                'history': {
                    pt: {
                        'total_trades': h.total_trades,
                        'wins': h.wins,
                        'losses': h.losses,
                        'total_r': h.total_r,
                        'last_20_wins': h.last_20_wins,
                        'last_20_losses': h.last_20_losses,
                        'previous_20_wins': h.previous_20_wins,
                        'previous_20_losses': h.previous_20_losses,
                        'is_stable': h.is_stable,
                        'stability_flag': h.stability_flag
                    }
                    for pt, h in self.pattern_history.items()
                }
            }
            async with aiofiles.open(self.history_file, 'w') as f:
                await f.write(json.dumps(history_data, indent=2))
                
        except Exception as e:
            logger.error(f"Error saving validator data: {e}")
    
    # ==================== ENTRY VALIDATION ====================
    
    def validate_entry(
        self,
        pattern_type: str,
        direction: str,
        entry_price: float,
        stop_loss: float,
        take_profit: float,
        confidence: float,
        candles: List[Dict],
        spread: float,
        atr: float,
        symbol: str
    ) -> EntryValidation:
        """
        Validate if a pattern entry should be executed.
        
        Checks:
        1. Market state (closed/low vol/transition/active)
        2. Confirmation candle (directional close)
        3. Spread issue (SL > spread * 2)
        4. R:R minimum (>= 1.2)
        5. Pattern stability (anti-overfitting)
        6. Real confidence (historical performance)
        
        Returns EntryValidation with adjusted levels for real execution.
        """
        result = EntryValidation()
        
        # 1. Check market state
        market_state = market_state_engine.get_market_state(
            utc_time=datetime.utcnow(),
            atr=atr,
            symbol=symbol
        )
        result.market_state = market_state.value
        
        can_trade, reason = market_state_engine.should_trade(market_state)
        if not can_trade:
            result.is_valid = False
            result.reason = EntryRejectionReason.MARKET_CLOSED.value if market_state == MarketState.CLOSED else EntryRejectionReason.LOW_VOLATILITY.value
            return result
        
        # 2. Check confirmation candle
        if self.config.require_confirmation_candle and len(candles) >= 2:
            last_candle = candles[-1]
            candle_direction = "BUY" if last_candle.get('close', 0) > last_candle.get('open', 0) else "SELL"
            
            if candle_direction != direction:
                result.is_valid = False
                result.reason = EntryRejectionReason.NO_CONFIRMATION.value
                result.confirmation_candle = False
                return result
            
            result.confirmation_candle = True
        
        # 3. Calculate spread in price terms
        # For EURUSD: spread is in price (e.g., 0.00008 = 0.8 pips)
        # For XAUUSD: spread is in price (e.g., 0.30 = 30 cents)
        result.spread_pips = spread
        
        # 4. Check SL distance vs spread
        if direction == "BUY":
            sl_distance = entry_price - stop_loss
        else:
            sl_distance = stop_loss - entry_price
        
        min_sl_distance = spread * self.config.min_sl_spread_multiplier
        if sl_distance < min_sl_distance:
            result.is_valid = False
            result.reason = EntryRejectionReason.SPREAD_ISSUE.value
            return result
        
        # 5. Apply slippage to entry
        slippage = self.config.slippage_pips_eurusd if 'EUR' in symbol else self.config.slippage_pips_xauusd
        pip_value = 0.0001 if 'EUR' in symbol else 0.01
        slippage_price = slippage * pip_value
        
        result.slippage_pips = slippage
        
        if direction == "BUY":
            result.adjusted_entry = entry_price + slippage_price  # Worse entry for buy
            result.adjusted_sl = stop_loss - (spread * 0.5)       # SL with spread buffer
            result.adjusted_tp = take_profit                       # TP unchanged
        else:
            result.adjusted_entry = entry_price - slippage_price  # Worse entry for sell
            result.adjusted_sl = stop_loss + (spread * 0.5)       # SL with spread buffer
            result.adjusted_tp = take_profit
        
        # 6. Calculate real R:R after adjustments
        if direction == "BUY":
            real_risk = result.adjusted_entry - result.adjusted_sl
            real_reward = result.adjusted_tp - result.adjusted_entry
        else:
            real_risk = result.adjusted_sl - result.adjusted_entry
            real_reward = result.adjusted_entry - result.adjusted_tp
        
        result.real_rr = real_reward / real_risk if real_risk > 0 else 0
        
        # 7. Check minimum R:R
        if result.real_rr < self.config.min_rr:
            result.is_valid = False
            result.reason = EntryRejectionReason.BAD_RR.value
            return result
        
        # 8. Check pattern stability (anti-overfitting)
        if pattern_type in self.pattern_history:
            history = self.pattern_history[pattern_type]
            if not history.is_stable:
                result.is_valid = False
                result.reason = EntryRejectionReason.UNSTABLE_PATTERN.value
                return result
        
        # 9. Calculate real confidence
        result.real_confidence = self._calculate_real_confidence(pattern_type, confidence)
        
        if result.real_confidence < self.config.min_confidence_to_trade:
            result.is_valid = False
            result.reason = EntryRejectionReason.CONFIDENCE_TOO_LOW.value
            return result
        
        # Entry at next candle close
        result.entry_candle_close = True
        result.is_valid = True
        result.reason = "entry_valid"
        
        return result
    
    def _calculate_real_confidence(self, pattern_type: str, original_confidence: float) -> float:
        """
        Calculate real confidence based on historical performance.
        
        Not based on pattern detection, but on actual results.
        """
        if pattern_type not in self.pattern_history:
            # New pattern - use original confidence with penalty
            return original_confidence * 0.7  # 30% penalty for no history
        
        history = self.pattern_history[pattern_type]
        
        # Use historical confidence
        historical_confidence = history.real_confidence
        
        # Blend: 70% historical, 30% pattern detection
        blended = (historical_confidence * 0.7) + (original_confidence * 0.3)
        
        return min(100, max(0, blended))
    
    # ==================== REJECTED PATTERN TRACKING ====================
    
    async def track_rejected_pattern(
        self,
        pattern_type: str,
        direction: str,
        symbol: str,
        entry_price: float,
        stop_loss: float,
        take_profit: float,
        confidence: float,
        rejection_reason: str,
        market_state: str,
        atr: float,
        spread: float
    ) -> str:
        """
        Track a pattern that was detected but not executed.
        
        Will simulate outcome later for comparison.
        """
        import uuid
        
        pattern_id = f"REJ_{symbol}_{pattern_type}_{datetime.utcnow().strftime('%Y%m%d_%H%M%S')}_{uuid.uuid4().hex[:6]}"
        
        # Calculate original R:R
        if direction == "BUY":
            risk = entry_price - stop_loss
            reward = take_profit - entry_price
        else:
            risk = stop_loss - entry_price
            reward = entry_price - take_profit
        
        original_rr = reward / risk if risk > 0 else 0
        
        rejected = RejectedPattern(
            id=pattern_id,
            timestamp=datetime.utcnow().isoformat(),
            symbol=symbol,
            direction=direction,
            pattern_type=pattern_type,
            rejection_reason=rejection_reason,
            original_entry=entry_price,
            original_sl=stop_loss,
            original_tp=take_profit,
            original_rr=original_rr,
            original_confidence=confidence,
            market_state=market_state,
            atr=atr,
            spread=spread
        )
        
        self.rejected_patterns.append(rejected)
        await self._save_data()
        
        logger.info(f"[VALIDATOR] Rejected pattern tracked: {pattern_id} | Reason: {rejection_reason}")
        
        return pattern_id
    
    async def simulate_rejected_outcome(self, pattern_id: str, current_price: float):
        """
        Simulate outcome for a rejected pattern.
        
        Updates would_have_won, would_have_rr, simulated_mfe, simulated_mae.
        """
        for rejected in self.rejected_patterns:
            if rejected.id != pattern_id or rejected.simulation_complete:
                continue
            
            direction = rejected.direction
            entry = rejected.original_entry
            sl = rejected.original_sl
            tp = rejected.original_tp
            
            # Calculate excursions
            if direction == "BUY":
                risk = entry - sl
                if risk <= 0:
                    continue
                
                # Favorable if price went up
                favorable = max(0, current_price - entry)
                adverse = max(0, entry - current_price)
                
                rejected.simulated_mfe = max(rejected.simulated_mfe, favorable / risk)
                rejected.simulated_mae = max(rejected.simulated_mae, adverse / risk)
                
                # Check if would have hit TP or SL
                if current_price >= tp:
                    rejected.would_have_won = True
                    rejected.would_have_rr = (tp - entry) / risk
                    rejected.simulation_complete = True
                elif current_price <= sl:
                    rejected.would_have_won = False
                    rejected.would_have_rr = -1.0
                    rejected.simulation_complete = True
            
            else:  # SELL
                risk = sl - entry
                if risk <= 0:
                    continue
                
                favorable = max(0, entry - current_price)
                adverse = max(0, current_price - entry)
                
                rejected.simulated_mfe = max(rejected.simulated_mfe, favorable / risk)
                rejected.simulated_mae = max(rejected.simulated_mae, adverse / risk)
                
                if current_price <= tp:
                    rejected.would_have_won = True
                    rejected.would_have_rr = (entry - tp) / risk
                    rejected.simulation_complete = True
                elif current_price >= sl:
                    rejected.would_have_won = False
                    rejected.would_have_rr = -1.0
                    rejected.simulation_complete = True
        
        await self._save_data()
    
    async def update_prices_for_rejections(self, symbol: str, current_price: float):
        """Update simulations for all pending rejected patterns"""
        for rejected in self.rejected_patterns:
            if rejected.symbol == symbol and not rejected.simulation_complete:
                await self.simulate_rejected_outcome(rejected.id, current_price)
    
    # ==================== PERFORMANCE TRACKING ====================
    
    def update_pattern_performance(self, pattern_type: str, won: bool, final_r: float):
        """
        Update pattern performance history after a trade completes.
        
        Includes anti-overfitting check.
        """
        if pattern_type not in self.pattern_history:
            self.pattern_history[pattern_type] = PatternPerformanceHistory(pattern_type=pattern_type)
        
        history = self.pattern_history[pattern_type]
        
        # Update totals
        history.total_trades += 1
        history.total_r += final_r
        if won:
            history.wins += 1
        else:
            history.losses += 1
        
        # Update rolling windows
        if history.total_trades % 20 == 0:
            # Shift windows
            history.previous_20_wins = history.last_20_wins
            history.previous_20_losses = history.last_20_losses
            history.last_20_wins = 0
            history.last_20_losses = 0
        
        # Update last 20
        if won:
            history.last_20_wins += 1
        else:
            history.last_20_losses += 1
        
        # Anti-overfitting check (every 20 trades)
        if history.total_trades >= 40 and history.total_trades % 20 == 0:
            self._check_pattern_stability(history)
    
    def _check_pattern_stability(self, history: PatternPerformanceHistory):
        """
        Check if pattern performance is stable.
        
        If difference between last 20 and previous 20 winrate > threshold,
        flag as unstable.
        """
        wr_diff = abs(history.last_20_winrate - history.previous_20_winrate)
        
        if wr_diff > self.config.overfitting_wr_diff_threshold:
            history.is_stable = False
            history.stability_flag = f"unstable: WR diff {wr_diff:.1f}% (last: {history.last_20_winrate:.1f}%, prev: {history.previous_20_winrate:.1f}%)"
            logger.warning(f"[VALIDATOR] Pattern {history.pattern_type} flagged as UNSTABLE: {history.stability_flag}")
        else:
            history.is_stable = True
            history.stability_flag = ""
    
    # ==================== STATISTICS ====================
    
    def get_rejected_stats(self) -> Dict:
        """Get statistics on rejected patterns"""
        total = len(self.rejected_patterns)
        simulated = len([r for r in self.rejected_patterns if r.simulation_complete])
        
        would_have_won = len([r for r in self.rejected_patterns if r.would_have_won is True])
        would_have_lost = len([r for r in self.rejected_patterns if r.would_have_won is False])
        
        # By rejection reason
        by_reason = {}
        for r in self.rejected_patterns:
            reason = r.rejection_reason
            if reason not in by_reason:
                by_reason[reason] = {'count': 0, 'would_have_won': 0}
            by_reason[reason]['count'] += 1
            if r.would_have_won:
                by_reason[reason]['would_have_won'] += 1
        
        # Calculate what we missed
        missed_r = sum(r.would_have_rr for r in self.rejected_patterns if r.would_have_won)
        
        return {
            "total_rejected": total,
            "simulations_complete": simulated,
            "would_have_won": would_have_won,
            "would_have_lost": would_have_lost,
            "would_have_winrate": round(would_have_won / max(1, would_have_won + would_have_lost) * 100, 1),
            "missed_r_total": round(missed_r, 2),
            "by_rejection_reason": by_reason,
            "avg_simulated_mfe": round(sum(r.simulated_mfe for r in self.rejected_patterns) / max(1, total), 2),
            "avg_simulated_mae": round(sum(r.simulated_mae for r in self.rejected_patterns) / max(1, total), 2),
            "note": "Shows what we would have captured if we ignored the filter"
        }
    
    def get_pattern_history_stats(self) -> Dict:
        """Get pattern performance history statistics"""
        return {
            pt: {
                "total_trades": h.total_trades,
                "wins": h.wins,
                "losses": h.losses,
                "winrate": round(h.winrate, 1),
                "expectancy": round(h.expectancy, 3),
                "real_confidence": round(h.real_confidence, 1),
                "is_stable": h.is_stable,
                "stability_flag": h.stability_flag,
                "last_20_winrate": round(h.last_20_winrate, 1),
                "previous_20_winrate": round(h.previous_20_winrate, 1)
            }
            for pt, h in self.pattern_history.items()
        }
    
    def get_full_validation_report(self) -> Dict:
        """Get complete validation report"""
        return {
            "report_generated": datetime.utcnow().isoformat(),
            "market_state": market_state_engine.current_state.value,
            "rejected_patterns": self.get_rejected_stats(),
            "pattern_performance": self.get_pattern_history_stats(),
            "config": {
                "min_rr": self.config.min_rr,
                "min_sl_spread_multiplier": self.config.min_sl_spread_multiplier,
                "min_confidence": self.config.min_confidence_to_trade,
                "overfitting_threshold": self.config.overfitting_wr_diff_threshold
            },
            "note": "EDGE VALIDATOR - Shows real vs filtered performance"
        }


# Global instance
entry_validator = PatternEntryValidator()
