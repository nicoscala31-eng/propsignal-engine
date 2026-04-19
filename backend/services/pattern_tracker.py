"""
Pattern Tracker V1.0 - Track Pattern Outcomes
==============================================

Tracks:
- All detected patterns
- Entry/SL/TP levels
- MFE (Maximum Favorable Excursion)
- MAE (Maximum Adverse Excursion)
- Final outcome (TP/SL/Expired)

Provides anti-illusion system by comparing:
- Patterns executed vs not executed
- Performance by pattern type
- Real statistics
"""

import json
import logging
import asyncio
from typing import Dict, List, Optional
from dataclasses import dataclass, field, asdict
from datetime import datetime, timedelta
from pathlib import Path
from enum import Enum
import aiofiles
import uuid

logger = logging.getLogger(__name__)


class PatternOutcome(Enum):
    PENDING = "pending"
    TP_HIT = "tp_hit"
    SL_HIT = "sl_hit"
    EXPIRED = "expired"
    INVALIDATED = "invalidated"


@dataclass
class TrackedPattern:
    """Pattern event being tracked"""
    id: str
    symbol: str
    pattern_type: str
    direction: str  # BUY or SELL
    timestamp_detected: str
    
    entry_price: float
    stop_loss: float
    take_profit: float
    
    atr: float
    session: str
    trend_h1: str
    trend_m15: str
    confidence: float
    
    # Tracking
    outcome: str = "pending"
    timestamp_closed: str = ""
    close_price: float = 0.0
    
    # Excursion tracking
    mfe: float = 0.0  # Max Favorable Excursion in R
    mae: float = 0.0  # Max Adverse Excursion in R
    mfe_price: float = 0.0
    mae_price: float = 0.0
    
    # Flags
    executed: bool = False  # Was notification sent?
    simulated: bool = True  # Is this a simulation?
    
    def to_dict(self) -> Dict:
        return asdict(self)
    
    @classmethod
    def from_dict(cls, data: Dict) -> 'TrackedPattern':
        return cls(**{k: v for k, v in data.items() if k in cls.__dataclass_fields__})
    
    @property
    def risk(self) -> float:
        """Calculate risk in price units"""
        if self.direction == "BUY":
            return self.entry_price - self.stop_loss
        else:
            return self.stop_loss - self.entry_price
    
    @property
    def reward(self) -> float:
        """Calculate reward in price units"""
        if self.direction == "BUY":
            return self.take_profit - self.entry_price
        else:
            return self.entry_price - self.take_profit
    
    @property
    def risk_reward(self) -> float:
        """Calculate R:R ratio"""
        risk = self.risk
        if risk <= 0:
            return 0
        return self.reward / risk
    
    @property
    def final_r(self) -> float:
        """Calculate final R multiple"""
        if self.outcome == "pending":
            return 0
        
        risk = self.risk
        if risk <= 0:
            return 0
        
        if self.direction == "BUY":
            profit = self.close_price - self.entry_price
        else:
            profit = self.entry_price - self.close_price
        
        return profit / risk


