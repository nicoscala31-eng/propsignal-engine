"""
Production Control Service - Single Source of Truth for Production State
=========================================================================

CRITICAL SAFETY MODULE

This module provides the ONLY authoritative source of truth for:
1. Scanner state (ON/OFF) - backend-enforced
2. Notification state (ON/OFF) - backend-enforced
3. Active production engine registration
4. Production safeguards against unauthorized engines

PRODUCTION RULES:
- Only ONE engine can be the production engine
- Scanner OFF = NO scanning, NO signals, NO notifications
- Notifications OFF = NO push notifications from ANY path
- All state is backend-enforced, not frontend-only

AUTHORIZED PRODUCTION ENGINE: signal_generator_v3
"""

import logging
from datetime import datetime
from typing import Dict, Optional, Set
from dataclasses import dataclass, field
from enum import Enum
from threading import Lock

logger = logging.getLogger(__name__)


class EngineType(Enum):
    """Registered engine types"""
    SIGNAL_GENERATOR_V3 = "signal_generator_v3"  # PRODUCTION AUTHORIZED
    ADVANCED_SCANNER_V2 = "advanced_scanner_v2"  # DISABLED IN PRODUCTION
    MARKET_SCANNER_LEGACY = "market_scanner_legacy"  # DISABLED IN PRODUCTION
    SIGNAL_ORCHESTRATOR = "signal_orchestrator"  # DISABLED IN PRODUCTION


@dataclass
class ProductionState:
    """Current production state"""
    scanner_enabled: bool = True
    notifications_enabled: bool = True
    last_scanner_toggle: Optional[datetime] = None
    last_notification_toggle: Optional[datetime] = None
    toggled_by: str = "system"


