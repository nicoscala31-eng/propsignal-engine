"""
Missed Opportunity Analysis Module
===================================

PURPOSE: Simulate and analyze what would have happened if rejected trades were taken.
This is AUDIT ONLY - no impact on live trading.

CRITICAL: This module does NOT modify:
- Signal generation logic
- Scoring weights
- Thresholds
- FTA filter behavior
- Entry/SL/TP calculation

It ONLY tracks and simulates rejected trades to answer:
"Were the rejections correct, or were they profitable opportunities missed?"

SIMULATION METHODOLOGY:
1. Use theoretical entry, SL, TP calculated BEFORE rejection
2. Use ONLY FUTURE candle data (after rejection timestamp)
3. Sequential candle-by-candle simulation on M5
4. If same candle hits both TP and SL → SL HIT (conservative)
5. 24-hour expiry window
"""

import json
import logging
import asyncio
from typing import Dict, List, Optional, Any, Tuple
from datetime import datetime, timedelta
from dataclasses import dataclass, field, asdict
from pathlib import Path
from enum import Enum

logger = logging.getLogger(__name__)

# Storage file
MISSED_OPP_FILE = Path("/app/backend/storage/missed_opportunities.json")


class SimulatedOutcome(Enum):
    """Simulated trade outcome"""
    TP_HIT = "tp_hit"
    SL_HIT = "sl_hit"
    EXPIRED = "expired"
    PENDING = "pending"  # Not yet simulated


class FTABucket(Enum):
    """FTA clean_space_ratio buckets"""
    VERY_CLOSE = "very_close"    # ratio < 0.20
    CLOSE = "close"              # 0.20 - 0.35
    BORDERLINE = "borderline"    # 0.35 - 0.50
    NEAR_VALID = "near_valid"    # 0.50 - 0.65
    VALID = "valid"              # >= 0.65


def get_fta_bucket(ratio: float) -> str:
    """Classify FTA ratio into bucket"""
    if ratio < 0.20:
        return FTABucket.VERY_CLOSE.value
    elif ratio < 0.35:
        return FTABucket.CLOSE.value
    elif ratio < 0.50:
        return FTABucket.BORDERLINE.value
    elif ratio < 0.65:
        return FTABucket.NEAR_VALID.value
    else:
        return FTABucket.VALID.value


@dataclass
class MissedOpportunityRecord:
    """
    Complete record for a rejected trade with simulation results.
    """
    # Identification
    record_id: str = ""
    symbol: str = ""
    direction: str = ""
    timestamp: str = ""
    
    # Rejection info
    rejection_reason: str = ""
    score_before_reject: float = 0.0
    
    # Theoretical trade parameters (calculated BEFORE reject)
    entry_price_theoretical: float = 0.0
    stop_loss_theoretical: float = 0.0
    take_profit_theoretical: float = 0.0
    risk_reward_theoretical: float = 0.0
    
    # FTA data
    fta_price: Optional[float] = None
    fta_type: str = "none"
    fta_distance: float = 0.0
    clean_space_ratio: float = 1.0
    fta_bucket: str = ""
    
    # Simulation results
    simulated_outcome: str = "pending"
    simulated_mfe: float = 0.0  # Maximum Favorable Excursion
    simulated_mae: float = 0.0  # Maximum Adverse Excursion
    simulated_time_to_outcome_minutes: int = 0
    simulation_candles_checked: int = 0
    simulation_completed: bool = False
    simulation_timestamp: str = ""
    
    # Context at rejection
    h1_bias: str = "neutral"
    h1_bias_score: float = 0.0
    m15_bias: str = "neutral"
    m15_bias_score: float = 0.0
    m5_momentum: str = "neutral"
    m5_momentum_score: float = 0.0
    market_structure_score: float = 0.0
    pullback_quality: str = "weak"
    pullback_quality_score: float = 0.0
    session: str = ""
    regime: str = ""
    news_penalty: float = 0.0
    spread_penalty: float = 0.0
    fta_penalty: float = 0.0
    
    def to_dict(self) -> Dict:
        return asdict(self)