class PatternTracker:
    """
    Track pattern outcomes and maintain performance statistics.
    """
    
    def __init__(self):
        self.data_dir = Path("/app/backend/data")
        self.data_file = self.data_dir / "pattern_events.json"
        
        self.pending_patterns: Dict[str, TrackedPattern] = {}
        self.completed_patterns: List[TrackedPattern] = []
        
        self.check_interval = 30  # seconds
        self.max_age_hours = 24  # expire after 24h
        
        self._loaded = False
        self._running = False
        self._task: Optional[asyncio.Task] = None
        
        # Statistics
        self.stats = {
            'total_tracked': 0,
            'tp_hit': 0,
            'sl_hit': 0,
            'expired': 0,
            'by_pattern_type': {},
            'by_session': {},
            'checks_performed': 0
        }
        
        logger.info("Pattern Tracker V1.0 initialized")
    
    async def initialize(self):
        """Load existing data and start tracking loop"""
        if self._loaded:
            return
        
        self.data_dir.mkdir(parents=True, exist_ok=True)
        await self._load_data()
        self._loaded = True
        logger.info(f"Pattern Tracker loaded: {len(self.pending_patterns)} pending, {len(self.completed_patterns)} completed")
    
    async def _load_data(self):
        """Load tracked patterns from file"""
        try:
            if self.data_file.exists():
                async with aiofiles.open(self.data_file, 'r') as f:
                    data = json.loads(await f.read())
                
                for p_data in data.get('pending', []):
                    pattern = TrackedPattern.from_dict(p_data)
                    self.pending_patterns[pattern.id] = pattern
                
                for p_data in data.get('completed', []):
                    pattern = TrackedPattern.from_dict(p_data)
                    self.completed_patterns.append(pattern)
                
                self.stats = data.get('stats', self.stats)
                
        except Exception as e:
            logger.error(f"Error loading pattern data: {e}")
    
    async def _save_data(self):
        """Save tracked patterns to file"""
        try:
            data = {
                'updated_at': datetime.utcnow().isoformat(),
                'pending': [p.to_dict() for p in self.pending_patterns.values()],
                'completed': [p.to_dict() for p in self.completed_patterns[-500:]],  # Keep last 500
                'stats': self.stats
            }
            
            async with aiofiles.open(self.data_file, 'w') as f:
                await f.write(json.dumps(data, indent=2))
                
        except Exception as e:
            logger.error(f"Error saving pattern data: {e}")
    
    # ==================== TRACKING ====================
    
    async def track_pattern(self, symbol: str, pattern_type: str, direction: str,
                           entry_price: float, stop_loss: float, take_profit: float,
                           atr: float, session: str, trend_h1: str, trend_m15: str,
                           confidence: float, executed: bool = False) -> str:
        """
        Start tracking a new pattern.
        
        Returns: pattern ID
        """
        pattern_id = f"{symbol}_{pattern_type}_{datetime.utcnow().strftime('%Y%m%d_%H%M%S')}_{uuid.uuid4().hex[:6]}"
        
        pattern = TrackedPattern(
            id=pattern_id,
            symbol=symbol,
            pattern_type=pattern_type,
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
            executed=executed,
            simulated=not executed,
            mfe_price=entry_price,
            mae_price=entry_price
        )
        
        self.pending_patterns[pattern_id] = pattern
        self.stats['total_tracked'] += 1
        
        # Update by_pattern_type
        if pattern_type not in self.stats['by_pattern_type']:
            self.stats['by_pattern_type'][pattern_type] = {'total': 0, 'wins': 0, 'losses': 0}
        self.stats['by_pattern_type'][pattern_type]['total'] += 1
        
        # Update by_session
        if session not in self.stats['by_session']:
            self.stats['by_session'][session] = {'total': 0, 'wins': 0, 'losses': 0}
        self.stats['by_session'][session]['total'] += 1
        
        await self._save_data()
        
        logger.info(f"[TRACKER] New pattern: {pattern_id} | {symbol} {direction} {pattern_type}")
        
        return pattern_id
    
    async def update_price(self, symbol: str, current_price: float):
        """
        Update MFE/MAE and check for TP/SL hits.
        """
        patterns_to_close = []
        
        for pattern_id, pattern in list(self.pending_patterns.items()):
            if pattern.symbol != symbol:
                continue
            
            risk = pattern.risk
            if risk <= 0:
                continue
            
            # Update MFE/MAE
            if pattern.direction == "BUY":
                favorable = current_price - pattern.entry_price
                adverse = pattern.entry_price - current_price
                
                if current_price > pattern.mfe_price:
                    pattern.mfe_price = current_price
                    pattern.mfe = favorable / risk
                
                if current_price < pattern.mae_price:
                    pattern.mae_price = current_price
                    pattern.mae = adverse / risk
                
                # Check TP/SL
                if current_price >= pattern.take_profit:
                    patterns_to_close.append((pattern_id, PatternOutcome.TP_HIT, current_price))
                elif current_price <= pattern.stop_loss:
                    patterns_to_close.append((pattern_id, PatternOutcome.SL_HIT, current_price))
            
            else:  # SELL
                favorable = pattern.entry_price - current_price
                adverse = current_price - pattern.entry_price
                
                if current_price < pattern.mfe_price:
                    pattern.mfe_price = current_price
                    pattern.mfe = favorable / risk
                
                if current_price > pattern.mae_price:
                    pattern.mae_price = current_price
                    pattern.mae = adverse / risk
                
                # Check TP/SL
                if current_price <= pattern.take_profit:
                    patterns_to_close.append((pattern_id, PatternOutcome.TP_HIT, current_price))
                elif current_price >= pattern.stop_loss:
                    patterns_to_close.append((pattern_id, PatternOutcome.SL_HIT, current_price))
        
        # Close patterns
        for pattern_id, outcome, price in patterns_to_close:
            await self._close_pattern(pattern_id, outcome, price)
    
    async def _close_pattern(self, pattern_id: str, outcome: PatternOutcome, close_price: float):
        """Close a pattern with outcome"""
        if pattern_id not in self.pending_patterns:
            return
        
        pattern = self.pending_patterns.pop(pattern_id)
        pattern.outcome = outcome.value
        pattern.timestamp_closed = datetime.utcnow().isoformat()
        pattern.close_price = close_price
        
        self.completed_patterns.append(pattern)
        
        # Update stats
        if outcome == PatternOutcome.TP_HIT:
            self.stats['tp_hit'] += 1
            if pattern.pattern_type in self.stats['by_pattern_type']:
                self.stats['by_pattern_type'][pattern.pattern_type]['wins'] += 1
            if pattern.session in self.stats['by_session']:
                self.stats['by_session'][pattern.session]['wins'] += 1
        elif outcome == PatternOutcome.SL_HIT:
            self.stats['sl_hit'] += 1
            if pattern.pattern_type in self.stats['by_pattern_type']:
                self.stats['by_pattern_type'][pattern.pattern_type]['losses'] += 1
            if pattern.session in self.stats['by_session']:
                self.stats['by_session'][pattern.session]['losses'] += 1
        elif outcome == PatternOutcome.EXPIRED:
            self.stats['expired'] += 1
        
        await self._save_data()
        
        logger.info(f"[TRACKER] Pattern closed: {pattern_id} | {outcome.value} | Final R: {pattern.final_r:.2f}")
    
    async def check_expired(self):
        """Check for expired patterns"""
        now = datetime.utcnow()
        max_age = timedelta(hours=self.max_age_hours)
        
        to_expire = []
        
        for pattern_id, pattern in self.pending_patterns.items():
            try:
                detected = datetime.fromisoformat(pattern.timestamp_detected)
                if now - detected > max_age:
                    to_expire.append(pattern_id)
            except:
                pass
        
        for pattern_id in to_expire:
            pattern = self.pending_patterns[pattern_id]
            # Use last known price as close price (approximate)
            await self._close_pattern(pattern_id, PatternOutcome.EXPIRED, pattern.mfe_price)
    
    # ==================== TRACKING LOOP ====================
    
    async def start(self):
        """Start the tracking loop"""
        if self._running:
            return
        
        await self.initialize()
        self._running = True
        self._task = asyncio.create_task(self._run_loop())
        logger.info("Pattern Tracker started")
    
    async def stop(self):
        """Stop the tracking loop"""
        self._running = False
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
        await self._save_data()
        logger.info("Pattern Tracker stopped")
    
    async def _run_loop(self):
        """Main tracking loop"""
        while self._running:
            try:
                self.stats['checks_performed'] += 1
                await self.check_expired()
                await self._save_data()
                await asyncio.sleep(self.check_interval)
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"Tracker loop error: {e}")
                await asyncio.sleep(5)
    
    # ==================== PERFORMANCE ANALYSIS ====================
    
    def get_pattern_performance(self, pattern_type: str = None) -> Dict:
        """
        Get performance statistics for a pattern type or all patterns.
        
        Anti-illusion: Shows real performance data.
        """
        patterns = self.completed_patterns
        
        if pattern_type:
            patterns = [p for p in patterns if p.pattern_type == pattern_type]
        
        if not patterns:
            return {
                'pattern_type': pattern_type or 'all',
                'total_trades': 0,
                'note': 'No completed patterns yet'
            }
        
        wins = [p for p in patterns if p.outcome == 'tp_hit']
        losses = [p for p in patterns if p.outcome == 'sl_hit']
        
        total = len(wins) + len(losses)
        winrate = len(wins) / total * 100 if total > 0 else 0
        
        # Calculate totals
        total_r = sum(p.final_r for p in patterns if p.outcome in ['tp_hit', 'sl_hit'])
        avg_win_r = sum(p.final_r for p in wins) / len(wins) if wins else 0
        avg_loss_r = sum(p.final_r for p in losses) / len(losses) if losses else 0
        
        # Expectancy
        expectancy = total_r / total if total > 0 else 0
        
        # Profit factor
        gross_profit = sum(p.final_r for p in wins) if wins else 0
        gross_loss = abs(sum(p.final_r for p in losses)) if losses else 1
        profit_factor = gross_profit / gross_loss if gross_loss > 0 else 0
        
        # MFE/MAE averages
        avg_mfe = sum(p.mfe for p in patterns) / len(patterns) if patterns else 0
        avg_mae = sum(p.mae for p in patterns) / len(patterns) if patterns else 0
        
        return {
            'pattern_type': pattern_type or 'all',
            'total_trades': total,
            'wins': len(wins),
            'losses': len(losses),
            'winrate': round(winrate, 1),
            'total_r': round(total_r, 2),
            'avg_win_r': round(avg_win_r, 2),
            'avg_loss_r': round(avg_loss_r, 2),
            'expectancy': round(expectancy, 3),
            'profit_factor': round(profit_factor, 2),
            'avg_mfe': round(avg_mfe, 2),
            'avg_mae': round(avg_mae, 2),
            'min_required_trades': 50,
            'statistically_valid': total >= 50
        }
    
    def get_all_performance(self) -> Dict:
        """Get performance for all pattern types"""
        pattern_types = set(p.pattern_type for p in self.completed_patterns)
        
        result = {
            'overall': self.get_pattern_performance(),
            'by_pattern': {},
            'by_session': {},
            'executed_vs_simulated': self._compare_executed_vs_simulated()
        }
        
        for pt in pattern_types:
            result['by_pattern'][pt] = self.get_pattern_performance(pt)
        
        # By session
        sessions = set(p.session for p in self.completed_patterns)
        for session in sessions:
            patterns = [p for p in self.completed_patterns if p.session == session]
            result['by_session'][session] = self._calc_session_stats(patterns)
        
        return result
    
    def _compare_executed_vs_simulated(self) -> Dict:
        """Compare executed patterns vs simulated (not sent)"""
        executed = [p for p in self.completed_patterns if p.executed]
        simulated = [p for p in self.completed_patterns if not p.executed]
        
        def calc_stats(patterns):
            if not patterns:
                return {'total': 0, 'winrate': 0, 'expectancy': 0}
            
            wins = len([p for p in patterns if p.outcome == 'tp_hit'])
            total = len([p for p in patterns if p.outcome in ['tp_hit', 'sl_hit']])
            total_r = sum(p.final_r for p in patterns if p.outcome in ['tp_hit', 'sl_hit'])
            
            return {
                'total': total,
                'winrate': round(wins / total * 100, 1) if total > 0 else 0,
                'total_r': round(total_r, 2),
                'expectancy': round(total_r / total, 3) if total > 0 else 0
            }
        
        return {
            'executed': calc_stats(executed),
            'simulated': calc_stats(simulated),
            'note': 'Compare executed (sent notifications) vs simulated (not sent)'
        }
    
    def _calc_session_stats(self, patterns: List[TrackedPattern]) -> Dict:
        """Calculate stats for a list of patterns"""
        if not patterns:
            return {'total': 0}
        
        wins = len([p for p in patterns if p.outcome == 'tp_hit'])
        losses = len([p for p in patterns if p.outcome == 'sl_hit'])
        total = wins + losses
        
        return {
            'total': total,
            'wins': wins,
            'losses': losses,
            'winrate': round(wins / total * 100, 1) if total > 0 else 0
        }
    
    def get_status(self) -> Dict:
        """Get tracker status"""
        return {
            'running': self._running,
            'pending_count': len(self.pending_patterns),
            'completed_count': len(self.completed_patterns),
            'stats': self.stats
        }


# Global instance
pattern_tracker = PatternTracker()
