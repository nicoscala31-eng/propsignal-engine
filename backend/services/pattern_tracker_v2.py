"""
Pattern Tracker V2.0 - Advanced Pattern Performance Tracking
=============================================================

IMPROVEMENTS OVER V1:
- Tracks ALL active patterns simultaneously (not just primary)
- Pattern combination analysis
- Per-pattern performance metrics
- Pattern count correlation
- Real edge measurement

Key Features:
1. Multi-pattern logging per trade
2. Automatic aggregation by pattern type
3. Combination analysis (which patterns together = edge)
4. Pattern count quality filter
5. Complete MFE/MAE/R tracking

Usage:
    from services.pattern_tracker_v2 import pattern_tracker_v2
    
    # Track a trade with multiple patterns
    await pattern_tracker_v2.track_trade(
        symbol="EURUSD",
        direction="BUY",
        patterns={
            "trend_structure": True,
            "fib_pullback": True,
            "breakout_retest": False,
            "liquidity_sweep": False,
            "flag_pattern": False
        },
        ...
    )
"""

import json
import logging
import asyncio
from typing import Dict, List, Optional, Set, Tuple
from dataclasses import dataclass, field, asdict
from datetime import datetime, timedelta
from pathlib import Path
from enum import Enum
from collections import defaultdict
import aiofiles
import uuid

logger = logging.getLogger(__name__)


# ==================== ENUMS ====================

class TradeOutcome(Enum):
    PENDING = "pending"
    TP_HIT = "tp_hit"
    SL_HIT = "sl_hit"
    EXPIRED = "expired"
    BREAKEVEN = "breakeven"


PATTERN_TYPES = [
    "trend_structure",
    "fib_pullback", 
    "breakout_retest",
    "liquidity_sweep",
    "flag_pattern"
]


# ==================== DATA CLASSES ====================

@dataclass
class PatternFlags:
    """All pattern flags for a trade"""
    trend_structure: bool = False
    fib_pullback: bool = False
    breakout_retest: bool = False
    liquidity_sweep: bool = False
    flag_pattern: bool = False
    
    def to_dict(self) -> Dict[str, bool]:
        return asdict(self)
    
    @classmethod
    def from_dict(cls, data: Dict) -> 'PatternFlags':
        return cls(**{k: v for k, v in data.items() if k in cls.__dataclass_fields__})
    
    @property
    def active_patterns(self) -> List[str]:
        """Get list of active pattern names"""
        return [p for p in PATTERN_TYPES if getattr(self, p, False)]
    
    @property
    def pattern_count(self) -> int:
        """Count of active patterns"""
        return len(self.active_patterns)
    
    @property
    def combination_key(self) -> str:
        """Get unique key for this pattern combination"""
        active = sorted(self.active_patterns)
        return "+".join(active) if active else "none"


@dataclass
class TrackedTradeV2:
    """Trade with comprehensive pattern tracking"""
    # Identity
    id: str
    symbol: str
    direction: str
    timestamp_detected: str
    
    # Trade levels
    entry_price: float
    stop_loss: float
    take_profit: float
    
    # Context
    atr: float
    session: str
    trend_h1: str
    trend_m15: str
    confidence: float
    
    # Pattern flags (ALL patterns, not just primary)
    patterns: Dict[str, bool] = field(default_factory=dict)
    primary_pattern: str = ""  # The main trigger pattern
    pattern_count: int = 0
    combination_key: str = ""
    
    # Outcome tracking
    outcome: str = "pending"
    timestamp_closed: str = ""
    close_price: float = 0.0
    
    # Excursion tracking
    mfe: float = 0.0  # Max Favorable Excursion in R
    mae: float = 0.0  # Max Adverse Excursion in R
    mfe_price: float = 0.0
    mae_price: float = 0.0
    final_r: float = 0.0
    
    # Execution flags
    executed: bool = False
    simulated: bool = True
    
    def to_dict(self) -> Dict:
        return asdict(self)
    
    @classmethod
    def from_dict(cls, data: Dict) -> 'TrackedTradeV2':
        valid_fields = {k: v for k, v in data.items() if k in cls.__dataclass_fields__}
        return cls(**valid_fields)
    
    @property
    def risk(self) -> float:
        """Risk in price units"""
        if self.direction == "BUY":
            return max(0.00001, self.entry_price - self.stop_loss)
        return max(0.00001, self.stop_loss - self.entry_price)
    
    @property
    def reward(self) -> float:
        """Reward in price units"""
        if self.direction == "BUY":
            return self.take_profit - self.entry_price
        return self.entry_price - self.take_profit
    
    @property
    def risk_reward(self) -> float:
        """R:R ratio"""
        return self.reward / self.risk if self.risk > 0 else 0
    
    def calculate_final_r(self) -> float:
        """Calculate final R achieved"""
        if self.outcome == "pending" or self.close_price == 0:
            return 0
        
        if self.direction == "BUY":
            profit = self.close_price - self.entry_price
        else:
            profit = self.entry_price - self.close_price
        
        return profit / self.risk if self.risk > 0 else 0


