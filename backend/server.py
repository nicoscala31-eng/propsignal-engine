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
from services.rejected_trade_tracker import rejected_trade_tracker
from services.pattern_engine import pattern_engine, PatternType, Session as PatternSession
from services.pattern_tracker import pattern_tracker
from services.pattern_tracker_v2 import pattern_tracker_v2
from services.pattern_signal_generator import pattern_signal_generator, OperationMode
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
    logger.info("📊 Environment Configuration:")
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
    
    # ========== DEVICE STORAGE - MONGODB CONNECTION ==========
    if db is not None:
        device_storage.set_mongodb(db)
        logger.info("✅ Device Storage connected to MongoDB (persistent)")
    else:
        logger.warning("⚠️ Device Storage using FILE storage (not persistent across deploys)")
    
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
            
            # ========== START REJECTED TRADE OUTCOME TRACKER (AUDIT) ==========
            await rejected_trade_tracker.start()
            logger.info("📊 Rejected Trade Outcome Tracker started (audit/analysis only)")
            
            # ========== START SIGNAL SNAPSHOT SERVICE ==========
            from services.signal_snapshot_service import signal_snapshot_service
            await signal_snapshot_service.initialize()
            logger.info("📸 Signal Snapshot Service initialized")
            
            # ========== START SIGNAL CLEANUP SERVICE (Daily) ==========
            from services.signal_cleanup_service import signal_cleanup_service, scheduled_cleanup_task
            asyncio.create_task(scheduled_cleanup_task())
            logger.info("🧹 Signal Cleanup Service scheduled (14-day retention)")
            
            logger.info("=" * 60)
            logger.info("🛡️ PRODUCTION SAFETY ACTIVE")
            logger.info("   ✅ Signal Generator v3: RUNNING (authorized)")
            logger.info("   🚫 Legacy Scanner: BLOCKED")
            logger.info("   🚫 Advanced Scanner v2: BLOCKED")
            logger.info("   📊 Missed Opportunity Analyzer: RUNNING (audit only)")
            logger.info("   📊 Rejected Trade Tracker: RUNNING (audit only)")
            logger.info("   📸 Signal Snapshot Service: RUNNING")
            logger.info("   🧹 Cleanup Service: SCHEDULED (14-day retention)")
            logger.info("=" * 60)
        else:
            logger.warning("⚠️ Scanner/Tracker disabled - no database")
    except Exception as e:
        logger.error(f"❌ Scanner/Tracker initialization error: {e}")
    
    logger.info("=" * 60)
    logger.info("✅ PROPSIGNAL ENGINE STARTUP COMPLETE")
    logger.info("=" * 60)
    
    # Print all registered routes for debugging
    logger.info("📋 REGISTERED API ROUTES:")
    audit_routes = []
    for route in app.routes:
        if hasattr(route, 'path'):
            if '/audit/' in route.path:
                audit_routes.append(route.path)
    
    if audit_routes:
        logger.info(f"   Found {len(audit_routes)} audit routes:")
        for r in sorted(audit_routes)[:15]:
            logger.info(f"      {r}")
        if len(audit_routes) > 15:
            logger.info(f"      ... and {len(audit_routes) - 15} more")
    else:
        logger.warning("   ⚠️ NO AUDIT ROUTES REGISTERED!")
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
        "version": "3.3.1",  # Updated with audit endpoints
        "build": "2026-03-23-audit-report",
        "status": "operational"
    }

@api_router.get("/routes")
async def list_routes():
    """
    List all registered API routes.
    Useful for debugging 404 errors in production.
    """
    routes = []
    for route in app.routes:
        if hasattr(route, 'path') and hasattr(route, 'methods'):
            routes.append({
                "path": route.path,
                "methods": list(route.methods) if route.methods else []
            })
    
    # Group by prefix
    audit_routes = [r for r in routes if '/audit/' in r['path']]
    push_routes = [r for r in routes if '/push/' in r['path']]
    scanner_routes = [r for r in routes if '/scanner/' in r['path']]
    
    return {
        "total_routes": len(routes),
        "audit_routes_count": len(audit_routes),
        "audit_routes": sorted([r['path'] for r in audit_routes]),
        "push_routes": sorted([r['path'] for r in push_routes]),
        "scanner_routes": sorted([r['path'] for r in scanner_routes]),
        "note": "All audit endpoints should be accessible at /api/audit/*"
    }

