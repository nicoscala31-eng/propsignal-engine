from fastapi import FastAPI, APIRouter, HTTPException
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from dotenv import load_dotenv
from starlette.middleware.cors import CORSMiddleware
from motor.motor_asyncio import AsyncIOMotorClient
import os
import sys
import logging
import asyncio
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
from services.advanced_scanner import init_advanced_scanner, advanced_scanner
from services.signal_generator_v3 import init_signal_generator, signal_generator_v3
from services.analytics_service import create_analytics_service
from services.push_notification_service import push_service
from services.signal_outcome_tracker import init_outcome_tracker, outcome_tracker
from services.macro_news_service import macro_news_service
from services.market_data_engine import market_data_engine
from services.market_data_fetch_engine import market_data_fetch_engine
from services.market_data_cache import market_data_cache
from services.device_storage_service import device_storage
from engines.prop_rule_engine import prop_rule_engine
from engines.mtf_bias_engine import mtf_bias_engine
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
        print("⚠️  Server will start but database features will not work!", file=sys.stderr)
        # Set defaults to prevent crash
        if not os.environ.get('MONGO_URL'):
            os.environ['MONGO_URL'] = 'mongodb://localhost:27017'
        if not os.environ.get('DB_NAME'):
            os.environ['DB_NAME'] = 'propsignal'
    
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

# MongoDB connection - optional, lazy loading
mongo_url = os.environ.get('MONGO_URL', '')
db = None
client = None

if mongo_url:
    try:
        import certifi
        
        # Configure connection options for MongoDB Atlas
        connection_options = {
            'serverSelectionTimeoutMS': 10000,
            'connectTimeoutMS': 20000,
            'retryWrites': True,
            'w': 'majority'
        }
        
        # Add TLS options for Atlas connections with certifi
        if 'mongodb.net' in mongo_url or 'mongodb+srv' in mongo_url:
            connection_options['tls'] = True
            connection_options['tlsCAFile'] = certifi.where()
        
        client = AsyncIOMotorClient(mongo_url, **connection_options)
        db = client[os.environ.get('DB_NAME', 'propsignal')]
        print("✅ MongoDB configured")
    except ImportError:
        print("⚠️ certifi not installed, trying without TLS config")
        try:
            client = AsyncIOMotorClient(mongo_url, serverSelectionTimeoutMS=5000)
            db = client[os.environ.get('DB_NAME', 'propsignal')]
            print("✅ MongoDB configured (no certifi)")
        except Exception as e:
            print(f"⚠️ MongoDB connection error: {e}")
            db = None
    except Exception as e:
        print(f"⚠️ MongoDB connection error: {e}")
        db = None
else:
    print("⚠️ MongoDB not configured - running without database")

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
advanced_scanner_instance = None
signal_generator_instance = None
analytics = None
tracker = None


# ==================== STARTUP/SHUTDOWN EVENTS ====================

