#!/usr/bin/env python3
"""
PropSignal Engine Backend API Test Suite
Push Notification Registration Flow Testing

This script tests the push notification registration endpoints specifically requested.
"""

import asyncio
import aiohttp
import json
import sys
from datetime import datetime
import uuid
import os

# Backend URL from frontend .env - use the production configured URL
BACKEND_URL = "https://eurusd-alerts.preview.emergentagent.com/api"

class Colors:
    """Terminal color codes for output formatting"""
    GREEN = '\033[92m'
    RED = '\033[91m'
    YELLOW = '\033[93m'
    BLUE = '\033[94m'
    PURPLE = '\033[95m'
    CYAN = '\033[96m'
    WHITE = '\033[97m'
    BOLD = '\033[1m'
    END = '\033[0m'

class PushNotificationTester:
    def __init__(self):
        self.session = None
        self.test_results = []
        self.device_id_1 = f"test_device_ios_{uuid.uuid4().hex[:8]}"
        self.device_id_2 = f"test_device_android_{uuid.uuid4().hex[:8]}"
        
    async def __aenter__(self):
        self.session = aiohttp.ClientSession(
            timeout=aiohttp.ClientTimeout(total=30),
            connector=aiohttp.TCPConnector(ssl=False)
        )
        return self
        
    async def __aexit__(self, exc_type, exc_val, exc_tb):
        if self.session:
            await self.session.close()
    
    def log_test_result(self, test_name: str, success: bool, details: str = ""):
        """Log a test result"""
        status = f"{Colors.GREEN}✅ PASS{Colors.END}" if success else f"{Colors.RED}❌ FAIL{Colors.END}"
        print(f"{status} {test_name}")
        if details:
            print(f"    {Colors.CYAN}→{Colors.END} {details}")
        
        self.test_results.append({
            "test": test_name,
            "success": success,
            "details": details,
            "timestamp": datetime.utcnow().isoformat()
        })
    
    async def make_request(self, method: str, endpoint: str, data=None, expected_status=200):
        """Make HTTP request with error handling"""
        url = f"{BACKEND_URL}{endpoint}"
        
        try:
            if method.upper() == "GET":
                async with self.session.get(url) as response:
                    response_data = await response.json()
                    return response.status, response_data
            elif method.upper() == "POST":
                headers = {"Content-Type": "application/json"} if data else None
                json_data = json.dumps(data) if data else None
                
                async with self.session.post(url, data=json_data, headers=headers) as response:
                    response_data = await response.json()
                    return response.status, response_data
                    
        except Exception as e:
            print(f"{Colors.RED}❌ Request Error{Colors.END}: {method} {endpoint}")
            print(f"    {Colors.RED}Error: {str(e)}{Colors.END}")
            return None, {"error": str(e)}
    
    async def test_health_check(self):
        """Test basic health check to verify backend connectivity"""
        print(f"\n{Colors.BOLD}{Colors.BLUE}=== HEALTH CHECK ==={Colors.END}")
        
        status, data = await self.make_request("GET", "/health")
        
        if status == 200:
            self.log_test_result("Health check endpoint", True, f"Status: {data.get('status', 'unknown')}")
            return True
        else:
            self.log_test_result("Health check endpoint", False, f"Status: {status}, Response: {data}")
            return False
    
    async def test_register_device_valid(self):
        """Test 1: Register a new device with valid data"""
        print(f"\n{Colors.BOLD}{Colors.BLUE}=== TEST 1: Register Device (Valid Data) ==={Colors.END}")
        
        device_data = {
            "push_token": "ExponentPushToken[xxxxxxxxxxxxxxxxxxxxxx]",
            "platform": "ios", 
            "device_id": self.device_id_1,
            "device_name": "iPhone 15 Pro"
        }
        
        status, data = await self.make_request("POST", "/register-device", device_data)
        
        if status == 200 and data.get("status") == "registered":
            self.log_test_result(
                "Register new iOS device", 
                True, 
                f"Device ID: {data.get('device_id')}, Status: {data.get('status')}"
            )
            return True
        else:
            self.log_test_result(
                "Register new iOS device", 
                False, 
                f"Status: {status}, Response: {data}"
            )
            return False
    
    async def test_register_device_update(self):
        """Test 2: Register same device again (should update, not duplicate)"""
        print(f"\n{Colors.BOLD}{Colors.BLUE}=== TEST 2: Register Device (Update Existing) ==={Colors.END}")
        
        device_data = {
            "push_token": "ExponentPushToken[yyyyyyyyyyyyyyyyyyyyyy]",  # Different token
            "platform": "ios",
            "device_id": self.device_id_1,  # Same device ID
            "device_name": "iPhone 15 Pro Max"  # Different name
        }
        
        status, data = await self.make_request("POST", "/register-device", device_data)
        
        if status == 200 and data.get("status") == "updated":
            self.log_test_result(
                "Update existing device", 
                True, 
                f"Device ID: {data.get('device_id')}, Status: {data.get('status')}"
            )
            return True
        else:
            self.log_test_result(
                "Update existing device", 
                False, 
                f"Status: {status}, Response: {data}"
            )
            return False
    
    async def test_register_missing_token(self):
        """Test 3: Try to register with missing push_token (should return 400 or 422)"""
        print(f"\n{Colors.BOLD}{Colors.BLUE}=== TEST 3: Register Device (Missing Token) ==={Colors.END}")
        
        device_data = {
            "platform": "android",
            "device_id": self.device_id_2,
            "device_name": "Samsung Galaxy S24"
            # Missing push_token
        }
        
        status, data = await self.make_request("POST", "/register-device", device_data)
        
        if status in [400, 422]:  # Accept both 400 and 422 as validation errors
            self.log_test_result(
                "Register without push_token (validation error)", 
                True, 
                f"Expected validation error received ({status}): {data.get('detail', 'No detail')}"
            )
            return True
        else:
            self.log_test_result(
                "Register without push_token (validation error)", 
                False, 
                f"Expected 400/422 but got {status}: {data}"
            )
            return False
    
    async def test_register_invalid_platform(self):
        """Test 4: Try to register with invalid platform (should return 400)"""
        print(f"\n{Colors.BOLD}{Colors.BLUE}=== TEST 4: Register Device (Invalid Platform) ==={Colors.END}")
        
        device_data = {
            "push_token": "ExponentPushToken[zzzzzzzzzzzzzzzzzzzzz]",
            "platform": "windows",  # Invalid platform
            "device_id": self.device_id_2,
            "device_name": "Windows Phone"
        }
        
        status, data = await self.make_request("POST", "/register-device", device_data)
        
        if status == 400:
            self.log_test_result(
                "Register with invalid platform (400 error)", 
                True, 
                f"Expected 400 error received: {data.get('detail', 'No detail')}"
            )
            return True
        else:
            self.log_test_result(
                "Register with invalid platform (400 error)", 
                False, 
                f"Expected 400 but got {status}: {data}"
            )
            return False
    
    async def test_register_android_device(self):
        """Register a valid Android device for further testing"""
        print(f"\n{Colors.BOLD}{Colors.BLUE}=== Register Android Device for Testing ==={Colors.END}")
        
        device_data = {
            "push_token": "ExponentPushToken[androidtokenhere123456789]",
            "platform": "android",
            "device_id": self.device_id_2,
            "device_name": "Samsung Galaxy S24 Ultra"
        }
        
        status, data = await self.make_request("POST", "/register-device", device_data)
        
        if status == 200:
            self.log_test_result(
                "Register Android device", 
                True, 
                f"Status: {data.get('status')}, Device: {data.get('device_id')}"
            )
            return True
        else:
            self.log_test_result(
                "Register Android device", 
                False, 
                f"Status: {status}, Response: {data}"
            )
            return False
    
    async def test_get_device_count(self):
        """Test 5: Get count of registered devices"""
        print(f"\n{Colors.BOLD}{Colors.BLUE}=== TEST 5: Get Device Count ==={Colors.END}")
        
        status, data = await self.make_request("GET", "/devices/count")
        
        if status == 200 and "total_devices" in data and "active_devices" in data:
            total = data.get("total_devices", 0)
            active = data.get("active_devices", 0)
            
            # We registered 2 devices, so total should be at least 2
            if total >= 2 and active >= 2:
                self.log_test_result(
                    "Get device count", 
                    True, 
                    f"Total: {total}, Active: {active}"
                )
                return True
            else:
                self.log_test_result(
                    "Get device count", 
                    False, 
                    f"Expected at least 2 devices, got Total: {total}, Active: {active}"
                )
                return False
        else:
            self.log_test_result(
                "Get device count", 
                False, 
                f"Status: {status}, Response: {data}"
            )
            return False
    
    async def test_send_test_push_all(self):
        """Test 6: Send test push to all devices"""
        print(f"\n{Colors.BOLD}{Colors.BLUE}=== TEST 6: Send Test Push (All Devices) ==={Colors.END}")
        
        status, data = await self.make_request("POST", "/push/test")
        
        if status == 200 and data.get("status") == "sent":
            total = data.get("total", 0)
            successful = data.get("successful", 0) 
            failed = data.get("failed", 0)
            
            # Should have attempted to send to our registered devices
            if total >= 2:
                self.log_test_result(
                    "Send test push to all devices", 
                    True, 
                    f"Total: {total}, Successful: {successful}, Failed: {failed}"
                )
                return True
            else:
                self.log_test_result(
                    "Send test push to all devices", 
                    False, 
                    f"Expected to send to at least 2 devices, got Total: {total}"
                )
                return False
        else:
            self.log_test_result(
                "Send test push to all devices", 
                False, 
                f"Status: {status}, Response: {data}"
            )
            return False
    
    async def test_send_test_push_specific(self):
        """Test 7: Send test push to specific device"""
        print(f"\n{Colors.BOLD}{Colors.BLUE}=== TEST 7: Send Test Push (Specific Device) ==={Colors.END}")
        
        status, data = await self.make_request("POST", f"/push/test?device_id={self.device_id_1}")
        
        if status == 200 and data.get("status") == "sent":
            total = data.get("total", 0)
            successful = data.get("successful", 0)
            failed = data.get("failed", 0)
            
            # Should have attempted to send to 1 device
            if total == 1:
                self.log_test_result(
                    "Send test push to specific device", 
                    True, 
                    f"Total: {total}, Successful: {successful}, Failed: {failed}"
                )
                return True
            else:
                self.log_test_result(
                    "Send test push to specific device", 
                    False, 
                    f"Expected to send to 1 device, got Total: {total}"
                )
                return False
        else:
            self.log_test_result(
                "Send test push to specific device", 
                False, 
                f"Status: {status}, Response: {data}"
            )
            return False
    
    async def test_send_push_invalid_device(self):
        """Test 8: Send test push to non-existent device"""
        print(f"\n{Colors.BOLD}{Colors.BLUE}=== TEST 8: Send Test Push (Invalid Device) ==={Colors.END}")
        
        invalid_device_id = "nonexistent_device_12345"
        status, data = await self.make_request("POST", f"/push/test?device_id={invalid_device_id}")
        
        if status == 404:
            self.log_test_result(
                "Send test push to invalid device (404 error)", 
                True, 
                f"Expected 404 error received: {data.get('detail', 'No detail')}"
            )
            return True
        else:
            self.log_test_result(
                "Send test push to invalid device (404 error)", 
                False, 
                f"Expected 404 but got {status}: {data}"
            )
            return False
    
    async def run_all_tests(self):
        """Run all push notification registration tests"""
        print(f"{Colors.BOLD}{Colors.PURPLE}")
        print("=" * 60)
        print("PropSignal Engine - Push Notification Registration Tests")
        print("=" * 60)
        print(f"{Colors.END}")
        
        print(f"{Colors.YELLOW}🎯 Target Backend: {BACKEND_URL}{Colors.END}")
        print(f"{Colors.YELLOW}📱 Test Device IDs:{Colors.END}")
        print(f"   iOS: {self.device_id_1}")
        print(f"   Android: {self.device_id_2}")
        
        # Run all tests in sequence
        tests = [
            self.test_health_check,
            self.test_register_device_valid,
            self.test_register_device_update,
            self.test_register_missing_token,
            self.test_register_invalid_platform,
            self.test_register_android_device,
            self.test_get_device_count,
            self.test_send_test_push_all,
            self.test_send_test_push_specific,
            self.test_send_push_invalid_device
        ]
        
        successful_tests = 0
        total_tests = len(tests)
        
        for test_func in tests:
            try:
                result = await test_func()
                if result:
                    successful_tests += 1
            except Exception as e:
                print(f"{Colors.RED}❌ Test Error: {test_func.__name__}{Colors.END}")
                print(f"    {Colors.RED}Exception: {str(e)}{Colors.END}")
        
        # Print summary
        print(f"\n{Colors.BOLD}{Colors.BLUE}=== TEST SUMMARY ==={Colors.END}")
        print(f"{Colors.BOLD}Total Tests: {total_tests}{Colors.END}")
        print(f"{Colors.GREEN}✅ Passed: {successful_tests}{Colors.END}")
        print(f"{Colors.RED}❌ Failed: {total_tests - successful_tests}{Colors.END}")
        
        success_rate = (successful_tests / total_tests) * 100
        if success_rate == 100:
            print(f"{Colors.GREEN}{Colors.BOLD}🎉 ALL TESTS PASSED! (100%){Colors.END}")
        elif success_rate >= 80:
            print(f"{Colors.YELLOW}{Colors.BOLD}⚠️  Most tests passed ({success_rate:.1f}%){Colors.END}")
        else:
            print(f"{Colors.RED}{Colors.BOLD}❌ Many tests failed ({success_rate:.1f}%){Colors.END}")
        
        return successful_tests == total_tests

async def main():
    """Main test execution function"""
    print(f"{Colors.CYAN}🚀 Starting PropSignal Engine Push Notification Tests...{Colors.END}\n")
    
    try:
        async with PushNotificationTester() as tester:
            success = await tester.run_all_tests()
            
            if success:
                print(f"\n{Colors.GREEN}{Colors.BOLD}🎯 PUSH NOTIFICATION REGISTRATION FLOW: FULLY WORKING{Colors.END}")
                return 0
            else:
                print(f"\n{Colors.RED}{Colors.BOLD}⚠️  PUSH NOTIFICATION REGISTRATION FLOW: ISSUES DETECTED{Colors.END}")
                return 1
                
    except Exception as e:
        print(f"{Colors.RED}{Colors.BOLD}❌ CRITICAL ERROR: {str(e)}{Colors.END}")
        return 1

if __name__ == "__main__":
    exit_code = asyncio.run(main())
    sys.exit(exit_code)