"""Push Notification Service - Server-side push notifications via Expo Push API"""
import aiohttp
import asyncio
import logging
from typing import List, Dict, Any, Optional
from datetime import datetime
from dataclasses import dataclass

logger = logging.getLogger(__name__)

@dataclass
class PushResult:
    """Result of a push notification attempt"""
    token: str
    success: bool
    ticket_id: Optional[str] = None
    error: Optional[str] = None


class PushNotificationService:
    """
    Central push notification service using Expo Push API
    
    Features:
    - Batch notifications to multiple devices
    - Automatic retry on failure
    - Response logging
    - Error tracking
    """
    
    EXPO_PUSH_URL = "https://exp.host/--/api/v2/push/send"
    MAX_BATCH_SIZE = 100  # Expo recommends max 100 per request
    
    def __init__(self):
        self.session: Optional[aiohttp.ClientSession] = None
        self.sent_count = 0
        self.failed_count = 0
    
    async def _get_session(self) -> aiohttp.ClientSession:
        """Get or create aiohttp session"""
        if not self.session or self.session.closed:
            self.session = aiohttp.ClientSession()
        return self.session
    
    async def send_notification(
        self,
        token: str,
        title: str,
        body: str,
        data: Optional[Dict[str, Any]] = None,
        sound: str = "default",
        badge: int = 1,
        channel_id: str = "signals"
    ) -> PushResult:
        """
        Send a single push notification
        
        Args:
            token: Expo push token (ExpoPushToken[xxx])
            title: Notification title
            body: Notification body
            data: Custom data payload
            sound: Sound to play
            badge: Badge count
            channel_id: Android notification channel
        
        Returns:
            PushResult with success status and any errors
        """
        message = {
            "to": token,
            "title": title,
            "body": body,
            "sound": sound,
            "badge": badge,
            "channelId": channel_id,
        }
        
        if data:
            message["data"] = data
        
        results = await self._send_batch([message])
        return results[0] if results else PushResult(token=token, success=False, error="No response")
    
    async def send_to_all_devices(
        self,
        tokens: List[str],
        title: str,
        body: str,
        data: Optional[Dict[str, Any]] = None,
        sound: str = "default",
        badge: int = 1,
        channel_id: str = "signals"
    ) -> List[PushResult]:
        """
        Send notification to multiple devices with batching
        
        Args:
            tokens: List of Expo push tokens
            title: Notification title
            body: Notification body
            data: Custom data payload
            sound: Sound to play
            badge: Badge count
            channel_id: Android notification channel
        
        Returns:
            List of PushResult for each token
        """
        if not tokens:
            logger.warning("No tokens provided for push notification")
            return []
        
        # Create messages
        messages = []
        for token in tokens:
            message = {
                "to": token,
                "title": title,
                "body": body,
                "sound": sound,
                "badge": badge,
                "channelId": channel_id,
            }
            if data:
                message["data"] = data
            messages.append(message)
        
        # Send in batches
        all_results = []
        for i in range(0, len(messages), self.MAX_BATCH_SIZE):
            batch = messages[i:i + self.MAX_BATCH_SIZE]
            results = await self._send_batch(batch)
            all_results.extend(results)
        
        return all_results
    
    async def _send_batch(self, messages: List[Dict], retry: bool = True) -> List[PushResult]:
        """
        Send a batch of messages to Expo Push API
        
        Args:
            messages: List of message payloads
            retry: Whether to retry failed messages
        
        Returns:
            List of PushResult
        """
        results = []
        session = await self._get_session()
        
        try:
            logger.info(f"📤 Sending {len(messages)} push notifications...")
            
            async with session.post(
                self.EXPO_PUSH_URL,
                json=messages,
                headers={"Content-Type": "application/json"},
                timeout=aiohttp.ClientTimeout(total=30)
            ) as response:
                response_data = await response.json()
                
                if response.status == 200:
                    tickets = response_data.get("data", [])
                    
                    for i, ticket in enumerate(tickets):
                        token = messages[i]["to"]
                        
                        if ticket.get("status") == "ok":
                            results.append(PushResult(
                                token=token,
                                success=True,
                                ticket_id=ticket.get("id")
                            ))
                            self.sent_count += 1
                            logger.info(f"✅ Push sent to {token[:30]}...")
                        else:
                            error = ticket.get("message", "Unknown error")
                            results.append(PushResult(
                                token=token,
                                success=False,
                                error=error
                            ))
                            self.failed_count += 1
                            logger.error(f"❌ Push failed for {token[:30]}...: {error}")
                else:
                    error = f"HTTP {response.status}: {response_data}"
                    logger.error(f"Expo API error: {error}")
                    
                    # Retry once if enabled
                    if retry:
                        logger.info("Retrying failed batch...")
                        await asyncio.sleep(1)
                        return await self._send_batch(messages, retry=False)
                    
                    for msg in messages:
                        results.append(PushResult(
                            token=msg["to"],
                            success=False,
                            error=error
                        ))
                        self.failed_count += 1
        
        except asyncio.TimeoutError:
            logger.error("Expo Push API timeout")
            if retry:
                logger.info("Retrying after timeout...")
                await asyncio.sleep(2)
                return await self._send_batch(messages, retry=False)
            
            for msg in messages:
                results.append(PushResult(
                    token=msg["to"],
                    success=False,
                    error="Timeout"
                ))
                self.failed_count += 1
        
        except Exception as e:
            logger.error(f"Push notification error: {e}")
            for msg in messages:
                results.append(PushResult(
                    token=msg["to"],
                    success=False,
                    error=str(e)
                ))
                self.failed_count += 1
        
        return results
    
    async def send_signal_notification(
        self,
        tokens: List[str],
        signal_type: str,
        asset: str,
        entry_price: float,
        confidence: float,
        signal_id: str,
        stop_loss: Optional[float] = None,
        take_profit: Optional[float] = None,
        news_warning: bool = False
    ) -> List[PushResult]:
        """
        Send a trading signal notification
        
        Args:
            tokens: Device push tokens
            signal_type: BUY or SELL
            asset: Trading asset (EURUSD, XAUUSD)
            entry_price: Entry price
            confidence: Confidence score
            signal_id: Signal ID for deep linking
            stop_loss: Stop loss price
            take_profit: Take profit price
            news_warning: Whether high-impact news is near
        """
        # Format price based on asset
        if asset == "EURUSD":
            price_str = f"{entry_price:.5f}"
        else:
            price_str = f"{entry_price:.2f}"
        
        title = f"🔔 {signal_type} Signal: {asset}"
        if news_warning:
            title += " ⚠️"
        
        body = f"Entry: {price_str} | Confidence: {confidence:.0f}%"
        
        if stop_loss:
            sl_str = f"{stop_loss:.5f}" if asset == "EURUSD" else f"{stop_loss:.2f}"
            body += f"\nSL: {sl_str}"
        
        if take_profit:
            tp_str = f"{take_profit:.5f}" if asset == "EURUSD" else f"{take_profit:.2f}"
            body += f" | TP: {tp_str}"
        
        if news_warning:
            body += "\n⚠️ High-impact news nearby"
        
        data = {
            "type": "signal",
            "signalType": signal_type,
            "signalId": signal_id,
            "asset": asset,
            "entry": entry_price,
            "confidence": confidence
        }
        
        return await self.send_to_all_devices(tokens, title, body, data)
    
    async def send_pre_signal_alert(
        self,
        tokens: List[str],
        alert_type: str,
        asset: str,
        message: str
    ) -> List[PushResult]:
        """
        Send pre-signal informational alert
        
        Args:
            tokens: Device push tokens
            alert_type: Type of alert (setup_forming, liquidity_sweep, breakout_approaching, etc.)
            asset: Trading asset
            message: Alert message
        """
        title = f"📊 {asset} Alert"
        body = message
        
        data = {
            "type": "pre_signal",
            "alertType": alert_type,
            "asset": asset
        }
        
        return await self.send_to_all_devices(
            tokens, title, body, data,
            sound="default",
            badge=0,  # Don't increase badge for informational alerts
            channel_id="alerts"
        )
    
    async def send_to_all(
        self,
        title: str,
        body: str,
        data: Optional[Dict[str, Any]] = None,
        sound: str = "default",
        badge: int = 1,
        channel_id: str = "signals"
    ) -> List[PushResult]:
        """
        Send notification to ALL registered devices.
        
        This is a convenience wrapper that fetches all device tokens
        and sends the notification to all of them.
        
        Args:
            title: Notification title
            body: Notification body
            data: Custom data payload
            sound: Sound to play
            badge: Badge count
            channel_id: Android notification channel
        
        Returns:
            List of PushResult for each device
        """
        from services.device_storage_service import device_storage
        
        # Get all registered push tokens
        tokens = await device_storage.get_all_push_tokens()
        
        if not tokens:
            logger.warning("No registered devices to send notification to")
            return []
        
        logger.info(f"📤 Sending notification to {len(tokens)} devices: {title}")
        
        return await self.send_to_all_devices(
            tokens=tokens,
            title=title,
            body=body,
            data=data,
            sound=sound,
            badge=badge,
            channel_id=channel_id
        )
    
    def get_stats(self) -> Dict[str, int]:
        """Get push notification statistics"""
        return {
            "sent": self.sent_count,
            "failed": self.failed_count,
            "total": self.sent_count + self.failed_count
        }
    
    async def close(self):
        """Close the aiohttp session"""
        if self.session and not self.session.closed:
            await self.session.close()


# Global instance
push_service = PushNotificationService()