@app.on_event("startup")
async def startup_event():
    """Initialize market data provider and services on startup"""
    global scanner, advanced_scanner_instance, signal_generator_instance, analytics, tracker
    
    logger.info("=" * 60)
    logger.info("🚀 PROPSIGNAL ENGINE - PRODUCTION STARTUP")
    logger.info("=" * 60)
    logger.info(f"📊 Environment Configuration:")
    logger.info(f"   - PORT: {os.environ.get('PORT', '8080 (default)')}")
    logger.info(f"   - MONGO_URL: {'✅ configured' if os.environ.get('MONGO_URL') else '❌ missing'}")
    logger.info(f"   - DB_NAME: {os.environ.get('DB_NAME', 'not set')}")
    logger.info(f"   - TWELVE_DATA_API_KEY: {'✅ configured' if os.environ.get('TWELVE_DATA_API_KEY') else '❌ missing'}")
    
    try:
        # Initialize provider manager
        logger.info("-" * 40)
        logger.info("📡 Initializing Market Data Provider...")
        success = await provider_manager.initialize()
        
        if success:
            status = provider_manager.get_status()
            logger.info(f"✅ Provider initialized: {status.provider_name}")
        else:
            logger.warning("⚠️ Provider initialization returned False")
    except Exception as e:
        logger.error(f"❌ Provider initialization error: {e}")
    
    try:
        # Start Market Data Fetch Engine (centralized API calls)
        logger.info("📡 Starting Market Data Fetch Engine (centralized fetch)...")
        await market_data_fetch_engine.start()
        logger.info("✅ Fetch Engine started - prices every 10s, candles every 60s")
    except Exception as e:
        logger.error(f"❌ Market Data Fetch Engine error: {e}")
    
    try:
        # Start Live Market Data Engine (backward compatibility)
        logger.info("📈 Starting Live Market Data Engine...")
        await market_data_engine.start()
    except Exception as e:
        logger.error(f"❌ Market Data Engine error: {e}")
    
    # ========== PRODUCTION CONTROL INITIALIZATION ==========
    from services.production_control import production_control, EngineType
    production_control.initialize()
    logger.info("🛡️ Production Control Service ACTIVE")
    
    try:
        # Initialize market scanners
        logger.info("🔄 Initializing Signal Generators...")
        if db is not None:
            # ========== LEGACY SCANNERS - DISABLED FOR PRODUCTION ==========
            # These are kept for reference/development ONLY
            # They are NOT started and cannot generate production signals
            
            # Legacy scanner - BLOCKED in production
            scanner = init_market_scanner(db)
            if not production_control.guard_production_startup(EngineType.MARKET_SCANNER_LEGACY):
                logger.warning("🚫 Legacy Scanner BLOCKED - Not starting (production safety)")
                scanner = None
            
            # Advanced Scanner v2 - BLOCKED in production
            logger.info("📊 Advanced Scanner v2 - checking production guard...")
            advanced_scanner_instance = init_advanced_scanner(db)
            if not production_control.guard_production_startup(EngineType.ADVANCED_SCANNER_V2):
                logger.warning("🚫 Advanced Scanner v2 BLOCKED - Not starting (production safety)")
                advanced_scanner_instance = None
            
            # ========== AUTHORIZED PRODUCTION ENGINE ==========
            # Signal Generator v3 - THE ONLY authorized production engine
            logger.info("🚀 Initializing Signal Generator v3 (PRIMARY - threshold 60%)...")
            signal_generator_instance = await init_signal_generator(db)
            
            if production_control.guard_production_startup(EngineType.SIGNAL_GENERATOR_V3):
                logger.info("✅ Signal Generator v3 AUTHORIZED for production")
            
            tracker = init_outcome_tracker(db)
            analytics = create_analytics_service(db)
            
            # Start Outcome Tracker v2 (passive performance monitoring)
            from services.signal_outcome_tracker_v2 import signal_outcome_tracker
            await signal_outcome_tracker.start()
            
            # ========== START ONLY AUTHORIZED ENGINE ==========
            # DO NOT start legacy scanners - they are blocked
            # scanner.start() - REMOVED - Legacy scanner blocked
            # advanced_scanner_instance.start() - REMOVED - Advanced scanner blocked
            
            await signal_generator_instance.start()  # ONLY PRODUCTION ENGINE
            await tracker.start()
            
            # ========== START MISSED OPPORTUNITY SIMULATION (AUDIT) ==========
            # Background task for simulating rejected trades - AUDIT ONLY
            from services.missed_opportunity_analyzer import run_periodic_simulation
            asyncio.create_task(run_periodic_simulation())
            logger.info("📊 Missed Opportunity Analyzer background simulation started")
            
            logger.info("=" * 60)
            logger.info("🛡️ PRODUCTION SAFETY ACTIVE")
            logger.info("   ✅ Signal Generator v3: RUNNING (authorized)")
            logger.info("   🚫 Legacy Scanner: BLOCKED")
            logger.info("   🚫 Advanced Scanner v2: BLOCKED")
            logger.info("   📊 Missed Opportunity Analyzer: RUNNING (audit only)")
            logger.info("=" * 60)
        else:
            logger.warning("⚠️ Scanner/Tracker disabled - no database")
    except Exception as e:
        logger.error(f"❌ Scanner/Tracker initialization error: {e}")
    
    logger.info("=" * 60)
    logger.info("✅ PROPSIGNAL ENGINE STARTUP COMPLETE")
    logger.info("=" * 60)

