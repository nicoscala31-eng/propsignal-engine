#!/usr/bin/env python3
"""
Production Safety Cleanup Testing Script
=========================================

This script tests the NEW Production Safety Cleanup implementation for the trading signal system.

Focus Areas:
1. Production Control Status
2. Scanner Control Endpoints  
3. Notifications Control Endpoints
4. Audit Log
5. Signal Generator v3 Status
6. Legacy Scanners are Blocked
7. Existing Endpoints Still Work
"""

import requests
import json
import time
from datetime import datetime
from typing import Dict, List, Optional

# Backend URL from environment
BACKEND_URL = "https://eurusd-alerts.preview.emergentagent.com/api"

class ProductionSafetyTester:
    def __init__(self, base_url: str):
        self.base_url = base_url.rstrip('/')
        self.test_results = []
        
    def log_test(self, test_name: str, success: bool, message: str, data: Optional[Dict] = None):
        """Log test result"""
        result = {
            "test": test_name,
            "success": success,
            "message": message,
            "timestamp": datetime.utcnow().isoformat(),
            "data": data
        }
        self.test_results.append(result)
        
        status = "✅" if success else "❌"
        print(f"{status} {test_name}: {message}")
        if data and not success:
            print(f"   Data: {json.dumps(data, indent=2)}")
    
    def make_request(self, method: str, endpoint: str, **kwargs) -> tuple[bool, Dict]:
        """Make HTTP request and return (success, response_data)"""
        url = f"{self.base_url}{endpoint}"
        
        try:
            response = requests.request(method, url, timeout=10, **kwargs)
            
            # Try to parse JSON, fallback to text
            try:
                data = response.json()
            except:
                data = {"text": response.text, "status_code": response.status_code}
            
            if response.status_code == 200:
                return True, data
            else:
                return False, data
                
        except requests.RequestException as e:
            return False, {"error": str(e), "type": "connection_error"}
    
    # ==================== CORE TESTS ====================
    
    def test_production_status(self):
        """Test GET /api/production/status"""
        success, data = self.make_request("GET", "/production/status")
        
        if not success:
            self.log_test("Production Status", False, f"Request failed: {data}", data)
            return False
        
        # Validate structure
        required_keys = ["scanner", "notifications", "engine", "initialized"]
        missing_keys = [k for k in required_keys if k not in data]
        
        if missing_keys:
            self.log_test("Production Status", False, f"Missing keys: {missing_keys}", data)
            return False
        
        # Check scanner structure
        scanner = data.get("scanner", {})
        if "enabled" not in scanner:
            self.log_test("Production Status", False, "Scanner missing 'enabled' field", data)
            return False
        
        # Check notifications structure
        notifications = data.get("notifications", {})
        if "enabled" not in notifications:
            self.log_test("Production Status", False, "Notifications missing 'enabled' field", data)
            return False
        
        # Check engine structure
        engine = data.get("engine", {})
        expected_auth = "signal_generator_v3"
        expected_blocked = ["advanced_scanner_v2", "signal_orchestrator", "market_scanner_legacy"]
        
        if engine.get("authorized") != expected_auth:
            self.log_test("Production Status", False, f"Wrong authorized engine: expected {expected_auth}, got {engine.get('authorized')}", data)
            return False
        
        blocked = engine.get("blocked", [])
        missing_blocked = [e for e in expected_blocked if e not in blocked]
        if missing_blocked:
            self.log_test("Production Status", False, f"Missing blocked engines: {missing_blocked}", data)
            return False
        
        self.log_test("Production Status", True, "All production status fields validated", {
            "scanner_enabled": scanner.get("enabled"),
            "notifications_enabled": notifications.get("enabled"),
            "authorized_engine": engine.get("authorized"),
            "blocked_engines": blocked
        })
        
        return True
    
    def test_scanner_disable_enable(self):
        """Test Scanner Control Endpoints"""
        
        # First, get current status
        success, initial_data = self.make_request("GET", "/production/status")
        if not success:
            self.log_test("Scanner Control - Initial Status", False, "Failed to get initial status", initial_data)
            return False
        
        initial_state = initial_data.get("scanner", {}).get("enabled")
        
        # Test disable
        success, disable_data = self.make_request("POST", "/production/scanner/disable")
        if not success:
            self.log_test("Scanner Disable", False, "Disable request failed", disable_data)
            return False
        
        self.log_test("Scanner Disable", True, "Scanner disable command executed", disable_data)
        
        # Check status after disable
        success, status_data = self.make_request("GET", "/production/status")
        if not success:
            self.log_test("Scanner Status After Disable", False, "Status check failed", status_data)
            return False
        
        if status_data.get("scanner", {}).get("enabled") != False:
            self.log_test("Scanner Status After Disable", False, "Scanner not disabled in status", status_data)
            return False
        
        self.log_test("Scanner Status After Disable", True, "Scanner correctly shows disabled", {
            "enabled": status_data.get("scanner", {}).get("enabled")
        })
        
        # Test enable
        success, enable_data = self.make_request("POST", "/production/scanner/enable")
        if not success:
            self.log_test("Scanner Enable", False, "Enable request failed", enable_data)
            return False
        
        self.log_test("Scanner Enable", True, "Scanner enable command executed", enable_data)
        
        # Check status after enable
        success, final_status_data = self.make_request("GET", "/production/status")
        if not success:
            self.log_test("Scanner Status After Enable", False, "Final status check failed", final_status_data)
            return False
        
        if final_status_data.get("scanner", {}).get("enabled") != True:
            self.log_test("Scanner Status After Enable", False, "Scanner not enabled in status", final_status_data)
            return False
        
        self.log_test("Scanner Status After Enable", True, "Scanner correctly shows enabled", {
            "enabled": final_status_data.get("scanner", {}).get("enabled")
        })
        
        return True
    
    def test_notifications_disable_enable(self):
        """Test Notifications Control Endpoints"""
        
        # First, get current status
        success, initial_data = self.make_request("GET", "/production/status")
        if not success:
            self.log_test("Notifications Control - Initial Status", False, "Failed to get initial status", initial_data)
            return False
        
        initial_state = initial_data.get("notifications", {}).get("enabled")
        
        # Test disable
        success, disable_data = self.make_request("POST", "/production/notifications/disable")
        if not success:
            self.log_test("Notifications Disable", False, "Disable request failed", disable_data)
            return False
        
        self.log_test("Notifications Disable", True, "Notifications disable command executed", disable_data)
        
        # Check status after disable
        success, status_data = self.make_request("GET", "/production/status")
        if not success:
            self.log_test("Notifications Status After Disable", False, "Status check failed", status_data)
            return False
        
        if status_data.get("notifications", {}).get("enabled") != False:
            self.log_test("Notifications Status After Disable", False, "Notifications not disabled in status", status_data)
            return False
        
        self.log_test("Notifications Status After Disable", True, "Notifications correctly shows disabled", {
            "enabled": status_data.get("notifications", {}).get("enabled")
        })
        
        # Test enable
        success, enable_data = self.make_request("POST", "/production/notifications/enable")
        if not success:
            self.log_test("Notifications Enable", False, "Enable request failed", enable_data)
            return False
        
        self.log_test("Notifications Enable", True, "Notifications enable command executed", enable_data)
        
        # Check status after enable
        success, final_status_data = self.make_request("GET", "/production/status")
        if not success:
            self.log_test("Notifications Status After Enable", False, "Final status check failed", final_status_data)
            return False
        
        if final_status_data.get("notifications", {}).get("enabled") != True:
            self.log_test("Notifications Status After Enable", False, "Notifications not enabled in status", final_status_data)
            return False
        
        self.log_test("Notifications Status After Enable", True, "Notifications correctly shows enabled", {
            "enabled": final_status_data.get("notifications", {}).get("enabled")
        })
        
        return True
    
    def test_audit_log(self):
        """Test GET /api/production/audit"""
        success, data = self.make_request("GET", "/production/audit")
        
        if not success:
            self.log_test("Production Audit Log", False, f"Request failed: {data}", data)
            return False
        
        # Check structure
        if "audit_log" not in data:
            self.log_test("Production Audit Log", False, "Missing audit_log field", data)
            return False
        
        audit_log = data["audit_log"]
        
        if not isinstance(audit_log, list):
            self.log_test("Production Audit Log", False, "audit_log is not a list", data)
            return False
        
        # Check for recent state changes or blocked attempts
        entries_found = len(audit_log)
        
        # Look for startup blocks
        startup_blocks = [entry for entry in audit_log 
                         if entry.get("event_type") in ["GUARD_BLOCK", "GUARD_ALLOW"]]
        
        self.log_test("Production Audit Log", True, f"Audit log retrieved with {entries_found} entries, {len(startup_blocks)} startup events", {
            "total_entries": entries_found,
            "startup_blocks": len(startup_blocks),
            "recent_entries": audit_log[-3:] if audit_log else []
        })
        
        return True
    
    def test_signal_generator_v3_status(self):
        """Test GET /api/scanner/v3/status"""
        success, data = self.make_request("GET", "/scanner/v3/status")
        
        if not success:
            self.log_test("Signal Generator v3 Status", False, f"Request failed: {data}", data)
            return False
        
        # Check if it's running
        is_running = data.get("is_running")
        
        if is_running != True:
            self.log_test("Signal Generator v3 Status", False, f"Signal Generator v3 not running: {is_running}", data)
            return False
        
        # Validate structure
        expected_fields = ["version", "mode", "is_running", "min_confidence_threshold", "statistics"]
        missing_fields = [f for f in expected_fields if f not in data]
        
        if missing_fields:
            self.log_test("Signal Generator v3 Status", False, f"Missing fields: {missing_fields}", data)
            return False
        
        self.log_test("Signal Generator v3 Status", True, "Signal Generator v3 is running and all fields present", {
            "is_running": data.get("is_running"),
            "version": data.get("version"),
            "mode": data.get("mode"),
            "min_confidence_threshold": data.get("min_confidence_threshold"),
            "statistics": data.get("statistics")
        })
        
        return True
    
    def test_legacy_scanners_blocked(self):
        """Test that legacy scanners are properly blocked"""
        
        # Test legacy scanner status - should NOT be running or return error
        success, legacy_data = self.make_request("GET", "/scanner/status")
        
        if success:
            # If it returns, check if it shows not running or error
            is_running = legacy_data.get("is_running")
            if is_running == True:
                self.log_test("Legacy Scanner Blocked", False, "Legacy scanner is still running", legacy_data)
                return False
            else:
                self.log_test("Legacy Scanner Status", True, "Legacy scanner not running", {
                    "is_running": is_running,
                    "message": "Scanner correctly not running"
                })
        else:
            # Error response is acceptable - scanner is blocked
            self.log_test("Legacy Scanner Status", True, "Legacy scanner blocked/error (expected)", legacy_data)
        
        # Test advanced scanner v2 status - should NOT be running  
        success, adv_data = self.make_request("GET", "/scanner/v2/status")
        
        if success:
            # If it returns, check if it shows not running or error
            is_running = adv_data.get("is_running")
            if is_running == True:
                self.log_test("Advanced Scanner v2 Blocked", False, "Advanced scanner v2 is still running", adv_data)
                return False
            else:
                self.log_test("Advanced Scanner v2 Status", True, "Advanced scanner v2 not running", {
                    "is_running": is_running,
                    "message": "Scanner correctly not running"
                })
        else:
            # Error response is acceptable - scanner is blocked
            self.log_test("Advanced Scanner v2 Status", True, "Advanced scanner v2 blocked/error (expected)", adv_data)
        
        return True
    
    def test_existing_endpoints_still_work(self):
        """Test that existing endpoints still work correctly"""
        
        # Test health endpoint
        success, health_data = self.make_request("GET", "/health")
        if not success:
            self.log_test("Health Endpoint", False, "Health check failed", health_data)
            return False
        
        self.log_test("Health Endpoint", True, "Health endpoint working", {
            "status": health_data.get("status"),
            "uptime_check": health_data.get("uptime_check")
        })
        
        # Test market validation status
        success, validation_data = self.make_request("GET", "/market/validation/status")
        if not success:
            self.log_test("Market Validation Status", False, "Market validation status failed", validation_data)
            return False
        
        self.log_test("Market Validation Status", True, "Market validation endpoint working", {
            "forex_status": validation_data.get("market_status", {}).get("forex_status"),
            "validations": validation_data.get("validation_statistics")
        })
        
        # Test provider live prices
        success, prices_data = self.make_request("GET", "/provider/live-prices")
        if not success:
            self.log_test("Provider Live Prices", False, "Provider live prices failed", prices_data)
            return False
        
        # Check if we have price data
        prices = prices_data.get("prices", {})
        eurusd = prices.get("EURUSD", {})
        xauusd = prices.get("XAUUSD", {})
        
        self.log_test("Provider Live Prices", True, "Provider live prices working", {
            "provider": prices_data.get("provider"),
            "is_production": prices_data.get("is_production"),
            "eurusd_status": eurusd.get("status"),
            "xauusd_status": xauusd.get("status")
        })
        
        return True
    
    def run_all_tests(self):
        """Run all production safety tests"""
        print("=" * 60)
        print("🛡️ PRODUCTION SAFETY CLEANUP TESTING")
        print("=" * 60)
        print(f"Backend URL: {self.base_url}")
        print(f"Test Started: {datetime.utcnow().isoformat()}")
        print()
        
        # Run all tests
        tests = [
            ("Production Status Check", self.test_production_status),
            ("Scanner Control", self.test_scanner_disable_enable), 
            ("Notifications Control", self.test_notifications_disable_enable),
            ("Audit Log", self.test_audit_log),
            ("Signal Generator v3", self.test_signal_generator_v3_status),
            ("Legacy Scanners Blocked", self.test_legacy_scanners_blocked),
            ("Existing Endpoints", self.test_existing_endpoints_still_work)
        ]
        
        passed = 0
        failed = 0
        
        for test_name, test_func in tests:
            print(f"\n🔍 Running: {test_name}")
            try:
                result = test_func()
                if result:
                    passed += 1
                else:
                    failed += 1
            except Exception as e:
                self.log_test(test_name, False, f"Test crashed: {str(e)}")
                failed += 1
                print(f"❌ {test_name}: CRASHED - {str(e)}")
        
        # Summary
        print("\n" + "=" * 60)
        print("📊 PRODUCTION SAFETY TEST SUMMARY")
        print("=" * 60)
        print(f"✅ Passed: {passed}")
        print(f"❌ Failed: {failed}")
        print(f"📝 Total: {len(tests)}")
        print(f"✨ Success Rate: {(passed / len(tests) * 100):.1f}%")
        
        if failed == 0:
            print("\n🎉 ALL PRODUCTION SAFETY TESTS PASSED!")
            print("✅ Production Safety Cleanup implementation is working correctly")
        else:
            print(f"\n⚠️  {failed} tests failed - review implementation")
        
        print("\n" + "=" * 60)
        return failed == 0


def main():
    tester = ProductionSafetyTester(BACKEND_URL)
    success = tester.run_all_tests()
    
    # Save detailed results
    with open('/app/production_safety_test_results.json', 'w') as f:
        json.dump({
            "test_summary": {
                "total_tests": len(tester.test_results),
                "passed": sum(1 for r in tester.test_results if r["success"]),
                "failed": sum(1 for r in tester.test_results if not r["success"]),
                "success_rate": sum(1 for r in tester.test_results if r["success"]) / len(tester.test_results) * 100,
                "test_timestamp": datetime.utcnow().isoformat()
            },
            "test_results": tester.test_results
        }, f, indent=2)
    
    return 0 if success else 1


if __name__ == "__main__":
    exit(main())