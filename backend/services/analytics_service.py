"""Analytics Service - Performance metrics and signal statistics"""
import logging
from typing import Dict, List, Optional, Any
from datetime import datetime, timedelta
from dataclasses import dataclass

from models import SignalType, Asset, MarketRegime

logger = logging.getLogger(__name__)


@dataclass
class PerformanceMetrics:
    """Complete performance metrics"""
    total_signals: int = 0
    buy_signals: int = 0
    sell_signals: int = 0
    next_signals: int = 0
    
    # Outcomes
    winning_trades: int = 0
    losing_trades: int = 0
    pending_trades: int = 0
    
    # Rates
    win_rate: float = 0.0
    loss_rate: float = 0.0
    
    # Risk metrics
    average_rr_ratio: float = 0.0
    profit_factor: float = 0.0
    expectancy: float = 0.0
    
    # Drawdown
    max_drawdown_pct: float = 0.0
    current_drawdown_pct: float = 0.0
    
    # Time metrics
    average_trade_duration_minutes: float = 0.0
    longest_winning_streak: int = 0
    longest_losing_streak: int = 0
    
    # By asset
    signals_per_asset: Dict[str, int] = None
    win_rate_per_asset: Dict[str, float] = None
    
    # By regime
    signals_per_regime: Dict[str, int] = None
    win_rate_per_regime: Dict[str, float] = None
    
    # Recent performance
    signals_today: int = 0
    signals_this_week: int = 0
    signals_this_month: int = 0
    
    def __post_init__(self):
        if self.signals_per_asset is None:
            self.signals_per_asset = {}
        if self.win_rate_per_asset is None:
            self.win_rate_per_asset = {}
        if self.signals_per_regime is None:
            self.signals_per_regime = {}
        if self.win_rate_per_regime is None:
            self.win_rate_per_regime = {}


