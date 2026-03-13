#!/usr/bin/env python3
"""
PropSignal Engine - Push Notification System Testing (Production Railway)
Test the complete push notification system with resilient storage fix.
"""

import requests
import json
import time
from typing import Dict, Any, Optional

class PushNotificationTester:
    def __init__(self, base_url: str):
        self.base_url = base_url.rstrip('/')
        self.session = requests.Session()
        self.session.headers.update({
            'Content-Type': 'application/json',
            'User-Agent': 'PropSignal-Tester/1.0'
        })
        
    def test_endpoint(self, method: str, endpoint: str, data: Optional[Dict] = None, 
                     params: Optional[Dict] = None, expected_status: int = 200) -> Dict[str, Any]:
        """Test a single endpoint and return result"""
        url = f"{self.base_url}{endpoint}"
        
        try:
            if method.upper() == 'GET':
                response = self.session.get(url, params=params)
            elif method.upper() == 'POST':
                response = self.session.post(url, json=data, params=params)
            elif method.upper() == 'DELETE':
                response = self.session.delete(url, params=params)
            else:
                return {"success": False, "error": f"Unsupported method: {method}"}
            
            result = {
                "success": response.status_code == expected_status,
                "status_code": response.status_code,
                "url": url,
                "method": method.upper()
            }
            
            try:
                result["response"] = response.json()
            except:
                result["response"] = response.text
                
            if not result["success"]:
                result["error"] = f"Expected status {expected_status}, got {response.status_code}"
                
            return result
            
        except Exception as e:
            return {
                "success": False,
                "error": str(e),
                "url": url,
                "method": method.upper()
            }

    def run_push_notification_tests(self):
        """Run comprehensive push notification system tests"""
        print("🚀 TESTING PropSignal Engine Push Notification System (Production Railway)")
        print(f"📍 Base URL: {self.base_url}")
        print("=" * 80)
        
        test_results = []
        
        # Test 1: Device Registration
        print("\n📱 TEST 1: Device Registration")
        device_data = {
            "push_token": "ExponentPushToken[TestFinal123]",
            "platform": "android",
            "device_id": "final_test_device",
            "device_name": "Final Test"
        }
        
        result = self.test_endpoint('POST', '/api/register-device', data=device_data)
        test_results.append(('Device Registration', result))
        
        if result['success']:
            response = result['response']
            expected_keys = ['status', 'device_id']
            if all(key in response for key in expected_keys):
                print(f"✅ Device registered successfully: {response}")
                if response.get('device_id') == 'final_test_device' and response.get('status') in ['registered', 'updated']:
                    print("✅ Registration response format correct")
                else:
                    print(f"❌ Unexpected response format: {response}")
            else:
                print(f"❌ Missing expected keys in response: {response}")
        else:
            print(f"❌ Device registration failed: {result}")
        
        # Test 2: Device Count
        print("\n📊 TEST 2: Device Count")
        result = self.test_endpoint('GET', '/api/devices/count')
        test_results.append(('Device Count', result))
        
        if result['success']:
            response = result['response']
            expected_keys = ['total_devices', 'active_devices']
            if all(key in response for key in expected_keys):
                print(f"✅ Device count retrieved: {response}")
                total = response.get('total_devices', 0)
                active = response.get('active_devices', 0)
                if isinstance(total, int) and isinstance(active, int) and active <= total:
                    print("✅ Device count format valid")
                else:
                    print(f"❌ Invalid device count format: total={total}, active={active}")
            else:
                print(f"❌ Missing expected keys in response: {response}")
        else:
            print(f"❌ Device count retrieval failed: {result}")
        
        # Test 3: Push Health Check
        print("\n🏥 TEST 3: Push Health Check")
        result = self.test_endpoint('GET', '/api/push/health')
        test_results.append(('Push Health Check', result))
        
        if result['success']:
            response = result['response']
            print(f"✅ Push health check successful: {response}")
            
            # Check for storage backend info
            if isinstance(response, dict):
                storage_info = response.get('storage', {})
                if 'backend' in storage_info:
                    backend = storage_info['backend']
                    print(f"📦 Storage backend: {backend}")
                    if backend == 'file':
                        print("✅ Resilient storage fallback working (file backend)")
                    else:
                        print(f"ℹ️  Storage backend is: {backend}")
                else:
                    print("ℹ️  Storage backend info not found in response")
                
                # Check device counts
                if 'device_counts' in response or 'devices' in response:
                    print("✅ Device count info present in health check")
                
            else:
                print(f"❌ Unexpected response format: {response}")
        else:
            print(f"❌ Push health check failed: {result}")
        
        # Test 4: Test Push Notification
        print("\n📬 TEST 4: Test Push Notification")
        result = self.test_endpoint('POST', '/api/push/test', params={'device_id': 'final_test_device'})
        test_results.append(('Test Push Notification', result))
        
        if result['success']:
            response = result['response']
            expected_keys = ['status']
            if 'status' in response:
                print(f"✅ Test push notification sent: {response}")
                if response.get('status') == 'sent':
                    print("✅ Push notification status correct")
                else:
                    print(f"ℹ️  Push status: {response.get('status')}")
            else:
                print(f"❌ Missing status in response: {response}")
        else:
            print(f"❌ Test push notification failed: {result}")
        
        # Test 5: Device Unregistration
        print("\n🗑️ TEST 5: Device Unregistration")
        result = self.test_endpoint('DELETE', '/api/devices/final_test_device')
        test_results.append(('Device Unregistration', result))
        
        if result['success']:
            response = result['response']
            if isinstance(response, dict) and 'status' in response:
                print(f"✅ Device unregistered successfully: {response}")
                if response.get('status') == 'unregistered':
                    print("✅ Unregistration response format correct")
                else:
                    print(f"ℹ️  Unregistration status: {response.get('status')}")
            else:
                print(f"❌ Unexpected unregistration response: {response}")
        else:
            print(f"❌ Device unregistration failed: {result}")
        
        # Additional Tests: Error Validation
        print("\n🔍 ADDITIONAL TESTS: Error Validation")
        
        # Test invalid device registration
        print("\n📱 TEST 6: Invalid Device Registration (Missing push_token)")
        invalid_device_data = {
            "platform": "android",
            "device_id": "test_invalid",
            "device_name": "Invalid Test"
        }
        result = self.test_endpoint('POST', '/api/register-device', data=invalid_device_data, expected_status=422)
        test_results.append(('Invalid Registration Validation', result))
        
        if result['success']:
            print(f"✅ Validation error correctly returned: {result['response']}")
        else:
            print(f"❌ Expected 422 validation error, got: {result}")
        
        # Test invalid platform
        print("\n📱 TEST 7: Invalid Platform Validation")
        invalid_platform_data = {
            "push_token": "ExponentPushToken[Test123]",
            "platform": "invalid_platform",
            "device_id": "test_platform",
            "device_name": "Platform Test"
        }
        result = self.test_endpoint('POST', '/api/register-device', data=invalid_platform_data, expected_status=400)
        test_results.append(('Invalid Platform Validation', result))
        
        if result['success']:
            print(f"✅ Platform validation error correctly returned: {result['response']}")
        else:
            print(f"❌ Expected 400 validation error, got: {result}")
        
        # Test push to invalid device
        print("\n📬 TEST 8: Push to Invalid Device")
        result = self.test_endpoint('POST', '/api/push/test', params={'device_id': 'non_existent_device'}, expected_status=404)
        test_results.append(('Push to Invalid Device', result))
        
        if result['success']:
            print(f"✅ Invalid device error correctly returned: {result['response']}")
        else:
            print(f"❌ Expected 404 error for invalid device, got: {result}")
        
        # Summary
        print("\n" + "=" * 80)
        print("📊 TEST SUMMARY")
        print("=" * 80)
        
        passed = 0
        total = len(test_results)
        
        for test_name, result in test_results:
            status = "✅ PASS" if result['success'] else "❌ FAIL"
            print(f"{status} - {test_name}")
            if result['success']:
                passed += 1
            else:
                print(f"     Error: {result.get('error', 'Unknown error')}")
        
        print(f"\n📈 RESULTS: {passed}/{total} tests passed ({(passed/total)*100:.1f}%)")
        
        # Critical Issues Check
        critical_issues = []
        for test_name, result in test_results:
            if not result['success']:
                if result.get('status_code') == 500:
                    critical_issues.append(f"{test_name}: 500 Internal Server Error")
                elif 'error' in result and 'connection' in result['error'].lower():
                    critical_issues.append(f"{test_name}: Connection Error")
        
        if critical_issues:
            print(f"\n🚨 CRITICAL ISSUES FOUND:")
            for issue in critical_issues:
                print(f"   - {issue}")
        else:
            print(f"\n✅ NO CRITICAL ISSUES (500 errors or connection failures)")
        
        return test_results, passed, total

def main():
    """Main testing function"""
    base_url = "https://propsignal-engine-production-b22b.up.railway.app"
    
    tester = PushNotificationTester(base_url)
    test_results, passed, total = tester.run_push_notification_tests()
    
    print(f"\n🎯 FINAL ASSESSMENT:")
    if passed == total:
        print("🎉 ALL TESTS PASSED - Push notification system is fully functional!")
    elif passed >= total * 0.8:
        print("✅ MOSTLY FUNCTIONAL - Minor issues detected")
    else:
        print("❌ SIGNIFICANT ISSUES - Multiple test failures")
    
    return passed == total

if __name__ == "__main__":
    success = main()
    exit(0 if success else 1)