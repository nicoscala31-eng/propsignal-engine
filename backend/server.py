from fastapi import FastAPI, APIRouter, HTTPException
from dotenv import load_dotenv
from starlette.middleware.cors import CORSMiddleware
from motor.motor_asyncio import AsyncIOMotorClient
import os
import sys
import logging
from pathlib import Path
from pydantic import BaseModel, Field
from typing import List, Optional, Dict, Any
from datetime import datetime

from models import (
    User, PropProfile, Signal, SignalHistory, Notification,
    Asset, Timeframe, PropPhase, DrawdownType, AccountSettings, SignalType,
    SignalOutcome, SignalLifecycle
)
from services.signal_orchestrator import enhanced_signal_orchestrator
from services.market_scanner import init_market_scanner, market_scanner
from services.analytics_service import create_analytics_service
from services.push_notification_service import push_service
from services.signal_outcome_tracker import init_outcome_tracker, outcome_tracker
from services.macro_news_service import macro_news_service
from services.market_data_engine import market_data_engine
from engines.prop_rule_engine import prop_rule_engine
from providers.provider_manager import provider_manager

ROOT_DIR = Path(__file__).parent
load_dotenv(ROOT_DIR / '.env')

# ==================== ENVIRONMENT VALIDATION ====================

def validate_environment():
    """Validate required environment variables on startup"""
    required_vars = {
        'MONGO_URL': 'MongoDB connection string',
        'DB_NAME': 'Database name',
    }
    
    optional_vars = {
        'TWELVE_DATA_API_KEY': 'Twelve Data API key for live market data',
        'PORT': 'Server port (default: 8001)'
    }
    
    missing = []
    for var, description in required_vars.items():
        if not os.environ.get(var):
            missing.append(f"  - {var}: {description}")
    
    if missing:
        error_msg = "❌ CRITICAL: Missing required environment variables:\n" + "\n".join(missing)
        print(error_msg, file=sys.stderr)
        raise RuntimeError(error_msg)
    
    # Log optional vars status
    for var, description in optional_vars.items():
        value = os.environ.get(var)
        if value:
            # Mask sensitive values
            masked = value[:4] + "..." if len(value) > 8 else "****"
            print(f"✅ {var}: configured ({masked})")
        else:
            print(f"⚠️  {var}: not set - {description}")

# Run validation
validate_environment()

# MongoDB connection
mongo_url = os.environ['MONGO_URL']
client = AsyncIOMotorClient(mongo_url)
db = client[os.environ['DB_NAME']]

# Create the main app without a prefix
app = FastAPI(title="PropSignal Engine API", version="1.0.0")

# Create a router with the /api prefix
api_router = APIRouter(prefix="/api")

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# Initialize services
scanner = None
analytics = None
tracker = None


# ==================== STARTUP/SHUTDOWN EVENTS ====================

@app.on_event("startup")
async def startup_event():
    """Initialize market data provider and services on startup"""
    global scanner, analytics, tracker
    
    logger.info("=" * 60)
    logger.info("🚀 PROPSIGNAL ENGINE - PRODUCTION STARTUP")
    logger.info("=" * 60)
    logger.info(f"📊 Environment Configuration:")
    logger.info(f"   - PORT: {os.environ.get('PORT', '8001 (default)')}")
    logger.info(f"   - MONGO_URL: {'✅ configured' if os.environ.get('MONGO_URL') else '❌ missing'}")
    logger.info(f"   - DB_NAME: {os.environ.get('DB_NAME', 'not set')}")
    logger.info(f"   - TWELVE_DATA_API_KEY: {'✅ configured' if os.environ.get('TWELVE_DATA_API_KEY') else '❌ missing'}")
    
    # Initialize provider manager
    logger.info("-" * 40)
    logger.info("📡 Initializing Market Data Provider...")
    success = await provider_manager.initialize()
    
    if success:
        status = provider_manager.get_status()
        if provider_manager.is_simulation_mode():
            logger.warning(f"⚠️  SIMULATION MODE ACTIVE - Provider: {status.provider_name}")
        else:
            logger.info(f"✅ Production data connected - Provider: {status.provider_name}")
        
        # Test Twelve Data API with actual requests and log raw responses
        logger.info("-" * 40)
        logger.info("🔍 Testing Twelve Data API with real requests...")
        
        try:
            provider = provider_manager.get_provider()
            if provider:
                # Test EUR/USD
                eurusd_quote = await provider.get_live_quote(Asset.EURUSD)
                if eurusd_quote:
                    logger.info(f"✅ EUR/USD TEST SUCCESS:")
                    logger.info(f"   - Bid: {eurusd_quote.bid}")
                    logger.info(f"   - Ask: {eurusd_quote.ask}")
                    logger.info(f"   - Spread: {eurusd_quote.spread_pips:.2f} pips")
                    logger.info(f"   - Timestamp: {eurusd_quote.timestamp}")
                else:
                    logger.error("❌ EUR/USD TEST FAILED: No quote returned")
                
                # Test XAU/USD
                xauusd_quote = await provider.get_live_quote(Asset.XAUUSD)
                if xauusd_quote:
                    logger.info(f"✅ XAU/USD TEST SUCCESS:")
                    logger.info(f"   - Bid: {xauusd_quote.bid}")
                    logger.info(f"   - Ask: {xauusd_quote.ask}")
                    logger.info(f"   - Spread: {xauusd_quote.spread_pips:.2f} pips")
                    logger.info(f"   - Timestamp: {xauusd_quote.timestamp}")
                else:
                    logger.error("❌ XAU/USD TEST FAILED: No quote returned")
            else:
                logger.error("❌ No provider available for API tests")
                
        except Exception as e:
            logger.error(f"❌ Twelve Data API test EXCEPTION: {type(e).__name__}: {e}")
    else:
        logger.error("❌ CRITICAL: Failed to initialize market data provider")
        logger.error("   The app will continue but live prices will not be available")
    
    # Start Live Market Data Engine (continuous price updates)
    logger.info("-" * 40)
    logger.info("📈 Starting Live Market Data Engine...")
    await market_data_engine.start()
    
    # Initialize market scanner with watchdog protection
    logger.info("-" * 40)
    logger.info("🔄 Initializing Market Scanner...")
    scanner = init_market_scanner(db)
    logger.info("📊 Market Scanner initialized")
    
    # Initialize outcome tracker
    tracker = init_outcome_tracker(db)
    logger.info("📈 Outcome Tracker initialized")
    
    # Initialize analytics service
    analytics = create_analytics_service(db)
    logger.info("📈 Analytics Service initialized")
    
    # Auto-start scanner and tracker for production
    logger.info("-" * 40)
    device_count = await db.devices.count_documents({"is_active": True})
    logger.info(f"📱 Registered devices: {device_count}")
    
    # Always start scanner in production for continuous operation
    logger.info("🚀 Starting scanner and tracker for continuous operation...")
    await scanner.start()
    await tracker.start()
    
    logger.info("=" * 60)
    logger.info("✅ PROPSIGNAL ENGINE STARTUP COMPLETE")
    logger.info(f"   Scanner: {'RUNNING' if scanner.is_running else 'STOPPED'}")
    logger.info(f"   Tracker: {'RUNNING' if tracker.is_running else 'STOPPED'}")
    logger.info(f"   Market Data Engine: {'RUNNING' if market_data_engine.is_running else 'STOPPED'}")
    logger.info("=" * 60)