@dataclass
class PatternStats:
    """Statistics for a single pattern type"""
    pattern_name: str
    total_trades: int = 0
    wins: int = 0
    losses: int = 0
    expired: int = 0
    
    total_r: float = 0.0
    total_mfe: float = 0.0
    total_mae: float = 0.0
    
    @property
    def winrate(self) -> float:
        total = self.wins + self.losses
        return (self.wins / total * 100) if total > 0 else 0
    
    @property
    def avg_r(self) -> float:
        return self.total_r / self.total_trades if self.total_trades > 0 else 0
    
    @property
    def expectancy(self) -> float:
        """Expected R per trade"""
        total = self.wins + self.losses
        return self.total_r / total if total > 0 else 0
    
    @property
    def avg_mfe(self) -> float:
        return self.total_mfe / self.total_trades if self.total_trades > 0 else 0
    
    @property
    def avg_mae(self) -> float:
        return self.total_mae / self.total_trades if self.total_trades > 0 else 0
    
    @property
    def profit_factor(self) -> float:
        """Gross profit / Gross loss"""
        # Approximate from win/loss ratio and avg R
        if self.losses == 0:
            return float('inf') if self.wins > 0 else 0
        if self.wins == 0:
            return 0
        # Assuming average win is +RR and average loss is -1R
        avg_win = self.total_r / self.wins if self.wins > 0 and self.total_r > 0 else 1.5
        gross_profit = self.wins * max(avg_win, 0)
        gross_loss = self.losses * 1  # 1R loss
        return gross_profit / gross_loss if gross_loss > 0 else 0
    
    def to_dict(self) -> Dict:
        return {
            "pattern": self.pattern_name,
            "trades": self.total_trades,
            "wins": self.wins,
            "losses": self.losses,
            "expired": self.expired,
            "winrate": round(self.winrate, 1),
            "total_r": round(self.total_r, 2),
            "avg_r": round(self.avg_r, 3),
            "expectancy": round(self.expectancy, 3),
            "avg_mfe": round(self.avg_mfe, 2),
            "avg_mae": round(self.avg_mae, 2),
            "profit_factor": round(self.profit_factor, 2),
            "statistically_valid": self.total_trades >= 50
        }


@dataclass
class CombinationStats:
    """Statistics for a pattern combination"""
    combination: str
    patterns: List[str] = field(default_factory=list)
    total_trades: int = 0
    wins: int = 0
    losses: int = 0
    total_r: float = 0.0
    total_mfe: float = 0.0
    total_mae: float = 0.0
    
    @property
    def winrate(self) -> float:
        total = self.wins + self.losses
        return (self.wins / total * 100) if total > 0 else 0
    
    @property
    def expectancy(self) -> float:
        total = self.wins + self.losses
        return self.total_r / total if total > 0 else 0
    
    @property
    def avg_mfe(self) -> float:
        return self.total_mfe / self.total_trades if self.total_trades > 0 else 0
    
    def to_dict(self) -> Dict:
        return {
            "combination": self.combination,
            "patterns": self.patterns,
            "pattern_count": len(self.patterns),
            "trades": self.total_trades,
            "wins": self.wins,
            "losses": self.losses,
            "winrate": round(self.winrate, 1),
            "total_r": round(self.total_r, 2),
            "expectancy": round(self.expectancy, 3),
            "avg_mfe": round(self.avg_mfe, 2),
            "statistically_valid": self.total_trades >= 30
        }


# ==================== MAIN TRACKER ====================

