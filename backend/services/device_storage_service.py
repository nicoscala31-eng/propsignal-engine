"""
Device Storage Service - Resilient storage for push notification tokens

This service provides a reliable way to store device tokens with:
- Primary: MongoDB (when available)
- Fallback: In-memory storage with JSON file persistence
- Automatic failover between storage backends
- Health monitoring and diagnostics
"""

import json
import asyncio
import logging
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional, Any
from dataclasses import dataclass, asdict
import aiofiles
import os

logger = logging.getLogger(__name__)

@dataclass
class DeviceRecord:
    """Device registration record"""
    device_id: str
    push_token: str
    platform: str
    device_name: Optional[str] = None
    is_active: bool = True
    created_at: str = ""
    updated_at: str = ""
    
    def __post_init__(self):
        now = datetime.utcnow().isoformat()
        if not self.created_at:
            self.created_at = now
        if not self.updated_at:
            self.updated_at = now
    
    def to_dict(self) -> Dict:
        return asdict(self)
    
    @classmethod
    def from_dict(cls, data: Dict) -> 'DeviceRecord':
        return cls(
            device_id=data.get('device_id', ''),
            push_token=data.get('push_token', ''),
            platform=data.get('platform', ''),
            device_name=data.get('device_name'),
            is_active=data.get('is_active', True),
            created_at=data.get('created_at', ''),
            updated_at=data.get('updated_at', '')
        )