@app.on_event("shutdown")
async def shutdown_event():
    """Cleanup on shutdown"""
    global scanner, tracker
    
    if scanner:
        await scanner.stop()
    
    if tracker:
        await tracker.stop()
    
    await push_service.close()
    await provider_manager.shutdown()
    client.close()
    logger.info("PropSignal Engine shut down")


# ====================REQUEST/RESPONSE MODELS ====================

class CreateUserRequest(BaseModel):
    email: Optional[str] = None

class RegisterDeviceRequest(BaseModel):
    push_token: str
    platform: str  # "ios" or "android"
    device_id: str
    device_name: Optional[str] = None

class CreatePropProfileRequest(BaseModel):
    name: str
    firm_name: str
    phase: PropPhase = PropPhase.CHALLENGE
    daily_drawdown_percent: float = 5.0
    max_drawdown_percent: float = 10.0
    drawdown_type: DrawdownType = DrawdownType.BALANCE
    max_lot_exposure: Optional[float] = None
    news_rule_enabled: bool = False
    weekend_holding_allowed: bool = False
    overnight_holding_allowed: bool = True
    consistency_rule_enabled: bool = False
    max_daily_profit_percent: Optional[float] = None
    minimum_trading_days: int = 5
    minimum_profitable_days: int = 3
    minimum_trade_duration_minutes: int = 3
    initial_balance: float = 10000.0

class GenerateSignalRequest(BaseModel):
    asset: Asset
    prop_profile_id: str

class UpdateProfileBalanceRequest(BaseModel):
    current_balance: float
    current_equity: float


# ==================== HEALTH CHECK ====================

@api_router.get("/")
async def root():
    return {
        "message": "PropSignal Engine API",
        "version": "1.0.0",
        "status": "operational"
    }