class AnalyticsService:
    """
    Analytics service for signal performance tracking
    
    Features:
    - Win rate calculation
    - Risk-reward analysis
    - Profit factor
    - Drawdown tracking
    - Asset and regime breakdowns
    - Time-based analysis
    """
    
    def __init__(self, db):
        self.db = db
    
    async def get_performance_metrics(
        self,
        user_id: Optional[str] = None,
        start_date: Optional[datetime] = None,
        end_date: Optional[datetime] = None
    ) -> PerformanceMetrics:
        """
        Calculate comprehensive performance metrics
        
        Args:
            user_id: Filter by user (None for all)
            start_date: Start of analysis period
            end_date: End of analysis period
        
        Returns:
            PerformanceMetrics dataclass with all metrics
        """
        # Build query
        query: Dict[str, Any] = {}
        if user_id:
            query["user_id"] = user_id
        
        if start_date or end_date:
            query["created_at"] = {}
            if start_date:
                query["created_at"]["$gte"] = start_date
            if end_date:
                query["created_at"]["$lte"] = end_date
        
        # Fetch signals
        signals = await self.db.signals.find(query).sort("created_at", -1).to_list(10000)
        
        if not signals:
            return PerformanceMetrics()
        
        # Initialize metrics
        metrics = PerformanceMetrics()
        metrics.total_signals = len(signals)
        
        # Count by type
        trade_signals = []
        for s in signals:
            signal_type = s.get("signal_type", "NEXT")
            if signal_type == "BUY":
                metrics.buy_signals += 1
                trade_signals.append(s)
            elif signal_type == "SELL":
                metrics.sell_signals += 1
                trade_signals.append(s)
            else:
                metrics.next_signals += 1
        
        # Calculate outcomes
        for s in trade_signals:
            if s.get("tp1_hit") or s.get("tp2_hit"):
                metrics.winning_trades += 1
            elif s.get("sl_hit"):
                metrics.losing_trades += 1
            elif s.get("is_active"):
                metrics.pending_trades += 1
        
        # Win rate
        completed_trades = metrics.winning_trades + metrics.losing_trades
        if completed_trades > 0:
            metrics.win_rate = (metrics.winning_trades / completed_trades) * 100
            metrics.loss_rate = (metrics.losing_trades / completed_trades) * 100
        
        # Average R:R ratio
        rr_ratios = [s.get("risk_reward_ratio", 0) for s in trade_signals if s.get("risk_reward_ratio")]
        if rr_ratios:
            metrics.average_rr_ratio = sum(rr_ratios) / len(rr_ratios)
        
        # Profit factor and expectancy
        metrics.profit_factor = self._calculate_profit_factor(trade_signals)
        metrics.expectancy = self._calculate_expectancy(trade_signals)
        
        # Drawdown
        metrics.max_drawdown_pct, metrics.current_drawdown_pct = self._calculate_drawdown(trade_signals)
        
        # Streaks
        metrics.longest_winning_streak = self._calculate_streak(trade_signals, winning=True)
        metrics.longest_losing_streak = self._calculate_streak(trade_signals, winning=False)
        
        # By asset
        metrics.signals_per_asset = self._count_by_field(trade_signals, "asset")
        metrics.win_rate_per_asset = self._win_rate_by_field(trade_signals, "asset")
        
        # By regime
        metrics.signals_per_regime = self._count_by_field(trade_signals, "market_regime")
        metrics.win_rate_per_regime = self._win_rate_by_field(trade_signals, "market_regime")
        
        # Time-based counts
        now = datetime.utcnow()
        today_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
        week_start = today_start - timedelta(days=now.weekday())
        month_start = today_start.replace(day=1)
        
        for s in signals:
            created = s.get("created_at")
            if not created:
                continue
            
            if created >= today_start:
                metrics.signals_today += 1
            if created >= week_start:
                metrics.signals_this_week += 1
            if created >= month_start:
                metrics.signals_this_month += 1
        
        return metrics
    
    def _calculate_profit_factor(self, signals: List[Dict]) -> float:
        """Calculate profit factor (gross profit / gross loss)"""
        gross_profit = 0.0
        gross_loss = 0.0
        
        for s in signals:
            if s.get("tp1_hit") or s.get("tp2_hit"):
                # Estimate profit based on R:R
                rr = s.get("risk_reward_ratio", 1.5)
                risk = s.get("money_at_risk", 100)
                gross_profit += risk * rr
            elif s.get("sl_hit"):
                risk = s.get("money_at_risk", 100)
                gross_loss += risk
        
        if gross_loss == 0:
            return 0.0 if gross_profit == 0 else float('inf')
        
        return gross_profit / gross_loss
    
    def _calculate_expectancy(self, signals: List[Dict]) -> float:
        """Calculate expected value per trade"""
        wins = []
        losses = []
        
        for s in signals:
            if s.get("tp1_hit") or s.get("tp2_hit"):
                rr = s.get("risk_reward_ratio", 1.5)
                wins.append(rr)
            elif s.get("sl_hit"):
                losses.append(-1.0)  # Normalized to 1R loss
        
        total_trades = len(wins) + len(losses)
        if total_trades == 0:
            return 0.0
        
        win_rate = len(wins) / total_trades
        avg_win = sum(wins) / len(wins) if wins else 0
        avg_loss = abs(sum(losses) / len(losses)) if losses else 0
        
        return (win_rate * avg_win) - ((1 - win_rate) * avg_loss)
    
    def _calculate_drawdown(self, signals: List[Dict]) -> tuple:
        """Calculate max and current drawdown percentage"""
        if not signals:
            return 0.0, 0.0
        
        # Simple simulation of equity curve
        equity = 10000.0
        peak = equity
        max_dd = 0.0
        
        for s in sorted(signals, key=lambda x: x.get("created_at", datetime.min)):
            risk = s.get("money_at_risk", equity * 0.01)
            
            if s.get("tp1_hit") or s.get("tp2_hit"):
                rr = s.get("risk_reward_ratio", 1.5)
                equity += risk * rr
            elif s.get("sl_hit"):
                equity -= risk
            
            if equity > peak:
                peak = equity
            
            dd = ((peak - equity) / peak) * 100 if peak > 0 else 0
            max_dd = max(max_dd, dd)
        
        current_dd = ((peak - equity) / peak) * 100 if peak > 0 else 0
        
        return round(max_dd, 2), round(current_dd, 2)
    
    def _calculate_streak(self, signals: List[Dict], winning: bool) -> int:
        """Calculate longest winning or losing streak"""
        sorted_signals = sorted(signals, key=lambda x: x.get("created_at", datetime.min))
        
        max_streak = 0
        current_streak = 0
        
        for s in sorted_signals:
            is_win = s.get("tp1_hit") or s.get("tp2_hit")
            is_loss = s.get("sl_hit")
            
            if (winning and is_win) or (not winning and is_loss):
                current_streak += 1
                max_streak = max(max_streak, current_streak)
            elif is_win or is_loss:  # Opposite result
                current_streak = 0
        
        return max_streak
    
    def _count_by_field(self, signals: List[Dict], field: str) -> Dict[str, int]:
        """Count signals by a specific field"""
        counts: Dict[str, int] = {}
        
        for s in signals:
            value = s.get(field, "Unknown")
            if isinstance(value, str):
                counts[value] = counts.get(value, 0) + 1
        
        return counts
    
    def _win_rate_by_field(self, signals: List[Dict], field: str) -> Dict[str, float]:
        """Calculate win rate by a specific field"""
        wins_by_field: Dict[str, int] = {}
        total_by_field: Dict[str, int] = {}
        
        for s in signals:
            value = s.get(field, "Unknown")
            if not isinstance(value, str):
                continue
            
            is_win = s.get("tp1_hit") or s.get("tp2_hit")
            is_loss = s.get("sl_hit")
            
            if is_win or is_loss:
                total_by_field[value] = total_by_field.get(value, 0) + 1
                if is_win:
                    wins_by_field[value] = wins_by_field.get(value, 0) + 1
        
        win_rates: Dict[str, float] = {}
        for field_value, total in total_by_field.items():
            wins = wins_by_field.get(field_value, 0)
            win_rates[field_value] = round((wins / total) * 100, 1) if total > 0 else 0.0
        
        return win_rates
    
    async def get_signal_distribution(
        self,
        user_id: Optional[str] = None,
        days: int = 30
    ) -> Dict[str, Any]:
        """Get signal distribution over time"""
        start_date = datetime.utcnow() - timedelta(days=days)
        
        query: Dict[str, Any] = {"created_at": {"$gte": start_date}}
        if user_id:
            query["user_id"] = user_id
        
        signals = await self.db.signals.find(query).to_list(10000)
        
        # Group by day
        daily_distribution: Dict[str, Dict[str, int]] = {}
        
        for s in signals:
            created = s.get("created_at")
            if not created:
                continue
            
            day_key = created.strftime("%Y-%m-%d")
            signal_type = s.get("signal_type", "NEXT")
            
            if day_key not in daily_distribution:
                daily_distribution[day_key] = {"BUY": 0, "SELL": 0, "NEXT": 0}
            
            daily_distribution[day_key][signal_type] = daily_distribution[day_key].get(signal_type, 0) + 1
        
        return {
            "period_days": days,
            "start_date": start_date.isoformat(),
            "end_date": datetime.utcnow().isoformat(),
            "daily_distribution": daily_distribution
        }
    
    async def get_recent_trades_summary(
        self,
        user_id: Optional[str] = None,
        limit: int = 10
    ) -> List[Dict[str, Any]]:
        """Get summary of recent trades"""
        query: Dict[str, Any] = {"signal_type": {"$in": ["BUY", "SELL"]}}
        if user_id:
            query["user_id"] = user_id
        
        signals = await self.db.signals.find(query).sort("created_at", -1).limit(limit).to_list(limit)
        
        summaries = []
        for s in signals:
            outcome = "PENDING"
            if s.get("tp1_hit") or s.get("tp2_hit"):
                outcome = "WIN"
            elif s.get("sl_hit"):
                outcome = "LOSS"
            
            summaries.append({
                "id": s.get("id"),
                "asset": s.get("asset"),
                "signal_type": s.get("signal_type"),
                "entry_price": s.get("entry_price"),
                "stop_loss": s.get("stop_loss"),
                "take_profit": s.get("take_profit_1"),
                "confidence": s.get("confidence_score"),
                "outcome": outcome,
                "created_at": s.get("created_at").isoformat() if s.get("created_at") else None
            })
        
        return summaries


# Factory function
def create_analytics_service(db) -> AnalyticsService:
    """Create analytics service instance"""
    return AnalyticsService(db)
