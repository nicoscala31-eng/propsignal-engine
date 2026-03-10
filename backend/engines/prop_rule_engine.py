"""Prop Firm Rule Engine - Safety checks and compliance"""
from typing import List, Tuple
from models import PropProfile, PropRuleSafety, SignalType
from engines.signal_engine import StrategySetup

class PropRuleEngine:
    """Validates setups against prop firm rules"""
    
    def __init__(self):
        pass
    
    def check_setup_safety(self, setup: StrategySetup, profile: PropProfile) -> Tuple[PropRuleSafety, List[str]]:
        """Comprehensive safety check for a setup"""
        warnings = []
        safety_level = PropRuleSafety.SAFE
        
        # Check minimum trade duration
        if setup.expected_duration_minutes < profile.minimum_trade_duration_minutes:
            warnings.append(f"Trade duration {setup.expected_duration_minutes}min below minimum {profile.minimum_trade_duration_minutes}min")
            return PropRuleSafety.BLOCKED, warnings
        
        # Check drawdown risk
        current_drawdown_pct = ((profile.initial_balance - profile.current_balance) / profile.initial_balance) * 100
        
        # Calculate potential loss percentage
        risk_amount = abs(setup.entry_price - setup.stop_loss)
        # Assume 1 standard lot for calculation
        potential_loss_pct = (risk_amount / profile.current_balance) * 100
        
        # Check if trade would breach daily drawdown
        if current_drawdown_pct + potential_loss_pct > profile.daily_drawdown_percent * 0.8:
            warnings.append(f"Trade risk {potential_loss_pct:.1f}% too close to daily drawdown limit")
            safety_level = PropRuleSafety.BLOCKED
        
        # Check max drawdown
        if current_drawdown_pct + potential_loss_pct > profile.max_drawdown_percent * 0.7:
            warnings.append(f"Trade risk approaching max drawdown limit")
            if safety_level != PropRuleSafety.BLOCKED:
                safety_level = PropRuleSafety.CAUTION
        
        # Weekend holding rule
        if not profile.weekend_holding_allowed:
            # Check if trade could extend into weekend
            if setup.expected_duration_minutes > 24 * 60:  # More than 1 day
                warnings.append("Trade may extend into weekend - not allowed by firm rules")
                if safety_level != PropRuleSafety.BLOCKED:
                    safety_level = PropRuleSafety.CAUTION
        
        # Stop loss size check
        if setup.stop_distance_pips > 100:  # Large stop
            warnings.append(f"Large stop loss: {setup.stop_distance_pips:.0f} pips")
            if safety_level == PropRuleSafety.SAFE:
                safety_level = PropRuleSafety.CAUTION
        
        # Risk/reward check
        if setup.risk_reward_ratio < 1.2:
            warnings.append(f"Low risk/reward ratio: {setup.risk_reward_ratio:.1f}")
            if safety_level == PropRuleSafety.SAFE:
                safety_level = PropRuleSafety.CAUTION
        
        return safety_level, warnings
    
    def check_account_health(self, profile: PropProfile) -> Tuple[bool, List[str]]:
        """Check overall account health"""
        warnings = []
        is_healthy = True
        
        # Check current drawdown
        current_drawdown_pct = ((profile.initial_balance - profile.current_balance) / profile.initial_balance) * 100
        
        if current_drawdown_pct > profile.daily_drawdown_percent * 0.9:
            warnings.append(f"CRITICAL: Daily drawdown at {current_drawdown_pct:.1f}% - near limit {profile.daily_drawdown_percent}%")
            is_healthy = False
        elif current_drawdown_pct > profile.daily_drawdown_percent * 0.7:
            warnings.append(f"WARNING: Daily drawdown at {current_drawdown_pct:.1f}%")
        
        if current_drawdown_pct > profile.max_drawdown_percent * 0.9:
            warnings.append(f"CRITICAL: Max drawdown at {current_drawdown_pct:.1f}% - near limit {profile.max_drawdown_percent}%")
            is_healthy = False
        
        # Check equity vs balance
        equity_drawdown = ((profile.current_balance - profile.current_equity) / profile.current_balance) * 100
        if equity_drawdown > 3.0:
            warnings.append(f"Open positions risk: {equity_drawdown:.1f}%")
        
        return is_healthy, warnings
    
    def should_allow_trading(self, profile: PropProfile) -> Tuple[bool, str]:
        """Determine if trading should be allowed"""
        is_healthy, warnings = self.check_account_health(profile)
        
        if not is_healthy:
            return False, "; ".join(warnings)
        
        # Check if daily drawdown exceeded
        current_drawdown_pct = ((profile.initial_balance - profile.current_balance) / profile.initial_balance) * 100
        
        if current_drawdown_pct >= profile.daily_drawdown_percent:
            return False, f"Daily drawdown limit reached: {current_drawdown_pct:.1f}%"
        
        if current_drawdown_pct >= profile.max_drawdown_percent:
            return False, f"Max drawdown limit reached: {current_drawdown_pct:.1f}%"
        
        return True, "Account healthy"
    
    def calculate_safe_position_size(self, setup: StrategySetup, profile: PropProfile,
                                    max_risk_percent: float = 1.0) -> float:
        """Calculate safe position size based on account and risk"""
        risk_amount = abs(setup.entry_price - setup.stop_loss)
        
        if risk_amount == 0:
            return 0.0
        
        # Max risk amount in account currency
        max_risk = profile.current_balance * (max_risk_percent / 100)
        
        # Calculate position size
        # This is simplified - real calculation depends on contract size
        position_size = max_risk / risk_amount
        
        # Apply max lot exposure if set
        if profile.max_lot_exposure:
            position_size = min(position_size, profile.max_lot_exposure)
        
        return round(position_size, 2)
    
    def get_preset_profile(self, firm_name: str, user_id: str) -> PropProfile:
        """Get preset prop profile for known firms"""
        presets = {
            "get_leveraged": PropProfile(
                id=f"preset_{firm_name}_{user_id}",
                user_id=user_id,
                name="Get Leveraged Challenge",
                firm_name="Get Leveraged",
                daily_drawdown_percent=5.0,
                max_drawdown_percent=10.0,
                minimum_trading_days=5,
                minimum_profitable_days=3,
                minimum_trade_duration_minutes=3,
                consistency_rule_enabled=True,
                weekend_holding_allowed=False,
                overnight_holding_allowed=True
            ),
            "goatfundedtrader": PropProfile(
                id=f"preset_{firm_name}_{user_id}",
                user_id=user_id,
                name="GoatFundedTrader Challenge",
                firm_name="GoatFundedTrader",
                daily_drawdown_percent=4.0,
                max_drawdown_percent=8.0,
                minimum_trading_days=4,
                minimum_profitable_days=2,
                minimum_trade_duration_minutes=3,
                consistency_rule_enabled=True,
                weekend_holding_allowed=False,
                overnight_holding_allowed=True
            )
        }
        
        return presets.get(firm_name.lower().replace(" ", ""), presets["get_leveraged"])

prop_rule_engine = PropRuleEngine()