@app.on_event("shutdown")
async def shutdown_event():
    """Cleanup on shutdown"""
    global scanner, advanced_scanner_instance, signal_generator_instance, tracker
    
    if scanner:
        await scanner.stop()
    
    if advanced_scanner_instance:
        await advanced_scanner_instance.stop()
    
    if signal_generator_instance:
        await signal_generator_instance.stop()
    
    if tracker:
        await tracker.stop()
    
    # Stop outcome tracker
    try:
        from services.signal_outcome_tracker_v2 import signal_outcome_tracker
        await signal_outcome_tracker.stop()
    except:
        pass
    
    # Stop fetch engine
    await market_data_fetch_engine.stop()
    
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
    profiles = await db.prop_profiles.find({"user_id": user_id}).limit(100).to_list(100)
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
    projection = {
        "id": 1, "signal_type": 1, "asset": 1, "entry_price": 1, 
        "stop_loss": 1, "take_profit_1": 1, "confidence_score": 1, 
        "created_at": 1, "is_active": 1, "user_id": 1
    }
    signals = await db.signals.find({
        "user_id": user_id,
        "is_active": True
    }, projection).sort("created_at", -1).limit(100).to_list(100)
    
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
    
    # Get all signals with projection for needed fields only
    projection = {
        "signal_type": 1, 
        "confidence_score": 1, 
        "risk_percentage": 1, 
        "lot_size": 1, 
        "asset": 1, 
        "_id": 0
    }
    all_signals = await db.signals.find({"user_id": user_id}, projection).to_list(1000)
    
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
    """Get current live prices for all assets from the centralized market data engine"""
    
    # Use the centralized market data engine instead of direct provider calls
    # This respects rate limits and provides cached data
    engine_prices = market_data_engine.get_all_prices()
    status = provider_manager.get_status()
    
    prices = {}
    
    for asset in [Asset.EURUSD, Asset.XAUUSD]:
        engine_price = engine_prices.get(asset.value)
        
        if engine_price:
            prices[asset.value] = {
                "bid": engine_price["bid"],
                "ask": engine_price["ask"],
                "mid": engine_price["mid"],
                "spread_pips": engine_price["spread_pips"],
                "timestamp": engine_price["timestamp"],
                "age_seconds": engine_price["age_seconds"],
                "status": "STALE" if engine_price["is_stale"] else "LIVE"
            }
        else:
            prices[asset.value] = {
                "status": "NO_DATA",
                "error": "No data available yet - check /api/health for engine status"
            }
    
    return {
        "provider": status.provider_name if status else "Unknown",
        "is_production": provider_manager.is_production_ready(),
        "timestamp": datetime.utcnow().isoformat(),
        "engine_running": market_data_engine.is_running,
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
    
    This endpoint uses resilient storage that works with:
    - MongoDB (primary, when available)
    - File-based storage (fallback, always available)
    """
    # Log incoming request
    logger.info(f"📱 Device registration request: platform={request.platform}, device_id={request.device_id[:20] if request.device_id else 'None'}...")
    logger.info(f"📱 Token: {request.push_token[:30] if request.push_token else 'None'}...")
    
    # Validate token format
    if not request.push_token:
        logger.error("❌ Missing push_token")
        raise HTTPException(status_code=400, detail="push_token is required")
    
    if not request.device_id:
        logger.error("❌ Missing device_id")
        raise HTTPException(status_code=400, detail="device_id is required")
    
    if not request.platform or request.platform not in ['ios', 'android', 'web']:
        logger.error(f"❌ Invalid platform: {request.platform}")
        raise HTTPException(status_code=400, detail="platform must be 'ios', 'android', or 'web'")
    
    # Validate Expo push token format (warning only, not blocking)
    if not request.push_token.startswith('ExponentPushToken[') and not request.push_token.startswith('ExpoPushToken['):
        logger.warning(f"⚠️ Unusual token format (not Expo): {request.push_token[:30]}...")
    
    try:
        # Use resilient device storage
        result = await device_storage.register_device(
            device_id=request.device_id,
            push_token=request.push_token,
            platform=request.platform,
            device_name=request.device_name
        )
        
        logger.info(f"✅ Device {result['status']}: {request.device_id[:20]}... (backend: {result.get('storage_backend', 'unknown')})")
        
        return {
            "status": result['status'],
            "device_id": result['device_id']
        }
        
    except Exception as e:
        logger.error(f"❌ Device registration error: {str(e)}")
        import traceback
        logger.error(f"❌ Stack trace: {traceback.format_exc()}")
        raise HTTPException(status_code=500, detail=f"Registration error: {str(e)}")

@api_router.delete("/devices/{device_id}")
async def unregister_device(device_id: str):
    """Unregister a device from push notifications"""
    try:
        success = await device_storage.deactivate_device(device_id)
        if not success:
            raise HTTPException(status_code=404, detail="Device not found")
        return {"status": "unregistered"}
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"❌ Error unregistering device: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Error: {str(e)}")

@api_router.get("/devices/count")
async def get_device_count():
    """Get count of registered devices"""
    try:
        counts = await device_storage.get_device_count()
        return counts
    except Exception as e:
        logger.error(f"❌ Error counting devices: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Error: {str(e)}")


@api_router.get("/devices/list")
async def list_devices():
    """List all registered devices (for debugging)"""
    try:
        devices = await device_storage.get_active_devices()
        return {
            "count": len(devices),
            "devices": [
                {
                    "device_id": d.device_id[:20] + "...",
                    "platform": d.platform,
                    "token_prefix": d.push_token[:40] + "..." if d.push_token else None,
                    "is_active": d.is_active,
                    "created_at": d.created_at
                }
                for d in devices
            ]
        }
    except Exception as e:
        logger.error(f"❌ Error listing devices: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Error: {str(e)}")


@api_router.post("/push/test-debug")
async def send_test_notification_debug():
    """Send test push with full debug info"""
    try:
        devices = await device_storage.get_active_devices()
        if not devices:
            return {"status": "error", "message": "No devices registered"}
        
        results = []
        for device in devices:
            token = device.push_token
            logger.info(f"📬 Testing push to token: {token}")
            
            # Test directly with Expo API
            import aiohttp
            async with aiohttp.ClientSession() as session:
                payload = {
                    "to": token,
                    "title": "🔔 PropSignal Test",
                    "body": "Test notification - se vedi questo, le notifiche funzionano!",
                    "sound": "default",
                    "data": {"type": "test"}
                }
                
                async with session.post(
                    "https://exp.host/--/api/v2/push/send",
                    json=payload,
                    headers={"Content-Type": "application/json"}
                ) as response:
                    resp_data = await response.json()
                    results.append({
                        "device_id": device.device_id,
                        "token_length": len(token),
                        "token_valid_format": token.startswith("ExponentPushToken["),
                        "http_status": response.status,
                        "expo_response": resp_data
                    })
                    logger.info(f"📬 Expo response: {resp_data}")
        
        return {
            "status": "debug_complete",
            "results": results
        }
    except Exception as e:
        logger.error(f"❌ Debug push error: {str(e)}")
        return {"status": "error", "message": str(e)}


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


@api_router.get("/scanner/v2/status")
async def get_advanced_scanner_status():
    """
    Get Advanced Scanner v2 status with MTF bias and scoring details
    
    Returns:
    - Version and running state
    - Configuration (thresholds, enabled setups)
    - Statistics (scans, signals, notifications)
    - Recent signals per asset
    """
    if not advanced_scanner_instance:
        return {"error": "Advanced Scanner v2 not initialized"}
    
    stats = advanced_scanner_instance.get_stats()
    
    return {
        "version": stats["version"],
        "is_running": stats["is_running"],
        "uptime_seconds": stats["uptime_seconds"],
        "scan_interval_seconds": stats["scan_interval"],
        
        "configuration": stats["config"],
        
        "statistics": {
            "total_scans": stats["scan_count"],
            "signals_generated": stats["signal_count"],
            "notifications_sent": stats["notification_count"]
        },
        
        "recent_signals_count": stats["recent_signals"]
    }


@api_router.get("/scanner/v3/status")
async def get_signal_generator_v3_status():
    """
    Get status of Signal Generator v3 (confidence-based)
    
    This is the PRIMARY signal generator with:
    - Minimum threshold: 60%
    - Classification: STRONG (80+), GOOD (70-79), ACCEPTABLE (60-69), REJECTED (<60)
    - Position Sizing Engine (lot_size, money_at_risk, risk_percent, pip_risk)
    - Prop Firm Awareness ($100k account, $3k max daily loss)
    - News Risk Detection
    - Advanced MTF Bias Scoring
    """
    if not signal_generator_instance:
        return {"error": "Signal Generator v3 not initialized"}
    
    stats = signal_generator_instance.get_stats()
    
    return {
        "version": stats["version"],
        "mode": stats["mode"],
        "is_running": stats["is_running"],
        "uptime_seconds": stats["uptime_seconds"],
        "min_confidence_threshold": stats["min_confidence"],
        "classification": stats["classification"],
        
        "statistics": {
            "total_scans": stats["scan_count"],
            "signals_generated": stats["signal_count"],
            "notifications_sent": stats["notification_count"],
            "rejections": stats["rejection_count"],
            "invalid_tokens_removed": stats.get("invalid_tokens_removed", 0)
        },
        
        "duplicate_window_minutes": stats["duplicate_window_minutes"],
        "recent_signals_count": stats["recent_signals"],
        
        # NEW: Prop firm configuration and risk status
        "prop_config": stats.get("prop_config", {}),
        "daily_risk_status": stats.get("daily_risk_status", {})
    }


@api_router.post("/scanner/v3/reset-daily-risk")
async def reset_daily_risk():
    """
    Reset daily risk counter for Signal Generator v3
    
    Use this to start fresh for a new trading day or testing.
    """
    if not signal_generator_instance:
        return {"error": "Signal Generator v3 not initialized"}
    
    signal_generator_instance.position_sizer.daily_risk_used = 0.0
    signal_generator_instance.position_sizer.last_reset_date = datetime.utcnow().date()
    signal_generator_instance._save_state()
    
    return {
        "success": True,
        "message": "Daily risk reset to $0",
        "daily_risk_status": signal_generator_instance.position_sizer.get_daily_status()
    }


# ==================== DIRECTION QUALITY AUDIT ====================

@api_router.get("/audit/direction-quality")
async def get_direction_quality_report():
    """
    Get comprehensive Direction Quality Audit Report.
    
    This is an AUDIT-ONLY endpoint - no strategy modifications.
    
    Returns:
    - Stats by symbol + direction (EURUSD BUY/SELL, XAUUSD BUY/SELL)
    - Stats by session, confidence bucket, MTF alignment, FTA quality
    - Rejection analysis by direction
    - Top winning and losing patterns
    
    Use this data for evidence-based strategy calibration.
    """
    from services.direction_quality_audit import direction_quality_audit
    
    return direction_quality_audit.get_full_report()


@api_router.get("/audit/direction-quality/by-symbol")
async def get_direction_stats_by_symbol():
    """
    Get direction quality stats broken down by symbol + direction.
    
    Returns stats for:
    - EURUSD_BUY
    - EURUSD_SELL
    - XAUUSD_BUY
    - XAUUSD_SELL
    """
    from services.direction_quality_audit import direction_quality_audit
    
    return {
        "report_type": "by_symbol_direction",
        "stats": direction_quality_audit.get_stats_by_symbol_direction(),
        "note": "AUDIT ONLY - No weights modified"
    }


@api_router.get("/audit/direction-quality/rejections")
async def get_direction_rejection_analysis():
    """
    Get rejection analysis by direction.
    
    Shows:
    - Total BUY vs SELL rejections
    - Rejection reasons by direction
    - Rejection counts by symbol
    """
    from services.direction_quality_audit import direction_quality_audit
    
    return {
        "report_type": "rejection_analysis",
        "analysis": direction_quality_audit.get_rejection_analysis(),
        "note": "AUDIT ONLY - No weights modified"
    }


@api_router.get("/audit/direction-quality/patterns")
async def get_direction_patterns():
    """
    Get top winning and losing directional patterns.
    
    Identifies patterns like:
    - EURUSD_BUY_trending_London
    - XAUUSD_SELL_mixed_NY
    """
    from services.direction_quality_audit import direction_quality_audit
    
    return {
        "report_type": "patterns",
        "patterns": direction_quality_audit.get_top_patterns(),
        "note": "AUDIT ONLY - No weights modified"
    }


# ==================== MISSED OPPORTUNITY ANALYSIS ENDPOINTS ====================

@api_router.get("/audit/missed-opportunities")
async def get_missed_opportunities_report():
    """
    Get comprehensive Missed Opportunity Analysis report.
    
    This is an AUDIT-ONLY endpoint - no impact on live trading.
    
    Returns:
    - Overall statistics for all rejected trades
    - Simulated outcomes (TP hits, SL hits, expired)
    - Breakdown by symbol, direction, symbol+direction
    - Key insight about filter effectiveness
    
    Use this data to evaluate if rejections were correct.
    """
    from services.missed_opportunity_analyzer import missed_opportunity_analyzer
    
    return missed_opportunity_analyzer.get_full_report()


@api_router.get("/audit/missed-opportunities/by-symbol")
async def get_missed_opportunities_by_symbol():
    """
    Get missed opportunity statistics broken down by symbol.
    
    Returns stats for:
    - EURUSD: total, tp_hits, sl_hits, expired, simulated_winrate
    - XAUUSD: total, tp_hits, sl_hits, expired, simulated_winrate
    """
    from services.missed_opportunity_analyzer import missed_opportunity_analyzer
    
    report = missed_opportunity_analyzer.get_full_report()
    return {
        "report_type": "by_symbol",
        "stats": report["by_symbol"],
        "note": "AUDIT ONLY - Simulated outcomes for rejected trades"
    }


@api_router.get("/audit/missed-opportunities/by-reason")
async def get_missed_opportunities_by_reason():
    """
    Get missed opportunity statistics broken down by rejection reason.
    
    Shows simulated performance for:
    - fta_blocked: FTA filter rejections
    - low_confidence: Score below 60% threshold
    - low_rr: R:R below minimum
    - late_entry: Entry too late
    - duplicate: Duplicate signal
    """
    from services.missed_opportunity_analyzer import missed_opportunity_analyzer
    
    return missed_opportunity_analyzer.get_stats_by_reason()


@api_router.get("/audit/missed-opportunities/by-fta-bucket")
async def get_missed_opportunities_by_fta_bucket():
    """
    Get missed opportunity statistics broken down by FTA clean_space_ratio bucket.
    
    FTA Buckets (calibrated for trading):
    - very_close: ratio < 0.20 (FTA extremely close to entry)
    - close: 0.20 - 0.35
    - borderline: 0.35 - 0.50
    - near_valid: 0.50 - 0.65
    - valid: >= 0.65 (mostly clean path)
    
    Use this to evaluate if FTA filter thresholds are optimal.
    """
    from services.missed_opportunity_analyzer import missed_opportunity_analyzer
    
    return missed_opportunity_analyzer.get_stats_by_fta_bucket()


@api_router.get("/audit/missed-opportunities/top-patterns")
async def get_missed_opportunities_top_patterns():
    """
    Get top winning and losing patterns among rejected trades.
    
    Identifies patterns like:
    - EURUSD_BUY_London_trending_borderline
    - XAUUSD_SELL_NY_ranging_very_close
    
    Use this to find systematic missed opportunities.
    """
    from services.missed_opportunity_analyzer import missed_opportunity_analyzer
    
    return missed_opportunity_analyzer.get_top_patterns()


@api_router.get("/audit/missed-opportunities/samples")
async def get_missed_opportunities_samples(count: int = 5):
    """
    Get sample simulation records for verification.
    
    Returns detailed records showing:
    - Theoretical trade setup (entry, SL, TP, R:R)
    - FTA data (bucket, clean_space_ratio)
    - Simulation results (outcome, MFE, MAE, time to outcome)
    - Context at rejection (session, regime, biases)
    
    Use this to verify simulation accuracy.
    """
    from services.missed_opportunity_analyzer import missed_opportunity_analyzer
    
    return {
        "sample_count": count,
        "samples": missed_opportunity_analyzer.get_sample_simulations(count),
        "note": "AUDIT ONLY - Sample simulations for verification"
    }


@api_router.post("/audit/missed-opportunities/run-simulation")
async def trigger_missed_opportunities_simulation():
    """
    Manually trigger a simulation batch.
    
    Normally simulations run automatically in the background every 60 seconds.
    This endpoint allows manual triggering for testing.
    
    Returns number of records processed.
    """
    from services.missed_opportunity_analyzer import missed_opportunity_analyzer
    
    await missed_opportunity_analyzer.run_simulation_batch()
    
    pending = sum(1 for r in missed_opportunity_analyzer.records if not r.simulation_completed)
    completed = len(missed_opportunity_analyzer.records) - pending
    
    return {
        "status": "simulation_batch_completed",
        "total_records": len(missed_opportunity_analyzer.records),
        "completed_simulations": completed,
        "pending_simulations": pending
    }


@api_router.get("/market/validation/status")
async def get_market_validation_status():
    """
    Get market validation status and statistics
    
    Returns:
    - Current forex market status (open/closed)
    - Validation statistics (total checks, rejections)
    - Configuration (staleness thresholds, freeze detection settings)
    - Last rejection reasons per asset
    
    This endpoint helps monitor the data-validity and market-session safety layer.
    """
    from services.market_validator import market_validator
    
    summary = market_validator.get_market_status_summary()
    stats = market_validator.get_stats()
    
    return {
        "market_status": {
            "current_time_utc": summary["current_time_utc"],
            "day_of_week": summary["day_of_week"],
            "hour_utc": summary["hour_utc"],
            "forex_status": summary["forex_status"],
            "forex_open": summary["forex_open"]
        },
        "validation_statistics": summary["validation_stats"],
        "configuration": {
            "price_staleness_threshold_seconds": 120,
            "candle_staleness_threshold_seconds": 120,
            "price_freeze_threshold_seconds": 60,
            "forex_market_hours": "Sunday 22:00 UTC to Friday 22:00 UTC"
        },
        "last_rejections_by_asset": summary["last_rejections"],
        "summary": {
            "is_forex_open": stats["forex_open"],
            "total_validations": stats["validation_count"],
            "total_rejections": stats["rejection_count"]
        }
    }


# ==================== PRODUCTION CONTROL ENDPOINTS ====================

@api_router.get("/production/status")
async def get_production_status():
    """
    Get production control status
    
    Returns:
    - Scanner state (enabled/disabled)
    - Notifications state (enabled/disabled)
    - Authorized engine information
    - Blocked engines list
    - Statistics (blocks, unauthorized attempts)
    
    This is the SINGLE SOURCE OF TRUTH for production state.
    """
    from services.production_control import production_control
    return production_control.get_status()


@api_router.post("/production/scanner/{action}")
async def control_scanner(action: str):
    """
    Control scanner state - backend-enforced
    
    Actions:
    - enable: Allow scanning and signal generation
    - disable: Block ALL scanning, signal generation, and notifications
    
    When scanner is DISABLED:
    - No scans will run
    - No candidates will be generated
    - No scoring will occur
    - No notifications will be sent
    """
    from services.production_control import production_control
    
    if action.lower() == "enable":
        result = production_control.set_scanner_enabled(True, toggled_by="api")
        return {"status": "success", "action": "enabled", **result}
    elif action.lower() == "disable":
        result = production_control.set_scanner_enabled(False, toggled_by="api")
        return {"status": "success", "action": "disabled", **result}
    else:
        return {"status": "error", "message": f"Unknown action: {action}. Use 'enable' or 'disable'."}


@api_router.post("/production/notifications/{action}")
async def control_notifications(action: str):
    """
    Control notifications state - backend-enforced
    
    Actions:
    - enable: Allow push notifications
    - disable: Block ALL push notifications
    
    When notifications are DISABLED:
    - No push notifications will be sent from ANY engine
    - No legacy or parallel path can bypass this
    """
    from services.production_control import production_control
    
    if action.lower() == "enable":
        result = production_control.set_notifications_enabled(True, toggled_by="api")
        return {"status": "success", "action": "enabled", **result}
    elif action.lower() == "disable":
        result = production_control.set_notifications_enabled(False, toggled_by="api")
        return {"status": "success", "action": "disabled", **result}
    else:
        return {"status": "error", "message": f"Unknown action: {action}. Use 'enable' or 'disable'."}


@api_router.get("/production/audit")
async def get_production_audit_log(limit: int = 20):
    """
    Get production control audit log
    
    Returns recent state changes and blocked attempts for traceability.
    """
    from services.production_control import production_control
    return {
        "audit_log": production_control.get_audit_log(limit),
        "limit": limit
    }


# ==================== SIGNAL OUTCOME TRACKING ====================

@api_router.get("/signals/tracking/stats")
async def get_signal_tracking_stats():
    """
    Get signal outcome tracking statistics
    
    Returns:
    - Win/loss counts and win rate
    - Performance by asset
    - Performance by session
    - Performance by confidence bucket
    - Average MFE/MAE
    """
    from services.signal_outcome_tracker_v2 import signal_outcome_tracker
    return signal_outcome_tracker.get_stats()


@api_router.get("/signals/tracking/recent")
async def get_recent_tracked_signals(limit: int = 20):
    """
    Get recently tracked signals
    
    Returns list of signals with their current status and outcome data
    """
    from services.signal_outcome_tracker_v2 import signal_outcome_tracker
    return signal_outcome_tracker.get_recent_signals(limit)


@api_router.get("/signals/tracking/report")
async def get_signal_performance_report():
    """
    Get comprehensive signal performance report
    
    Returns:
    - Overall statistics
    - Performance breakdown by asset, session, confidence
    - Excursion analysis
    """
    from services.signal_outcome_tracker_v2 import signal_outcome_tracker
    return signal_outcome_tracker.get_performance_report()


@api_router.get("/scanner/v2/bias/{asset}")
async def get_current_mtf_bias(asset: str):
    """
    Get current Multi-Timeframe Bias analysis for an asset
    
    Returns the most recent bias analysis with:
    - H1, M15, M5 individual biases
    - Overall bias and alignment score
    - Trade direction recommendation
    """
    try:
        asset_enum = Asset(asset)
    except ValueError:
        raise HTTPException(status_code=400, detail=f"Invalid asset. Use EURUSD or XAUUSD")
    
    if asset_enum not in mtf_bias_engine.last_analysis:
        return {
            "asset": asset,
            "bias": None,
            "message": "No bias analysis available yet. Wait for next scan cycle."
        }
    
    bias = mtf_bias_engine.last_analysis[asset_enum]
    
    return {
        "asset": asset,
        "analysis_timestamp": bias.analysis_timestamp.isoformat() if bias.analysis_timestamp else None,
        
        "timeframes": {
            "h1": {
                "bias": bias.h1_bias.bias.value,
                "strength": bias.h1_bias.trend_strength,
                "structure": bias.h1_bias.structure,
                "momentum_aligned": bias.h1_bias.momentum_aligned
            },
            "m15": {
                "bias": bias.m15_bias.bias.value,
                "strength": bias.m15_bias.trend_strength,
                "structure": bias.m15_bias.structure,
                "momentum_aligned": bias.m15_bias.momentum_aligned
            },
            "m5": {
                "bias": bias.m5_bias.bias.value,
                "strength": bias.m5_bias.trend_strength,
                "structure": bias.m5_bias.structure,
                "momentum_aligned": bias.m5_bias.momentum_aligned
            }
        },
        
        "summary": {
            "overall_bias": bias.overall_bias.value,
            "alignment_score": bias.alignment_score,
            "trade_direction": bias.trade_direction,
            "is_countertrend": bias.is_countertrend
        }
    }


@api_router.get("/scanner/v2/structure/{asset}")
async def get_msb_sequence(asset: str):
    """
    Get current Market Structure Break (MSB) sequence analysis for an asset
    
    Returns the MSB -> Displacement -> Pullback sequence analysis with:
    - Structure break type and location
    - Displacement strength and type
    - Pullback zone and validation
    - Whether sequence is ready for M5 trigger
    
    CRITICAL: Signal can only be generated if sequence is complete and ready
    """
    from engines.market_structure_engine import market_structure_engine
    
    try:
        asset_enum = Asset(asset)
    except ValueError:
        raise HTTPException(status_code=400, detail=f"Invalid asset. Use EURUSD or XAUUSD")
    
    if asset_enum not in market_structure_engine.last_analysis:
        return {
            "asset": asset,
            "sequence": None,
            "message": "No MSB sequence analysis available yet. Wait for next scan cycle."
        }
    
    seq = market_structure_engine.last_analysis[asset_enum]
    
    response = {
        "asset": asset,
        "is_complete": seq.is_complete,
        "is_ready_for_trigger": seq.is_ready_for_trigger,
        "direction": seq.direction,
        "sequence_score": seq.sequence_score,
        "rejection_reason": seq.rejection_reason,
        "summary": seq.get_summary() if seq.is_complete else None
    }
    
    # Add structure break details if available
    if seq.structure_break:
        response["structure_break"] = {
            "type": seq.structure_break.type.value,
            "break_price": seq.structure_break.break_price,
            "displacement_strength": seq.structure_break.displacement_strength,
            "displacement_type": seq.structure_break.displacement_type.value,
            "is_valid": seq.structure_break.is_valid
        }
    
    # Add pullback zone details if available
    if seq.pullback_zone:
        response["pullback_zone"] = {
            "zone_type": seq.pullback_zone.zone_type.value,
            "zone_high": seq.pullback_zone.zone_high,
            "zone_low": seq.pullback_zone.zone_low,
            "strength": seq.pullback_zone.strength
        }
    
    # Add pullback validation if available
    if seq.pullback_validation:
        response["pullback_validation"] = {
            "is_valid": seq.pullback_validation.is_valid,
            "pullback_depth": seq.pullback_validation.pullback_depth,
            "pullback_type": seq.pullback_validation.pullback_type,
            "reason": seq.pullback_validation.reason
        }
    
    return response


@api_router.get("/data/cache/status")
async def get_cache_status():
    """
    Get Market Data Cache status
    
    Returns:
    - Cache statistics (reads, writes, hits, misses)
    - Per-symbol freshness status
    - Staleness warnings
    """
    return market_data_cache.get_cache_status()


@api_router.get("/data/cache/{asset}")
async def get_cached_symbol_data(asset: str):
    """
    Get cached data for a specific symbol
    
    Returns:
    - Current price data
    - Candle counts per timeframe
    - Freshness status
    """
    try:
        asset_enum = Asset(asset)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid asset. Use EURUSD or XAUUSD")
    
    summary = market_data_cache.get_symbol_summary(asset_enum)
    
    if not summary:
        return {"asset": asset, "data": None, "message": "No cached data available"}
    
    return summary


@api_router.get("/data/fetch-engine/status")
async def get_fetch_engine_status():
    """
    Get Market Data Fetch Engine status
    
    Returns:
    - Engine configuration (fetch intervals)
    - API usage statistics
    - Timing information
    - Cache health
    """
    return market_data_fetch_engine.get_status()


@api_router.get("/data/api-usage")
async def get_api_usage_estimate():
    """
    Get estimated API usage per minute
    
    Helps monitor rate limits for Twelve Data free tier (8 credits/min)
    """
    return market_data_fetch_engine.get_estimated_api_usage()


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
    try:
        if not analytics:
            # Return default empty metrics if analytics not initialized
            return {
                "summary": {"total_signals": 0, "buy_signals": 0, "sell_signals": 0, "next_signals": 0},
                "performance": {"win_rate": 0, "loss_rate": 0, "winning_trades": 0, "losing_trades": 0, "pending_trades": 0},
                "risk_metrics": {"average_rr_ratio": 0, "profit_factor": 0, "expectancy": 0, "max_drawdown_pct": 0, "current_drawdown_pct": 0},
                "streaks": {"longest_winning": 0, "longest_losing": 0},
                "by_asset": {},
                "by_regime": {},
                "win_rate_by_asset": {},
                "win_rate_by_regime": {},
                "activity": {"signals_today": 0, "signals_this_week": 0, "signals_this_month": 0},
                "note": "Analytics service not initialized"
            }
        
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
    except Exception as e:
        logger.error(f"Analytics error: {e}")
        return {
            "summary": {"total_signals": 0, "buy_signals": 0, "sell_signals": 0, "next_signals": 0},
            "performance": {"win_rate": 0, "loss_rate": 0, "winning_trades": 0, "losing_trades": 0, "pending_trades": 0},
            "risk_metrics": {"average_rr_ratio": 0, "profit_factor": 0, "expectancy": 0, "max_drawdown_pct": 0, "current_drawdown_pct": 0},
            "streaks": {"longest_winning": 0, "longest_losing": 0},
            "by_asset": {},
            "by_regime": {},
            "win_rate_by_asset": {},
            "win_rate_by_regime": {},
            "activity": {"signals_today": 0, "signals_this_week": 0, "signals_this_month": 0},
            "error": str(e)
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
    logger.info(f"📬 Test push notification requested for device: {device_id or 'all devices'}")
    
    try:
        if device_id:
            device = await device_storage.get_device(device_id)
            if not device or not device.is_active:
                logger.warning(f"⚠️ Device not found or inactive: {device_id[:20]}...")
                raise HTTPException(status_code=404, detail="Device not found")
            tokens = [device.push_token]
            logger.info(f"📬 Sending test to 1 device")
        else:
            tokens = await device_storage.get_active_tokens()
            logger.info(f"📬 Sending test to {len(tokens)} devices")
        
        if not tokens:
            logger.warning("⚠️ No active devices to send test to")
            return {"status": "no_devices", "message": "No active devices to send to"}
        
        results = await push_service.send_to_all_devices(
            tokens=tokens,
            title="🧪 Test Notification",
            body="This is a test notification from PropSignal Engine",
            data={"type": "test"}
        )
        
        successful = sum(1 for r in results if r.success)
        failed = len(results) - successful
        
        logger.info(f"📬 Test push results: {successful} successful, {failed} failed")
        
        return {
            "status": "sent",
            "total": len(results),
            "successful": successful,
            "failed": failed
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"❌ Test push error: {str(e)}")
        import traceback
        logger.error(f"❌ Stack trace: {traceback.format_exc()}")
        raise HTTPException(status_code=500, detail=f"Push error: {str(e)}")

@api_router.get("/push/health")
async def get_push_health():
    """
    Get comprehensive push notification system health status
    
    Returns:
    - Device storage status (MongoDB/File)
    - Device counts
    - Storage stats
    - Push service stats
    """
    try:
        storage_health = await device_storage.health_check()
        push_stats = push_service.get_stats()
        
        return {
            "status": "healthy",
            "device_storage": storage_health,
            "push_service": push_stats,
            "timestamp": datetime.utcnow().isoformat()
        }
    except Exception as e:
        logger.error(f"❌ Health check error: {str(e)}")
        return {
            "status": "degraded",
            "error": str(e),
            "timestamp": datetime.utcnow().isoformat()
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


# ==================== APK DOWNLOAD ENDPOINT ====================

@api_router.get("/download/apk")
async def download_apk():
    """Download the latest PropSignal APK"""
    apk_path = Path("/app/backend/static/propsignal-v5.apk")
    
    if not apk_path.exists():
        raise HTTPException(status_code=404, detail="APK not found")
    
    return FileResponse(
        path=str(apk_path),
        filename="propsignal-v5.apk",
        media_type="application/vnd.android.package-archive"
    )


@api_router.get("/download/page")
async def download_page():
    """HTML page for APK download"""
    from fastapi.responses import HTMLResponse
    html = """
<!DOCTYPE html>
<html lang="it">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Download PropSignal APK</title>
    <style>
        * { margin: 0; padding: 0; box-sizing: border-box; }
        body {
            font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
            background: linear-gradient(135deg, #0a0a0a 0%, #1a1a2e 100%);
            min-height: 100vh;
            display: flex;
            justify-content: center;
            align-items: center;
            color: #fff;
        }
        .container { text-align: center; padding: 40px; max-width: 400px; }
        .logo { font-size: 64px; margin-bottom: 20px; }
        h1 { font-size: 28px; margin-bottom: 10px; color: #00ff88; }
        .version { color: #888; margin-bottom: 30px; }
        .download-btn {
            display: inline-block;
            background: linear-gradient(135deg, #00ff88 0%, #00cc66 100%);
            color: #000;
            padding: 18px 40px;
            border-radius: 12px;
            text-decoration: none;
            font-size: 18px;
            font-weight: bold;
            margin-bottom: 20px;
        }
        .size { color: #666; font-size: 14px; margin-bottom: 30px; }
        .instructions {
            background: rgba(255,255,255,0.05);
            padding: 20px;
            border-radius: 12px;
            text-align: left;
            margin-top: 20px;
        }
        .instructions h3 { color: #00ff88; margin-bottom: 15px; }
        .instructions ol { padding-left: 20px; }
        .instructions li { margin-bottom: 10px; color: #ccc; }
    </style>
</head>
<body>
    <div class="container">
        <div class="logo">📈</div>
        <h1>PropSignal Engine</h1>
        <p class="version">Versione 5 - Push Notifications</p>
        
        <a href="/api/download/apk" class="download-btn">⬇️ Scarica APK</a>
        
        <p class="size">Dimensione: 107 MB</p>
        
        <div class="instructions">
            <h3>📱 Istruzioni:</h3>
            <ol>
                <li>Clicca "Scarica APK"</li>
                <li>Apri il file scaricato</li>
                <li>Abilita "Origini sconosciute" se richiesto</li>
                <li>Completa l'installazione</li>
                <li>Attiva le notifiche push!</li>
            </ol>
        </div>
    </div>
</body>
</html>
"""
    return HTMLResponse(content=html)


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
