"""Position Sizing Engine - Calculates exact lot sizes with risk management"""
from typing import Tuple, Optional
from models import Asset, PropProfile
from engines.signal_engine import StrategySetup
import logging

logger = logging.getLogger(__name__)

class RiskMode:
    """Risk mode settings"""
    CONSERVATIVE = "CONSERVATIVE"
    BALANCED = "BALANCED"
    AGGRESSIVE = "AGGRESSIVE"

class PositionSizingEngine:
    """Calculates exact position sizes with prop firm risk management"""
    
    def __init__(self):
        # Risk percentages by mode
        self.risk_percentages = {
            RiskMode.CONSERVATIVE: 0.25,
            RiskMode.BALANCED: 0.50,
            RiskMode.AGGRESSIVE: 0.75
        }
        
        # Contract specifications
        self.contract_specs = {
            Asset.EURUSD: {
                'contract_size': 100000,  # 1 lot = 100,000 units
                'pip_value_per_lot': 10,  # $10 per pip for 1 standard lot
                'pip_size': 0.0001,
                'min_lot': 0.01,
                'max_lot': 100.0,
                'lot_step': 0.01
            },
            Asset.XAUUSD: {
                'contract_size': 100,  # 1 lot = 100 oz
                'pip_value_per_lot': 10,  # $10 per point for 1 lot
                'pip_size': 0.10,
                'min_lot': 0.01,
                'max_lot': 50.0,
                'lot_step': 0.01
            }
        }
    
    def calculate_position_size(
        self,
        setup: StrategySetup,
        asset: Asset,
        profile: PropProfile,
        risk_mode: str = RiskMode.BALANCED,
        consecutive_losses: int = 0
    ) -> Tuple[float, float, float, str]:
        """
        Calculate exact position size with risk management
        
        Returns:
            (lot_size, risk_percentage, money_at_risk, risk_explanation)
        """
        
        # Get base risk percentage
        base_risk_pct = self.risk_percentages.get(risk_mode, 0.50)
        
        # Calculate current drawdown
        current_drawdown_pct = ((profile.initial_balance - profile.current_balance) / profile.initial_balance) * 100
        
        # Calculate remaining risk room
        daily_dd_remaining = profile.daily_drawdown_percent - current_drawdown_pct
        max_dd_remaining = profile.max_drawdown_percent - current_drawdown_pct
        
        # Apply risk reductions
        adjusted_risk_pct = base_risk_pct
        risk_explanation = f"{risk_mode} mode"
        
        # Reduce risk if close to daily drawdown (within 2%)
        if daily_dd_remaining < 2.0:
            reduction = 0.5  # Reduce to 50%
            adjusted_risk_pct *= reduction
            risk_explanation += f", reduced (near daily DD limit)"
            logger.warning(f"Risk reduced due to daily drawdown proximity: {daily_dd_remaining:.1f}% remaining")
        
        # Reduce risk if close to max drawdown (within 3%)
        if max_dd_remaining < 3.0:
            reduction = 0.3  # Reduce to 30%
            adjusted_risk_pct *= reduction
            risk_explanation += f", reduced (near max DD limit)"
            logger.warning(f"Risk reduced due to max drawdown proximity: {max_dd_remaining:.1f}% remaining")
        
        # Reduce risk after consecutive losses
        if consecutive_losses >= 2:
            reduction = max(0.5, 1.0 - (consecutive_losses * 0.1))
            adjusted_risk_pct *= reduction
            risk_explanation += f", reduced ({consecutive_losses} consecutive losses)"
        
        # Further reduce if prop safety is CAUTION
        # This would be passed from the orchestrator
        
        # Calculate stop loss distance in pips/points
        stop_distance = abs(setup.entry_price - setup.stop_loss)
        
        # Get contract specs
        specs = self.contract_specs[asset]
        pip_size = specs['pip_size']
        pip_value_per_lot = specs['pip_value_per_lot']
        
        # Calculate pips/points
        stop_distance_pips = stop_distance / pip_size
        
        # Calculate maximum money to risk
        max_money_risk = profile.current_balance * (adjusted_risk_pct / 100)
        
        # Don't risk more than what would leave us safe from drawdown limits
        # Keep a 1% buffer from daily DD
        max_safe_risk_daily = profile.current_balance * ((daily_dd_remaining - 1.0) / 100)
        max_money_risk = min(max_money_risk, max_safe_risk_daily)
        
        if max_money_risk <= 0:
            logger.error("No risk capacity available")
            return 0.0, 0.0, 0.0, "No risk capacity"
        
        # Calculate lot size
        # Formula: Lot Size = Risk Amount / (Stop Distance in Pips * Pip Value per Lot)
        lot_size = max_money_risk / (stop_distance_pips * pip_value_per_lot)
        
        # Apply lot limits
        lot_size = max(specs['min_lot'], min(lot_size, specs['max_lot']))
        
        # Round to lot step
        lot_size = round(lot_size / specs['lot_step']) * specs['lot_step']
        
        # Apply max lot exposure if profile has it
        if profile.max_lot_exposure:
            lot_size = min(lot_size, profile.max_lot_exposure)
        
        # Calculate actual money at risk with final lot size
        actual_money_risk = lot_size * stop_distance_pips * pip_value_per_lot
        
        # Calculate actual risk percentage
        actual_risk_pct = (actual_money_risk / profile.current_balance) * 100
        
        logger.info(f"Position sizing: {lot_size:.2f} lots, {actual_risk_pct:.2f}% risk, ${actual_money_risk:.2f} at risk")
        
        return (
            round(lot_size, 2),
            round(actual_risk_pct, 2),
            round(actual_money_risk, 2),
            risk_explanation
        )
    
    def validate_position_size(
        self,
        lot_size: float,
        asset: Asset,
        profile: PropProfile
    ) -> Tuple[bool, str]:
        """
        Validate if position size is safe
        
        Returns:
            (is_valid, reason)
        """
        specs = self.contract_specs[asset]
        
        # Check lot limits
        if lot_size < specs['min_lot']:
            return False, f"Lot size {lot_size:.2f} below minimum {specs['min_lot']}"
        
        if lot_size > specs['max_lot']:
            return False, f"Lot size {lot_size:.2f} exceeds maximum {specs['max_lot']}"
        
        # Check profile max exposure
        if profile.max_lot_exposure and lot_size > profile.max_lot_exposure:
            return False, f"Lot size {lot_size:.2f} exceeds profile limit {profile.max_lot_exposure}"
        
        return True, "Position size valid"
    
    def get_risk_mode_info(self, mode: str) -> dict:
        """Get information about a risk mode"""
        return {
            "mode": mode,
            "base_risk_pct": self.risk_percentages.get(mode, 0.50),
            "description": {
                RiskMode.CONSERVATIVE: "Low risk (0.25% per trade) - safest for challenges",
                RiskMode.BALANCED: "Moderate risk (0.50% per trade) - recommended default",
                RiskMode.AGGRESSIVE: "Higher risk (0.75% per trade) - for experienced traders"
            }.get(mode, "Unknown mode")
        }

position_sizing_engine = PositionSizingEngine()