@api_router.get("/health")
async def health_check():
    """
    Production health check endpoint with full diagnostics.
    Returns status of all services, live prices, and configuration.
    """
    global scanner, tracker
    
    # Get provider status
    provider_status = provider_manager.get_status()
    
    # Get prices from the Market Data Engine
    engine_prices = market_data_engine.get_all_prices()
    engine_health = market_data_engine.get_health_status()
    
    # Also try to get direct prices from provider for comparison
    direct_eurusd = None
    direct_xauusd = None
    direct_error = None
    
    try:
        provider = provider_manager.get_provider()
        if provider:
            eurusd_quote = await provider.get_live_quote(Asset.EURUSD)
            xauusd_quote = await provider.get_live_quote(Asset.XAUUSD)
            
            if eurusd_quote:
                direct_eurusd = {
                    "bid": eurusd_quote.bid,
                    "ask": eurusd_quote.ask,
                    "mid": eurusd_quote.mid_price,
                    "spread_pips": eurusd_quote.spread_pips,
                    "timestamp": eurusd_quote.timestamp.isoformat() if eurusd_quote.timestamp else None
                }
            
            if xauusd_quote:
                direct_xauusd = {
                    "bid": xauusd_quote.bid,
                    "ask": xauusd_quote.ask,
                    "mid": xauusd_quote.mid_price,
                    "spread_pips": xauusd_quote.spread_pips,
                    "timestamp": xauusd_quote.timestamp.isoformat() if xauusd_quote.timestamp else None
                }
    except Exception as e:
        direct_error = str(e)
    
    # Get scanner status with last cycle timestamp
    scanner_status = {
        "running": scanner.is_running if scanner else False,
        "total_scans": scanner.scan_count if scanner else 0,
        "signals_generated": scanner.signal_count if scanner else 0,
        "active_profile": scanner.active_profile.name if (scanner and scanner.active_profile) else None,
        "last_scan_timestamp": scanner.last_scan_time.isoformat() if (scanner and hasattr(scanner, 'last_scan_time') and scanner.last_scan_time) else None
    }
    
    # Get tracker status
    tracker_status = {
        "running": tracker.is_running if tracker else False,
        "checks_performed": tracker.checks_performed if tracker else 0
    }
    
    # Environment variables status
    env_status = {
        "MONGO_URL": bool(os.getenv('MONGO_URL')),
        "DB_NAME": bool(os.getenv('DB_NAME')),
        "TWELVE_DATA_API_KEY": bool(os.getenv('TWELVE_DATA_API_KEY')),
        "PORT": os.getenv('PORT', '8001')
    }
    
    # Determine overall health
    is_healthy = (
        (scanner and scanner.is_running) and
        (tracker and tracker.is_running) and
        market_data_engine.is_running
    )
    
    return {
        "status": "healthy" if is_healthy else "degraded",
        "timestamp": datetime.utcnow().isoformat(),
        "uptime_check": "OK",
        
        "backend": {
            "status": "running",
            "version": "1.0.0",
            "host": "0.0.0.0",
            "port": os.getenv('PORT', '8001')
        },
        
        "environment": env_status,
        
        "twelve_data": {
            "status": "connected" if (provider_status and provider_status.is_connected) else "disconnected",
            "provider": provider_status.provider_name if provider_status else "none",
            "is_production": not provider_manager.is_simulation_mode(),
            "api_key_loaded": bool(os.getenv('TWELVE_DATA_API_KEY')),
            "error": direct_error
        },
        
        "market_data_engine": engine_health,
        
        "prices": {
            "EURUSD": engine_prices.get("EURUSD") or direct_eurusd,
            "XAUUSD": engine_prices.get("XAUUSD") or direct_xauusd,
            "source": "market_data_engine" if engine_prices.get("EURUSD") else "direct_provider"
        },
        
        "timestamps": {
            "eurusd_last_update": engine_health['prices']['EURUSD']['last_successful_update'] if engine_health.get('prices', {}).get('EURUSD') else None,
            "xauusd_last_update": engine_health['prices']['XAUUSD']['last_successful_update'] if engine_health.get('prices', {}).get('XAUUSD') else None,
            "scanner_last_cycle": scanner_status.get('last_scan_timestamp'),
            "server_time": datetime.utcnow().isoformat()
        },
        
        "scanner": scanner_status,
        "tracker": tracker_status
    }


# ==================== USER MANAGEMENT ====================

@api_router.post("/users", response_model=User)
async def create_user(request: CreateUserRequest):
    """Create a new user"""
    user = User(email=request.email)
    await db.users.insert_one(user.dict())
    return user

@api_router.get("/users/{user_id}", response_model=User)
async def get_user(user_id: str):
    """Get user by ID"""
    user_data = await db.users.find_one({"id": user_id})
    if not user_data:
        raise HTTPException(status_code=404, detail="User not found")
    return User(**user_data)


# ==================== PROP PROFILE MANAGEMENT ====================

@api_router.post("/users/{user_id}/prop-profiles", response_model=PropProfile)
async def create_prop_profile(user_id: str, request: CreatePropProfileRequest):
    """Create a prop firm profile for a user"""
    
    # Verify user exists
    user = await db.users.find_one({"id": user_id})
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    
    profile = PropProfile(
        user_id=user_id,
        name=request.name,
        firm_name=request.firm_name,
        phase=request.phase,
        daily_drawdown_percent=request.daily_drawdown_percent,
        max_drawdown_percent=request.max_drawdown_percent,
        drawdown_type=request.drawdown_type,
        max_lot_exposure=request.max_lot_exposure,
        news_rule_enabled=request.news_rule_enabled,
        weekend_holding_allowed=request.weekend_holding_allowed,
        overnight_holding_allowed=request.overnight_holding_allowed,
        consistency_rule_enabled=request.consistency_rule_enabled,
        max_daily_profit_percent=request.max_daily_profit_percent,
        minimum_trading_days=request.minimum_trading_days,
        minimum_profitable_days=request.minimum_profitable_days,
        minimum_trade_duration_minutes=request.minimum_trade_duration_minutes,
        initial_balance=request.initial_balance,
        current_balance=request.initial_balance,
        current_equity=request.initial_balance
    )
    
    await db.prop_profiles.insert_one(profile.dict())
    
    # Set as active profile if user has none
    if not user.get("active_prop_profile_id"):
        await db.users.update_one(
            {"id": user_id},
            {"$set": {"active_prop_profile_id": profile.id}}
        )
    
    return profile

@api_router.get("/users/{user_id}/prop-profiles", response_model=List[PropProfile])
async def get_user_prop_profiles(user_id: str):
    """Get all prop profiles for a user"""
    profiles = await db.prop_profiles.find({"user_id": user_id}).to_list(100)
    return [PropProfile(**p) for p in profiles]

@api_router.get("/prop-profiles/{profile_id}", response_model=PropProfile)
async def get_prop_profile(profile_id: str):
    """Get a specific prop profile"""
    profile = await db.prop_profiles.find_one({"id": profile_id})
    if not profile:
        raise HTTPException(status_code=404, detail="Profile not found")
    return PropProfile(**profile)

