"""
FCM v1 Push Notification Service
================================
Direct integration with Firebase Cloud Messaging v1 API.
Uses service account credentials for authentication.
Works with Expo push tokens on Android devices.
"""

import os
import json
import time
import logging
import aiohttp
import asyncio
from typing import List, Dict, Any, Optional
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

logger = logging.getLogger(__name__)

# Path to service account credentials
CREDENTIALS_PATH = Path(__file__).parent.parent / "credentials" / "firebase-service-account.json"


@dataclass
class FCMPushResult:
    """Result of a push notification attempt"""
    token: str
    success: bool
    message_id: Optional[str] = None
    error: Optional[str] = None
    error_code: Optional[str] = None


class FCMv1PushService:
    """
    Firebase Cloud Messaging v1 API Push Service
    
    Features:
    - OAuth2 authentication with service account
    - Automatic token refresh
    - Direct FCM v1 API integration
    - Works with Expo push tokens
    - Background notification support
    """
    
    FCM_SEND_URL = "https://fcm.googleapis.com/v1/projects/{project_id}/messages:send"
    TOKEN_URL = "https://oauth2.googleapis.com/token"
    SCOPES = ["https://www.googleapis.com/auth/firebase.messaging"]
    
    def __init__(self):
        self.credentials: Optional[Dict] = None
        self.access_token: Optional[str] = None
        self.token_expiry: float = 0
        self.project_id: Optional[str] = None
        self.sent_count = 0
        self.failed_count = 0
        self._initialized = False
    
    async def initialize(self) -> bool:
        """Load credentials and initialize the service"""
        try:
            # Try multiple environment variable names
            creds_base64 = (
                os.environ.get("FIREBASE_SERVICE_ACCOUNT_BASE64") or
                os.environ.get("FIREBASE_CREDENTIALS_BASE64") or
                os.environ.get("FCM_CREDENTIALS") or
                os.environ.get("GOOGLE_APPLICATION_CREDENTIALS_BASE64")
            )
            
            creds_json_str = (
                os.environ.get("FIREBASE_SERVICE_ACCOUNT_JSON") or
                os.environ.get("FIREBASE_CREDENTIALS") or
                os.environ.get("FCM_SERVICE_ACCOUNT") or
                os.environ.get("GOOGLE_APPLICATION_CREDENTIALS_JSON")
            )
            
            if creds_base64:
                import base64
                creds_json = base64.b64decode(creds_base64).decode('utf-8')
                self.credentials = json.loads(creds_json)
                logger.info("✅ FCM v1: Loaded credentials from base64 env var")
            elif creds_json_str:
                self.credentials = json.loads(creds_json_str)
                logger.info("✅ FCM v1: Loaded credentials from JSON env var")
            elif CREDENTIALS_PATH.exists():
                with open(CREDENTIALS_PATH) as f:
                    self.credentials = json.load(f)
                logger.info(f"✅ FCM v1: Loaded credentials from {CREDENTIALS_PATH}")
            else:
                logger.error("❌ FCM v1: No credentials found. Set one of: FIREBASE_SERVICE_ACCOUNT_BASE64, FIREBASE_CREDENTIALS, FCM_CREDENTIALS")
                logger.error(f"   Available env vars: {[k for k in os.environ.keys() if 'FIRE' in k.upper() or 'FCM' in k.upper() or 'GOOGLE' in k.upper()]}")
                return False
            
            self.project_id = self.credentials.get("project_id")
            if not self.project_id:
                logger.error("❌ FCM v1: No project_id in credentials")
                return False
            
            # Get initial access token
            token_result = await self._refresh_access_token()
            if not token_result:
                logger.error("❌ FCM v1: Failed to get access token")
                return False
            
            self._initialized = True
            logger.info(f"✅ FCM v1 Push Service initialized for project: {self.project_id}")
            return True
            
        except Exception as e:
            logger.error(f"❌ FCM v1 initialization error: {str(e)}")
            import traceback
            logger.error(traceback.format_exc())
            return False
    
    async def _refresh_access_token(self) -> bool:
        """Get a new OAuth2 access token using service account"""
        try:
            import jwt
            
            now = int(time.time())
            
            # Create JWT for service account
            payload = {
                "iss": self.credentials["client_email"],
                "sub": self.credentials["client_email"],
                "aud": self.TOKEN_URL,
                "iat": now,
                "exp": now + 3600,  # 1 hour
                "scope": " ".join(self.SCOPES)
            }
            
            # Sign JWT with private key
            private_key = self.credentials["private_key"]
            signed_jwt = jwt.encode(payload, private_key, algorithm="RS256")
            
            # Exchange JWT for access token
            async with aiohttp.ClientSession() as session:
                async with session.post(
                    self.TOKEN_URL,
                    data={
                        "grant_type": "urn:ietf:params:oauth:grant-type:jwt-bearer",
                        "assertion": signed_jwt
                    },
                    timeout=aiohttp.ClientTimeout(total=30)
                ) as response:
                    if response.status == 200:
                        data = await response.json()
                        self.access_token = data["access_token"]
                        self.token_expiry = now + data.get("expires_in", 3600) - 60  # Refresh 1 min early
                        logger.info("✅ FCM v1: Access token refreshed")
                        return True
                    else:
                        error = await response.text()
                        logger.error(f"❌ FCM v1 token refresh failed: {error}")
                        return False
                        
        except Exception as e:
            logger.error(f"❌ FCM v1 token refresh error: {str(e)}")
            return False
    
    async def _ensure_valid_token(self) -> bool:
        """Ensure we have a valid access token"""
        if not self._initialized:
            await self.initialize()
        
        if time.time() >= self.token_expiry:
            return await self._refresh_access_token()
        return True
    
    def _expo_token_to_fcm(self, expo_token: str) -> Optional[str]:
        """
        Extract FCM token from Expo push token.
        Expo tokens are in format: ExponentPushToken[FCM_TOKEN]
        """
        if not expo_token:
            return None
        
        # Handle Expo token format
        if expo_token.startswith("ExponentPushToken[") and expo_token.endswith("]"):
            return expo_token[18:-1]  # Extract the FCM token inside
        
        # Already a raw FCM token
        return expo_token
    
    async def send_notification(
        self,
        token: str,
        title: str,
        body: str,
        data: Optional[Dict[str, Any]] = None,
        sound: str = "default",
        channel_id: str = "trading-signals",
        priority: str = "high"
    ) -> FCMPushResult:
        """
        Send a push notification via FCM v1 API
        
        Args:
            token: Expo push token or FCM token
            title: Notification title
            body: Notification body
            data: Custom data payload
            sound: Notification sound
            channel_id: Android notification channel
            priority: Message priority (high/normal)
        
        Returns:
            FCMPushResult with success status
        """
        if not await self._ensure_valid_token():
            return FCMPushResult(
                token=token,
                success=False,
                error="Failed to get access token"
            )
        
        # Convert Expo token to FCM token
        fcm_token = self._expo_token_to_fcm(token)
        if not fcm_token:
            return FCMPushResult(
                token=token,
                success=False,
                error="Invalid token format"
            )
        
        # Build FCM v1 message
        message = {
            "message": {
                "token": fcm_token,
                "notification": {
                    "title": title,
                    "body": body
                },
                "android": {
                    "priority": priority,
                    "notification": {
                        "channel_id": channel_id,
                        "sound": sound,
                        "default_sound": True,
                        "notification_priority": "PRIORITY_HIGH",
                        "visibility": "PUBLIC"
                    }
                },
                "data": {
                    "title": title,
                    "body": body,
                    "channelId": channel_id,
                    **(data or {})
                }
            }
        }
        
        # Add custom data for Expo compatibility
        if data:
            # Convert all values to strings (FCM requirement)
            message["message"]["data"].update({
                k: str(v) if not isinstance(v, str) else v 
                for k, v in data.items()
            })
        
        url = self.FCM_SEND_URL.format(project_id=self.project_id)
        
        try:
            async with aiohttp.ClientSession() as session:
                async with session.post(
                    url,
                    json=message,
                    headers={
                        "Authorization": f"Bearer {self.access_token}",
                        "Content-Type": "application/json"
                    },
                    timeout=aiohttp.ClientTimeout(total=30)
                ) as response:
                    response_data = await response.json()
                    
                    if response.status == 200:
                        message_id = response_data.get("name", "")
                        self.sent_count += 1
                        logger.info(f"✅ FCM v1: Push sent to {token[:30]}... -> {message_id}")
                        return FCMPushResult(
                            token=token,
                            success=True,
                            message_id=message_id
                        )
                    else:
                        error = response_data.get("error", {})
                        error_msg = error.get("message", str(response_data))
                        error_code = error.get("code", response.status)
                        self.failed_count += 1
                        logger.error(f"❌ FCM v1: Push failed for {token[:30]}...: {error_msg}")
                        return FCMPushResult(
                            token=token,
                            success=False,
                            error=error_msg,
                            error_code=str(error_code)
                        )
                        
        except Exception as e:
            self.failed_count += 1
            logger.error(f"❌ FCM v1: Push exception for {token[:30]}...: {str(e)}")
            return FCMPushResult(
                token=token,
                success=False,
                error=str(e)
            )
    
    async def send_to_all_devices(
        self,
        tokens: List[str],
        title: str,
        body: str,
        data: Optional[Dict[str, Any]] = None,
        sound: str = "default",
        channel_id: str = "trading-signals"
    ) -> List[FCMPushResult]:
        """Send notification to multiple devices"""
        if not tokens:
            return []
        
        results = []
        for token in tokens:
            result = await self.send_notification(
                token=token,
                title=title,
                body=body,
                data=data,
                sound=sound,
                channel_id=channel_id
            )
            results.append(result)
            # Small delay to avoid rate limiting
            await asyncio.sleep(0.1)
        
        return results
    
    def get_stats(self) -> Dict:
        """Get push notification statistics"""
        return {
            "service": "FCM v1",
            "project_id": self.project_id,
            "initialized": self._initialized,
            "sent": self.sent_count,
            "failed": self.failed_count,
            "total": self.sent_count + self.failed_count
        }


# Global instance
fcm_push_service = FCMv1PushService()
