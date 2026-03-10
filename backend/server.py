from fastapi import FastAPI, APIRouter, HTTPException
from dotenv import load_dotenv
from starlette.middleware.cors import CORSMiddleware
from motor.motor_asyncio import AsyncIOMotorClient
import os
import logging
from pathlib import Path
from pydantic import BaseModel, Field
from typing import List, Optional
from datetime import datetime

from models import (
    User, PropProfile, Signal, SignalHistory, Notification,
    Asset, Timeframe, PropPhase, DrawdownType, AccountSettings, SignalType
)
from services.signal_orchestrator import enhanced_signal_orchestrator
from engines.prop_rule_engine import prop_rule_engine
from providers.provider_manager import provider_manager

ROOT_DIR = Path(__file__).parent
load_dotenv(ROOT_DIR / '.env')

# MongoDB connection
mongo_url = os.environ['MONGO_URL']
client = AsyncIOMotorClient(mongo_url)
db = client[os.environ['DB_NAME']]

# Create the main app without a prefix
app = FastAPI(title="PropSignal Engine API")

# Create a router with the /api prefix
api_router = APIRouter(prefix="/api")

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


# ==================== STARTUP/SHUTDOWN EVENTS ====================

@app.on_event("startup")
async def startup_event():
    """Initialize market data provider on startup"""
    logger.info("🚀 Starting PropSignal Engine...")
    
    # Initialize provider manager
    success = await provider_manager.initialize()
    
    if success:
        status = provider_manager.get_status()
        if provider_manager.is_simulation_mode():
            logger.warning(f"⚠️  SIMULATION MODE - Provider: {status.provider_name}")
        else:
            logger.info(f"✅ Production data connected - Provider: {status.provider_name}")
    else:
        logger.error("❌ Failed to initialize market data provider")

@app.on_event("shutdown")
async def shutdown_event():
    """Cleanup on shutdown"""
    await provider_manager.shutdown()
    client.close()
    logger.info("PropSignal Engine shut down")


# ====================REQUEST/RESPONSE MODELS ====================

class CreateUserRequest(BaseModel):
    email: Optional[str] = None

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
    return {"status": "healthy", "timestamp": datetime.utcnow()}


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
