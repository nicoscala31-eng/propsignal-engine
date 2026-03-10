"""Signal Generation Engine - Core strategy logic"""
from typing import Optional, Tuple, List
from models import (
    Candle, Asset, Timeframe, SignalType, StrategyType, 
    MarketRegime, TradeHorizon, ScoreBreakdown
)
import statistics

class StrategySetup:
    """Represents a potential trade setup"""
    def __init__(self):
        self.signal_type: Optional[SignalType] = None
        self.strategy_type: Optional[StrategyType] = None
        self.entry_price: float = 0.0
        self.entry_zone_low: float = 0.0
        self.entry_zone_high: float = 0.0
        self.stop_loss: float = 0.0
        self.take_profit_1: float = 0.0
        self.take_profit_2: float = 0.0
        self.risk_reward_ratio: float = 0.0
        self.stop_distance_pips: float = 0.0
        self.expected_duration_minutes: int = 0
        self.trade_horizon: Optional[TradeHorizon] = None
        self.explanation: str = ""
        self.structure_quality: float = 0.0
        self.entry_quality: float = 0.0
        self.target_feasibility: float = 0.0

class SignalEngine:
    """Generates trading signals based on multiple strategies"""
    
    def __init__(self):
        self.pip_values = {
            Asset.EURUSD: 0.0001,
            Asset.XAUUSD: 0.10
        }
    
    def calculate_pips(self, asset: Asset, price1: float, price2: float) -> float:
        """Calculate pip distance between two prices"""
        pip_value = self.pip_values[asset]
        return abs(price1 - price2) / pip_value
    
    def find_support_resistance(self, candles: List[Candle], lookback: int = 50) -> Tuple[List[float], List[float]]:
        """Find key support and resistance levels"""
        recent = candles[-lookback:]
        
        # Find swing highs and lows
        supports = []
        resistances = []
        
        for i in range(2, len(recent) - 2):
            # Swing high
            if (recent[i].high > recent[i-1].high and 
                recent[i].high > recent[i-2].high and
                recent[i].high > recent[i+1].high and
                recent[i].high > recent[i+2].high):
                resistances.append(recent[i].high)
            
            # Swing low
            if (recent[i].low < recent[i-1].low and 
                recent[i].low < recent[i-2].low and
                recent[i].low < recent[i+1].low and
                recent[i].low < recent[i+2].low):
                supports.append(recent[i].low)
        
        return supports, resistances
    
    def calculate_atr(self, candles: List[Candle], period: int = 14) -> float:
        """Calculate ATR"""
        if len(candles) < period + 1:
            return 0.0
        
        true_ranges = []
        for i in range(1, len(candles)):
            high = candles[i].high
            low = candles[i].low
            prev_close = candles[i-1].close
            tr = max(high - low, abs(high - prev_close), abs(low - prev_close))
            true_ranges.append(tr)
        
        return statistics.mean(true_ranges[-period:])
    
    def generate_trend_pullback_setup(self, candles: List[Candle], asset: Asset, 
                                     regime: MarketRegime) -> Optional[StrategySetup]:
        """Strategy: Trend pullback continuation"""
        if regime not in [MarketRegime.BULLISH_TREND, MarketRegime.BEARISH_TREND]:
            return None
        
        if len(candles) < 50:
            return None
        
        current = candles[-1]
        prev = candles[-2]
        
        # Calculate EMA 20
        ema20 = sum(c.close for c in candles[-20:]) / 20
        atr = self.calculate_atr(candles)
        
        setup = StrategySetup()
        setup.strategy_type = StrategyType.TREND_PULLBACK
        
        if regime == MarketRegime.BULLISH_TREND:
            # Look for pullback to EMA and bullish rejection
            if (prev.low <= ema20 and current.close > ema20 and 
                current.close > current.open):  # Bullish candle
                
                setup.signal_type = SignalType.BUY
                setup.entry_price = current.close
                setup.entry_zone_low = current.close - (atr * 0.3)
                setup.entry_zone_high = current.close + (atr * 0.2)
                setup.stop_loss = current.low - (atr * 1.5)
                
                # Calculate targets
                risk = setup.entry_price - setup.stop_loss
                setup.take_profit_1 = setup.entry_price + (risk * 1.5)
                setup.take_profit_2 = setup.entry_price + (risk * 2.5)
                
                setup.stop_distance_pips = self.calculate_pips(asset, setup.entry_price, setup.stop_loss)
                setup.risk_reward_ratio = 1.5
                setup.expected_duration_minutes = 120
                setup.trade_horizon = TradeHorizon.STANDARD_INTRADAY
                setup.explanation = f"Bullish trend pullback to EMA20, bullish rejection candle formed"
                setup.structure_quality = 80.0
                setup.entry_quality = 75.0
                setup.target_feasibility = 80.0
                
                return setup
        
        elif regime == MarketRegime.BEARISH_TREND:
            # Look for pullback to EMA and bearish rejection
            if (prev.high >= ema20 and current.close < ema20 and 
                current.close < current.open):  # Bearish candle
                
                setup.signal_type = SignalType.SELL
                setup.entry_price = current.close
                setup.entry_zone_low = current.close - (atr * 0.2)
                setup.entry_zone_high = current.close + (atr * 0.3)
                setup.stop_loss = current.high + (atr * 1.5)
                
                # Calculate targets
                risk = setup.stop_loss - setup.entry_price
                setup.take_profit_1 = setup.entry_price - (risk * 1.5)
                setup.take_profit_2 = setup.entry_price - (risk * 2.5)
                
                setup.stop_distance_pips = self.calculate_pips(asset, setup.entry_price, setup.stop_loss)
                setup.risk_reward_ratio = 1.5
                setup.expected_duration_minutes = 120
                setup.trade_horizon = TradeHorizon.STANDARD_INTRADAY
                setup.explanation = f"Bearish trend pullback to EMA20, bearish rejection candle formed"
                setup.structure_quality = 80.0
                setup.entry_quality = 75.0
                setup.target_feasibility = 80.0
                
                return setup
        
        return None
    
    def generate_breakout_retest_setup(self, candles: List[Candle], asset: Asset,
                                      regime: MarketRegime) -> Optional[StrategySetup]:
        """Strategy: Breakout and retest"""
        if regime == MarketRegime.CHAOTIC:
            return None
        
        if len(candles) < 50:
            return None
        
        supports, resistances = self.find_support_resistance(candles)
        
        if not supports and not resistances:
            return None
        
        current = candles[-1]
        atr = self.calculate_atr(candles)
        
        setup = StrategySetup()
        setup.strategy_type = StrategyType.BREAKOUT_RETEST
        
        # Check for resistance breakout and retest (BUY)
        if resistances:
            nearest_resistance = min(resistances, key=lambda x: abs(x - current.close))
            
            # Price broke above and is retesting
            if (current.close > nearest_resistance and 
                current.low <= nearest_resistance * 1.001):  # Within 0.1% of level
                
                setup.signal_type = SignalType.BUY
                setup.entry_price = nearest_resistance
                setup.entry_zone_low = nearest_resistance - (atr * 0.3)
                setup.entry_zone_high = nearest_resistance + (atr * 0.3)
                setup.stop_loss = nearest_resistance - (atr * 2.0)
                
                risk = setup.entry_price - setup.stop_loss
                setup.take_profit_1 = setup.entry_price + (risk * 2.0)
                setup.take_profit_2 = setup.entry_price + (risk * 3.0)
                
                setup.stop_distance_pips = self.calculate_pips(asset, setup.entry_price, setup.stop_loss)
                setup.risk_reward_ratio = 2.0
                setup.expected_duration_minutes = 180
                setup.trade_horizon = TradeHorizon.STANDARD_INTRADAY
                setup.explanation = f"Resistance broken at {nearest_resistance:.5f}, retesting as support"
                setup.structure_quality = 85.0
                setup.entry_quality = 80.0
                setup.target_feasibility = 75.0
                
                return setup
        
        # Check for support breakdown and retest (SELL)
        if supports:
            nearest_support = min(supports, key=lambda x: abs(x - current.close))
            
            # Price broke below and is retesting
            if (current.close < nearest_support and 
                current.high >= nearest_support * 0.999):  # Within 0.1% of level
                
                setup.signal_type = SignalType.SELL
                setup.entry_price = nearest_support
                setup.entry_zone_low = nearest_support - (atr * 0.3)
                setup.entry_zone_high = nearest_support + (atr * 0.3)
                setup.stop_loss = nearest_support + (atr * 2.0)
                
                risk = setup.stop_loss - setup.entry_price
                setup.take_profit_1 = setup.entry_price - (risk * 2.0)
                setup.take_profit_2 = setup.entry_price - (risk * 3.0)
                
                setup.stop_distance_pips = self.calculate_pips(asset, setup.entry_price, setup.stop_loss)
                setup.risk_reward_ratio = 2.0
                setup.expected_duration_minutes = 180
                setup.trade_horizon = TradeHorizon.STANDARD_INTRADAY
                setup.explanation = f"Support broken at {nearest_support:.5f}, retesting as resistance"
                setup.structure_quality = 85.0
                setup.entry_quality = 80.0
                setup.target_feasibility = 75.0
                
                return setup
        
        return None
    
    def generate_range_rejection_setup(self, candles: List[Candle], asset: Asset,
                                      regime: MarketRegime) -> Optional[StrategySetup]:
        """Strategy: Range boundary rejection"""
        if regime != MarketRegime.RANGE:
            return None
        
        if len(candles) < 50:
            return None
        
        # Define range boundaries
        recent = candles[-50:]
        range_high = max(c.high for c in recent)
        range_low = min(c.low for c in recent)
        range_mid = (range_high + range_low) / 2
        
        current = candles[-1]
        atr = self.calculate_atr(candles)
        
        setup = StrategySetup()
        setup.strategy_type = StrategyType.RANGE_REJECTION
        
        # Rejection from range low (BUY)
        if current.low <= range_low * 1.002 and current.close > range_low:
            setup.signal_type = SignalType.BUY
            setup.entry_price = current.close
            setup.entry_zone_low = range_low
            setup.entry_zone_high = range_low + (atr * 0.5)
            setup.stop_loss = range_low - (atr * 1.5)
            setup.take_profit_1 = range_mid
            setup.take_profit_2 = range_high
            
            setup.stop_distance_pips = self.calculate_pips(asset, setup.entry_price, setup.stop_loss)
            risk = setup.entry_price - setup.stop_loss
            reward = setup.take_profit_1 - setup.entry_price
            setup.risk_reward_ratio = reward / risk if risk > 0 else 0
            setup.expected_duration_minutes = 240
            setup.trade_horizon = TradeHorizon.MULTI_SESSION
            setup.explanation = f"Range low rejection, targeting range high"
            setup.structure_quality = 75.0
            setup.entry_quality = 70.0
            setup.target_feasibility = 70.0
            
            return setup
        
        # Rejection from range high (SELL)
        if current.high >= range_high * 0.998 and current.close < range_high:
            setup.signal_type = SignalType.SELL
            setup.entry_price = current.close
            setup.entry_zone_low = range_high - (atr * 0.5)
            setup.entry_zone_high = range_high
            setup.stop_loss = range_high + (atr * 1.5)
            setup.take_profit_1 = range_mid
            setup.take_profit_2 = range_low
            
            setup.stop_distance_pips = self.calculate_pips(asset, setup.entry_price, setup.stop_loss)
            risk = setup.stop_loss - setup.entry_price
            reward = setup.entry_price - setup.take_profit_1
            setup.risk_reward_ratio = reward / risk if risk > 0 else 0
            setup.expected_duration_minutes = 240
            setup.trade_horizon = TradeHorizon.MULTI_SESSION
            setup.explanation = f"Range high rejection, targeting range low"
            setup.structure_quality = 75.0
            setup.entry_quality = 70.0
            setup.target_feasibility = 70.0
            
            return setup
        
        return None
    
    def generate_candidate_setups(self, candles: List[Candle], asset: Asset, 
                                 regime: MarketRegime) -> List[StrategySetup]:
        """Generate all possible setups for current market conditions"""
        setups = []
        
        # Try each strategy
        trend_pullback = self.generate_trend_pullback_setup(candles, asset, regime)
        if trend_pullback:
            setups.append(trend_pullback)
        
        breakout_retest = self.generate_breakout_retest_setup(candles, asset, regime)
        if breakout_retest:
            setups.append(breakout_retest)
        
        range_rejection = self.generate_range_rejection_setup(candles, asset, regime)
        if range_rejection:
            setups.append(range_rejection)
        
        return setups

signal_engine = SignalEngine()