class ProductionControlService:
    """
    Single Source of Truth for Production State
    
    CRITICAL: This service controls ALL production signal activity.
    
    Features:
    - Backend-enforced scanner ON/OFF
    - Backend-enforced notifications ON/OFF
    - Engine authorization registry
    - Production safeguards
    - Audit logging
    """
    
    # The ONLY authorized production engine
    AUTHORIZED_PRODUCTION_ENGINE = EngineType.SIGNAL_GENERATOR_V3
    
    # Engines that are BLOCKED in production
    BLOCKED_ENGINES: Set[EngineType] = {
        EngineType.ADVANCED_SCANNER_V2,
        EngineType.MARKET_SCANNER_LEGACY,
        EngineType.SIGNAL_ORCHESTRATOR,
    }
    
    def __init__(self):
        self._lock = Lock()
        self._state = ProductionState()
        self._initialized = False
        
        # Statistics
        self._scanner_block_count = 0
        self._notification_block_count = 0
        self._unauthorized_engine_block_count = 0
        
        # Audit log (last N events)
        self._audit_log: list = []
        self._max_audit_entries = 100
        
        logger.info("=" * 60)
        logger.info("🛡️ PRODUCTION CONTROL SERVICE INITIALIZED")
        logger.info(f"   Authorized Engine: {self.AUTHORIZED_PRODUCTION_ENGINE.value}")
        logger.info(f"   Blocked Engines: {[e.value for e in self.BLOCKED_ENGINES]}")
        logger.info("=" * 60)
    
    def initialize(self):
        """Initialize production control"""
        with self._lock:
            self._initialized = True
            self._log_audit("INIT", "Production Control Service initialized")
            logger.info("🛡️ Production Control: ACTIVE")
    
    # ==================== STATE QUERIES ====================
    
    def is_scanner_enabled(self) -> bool:
        """Check if scanner is enabled - MUST be called before ANY scanning"""
        with self._lock:
            return self._state.scanner_enabled
    
    def is_notifications_enabled(self) -> bool:
        """Check if notifications are enabled - MUST be called before ANY push"""
        with self._lock:
            return self._state.notifications_enabled
    
    def is_engine_authorized(self, engine: EngineType) -> bool:
        """Check if engine is authorized for production use"""
        return engine == self.AUTHORIZED_PRODUCTION_ENGINE
    
    def is_engine_blocked(self, engine: EngineType) -> bool:
        """Check if engine is blocked in production"""
        return engine in self.BLOCKED_ENGINES
    
    # ==================== STATE CONTROLS ====================
    
    def set_scanner_enabled(self, enabled: bool, toggled_by: str = "api") -> Dict:
        """
        Set scanner state - backend-enforced
        
        When scanner is OFF:
        - No scanning allowed
        - No candidate generation
        - No scoring
        - No notifications
        """
        with self._lock:
            previous = self._state.scanner_enabled
            self._state.scanner_enabled = enabled
            self._state.last_scanner_toggle = datetime.utcnow()
            self._state.toggled_by = toggled_by
            
            action = "ENABLED" if enabled else "DISABLED"
            self._log_audit("SCANNER", f"Scanner {action} by {toggled_by}")
            
            logger.info(f"🔧 SCANNER STATE CHANGED: {previous} → {enabled} (by {toggled_by})")
            
            return {
                "scanner_enabled": enabled,
                "previous_state": previous,
                "toggled_by": toggled_by,
                "timestamp": self._state.last_scanner_toggle.isoformat()
            }
    
    def set_notifications_enabled(self, enabled: bool, toggled_by: str = "api") -> Dict:
        """
        Set notification state - backend-enforced
        
        When notifications are OFF:
        - No push notifications from ANY path
        - No legacy bypass allowed
        """
        with self._lock:
            previous = self._state.notifications_enabled
            self._state.notifications_enabled = enabled
            self._state.last_notification_toggle = datetime.utcnow()
            self._state.toggled_by = toggled_by
            
            action = "ENABLED" if enabled else "DISABLED"
            self._log_audit("NOTIFICATIONS", f"Notifications {action} by {toggled_by}")
            
            logger.info(f"🔧 NOTIFICATION STATE CHANGED: {previous} → {enabled} (by {toggled_by})")
            
            return {
                "notifications_enabled": enabled,
                "previous_state": previous,
                "toggled_by": toggled_by,
                "timestamp": self._state.last_notification_toggle.isoformat()
            }
    
    # ==================== AUTHORIZATION CHECKS ====================
    
    def authorize_scan(self, engine: EngineType) -> tuple[bool, str]:
        """
        Authorize a scan attempt
        
        Returns (authorized, reason)
        
        Checks:
        1. Is engine authorized for production?
        2. Is scanner enabled?
        """
        with self._lock:
            # Check engine authorization
            if engine in self.BLOCKED_ENGINES:
                self._unauthorized_engine_block_count += 1
                reason = f"Engine '{engine.value}' is BLOCKED in production"
                self._log_audit("BLOCK_ENGINE", reason)
                logger.warning(f"🚫 UNAUTHORIZED ENGINE BLOCKED: {engine.value}")
                return False, reason
            
            if engine != self.AUTHORIZED_PRODUCTION_ENGINE:
                self._unauthorized_engine_block_count += 1
                reason = f"Engine '{engine.value}' is not the authorized production engine"
                self._log_audit("BLOCK_ENGINE", reason)
                logger.warning(f"🚫 UNAUTHORIZED ENGINE BLOCKED: {engine.value}")
                return False, reason
            
            # Check scanner state
            if not self._state.scanner_enabled:
                self._scanner_block_count += 1
                reason = "Scanner is DISABLED"
                self._log_audit("BLOCK_SCAN", reason)
                return False, reason
            
            return True, "Authorized"
    
    def authorize_notification(self, engine: EngineType, signal_id: str = "") -> tuple[bool, str]:
        """
        Authorize a notification attempt
        
        Returns (authorized, reason)
        
        Checks:
        1. Is engine authorized for production?
        2. Are notifications enabled?
        """
        with self._lock:
            # Check engine authorization
            if engine in self.BLOCKED_ENGINES:
                self._unauthorized_engine_block_count += 1
                reason = f"Engine '{engine.value}' cannot send notifications - BLOCKED"
                self._log_audit("BLOCK_NOTIF", f"{reason} (signal: {signal_id})")
                logger.warning(f"🚫 NOTIFICATION BLOCKED: {engine.value} tried to send for {signal_id}")
                return False, reason
            
            if engine != self.AUTHORIZED_PRODUCTION_ENGINE:
                self._unauthorized_engine_block_count += 1
                reason = f"Engine '{engine.value}' is not authorized to send notifications"
                self._log_audit("BLOCK_NOTIF", f"{reason} (signal: {signal_id})")
                logger.warning(f"🚫 NOTIFICATION BLOCKED: {engine.value} tried to send for {signal_id}")
                return False, reason
            
            # Check notification state
            if not self._state.notifications_enabled:
                self._notification_block_count += 1
                reason = "Notifications are DISABLED"
                self._log_audit("BLOCK_NOTIF", f"{reason} (signal: {signal_id})")
                return False, reason
            
            return True, "Authorized"
    
    # ==================== PRODUCTION GUARD ====================
    
    def guard_production_startup(self, engine: EngineType) -> bool:
        """
        Guard called at engine startup to prevent unauthorized engines from starting
        
        Returns True if engine is allowed to start, False otherwise
        """
        if engine in self.BLOCKED_ENGINES:
            logger.error(f"🚨 PRODUCTION GUARD: Blocked startup of '{engine.value}'")
            self._log_audit("GUARD_BLOCK", f"Blocked startup of {engine.value}")
            return False
        
        if engine == self.AUTHORIZED_PRODUCTION_ENGINE:
            logger.info(f"✅ PRODUCTION GUARD: Authorized startup of '{engine.value}'")
            self._log_audit("GUARD_ALLOW", f"Authorized startup of {engine.value}")
            return True
        
        logger.warning(f"⚠️ PRODUCTION GUARD: Unknown engine '{engine.value}' - blocking")
        self._log_audit("GUARD_BLOCK", f"Unknown engine {engine.value}")
        return False
    
    # ==================== AUDIT & STATUS ====================
    
    def _log_audit(self, event_type: str, message: str):
        """Add entry to audit log"""
        entry = {
            "timestamp": datetime.utcnow().isoformat(),
            "event_type": event_type,
            "message": message
        }
        self._audit_log.append(entry)
        
        # Trim to max size
        if len(self._audit_log) > self._max_audit_entries:
            self._audit_log = self._audit_log[-self._max_audit_entries:]
    
    def get_status(self) -> Dict:
        """Get complete production control status"""
        with self._lock:
            return {
                "scanner": {
                    "enabled": self._state.scanner_enabled,
                    "last_toggle": self._state.last_scanner_toggle.isoformat() if self._state.last_scanner_toggle else None,
                    "blocks": self._scanner_block_count
                },
                "notifications": {
                    "enabled": self._state.notifications_enabled,
                    "last_toggle": self._state.last_notification_toggle.isoformat() if self._state.last_notification_toggle else None,
                    "blocks": self._notification_block_count
                },
                "engine": {
                    "authorized": self.AUTHORIZED_PRODUCTION_ENGINE.value,
                    "blocked": [e.value for e in self.BLOCKED_ENGINES],
                    "unauthorized_blocks": self._unauthorized_engine_block_count
                },
                "initialized": self._initialized
            }
    
    def get_audit_log(self, limit: int = 20) -> list:
        """Get recent audit log entries"""
        with self._lock:
            return self._audit_log[-limit:]


# Global singleton instance
production_control = ProductionControlService()