class PatternTrackerV2:
    """
    Advanced Pattern Performance Tracker V2.
    
    Tracks ALL patterns simultaneously and measures real edge.
    """
    
    def __init__(self):
        self.data_dir = Path("/app/backend/data")
        self.data_file = self.data_dir / "pattern_tracking_v2.json"
        
        # Active and completed trades
        self.pending_trades: Dict[str, TrackedTradeV2] = {}
        self.completed_trades: List[TrackedTradeV2] = []
        
        # Aggregated statistics
        self.pattern_stats: Dict[str, PatternStats] = {}
        self.combination_stats: Dict[str, CombinationStats] = {}
        self.pattern_count_stats: Dict[int, Dict] = {}  # By number of patterns
        
        # Configuration
        self.check_interval = 30
        self.max_age_hours = 24
        self.max_completed = 1000  # Keep last 1000 trades
        
        # State
        self._loaded = False
        self._running = False
        self._task: Optional[asyncio.Task] = None
        
        # Initialize pattern stats
        for pt in PATTERN_TYPES:
            self.pattern_stats[pt] = PatternStats(pattern_name=pt)
        
        logger.info("Pattern Tracker V2.0 initialized")
    
    # ==================== LIFECYCLE ====================
    
    async def initialize(self):
        """Load data and prepare tracker"""
        if self._loaded:
            return
        
        self.data_dir.mkdir(parents=True, exist_ok=True)
        await self._load_data()
        self._recalculate_stats()
        self._loaded = True
        
        logger.info(f"Pattern Tracker V2 loaded: {len(self.pending_trades)} pending, "
                   f"{len(self.completed_trades)} completed")
    
    async def start(self):
        """Start tracking loop"""
        if self._running:
            return
        
        await self.initialize()
        self._running = True
        self._task = asyncio.create_task(self._run_loop())
        logger.info("Pattern Tracker V2 started")
    
    async def stop(self):
        """Stop tracking loop"""
        self._running = False
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
        await self._save_data()
        logger.info("Pattern Tracker V2 stopped")
    
    # ==================== DATA PERSISTENCE ====================
    
    async def _load_data(self):
        """Load from JSON file"""
        try:
            if self.data_file.exists():
                async with aiofiles.open(self.data_file, 'r') as f:
                    data = json.loads(await f.read())
                
                for t_data in data.get('pending', []):
                    trade = TrackedTradeV2.from_dict(t_data)
                    self.pending_trades[trade.id] = trade
                
                for t_data in data.get('completed', []):
                    trade = TrackedTradeV2.from_dict(t_data)
                    self.completed_trades.append(trade)
                
        except Exception as e:
            logger.error(f"Error loading pattern data V2: {e}")
    
    async def _save_data(self):
        """Save to JSON file"""
        try:
            data = {
                'updated_at': datetime.utcnow().isoformat(),
                'version': '2.0',
                'pending': [t.to_dict() for t in self.pending_trades.values()],
                'completed': [t.to_dict() for t in self.completed_trades[-self.max_completed:]]
            }
            
            async with aiofiles.open(self.data_file, 'w') as f:
                await f.write(json.dumps(data, indent=2))
                
        except Exception as e:
            logger.error(f"Error saving pattern data V2: {e}")
    
    # ==================== TRADE TRACKING ====================
    
    async def track_trade(
        self,
        symbol: str,
        direction: str,
        patterns: Dict[str, bool],
        primary_pattern: str,
        entry_price: float,
        stop_loss: float,
        take_profit: float,
        atr: float,
        session: str,
        trend_h1: str,
        trend_m15: str,
        confidence: float,
        executed: bool = False
    ) -> str:
        """
        Track a new trade with ALL active patterns.
        
        Args:
            patterns: Dict of {pattern_name: active_bool} for ALL patterns
            primary_pattern: The main trigger pattern
            
        Returns:
            Trade ID
        """
        trade_id = f"{symbol}_{primary_pattern}_{datetime.utcnow().strftime('%Y%m%d_%H%M%S')}_{uuid.uuid4().hex[:6]}"
        
        # Build pattern flags
        pattern_flags = PatternFlags(**{k: v for k, v in patterns.items() if k in PATTERN_TYPES})
        
        trade = TrackedTradeV2(
            id=trade_id,
            symbol=symbol,
            direction=direction,
            timestamp_detected=datetime.utcnow().isoformat(),
            entry_price=entry_price,
            stop_loss=stop_loss,
            take_profit=take_profit,
            atr=atr,
            session=session,
            trend_h1=trend_h1,
            trend_m15=trend_m15,
            confidence=confidence,
            patterns=pattern_flags.to_dict(),
            primary_pattern=primary_pattern,
            pattern_count=pattern_flags.pattern_count,
            combination_key=pattern_flags.combination_key,
            executed=executed,
            simulated=not executed,
            mfe_price=entry_price,
            mae_price=entry_price
        )
        
        self.pending_trades[trade_id] = trade
        await self._save_data()
        
        active_patterns = pattern_flags.active_patterns
        logger.info(f"[TRACKER V2] New trade: {trade_id} | "
                   f"Patterns: {active_patterns} ({len(active_patterns)} active) | "
                   f"Primary: {primary_pattern}")
        
        return trade_id
    
    async def update_price(self, symbol: str, current_price: float):
        """Update MFE/MAE and check for TP/SL"""
        trades_to_close = []
        
        for trade_id, trade in list(self.pending_trades.items()):
            if trade.symbol != symbol:
                continue
            
            risk = trade.risk
            if risk <= 0:
                continue
            
            # Update MFE/MAE
            if trade.direction == "BUY":
                favorable = current_price - trade.entry_price
                adverse = trade.entry_price - current_price
                
                if current_price > trade.mfe_price:
                    trade.mfe_price = current_price
                    trade.mfe = favorable / risk
                
                if current_price < trade.mae_price:
                    trade.mae_price = current_price
                    trade.mae = adverse / risk
                
                # Check TP/SL
                if current_price >= trade.take_profit:
                    trades_to_close.append((trade_id, TradeOutcome.TP_HIT, current_price))
                elif current_price <= trade.stop_loss:
                    trades_to_close.append((trade_id, TradeOutcome.SL_HIT, current_price))
            
            else:  # SELL
                favorable = trade.entry_price - current_price
                adverse = current_price - trade.entry_price
                
                if current_price < trade.mfe_price:
                    trade.mfe_price = current_price
                    trade.mfe = favorable / risk
                
                if current_price > trade.mae_price:
                    trade.mae_price = current_price
                    trade.mae = adverse / risk
                
                # Check TP/SL
                if current_price <= trade.take_profit:
                    trades_to_close.append((trade_id, TradeOutcome.TP_HIT, current_price))
                elif current_price >= trade.stop_loss:
                    trades_to_close.append((trade_id, TradeOutcome.SL_HIT, current_price))
        
        # Close trades
        for trade_id, outcome, price in trades_to_close:
            await self._close_trade(trade_id, outcome, price)
    
    async def _close_trade(self, trade_id: str, outcome: TradeOutcome, close_price: float):
        """Close a trade and update statistics"""
        if trade_id not in self.pending_trades:
            return
        
        trade = self.pending_trades.pop(trade_id)
        trade.outcome = outcome.value
        trade.timestamp_closed = datetime.utcnow().isoformat()
        trade.close_price = close_price
        trade.final_r = trade.calculate_final_r()
        
        self.completed_trades.append(trade)
        
        # Update pattern stats
        self._update_stats_for_trade(trade)
        
        await self._save_data()
        
        logger.info(f"[TRACKER V2] Trade closed: {trade_id} | {outcome.value} | "
                   f"Final R: {trade.final_r:.2f} | MFE: {trade.mfe:.2f}R | MAE: {trade.mae:.2f}R")
    
    async def check_expired(self):
        """Check for expired trades"""
        now = datetime.utcnow()
        max_age = timedelta(hours=self.max_age_hours)
        
        to_expire = []
        for trade_id, trade in self.pending_trades.items():
            try:
                detected = datetime.fromisoformat(trade.timestamp_detected)
                if now - detected > max_age:
                    to_expire.append(trade_id)
            except:
                pass
        
        for trade_id in to_expire:
            trade = self.pending_trades[trade_id]
            await self._close_trade(trade_id, TradeOutcome.EXPIRED, trade.mfe_price)
    
    # ==================== TRACKING LOOP ====================
    
    async def _run_loop(self):
        """Main tracking loop"""
        while self._running:
            try:
                await self.check_expired()
                await self._save_data()
                await asyncio.sleep(self.check_interval)
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"Tracker V2 loop error: {e}")
                await asyncio.sleep(5)
    
    # ==================== STATISTICS ====================
    
    def _update_stats_for_trade(self, trade: TrackedTradeV2):
        """Update all statistics for a completed trade"""
        # Update per-pattern stats
        for pattern_name, is_active in trade.patterns.items():
            if is_active and pattern_name in self.pattern_stats:
                stats = self.pattern_stats[pattern_name]
                stats.total_trades += 1
                stats.total_mfe += trade.mfe
                stats.total_mae += trade.mae
                stats.total_r += trade.final_r
                
                if trade.outcome == "tp_hit":
                    stats.wins += 1
                elif trade.outcome == "sl_hit":
                    stats.losses += 1
                else:
                    stats.expired += 1
        
        # Update combination stats
        combo_key = trade.combination_key
        if combo_key not in self.combination_stats:
            patterns = [p for p, v in trade.patterns.items() if v]
            self.combination_stats[combo_key] = CombinationStats(
                combination=combo_key,
                patterns=patterns
            )
        
        combo_stats = self.combination_stats[combo_key]
        combo_stats.total_trades += 1
        combo_stats.total_r += trade.final_r
        combo_stats.total_mfe += trade.mfe
        combo_stats.total_mae += trade.mae
        
        if trade.outcome == "tp_hit":
            combo_stats.wins += 1
        elif trade.outcome == "sl_hit":
            combo_stats.losses += 1
        
        # Update pattern count stats
        count = trade.pattern_count
        if count not in self.pattern_count_stats:
            self.pattern_count_stats[count] = {
                'trades': 0, 'wins': 0, 'losses': 0, 'total_r': 0
            }
        
        self.pattern_count_stats[count]['trades'] += 1
        self.pattern_count_stats[count]['total_r'] += trade.final_r
        if trade.outcome == "tp_hit":
            self.pattern_count_stats[count]['wins'] += 1
        elif trade.outcome == "sl_hit":
            self.pattern_count_stats[count]['losses'] += 1
    
    def _recalculate_stats(self):
        """Recalculate all stats from completed trades"""
        # Reset stats
        for pt in PATTERN_TYPES:
            self.pattern_stats[pt] = PatternStats(pattern_name=pt)
        self.combination_stats = {}
        self.pattern_count_stats = {}
        
        # Recalculate from completed trades
        for trade in self.completed_trades:
            self._update_stats_for_trade(trade)
    
    # ==================== ANALYSIS ====================
    
    def get_pattern_performance(self, pattern_type: str = None) -> Dict:
        """
        Get performance statistics for a pattern type.
        
        If pattern_type is None, returns all patterns.
        """
        if pattern_type:
            if pattern_type in self.pattern_stats:
                return self.pattern_stats[pattern_type].to_dict()
            return {"error": f"Unknown pattern: {pattern_type}"}
        
        return {pt: stats.to_dict() for pt, stats in self.pattern_stats.items()}
    
    def get_combination_performance(self) -> Dict:
        """Get performance by pattern combinations"""
        combos = sorted(
            self.combination_stats.values(),
            key=lambda x: x.expectancy,
            reverse=True
        )
        
        return {
            "total_combinations": len(combos),
            "combinations": [c.to_dict() for c in combos],
            "top_5_by_winrate": [c.to_dict() for c in sorted(combos, key=lambda x: x.winrate, reverse=True)[:5]],
            "top_5_by_expectancy": [c.to_dict() for c in sorted(combos, key=lambda x: x.expectancy, reverse=True)[:5]]
        }
    
    def get_pattern_count_analysis(self) -> Dict:
        """Analyze performance by number of active patterns"""
        results = {}
        
        for count, data in sorted(self.pattern_count_stats.items()):
            total = data['wins'] + data['losses']
            winrate = (data['wins'] / total * 100) if total > 0 else 0
            expectancy = (data['total_r'] / total) if total > 0 else 0
            
            results[f"{count}_patterns"] = {
                "pattern_count": count,
                "trades": data['trades'],
                "wins": data['wins'],
                "losses": data['losses'],
                "winrate": round(winrate, 1),
                "total_r": round(data['total_r'], 2),
                "expectancy": round(expectancy, 3)
            }
        
        return results
    
    def get_full_analysis(self) -> Dict:
        """
        Complete pattern performance analysis.
        
        This is the anti-illusion system - shows real edge.
        """
        # Overall stats
        all_trades = self.completed_trades
        wins = len([t for t in all_trades if t.outcome == "tp_hit"])
        losses = len([t for t in all_trades if t.outcome == "sl_hit"])
        total = wins + losses
        total_r = sum(t.final_r for t in all_trades if t.outcome in ["tp_hit", "sl_hit"])
        total_mfe = sum(t.mfe for t in all_trades)
        total_mae = sum(t.mae for t in all_trades)
        
        overall = {
            "total_trades": len(all_trades),
            "wins": wins,
            "losses": losses,
            "expired": len([t for t in all_trades if t.outcome == "expired"]),
            "winrate": round(wins / total * 100, 1) if total > 0 else 0,
            "total_r": round(total_r, 2),
            "expectancy": round(total_r / total, 3) if total > 0 else 0,
            "avg_mfe": round(total_mfe / len(all_trades), 2) if all_trades else 0,
            "avg_mae": round(total_mae / len(all_trades), 2) if all_trades else 0,
            "statistically_valid": total >= 50
        }
        
        # Pattern ranking by expectancy
        pattern_ranking = sorted(
            [(pt, stats) for pt, stats in self.pattern_stats.items() if stats.total_trades > 0],
            key=lambda x: x[1].expectancy,
            reverse=True
        )
        
        return {
            "report_generated": datetime.utcnow().isoformat(),
            "version": "2.0",
            "overall": overall,
            "by_pattern": self.get_pattern_performance(),
            "pattern_ranking": [
                {"rank": i+1, **self.pattern_stats[pt].to_dict()}
                for i, (pt, _) in enumerate(pattern_ranking)
            ],
            "by_combination": self.get_combination_performance(),
            "by_pattern_count": self.get_pattern_count_analysis(),
            "recommendations": self._generate_recommendations(),
            "note": "ANTI-ILLUSION SYSTEM - Real edge measurement"
        }
    
    def _generate_recommendations(self) -> List[str]:
        """Generate recommendations based on data"""
        recs = []
        
        # Check if we have enough data
        total = sum(s.total_trades for s in self.pattern_stats.values())
        if total < 50:
            recs.append(f"⚠️ Insufficient data ({total} trades). Need 50+ for statistical validity.")
            return recs
        
        # Find best/worst patterns
        valid_patterns = [(pt, s) for pt, s in self.pattern_stats.items() 
                         if s.total_trades >= 10]
        
        if valid_patterns:
            best = max(valid_patterns, key=lambda x: x[1].expectancy)
            worst = min(valid_patterns, key=lambda x: x[1].expectancy)
            
            if best[1].expectancy > 0:
                recs.append(f"✅ Best pattern: {best[0]} (expectancy: +{best[1].expectancy:.2f}R)")
            
            if worst[1].expectancy < 0:
                recs.append(f"❌ Worst pattern: {worst[0]} (expectancy: {worst[1].expectancy:.2f}R)")
        
        # Check pattern count correlation
        if self.pattern_count_stats:
            count_data = [(c, d) for c, d in self.pattern_count_stats.items() 
                         if d['wins'] + d['losses'] >= 5]
            if count_data:
                best_count = max(count_data, key=lambda x: x[1]['total_r'] / max(1, x[1]['wins'] + x[1]['losses']))
                recs.append(f"📊 Optimal pattern count: {best_count[0]} patterns")
        
        # Check combinations
        valid_combos = [c for c in self.combination_stats.values() if c.total_trades >= 10]
        if valid_combos:
            best_combo = max(valid_combos, key=lambda x: x.expectancy)
            if best_combo.expectancy > 0:
                recs.append(f"🎯 Best combination: {best_combo.combination} "
                          f"(expectancy: +{best_combo.expectancy:.2f}R)")
        
        return recs
    
    def get_status(self) -> Dict:
        """Get tracker status"""
        return {
            "version": "2.0",
            "running": self._running,
            "pending_trades": len(self.pending_trades),
            "completed_trades": len(self.completed_trades),
            "patterns_tracked": PATTERN_TYPES,
            "combinations_discovered": len(self.combination_stats)
        }


# Global instance
pattern_tracker_v2 = PatternTrackerV2()
