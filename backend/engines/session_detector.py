"""Trading Session Detector"""
from datetime import datetime, time
from models import Session

class SessionDetector:
    """Detects current trading session"""
    
    def __init__(self):
        # Session times in UTC
        self.london_start = time(8, 0)  # 8:00 AM UTC
        self.london_end = time(16, 0)   # 4:00 PM UTC
        self.ny_start = time(13, 0)     # 1:00 PM UTC
        self.ny_end = time(21, 0)       # 9:00 PM UTC
    
    def get_current_session(self, dt: datetime = None) -> Session:
        """Determine current trading session"""
        if dt is None:
            dt = datetime.utcnow()
        
        current_time = dt.time()
        
        # Check for overlap (1:00 PM - 4:00 PM UTC)
        if self.ny_start <= current_time < self.london_end:
            return Session.OVERLAP
        
        # Check for London session (8:00 AM - 4:00 PM UTC)
        if self.london_start <= current_time < self.london_end:
            return Session.LONDON
        
        # Check for New York session (1:00 PM - 9:00 PM UTC)
        if self.ny_start <= current_time < self.ny_end:
            return Session.NEW_YORK
        
        return Session.OTHER
    
    def is_major_session(self, session: Session) -> bool:
        """Check if session is a major trading session"""
        return session in [Session.LONDON, Session.NEW_YORK, Session.OVERLAP]
    
    def get_session_quality_score(self, session: Session) -> float:
        """Score session quality for trading (0-100)"""
        scores = {
            Session.OVERLAP: 100,
            Session.LONDON: 85,
            Session.NEW_YORK: 85,
            Session.OTHER: 40
        }
        return scores.get(session, 40)

session_detector = SessionDetector()