@api_router.put("/prop-profiles/{profile_id}/balance")
async def update_profile_balance(profile_id: str, request: UpdateProfileBalanceRequest):
    """Update profile balance and equity"""
    result = await db.prop_profiles.update_one(
        {"id": profile_id},
        {"$set": {
            "current_balance": request.current_balance,
            "current_equity": request.current_equity,
            "updated_at": datetime.utcnow()
        }}
    )
    
    if result.matched_count == 0:
        raise HTTPException(status_code=404, detail="Profile not found")
    
    return {"status": "updated"}

@api_router.get("/prop-profiles/presets/{firm_name}")
async def get_preset_profile(firm_name: str, user_id: str):
    """Get preset configuration for a prop firm"""
    preset = prop_rule_engine.get_preset_profile(firm_name, user_id)
    return preset


# ==================== SIGNAL GENERATION ====================

@api_router.post("/users/{user_id}/signals/generate", response_model=Signal)
async def generate_signal(user_id: str, request: GenerateSignalRequest):
    """Generate a new trading signal with live data and position sizing"""
    
    # Get prop profile
    profile_data = await db.prop_profiles.find_one({"id": request.prop_profile_id})
    if not profile_data:
        raise HTTPException(status_code=404, detail="Prop profile not found")
    
    profile = PropProfile(**profile_data)
    
    # Get or create account settings
    settings_data = await db.account_settings.find_one({"user_id": user_id})
    if not settings_data:
        # Create default settings
        settings = AccountSettings(user_id=user_id)
        await db.account_settings.insert_one(settings.dict())
    else:
        settings = AccountSettings(**settings_data)
    
    # Calculate consecutive losses for risk adjustment
    recent_signals = await db.signals.find({
        "user_id": user_id,
        "signal_type": {"$in": ["BUY", "SELL"]}
    }).sort("created_at", -1).limit(5).to_list(5)
    
    consecutive_losses = 0
    for sig in recent_signals:
        if sig.get("sl_hit"):
            consecutive_losses += 1
        else:
            break
    
    # Generate signal with enhanced orchestrator
    signal = await enhanced_signal_orchestrator.generate_signal(
        user_id, request.asset, profile, settings, consecutive_losses
    )
    
    # Save signal to database
    await db.signals.insert_one(signal.dict())
    
    # Create signal history entry
    history = SignalHistory(
        signal_id=signal.id,
        user_id=user_id,
        event_type="created",
        event_data={"signal_type": signal.signal_type.value}
    )
    await db.signal_history.insert_one(history.dict())
    
    # Create notification if BUY or SELL
    if signal.signal_type in [SignalType.BUY, SignalType.SELL]:
        notification = Notification(
            user_id=user_id,
            title=f"{signal.signal_type.value} Signal: {signal.asset.value}",
            body=f"Lot: {signal.lot_size:.2f} | Risk: {signal.risk_percentage:.2f}% | {signal.explanation or 'New signal generated'}",
            notification_type="signal",
            data={"signal_id": signal.id}
        )
        await db.notifications.insert_one(notification.dict())
    
    return signal

@api_router.get("/users/{user_id}/signals/active", response_model=List[Signal])
async def get_active_signals(user_id: str):
    """Get all active signals for a user"""
    signals = await db.signals.find({
        "user_id": user_id,
        "is_active": True
    }).sort("created_at", -1).to_list(100)
    
    return [Signal(**s) for s in signals]

@api_router.get("/users/{user_id}/signals/latest")
async def get_latest_signal(user_id: str, asset: Optional[Asset] = None):
    """Get the latest signal for a user (optionally filtered by asset)"""
    query = {"user_id": user_id}
    if asset:
        query["asset"] = asset.value
    
    signal_data = await db.signals.find_one(
        query,
        sort=[("created_at", -1)]
    )
    
    if not signal_data:
        return None
    
    return Signal(**signal_data)

@api_router.get("/users/{user_id}/signals/history", response_model=List[Signal])
async def get_signal_history(user_id: str, limit: int = 50):
    """Get signal history for a user"""
    signals = await db.signals.find({
        "user_id": user_id
    }).sort("created_at", -1).limit(limit).to_list(limit)
    
    return [Signal(**s) for s in signals]


# ==================== GLOBAL SIGNAL QUERIES (must be before /{signal_id}) ====================

@api_router.get("/signals/active")
async def get_global_active_signals():
    """Get all active (unresolved) signals"""
    signals = await db.signals.find({
        "is_active": True,
        "is_resolved": {"$ne": True},
        "signal_type": {"$in": ["BUY", "SELL"]}
    }).sort("created_at", -1).to_list(100)
    
    return [
        {
            "id": s.get("id"),
            "asset": s.get("asset"),
            "signal_type": s.get("signal_type"),
            "entry_price": s.get("entry_price"),
            "stop_loss": s.get("stop_loss"),
            "take_profit_1": s.get("take_profit_1"),
            "confidence": s.get("confidence_score"),
            "lifecycle_stage": s.get("lifecycle_stage", "signal_created"),
            "news_risk": s.get("news_risk", False),
            "created_at": s.get("created_at").isoformat() if s.get("created_at") else None
        }
        for s in signals
    ]

@api_router.get("/signals/resolved")
async def get_global_resolved_signals(limit: int = 50):
    """Get resolved signals with outcomes"""
    signals = await db.signals.find({
        "is_resolved": True,
        "signal_type": {"$in": ["BUY", "SELL"]}
    }).sort("resolved_at", -1).limit(limit).to_list(limit)
    
    return [
        {
            "id": s.get("id"),
            "asset": s.get("asset"),
            "signal_type": s.get("signal_type"),
            "outcome": s.get("outcome"),
            "outcome_price": s.get("outcome_price"),
            "outcome_pips": s.get("outcome_pips"),
            "outcome_rr": s.get("outcome_rr_achieved"),
            "news_risk": s.get("news_risk", False),
            "created_at": s.get("created_at").isoformat() if s.get("created_at") else None,
            "resolved_at": s.get("resolved_at").isoformat() if s.get("resolved_at") else None
        }
        for s in signals
    ]


