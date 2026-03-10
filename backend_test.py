#!/usr/bin/env python3
"""
PropSignal Engine Backend Testing Suite
Focus: Live Market Data Connection and Signal Generation
"""

import asyncio
import aiohttp
import json
from datetime import datetime
from typing import Dict, Any, Optional

# Test Configuration
BASE_URL = "https://eurusd-alerts.preview.emergentagent.com/api"
TEST_USER_ID = "1773156899.291813"  
TEST_PROP_PROFILE_ID = "1773156903.940538"

class PropSignalTester:
    def __init__(self):
        self.session: Optional[aiohttp.ClientSession] = None
        self.test_results = []
        
    async def __aenter__(self):
        self.session = aiohttp.ClientSession()
        return self
        
    async def __aexit__(self, exc_type, exc_val, exc_tb):
        if self.session:
            await self.session.close()
    
    def log_test(self, test_name: str, success: bool, details: str, data: Dict = None):
        """Log test results"""
        result = {
            "test": test_name,
            "success": success,
            "details": details,
            "timestamp": datetime.now().isoformat(),
            "data": data
        }
        self.test_results.append(result)
        status = "✅ PASS" if success else "❌ FAIL"
        print(f"{status} {test_name}: {details}")
        
    async def test_health_check(self):
        """Test basic health endpoint"""
        try:
            async with self.session.get(f"{BASE_URL}/health") as response:
                if response.status == 200:
                    data = await response.json()
                    self.log_test("Health Check", True, "Backend is healthy", data)
                    return True
                else:
                    self.log_test("Health Check", False, f"HTTP {response.status}")
                    return False
        except Exception as e:
            self.log_test("Health Check", False, f"Connection error: {str(e)}")
            return False

    async def test_provider_debug(self):
        """Test /api/provider/debug endpoint - CRITICAL TEST"""
        try:
            async with self.session.get(f"{BASE_URL}/provider/debug") as response:
                if response.status == 200:
                    data = await response.json()
                    
                    # Check API key status
                    api_key_loaded = data.get("api_key", {}).get("status") == "LOADED"
                    
                    # Check provider status
                    provider_info = data.get("provider", {})
                    is_production = provider_info.get("is_production", False)
                    
                    # Check connection status
                    connection_info = data.get("connection", {})
                    is_connected = connection_info.get("is_connected", False)
                    provider_name = connection_info.get("provider_name", "Unknown")
                    
                    success = api_key_loaded and is_production and is_connected
                    details = f"API Key: {data.get('api_key', {}).get('status')}, Provider: {provider_name}, Production: {is_production}, Connected: {is_connected}"
                    
                    self.log_test("Provider Debug Info", success, details, data)
                    return success, data
                else:
                    self.log_test("Provider Debug Info", False, f"HTTP {response.status}")
                    return False, None
        except Exception as e:
            self.log_test("Provider Debug Info", False, f"Error: {str(e)}")
            return False, None

    async def test_provider_status(self):
        """Test /api/provider/status endpoint"""
        try:
            async with self.session.get(f"{BASE_URL}/provider/status") as response:
                if response.status == 200:
                    data = await response.json()
                    
                    connected = data.get("connected", False)
                    is_production = data.get("is_production", False)
                    provider_name = data.get("provider_name", "Unknown")
                    
                    success = connected and is_production
                    details = f"Connected: {connected}, Production: {is_production}, Provider: {provider_name}"
                    
                    self.log_test("Provider Status", success, details, data)
                    return success, data
                else:
                    self.log_test("Provider Status", False, f"HTTP {response.status}")
                    return False, None
        except Exception as e:
            self.log_test("Provider Status", False, f"Error: {str(e)}")
            return False, None

    async def test_live_prices(self):
        """Test /api/provider/live-prices endpoint - CRITICAL TEST"""
        try:
            async with self.session.get(f"{BASE_URL}/provider/live-prices") as response:
                if response.status == 200:
                    data = await response.json()
                    
                    eurusd_data = data.get("prices", {}).get("EURUSD", {})
                    xauusd_data = data.get("prices", {}).get("XAUUSD", {})
                    
                    # Check EURUSD
                    eurusd_status = eurusd_data.get("status") == "LIVE"
                    eurusd_bid = eurusd_data.get("bid")
                    eurusd_ask = eurusd_data.get("ask")
                    eurusd_realistic = False
                    
                    if eurusd_bid and eurusd_ask:
                        # Check if EURUSD price is realistic (~1.165xx)
                        eurusd_realistic = 1.10 <= float(eurusd_bid) <= 1.25 and 1.10 <= float(eurusd_ask) <= 1.25
                    
                    # Check XAUUSD
                    xauusd_status = xauusd_data.get("status") == "LIVE"
                    xauusd_bid = xauusd_data.get("bid")
                    xauusd_ask = xauusd_data.get("ask")
                    xauusd_realistic = False
                    
                    if xauusd_bid and xauusd_ask:
                        # Check if XAUUSD price is realistic (~5228-5230)
                        xauusd_realistic = 2500 <= float(xauusd_bid) <= 6000 and 2500 <= float(xauusd_ask) <= 6000
                    
                    # Check provider info
                    provider_name = data.get("provider", "Unknown")
                    is_production = data.get("is_production", False)
                    
                    success = (eurusd_status and eurusd_realistic and 
                              xauusd_status and xauusd_realistic and 
                              provider_name == "Twelve Data" and is_production)
                    
                    details = f"EURUSD: {eurusd_bid}/{eurusd_ask} ({eurusd_status}), XAUUSD: {xauusd_bid}/{xauusd_ask} ({xauusd_status}), Provider: {provider_name}"
                    
                    self.log_test("Live Prices", success, details, data)
                    return success, data
                else:
                    self.log_test("Live Prices", False, f"HTTP {response.status}")
                    return False, None
        except Exception as e:
            self.log_test("Live Prices", False, f"Error: {str(e)}")
            return False, None

    async def test_signal_generation(self, asset: str):
        """Test signal generation with live data"""
        try:
            payload = {
                "asset": asset,
                "prop_profile_id": TEST_PROP_PROFILE_ID
            }
            
            async with self.session.post(
                f"{BASE_URL}/users/{TEST_USER_ID}/signals/generate",
                json=payload,
                headers={"Content-Type": "application/json"}
            ) as response:
                
                if response.status == 200:
                    data = await response.json()
                    
                    # Check required live data fields
                    live_bid = data.get("live_bid")
                    live_ask = data.get("live_ask") 
                    live_spread_pips = data.get("live_spread_pips")
                    data_provider = data.get("data_provider")
                    
                    # Check signal quality
                    signal_type = data.get("signal_type")
                    confidence = data.get("confidence")
                    success_probability = data.get("success_probability")
                    
                    has_live_data = all([live_bid, live_ask, live_spread_pips])
                    is_twelve_data = data_provider == "Twelve Data"
                    has_signal_data = all([signal_type, confidence, success_probability])
                    
                    success = has_live_data and is_twelve_data and has_signal_data
                    
                    details = f"Signal: {signal_type}, Confidence: {confidence}%, Live: {live_bid}/{live_ask}, Provider: {data_provider}"
                    
                    self.log_test(f"Signal Generation ({asset})", success, details, data)
                    return success, data
                else:
                    error_text = await response.text()
                    self.log_test(f"Signal Generation ({asset})", False, f"HTTP {response.status}: {error_text}")
                    return False, None
        except Exception as e:
            self.log_test(f"Signal Generation ({asset})", False, f"Error: {str(e)}")
            return False, None

    async def run_all_tests(self):
        """Run comprehensive backend tests"""
        print("🚀 PropSignal Engine Backend Testing Suite")
        print("=" * 60)
        
        # Test 1: Health Check
        await self.test_health_check()
        
        # Test 2: Provider Debug (CRITICAL)
        debug_success, debug_data = await self.test_provider_debug()
        
        # Test 3: Provider Status
        status_success, status_data = await self.test_provider_status()
        
        # Test 4: Live Prices (CRITICAL)
        prices_success, prices_data = await self.test_live_prices()
        
        # Test 5: Signal Generation with Live Data (CRITICAL)
        eurusd_signal_success, eurusd_signal_data = await self.test_signal_generation("EURUSD")
        
        # Test 6: Signal Generation for XAUUSD (CRITICAL)
        xauusd_signal_success, xauusd_signal_data = await self.test_signal_generation("XAUUSD")
        
        # Summary
        print("\n" + "=" * 60)
        print("📊 TEST SUMMARY")
        print("=" * 60)
        
        total_tests = len(self.test_results)
        passed_tests = sum(1 for result in self.test_results if result["success"])
        
        print(f"Total Tests: {total_tests}")
        print(f"Passed: {passed_tests}")
        print(f"Failed: {total_tests - passed_tests}")
        print(f"Success Rate: {(passed_tests/total_tests)*100:.1f}%")
        
        # Critical test results
        critical_tests = [
            ("Provider Debug", debug_success),
            ("Live Prices", prices_success), 
            ("EURUSD Signal Generation", eurusd_signal_success),
            ("XAUUSD Signal Generation", xauusd_signal_success)
        ]
        
        print("\n🎯 CRITICAL TEST RESULTS:")
        for test_name, success in critical_tests:
            status = "✅ PASS" if success else "❌ FAIL"
            print(f"  {status} {test_name}")
        
        # Failed tests details
        failed_tests = [result for result in self.test_results if not result["success"]]
        if failed_tests:
            print("\n❌ FAILED TESTS DETAILS:")
            for test in failed_tests:
                print(f"  • {test['test']}: {test['details']}")
        
        return self.test_results

async def main():
    """Main test execution"""
    async with PropSignalTester() as tester:
        await tester.run_all_tests()

if __name__ == "__main__":
    asyncio.run(main())