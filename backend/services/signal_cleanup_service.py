"""
Signal Data Cleanup Service
============================

Automatically purges old signal data to prevent database bloat.
Runs daily and removes signals older than the retention period.

Configuration:
- RETENTION_DAYS: 14 (2 weeks) - keeps app fast and responsive
- Runs automatically via BackgroundTasks
- Can be triggered manually via API
"""

import asyncio
import logging
from datetime import datetime, timedelta
from pathlib import Path
import json
import aiofiles

logger = logging.getLogger(__name__)

# Configuration
RETENTION_DAYS = 14  # 2 weeks retention
DATA_DIR = Path("/app/backend/data")

class SignalCleanupService:
    """Service to automatically purge old signal data"""
    
    def __init__(self, retention_days: int = RETENTION_DAYS):
        self.retention_days = retention_days
        self.last_cleanup = None
        self.cleanup_stats = {
            'total_cleanups': 0,
            'total_deleted': 0,
            'last_cleanup_at': None,
            'last_deleted_count': 0
        }
        logger.info(f"🧹 SignalCleanupService initialized (retention: {retention_days} days)")
    
    def _get_cutoff_date(self) -> datetime:
        """Get the cutoff date for cleanup"""
        return datetime.utcnow() - timedelta(days=self.retention_days)
    
    async def _cleanup_json_file(self, filepath: Path, timestamp_field: str = 'timestamp') -> int:
        """Clean old records from a JSON file"""
        if not filepath.exists():
            return 0
        
        try:
            async with aiofiles.open(filepath, 'r') as f:
                data = json.loads(await f.read())
            
            cutoff = self._get_cutoff_date()
            deleted_count = 0
            
            # Handle different data structures
            if isinstance(data, dict):
                # Handle signal_snapshots.json structure
                if 'snapshots' in data:
                    original_count = len(data['snapshots'])
                    data['snapshots'] = [
                        s for s in data['snapshots']
                        if self._is_recent(s.get(timestamp_field), cutoff)
                    ]
                    deleted_count = original_count - len(data['snapshots'])
                    data['total_count'] = len(data['snapshots'])
                
                # Handle tracked_signals.json structure
                if 'completed' in data:
                    original_count = len(data['completed'])
                    data['completed'] = [
                        s for s in data['completed']
                        if self._is_recent(s.get(timestamp_field), cutoff)
                    ]
                    deleted_count += original_count - len(data['completed'])
                
                # Handle candidate_audit.json structure
                if 'candidates' in data:
                    original_count = len(data['candidates'])
                    data['candidates'] = [
                        c for c in data['candidates']
                        if self._is_recent(c.get(timestamp_field), cutoff)
                    ]
                    deleted_count += original_count - len(data['candidates'])
                    data['total_candidates'] = len(data['candidates'])
                    
                    # Recalculate counts
                    data['accepted_count'] = len([c for c in data['candidates'] if c.get('decision') == 'accepted'])
                    data['rejected_count'] = len([c for c in data['candidates'] if c.get('decision') == 'rejected'])
            
            elif isinstance(data, list):
                original_count = len(data)
                data = [
                    item for item in data
                    if self._is_recent(item.get(timestamp_field), cutoff)
                ]
                deleted_count = original_count - len(data)
            
            # Save cleaned data
            if deleted_count > 0:
                if isinstance(data, dict):
                    data['updated_at'] = datetime.utcnow().isoformat()
                    data['last_cleanup'] = datetime.utcnow().isoformat()
                
                async with aiofiles.open(filepath, 'w') as f:
                    await f.write(json.dumps(data, indent=2))
                
                logger.info(f"🧹 Cleaned {deleted_count} old records from {filepath.name}")
            
            return deleted_count
            
        except Exception as e:
            logger.error(f"Error cleaning {filepath}: {e}")
            return 0
    
    def _is_recent(self, timestamp_str: str, cutoff: datetime) -> bool:
        """Check if a timestamp is more recent than cutoff"""
        if not timestamp_str:
            return True  # Keep records without timestamp
        
        try:
            # Handle different timestamp formats
            for fmt in ["%Y-%m-%dT%H:%M:%S.%f", "%Y-%m-%dT%H:%M:%S", "%Y-%m-%d %H:%M:%S"]:
                try:
                    ts = datetime.strptime(timestamp_str[:26], fmt)
                    return ts >= cutoff
                except ValueError:
                    continue
            return True  # Keep if can't parse
        except:
            return True
    
    async def run_cleanup(self) -> dict:
        """Run cleanup on all signal data files"""
        logger.info(f"🧹 Starting cleanup (retention: {self.retention_days} days)")
        
        start_time = datetime.utcnow()
        total_deleted = 0
        
        files_to_clean = [
            (DATA_DIR / "signal_snapshots.json", "timestamp"),
            (DATA_DIR / "tracked_signals.json", "timestamp"),
            (DATA_DIR / "candidate_audit.json", "timestamp"),
        ]
        
        for filepath, ts_field in files_to_clean:
            deleted = await self._cleanup_json_file(filepath, ts_field)
            total_deleted += deleted
        
        # Update stats
        self.cleanup_stats['total_cleanups'] += 1
        self.cleanup_stats['total_deleted'] += total_deleted
        self.cleanup_stats['last_cleanup_at'] = start_time.isoformat()
        self.cleanup_stats['last_deleted_count'] = total_deleted
        self.last_cleanup = start_time
        
        duration = (datetime.utcnow() - start_time).total_seconds()
        
        logger.info(f"🧹 Cleanup complete: {total_deleted} records removed in {duration:.2f}s")
        
        return {
            'success': True,
            'deleted_count': total_deleted,
            'duration_seconds': duration,
            'cutoff_date': self._get_cutoff_date().isoformat(),
            'retention_days': self.retention_days
        }
    
    def get_stats(self) -> dict:
        """Get cleanup statistics"""
        return {
            **self.cleanup_stats,
            'retention_days': self.retention_days,
            'next_cleanup_recommended': (
                (self.last_cleanup + timedelta(days=1)).isoformat()
                if self.last_cleanup else 'never run'
            )
        }


# Global instance
signal_cleanup_service = SignalCleanupService()


async def scheduled_cleanup_task():
    """Background task that runs cleanup daily"""
    while True:
        try:
            # Wait 24 hours between cleanups
            await asyncio.sleep(86400)  # 24 hours
            
            await signal_cleanup_service.run_cleanup()
            
        except asyncio.CancelledError:
            logger.info("🧹 Cleanup task cancelled")
            break
        except Exception as e:
            logger.error(f"🧹 Cleanup task error: {e}")
            await asyncio.sleep(3600)  # Retry in 1 hour on error