@api_router.get("/signals/{signal_id}", response_model=Signal)
async def get_signal(signal_id: str):
    """Get a specific signal by ID"""
    signal = await db.signals.find_one({"id": signal_id})
    if not signal:
        raise HTTPException(status_code=404, detail="Signal not found")
    return Signal(**signal)


# ==================== NOTIFICATIONS ====================

@api_router.get("/users/{user_id}/notifications", response_model=List[Notification])
async def get_notifications(user_id: str, unread_only: bool = False):
    """Get notifications for a user"""
    query = {"user_id": user_id}
    if unread_only:
        query["read"] = False
    
    notifications = await db.notifications.find(query).sort("created_at", -1).limit(50).to_list(50)
    return [Notification(**n) for n in notifications]

@api_router.put("/notifications/{notification_id}/read")
async def mark_notification_read(notification_id: str):
    """Mark a notification as read"""
    result = await db.notifications.update_one(
        {"id": notification_id},
        {"$set": {"read": True}}
    )
    
    if result.matched_count == 0:
        raise HTTPException(status_code=404, detail="Notification not found")
    
    return {"status": "marked_read"}


# ==================== ANALYTICS ====================

@api_router.get("/users/{user_id}/analytics/summary")
async def get_analytics_summary(user_id: str):
    """Get analytics summary for a user"""
    
    # Get all signals
    all_signals = await db.signals.find({"user_id": user_id}).to_list(1000)
    
    total_signals = len(all_signals)
    buy_signals = sum(1 for s in all_signals if s.get("signal_type") == "BUY")
    sell_signals = sum(1 for s in all_signals if s.get("signal_type") == "SELL")
    next_signals = sum(1 for s in all_signals if s.get("signal_type") == "NEXT")
    
    # Calculate average confidence for BUY/SELL
    trade_signals = [s for s in all_signals if s.get("signal_type") in ["BUY", "SELL"]]
    avg_confidence = sum(s.get("confidence_score", 0) for s in trade_signals) / len(trade_signals) if trade_signals else 0
    
    # Average risk
    avg_risk_pct = sum(s.get("risk_percentage", 0) for s in trade_signals) / len(trade_signals) if trade_signals else 0
    avg_lot_size = sum(s.get("lot_size", 0) for s in trade_signals) / len(trade_signals) if trade_signals else 0
    
    # By asset
    eurusd_count = sum(1 for s in all_signals if s.get("asset") == "EURUSD" and s.get("signal_type") != "NEXT")
    xauusd_count = sum(1 for s in all_signals if s.get("asset") == "XAUUSD" and s.get("signal_type") != "NEXT")
    
    return {
        "total_signals": total_signals,
        "buy_signals": buy_signals,
        "sell_signals": sell_signals,
        "next_signals": next_signals,
        "trade_signals": len(trade_signals),
        "average_confidence": round(avg_confidence, 1),
        "average_risk_pct": round(avg_risk_pct, 2),
        "average_lot_size": round(avg_lot_size, 2),
        "by_asset": {
            "EURUSD": eurusd_count,
            "XAUUSD": xauusd_count
        }
    }


# ==================== ACCOUNT SETTINGS ====================

@api_router.get("/users/{user_id}/settings", response_model=AccountSettings)
async def get_account_settings(user_id: str):
    """Get account settings for a user"""
    settings_data = await db.account_settings.find_one({"user_id": user_id})
    
    if not settings_data:
        # Create default settings
        settings = AccountSettings(user_id=user_id)
        await db.account_settings.insert_one(settings.dict())
        return settings
    
    return AccountSettings(**settings_data)

@api_router.put("/users/{user_id}/settings")
async def update_account_settings(user_id: str, settings: AccountSettings):
    """Update account settings"""
    settings.updated_at = datetime.utcnow()
    
    result = await db.account_settings.update_one(
        {"user_id": user_id},
        {"$set": settings.dict()},
        upsert=True
    )
    
    return {"status": "updated"}


# ==================== PROVIDER STATUS ====================

@api_router.get("/provider/status")
async def get_provider_status():
    """Get market data provider status"""
    status = provider_manager.get_status()
    
    if not status:
        return {
            "connected": False,
            "provider_name": "None",
            "is_simulation": False,
            "error": "No provider initialized"
        }
    
    return {
        "connected": status.is_connected,
        "is_healthy": status.is_healthy,
        "provider_name": status.provider_name,
        "is_simulation": provider_manager.is_simulation_mode(),
        "is_production": provider_manager.is_production_ready(),
        "last_update": status.last_update.isoformat() if status.last_update else None,
        "error_message": status.error_message
    }

