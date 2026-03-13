"""
Signal Generator v3 - Confidence-Based Signal Engine
=====================================================

DESIGN PHILOSOPHY:
- Generate signals consistently instead of blocking almost everything
- Use weighted scoring to assign confidence (0-100) to each signal
- Only reject for truly invalid market conditions
- Let confidence score reflect setup quality

MINIMAL HARD REJECTION FILTERS (the only things that block signals):
1. Abnormal/excessive spread
2. Stale or missing market data
3. Extremely low volatility (dead market)
4. Technical data corruption

ALL OTHER CONDITIONS contribute to score, don't block signals.

CONFIDENCE CLASSIFICATION:
- 80-100: Strong setup (high confidence)
- 65-79: Tradable setup (medium confidence)
- 50-64: Aggressive/weaker setup (low confidence)
- Below 50: Reject (don't send notification)

DUPLICATE SUPPRESSION: Light (20-30 min window)
"""

import asyncio
import logging
from typing import Dict, List, Optional, Tuple, Any
from datetime import datetime, timedelta
from dataclasses import dataclass, field
from enum import Enum

from models import Asset, SignalType, Timeframe
from services.market_data_cache import market_data_cache
from engines.session_detector import session_detector

logger = logging.getLogger(__name__)


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
    """A generated trading signal with full metadata"""
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
    
    def to_notification_dict(self) -> Dict:
        """Format for push notification"""
        emoji = "🟢" if self.direction == "BUY" else "🔴"
        return {
            "title": f"{emoji} {self.direction} {self.asset.value}",
            "body": f"Entry: {self.entry_price:.5f} | Conf: {self.confidence_score:.0f}% | R:R {self.risk_reward:.1f}",
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
                "timestamp": self.timestamp.isoformat()
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


class SignalGeneratorV3:
    """
    Confidence-Based Signal Generator
    
    Key differences from v2:
    1. Scoring-based instead of pass/fail
    2. Only hard rejects for invalid market conditions
    3. Lighter duplicate suppression (25 min)
    4. Generates signals more frequently
    5. Clear confidence classification
    """
    
    # Scoring weights (must sum to 100)
    WEIGHTS = {
        'h1_bias': 20.0,           # H1 directional bias
        'm15_context': 15.0,       # M15 alignment/context
        'market_structure': 15.0,  # Market structure quality
        'momentum': 12.0,          # Momentum strength
        'pullback_quality': 12.0,  # Pullback to key level
        'key_level': 10.0,         # Reaction at key level
        'session': 8.0,            # Session quality
        'rr_ratio': 5.0,           # Risk/Reward ratio
        'volatility': 3.0,         # Volatility conditions
    }
    
    # Hard rejection thresholds
    MAX_SPREAD_PIPS_EURUSD = 3.0   # Max spread for EURUSD
    MAX_SPREAD_PIPS_XAUUSD = 50.0  # Max spread for XAUUSD
    MIN_ATR_MULTIPLIER = 0.3      # Minimum ATR for activity
    MAX_DATA_AGE_SECONDS = 60     # Max age of market data
    
    # Duplicate suppression
    DUPLICATE_WINDOW_MINUTES = 25  # Light duplicate window
    DUPLICATE_PRICE_ZONE_PIPS = 15 # Price zone for EURUSD
    DUPLICATE_PRICE_ZONE_XAU = 200 # Price zone for XAUUSD ($2)
    
    def __init__(self, db):
        self.db = db
        self.is_running = False
        self.scan_interval = 5  # seconds
        self.scanner_task: Optional[asyncio.Task] = None
        
        # Recent signals tracking
        self.recent_signals: List[RecentSignal] = []
        
        # Statistics
        self.scan_count = 0
        self.signal_count = 0
        self.notification_count = 0
        self.rejection_count = 0
        self.start_time: Optional[datetime] = None
        
        logger.info("🚀 Signal Generator v3 initialized")
        logger.info(f"   Duplicate window: {self.DUPLICATE_WINDOW_MINUTES} minutes")
        logger.info(f"   Min confidence: 60% (MANDATORY)")
        logger.info(f"   Classification: 80-100=STRONG, 70-79=GOOD, 60-69=ACCEPTABLE, <60=REJECTED")
    
    async def start(self):
        """Start the generator"""
        if self.is_running:
            return
        
        self.is_running = True
        self.start_time = datetime.utcnow()
        
        logger.info("=" * 60)
        logger.info("🚀 SIGNAL GENERATOR V3 STARTED")
        logger.info("   Mode: Confidence-based scoring (NO hidden thresholds)")
        logger.info("   MANDATORY Min confidence: 60%")
        logger.info("   80-100: STRONG | 70-79: GOOD | 60-69: ACCEPTABLE | <60: REJECTED")
        logger.info(f"   Scan interval: {self.scan_interval}s")
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
        logger.info("🛑 Signal Generator v3 stopped")
    
    async def _run_loop(self):
        """Main loop"""
        while self.is_running:
            try:
                await self._scan_all_assets()
            except Exception as e:
                logger.error(f"Generator error: {e}", exc_info=True)
            
            await asyncio.sleep(self.scan_interval)
    
    async def _scan_all_assets(self):
        """Scan all assets"""
        self.scan_count += 1
        
        for asset in [Asset.EURUSD, Asset.XAUUSD]:
            signal = await self._analyze_asset(asset)
            
            if signal:
                await self._process_signal(signal)
    
    async def _analyze_asset(self, asset: Asset) -> Optional[GeneratedSignal]:
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
        
        # Check spread
        max_spread = self.MAX_SPREAD_PIPS_EURUSD if asset == Asset.EURUSD else self.MAX_SPREAD_PIPS_XAUUSD
        if price_data.spread_pips > max_spread:
            logger.info(f"⏭️  {asset.value}: Spread too high ({price_data.spread_pips:.1f} pips > {max_spread})")
            return None
        
        # 4. Check minimum volatility (ATR)
        atr = self._calculate_atr(m5_candles, 14)
        if atr == 0:
            logger.debug(f"⏭️  {asset.value}: Zero volatility")
            return None
        
        # Calculate average ATR
        avg_atr = self._calculate_average_atr(m5_candles, 50)
        if avg_atr > 0 and atr < avg_atr * self.MIN_ATR_MULTIPLIER:
            logger.debug(f"⏭️  {asset.value}: Low volatility (ATR: {atr:.5f} < avg {avg_atr:.5f})")
            return None
        
        # ========== SCORING ANALYSIS ==========
        # From here, everything contributes to score
        
        current_price = price_data.mid
        session = session_detector.get_current_session()
        session_name = self._get_session_name(session)
        
        # Analyze market to determine direction
        direction, direction_score, direction_reason = self._analyze_direction(
            h1_candles, m15_candles, m5_candles
        )
        
        if not direction:
            # No clear direction - try to find any opportunity
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
        
        # 3. Market Structure Score
        struct_score, struct_reason = self._score_market_structure(m5_candles, direction)
        components.append(ScoreComponent("Market Structure", self.WEIGHTS['market_structure'], struct_score, struct_reason))
        
        # 4. Momentum Score
        mom_score, mom_reason = self._score_momentum(m5_candles, direction)
        components.append(ScoreComponent("Momentum", self.WEIGHTS['momentum'], mom_score, mom_reason))
        
        # 5. Pullback Quality Score
        pb_score, pb_reason = self._score_pullback(m5_candles, direction, current_price)
        components.append(ScoreComponent("Pullback Quality", self.WEIGHTS['pullback_quality'], pb_score, pb_reason))
        
        # 6. Key Level Score
        kl_score, kl_reason = self._score_key_level(m5_candles, current_price, direction)
        components.append(ScoreComponent("Key Level Reaction", self.WEIGHTS['key_level'], kl_score, kl_reason))
        
        # 7. Session Score
        sess_score, sess_reason = self._score_session(session)
        components.append(ScoreComponent("Session Quality", self.WEIGHTS['session'], sess_score, sess_reason))
        
        # 8. Calculate entry, SL, TP
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
        
        # 9. R:R Score
        rr_score, rr_reason = self._score_rr_ratio(rr_ratio)
        components.append(ScoreComponent("Risk/Reward", self.WEIGHTS['rr_ratio'], rr_score, rr_reason))
        
        # 10. Volatility Score
        vol_score, vol_reason = self._score_volatility(atr, avg_atr)
        components.append(ScoreComponent("Volatility", self.WEIGHTS['volatility'], vol_score, vol_reason))
        
        # Calculate final score
        final_score = sum(c.weighted_score for c in components)
        
        # Determine confidence level - MANDATORY threshold is 60
        # Classification per user requirements:
        # 80-100: STRONG, 70-79: GOOD, 60-69: ACCEPTABLE, <60: REJECTED
        if final_score >= 80:
            confidence = SignalConfidence.STRONG
        elif final_score >= 70:
            confidence = SignalConfidence.GOOD
        elif final_score >= 60:
            confidence = SignalConfidence.ACCEPTABLE
        else:
            # Below 60 - REJECTED
            confidence = SignalConfidence.REJECTED
            self.rejection_count += 1
            logger.info(f"📉 {asset.value} {direction}: Score {final_score:.0f}% < 60% (MANDATORY threshold) - Rejected")
            self._log_score_breakdown(asset, direction, components, final_score)
            return None
        
        # Check duplicate
        if self._is_duplicate(asset, direction, current_price):
            logger.debug(f"⏭️  {asset.value}: Duplicate signal suppressed")
            return None
        
        # Generate signal
        signal_id = f"{asset.value}_{direction}_{datetime.utcnow().strftime('%Y%m%d_%H%M%S')}"
        
        # Determine setup type based on scores
        setup_type = self._determine_setup_type(components)
        
        # Invalidation condition
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
            timestamp=datetime.utcnow()
        )
        
        return signal
    
    async def _process_signal(self, signal: GeneratedSignal):
        """Process a generated signal"""
        self.signal_count += 1
        
        # Log signal
        emoji = "🟢" if signal.direction == "BUY" else "🔴"
        logger.info("=" * 60)
        logger.info(f"{emoji} SIGNAL GENERATED: {signal.asset.value} {signal.direction}")
        logger.info(f"   Confidence: {signal.confidence_score:.0f}% ({signal.confidence_level.value})")
        logger.info(f"   Entry: {signal.entry_price:.5f}")
        logger.info(f"   Stop Loss: {signal.stop_loss:.5f}")
        logger.info(f"   Take Profit 1: {signal.take_profit_1:.5f}")
        logger.info(f"   Take Profit 2: {signal.take_profit_2:.5f}")
        logger.info(f"   Risk/Reward: {signal.risk_reward:.2f}")
        logger.info(f"   Setup: {signal.setup_type}")
        logger.info(f"   Session: {signal.session}")
        logger.info(f"   Invalidation: {signal.invalidation}")
        logger.info("-" * 40)
        logger.info("   SCORE BREAKDOWN:")
        for comp in signal.score_breakdown.components:
            logger.info(f"   • {comp.name}: {comp.score:.0f}% (weight: {comp.weight}%) → {comp.weighted_score:.1f} pts")
            logger.info(f"     Reason: {comp.reason}")
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
        
        # Send notification
        await self._send_notification(signal)
    
    async def _send_notification(self, signal: GeneratedSignal):
        """Send push notification for signal"""
        try:
            from services.device_storage_service import device_storage
            from services.push_notification_service import push_service
            
            tokens = await device_storage.get_active_tokens()
            
            if not tokens:
                logger.warning("📭 No devices registered for notifications")
                return
            
            notif = signal.to_notification_dict()
            
            results = await push_service.send_to_all_devices(
                tokens=tokens,
                title=notif['title'],
                body=notif['body'],
                data=notif['data']
            )
            
            successful = sum(1 for r in results if r.success)
            self.notification_count += 1
            
            logger.info(f"📤 Notification sent: {successful}/{len(results)} devices")
            
        except Exception as e:
            logger.error(f"❌ Failed to send notification: {e}")
    
    # ========== SCORING METHODS ==========
    
    def _analyze_direction(self, h1: List, m15: List, m5: List) -> Tuple[Optional[str], float, str]:
        """Determine trade direction from multi-timeframe analysis"""
        # H1 trend
        h1_trend = self._get_trend(h1[-20:]) if len(h1) >= 20 else 0
        # M15 trend
        m15_trend = self._get_trend(m15[-20:]) if len(m15) >= 20 else 0
        # M5 momentum
        m5_momentum = self._get_momentum(m5[-10:]) if len(m5) >= 10 else 0
        
        # Combined score
        total = h1_trend * 0.5 + m15_trend * 0.3 + m5_momentum * 0.2
        
        if total > 0.3:
            return "BUY", total * 100, "Bullish bias across timeframes"
        elif total < -0.3:
            return "SELL", abs(total) * 100, "Bearish bias across timeframes"
        elif abs(m5_momentum) > 0.5:
            # Use M5 momentum when HTF is unclear
            direction = "BUY" if m5_momentum > 0 else "SELL"
            return direction, 50, "M5 momentum breakout"
        
        return None, 0, "No clear direction"
    
    def _fallback_direction(self, m5: List) -> Optional[str]:
        """Fallback direction detection from M5 only"""
        if len(m5) < 5:
            return None
        
        # Simple: last 5 candles direction
        closes = [c.get('close', 0) for c in m5[-5:]]
        if closes[-1] > closes[0] * 1.0005:  # 0.05% up
            return "BUY"
        elif closes[-1] < closes[0] * 0.9995:  # 0.05% down
            return "SELL"
        return None
    
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
        return max(-1, min(1, change * 100))  # Normalize
    
    def _get_momentum(self, candles: List) -> float:
        """Get momentum (-1 to 1)"""
        if len(candles) < 3:
            return 0
        
        # Recent price action
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
        
        # Find swing highs and lows
        swing_highs = self._find_swing_points(highs, 'high')
        swing_lows = self._find_swing_points(lows, 'low')
        
        if direction == "BUY":
            # Look for higher lows
            if len(swing_lows) >= 2 and swing_lows[-1] > swing_lows[-2]:
                return 85, "Higher lows forming"
            elif len(swing_lows) >= 2 and swing_lows[-1] >= swing_lows[-2] * 0.999:
                return 65, "Equal lows holding"
            else:
                return 45, "No clear bullish structure"
        else:
            # Look for lower highs
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
    
    def _score_pullback(self, m5: List, direction: str, current_price: float) -> Tuple[float, str]:
        """Score pullback quality"""
        if len(m5) < 10:
            return 50, "Insufficient data"
        
        # Get recent range
        highs = [c.get('high', 0) for c in m5[-10:]]
        lows = [c.get('low', 0) for c in m5[-10:]]
        recent_high = max(highs)
        recent_low = min(lows)
        range_size = recent_high - recent_low
        
        if range_size == 0:
            return 50, "No range"
        
        # Calculate position in range
        position = (current_price - recent_low) / range_size
        
        if direction == "BUY":
            # Good pullback is price near recent low (38-62% of range)
            if 0.3 <= position <= 0.5:
                return 90, "Excellent pullback to key zone"
            elif 0.2 <= position <= 0.6:
                return 70, "Good pullback"
            elif position < 0.7:
                return 50, "Moderate pullback"
            else:
                return 30, "No pullback (extended)"
        else:
            # Good pullback is price near recent high
            if 0.5 <= position <= 0.7:
                return 90, "Excellent pullback to key zone"
            elif 0.4 <= position <= 0.8:
                return 70, "Good pullback"
            elif position > 0.3:
                return 50, "Moderate pullback"
            else:
                return 30, "No pullback (extended)"
    
    def _score_key_level(self, m5: List, current_price: float, direction: str) -> Tuple[float, str]:
        """Score reaction at key level"""
        if len(m5) < 20:
            return 50, "Insufficient data"
        
        # Find key levels (areas of high volume/rejection)
        closes = [c.get('close', 0) for c in m5[-20:]]
        
        # Simple: round numbers and previous swing points
        round_level_distance = current_price % (0.001 if current_price < 10 else 1)
        near_round = round_level_distance < 0.0003 or round_level_distance > 0.0007
        
        # Check for price rejection in last few candles
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
    
    def _score_session(self, session) -> Tuple[float, str]:
        """Score current trading session"""
        hour = datetime.utcnow().hour
        
        # London/NY overlap (best)
        if 13 <= hour <= 16:
            return 100, "London/NY overlap - optimal"
        # London session
        elif 7 <= hour <= 12:
            return 85, "London session - good"
        # NY session
        elif 13 <= hour <= 20:
            return 80, "NY session - good"
        # Asian session
        elif 0 <= hour <= 7:
            return 50, "Asian session - moderate"
        # Dead hours
        else:
            return 30, "Off-hours - low activity"
    
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
        
        if struct_score > 80 and pb_score > 70:
            return "Trend Continuation"
        elif mom_score > 80:
            return "Momentum Breakout"
        elif pb_score > 80:
            return "Pullback Entry"
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
    
    def get_stats(self) -> Dict:
        """Get generator statistics"""
        uptime = (datetime.utcnow() - self.start_time).total_seconds() if self.start_time else 0
        
        return {
            "is_running": self.is_running,
            "version": "v3",
            "mode": "confidence_based",
            "uptime_seconds": uptime,
            "scan_count": self.scan_count,
            "signal_count": self.signal_count,
            "notification_count": self.notification_count,
            "rejection_count": self.rejection_count,
            "recent_signals": len(self.recent_signals),
            "duplicate_window_minutes": self.DUPLICATE_WINDOW_MINUTES,
            "min_confidence": 60,
            "classification": {
                "strong": "80-100",
                "good": "70-79",
                "acceptable": "60-69",
                "rejected": "<60"
            }
        }


# Global instance
signal_generator_v3: Optional[SignalGeneratorV3] = None

async def init_signal_generator(db) -> SignalGeneratorV3:
    """Initialize the signal generator"""
    global signal_generator_v3
    signal_generator_v3 = SignalGeneratorV3(db)
    return signal_generator_v3