@dataclass
class SimulationStats:
    """Statistics for a group of simulated trades"""
    total: int = 0
    tp_hits: int = 0
    sl_hits: int = 0
    expired: int = 0
    pending: int = 0
    simulated_winrate: float = 0.0
    avg_rr: float = 0.0
    avg_mfe: float = 0.0
    avg_mae: float = 0.0
    expectancy: float = 0.0
    
    def to_dict(self) -> Dict:
        return asdict(self)


class MissedOpportunityAnalyzer:
    """
    Missed Opportunity Analysis System
    
    Tracks rejected trades and simulates outcomes using future candle data.
    
    CRITICAL: This is AUDIT ONLY - no impact on live trading.
    """
    
    # Simulation parameters
    EXPIRY_HOURS = 24
    SIMULATION_BATCH_SIZE = 10  # Process in batches to avoid blocking
    
    def __init__(self):
        self.records: List[MissedOpportunityRecord] = []
        self._load_data()
        self._simulation_running = False
        logger.info("📊 Missed Opportunity Analyzer initialized (AUDIT ONLY)")
    
    def _load_data(self):
        """Load persisted data"""
        try:
            if MISSED_OPP_FILE.exists():
                with open(MISSED_OPP_FILE, 'r') as f:
                    data = json.load(f)
                    self.records = [
                        MissedOpportunityRecord(**r) for r in data.get('records', [])
                    ]
                logger.info(f"📂 Loaded {len(self.records)} missed opportunity records")
        except Exception as e:
            logger.warning(f"Could not load missed opportunity data: {e}")
    
    def _save_data(self):
        """Persist data"""
        try:
            MISSED_OPP_FILE.parent.mkdir(parents=True, exist_ok=True)
            
            # Keep last 1000 records
            recent_records = self.records[-1000:]
            with open(MISSED_OPP_FILE, 'w') as f:
                json.dump({
                    'records': [r.to_dict() for r in recent_records],
                    'last_save': datetime.utcnow().isoformat()
                }, f, indent=2)
        except Exception as e:
            logger.warning(f"Could not save missed opportunity data: {e}")
    
    def record_rejection(
        self,
        symbol: str,
        direction: str,
        rejection_reason: str,
        score_before_reject: float,
        entry_price: float,
        stop_loss: float,
        take_profit: float,
        risk_reward: float,
        fta_price: Optional[float],
        fta_type: str,
        fta_distance: float,
        clean_space_ratio: float,
        context: Dict
    ):
        """
        Record a rejected trade for later simulation.
        
        IMPORTANT: entry, SL, TP are the theoretical values calculated BEFORE rejection.
        """
        record_id = f"MO_{symbol}_{direction}_{datetime.utcnow().strftime('%Y%m%d_%H%M%S_%f')}"
        
        record = MissedOpportunityRecord(
            record_id=record_id,
            symbol=symbol,
            direction=direction,
            timestamp=datetime.utcnow().isoformat(),
            rejection_reason=rejection_reason,
            score_before_reject=score_before_reject,
            entry_price_theoretical=entry_price,
            stop_loss_theoretical=stop_loss,
            take_profit_theoretical=take_profit,
            risk_reward_theoretical=risk_reward,
            fta_price=fta_price,
            fta_type=fta_type,
            fta_distance=fta_distance,
            clean_space_ratio=clean_space_ratio,
            fta_bucket=get_fta_bucket(clean_space_ratio),
            # Context
            h1_bias=context.get('h1_bias', 'neutral'),
            h1_bias_score=context.get('h1_bias_score', 0),
            m15_bias=context.get('m15_bias', 'neutral'),
            m15_bias_score=context.get('m15_bias_score', 0),
            m5_momentum=context.get('m5_momentum', 'neutral'),
            m5_momentum_score=context.get('m5_momentum_score', 0),
            market_structure_score=context.get('market_structure_score', 0),
            pullback_quality=context.get('pullback_quality', 'weak'),
            pullback_quality_score=context.get('pullback_quality_score', 0),
            session=context.get('session', ''),
            regime=context.get('regime', ''),
            news_penalty=context.get('news_penalty', 0),
            spread_penalty=context.get('spread_penalty', 0),
            fta_penalty=context.get('fta_penalty', 0)
        )
        
        self.records.append(record)
        
        # Save periodically
        if len(self.records) % 20 == 0:
            self._save_data()
        
        logger.debug(f"📊 Missed opportunity recorded: {symbol} {direction} ({rejection_reason})")
    
    async def simulate_single(self, record: MissedOpportunityRecord, candles: List[Dict]) -> MissedOpportunityRecord:
        """
        Simulate a single rejected trade using candle-by-candle analysis.
        
        CRITICAL METHODOLOGY:
        1. Use ONLY candles AFTER the rejection timestamp
        2. Check each candle sequentially
        3. For each candle: check if HIGH >= TP or LOW <= SL
        4. If same candle hits both → SL HIT (conservative)
        5. Track MFE and MAE throughout
        6. Expire after 24 hours
        """
        if record.simulation_completed:
            return record
        
        try:
            rejection_time = datetime.fromisoformat(record.timestamp)
        except:
            record.simulation_completed = True
            record.simulated_outcome = SimulatedOutcome.EXPIRED.value
            return record
        
        entry = record.entry_price_theoretical
        sl = record.stop_loss_theoretical
        tp = record.take_profit_theoretical
        direction = record.direction
        
        # Filter candles: only FUTURE candles (after rejection)
        future_candles = []
        for c in candles:
            try:
                candle_time = datetime.fromisoformat(c.get('datetime', ''))
                if candle_time > rejection_time:
                    future_candles.append((candle_time, c))
            except:
                continue
        
        # Sort by time
        future_candles.sort(key=lambda x: x[0])
        
        # Expiry cutoff
        expiry_time = rejection_time + timedelta(hours=self.EXPIRY_HOURS)
        
        # Initialize tracking
        mfe = 0.0  # Maximum Favorable Excursion
        mae = 0.0  # Maximum Adverse Excursion
        candles_checked = 0
        outcome = SimulatedOutcome.PENDING
        outcome_time = None
        
        # Candle-by-candle simulation
        for candle_time, candle in future_candles:
            if candle_time > expiry_time:
                # Trade expired
                outcome = SimulatedOutcome.EXPIRED
                outcome_time = expiry_time
                break
            
            candles_checked += 1
            high = candle.get('high', 0)
            low = candle.get('low', 0)
            
            if direction == "BUY":
                # For BUY: favorable = up, adverse = down
                favorable_excursion = high - entry
                adverse_excursion = entry - low
                
                mfe = max(mfe, favorable_excursion)
                mae = max(mae, adverse_excursion)
                
                # Check TP/SL hits
                tp_hit = high >= tp
                sl_hit = low <= sl
            else:  # SELL
                # For SELL: favorable = down, adverse = up
                favorable_excursion = entry - low
                adverse_excursion = high - entry
                
                mfe = max(mfe, favorable_excursion)
                mae = max(mae, adverse_excursion)
                
                # Check TP/SL hits
                tp_hit = low <= tp
                sl_hit = high >= sl
            
            # Determine outcome (SL takes priority if both hit - conservative)
            if sl_hit and tp_hit:
                outcome = SimulatedOutcome.SL_HIT
                outcome_time = candle_time
                break
            elif sl_hit:
                outcome = SimulatedOutcome.SL_HIT
                outcome_time = candle_time
                break
            elif tp_hit:
                outcome = SimulatedOutcome.TP_HIT
                outcome_time = candle_time
                break
        
        # If we went through all candles without hitting TP/SL
        if outcome == SimulatedOutcome.PENDING:
            if len(future_candles) > 0 and future_candles[-1][0] >= expiry_time:
                outcome = SimulatedOutcome.EXPIRED
                outcome_time = expiry_time
            else:
                # Not enough future data yet - keep as pending
                pass
        
        # Calculate time to outcome
        time_to_outcome = 0
        if outcome_time:
            time_to_outcome = int((outcome_time - rejection_time).total_seconds() / 60)
        
        # Convert MFE/MAE to pips
        pip_size = 0.0001 if record.symbol == "EURUSD" else 0.01
        mfe_pips = mfe / pip_size
        mae_pips = mae / pip_size
        
        # Update record
        record.simulated_outcome = outcome.value
        record.simulated_mfe = round(mfe_pips, 1)
        record.simulated_mae = round(mae_pips, 1)
        record.simulated_time_to_outcome_minutes = time_to_outcome
        record.simulation_candles_checked = candles_checked
        record.simulation_completed = outcome != SimulatedOutcome.PENDING
        record.simulation_timestamp = datetime.utcnow().isoformat()
        
        return record
    
    async def run_simulation_batch(self):
        """
        Run simulation on pending records in batches.
        Called periodically to avoid blocking live trading.
        """
        if self._simulation_running:
            return
        
        self._simulation_running = True
        
        try:
            from services.market_data_cache import market_data_cache
            from models import Asset, Timeframe
            
            # Get pending records
            pending = [r for r in self.records if not r.simulation_completed]
            
            if not pending:
                return
            
            # Process in batches
            batch = pending[:self.SIMULATION_BATCH_SIZE]
            
            for record in batch:
                try:
                    # Get M5 candles for the symbol
                    asset = Asset.EURUSD if record.symbol == "EURUSD" else Asset.XAUUSD
                    candles = market_data_cache.get_candles(asset, Timeframe.M5)
                    
                    if candles and len(candles) > 50:
                        await self.simulate_single(record, candles)
                except Exception as e:
                    logger.debug(f"Simulation error for {record.record_id}: {e}")
            
            self._save_data()
            
            simulated_count = sum(1 for r in batch if r.simulation_completed)
            if simulated_count > 0:
                logger.info(f"📊 Simulated {simulated_count}/{len(batch)} missed opportunities")
                
        except Exception as e:
            logger.warning(f"Simulation batch error: {e}")
        finally:
            self._simulation_running = False
    
    def _calculate_stats(self, records: List[MissedOpportunityRecord]) -> SimulationStats:
        """Calculate statistics for a group of records"""
        stats = SimulationStats()
        
        if not records:
            return stats
        
        completed = [r for r in records if r.simulation_completed]
        stats.total = len(records)
        stats.pending = len(records) - len(completed)
        
        stats.tp_hits = sum(1 for r in completed if r.simulated_outcome == SimulatedOutcome.TP_HIT.value)
        stats.sl_hits = sum(1 for r in completed if r.simulated_outcome == SimulatedOutcome.SL_HIT.value)
        stats.expired = sum(1 for r in completed if r.simulated_outcome == SimulatedOutcome.EXPIRED.value)
        
        # Winrate (excluding expired)
        decisive = stats.tp_hits + stats.sl_hits
        if decisive > 0:
            stats.simulated_winrate = (stats.tp_hits / decisive) * 100
        
        # Averages
        rrs = [r.risk_reward_theoretical for r in records if r.risk_reward_theoretical > 0]
        mfes = [r.simulated_mfe for r in completed if r.simulated_mfe > 0]
        maes = [r.simulated_mae for r in completed if r.simulated_mae > 0]
        
        if rrs:
            stats.avg_rr = sum(rrs) / len(rrs)
        if mfes:
            stats.avg_mfe = sum(mfes) / len(mfes)
        if maes:
            stats.avg_mae = sum(maes) / len(maes)
        
        # Expectancy = (Win% × Avg RR) - Loss%
        if decisive > 0 and stats.avg_rr > 0:
            win_pct = stats.tp_hits / decisive
            loss_pct = stats.sl_hits / decisive
            stats.expectancy = (win_pct * stats.avg_rr) - loss_pct
        
        return stats
    
    def get_full_report(self) -> Dict:
        """Get comprehensive missed opportunity report"""
        all_stats = self._calculate_stats(self.records)
        
        # By symbol
        by_symbol = {}
        for symbol in ["EURUSD", "XAUUSD"]:
            symbol_records = [r for r in self.records if r.symbol == symbol]
            by_symbol[symbol] = self._calculate_stats(symbol_records).to_dict()
        
        # By direction
        by_direction = {}
        for direction in ["BUY", "SELL"]:
            dir_records = [r for r in self.records if r.direction == direction]
            by_direction[direction] = self._calculate_stats(dir_records).to_dict()
        
        # By symbol + direction
        by_symbol_direction = {}
        for combo in ["EURUSD_BUY", "EURUSD_SELL", "XAUUSD_BUY", "XAUUSD_SELL"]:
            parts = combo.split("_")
            combo_records = [r for r in self.records if r.symbol == parts[0] and r.direction == parts[1]]
            by_symbol_direction[combo] = self._calculate_stats(combo_records).to_dict()
        
        return {
            "report_generated": datetime.utcnow().isoformat(),
            "total_records": len(self.records),
            "overall_stats": all_stats.to_dict(),
            "by_symbol": by_symbol,
            "by_direction": by_direction,
            "by_symbol_direction": by_symbol_direction,
            "key_insight": self._generate_key_insight(all_stats),
            "note": "AUDIT ONLY - No strategy modifications"
        }
    
    def get_stats_by_reason(self) -> Dict:
        """Get statistics broken down by rejection reason"""
        reasons = {}
        for record in self.records:
            reason = record.rejection_reason
            if reason not in reasons:
                reasons[reason] = []
            reasons[reason].append(record)
        
        return {
            "report_type": "by_rejection_reason",
            "stats": {
                reason: self._calculate_stats(records).to_dict()
                for reason, records in reasons.items()
            },
            "note": "AUDIT ONLY"
        }
    
    def get_stats_by_fta_bucket(self) -> Dict:
        """Get statistics broken down by FTA bucket"""
        buckets = {
            FTABucket.VERY_CLOSE.value: [],
            FTABucket.CLOSE.value: [],
            FTABucket.BORDERLINE.value: [],
            FTABucket.NEAR_VALID.value: [],
            FTABucket.VALID.value: []
        }
        
        for record in self.records:
            bucket = record.fta_bucket
            if bucket in buckets:
                buckets[bucket].append(record)
        
        return {
            "report_type": "by_fta_bucket",
            "bucket_definitions": {
                "very_close": "ratio < 0.20",
                "close": "0.20 - 0.35",
                "borderline": "0.35 - 0.50",
                "near_valid": "0.50 - 0.65",
                "valid": ">= 0.65"
            },
            "stats": {
                bucket: self._calculate_stats(records).to_dict()
                for bucket, records in buckets.items()
            },
            "note": "AUDIT ONLY - Used to evaluate FTA filter effectiveness"
        }
    
    def get_top_patterns(self) -> Dict:
        """
        Identify top winning and losing patterns among rejected trades.
        """
        # Group by pattern: symbol + direction + session + regime + fta_bucket
        patterns = {}
        
        for record in self.records:
            if not record.simulation_completed:
                continue
            
            pattern_key = f"{record.symbol}_{record.direction}_{record.session}_{record.regime}_{record.fta_bucket}"
            
            if pattern_key not in patterns:
                patterns[pattern_key] = {
                    "symbol": record.symbol,
                    "direction": record.direction,
                    "session": record.session,
                    "regime": record.regime,
                    "fta_bucket": record.fta_bucket,
                    "records": []
                }
            
            patterns[pattern_key]["records"].append(record)
        
        # Calculate stats per pattern
        pattern_stats = []
        for key, data in patterns.items():
            records = data["records"]
            stats = self._calculate_stats(records)
            
            if stats.tp_hits + stats.sl_hits >= 3:  # Minimum sample size
                pattern_stats.append({
                    "pattern": key,
                    "symbol": data["symbol"],
                    "direction": data["direction"],
                    "session": data["session"],
                    "regime": data["regime"],
                    "fta_bucket": data["fta_bucket"],
                    "sample_size": len(records),
                    "simulated_winrate": round(stats.simulated_winrate, 1),
                    "avg_rr": round(stats.avg_rr, 2),
                    "tp_hits": stats.tp_hits,
                    "sl_hits": stats.sl_hits,
                    "expectancy": round(stats.expectancy, 3)
                })
        
        # Sort by winrate
        sorted_patterns = sorted(pattern_stats, key=lambda x: x["simulated_winrate"], reverse=True)
        
        return {
            "report_type": "top_patterns",
            "top_winning_patterns": sorted_patterns[:5] if sorted_patterns else [],
            "top_losing_patterns": sorted_patterns[-5:][::-1] if sorted_patterns else [],
            "patterns_with_100pct_tp": [p for p in sorted_patterns if p["simulated_winrate"] == 100],
            "patterns_with_0pct_tp": [p for p in sorted_patterns if p["simulated_winrate"] == 0],
            "note": "AUDIT ONLY - Patterns are rejected trades that were simulated"
        }
    
    def get_sample_simulations(self, count: int = 5) -> List[Dict]:
        """Get sample simulation records for verification"""
        completed = [r for r in self.records if r.simulation_completed]
        
        # Try to get a mix of outcomes
        samples = []
        
        tp_samples = [r for r in completed if r.simulated_outcome == SimulatedOutcome.TP_HIT.value][:2]
        sl_samples = [r for r in completed if r.simulated_outcome == SimulatedOutcome.SL_HIT.value][:2]
        expired_samples = [r for r in completed if r.simulated_outcome == SimulatedOutcome.EXPIRED.value][:1]
        
        samples.extend(tp_samples)
        samples.extend(sl_samples)
        samples.extend(expired_samples)
        
        return [
            {
                "record_id": r.record_id,
                "symbol": r.symbol,
                "direction": r.direction,
                "timestamp": r.timestamp,
                "rejection_reason": r.rejection_reason,
                "entry": r.entry_price_theoretical,
                "stop_loss": r.stop_loss_theoretical,
                "take_profit": r.take_profit_theoretical,
                "risk_reward": r.risk_reward_theoretical,
                "fta_bucket": r.fta_bucket,
                "clean_space_ratio": r.clean_space_ratio,
                "simulated_outcome": r.simulated_outcome,
                "simulated_mfe_pips": r.simulated_mfe,
                "simulated_mae_pips": r.simulated_mae,
                "time_to_outcome_minutes": r.simulated_time_to_outcome_minutes,
                "candles_checked": r.simulation_candles_checked,
                "context": {
                    "h1_bias": r.h1_bias,
                    "m15_bias": r.m15_bias,
                    "session": r.session,
                    "regime": r.regime
                }
            }
            for r in samples[:count]
        ]
    
    def _generate_key_insight(self, stats: SimulationStats) -> str:
        """Generate a key insight from the statistics"""
        if stats.total == 0:
            return "No data yet - waiting for rejected trades to be simulated"
        
        if stats.pending > stats.total * 0.5:
            return f"Simulation in progress: {stats.pending}/{stats.total} pending"
        
        if stats.simulated_winrate > 60:
            return f"⚠️ HIGH MISSED WIN RATE: {stats.simulated_winrate:.0f}% of rejected trades would have hit TP"
        elif stats.simulated_winrate > 40:
            return f"MODERATE: {stats.simulated_winrate:.0f}% of rejected trades would have won"
        else:
            return f"✅ FILTER EFFECTIVE: Only {stats.simulated_winrate:.0f}% would have won - rejections were mostly correct"


# Global instance
missed_opportunity_analyzer = MissedOpportunityAnalyzer()


async def run_periodic_simulation():
    """Background task to run simulations periodically"""
    while True:
        try:
            await missed_opportunity_analyzer.run_simulation_batch()
        except Exception as e:
            logger.warning(f"Periodic simulation error: {e}")
        await asyncio.sleep(60)  # Run every minute