@api_router.get("/provider/debug")
async def get_provider_debug():
    """DEBUG: Complete provider diagnostics"""
    import os
    from datetime import datetime
    
    # Check API key
    api_key = os.getenv('TWELVE_DATA_API_KEY')
    api_key_status = "LOADED" if api_key else "MISSING"
    api_key_preview = f"{api_key[:8]}...{api_key[-4:]}" if api_key and len(api_key) > 12 else "N/A"
    
    # Provider status
    provider = provider_manager.get_provider()
    status = provider_manager.get_status()
    
    debug_info = {
        "timestamp": datetime.utcnow().isoformat(),
        "api_key": {
            "status": api_key_status,
            "preview": api_key_preview
        },
        "provider": {
            "initialized": provider is not None,
            "type": type(provider).__name__ if provider else None,
            "is_simulation": provider_manager.is_simulation_mode(),
            "is_production": provider_manager.is_production_ready()
        },
        "connection": {
            "is_connected": status.is_connected if status else False,
            "is_healthy": status.is_healthy if status else False,
            "provider_name": status.provider_name if status else "None",
            "last_update": status.last_update.isoformat() if status and status.last_update else None,
            "last_update_age_seconds": status.last_update_age_seconds if status else None,
            "error_message": status.error_message if status else "No provider"
        }
    }
    
    return debug_info

@api_router.get("/provider/live-prices")
async def get_live_prices():
    """Get current live prices for all assets with full debug info"""
    from datetime import datetime
    
    provider = provider_manager.get_provider()
    status = provider_manager.get_status()
    
    if not provider:
        return {
            "error": "No provider available",
            "prices": {}
        }
    
    prices = {}
    
    for asset in [Asset.EURUSD, Asset.XAUUSD]:
        try:
            start_time = datetime.utcnow()
            quote = await provider.get_live_quote(asset)
            fetch_time = (datetime.utcnow() - start_time).total_seconds()
            
            if quote:
                prices[asset.value] = {
                    "bid": quote.bid,
                    "ask": quote.ask,
                    "mid": quote.mid_price,
                    "spread_pips": quote.spread_pips,
                    "timestamp": quote.timestamp.isoformat(),
                    "age_seconds": (datetime.utcnow() - quote.timestamp).total_seconds(),
                    "fetch_time_ms": round(fetch_time * 1000, 1),
                    "status": "LIVE"
                }
            else:
                prices[asset.value] = {
                    "status": "ERROR",
                    "error": "Failed to fetch quote"
                }
        except Exception as e:
            prices[asset.value] = {
                "status": "ERROR",
                "error": str(e)
            }
    
    return {
        "provider": status.provider_name if status else "Unknown",
        "is_production": provider_manager.is_production_ready(),
        "timestamp": datetime.utcnow().isoformat(),
        "prices": prices
    }

@api_router.get("/debug/live-quote/{asset}")
async def debug_live_quote(asset: str):
    """DEBUG: Get raw live quote data with full tracing"""
    try:
        asset_enum = Asset(asset)
    except ValueError:
        raise HTTPException(status_code=400, detail=f"Invalid asset: {asset}")
    
    provider = provider_manager.get_provider()
    status = provider_manager.get_status()
    
    if not provider:
        return {
            "error": "No provider available",
            "is_simulation": False,
            "provider_name": "None"
        }
    
    # Get quote
    from datetime import datetime
    start_time = datetime.utcnow()
    quote = await provider.get_live_quote(asset_enum)
    fetch_duration = (datetime.utcnow() - start_time).total_seconds()
    
    if not quote:
        return {
            "error": "Failed to fetch quote",
            "provider_name": status.provider_name,
            "is_simulation": provider_manager.is_simulation_mode(),
            "is_production": provider_manager.is_production_ready(),
            "fetch_duration_seconds": fetch_duration
        }
    
    # Calculate age
    quote_age_seconds = (datetime.utcnow() - quote.timestamp).total_seconds()
    
    return {
        "asset": asset,
        "provider_name": status.provider_name,
        "is_simulation": provider_manager.is_simulation_mode(),
        "is_production": provider_manager.is_production_ready(),
        "quote": {
            "bid": quote.bid,
            "ask": quote.ask,
            "mid": quote.mid_price,
            "spread_pips": quote.spread_pips,
            "timestamp": quote.timestamp.isoformat(),
            "age_seconds": round(quote_age_seconds, 2)
        },
        "validation": {
            "is_fresh": quote_age_seconds < 10,
            "is_stale": quote_age_seconds > 30
        },
        "fetch_duration_seconds": round(fetch_duration, 3),
        "warning": "⚠️ SIMULATION MODE - NOT REAL DATA" if provider_manager.is_simulation_mode() else None
    }


# ==================== DEVICE REGISTRATION ====================

@api_router.post("/register-device")
async def register_device(request: RegisterDeviceRequest):
    """
    Register a device for push notifications
    
    This endpoint should be called when the app launches and obtains
    an Expo push token.
    """
    # Check if device already exists
    existing = await db.devices.find_one({"device_id": request.device_id})
    
    if existing:
        # Update existing device
        await db.devices.update_one(
            {"device_id": request.device_id},
            {
                "$set": {
                    "push_token": request.push_token,
                    "platform": request.platform,
                    "device_name": request.device_name,
                    "is_active": True,
                    "updated_at": datetime.utcnow()
                }
            }
        )
        logger.info(f"📱 Device updated: {request.device_id[:20]}...")
        return {"status": "updated", "device_id": request.device_id}
    
    # Create new device
    device = {
        "id": str(datetime.utcnow().timestamp()),
        "device_id": request.device_id,
        "push_token": request.push_token,
        "platform": request.platform,
        "device_name": request.device_name,
        "is_active": True,
        "created_at": datetime.utcnow(),
        "updated_at": datetime.utcnow()
    }
    
    await db.devices.insert_one(device)
    logger.info(f"📱 New device registered: {request.device_id[:20]}...")
    
    return {"status": "registered", "device_id": request.device_id}

