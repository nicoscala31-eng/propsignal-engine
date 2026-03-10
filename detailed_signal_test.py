#!/usr/bin/env python3
"""
Additional testing to examine signal generation data structure
"""

import asyncio
import aiohttp
import json
from pprint import pprint

BASE_URL = "https://eurusd-alerts.preview.emergentagent.com/api"
TEST_USER_ID = "1773156899.291813"  
TEST_PROP_PROFILE_ID = "1773156903.940538"

async def detailed_signal_test():
    """Get detailed signal generation data"""
    
    async with aiohttp.ClientSession() as session:
        print("🔍 DETAILED SIGNAL GENERATION TEST")
        print("=" * 50)
        
        # Test EURUSD signal generation
        payload = {
            "asset": "EURUSD",
            "prop_profile_id": TEST_PROP_PROFILE_ID
        }
        
        try:
            async with session.post(
                f"{BASE_URL}/users/{TEST_USER_ID}/signals/generate",
                json=payload,
                headers={"Content-Type": "application/json"}
            ) as response:
                
                if response.status == 200:
                    data = await response.json()
                    print("\n📊 EURUSD Signal Generation Response:")
                    pprint(data, width=80)
                    
                    # Check what fields are present
                    print(f"\n🔍 Key Fields Analysis:")
                    print(f"Signal Type: {data.get('signal_type')}")
                    print(f"Confidence: {data.get('confidence')}")
                    print(f"Success Probability: {data.get('success_probability')}")
                    print(f"Live Bid: {data.get('live_bid')}")
                    print(f"Live Ask: {data.get('live_ask')}")
                    print(f"Live Spread Pips: {data.get('live_spread_pips')}")
                    print(f"Data Provider: {data.get('data_provider')}")
                    
                else:
                    print(f"❌ Error: HTTP {response.status}")
                    print(await response.text())
                    
        except Exception as e:
            print(f"❌ Exception: {str(e)}")

        # Also check latest signals
        print(f"\n📈 Getting Latest EURUSD Signals...")
        try:
            async with session.get(f"{BASE_URL}/users/{TEST_USER_ID}/signals/latest?asset=EURUSD") as response:
                if response.status == 200:
                    data = await response.json()
                    print("Latest EURUSD signal:")
                    pprint(data, width=80)
        except Exception as e:
            print(f"Error getting latest signals: {e}")

if __name__ == "__main__":
    asyncio.run(detailed_signal_test())