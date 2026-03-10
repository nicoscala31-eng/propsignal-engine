#!/usr/bin/env python3
"""
PropSignal Engine Backend Testing
Testing all NEW endpoints as specified in the review request
"""
import requests
import json
import time
from datetime import datetime
import logging

# Configure logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

# Backend URL - Use the environment variable from frontend/.env
BACKEND_URL = "https://eurusd-alerts.preview.emergentagent.com"
BASE_API_URL = f"{BACKEND_URL}/api"

class PropSignalTester:
    def __init__(self, base_url):
        self.base_url = base_url
        self.session = requests.Session()
        self.session.headers.update({
            'Content-Type': 'application/json',
            'Accept': 'application/json'
        })
        self.test_results = []
        self.errors = []

    def log_test(self, test_name, success, response_data=None, error=None):
        """Log test results"""
        result = {
            'test': test_name,
            'success': success,
            'timestamp': datetime.now().isoformat(),
            'response': response_data,
            'error': error
        }
        self.test_results.append(result)
        
        if success:
            logger.info(f"✅ {test_name}: PASSED")
        else:
            logger.error(f"❌ {test_name}: FAILED - {error}")
            self.errors.append(f"{test_name}: {error}")

    def test_device_registration(self):
        """Test device registration endpoints"""
        logger.info("\n=== 1. DEVICE REGISTRATION TESTS ===")
        
        # Test POST /api/register-device
        device_data = {
            "push_token": "ExpoTestToken123456",
            "platform": "ios", 
            "device_id": "test_device_001",
            "device_name": "Test iPhone"
        }
        
        try:
            response = self.session.post(f"{self.base_url}/register-device", json=device_data)
            if response.status_code == 200:
                data = response.json()
                expected_keys = ["status", "device_id"]
                if all(key in data for key in expected_keys):
                    self.log_test("Device Registration - POST /register-device", True, data)
                else:
                    self.log_test("Device Registration - POST /register-device", False, 
                                error=f"Missing expected keys in response: {data}")
            else:
                self.log_test("Device Registration - POST /register-device", False, 
                            error=f"HTTP {response.status_code}: {response.text}")
        except Exception as e:
            self.log_test("Device Registration - POST /register-device", False, error=str(e))

        # Test GET /api/devices/count
        try:
            response = self.session.get(f"{self.base_url}/devices/count")
            if response.status_code == 200:
                data = response.json()
                expected_keys = ["total_devices", "active_devices"]
                if all(key in data for key in expected_keys):
                    self.log_test("Device Count - GET /devices/count", True, data)
                else:
                    self.log_test("Device Count - GET /devices/count", False,
                                error=f"Missing expected keys in response: {data}")
            else:
                self.log_test("Device Count - GET /devices/count", False,
                            error=f"HTTP {response.status_code}: {response.text}")
        except Exception as e:
            self.log_test("Device Count - GET /devices/count", False, error=str(e))

    def test_market_scanner_control(self):
        """Test market scanner control endpoints"""
        logger.info("\n=== 2. MARKET SCANNER CONTROL TESTS ===")
        
        # Test GET /api/scanner/status 
        try:
            response = self.session.get(f"{self.base_url}/scanner/status")
            if response.status_code == 200:
                data = response.json()
                expected_keys = ["is_running", "active_profile", "statistics"]
                if all(key in data for key in expected_keys):
                    self.log_test("Scanner Status - GET /scanner/status", True, data)
                    
                    # Store initial profile for verification
                    initial_profile = data.get("active_profile")
                    
                else:
                    self.log_test("Scanner Status - GET /scanner/status", False,
                                error=f"Missing expected keys in response: {data}")
            else:
                self.log_test("Scanner Status - GET /scanner/status", False,
                            error=f"HTTP {response.status_code}: {response.text}")
        except Exception as e:
            self.log_test("Scanner Status - GET /scanner/status", False, error=str(e))

        # Test POST /api/scanner/profile/aggressive
        try:
            response = self.session.post(f"{self.base_url}/scanner/profile/aggressive")
            if response.status_code == 200:
                data = response.json()
                expected_keys = ["status", "new_profile"]
                if all(key in data for key in expected_keys):
                    if data.get("new_profile") == "Aggressive":
                        self.log_test("Scanner Profile Change - POST /scanner/profile/aggressive", True, data)
                    else:
                        self.log_test("Scanner Profile Change - POST /scanner/profile/aggressive", False,
                                    error=f"Profile not changed to Aggressive: {data}")
                else:
                    self.log_test("Scanner Profile Change - POST /scanner/profile/aggressive", False,
                                error=f"Missing expected keys in response: {data}")
            else:
                self.log_test("Scanner Profile Change - POST /scanner/profile/aggressive", False,
                            error=f"HTTP {response.status_code}: {response.text}")
        except Exception as e:
            self.log_test("Scanner Profile Change - POST /scanner/profile/aggressive", False, error=str(e))

        # Verify profile changed to "Aggressive"
        try:
            response = self.session.get(f"{self.base_url}/scanner/status")
            if response.status_code == 200:
                data = response.json()
                if data.get("active_profile") == "Aggressive":
                    self.log_test("Scanner Status Verification - Profile is Aggressive", True, data)
                else:
                    self.log_test("Scanner Status Verification - Profile is Aggressive", False,
                                error=f"Profile not changed to Aggressive: {data.get('active_profile')}")
            else:
                self.log_test("Scanner Status Verification - Profile is Aggressive", False,
                            error=f"HTTP {response.status_code}: {response.text}")
        except Exception as e:
            self.log_test("Scanner Status Verification - Profile is Aggressive", False, error=str(e))

        # Test POST /api/scanner/profile/prop_firm_safe (reset to safe profile)
        try:
            response = self.session.post(f"{self.base_url}/scanner/profile/prop_firm_safe")
            if response.status_code == 200:
                data = response.json()
                expected_keys = ["status", "new_profile"]
                if all(key in data for key in expected_keys):
                    if data.get("new_profile") == "Prop Firm Safe":
                        self.log_test("Scanner Profile Reset - POST /scanner/profile/prop_firm_safe", True, data)
                    else:
                        self.log_test("Scanner Profile Reset - POST /scanner/profile/prop_firm_safe", False,
                                    error=f"Profile not changed to Prop Firm Safe: {data}")
                else:
                    self.log_test("Scanner Profile Reset - POST /scanner/profile/prop_firm_safe", False,
                                error=f"Missing expected keys in response: {data}")
            else:
                self.log_test("Scanner Profile Reset - POST /scanner/profile/prop_firm_safe", False,
                            error=f"HTTP {response.status_code}: {response.text}")
        except Exception as e:
            self.log_test("Scanner Profile Reset - POST /scanner/profile/prop_firm_safe", False, error=str(e))

    def test_analytics_endpoints(self):
        """Test analytics endpoints"""
        logger.info("\n=== 3. ANALYTICS ENDPOINTS TESTS ===")
        
        # Test GET /api/analytics/performance
        try:
            response = self.session.get(f"{self.base_url}/analytics/performance")
            if response.status_code == 200:
                data = response.json()
                expected_top_keys = ["summary", "performance", "risk_metrics", "streaks", "activity"]
                if all(key in data for key in expected_top_keys):
                    # Check sub-keys
                    summary_keys = ["total_signals", "buy_signals", "sell_signals", "next_signals"]
                    performance_keys = ["win_rate", "loss_rate", "winning_trades", "losing_trades", "pending_trades"]
                    risk_keys = ["average_rr_ratio", "profit_factor", "expectancy"]
                    
                    if (all(key in data["summary"] for key in summary_keys) and
                        all(key in data["performance"] for key in performance_keys) and 
                        all(key in data["risk_metrics"] for key in risk_keys)):
                        self.log_test("Analytics Performance - GET /analytics/performance", True, data)
                    else:
                        self.log_test("Analytics Performance - GET /analytics/performance", False,
                                    error=f"Missing expected sub-keys in response")
                else:
                    self.log_test("Analytics Performance - GET /analytics/performance", False,
                                error=f"Missing expected keys in response: {list(data.keys())}")
            else:
                self.log_test("Analytics Performance - GET /analytics/performance", False,
                            error=f"HTTP {response.status_code}: {response.text}")
        except Exception as e:
            self.log_test("Analytics Performance - GET /analytics/performance", False, error=str(e))

        # Test GET /api/analytics/distribution?days=7
        try:
            response = self.session.get(f"{self.base_url}/analytics/distribution?days=7")
            if response.status_code == 200:
                data = response.json()
                expected_keys = ["period_days", "start_date", "end_date", "daily_distribution"]
                if all(key in data for key in expected_keys):
                    if data.get("period_days") == 7:
                        self.log_test("Analytics Distribution - GET /analytics/distribution?days=7", True, data)
                    else:
                        self.log_test("Analytics Distribution - GET /analytics/distribution?days=7", False,
                                    error=f"Period days incorrect: {data.get('period_days')}")
                else:
                    self.log_test("Analytics Distribution - GET /analytics/distribution?days=7", False,
                                error=f"Missing expected keys in response: {list(data.keys())}")
            else:
                self.log_test("Analytics Distribution - GET /analytics/distribution?days=7", False,
                            error=f"HTTP {response.status_code}: {response.text}")
        except Exception as e:
            self.log_test("Analytics Distribution - GET /analytics/distribution?days=7", False, error=str(e))

        # Test GET /api/analytics/recent-trades?limit=5
        try:
            response = self.session.get(f"{self.base_url}/analytics/recent-trades?limit=5")
            if response.status_code == 200:
                data = response.json()
                if isinstance(data, list):
                    # Check if we have data and it has correct structure
                    if len(data) <= 5:  # Should respect limit
                        if len(data) > 0:
                            # Check structure of first item
                            expected_trade_keys = ["id", "asset", "signal_type", "confidence", "outcome"]
                            if all(key in data[0] for key in expected_trade_keys):
                                self.log_test("Analytics Recent Trades - GET /analytics/recent-trades?limit=5", True, data)
                            else:
                                self.log_test("Analytics Recent Trades - GET /analytics/recent-trades?limit=5", False,
                                            error=f"Missing expected keys in trade data: {list(data[0].keys())}")
                        else:
                            # Empty array is valid (no trades yet)
                            self.log_test("Analytics Recent Trades - GET /analytics/recent-trades?limit=5", True, data)
                    else:
                        self.log_test("Analytics Recent Trades - GET /analytics/recent-trades?limit=5", False,
                                    error=f"Response exceeds limit of 5: {len(data)} items")
                else:
                    self.log_test("Analytics Recent Trades - GET /analytics/recent-trades?limit=5", False,
                                error=f"Response is not a list: {type(data)}")
            else:
                self.log_test("Analytics Recent Trades - GET /analytics/recent-trades?limit=5", False,
                            error=f"HTTP {response.status_code}: {response.text}")
        except Exception as e:
            self.log_test("Analytics Recent Trades - GET /analytics/recent-trades?limit=5", False, error=str(e))

    def test_push_notification_stats(self):
        """Test push notification stats"""
        logger.info("\n=== 4. PUSH NOTIFICATION STATS TESTS ===")
        
        # Test GET /api/push/stats
        try:
            response = self.session.get(f"{self.base_url}/push/stats")
            if response.status_code == 200:
                data = response.json()
                expected_keys = ["sent", "failed", "total"]
                if all(key in data for key in expected_keys):
                    # Verify total = sent + failed
                    if data["total"] == data["sent"] + data["failed"]:
                        self.log_test("Push Stats - GET /push/stats", True, data)
                    else:
                        self.log_test("Push Stats - GET /push/stats", False,
                                    error=f"Total doesn't match sent+failed: {data}")
                else:
                    self.log_test("Push Stats - GET /push/stats", False,
                                error=f"Missing expected keys in response: {list(data.keys())}")
            else:
                self.log_test("Push Stats - GET /push/stats", False,
                            error=f"HTTP {response.status_code}: {response.text}")
        except Exception as e:
            self.log_test("Push Stats - GET /push/stats", False, error=str(e))

    def test_existing_endpoints(self):
        """Test existing endpoints to verify they still work"""
        logger.info("\n=== 5. EXISTING ENDPOINTS VERIFICATION ===")
        
        # Test GET /api/provider/live-prices
        try:
            response = self.session.get(f"{self.base_url}/provider/live-prices")
            if response.status_code == 200:
                data = response.json()
                expected_keys = ["provider", "is_production", "timestamp", "prices"]
                if all(key in data for key in expected_keys):
                    # Check if prices have EURUSD and XAUUSD
                    prices = data.get("prices", {})
                    if "EURUSD" in prices and "XAUUSD" in prices:
                        # Check price structure
                        eurusd = prices["EURUSD"]
                        if "bid" in eurusd and "ask" in eurusd and "status" in eurusd:
                            self.log_test("Live Prices - GET /provider/live-prices", True, data)
                        else:
                            self.log_test("Live Prices - GET /provider/live-prices", False,
                                        error=f"Missing price structure: {eurusd}")
                    else:
                        self.log_test("Live Prices - GET /provider/live-prices", False,
                                    error=f"Missing EURUSD/XAUUSD in prices: {list(prices.keys())}")
                else:
                    self.log_test("Live Prices - GET /provider/live-prices", False,
                                error=f"Missing expected keys in response: {list(data.keys())}")
            else:
                self.log_test("Live Prices - GET /provider/live-prices", False,
                            error=f"HTTP {response.status_code}: {response.text}")
        except Exception as e:
            self.log_test("Live Prices - GET /provider/live-prices", False, error=str(e))

        # Test GET /api/provider/debug
        try:
            response = self.session.get(f"{self.base_url}/provider/debug")
            if response.status_code == 200:
                data = response.json()
                expected_keys = ["timestamp", "api_key", "provider", "connection"]
                if all(key in data for key in expected_keys):
                    # Check sub-structure
                    provider_info = data.get("provider", {})
                    connection_info = data.get("connection", {})
                    if "is_production" in provider_info and "is_connected" in connection_info:
                        self.log_test("Provider Debug - GET /provider/debug", True, data)
                    else:
                        self.log_test("Provider Debug - GET /provider/debug", False,
                                    error=f"Missing sub-keys in provider/connection data")
                else:
                    self.log_test("Provider Debug - GET /provider/debug", False,
                                error=f"Missing expected keys in response: {list(data.keys())}")
            else:
                self.log_test("Provider Debug - GET /provider/debug", False,
                            error=f"HTTP {response.status_code}: {response.text}")
        except Exception as e:
            self.log_test("Provider Debug - GET /provider/debug", False, error=str(e))

    def run_all_tests(self):
        """Run all tests"""
        logger.info(f"🚀 Starting PropSignal Engine Backend Tests")
        logger.info(f"📍 Backend URL: {self.base_url}")
        
        start_time = time.time()
        
        # Run all test suites
        self.test_device_registration()
        self.test_market_scanner_control()  
        self.test_analytics_endpoints()
        self.test_push_notification_stats()
        self.test_existing_endpoints()
        
        end_time = time.time()
        duration = round(end_time - start_time, 2)
        
        # Summary
        total_tests = len(self.test_results)
        passed_tests = sum(1 for result in self.test_results if result['success'])
        failed_tests = total_tests - passed_tests
        
        logger.info(f"\n{'='*60}")
        logger.info(f"🏁 PROPNIGNAL ENGINE BACKEND TEST SUMMARY")
        logger.info(f"{'='*60}")
        logger.info(f"⏱️  Duration: {duration}s")
        logger.info(f"📊 Total Tests: {total_tests}")
        logger.info(f"✅ Passed: {passed_tests}")
        logger.info(f"❌ Failed: {failed_tests}")
        logger.info(f"🎯 Success Rate: {(passed_tests/total_tests)*100:.1f}%")
        
        if self.errors:
            logger.info(f"\n❌ FAILED TESTS:")
            for i, error in enumerate(self.errors, 1):
                logger.info(f"  {i}. {error}")
        else:
            logger.info(f"\n🎉 ALL TESTS PASSED!")
            
        return passed_tests == total_tests

if __name__ == "__main__":
    tester = PropSignalTester(BASE_API_URL)
    success = tester.run_all_tests()
    exit(0 if success else 1)