@api_router.delete("/devices/{device_id}")
async def unregister_device(device_id: str):
    """Unregister a device from push notifications"""
    result = await db.devices.update_one(
        {"device_id": device_id},
        {"$set": {"is_active": False, "updated_at": datetime.utcnow()}}
    )
    
    if result.matched_count == 0:
        raise HTTPException(status_code=404, detail="Device not found")
    
    return {"status": "unregistered"}

@api_router.get("/devices/count")
async def get_device_count():
    """Get count of registered devices"""
    total = await db.devices.count_documents({})
    active = await db.devices.count_documents({"is_active": True})
    
    return {
        "total_devices": total,
        "active_devices": active
    }


# ==================== MARKET SCANNER CONTROL ====================

@api_router.post("/scanner/start")
async def start_scanner():
    """Start the background market scanner"""
    if not scanner:
        raise HTTPException(status_code=500, detail="Scanner not initialized")
    
    if scanner.is_running:
        return {"status": "already_running", "message": "Scanner is already running"}
    
    await scanner.start()
    return {"status": "started", "profile": scanner.active_profile.name}

@api_router.post("/scanner/stop")
async def stop_scanner():
    """Stop the background market scanner"""
    if not scanner:
        raise HTTPException(status_code=500, detail="Scanner not initialized")
    
    if not scanner.is_running:
        return {"status": "already_stopped", "message": "Scanner is not running"}
    
    await scanner.stop()
    return {"status": "stopped"}

@api_router.get("/scanner/status")
async def get_scanner_status():
    """Get current scanner status and statistics"""
    if not scanner:
        return {"error": "Scanner not initialized"}
    
    stats = scanner.get_stats()
    return {
        "is_running": stats["is_running"],
        "active_profile": stats["active_profile"],
        "scan_interval_seconds": stats["scan_interval"],
        "statistics": {
            "total_scans": stats["scans"],
            "signals_generated": stats["signals_generated"],
            "notifications_sent": stats["notifications_sent"]
        }
    }

@api_router.post("/scanner/profile/{profile_name}")
async def set_scanner_profile(profile_name: str):
    """
    Change the operational profile
    
    Available profiles:
    - aggressive: Lower thresholds, more signals
    - defensive: Higher thresholds, fewer but higher quality signals
    - prop_firm_safe: Balanced for prop firm trading
    """
    if not scanner:
        raise HTTPException(status_code=500, detail="Scanner not initialized")
    
    valid_profiles = ["aggressive", "defensive", "prop_firm_safe"]
    if profile_name.lower() not in valid_profiles:
        raise HTTPException(
            status_code=400, 
            detail=f"Invalid profile. Choose from: {valid_profiles}"
        )
    
    scanner.set_profile(profile_name)
    return {"status": "profile_changed", "new_profile": scanner.active_profile.name}


# ==================== ENHANCED ANALYTICS ====================

@api_router.get("/analytics/performance")
async def get_performance_analytics(user_id: Optional[str] = None):
    """Get comprehensive performance analytics"""
    if not analytics:
        raise HTTPException(status_code=500, detail="Analytics service not initialized")
    
    metrics = await analytics.get_performance_metrics(user_id=user_id)
    
    return {
        "summary": {
            "total_signals": metrics.total_signals,
            "buy_signals": metrics.buy_signals,
            "sell_signals": metrics.sell_signals,
            "next_signals": metrics.next_signals
        },
        "performance": {
            "win_rate": round(metrics.win_rate, 1),
            "loss_rate": round(metrics.loss_rate, 1),
            "winning_trades": metrics.winning_trades,
            "losing_trades": metrics.losing_trades,
            "pending_trades": metrics.pending_trades
        },
        "risk_metrics": {
            "average_rr_ratio": round(metrics.average_rr_ratio, 2),
            "profit_factor": round(metrics.profit_factor, 2),
            "expectancy": round(metrics.expectancy, 2),
            "max_drawdown_pct": metrics.max_drawdown_pct,
            "current_drawdown_pct": metrics.current_drawdown_pct
        },
        "streaks": {
            "longest_winning": metrics.longest_winning_streak,
            "longest_losing": metrics.longest_losing_streak
        },
        "by_asset": metrics.signals_per_asset,
        "by_regime": metrics.signals_per_regime,
        "win_rate_by_asset": metrics.win_rate_per_asset,
        "win_rate_by_regime": metrics.win_rate_per_regime,
        "activity": {
            "signals_today": metrics.signals_today,
            "signals_this_week": metrics.signals_this_week,
            "signals_this_month": metrics.signals_this_month
        }
    }

@api_router.get("/analytics/distribution")
async def get_signal_distribution(user_id: Optional[str] = None, days: int = 30):
    """Get signal distribution over time"""
    if not analytics:
        raise HTTPException(status_code=500, detail="Analytics service not initialized")
    
    return await analytics.get_signal_distribution(user_id=user_id, days=days)

@api_router.get("/analytics/recent-trades")
async def get_recent_trades(user_id: Optional[str] = None, limit: int = 10):
    """Get recent trade summaries"""
    if not analytics:
        raise HTTPException(status_code=500, detail="Analytics service not initialized")
    
    return await analytics.get_recent_trades_summary(user_id=user_id, limit=limit)


# ==================== PUSH NOTIFICATION STATS ====================

@api_router.get("/push/stats")
async def get_push_stats():
    """Get push notification statistics"""
    return push_service.get_stats()