class DeviceStorageService:
    """
    Resilient device storage with automatic failover
    
    Storage priority:
    1. MongoDB (if available and connected)
    2. In-memory with JSON file persistence (fallback)
    """
    
    def __init__(self, data_dir: str = "/app/backend/data"):
        self.data_dir = Path(data_dir)
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self.devices_file = self.data_dir / "devices.json"
        
        # In-memory storage
        self._devices: Dict[str, DeviceRecord] = {}
        self._loaded = False
        
        # MongoDB reference (set externally)
        self._db = None
        self._mongo_available = False
        self._last_mongo_check = None
        self._mongo_check_interval = 60  # seconds
        
        # Stats
        self._stats = {
            'registrations': 0,
            'updates': 0,
            'mongo_failures': 0,
            'file_saves': 0,
            'file_loads': 0
        }
        
        logger.info("📱 DeviceStorageService initialized")
    
    def set_mongodb(self, db):
        """Set MongoDB database reference"""
        self._db = db
        if db is not None:
            self._mongo_available = True
            logger.info("✅ DeviceStorageService: MongoDB connected")
        else:
            self._mongo_available = False
            logger.warning("⚠️ DeviceStorageService: MongoDB not available, using file storage")
    
    async def _check_mongo_health(self) -> bool:
        """Check if MongoDB is actually responsive"""
        if self._db is None:
            return False
        
        try:
            # Try a simple operation with short timeout
            await asyncio.wait_for(
                self._db.devices.find_one({"_test": True}),
                timeout=3.0
            )
            return True
        except Exception as e:
            logger.warning(f"⚠️ MongoDB health check failed: {e}")
            return False
    
    async def _ensure_loaded(self):
        """Ensure in-memory data is loaded from file"""
        if self._loaded:
            return
        
        if self.devices_file.exists():
            try:
                async with aiofiles.open(self.devices_file, 'r') as f:
                    content = await f.read()
                    data = json.loads(content)
                    for device_data in data.get('devices', []):
                        record = DeviceRecord.from_dict(device_data)
                        self._devices[record.device_id] = record
                    self._stats['file_loads'] += 1
                    logger.info(f"📂 Loaded {len(self._devices)} devices from file")
            except Exception as e:
                logger.error(f"❌ Failed to load devices from file: {e}")
        
        self._loaded = True
    
    async def _save_to_file(self):
        """Save in-memory data to file"""
        try:
            data = {
                'devices': [d.to_dict() for d in self._devices.values()],
                'updated_at': datetime.utcnow().isoformat(),
                'count': len(self._devices)
            }
            async with aiofiles.open(self.devices_file, 'w') as f:
                await f.write(json.dumps(data, indent=2))
            self._stats['file_saves'] += 1
            logger.debug(f"💾 Saved {len(self._devices)} devices to file")
        except Exception as e:
            logger.error(f"❌ Failed to save devices to file: {e}")
    
    async def register_device(
        self,
        device_id: str,
        push_token: str,
        platform: str,
        device_name: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        Register or update a device
        
        Returns:
            Dict with status ('registered' or 'updated'), device_id, and storage_backend
        """
        await self._ensure_loaded()
        
        now = datetime.utcnow().isoformat()
        existing = self._devices.get(device_id)
        
        if existing:
            # Update existing
            existing.push_token = push_token
            existing.platform = platform
            existing.device_name = device_name
            existing.is_active = True
            existing.updated_at = now
            status = 'updated'
            self._stats['updates'] += 1
        else:
            # New registration
            record = DeviceRecord(
                device_id=device_id,
                push_token=push_token,
                platform=platform,
                device_name=device_name,
                is_active=True,
                created_at=now,
                updated_at=now
            )
            self._devices[device_id] = record
            status = 'registered'
            self._stats['registrations'] += 1
        
        # Try MongoDB first
        mongo_success = False
        if self._mongo_available:
            try:
                mongo_success = await self._save_to_mongo(device_id)
            except Exception as e:
                logger.warning(f"⚠️ MongoDB save failed, using file: {e}")
                self._stats['mongo_failures'] += 1
                self._mongo_available = False
        
        # Always save to file as backup
        await self._save_to_file()
        
        backend = 'mongodb' if mongo_success else 'file'
        logger.info(f"📱 Device {status}: {device_id[:20]}... (backend: {backend})")
        
        return {
            'status': status,
            'device_id': device_id,
            'storage_backend': backend
        }
    
    async def _save_to_mongo(self, device_id: str) -> bool:
        """Save a device to MongoDB"""
        if self._db is None:
            return False
        
        try:
            record = self._devices.get(device_id)
            if not record:
                return False
            
            await asyncio.wait_for(
                self._db.devices.update_one(
                    {'device_id': device_id},
                    {'$set': record.to_dict()},
                    upsert=True
                ),
                timeout=5.0
            )
            return True
        except asyncio.TimeoutError:
            logger.warning("⚠️ MongoDB save timed out")
            return False
        except Exception as e:
            logger.warning(f"⚠️ MongoDB save error: {e}")
            return False
    
    async def get_device(self, device_id: str) -> Optional[DeviceRecord]:
        """Get a device by ID"""
        await self._ensure_loaded()
        return self._devices.get(device_id)
    
    async def get_active_devices(self) -> List[DeviceRecord]:
        """Get all active devices"""
        await self._ensure_loaded()
        return [d for d in self._devices.values() if d.is_active]
    
    async def get_active_tokens(self) -> List[str]:
        """Get all active push tokens"""
        devices = await self.get_active_devices()
        return [d.push_token for d in devices if d.push_token]
    
    async def deactivate_device(self, device_id: str) -> bool:
        """Deactivate a device"""
        await self._ensure_loaded()
        
        if device_id in self._devices:
            self._devices[device_id].is_active = False
            self._devices[device_id].updated_at = datetime.utcnow().isoformat()
            await self._save_to_file()
            
            # Try MongoDB
            if self._mongo_available and self._db:
                try:
                    await self._db.devices.update_one(
                        {'device_id': device_id},
                        {'$set': {'is_active': False}}
                    )
                except Exception:
                    pass
            
            return True
        return False
    
    async def deactivate_by_token(self, token: str) -> bool:
        """
        Deactivate a device by push token
        
        Used for invalid token cleanup when push notification fails.
        """
        await self._ensure_loaded()
        
        for device_id, record in self._devices.items():
            if record.push_token == token:
                record.is_active = False
                record.updated_at = datetime.utcnow().isoformat()
                await self._save_to_file()
                
                # Try MongoDB
                if self._mongo_available and self._db:
                    try:
                        await self._db.devices.update_one(
                            {'push_token': token},
                            {'$set': {'is_active': False}}
                        )
                    except Exception:
                        pass
                
                logger.info(f"🧹 Deactivated invalid token for device: {device_id[:20]}...")
                return True
        
        return False
    
    async def get_device_count(self) -> Dict[str, int]:
        """Get device counts"""
        await self._ensure_loaded()
        total = len(self._devices)
        active = sum(1 for d in self._devices.values() if d.is_active)
        return {
            'total_devices': total,
            'active_devices': active
        }
    
    def get_stats(self) -> Dict[str, Any]:
        """Get storage statistics"""
        return {
            **self._stats,
            'total_devices': len(self._devices),
            'mongo_available': self._mongo_available,
            'storage_backend': 'mongodb' if self._mongo_available else 'file'
        }
    
    async def health_check(self) -> Dict[str, Any]:
        """Comprehensive health check"""
        await self._ensure_loaded()
        
        mongo_healthy = await self._check_mongo_health() if self._db else False
        file_exists = self.devices_file.exists()
        
        return {
            'status': 'healthy',
            'storage': {
                'primary': 'mongodb' if mongo_healthy else 'file',
                'mongodb_available': mongo_healthy,
                'file_storage_available': True,
                'file_exists': file_exists
            },
            'devices': {
                'total': len(self._devices),
                'active': sum(1 for d in self._devices.values() if d.is_active)
            },
            'stats': self._stats
        }


# Global instance
device_storage = DeviceStorageService()
