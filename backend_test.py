#!/usr/bin/env python3
"""
PropSignal Engine Backend API Testing Suite

Comprehensive testing for the trading signals platform backend API.
Tests all core functionality: health checks, user management, prop profiles,
signal generation, notifications, and analytics.
"""

import requests
import json
import time
from typing import Dict, Any, Optional, List
from datetime import datetime

# Backend URL from frontend/.env
BASE_URL = "https://eurusd-alerts.preview.emergentagent.com/api"

class PropSignalTester:
    def __init__(self):
        self.session = requests.Session()
        self.session.headers.update({
            'Content-Type': 'application/json',
            'Accept': 'application/json'
        })
        
        # Test data storage
        self.created_user_id = None
        self.created_profile_id = None
        self.generated_signals = []
        self.notifications = []
        
        # Test statistics
        self.total_tests = 0
        self.passed_tests = 0
        self.failed_tests = 0
        self.test_results = []
        
    def log_test(self, test_name: str, success: bool, message: str, response_data: Any = None):
        """Log test result"""
        self.total_tests += 1
        if success:
            self.passed_tests += 1
            status = "✅ PASS"
        else:
            self.failed_tests += 1
            status = "❌ FAIL"
        
        result = {
            'test_name': test_name,
            'status': status,
            'success': success,
            'message': message,
            'response_data': response_data,
            'timestamp': datetime.now().isoformat()
        }
        
        self.test_results.append(result)
        print(f"{status} - {test_name}: {message}")
        
        if response_data and not success:
            print(f"   Response: {json.dumps(response_data, indent=2)}")
    
    def make_request(self, method: str, endpoint: str, data: Dict = None, params: Dict = None) -> tuple:
        """Make HTTP request and return (success, response_data, status_code)"""
        url = f"{BASE_URL}{endpoint}"
        
        try:
            if method.upper() == 'GET':
                response = self.session.get(url, params=params, timeout=30)
            elif method.upper() == 'POST':
                response = self.session.post(url, json=data, timeout=30)
            elif method.upper() == 'PUT':
                response = self.session.put(url, json=data, timeout=30)
            else:
                return False, {"error": f"Unsupported method: {method}"}, 0
                
            try:
                response_data = response.json()
            except json.JSONDecodeError:
                response_data = {"raw_response": response.text}
            
            return response.status_code < 400, response_data, response.status_code
            
        except requests.exceptions.RequestException as e:
            return False, {"error": str(e)}, 0
    
    def test_health_endpoints(self):
        """Test health check and root endpoints"""
        print("\n🔍 Testing Health & Basic Endpoints...")
        
        # Test root endpoint
        success, data, status_code = self.make_request('GET', '/')
        if success and data.get('message') == 'PropSignal Engine API':
            self.log_test("Root endpoint", True, f"API operational, version {data.get('version', 'unknown')}")
        else:
            self.log_test("Root endpoint", False, f"Status: {status_code}", data)
        
        # Test health endpoint
        success, data, status_code = self.make_request('GET', '/health')
        if success and data.get('status') == 'healthy':
            self.log_test("Health check", True, f"Backend healthy at {data.get('timestamp')}")
        else:
            self.log_test("Health check", False, f"Status: {status_code}", data)
    
    def test_user_management(self):
        """Test user creation and retrieval"""
        print("\n👤 Testing User Management...")
        
        # Create user
        user_data = {"email": "trader@propsignal.com"}
        success, data, status_code = self.make_request('POST', '/users', user_data)
        
        if success and data.get('id'):
            self.created_user_id = data['id']
            self.log_test("Create user", True, f"User created with ID: {self.created_user_id}")
        else:
            self.log_test("Create user", False, f"Status: {status_code}", data)
            return
        
        # Get user by ID
        success, data, status_code = self.make_request('GET', f'/users/{self.created_user_id}')
        if success and data.get('id') == self.created_user_id:
            self.log_test("Get user by ID", True, f"User retrieved: {data.get('email')}")
        else:
            self.log_test("Get user by ID", False, f"Status: {status_code}", data)
    
    def test_prop_profile_management(self):
        """Test prop profile creation and management"""
        print("\n📊 Testing Prop Profile Management...")
        
        if not self.created_user_id:
            self.log_test("Prop profile tests", False, "No user ID available")
            return
        
        # Create prop profile
        profile_data = {
            "name": "Get Leveraged Challenge Pro",
            "firm_name": "get_leveraged",
            "phase": "CHALLENGE",
            "daily_drawdown_percent": 5.0,
            "max_drawdown_percent": 10.0,
            "drawdown_type": "BALANCE",
            "max_lot_exposure": 2.0,
            "news_rule_enabled": False,
            "weekend_holding_allowed": False,
            "overnight_holding_allowed": True,
            "consistency_rule_enabled": False,
            "max_daily_profit_percent": None,
            "minimum_trading_days": 5,
            "minimum_profitable_days": 3,
            "minimum_trade_duration_minutes": 3,
            "initial_balance": 50000.0
        }
        
        success, data, status_code = self.make_request('POST', f'/users/{self.created_user_id}/prop-profiles', profile_data)
        
        if success and data.get('id'):
            self.created_profile_id = data['id']
            self.log_test("Create prop profile", True, f"Profile created: {data['name']} (${data['initial_balance']})")
        else:
            self.log_test("Create prop profile", False, f"Status: {status_code}", data)
            return
        
        # Get user prop profiles
        success, data, status_code = self.make_request('GET', f'/users/{self.created_user_id}/prop-profiles')
        if success and len(data) > 0 and data[0].get('id') == self.created_profile_id:
            self.log_test("Get user prop profiles", True, f"Retrieved {len(data)} profile(s)")
        else:
            self.log_test("Get user prop profiles", False, f"Status: {status_code}", data)
        
        # Get specific prop profile
        success, data, status_code = self.make_request('GET', f'/prop-profiles/{self.created_profile_id}')
        if success and data.get('id') == self.created_profile_id:
            self.log_test("Get prop profile by ID", True, f"Profile: {data['name']} - {data['firm_name']}")
        else:
            self.log_test("Get prop profile by ID", False, f"Status: {status_code}", data)
        
        # Update profile balance
        balance_data = {"current_balance": 52500.0, "current_equity": 52500.0}
        success, data, status_code = self.make_request('PUT', f'/prop-profiles/{self.created_profile_id}/balance', balance_data)
        if success and data.get('status') == 'updated':
            self.log_test("Update profile balance", True, "Balance updated successfully")
        else:
            self.log_test("Update profile balance", False, f"Status: {status_code}", data)
        
        # Test preset profiles
        for firm_name in ["get_leveraged", "goatfundedtrader"]:
            success, data, status_code = self.make_request('GET', f'/prop-profiles/presets/{firm_name}', 
                                                         params={"user_id": self.created_user_id})
            if success:
                self.log_test(f"Get {firm_name} preset", True, f"Preset loaded with {len(data)} fields")
            else:
                self.log_test(f"Get {firm_name} preset", False, f"Status: {status_code}", data)
    
    def test_signal_generation(self):
        """Test the core signal generation feature"""
        print("\n⚡ Testing Signal Generation - CORE FEATURE...")
        
        if not self.created_user_id or not self.created_profile_id:
            self.log_test("Signal generation tests", False, "Missing user ID or profile ID")
            return
        
        # Test signal generation for EURUSD and XAUUSD
        assets = ["EURUSD", "XAUUSD"]
        
        for asset in assets:
            print(f"\n  📈 Generating signals for {asset}...")
            
            # Generate multiple signals to test variety
            for i in range(5):
                signal_data = {
                    "asset": asset,
                    "prop_profile_id": self.created_profile_id
                }
                
                success, data, status_code = self.make_request('POST', f'/users/{self.created_user_id}/signals/generate', signal_data)
                
                if success and data.get('id'):
                    signal_type = data.get('signal_type')
                    confidence = data.get('confidence_score', 0)
                    success_prob = data.get('success_probability', 0)
                    prop_safety = data.get('prop_rule_safety')
                    
                    # Validate signal structure
                    validation_errors = []
                    
                    if signal_type not in ['BUY', 'SELL', 'NEXT']:
                        validation_errors.append(f"Invalid signal_type: {signal_type}")
                    
                    if signal_type in ['BUY', 'SELL']:
                        required_fields = ['entry_price', 'stop_loss', 'take_profit_1', 'take_profit_2']
                        for field in required_fields:
                            if data.get(field) is None:
                                validation_errors.append(f"Missing {field} for {signal_type} signal")
                        
                        if confidence < 78:
                            validation_errors.append(f"Confidence too low: {confidence} (min 78)")
                        elif confidence > 100:
                            validation_errors.append(f"Confidence too high: {confidence} (max 100)")
                    
                    if success_prob is not None and (success_prob < 35 or success_prob > 75):
                        validation_errors.append(f"Success probability out of range: {success_prob}% (35-75%)")
                    
                    if prop_safety not in ['SAFE', 'CAUTION', 'BLOCKED']:
                        validation_errors.append(f"Invalid prop_rule_safety: {prop_safety}")
                    
                    # Check score breakdown
                    score_breakdown = data.get('score_breakdown')
                    if score_breakdown and signal_type in ['BUY', 'SELL']:
                        total_score = score_breakdown.get('total', 0)
                        if abs(total_score - confidence) > 1:  # Allow 1 point tolerance
                            validation_errors.append(f"Score breakdown total {total_score} doesn't match confidence {confidence}")
                    
                    if validation_errors:
                        self.log_test(f"Generate {asset} signal #{i+1}", False, 
                                    f"Validation errors: {'; '.join(validation_errors)}", data)
                    else:
                        self.generated_signals.append(data)
                        self.log_test(f"Generate {asset} signal #{i+1}", True, 
                                    f"{signal_type} signal - Confidence: {confidence}%, Success: {success_prob}%, Safety: {prop_safety}")
                    
                    # Small delay between requests
                    time.sleep(0.5)
                else:
                    self.log_test(f"Generate {asset} signal #{i+1}", False, f"Status: {status_code}", data)
    
    def test_signal_retrieval(self):
        """Test signal retrieval endpoints"""
        print("\n📋 Testing Signal Retrieval...")
        
        if not self.created_user_id:
            self.log_test("Signal retrieval tests", False, "No user ID available")
            return
        
        # Get active signals
        success, data, status_code = self.make_request('GET', f'/users/{self.created_user_id}/signals/active')
        if success:
            active_count = len(data) if isinstance(data, list) else 0
            self.log_test("Get active signals", True, f"Retrieved {active_count} active signals")
        else:
            self.log_test("Get active signals", False, f"Status: {status_code}", data)
        
        # Get latest signals by asset
        for asset in ["EURUSD", "XAUUSD"]:
            success, data, status_code = self.make_request('GET', f'/users/{self.created_user_id}/signals/latest', 
                                                         params={"asset": asset})
            if success:
                if data and data.get('id'):
                    self.log_test(f"Get latest {asset} signal", True, 
                                f"Latest: {data['signal_type']} at {data.get('created_at', 'unknown time')}")
                else:
                    self.log_test(f"Get latest {asset} signal", True, "No signals found (expected)")
            else:
                self.log_test(f"Get latest {asset} signal", False, f"Status: {status_code}", data)
        
        # Get signal history
        success, data, status_code = self.make_request('GET', f'/users/{self.created_user_id}/signals/history', 
                                                     params={"limit": 20})
        if success:
            history_count = len(data) if isinstance(data, list) else 0
            self.log_test("Get signal history", True, f"Retrieved {history_count} historical signals")
        else:
            self.log_test("Get signal history", False, f"Status: {status_code}", data)
        
        # Test get specific signal by ID
        if self.generated_signals:
            signal_id = self.generated_signals[0]['id']
            success, data, status_code = self.make_request('GET', f'/signals/{signal_id}')
            if success and data.get('id') == signal_id:
                self.log_test("Get signal by ID", True, f"Signal retrieved: {data['signal_type']} {data['asset']}")
            else:
                self.log_test("Get signal by ID", False, f"Status: {status_code}", data)
    
    def test_notifications(self):
        """Test notification endpoints"""
        print("\n🔔 Testing Notifications...")
        
        if not self.created_user_id:
            self.log_test("Notification tests", False, "No user ID available")
            return
        
        # Get all notifications
        success, data, status_code = self.make_request('GET', f'/users/{self.created_user_id}/notifications')
        if success:
            notification_count = len(data) if isinstance(data, list) else 0
            self.log_test("Get notifications", True, f"Retrieved {notification_count} notifications")
            
            if notification_count > 0:
                self.notifications = data
        else:
            self.log_test("Get notifications", False, f"Status: {status_code}", data)
        
        # Get unread notifications only
        success, data, status_code = self.make_request('GET', f'/users/{self.created_user_id}/notifications', 
                                                     params={"unread_only": "true"})
        if success:
            unread_count = len(data) if isinstance(data, list) else 0
            self.log_test("Get unread notifications", True, f"Retrieved {unread_count} unread notifications")
        else:
            self.log_test("Get unread notifications", False, f"Status: {status_code}", data)
        
        # Mark notification as read (if any exist)
        if self.notifications:
            notification_id = self.notifications[0]['id']
            success, data, status_code = self.make_request('PUT', f'/notifications/{notification_id}/read')
            if success and data.get('status') == 'marked_read':
                self.log_test("Mark notification read", True, "Notification marked as read")
            else:
                self.log_test("Mark notification read", False, f"Status: {status_code}", data)
    
    def test_analytics(self):
        """Test analytics summary endpoint"""
        print("\n📊 Testing Analytics...")
        
        if not self.created_user_id:
            self.log_test("Analytics tests", False, "No user ID available")
            return
        
        success, data, status_code = self.make_request('GET', f'/users/{self.created_user_id}/analytics/summary')
        if success:
            total_signals = data.get('total_signals', 0)
            trade_signals = data.get('trade_signals', 0)
            avg_confidence = data.get('average_confidence', 0)
            by_asset = data.get('by_asset', {})
            
            self.log_test("Analytics summary", True, 
                        f"Total: {total_signals}, Trades: {trade_signals}, "
                        f"Avg Confidence: {avg_confidence}%, "
                        f"EURUSD: {by_asset.get('EURUSD', 0)}, XAUUSD: {by_asset.get('XAUUSD', 0)}")
        else:
            self.log_test("Analytics summary", False, f"Status: {status_code}", data)
    
    def run_all_tests(self):
        """Run comprehensive test suite"""
        print("🚀 PropSignal Engine Backend API Testing Suite")
        print("=" * 60)
        
        start_time = time.time()
        
        try:
            # Run all test categories
            self.test_health_endpoints()
            self.test_user_management()
            self.test_prop_profile_management()
            self.test_signal_generation()
            self.test_signal_retrieval()
            self.test_notifications()
            self.test_analytics()
            
            # Summary
            end_time = time.time()
            duration = round(end_time - start_time, 2)
            
            print(f"\n📊 TEST SUMMARY")
            print("=" * 40)
            print(f"Total Tests: {self.total_tests}")
            print(f"Passed: {self.passed_tests}")
            print(f"Failed: {self.failed_tests}")
            print(f"Success Rate: {(self.passed_tests/self.total_tests*100):.1f}%")
            print(f"Duration: {duration}s")
            
            if self.failed_tests > 0:
                print(f"\n❌ FAILED TESTS:")
                for result in self.test_results:
                    if not result['success']:
                        print(f"  - {result['test_name']}: {result['message']}")
            
            # Detailed signal analysis
            if self.generated_signals:
                print(f"\n📈 SIGNAL ANALYSIS:")
                buy_count = sum(1 for s in self.generated_signals if s.get('signal_type') == 'BUY')
                sell_count = sum(1 for s in self.generated_signals if s.get('signal_type') == 'SELL')
                next_count = sum(1 for s in self.generated_signals if s.get('signal_type') == 'NEXT')
                
                print(f"  Generated Signals: {len(self.generated_signals)}")
                print(f"  BUY: {buy_count}, SELL: {sell_count}, NEXT: {next_count}")
                
                trade_signals = [s for s in self.generated_signals if s.get('signal_type') in ['BUY', 'SELL']]
                if trade_signals:
                    avg_conf = sum(s.get('confidence_score', 0) for s in trade_signals) / len(trade_signals)
                    print(f"  Average Confidence: {avg_conf:.1f}%")
            
            return self.failed_tests == 0
            
        except Exception as e:
            print(f"\n💥 CRITICAL ERROR: {str(e)}")
            return False

def main():
    """Run the PropSignal Engine backend tests"""
    tester = PropSignalTester()
    
    try:
        success = tester.run_all_tests()
        
        # Write detailed results to file
        with open('/app/backend_test_results.json', 'w') as f:
            json.dump({
                'summary': {
                    'total_tests': tester.total_tests,
                    'passed': tester.passed_tests,
                    'failed': tester.failed_tests,
                    'success_rate': f"{(tester.passed_tests/tester.total_tests*100):.1f}%",
                    'all_passed': success
                },
                'test_results': tester.test_results,
                'generated_signals': tester.generated_signals,
                'notifications': tester.notifications,
                'user_id': tester.created_user_id,
                'profile_id': tester.created_profile_id
            }, indent=2)
        
        if success:
            print(f"\n🎉 All tests passed! PropSignal Engine backend is working correctly.")
            exit(0)
        else:
            print(f"\n⚠️  Some tests failed. Check the detailed output above.")
            exit(1)
            
    except KeyboardInterrupt:
        print(f"\n🛑 Tests interrupted by user")
        exit(1)
    except Exception as e:
        print(f"\n💥 Test suite crashed: {str(e)}")
        exit(1)

if __name__ == "__main__":
    main()