@api_router.get("/health")
async def health_check():
    """
    Production health check endpoint with full diagnostics.
    Returns status of all services, live prices, and configuration.
    IMPROVED: Self-healing status and detailed monitoring
    """
    global scanner, tracker, signal_generator_instance
    
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
    
    # Get Signal Generator v3 status (the ONLY production engine)
    v3_stats = signal_generator_instance.get_stats() if signal_generator_instance else None
    v3_health = v3_stats.get('health', {}) if v3_stats else {}
    
    scanner_status = {
        "running": signal_generator_instance.is_running if signal_generator_instance else False,
        "total_scans": v3_stats.get('scan_count', 0) if v3_stats else 0,
        "signals_generated": v3_stats.get('signal_count', 0) if v3_stats else 0,
        "version": v3_stats.get('version', 'unknown') if v3_stats else 'not initialized',
        "last_scan_timestamp": v3_health.get('last_scan_timestamp'),
        "last_scan_age_seconds": v3_health.get('scan_age_seconds'),
        "consecutive_failures": v3_health.get('consecutive_failures', 0),
        "scanner_restart_count": v3_health.get('scanner_restart_count', 0),
        "is_degraded": v3_health.get('is_degraded', False),
        "degradation_reason": v3_health.get('degradation_reason'),
        "watchdog_active": v3_health.get('watchdog_active', False)
    }
    
    # Get tracker status
    from services.signal_outcome_tracker_v2 import signal_outcome_tracker
    tracker_stats = signal_outcome_tracker.get_stats() if signal_outcome_tracker else {}
    
    tracker_status = {
        "running": signal_outcome_tracker.is_running if signal_outcome_tracker else False,
        "checks_performed": tracker_stats.get('summary', {}).get('total_tracked', 0),
        "active_trades": tracker_stats.get('summary', {}).get('active_signals', 0),
        "wins": tracker_stats.get('summary', {}).get('wins', 0),
        "losses": tracker_stats.get('summary', {}).get('losses', 0)
    }
    
    # Get device/push status
    device_stats = await device_storage.get_device_count()
    device_count = device_stats.get('total', 0) if isinstance(device_stats, dict) else device_stats
    valid_devices = device_stats.get('active', 0) if isinstance(device_stats, dict) else device_count
    
    push_status = {
        "device_count": device_count,
        "valid_devices": valid_devices,
        "can_send": valid_devices > 0,
        "status": "operational" if valid_devices > 0 else "no_valid_devices"
    }
    
    # Environment variables status
    env_status = {
        "MONGO_URL": bool(os.getenv('MONGO_URL')),
        "DB_NAME": bool(os.getenv('DB_NAME')),
        "TWELVE_DATA_API_KEY": bool(os.getenv('TWELVE_DATA_API_KEY')),
        "PORT": os.getenv('PORT', '8001')
    }
    
    # Determine overall health with detailed reasoning
    health_issues = []
    
    if not (signal_generator_instance and signal_generator_instance.is_running):
        health_issues.append("scanner_not_running")
    if v3_health.get('is_degraded'):
        health_issues.append(f"scanner_degraded: {v3_health.get('degradation_reason')}")
    if v3_health.get('scan_age_seconds') and v3_health.get('scan_age_seconds') > 30:
        health_issues.append(f"scan_stale: {v3_health.get('scan_age_seconds'):.0f}s old")
    if not (signal_outcome_tracker and signal_outcome_tracker.is_running):
        health_issues.append("tracker_not_running")
    if not market_data_engine.is_running:
        health_issues.append("market_data_engine_not_running")
    if valid_devices == 0:
        health_issues.append("no_valid_push_devices")
    
    is_healthy = len(health_issues) == 0
    
    return {
        "status": "healthy" if is_healthy else "degraded",
        "health_issues": health_issues if not is_healthy else None,
        "timestamp": datetime.utcnow().isoformat(),
        "uptime_check": "OK",
        
        "backend": {
            "status": "running",
            "version": "1.0.0-selfhealing",
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
        "tracker": tracker_status,
        "push": push_status
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

@api_router.get("/tracker/debug")
async def get_tracker_debug():
    """Debug endpoint to check tracker internal state"""
    from services.signal_outcome_tracker_v2 import signal_outcome_tracker
    
    return {
        "active_signals_count": len(signal_outcome_tracker.active_signals),
        "active_signal_ids": list(signal_outcome_tracker.active_signals.keys()),
        "completed_signals_count": len(signal_outcome_tracker.completed_signals),
        "stats": signal_outcome_tracker.stats,
        "is_running": signal_outcome_tracker.is_running,
        "data_dir": str(signal_outcome_tracker.data_dir),
        "signals_file": str(signal_outcome_tracker.signals_file),
        "signals_file_exists": signal_outcome_tracker.signals_file.exists() if hasattr(signal_outcome_tracker, 'signals_file') else "N/A"
    }


@api_router.post("/tracker/force-close/{signal_id}")
async def force_close_signal(signal_id: str, outcome: str = "sl_hit"):
    """Force close a signal for testing purposes"""
    from services.signal_outcome_tracker_v2 import signal_outcome_tracker
    
    if signal_id not in signal_outcome_tracker.active_signals:
        return {"error": f"Signal {signal_id} not found in active signals"}
    
    tracked = signal_outcome_tracker.active_signals[signal_id]
    tracked.final_outcome = outcome
    tracked.status = "closed"
    
    # Move to completed
    signal_outcome_tracker.completed_signals.append(tracked)
    del signal_outcome_tracker.active_signals[signal_id]
    
    # Update stats
    if outcome == "tp_hit":
        signal_outcome_tracker.stats["tp_hits"] += 1
    else:
        signal_outcome_tracker.stats["sl_hits"] += 1
    
    # Save
    await signal_outcome_tracker._save_data()
    
    return {
        "status": "closed",
        "signal_id": signal_id,
        "outcome": outcome,
        "active_remaining": len(signal_outcome_tracker.active_signals),
        "completed_total": len(signal_outcome_tracker.completed_signals)
    }


@api_router.get("/signals/active")
async def get_global_active_signals():
    """Get all active (unresolved) signals from tracker"""
    from services.signal_outcome_tracker_v2 import signal_outcome_tracker
    
    # Return active signals from tracker
    active = []
    for sig_id, tracked in signal_outcome_tracker.active_signals.items():
        active.append({
            "id": sig_id,
            "signal_id": sig_id,
            "asset": tracked.asset,
            "direction": tracked.direction,
            "signal_type": tracked.direction,
            "entry_price": tracked.entry_price,
            "stop_loss": tracked.stop_loss,
            "take_profit_1": tracked.take_profit_1,
            "confidence": tracked.confidence_score,
            "confidence_score": tracked.confidence_score,
            "status": tracked.status,
            "timestamp": tracked.timestamp
        })
    
    return active

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


# ==================== SIGNAL SNAPSHOT FEED (NEW - must be before /{signal_id}) ====================

@api_router.get("/signals/feed")
async def get_signal_feed(
    symbol: Optional[str] = None,
    direction: Optional[str] = None,
    status: Optional[str] = None,  # all / accepted / rejected / active / closed
    limit: int = 100,
    offset: int = 0
):
    """
    Get signal feed with complete snapshot data.
    
    Query params:
    - symbol: EURUSD or XAUUSD
    - direction: BUY or SELL
    - status: all / accepted / rejected / active / closed
    - limit: max items (default 100)
    - offset: pagination offset
    
    Returns list of signal snapshots with metadata, scores, and short reasons.
    """
    from services.signal_snapshot_service import signal_snapshot_service
    from services.signal_outcome_tracker_v2 import signal_outcome_tracker
    
    # Initialize if needed
    await signal_snapshot_service.initialize()
    
    # STEP 1: Get ALL signals from tracker first (they have priority)
    tracker_signals = []
    snapshot_ids_from_tracker = set()
    
    # Add ACTIVE signals from tracker
    if status in [None, 'all', 'active', 'accepted']:
        for sig_id, tracked in signal_outcome_tracker.active_signals.items():
            ts = tracked.timestamp
            if hasattr(ts, 'isoformat'):
                ts = ts.isoformat()
            
            tracker_signals.append({
                'signal_id': sig_id,
                'symbol': tracked.asset,
                'direction': tracked.direction,
                'status': 'active',
                'score': tracked.confidence_score or 0,
                'entry': tracked.entry_price,
                'sl': tracked.stop_loss,
                'tp': tracked.take_profit_1,
                'rr': getattr(tracked, 'risk_reward', 1.5) or 1.5,
                'session': getattr(tracked, 'session', 'Unknown') or 'Unknown',
                'setup_type': getattr(tracked, 'setup_type', 'From Tracker') or 'From Tracker',
                'short_reason': f"Score {tracked.confidence_score or 0:.1f} | Active",
                'rejection_reason': '',
                'blocking_filter': '',
                'confidence_bucket': f"{int((tracked.confidence_score or 0) // 5) * 5}+",
                'timestamp': ts,
                'outcome': None,
                'final_r': 0,
                'from_tracker': True
            })
            snapshot_ids_from_tracker.add(sig_id)
    
    # Add CLOSED signals from tracker
    if status in [None, 'all', 'closed']:
        for tracked in signal_outcome_tracker.completed_signals:
            sig_id = tracked.signal_id
            ts = tracked.timestamp
            if hasattr(ts, 'isoformat'):
                ts = ts.isoformat()
            
            tracker_signals.append({
                'signal_id': sig_id,
                'symbol': tracked.asset,
                'direction': tracked.direction,
                'status': 'closed',
                'score': tracked.confidence_score or 0,
                'entry': tracked.entry_price,
                'sl': tracked.stop_loss,
                'tp': tracked.take_profit_1,
                'rr': getattr(tracked, 'risk_reward', 1.5) or 1.5,
                'session': getattr(tracked, 'session', 'Unknown') or 'Unknown',
                'setup_type': getattr(tracked, 'setup_type', 'From Tracker') or 'From Tracker',
                'short_reason': f"Score {tracked.confidence_score or 0:.1f} | {getattr(tracked, 'final_outcome', 'closed') or 'closed'}",
                'rejection_reason': '',
                'blocking_filter': '',
                'confidence_bucket': f"{int((tracked.confidence_score or 0) // 5) * 5}+",
                'timestamp': ts,
                'outcome': getattr(tracked, 'final_outcome', None),
                'final_r': 0,
                'from_tracker': True
            })
            snapshot_ids_from_tracker.add(sig_id)
    
    # STEP 2: Get snapshots (for rejected and any missed signals)
    # When status is 'all' or None, we need BOTH accepted and rejected
    snapshot_status_filter = status
    if status in [None, 'all']:
        snapshot_status_filter = 'all'  # Get everything including rejected
    
    snapshot_feed = signal_snapshot_service.get_feed(
        symbol=symbol,
        direction=direction,
        status_filter=snapshot_status_filter,
        limit=1000,  # Get more, we'll filter later
        offset=0
    )
    
    # Filter out duplicates
    for s in snapshot_feed:
        if s.get('signal_id') not in snapshot_ids_from_tracker:
            tracker_signals.append(s)
    
    # STEP 3: Sort with priority - ACTIVE first, then CLOSED, then REJECTED
    def sort_key(s):
        status_priority = {'active': 0, 'accepted': 0, 'closed': 1, 'tp_hit': 1, 'sl_hit': 1}
        priority = status_priority.get(s.get('status', '').lower(), 2)
        # Timestamp as secondary sort (newest first)
        ts = s.get('timestamp', '') or ''
        return (priority, ts)
    
    tracker_signals.sort(key=lambda x: (sort_key(x)[0], -hash(sort_key(x)[1]) if sort_key(x)[1] else 0))
    
    # Better sort by timestamp within each priority group
    # FIXED: Explicitly handle 'rejected' status separately
    active = [s for s in tracker_signals if s.get('status') in ['active', 'accepted']]
    closed = [s for s in tracker_signals if s.get('status') in ['closed', 'tp_hit', 'sl_hit']]
    rejected = [s for s in tracker_signals if s.get('status') == 'rejected']
    others = [s for s in tracker_signals if s.get('status') not in ['active', 'accepted', 'closed', 'tp_hit', 'sl_hit', 'rejected']]
    
    # Sort each by timestamp descending
    def ts_sort(x):
        return x.get('timestamp', '') or ''
    
    active.sort(key=ts_sort, reverse=True)
    closed.sort(key=ts_sort, reverse=True)
    rejected.sort(key=ts_sort, reverse=True)
    others.sort(key=ts_sort, reverse=True)
    
    # Combine: ACTIVE first, then CLOSED, then REJECTED, then others
    feed = active + closed + rejected + others
    
    # Apply offset and limit
    feed = feed[offset:offset + limit]
    
    return {
        "count": len(feed),
        "offset": offset,
        "limit": limit,
        "signals": feed
    }


@api_router.get("/signals/feed/stats")
async def get_signal_feed_stats():
    """
    Get statistics about signal snapshots.
    
    Returns counts by status, symbol, etc.
    """
    from services.signal_snapshot_service import signal_snapshot_service
    from services.signal_outcome_tracker_v2 import signal_outcome_tracker
    
    await signal_snapshot_service.initialize()
    
    # Get base stats from snapshots
    stats = signal_snapshot_service.get_stats()
    
    # CRITICAL FIX: Merge with tracker data for accurate active/closed counts
    # Active signals from tracker
    tracker_active = len(signal_outcome_tracker.active_signals)
    tracker_closed = len(signal_outcome_tracker.completed_signals)
    
    # Count outcomes from tracker
    tracker_wins = sum(1 for s in signal_outcome_tracker.completed_signals if s.final_outcome == 'tp_hit')
    tracker_losses = sum(1 for s in signal_outcome_tracker.completed_signals if s.final_outcome == 'sl_hit')
    
    # Use tracker numbers as they are more accurate for active/closed
    stats['active'] = tracker_active
    stats['closed'] = tracker_closed
    stats['tracker_wins'] = tracker_wins
    stats['tracker_losses'] = tracker_losses
    
    return stats


@api_router.post("/signals/cleanup")
async def trigger_signal_cleanup():
    """
    Manually trigger cleanup of old signal data.
    
    Removes signals older than retention period (14 days).
    Returns cleanup statistics.
    """
    from services.signal_cleanup_service import signal_cleanup_service
    
    result = await signal_cleanup_service.run_cleanup()
    return result


@api_router.get("/signals/cleanup/stats")
async def get_cleanup_stats():
    """
    Get cleanup service statistics.
    
    Returns info about last cleanup, retention period, etc.
    """
    from services.signal_cleanup_service import signal_cleanup_service
    
    return signal_cleanup_service.get_stats()


@api_router.get("/signals/snapshot/{signal_id}")
async def get_signal_snapshot(signal_id: str):
    """
    Get complete signal snapshot with full diagnostic breakdown.
    
    Returns:
    - Metadata (symbol, direction, timestamp)
    - Trade levels (entry, SL, TP, RR)
    - Decision (accepted/rejected, reason)
    - Score breakdown (pre/post penalty, final)
    - Factor contributions (all components with scores)
    - Penalties applied (FTA, news, spread, setup)
    - Filters checked (passed/failed)
    - Reasoning (short/full summary)
    - Outcome (if trade completed)
    """
    from services.signal_snapshot_service import signal_snapshot_service
    
    await signal_snapshot_service.initialize()
    
    detail = signal_snapshot_service.get_detail(signal_id)
    
    if not detail:
        raise HTTPException(status_code=404, detail="Signal snapshot not found")
    
    return detail


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


@api_router.get("/debug/market-data")
async def debug_market_data():
    """
    DEBUG: Complete market data diagnostic endpoint
    
    Shows:
    - Current prices for all assets
    - Data source (TwelveData vs Simulation)
    - Price freshness and staleness
    - Whether bid/ask are real or calculated
    """
    from datetime import datetime
    
    provider = provider_manager.get_provider()
    status = provider_manager.get_status()
    
    is_simulation = provider_manager.is_simulation_mode()
    is_production = provider_manager.is_production_ready()
    
    result = {
        "timestamp": datetime.utcnow().isoformat(),
        "provider": {
            "name": status.provider_name if status else "None",
            "type": "SimulationProvider" if is_simulation else "TwelveDataProvider",
            "is_simulation": is_simulation,
            "is_production": is_production,
            "data_source": "SIMULATED (NOT REAL)" if is_simulation else "TwelveData API",
        },
        "data_quality": {
            "bid_ask_type": "CALCULATED (spread inventato)" if not is_simulation else "SIMULATED",
            "bid_ask_real": False,
            "explanation": "TwelveData fornisce solo mid-price. Bid/Ask sono calcolati con spread fisso (EURUSD: 0.8 pips, XAUUSD: 25 pips)"
        },
        "assets": {}
    }
    
    # Fetch quotes for all assets
    for asset in [Asset.EURUSD, Asset.XAUUSD]:
        try:
            start_time = datetime.utcnow()
            quote = await provider.get_live_quote(asset) if provider else None
            fetch_duration = (datetime.utcnow() - start_time).total_seconds()
            
            if quote:
                age_seconds = (datetime.utcnow() - quote.timestamp).total_seconds()
                result["assets"][asset.value] = {
                    "bid": quote.bid,
                    "ask": quote.ask,
                    "mid": quote.mid_price,
                    "spread_pips": quote.spread_pips,
                    "timestamp_provider": quote.timestamp.isoformat(),
                    "timestamp_server": datetime.utcnow().isoformat(),
                    "age_seconds": round(age_seconds, 2),
                    "is_fresh": age_seconds < 15,
                    "is_stale": age_seconds > 30,
                    "source_type": "simulation" if is_simulation else "price_endpoint_calculated_spread",
                    "fetch_duration_ms": round(fetch_duration * 1000, 1)
                }
            else:
                result["assets"][asset.value] = {
                    "error": "Failed to fetch quote",
                    "fetch_duration_ms": round(fetch_duration * 1000, 1)
                }
        except Exception as e:
            result["assets"][asset.value] = {
                "error": str(e)
            }
    
    # Add warnings
    result["warnings"] = []
    if is_simulation:
        result["warnings"].append("🚨 SIMULATION MODE ACTIVE - Prezzi NON reali!")
    if not is_production:
        result["warnings"].append("⚠️ Non connesso a TwelveData - verificare API key")
    result["warnings"].append("ℹ️ Bid/Ask sono CALCOLATI, non forniti dal provider")
    
    return result


@api_router.post("/debug/reinitialize-provider")
async def reinitialize_provider():
    """
    DEBUG: Force re-initialization of market data provider
    
    Use this if provider fell back to simulation mode incorrectly.
    """
    try:
        logger.info("🔄 Manual provider re-initialization requested...")
        
        # Get current state
        old_status = provider_manager.get_status()
        old_mode = "simulation" if provider_manager.is_simulation_mode() else "production"
        
        # Re-initialize
        success = await provider_manager.initialize()
        
        # Get new state
        new_status = provider_manager.get_status()
        new_mode = "simulation" if provider_manager.is_simulation_mode() else "production"
        
        return {
            "success": success,
            "before": {
                "mode": old_mode,
                "provider": old_status.provider_name if old_status else "None"
            },
            "after": {
                "mode": new_mode,
                "provider": new_status.provider_name if new_status else "None"
            },
            "message": f"Provider changed from {old_mode} to {new_mode}"
        }
    except Exception as e:
        logger.error(f"❌ Provider re-initialization error: {e}")
        return {
            "success": False,
            "error": str(e)
        }


@api_router.get("/debug/snapshot-service")
async def debug_snapshot_service():
    """
    DEBUG: Check signal_snapshot_service internal state
    """
    from services.signal_snapshot_service import signal_snapshot_service
    
    return {
        "initialized": signal_snapshot_service._loaded,
        "snapshots_count": len(signal_snapshot_service.snapshots),
        "snapshots_by_id_count": len(signal_snapshot_service.snapshots_by_id),
        "snapshots_file": str(signal_snapshot_service.snapshots_file),
        "max_snapshots": signal_snapshot_service.max_snapshots,
        "recent_snapshots": [
            {
                "id": s.signal_id,
                "status": s.status,
                "symbol": s.symbol,
                "timestamp": s.timestamp
            }
            for s in signal_snapshot_service.snapshots[-5:]
        ] if signal_snapshot_service.snapshots else []
    }


# ==================== DEVICE REGISTRATION ====================

@api_router.post("/register-device")
async def register_device(request: RegisterDeviceRequest):
    """
    Register a device for push notifications
    
    This endpoint uses resilient storage that works with:
    - MongoDB (primary, when available)
    - File-based storage (fallback, always available)
    
    VALIDATION:
    - Rejects placeholder/test tokens
    - Validates Expo push token format
    - Logs full registration pipeline
    """
    # ===== PIPELINE: LOG INCOMING REQUEST =====
    logger.info("📱 [DEVICE REG] Incoming registration request")
    logger.info(f"   Platform: {request.platform}")
    logger.info(f"   Device ID: {request.device_id[:30] if request.device_id else 'None'}...")
    logger.info(f"   Token: {request.push_token[:50] if request.push_token else 'None'}...")
    
    # ===== PIPELINE: VALIDATE REQUIRED FIELDS =====
    if not request.push_token:
        logger.error("❌ [DEVICE REG] REJECTED: Missing push_token")
        raise HTTPException(status_code=400, detail="push_token is required")
    
    if not request.device_id:
        logger.error("❌ [DEVICE REG] REJECTED: Missing device_id")
        raise HTTPException(status_code=400, detail="device_id is required")
    
    if not request.platform or request.platform not in ['ios', 'android', 'web']:
        logger.error(f"❌ [DEVICE REG] REJECTED: Invalid platform: {request.platform}")
        raise HTTPException(status_code=400, detail="platform must be 'ios', 'android', or 'web'")
    
    # ===== PIPELINE: REJECT TEST/PLACEHOLDER TOKENS =====
    token_upper = request.push_token.upper()
    is_test_token = any([
        'TEST' in token_upper,
        'PLACEHOLDER' in token_upper,
        'REAL_TOKEN' in token_upper,
        'FAKE' in token_upper,
        'DEMO' in token_upper,
        request.push_token == 'ExponentPushToken[REAL_TOKEN_TEST]',
        len(request.push_token) < 30
    ])
    
    if is_test_token:
        logger.error("❌ [DEVICE REG] REJECTED: Test/placeholder token detected")
        logger.error(f"   Token: {request.push_token}")
        raise HTTPException(
            status_code=400, 
            detail="Test/placeholder tokens are not accepted. Please use a real device token."
        )
    
    # ===== PIPELINE: VALIDATE TOKEN FORMAT =====
    is_expo_token = request.push_token.startswith('ExponentPushToken[') or request.push_token.startswith('ExpoPushToken[')
    is_fcm_token = len(request.push_token) > 100 and ':' in request.push_token  # FCM tokens are typically very long
    
    if not is_expo_token and not is_fcm_token:
        logger.warning(f"⚠️ [DEVICE REG] Unusual token format (not Expo or FCM): {request.push_token[:50]}...")
        # Continue anyway - might be a valid native token
    
    token_type = "expo" if is_expo_token else "fcm_native" if is_fcm_token else "unknown"
    logger.info(f"   Token type: {token_type}")
    
    # ===== PIPELINE: REGISTER DEVICE =====
    try:
        result = await device_storage.register_device(
            device_id=request.device_id,
            push_token=request.push_token,
            platform=request.platform,
            device_name=request.device_name
        )
        
        logger.info(f"✅ [DEVICE REG] SUCCESS: {result['status']}")
        logger.info(f"   Device ID: {result['device_id'][:30]}...")
        logger.info(f"   Storage: {result.get('storage_backend', 'file')}")
        
        return {
            "status": result['status'],
            "device_id": result['device_id'],
            "token_type": token_type,
            "message": "Device registered successfully for push notifications"
        }
        
    except Exception as e:
        logger.error(f"❌ [DEVICE REG] ERROR: {str(e)}")
        import traceback
        logger.error(f"   Stack trace: {traceback.format_exc()}")
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
    """
    List all registered devices with validation status.
    
    Shows:
    - device_id (masked)
    - platform
    - token (masked)
    - is_valid (true if real token)
    - is_placeholder (true if test token)
    - is_active
    - last_seen
    """
    try:
        devices = await device_storage.get_active_devices()
        
        device_list = []
        valid_count = 0
        placeholder_count = 0
        
        for d in devices:
            # Check if token is test/placeholder
            token_upper = (d.push_token or '').upper()
            is_placeholder = any([
                'TEST' in token_upper,
                'PLACEHOLDER' in token_upper,
                'REAL_TOKEN' in token_upper,
                'FAKE' in token_upper,
                'DEMO' in token_upper,
                d.push_token == 'ExponentPushToken[REAL_TOKEN_TEST]',
                len(d.push_token or '') < 30
            ])
            
            is_valid = not is_placeholder and len(d.push_token or '') > 30
            
            if is_valid:
                valid_count += 1
            if is_placeholder:
                placeholder_count += 1
            
            device_list.append({
                "device_id": d.device_id[:25] + "..." if len(d.device_id) > 25 else d.device_id,
                "platform": d.platform,
                "token_preview": d.push_token[:40] + "..." if d.push_token else None,
                "is_valid": is_valid,
                "is_placeholder": is_placeholder,
                "is_active": d.is_active,
                "created_at": d.created_at,
                "updated_at": d.updated_at
            })
        
        return {
            "count": len(devices),
            "valid_devices": valid_count,
            "placeholder_devices": placeholder_count,
            "can_receive_notifications": valid_count > 0,
            "devices": device_list
        }
    except Exception as e:
        logger.error(f"❌ Error listing devices: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Error: {str(e)}")


@api_router.get("/push/fcm-status")
async def get_fcm_status():
    """Check FCM v1 service status and credentials - FULL DEBUG"""
    import os
    from services.fcm_push_service import fcm_push_service
    
    # Get all env vars that might be related
    all_env = dict(os.environ)
    firebase_vars = {k: f"{v[:20]}..." if len(v) > 20 else v for k, v in all_env.items() if "FIREBASE" in k.upper()}
    
    # Check specific variable
    env_base64 = os.environ.get("FIREBASE_SERVICE_ACCOUNT_BASE64")
    env_json = os.environ.get("FIREBASE_SERVICE_ACCOUNT_JSON")
    
    # Try to initialize
    init_result = await fcm_push_service.initialize()
    
    # List all env var names (for debugging)
    all_var_names = sorted([k for k in all_env.keys()])
    
    return {
        "fcm_status": fcm_push_service.get_stats(),
        "initialized": fcm_push_service._initialized,
        "project_id": fcm_push_service.project_id,
        "debug": {
            "FIREBASE_SERVICE_ACCOUNT_BASE64": {
                "exists": env_base64 is not None,
                "length": len(env_base64) if env_base64 else 0,
                "first_20_chars": env_base64[:20] + "..." if env_base64 and len(env_base64) > 20 else env_base64
            },
            "FIREBASE_SERVICE_ACCOUNT_JSON": {
                "exists": env_json is not None,
                "length": len(env_json) if env_json else 0
            },
            "all_firebase_vars": firebase_vars,
            "total_env_vars": len(all_var_names),
            "env_var_names_containing_fire": [k for k in all_var_names if "FIRE" in k.upper()],
            "env_var_names_containing_fcm": [k for k in all_var_names if "FCM" in k.upper()],
            "env_var_names_containing_service": [k for k in all_var_names if "SERVICE" in k.upper()]
        },
        "init_result": init_result
    }


@api_router.post("/push/test-debug")
async def send_test_notification_debug():
    """Send test push with FCM v1 API (full debug info)"""
    from services.fcm_push_service import fcm_push_service
    
    try:
        # Initialize FCM service
        if not fcm_push_service._initialized:
            await fcm_push_service.initialize()
        
        devices = await device_storage.get_active_devices()
        if not devices:
            return {"status": "error", "message": "No devices registered"}
        
        results = []
        for device in devices:
            token = device.push_token
            logger.info(f"📬 FCM v1: Testing push to {token[:30]}...")
            
            result = await fcm_push_service.send_notification(
                token=token,
                title="🔔 PropSignal Test",
                body="Test notification - FCM v1 funziona!",
                data={"type": "test", "timestamp": datetime.utcnow().isoformat()},
                channel_id="trading-signals"
            )
            
            results.append({
                "device_id": device.device_id,
                "token_length": len(token),
                "success": result.success,
                "message_id": result.message_id,
                "error": result.error,
                "error_code": result.error_code
            })
        
        successful = sum(1 for r in results if r["success"])
        failed = len(results) - successful
        
        return {
            "status": "completed",
            "service": "FCM v1",
            "total": len(results),
            "successful": successful,
            "failed": failed,
            "results": results
        }
    except Exception as e:
        logger.error(f"❌ FCM v1 test error: {str(e)}")
        import traceback
        return {"status": "error", "message": str(e), "traceback": traceback.format_exc()}


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
    Get status of Signal Generator v3.2 (DATA-DRIVEN OPTIMIZATION)
    
    This is the PRIMARY signal generator with DATA-DRIVEN filters:
    - Min confidence: 75% (raised from 60% based on performance data)
    - Min MTF: 80 (only strong alignment)
    - Assets: EURUSD only (XAUUSD disabled due to -12R performance)
    - Sessions: London only (overlap and NY disabled)
    - Setups: HTF Continuation and Momentum Breakout only
    - Trade Management: Partial@0.5R, BE@1R, Trail@1R
    """
    if not signal_generator_instance:
        return {"error": "Signal Generator v3 not initialized"}
    
    stats = signal_generator_instance.get_stats()
    
    # Extract data-driven filters
    data_driven = stats.get("data_driven_filters", {})
    
    return {
        "version": stats["version"],
        "mode": stats["mode"],
        "is_running": stats["is_running"],
        "uptime_seconds": stats["uptime_seconds"],
        
        # v3.2 DATA-DRIVEN configuration
        "data_driven_filters": data_driven,
        "trade_management": stats.get("trade_management", {}),
        "classification": stats["classification"],
        
        "statistics": {
            "total_scans": stats["scan_count"],
            "signals_generated": stats["signal_count"],
            "notifications_sent": stats["notification_count"],
            "rejections": stats["rejection_count"],
            "invalid_tokens_removed": stats.get("invalid_tokens_removed", 0)
        },
        
        "rejection_reasons": stats.get("rejection_reasons", {}),
        "duplicate_window_minutes": stats["duplicate_window_minutes"],
        "recent_signals_count": stats["recent_signals"],
        
        # ========== BUFFER ZONE MONITORING (v3.3) ==========
        "buffer_zone_metrics": stats.get("buffer_zone_metrics", {}),
        
        # ========== BUFFER ZONE FAILURE DIAGNOSTICS (v5.1) ==========
        "buffer_fail_diagnostics": stats.get("buffer_fail_diagnostics", {}),
        
        # Prop firm configuration and risk status
        "prop_config": stats.get("prop_config", {}),
        "daily_risk_status": stats.get("daily_risk_status", {}),
        "optimization_applied": stats.get("optimization_applied", "")
    }


@api_router.post("/scanner/v3/initialize")
async def initialize_scanner_v3():
    """
    Manually initialize and start Signal Generator v3.
    
    Use this if the scanner failed to initialize during startup.
    This will:
    1. Initialize the signal snapshot service
    2. Initialize the signal generator if not already done
    3. Start the scanner if not running
    4. Initialize the outcome tracker
    """
    global signal_generator_instance, tracker
    
    try:
        # Initialize signal snapshot service FIRST
        from services.signal_snapshot_service import signal_snapshot_service
        await signal_snapshot_service.initialize()
        logger.info("✅ Signal Snapshot Service initialized manually")
        
        # Check if already running
        if signal_generator_instance and signal_generator_instance.is_running:
            return {
                "status": "already_running",
                "message": "Signal Generator v3 is already running",
                "version": signal_generator_instance.get_stats().get("version", "unknown")
            }
        
        # Initialize if not done
        if not signal_generator_instance:
            logger.info("🔄 Manual initialization of Signal Generator v3...")
            signal_generator_instance = await init_signal_generator(db)
            logger.info("✅ Signal Generator v3 initialized manually")
        
        # Start if not running
        if not signal_generator_instance.is_running:
            await signal_generator_instance.start()
            logger.info("✅ Signal Generator v3 started manually")
        
        # Initialize and start tracker V2
        from services.signal_outcome_tracker_v2 import signal_outcome_tracker
        if not signal_outcome_tracker.is_running:
            await signal_outcome_tracker.start()
            logger.info("✅ Outcome Tracker V2 started manually")
        
        return {
            "status": "success",
            "message": "Signal Generator v3 initialized and started",
            "scanner_running": signal_generator_instance.is_running,
            "tracker_running": signal_outcome_tracker.is_running,
            "version": signal_generator_instance.get_stats().get("version", "unknown")
        }
        
    except Exception as e:
        logger.error(f"❌ Manual initialization error: {e}")
        return {
            "status": "error",
            "message": str(e)
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
    
    return {
        "status": "simulation_triggered",
        "note": "Check /audit/missed-opportunities for results"
    }


# ==================== CANDIDATE AUDIT ENDPOINTS ====================

@api_router.get("/audit/candidates")
async def get_candidate_audit():
    """
    Get latest candidate trades with FULL SCORE BREAKDOWN.
    
    Returns all candidates that reached pre-filter stage,
    both accepted and rejected, with complete scoring details.
    """
    from services.candidate_audit_service import candidate_audit_service
    
    return {
        "report_type": "all_candidates",
        "count": len(candidate_audit_service.candidates),
        "candidates": candidate_audit_service.get_latest_candidates(50),
        "note": "AUDIT ONLY - Full score breakdown for threshold analysis"
    }


@api_router.get("/audit/rejections")
async def get_rejection_audit():
    """
    Get latest REJECTED trades with full score breakdown.
    
    Includes:
    - Rejection reason
    - Full score breakdown at rejection
    - Filter flags showing which filter blocked
    - Simulated outcome (if available)
    """
    from services.candidate_audit_service import candidate_audit_service
    
    return {
        "report_type": "rejections_only",
        "rejections": candidate_audit_service.get_latest_rejections(50),
        "analysis": candidate_audit_service.get_rejection_analysis(),
        "note": "AUDIT ONLY - Rejected trade analysis"
    }


@api_router.get("/audit/score-breakdown")
async def get_score_breakdown_analysis():
    """
    Get score component analysis - which components correlate with wins/losses.
    
    Shows for each score component:
    - Average value in winning trades
    - Average value in losing trades
    - Difference (positive = correlates with wins)
    """
    from services.candidate_audit_service import candidate_audit_service
    
    return {
        "report_type": "score_component_analysis",
        "component_analysis": candidate_audit_service.get_component_analysis(),
        "note": "AUDIT ONLY - Higher difference = stronger correlation with wins"
    }


@api_router.get("/audit/threshold-performance")
async def get_threshold_performance():
    """
    COMPREHENSIVE threshold performance report.
    
    Includes:
    - Score bucket analysis (winrate/R by score range)
    - Component analysis (which scores predict wins)
    - Rejection analysis (which rejects would have won)
    - Filter effectiveness (which filters are working)
    """
    from services.candidate_audit_service import candidate_audit_service
    
    return candidate_audit_service.get_threshold_performance_report()


@api_router.get("/audit/threshold-report")
async def get_threshold_analysis_report():
    """
    COMPLETE THRESHOLD ANALYSIS REPORT for data-driven optimization.
    
    Returns structured JSON with:
    
    1. BUCKETS: Trades grouped by total_score (<70, 70-74, 75-79, 80-84, 85+)
       - total candidates, accepted, rejected, acceptance rate
       - TP hits, SL hits, winrate, total R, expectancy
       - avg MFE/MAE
       
    2. REJECTIONS: Analysis by rejection reason
       - count, frequency
       - hypothetical performance (if trades were taken)
       - close-to-threshold analysis
       - verdict (OVER_FILTERING / WORKING_WELL)
       
    3. COMPONENTS: Score component importance ranking
       - avg in wins vs losses
       - delta (higher = stronger edge indicator)
       - correlation strength
       
    4. SUMMARY: Executive insights
       - best/worst score ranges
       - potentially over-filtering reasons
       - strongest edge components
       - actionable recommendations
    
    ANALYTICS ONLY - does NOT modify strategy or thresholds.
    """
    from services.candidate_audit_service import candidate_audit_service
    
    return candidate_audit_service.get_threshold_analysis_report()


@api_router.get("/audit/score-buckets")
async def get_score_bucket_analysis():
    """
    Analyze trades by TOTAL SCORE buckets.
    
    Buckets: <70, 70-74, 75-79, 80-84, 85+
    
    For each bucket shows:
    - Accepted/rejected count
    - Wins/losses
    - Winrate
    - Total R
    - Expectancy
    """
    from services.candidate_audit_service import candidate_audit_service
    
    return {
        "report_type": "score_bucket_analysis",
        "buckets": candidate_audit_service.get_score_bucket_analysis(),
        "note": "AUDIT ONLY - Score bucket performance"
    }


@api_router.get("/audit/mtf-buckets")
async def get_mtf_bucket_analysis():
    """
    Analyze trades by MTF SCORE buckets.
    
    Buckets: <60, 60-69, 70-79, 80-89, 90+
    """
    from services.candidate_audit_service import candidate_audit_service
    
    return {
        "report_type": "mtf_bucket_analysis",
        "buckets": candidate_audit_service.get_mtf_bucket_analysis(),
        "note": "AUDIT ONLY - MTF score bucket performance"
    }


@api_router.get("/audit/pullback-buckets")
async def get_pullback_bucket_analysis():
    """
    Analyze trades by PULLBACK SCORE buckets.
    
    Buckets: <50, 50-69, 70-84, 85-99, 100
    """
    from services.candidate_audit_service import candidate_audit_service
    
    return {
        "report_type": "pullback_bucket_analysis",
        "buckets": candidate_audit_service.get_pullback_bucket_analysis(),
        "note": "AUDIT ONLY - Pullback score bucket performance"
    }


@api_router.get("/audit/filter-effectiveness")
async def get_filter_effectiveness():
    """
    Analyze which filters are correctly blocking losing trades.
    
    For each filter shows:
    - Total blocked
    - Correctly blocked (would have lost)
    - Incorrectly blocked (would have won)
    - Effectiveness percentage
    - Verdict (effective/needs_review/potentially_harmful)
    """
    from services.candidate_audit_service import candidate_audit_service
    
    return {
        "report_type": "filter_effectiveness",
        "filters": candidate_audit_service.get_filter_effectiveness(),
        "note": "AUDIT ONLY - Filter effectiveness analysis"
    }
    
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
        raise HTTPException(status_code=400, detail="Invalid asset. Use EURUSD or XAUUSD")
    
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
        raise HTTPException(status_code=400, detail="Invalid asset. Use EURUSD or XAUUSD")
    
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
    """Send a test push notification using hybrid FCM/Expo service"""
    from services.fcm_push_service import fcm_push_service
    
    logger.info(f"📬 Test push notification requested for device: {device_id or 'all devices'}")
    
    try:
        # Initialize FCM service if needed
        if not fcm_push_service._initialized:
            init_ok = await fcm_push_service.initialize()
            if not init_ok:
                logger.warning("⚠️ FCM service not initialized, will use Expo API for Expo tokens")
        
        if device_id:
            device = await device_storage.get_device(device_id)
            if not device or not device.is_active:
                logger.warning(f"⚠️ Device not found or inactive: {device_id[:20]}...")
                raise HTTPException(status_code=404, detail="Device not found")
            tokens = [device.push_token]
            logger.info("📬 Sending test to 1 device")
        else:
            tokens = await device_storage.get_active_tokens()
            logger.info(f"📬 Sending test to {len(tokens)} devices")
        
        if not tokens:
            logger.warning("⚠️ No active devices to send test to")
            return {"status": "no_devices", "message": "No active devices to send to"}
        
        # Use hybrid push service
        results = await fcm_push_service.send_to_all_devices(
            tokens=tokens,
            title="🧪 Test PropSignal",
            body="Notifica di test - sistema push funzionante!",
            data={"type": "test", "timestamp": datetime.utcnow().isoformat()}
        )
        
        successful = sum(1 for r in results if r.success)
        failed = len(results) - successful
        
        logger.info(f"📬 Test push results: {successful} successful, {failed} failed")
        
        # Return detailed results
        return {
            "status": "sent",
            "total": len(results),
            "successful": successful,
            "failed": failed,
            "details": [
                {
                    "token_type": "expo" if t.startswith("ExponentPushToken") else "fcm",
                    "success": r.success,
                    "message_id": r.message_id,
                    "error": r.error
                }
                for t, r in zip(tokens, results)
            ]
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


@api_router.post("/push/real-pipeline-test")
async def send_real_pipeline_test():
    """
    Send a notification through the EXACT SAME pipeline as real signals.
    Uses fcm_push_service.send_to_all_devices() - same as production.
    NOT a test endpoint - uses real production code path.
    """
    from services.device_storage_service import device_storage
    from services.fcm_push_service import fcm_push_service
    from datetime import datetime
    
    pipeline_log = []
    
    def log_stage(stage: str, status: str, details: str = ""):
        entry = {"stage": stage, "status": status, "details": details, "timestamp": datetime.utcnow().isoformat()}
        pipeline_log.append(entry)
        logger.info(f"📋 [PIPELINE-TEST] {stage}: {status} - {details}")
    
    try:
        # ===== STAGE 1: SIGNAL GENERATION =====
        signal_id = f"PIPELINE_TEST_{datetime.utcnow().strftime('%Y%m%d_%H%M%S')}"
        
        log_stage("SIGNAL_GENERATED", "✅ SUCCESS", f"ID: {signal_id}")
        
        # ===== STAGE 2: GET DEVICES =====
        tokens = await device_storage.get_active_tokens()
        device_count = len(tokens)
        
        if device_count == 0:
            log_stage("DEVICES_FOUND", "❌ FAILED", "No active devices registered")
            return {
                "status": "no_devices",
                "signal_id": signal_id,
                "pipeline_log": pipeline_log,
                "message": "No devices registered to receive notification"
            }
        
        log_stage("DEVICES_FOUND", "✅ SUCCESS", f"{device_count} device(s) found")
        
        # ===== STAGE 3: FCM INITIALIZATION =====
        if not fcm_push_service._initialized:
            init_ok = await fcm_push_service.initialize()
            if not init_ok:
                log_stage("FCM_INIT", "⚠️ WARNING", "FCM not initialized, using Expo API")
            else:
                log_stage("FCM_INIT", "✅ SUCCESS", "FCM service ready")
        else:
            log_stage("FCM_INIT", "✅ SUCCESS", "FCM already initialized")
        
        # ===== STAGE 4: SEND NOTIFICATION (REAL PIPELINE) =====
        title = "🔔 REAL PIPELINE TEST - EURUSD BUY"
        body = f"Entry: 1.15250 | SL: 1.15150 | TP: 1.15383 | Score: 85% | ID: {signal_id[-8:]}"
        data = {
            "type": "trading_signal",
            "signal_id": signal_id,
            "asset": "EURUSD",
            "direction": "BUY",
            "is_pipeline_test": "true"
        }
        
        log_stage("PUSH_ATTEMPTED", "⏳ SENDING", f"To {device_count} device(s)")
        
        results = await fcm_push_service.send_to_all_devices(
            tokens=tokens,
            title=title,
            body=body,
            data=data
        )
        
        # ===== STAGE 5: PROCESS RESULTS =====
        successful = 0
        failed = 0
        result_details = []
        
        for i, result in enumerate(results):
            token_preview = tokens[i][:30] + "..." if len(tokens[i]) > 30 else tokens[i]
            token_type = "expo" if tokens[i].startswith("ExponentPushToken") else "fcm"
            
            if result.success:
                successful += 1
                result_details.append({
                    "device": i + 1,
                    "token_type": token_type,
                    "status": "✅ DELIVERED",
                    "message_id": result.message_id,
                    "error": None
                })
                log_stage(f"DEVICE_{i+1}", "✅ DELIVERED", f"Type: {token_type}, MsgID: {result.message_id}")
            else:
                failed += 1
                error_str = str(result.error) if result.error else "Unknown error"
                result_details.append({
                    "device": i + 1,
                    "token_type": token_type,
                    "status": "❌ FAILED",
                    "message_id": None,
                    "error": error_str
                })
                log_stage(f"DEVICE_{i+1}", "❌ FAILED", f"Type: {token_type}, Error: {error_str}")
        
        # ===== FINAL STATUS =====
        if successful == device_count:
            final_status = "✅ ALL DELIVERED"
            log_stage("FINAL_STATUS", "✅ SUCCESS", f"All {successful}/{device_count} delivered")
        elif successful > 0:
            final_status = "⚠️ PARTIAL DELIVERY"
            log_stage("FINAL_STATUS", "⚠️ PARTIAL", f"{successful}/{device_count} delivered")
        else:
            final_status = "❌ ALL FAILED"
            log_stage("FINAL_STATUS", "❌ FAILED", f"0/{device_count} delivered")
        
        return {
            "status": "sent",
            "signal_id": signal_id,
            "final_status": final_status,
            "devices_found": device_count,
            "successful": successful,
            "failed": failed,
            "result_details": result_details,
            "pipeline_log": pipeline_log,
            "notification": {
                "title": title,
                "body": body
            }
        }
        
    except Exception as e:
        logger.error(f"❌ Pipeline test error: {e}")
        import traceback
        logger.error(traceback.format_exc())
        log_stage("ERROR", "❌ EXCEPTION", str(e))
        return {
            "status": "error",
            "error": str(e),
            "pipeline_log": pipeline_log
        }


# ==================== OUTCOME TRACKER ====================

@api_router.get("/tracker/status")
async def get_tracker_status():
    """Get signal outcome tracker status"""
    from services.signal_outcome_tracker_v2 import signal_outcome_tracker
    
    return {
        "is_running": signal_outcome_tracker.is_running,
        "checks_performed": signal_outcome_tracker.stats.get("total_checks", 0),
        "wins": signal_outcome_tracker.stats.get("wins", 0),
        "losses": signal_outcome_tracker.stats.get("losses", 0),
        "expired": signal_outcome_tracker.stats.get("expired", 0),
        "active_signals": len(signal_outcome_tracker.active_signals),
        "check_interval_seconds": signal_outcome_tracker.PRICE_CHECK_INTERVAL,
        "max_signal_age_hours": signal_outcome_tracker.EXPIRY_HOURS,
        "stats": signal_outcome_tracker.stats
    }

@api_router.post("/tracker/start")
async def start_tracker():
    """Start the signal outcome tracker"""
    from services.signal_outcome_tracker_v2 import signal_outcome_tracker
    
    if signal_outcome_tracker.is_running:
        return {"status": "already_running"}
    
    await signal_outcome_tracker.start()
    return {"status": "started"}

@api_router.post("/tracker/stop")
async def stop_tracker():
    """Stop the signal outcome tracker"""
    from services.signal_outcome_tracker_v2 import signal_outcome_tracker
    
    if not signal_outcome_tracker.is_running:
        return {"status": "already_stopped"}
    
    await signal_outcome_tracker.stop()
    return {"status": "stopped"}


# ==================== TEST ENDPOINTS ====================

@api_router.post("/test/create-fake-trade")
async def create_fake_trade():
    """
    TEST: Create a fake trade
    """
    from datetime import datetime
    from services.signal_outcome_tracker_v2 import signal_outcome_tracker, TrackedSignal
    
    # Get current price
    provider = provider_manager.get_provider()
    quote = await provider.get_live_quote(Asset.EURUSD) if provider else None
    
    if not quote:
        return {"error": "Cannot get current price"}
    
    current_price = quote.mid_price
    
    # Create SELL signal
    entry_price = current_price + 0.0015
    stop_loss = entry_price + 0.0025
    take_profit = current_price - 0.0005  # TP below current (already in profit)
    
    signal_id = f"TEST_SELL_{datetime.utcnow().strftime('%Y%m%d_%H%M%S')}"
    timestamp = datetime.utcnow().isoformat()
    
    # Add to tracker
    tracked_signal = TrackedSignal(
        signal_id=signal_id,
        asset="EURUSD",
        direction="SELL",
        entry_price=entry_price,
        stop_loss=stop_loss,
        take_profit_1=take_profit,
        take_profit_2=take_profit - 0.0010,
        timestamp=timestamp,
        confidence_score=75.0,
        confidence_level="HIGH",
        setup_type="Test Signal",
        session="Test",
        invalidation="Test SL",
        risk_reward=1.5
    )
    
    signal_outcome_tracker.active_signals[signal_id] = tracked_signal
    await signal_outcome_tracker._save_data()
    logger.info(f"📝 TEST: Created trade {signal_id}")
    
    return {
        "signal_id": signal_id,
        "entry": round(entry_price, 5),
        "current": round(current_price, 5),
        "tp": round(take_profit, 5),
        "sl": round(stop_loss, 5),
        "message": f"Trade created. Call POST /api/test/close-fake-trade/{signal_id} to close it."
    }


@api_router.post("/test/close-fake-trade/{signal_id}")
async def close_fake_trade(signal_id: str):
    """
    TEST: Close the fake trade as TP hit
    """
    from services.signal_outcome_tracker_v2 import signal_outcome_tracker
    
    if signal_id not in signal_outcome_tracker.active_signals:
        return {"error": f"Signal {signal_id} not found in active signals. Available: {list(signal_outcome_tracker.active_signals.keys())[:5]}"}
    
    # Close as TP hit
    await signal_outcome_tracker._complete_signal(signal_id, "tp_hit")
    logger.info(f"📝 TEST: Closed {signal_id} in tracker as tp_hit")
    
    return {
        "step": "2_closed_tp_hit",
        "signal_id": signal_id,
        "status": "tp_hit",
        "message": "Trade closed as TP HIT! Check /api/tracker/status for wins count."
    }


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


# ==================== REJECTED TRADE AUDIT ENDPOINTS ====================

@api_router.get("/audit/rejected/stats")
async def get_rejected_trade_stats():
    """
    Get overall statistics for rejected trades.
    
    Shows:
    - Total rejected trades tracked
    - Simulations completed/pending
    - Simulated win rate and expectancy
    - Average MFE/MAE for rejected trades
    """
    return rejected_trade_tracker.get_overall_stats()


@api_router.get("/audit/rejected/by-reason")
async def get_rejected_stats_by_reason():
    """
    Get rejected trade statistics broken down by rejection reason.
    
    For each rejection reason shows:
    - Count of blocked trades
    - Simulated outcomes (TP hit, SL hit, expired)
    - Win rate and expectancy if those trades had been taken
    """
    return rejected_trade_tracker.get_stats_by_reason()


@api_router.get("/audit/rejected/filter-quality")
async def get_filter_quality_report():
    """
    Filter quality analysis report.
    
    For each active filter shows:
    - How many trades it blocked
    - How many would have been winners
    - How many would have been losers
    - Quality rating (good, too_strict, neutral)
    - Assessment of filter effectiveness
    
    Use this to identify which filters are correctly blocking bad trades
    vs which filters are being too restrictive and blocking good trades.
    """
    return rejected_trade_tracker.get_filter_quality_report()


@api_router.get("/audit/rejected/samples")
async def get_rejected_trade_samples(n: int = 5):
    """
    Get n sample rejected trades with full simulation details.
    
    Includes:
    - Entry/SL/TP levels
    - Rejection reason
    - Simulated outcome
    - MFE/MAE and peak R
    - Time to outcome
    
    Use this to validate the simulator is working correctly.
    """
    samples = rejected_trade_tracker.get_sample_rejections(n)
    return {
        "samples": samples,
        "count": len(samples),
        "note": "These are the most recently completed simulations"
    }


@api_router.get("/audit/rejected/pending")
async def get_pending_rejections():
    """Get list of pending simulations"""
    pending = list(rejected_trade_tracker.pending_candidates.values())
    return {
        "count": len(pending),
        "oldest": min([p.timestamp for p in pending]) if pending else None,
        "newest": max([p.timestamp for p in pending]) if pending else None,
        "candidates": [
            {
                "candidate_id": p.candidate_id,
                "asset": p.asset,
                "direction": p.direction,
                "rejection_reason": p.rejection_reason,
                "timestamp": p.timestamp,
                "simulation_status": p.simulation_status
            }
            for p in pending[:20]  # Show first 20
        ]
    }


@api_router.get("/audit/rejected/summary")
async def get_rejected_trade_summary():
    """
    Complete summary of rejected trade analysis.
    
    Combines:
    - Overall stats
    - Stats by reason
    - Filter quality assessment
    - Sample validations
    """
    overall = rejected_trade_tracker.get_overall_stats()
    by_reason = rejected_trade_tracker.get_stats_by_reason()
    filter_quality = rejected_trade_tracker.get_filter_quality_report()
    samples = rejected_trade_tracker.get_sample_rejections(5)
    
    # Calculate key insights
    insights = []
    
    # Check if any filters are too strict
    for filter_name, data in filter_quality.get("filters", {}).items():
        if data.get("quality_rating") == "too_strict":
            insights.append({
                "type": "warning",
                "message": f"Filter '{filter_name}' is blocking profitable trades (expectancy: {data['simulated_expectancy']:+.2f}R)",
                "recommendation": "Consider relaxing this filter"
            })
        elif data.get("quality_rating") == "good":
            insights.append({
                "type": "success",
                "message": f"Filter '{filter_name}' is correctly blocking losing trades",
                "impact": f"Saved {abs(data['simulated_expectancy']):+.2f}R per blocked trade"
            })
    
    return {
        "generated_at": datetime.utcnow().isoformat(),
        "overall_stats": overall,
        "stats_by_reason": by_reason,
        "filter_quality": filter_quality,
        "sample_validations": samples,
        "insights": insights,
        "conclusion": {
            "rejected_winrate": overall.get("winrate_pct", 0),
            "rejected_expectancy": overall.get("expectancy_r", 0),
            "interpretation": (
                "Rejected trades would have LOST money - filters are working well"
                if overall.get("expectancy_r", 0) < 0
                else "Rejected trades would have been PROFITABLE - filters may be too strict"
                if overall.get("expectancy_r", 0) > 0.1
                else "Rejected trades have neutral expectancy - filters are appropriately calibrated"
            )
        }
    }


@api_router.post("/audit/rejected/save")
async def force_save_rejected_data():
    """Force save rejected trade data to disk"""
    await rejected_trade_tracker._save_data()
    return {"status": "saved", "path": rejected_trade_tracker.STORAGE_PATH}


@api_router.post("/audit/rejected/simulate-batch")
async def trigger_simulation_batch():
    """Manually trigger a batch simulation of rejected trades"""
    await rejected_trade_tracker._process_simulation_batch()
    return {
        "status": "batch_processed",
        "pending": len(rejected_trade_tracker.pending_candidates),
        "completed": len(rejected_trade_tracker.completed_simulations)
    }


@api_router.get("/audit/signal-delivery")
async def get_signal_delivery_audit():
    """
    Full signal delivery pipeline audit.
    
    Shows:
    - Total signals generated
    - Notifications attempted
    - Successful deliveries
    - Failed deliveries
    - Failure reasons
    - Device token status
    """
    # Get signal stats
    stats = signal_generator_instance.get_stats() if signal_generator_instance else {}
    
    # Get device info
    devices = await device_storage.get_active_devices()
    active_devices = [d for d in devices if d.is_active]
    
    # Analyze tokens
    token_analysis = []
    for d in devices:
        token = d.push_token
        is_test = 'TEST' in token.upper() or 'REAL_TOKEN' in token
        is_expo = token.startswith('ExponentPushToken')
        
        token_analysis.append({
            "device_id": d.device_id,
            "platform": d.platform,
            "token_type": "expo" if is_expo else "fcm_native",
            "is_test_token": is_test,
            "is_valid": not is_test,
            "token_preview": token[:40] + "..."
        })
    
    # Get FCM status
    from services.fcm_push_service import fcm_push_service
    fcm_status = fcm_push_service.get_stats()
    
    # Calculate delivery rate
    signals_generated = stats.get("signal_count", 0)
    notifications_attempted = stats.get("notification_count", 0)
    
    # Check recent logs for delivery status
    valid_tokens = sum(1 for t in token_analysis if t["is_valid"])
    
    return {
        "generated_at": datetime.utcnow().isoformat(),
        "pipeline_summary": {
            "total_signals_generated": signals_generated,
            "notifications_attempted": notifications_attempted,
            "not_attempted": signals_generated - notifications_attempted,
            "estimated_successful_deliveries": 0 if valid_tokens == 0 else "unknown",
            "estimated_failed_deliveries": notifications_attempted if valid_tokens == 0 else "unknown"
        },
        "device_status": {
            "total_devices": len(devices),
            "active_devices": len(active_devices),
            "valid_tokens": valid_tokens,
            "test_tokens": len(devices) - valid_tokens
        },
        "token_analysis": token_analysis,
        "fcm_status": fcm_status,
        "delivery_issues": [
            {
                "issue": "No valid device tokens",
                "impact": "All notifications fail",
                "solution": "User needs to open the app and enable notifications to register a real token"
            }
        ] if valid_tokens == 0 else [],
        "pipeline_stages": {
            "1_generation": "Signal created in signal_generator_v3",
            "2_authorization": "Production control check",
            "3_fcm_init": "FCM service initialization",
            "4_token_fetch": "Get active device tokens",
            "5_send": "Send via FCM v1 / Expo API",
            "6_delivery": "Track success/failure per device"
        },
        "logging_enabled": True,
        "log_format": "[PIPELINE] {signal_id} - {STAGE}: {details}"
    }


@api_router.get("/audit/tracking-debug")
async def get_tracking_debug():
    """Debug endpoint to check tracking system status"""
    from services.candidate_audit_service import candidate_audit_service
    from services.signal_outcome_tracker_v2 import signal_outcome_tracker
    from services.rejected_trade_tracker import rejected_trade_tracker
    
    return {
        "candidate_audit": candidate_audit_service.get_tracking_debug(),
        "signal_tracker": {
            "is_running": signal_outcome_tracker.is_running,
            "active_signals": len(signal_outcome_tracker.active_signals),
            "completed_signals": len(signal_outcome_tracker.completed_signals),
            "tp_hits": signal_outcome_tracker.stats.get("tp_hits", 0),
            "sl_hits": signal_outcome_tracker.stats.get("sl_hits", 0)
        },
        "rejected_tracker": {
            "is_running": rejected_trade_tracker.is_running if hasattr(rejected_trade_tracker, 'is_running') else "unknown",
            "active_simulations": len(rejected_trade_tracker.active_simulations) if hasattr(rejected_trade_tracker, 'active_simulations') else 0,
            "completed_simulations": len(rejected_trade_tracker.completed_simulations) if hasattr(rejected_trade_tracker, 'completed_simulations') else 0,
            "stats": rejected_trade_tracker.stats if hasattr(rejected_trade_tracker, 'stats') else {}
        }
    }


# ==================== PATTERN ENGINE V1.0 ENDPOINTS ====================

@api_router.get("/pattern/status")
async def get_pattern_status():
    """Get Pattern Signal Generator status"""
    return pattern_signal_generator.get_status()


@api_router.post("/pattern/start")
async def start_pattern_engine(mode: str = "forward_test"):
    """
    Start the Pattern Signal Generator
    
    Modes:
    - forward_test: Track patterns without sending notifications (default)
    - live: Send real notifications
    """
    try:
        if mode == "live":
            pattern_signal_generator.set_mode(OperationMode.LIVE)
        else:
            pattern_signal_generator.set_mode(OperationMode.FORWARD_TEST)
        
        await pattern_signal_generator.start()
        
        return {
            "status": "success",
            "message": f"Pattern Engine started in {mode} mode",
            "mode": mode
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@api_router.post("/pattern/stop")
async def stop_pattern_engine():
    """Stop the Pattern Signal Generator"""
    await pattern_signal_generator.stop()
    return {"status": "success", "message": "Pattern Engine stopped"}


@api_router.post("/pattern/mode/{mode}")
async def set_pattern_mode(mode: str):
    """
    Change Pattern Engine mode
    
    - forward_test: No notifications, track only
    - live: Send real notifications
    """
    if mode == "live":
        pattern_signal_generator.enable_live_mode()
    elif mode == "forward_test":
        pattern_signal_generator.enable_forward_test()
    else:
        raise HTTPException(status_code=400, detail=f"Invalid mode: {mode}")
    
    return {"status": "success", "mode": mode}


@api_router.get("/pattern/performance")
async def get_pattern_performance():
    """
    Get Pattern Engine performance statistics (Anti-Illusion System)
    
    Shows:
    - Overall performance
    - Performance by pattern type
    - Performance by session
    - Executed vs simulated comparison
    """
    return pattern_signal_generator.get_performance()


@api_router.get("/audit/pattern-performance")
async def audit_pattern_performance(pattern_type: str = None):
    """
    ANTI-ILLUSION SYSTEM - Real edge measurement.
    
    Returns FULL pattern performance analysis:
    - Overall performance
    - Performance by individual pattern
    - Performance by pattern combination
    - Performance by pattern count (1, 2, 3+)
    - Recommendations based on data
    
    Use pattern_type parameter to filter by specific pattern.
    """
    if pattern_type:
        return pattern_tracker_v2.get_pattern_performance(pattern_type)
    return pattern_tracker_v2.get_full_analysis()


@api_router.get("/pattern/tracker/status")
async def get_pattern_tracker_status():
    """Get Pattern Tracker V2 status"""
    return pattern_tracker_v2.get_status()


@api_router.get("/pattern/tracker/pending")
async def get_pending_patterns():
    """Get all pending (active) tracked patterns"""
    return {
        "count": len(pattern_tracker_v2.pending_trades),
        "patterns": [p.to_dict() for p in pattern_tracker_v2.pending_trades.values()]
    }


@api_router.get("/pattern/tracker/completed")
async def get_completed_patterns(limit: int = 50):
    """Get completed patterns"""
    patterns = pattern_tracker_v2.completed_trades[-limit:]
    return {
        "count": len(patterns),
        "patterns": [p.to_dict() for p in patterns]
    }


@api_router.get("/pattern/combinations")
async def get_pattern_combinations():
    """
    Get performance by pattern combinations.
    
    Shows which combinations of patterns (e.g., trend+pullback) 
    have the best edge.
    """
    return pattern_tracker_v2.get_combination_performance()


@api_router.get("/pattern/by-count")
async def get_pattern_count_analysis():
    """
    Get performance by number of active patterns.
    
    Shows if 1 pattern, 2 patterns, or 3+ patterns 
    correlate with better performance.
    """
    return pattern_tracker_v2.get_pattern_count_analysis()


@api_router.get("/pattern/scan/test/{symbol}")
async def test_pattern_scan(symbol: str):
    """
    Test pattern detection on a symbol (debugging endpoint)
    
    Returns detected patterns without executing them.
    """
    try:
        asset = Asset(symbol)
    except:
        raise HTTPException(status_code=400, detail=f"Invalid symbol: {symbol}")
    
    # Get candle data
    candles_h1 = market_data_cache.get_candles(asset, Timeframe.H1)
    candles_m15 = market_data_cache.get_candles(asset, Timeframe.M15)
    candles_m5 = market_data_cache.get_candles(asset, Timeframe.M5)
    
    if not candles_m5:
        return {"error": "No candle data available"}
    
    # Get current price
    price_data = market_data_cache.get_price(asset)
    current_price = price_data.mid if price_data else 0
    
    if current_price <= 0:
        return {"error": "No price data available"}
    
    # Build context
    context = pattern_engine.build_market_context(
        symbol=symbol,
        candles_h1=candles_h1 or [],
        candles_m15=candles_m15 or [],
        candles_m5=candles_m5 or [],
        current_price=current_price
    )
    
    # Scan patterns
    patterns = pattern_engine.scan_all_patterns(
        symbol=symbol,
        candles_h1=candles_h1 or [],
        candles_m15=candles_m15 or [],
        candles_m5=candles_m5 or [],
        current_price=current_price
    )
    
    return {
        "symbol": symbol,
        "timestamp": datetime.utcnow().isoformat(),
        "current_price": current_price,
        "session": context.session.value,
        "data_valid": context.data_valid,
        "validation_error": context.validation_error,
        "trends": {
            "h1": {
                "direction": context.trend_h1.direction.value,
                "strength": context.trend_h1.strength,
                "hh": context.trend_h1.hh_count,
                "hl": context.trend_h1.hl_count,
                "lh": context.trend_h1.lh_count,
                "ll": context.trend_h1.ll_count
            },
            "m15": {
                "direction": context.trend_m15.direction.value,
                "strength": context.trend_m15.strength
            },
            "m5": {
                "direction": context.trend_m5.direction.value,
                "strength": context.trend_m5.strength
            }
        },
        "indicators": {
            "atr_m5": context.atr_m5,
            "atr_h1": context.atr_h1,
            "ema20_m5": context.ema20_m5,
            "ema50_m5": context.ema50_m5
        },
        "patterns_detected": len(patterns),
        "patterns": [p.to_dict() for p in patterns]
    }


@api_router.get("/pattern/config")
async def get_pattern_config():
    """Get Pattern Engine configuration"""
    from services.pattern_engine import DEFAULT_CONFIG
    from dataclasses import asdict
    
    return {
        "engine_config": asdict(DEFAULT_CONFIG),
        "generator_config": {
            "mode": pattern_signal_generator.config.mode.value,
            "scan_interval": pattern_signal_generator.config.scan_interval,
            "allowed_assets": pattern_signal_generator.config.allowed_assets,
            "duplicate_window_minutes": pattern_signal_generator.config.duplicate_window_minutes,
            "min_confidence": pattern_signal_generator.config.min_confidence
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


# TEMPORARY: Manual device registration for testing
@app.post("/api/debug/register-device-manual")
async def debug_register_device_manual():
    """
    Manually register a test device for debugging push notifications
    """
    try:
        # Use a known Expo push token format for testing
        # The real token will be registered when app reconnects
        test_device_id = f"manual_test_{int(datetime.now().timestamp())}"
        
        # Return instructions
        return {
            "status": "info",
            "message": "Per registrare il dispositivo, riapri l'app dopo aver fatto 'Shake' → 'Reload' in Expo Go",
            "current_devices": await device_storage.get_device_count()
        }
    except Exception as e:
        return {"error": str(e)}

# === ENDPOINT PER DOWNLOAD ANALISI ===
from fastapi.responses import FileResponse, PlainTextResponse
import os

@app.get("/api/download/analisi-statistiche")
async def download_analisi_statistiche():
    """Download file analisi statistiche"""
    file_path = "/app/backend/data/ANALISI_STATISTICHE_COMPLETE.txt"
    if os.path.exists(file_path):
        return FileResponse(file_path, filename="ANALISI_STATISTICHE_COMPLETE.txt", media_type="text/plain")
    return {"error": "File not found"}

@app.get("/api/download/analisi-trade")
async def download_analisi_trade():
    """Download file analisi trade completi"""
    file_path = "/app/backend/data/ANALISI_COMPLETA_TRADE.txt"
    if os.path.exists(file_path):
        return FileResponse(file_path, filename="ANALISI_COMPLETA_TRADE.txt", media_type="text/plain")
    return {"error": "File not found"}

@app.get("/api/download/analisi-json")
async def download_analisi_json():
    """Download analisi in formato JSON compatto per ChatGPT"""
    import json
    
    # Load data
    with open("/app/backend/data/tracked_signals.json", "r") as f:
        tracked = json.load(f)
    
    with open("/app/backend/data/signal_snapshots.json", "r") as f:
        snapshots = json.load(f)
    
    completed = tracked.get("completed", [])
    
    # Create compact analysis
    analysis = {
        "summary": {
            "total_trades": len(completed),
            "wins": len([t for t in completed if t.get("final_outcome") == "win"]),
            "losses": len([t for t in completed if t.get("final_outcome") == "loss"]),
            "expired": len([t for t in completed if t.get("final_outcome") == "expired"]),
            "win_rate": f"{len([t for t in completed if t.get('final_outcome') == 'win']) / (len([t for t in completed if t.get('final_outcome') == 'win']) + len([t for t in completed if t.get('final_outcome') == 'loss'])) * 100:.1f}%"
        },
        "trades": []
    }
    
    for t in completed:
        trade_data = {
            "id": t.get("signal_id"),
            "asset": t.get("asset"),
            "direction": t.get("direction"),
            "outcome": t.get("final_outcome"),
            "session": t.get("session"),
            "setup": t.get("setup_type"),
            "confidence": t.get("confidence_score"),
            "rr": t.get("risk_reward"),
            "entry": t.get("entry_price"),
            "sl": t.get("stop_loss"),
            "tp1": t.get("take_profit_1"),
            "mfe": t.get("max_favorable_excursion"),
            "mae": t.get("max_adverse_excursion"),
            "peak_r": t.get("peak_r_before_reversal"),
            "factors": t.get("score_breakdown", {}).get("breakdown", [])
        }
        analysis["trades"].append(trade_data)
    
    return analysis


# ==================== TEST ENDPOINTS ====================

@api_router.post("/test/create-fake-trade")
async def create_fake_trade():
    """
    TEST: Create a fake trade and simulate full lifecycle
    
    This will:
    1. Create an accepted signal
    2. Add it to tracker as active
    3. Simulate TP hit
    4. Close the trade
    """
    import uuid
    from datetime import datetime
    from services.signal_snapshot_service import signal_snapshot_service, SignalSnapshot
    from services.signal_outcome_tracker_v2 import signal_outcome_tracker, TrackedSignal
    
    # Get current price
    provider = provider_manager.get_provider()
    quote = await provider.get_live_quote(Asset.EURUSD) if provider else None
    
    if not quote:
        return {"error": "Cannot get current price"}
    
    current_price = quote.mid_price
    
    # Create fake signal that's already in profit (price moved in our favor)
    # SELL signal where current price is BELOW entry (in profit)
    entry_price = current_price + 0.0010  # Entry was 10 pips higher
    stop_loss = entry_price + 0.0020  # SL 20 pips above entry
    take_profit = entry_price - 0.0015  # TP 15 pips below entry (already hit!)
    
    signal_id = f"TEST_SELL_{datetime.utcnow().strftime('%Y%m%d_%H%M%S')}"
    timestamp = datetime.utcnow().isoformat()
    
    # Step 1: Create snapshot as "accepted"
    snapshot = SignalSnapshot(
        signal_id=signal_id,
        symbol="EURUSD",
        direction="SELL",
        status="accepted",
        timestamp=timestamp,
        entry_price=entry_price,
        stop_loss=stop_loss,
        take_profit=take_profit,
        score=75.0,
        score_breakdown={"total_score": 75.0, "factors": []},
        session="Test",
        setup_type="Test Signal",
        short_reason="Test trade for lifecycle verification",
        rejection_reason=None,
        atr=0.0010
    )
    
    await signal_snapshot_service.save_snapshot(snapshot)
    
    # Step 2: Add to tracker as active
    tracked_signal = TrackedSignal(
        signal_id=signal_id,
        asset="EURUSD",
        direction="SELL",
        entry_price=entry_price,
        stop_loss=stop_loss,
        take_profit_1=take_profit,
        take_profit_2=take_profit - 0.0010,
        timestamp=timestamp,
        confidence_score=75.0,
        setup_type="Test Signal",
        session="Test"
    )
    
    signal_outcome_tracker.active_signals[signal_id] = tracked_signal
    
    # Update snapshot to active
    await signal_snapshot_service.update_status(signal_id, "active")
    
    # Step 3: Simulate price check - TP should be hit since current_price < take_profit for SELL
    # Actually let's check: for SELL, TP hit when current_price <= take_profit
    tp_hit = current_price <= take_profit
    
    result = {
        "signal_id": signal_id,
        "entry_price": entry_price,
        "current_price": current_price,
        "take_profit": take_profit,
        "stop_loss": stop_loss,
        "tp_would_hit": tp_hit,
        "status": "created_as_active",
        "message": "Trade created. Tracker will close it on next check if TP/SL hit."
    }
    
    # If TP is already hit, force close it now
    if tp_hit:
        await signal_outcome_tracker._complete_signal(signal_id, "tp_hit")
        await signal_snapshot_service.update_status(signal_id, "tp_hit")
        result["status"] = "closed_tp_hit"
        result["message"] = "Trade created and immediately closed as TP was already hit!"
    
    return result


@api_router.post("/test/force-close-trade/{signal_id}")
async def force_close_trade(signal_id: str, outcome: str = "tp_hit"):
    """
    TEST: Force close a specific trade
    
    outcome: tp_hit, sl_hit, or expired
    """
    from services.signal_snapshot_service import signal_snapshot_service
    from services.signal_outcome_tracker_v2 import signal_outcome_tracker
    
    if signal_id not in signal_outcome_tracker.active_signals:
        return {"error": f"Signal {signal_id} not found in active signals"}
    
    # Close in tracker
    await signal_outcome_tracker._complete_signal(signal_id, outcome)
    
    # Update snapshot
    await signal_snapshot_service.update_status(signal_id, outcome)
    
    return {
        "success": True,
        "signal_id": signal_id,
        "outcome": outcome,
        "message": f"Trade {signal_id} closed as {outcome}"
    }