@api_router.post("/push/test")
async def send_test_notification(device_id: Optional[str] = None):
    """Send a test push notification"""
    if device_id:
        device = await db.devices.find_one({"device_id": device_id, "is_active": True})
        if not device:
            raise HTTPException(status_code=404, detail="Device not found")
        tokens = [device["push_token"]]
    else:
        devices = await db.devices.find({"is_active": True}).to_list(100)
        tokens = [d["push_token"] for d in devices if d.get("push_token")]
    
    if not tokens:
        return {"status": "no_devices", "message": "No active devices to send to"}
    
    results = await push_service.send_to_all_devices(
        tokens=tokens,
        title="🧪 Test Notification",
        body="This is a test notification from PropSignal Engine",
        data={"type": "test"}
    )
    
    successful = sum(1 for r in results if r.success)
    return {
        "status": "sent",
        "total": len(results),
        "successful": successful,
        "failed": len(results) - successful
    }


# ==================== OUTCOME TRACKER ====================

@api_router.get("/tracker/status")
async def get_tracker_status():
    """Get signal outcome tracker status"""
    if not tracker:
        return {"error": "Tracker not initialized"}
    
    return tracker.get_stats()

@api_router.post("/tracker/start")
async def start_tracker():
    """Start the signal outcome tracker"""
    if not tracker:
        raise HTTPException(status_code=500, detail="Tracker not initialized")
    
    if tracker.is_running:
        return {"status": "already_running"}
    
    await tracker.start()
    return {"status": "started"}

@api_router.post("/tracker/stop")
async def stop_tracker():
    """Stop the signal outcome tracker"""
    if not tracker:
        raise HTTPException(status_code=500, detail="Tracker not initialized")
    
    if not tracker.is_running:
        return {"status": "already_stopped"}
    
    await tracker.stop()
    return {"status": "stopped"}


# ==================== NEWS CALENDAR ====================

@api_router.get("/news/upcoming")
async def get_upcoming_news():
    """Get upcoming high-impact news events"""
    return await macro_news_service.get_news_calendar(days=7)

@api_router.get("/news/check/{asset}")
async def check_news_risk(asset: str):
    """Check news risk for a specific asset"""
    try:
        asset_enum = Asset(asset)
    except ValueError:
        raise HTTPException(status_code=400, detail=f"Invalid asset: {asset}")
    
    return await macro_news_service.check_news_risk(asset_enum, minutes_window=30)

@api_router.post("/news/simulate")
async def simulate_news_event(
    event_name: str,
    currency: str,
    minutes_from_now: int = 15
):
    """Add a simulated news event for testing"""
    macro_news_service.add_simulated_event(
        event_name=event_name,
        currency=currency,
        minutes_from_now=minutes_from_now
    )
    return {
        "status": "added",
        "event_name": event_name,
        "currency": currency,
        "minutes_from_now": minutes_from_now
    }


# ==================== SIGNAL LIFECYCLE ====================

@api_router.get("/signals/{signal_id}/lifecycle")
async def get_signal_lifecycle(signal_id: str):
    """Get full signal lifecycle history"""
    signal = await db.signals.find_one({"id": signal_id})
    
    if not signal:
        raise HTTPException(status_code=404, detail="Signal not found")
    
    return {
        "signal_id": signal_id,
        "asset": signal.get("asset"),
        "signal_type": signal.get("signal_type"),
        "outcome": signal.get("outcome", "PENDING"),
        "lifecycle_stage": signal.get("lifecycle_stage", "signal_created"),
        "lifecycle_history": signal.get("lifecycle_history", []),
        "news_risk": signal.get("news_risk", False),
        "news_event": signal.get("news_event"),
        "created_at": signal.get("created_at").isoformat() if signal.get("created_at") else None,
        "resolved_at": signal.get("resolved_at").isoformat() if signal.get("resolved_at") else None,
        "is_resolved": signal.get("is_resolved", False)
    }


# ==================== SYSTEM STATUS ====================

@api_router.get("/system/status")
async def get_system_status():
    """Get complete system status"""
    scanner_stats = scanner.get_stats() if scanner else {"error": "not initialized"}
    tracker_stats = tracker.get_stats() if tracker else {"error": "not initialized"}
    push_stats = push_service.get_stats()
    provider_status = provider_manager.get_status()
    
    device_count = await db.devices.count_documents({"is_active": True})
    active_signals = await db.signals.count_documents({"is_active": True, "is_resolved": {"$ne": True}, "signal_type": {"$in": ["BUY", "SELL"]}})
    total_signals = await db.signals.count_documents({})
    
    return {
        "timestamp": datetime.utcnow().isoformat(),
        "provider": {
            "name": provider_status.provider_name if provider_status else "Unknown",
            "connected": provider_status.is_connected if provider_status else False,
            "is_production": provider_manager.is_production_ready()
        },
        "scanner": scanner_stats,
        "tracker": tracker_stats,
        "push": push_stats,
        "database": {
            "active_devices": device_count,
            "active_signals": active_signals,
            "total_signals": total_signals
        }
    }


# Include the router in the main app
app.include_router(api_router)

app.add_middleware(
    CORSMiddleware,
    allow_credentials=True,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

@app.on_event("shutdown")
async def shutdown_db_client():
    client.close()


# ==================== PRODUCTION SERVER ENTRY POINT ====================

if __name__ == "__main__":
    import uvicorn
    
    # Get port from environment (Railway sets PORT)
    port = int(os.environ.get("PORT", 8001))
    
    logger.info(f"🚀 Starting PropSignal Engine on 0.0.0.0:{port}")
    
    uvicorn.run(
        "server:app",
        host="0.0.0.0",
        port=port,
        log_level="info",
        reload=False  # Disable reload in production
    )
