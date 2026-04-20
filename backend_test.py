#!/usr/bin/env python3
"""
Backend API Testing for Pattern UI Backend endpoints and Pattern Engine integration
Testing the NEW Pattern UI Backend endpoints as requested in review.
"""

import requests
import json
import sys
from datetime import datetime

# Backend URL from frontend .env
BACKEND_URL = "https://eurusd-alerts.preview.emergentagent.com/api"

def test_endpoint(method, endpoint, expected_status=200, data=None):
    """Test an API endpoint and return response"""
    url = f"{BACKEND_URL}{endpoint}"
    print(f"\n🔍 Testing {method} {endpoint}")
    
    try:
        if method == "GET":
            response = requests.get(url, timeout=30)
        elif method == "POST":
            response = requests.post(url, json=data, timeout=30)
        else:
            print(f"❌ Unsupported method: {method}")
            return None
            
        print(f"   Status: {response.status_code}")
        
        if response.status_code == expected_status:
            try:
                json_data = response.json()
                print(f"   ✅ SUCCESS - Response received")
                return json_data
            except:
                print(f"   ✅ SUCCESS - Non-JSON response")
                return response.text
        else:
            print(f"   ❌ FAILED - Expected {expected_status}, got {response.status_code}")
            try:
                error_data = response.json()
                print(f"   Error: {error_data}")
            except:
                print(f"   Error: {response.text}")
            return None
            
    except requests.exceptions.RequestException as e:
        print(f"   ❌ REQUEST FAILED: {e}")
        return None

def validate_pattern_components_response(data, symbol):
    """Validate pattern components response structure"""
    print(f"   📊 Validating pattern components for {symbol}:")
    
    required_fields = ['active_count', 'active_patterns', 'primary_pattern', 'factor_contributions']
    for field in required_fields:
        if field not in data:
            print(f"   ❌ Missing required field: {field}")
            return False
        print(f"   ✅ {field}: {data[field]}")
    
    # Validate factor_contributions structure
    factor_contributions = data.get('factor_contributions', [])
    if not isinstance(factor_contributions, list):
        print(f"   ❌ factor_contributions should be array")
        return False
        
    if len(factor_contributions) != 5:
        print(f"   ❌ Expected 5 patterns in factor_contributions, got {len(factor_contributions)}")
        return False
        
    expected_patterns = ['trend_structure', 'fib_pullback', 'breakout_retest', 'liquidity_sweep', 'flag_pattern']
    for i, factor in enumerate(factor_contributions):
        if not isinstance(factor, dict):
            print(f"   ❌ factor_contributions[{i}] should be object")
            return False
            
        required_factor_fields = ['factor_key', 'factor_name', 'status', 'reason']
        for field in required_factor_fields:
            if field not in factor:
                print(f"   ❌ Missing field in factor_contributions[{i}]: {field}")
                return False
                
        if factor['factor_key'] not in expected_patterns:
            print(f"   ❌ Unexpected factor_key: {factor['factor_key']}")
            return False
            
        if factor['status'] not in ['pass', 'fail']:
            print(f"   ❌ Invalid status: {factor['status']}")
            return False
            
        print(f"   ✅ Pattern {factor['factor_key']}: {factor['status']} - {factor['reason']}")
    
    return True

def validate_signal_feed_response(data):
    """Validate signal feed response structure"""
    print(f"   📊 Validating signal feed response:")
    
    if not isinstance(data, dict):
        print(f"   ❌ Signal feed should be object")
        return False
        
    if 'signals' not in data:
        print(f"   ❌ Missing 'signals' field")
        return False
        
    signals = data['signals']
    if not isinstance(signals, list):
        print(f"   ❌ signals should be array")
        return False
        
    print(f"   ✅ Signal count: {len(signals)}")
    print(f"   ✅ Total count: {data.get('count', 'N/A')}")
    
    if len(signals) > 0:
        # Check first signal structure
        signal = signals[0]
        required_fields = ['signal_id', 'symbol', 'direction', 'status']
        for field in required_fields:
            if field not in signal:
                print(f"   ❌ Missing field in signal: {field}")
                return False
        print(f"   ✅ Signal structure validated")
        print(f"   ✅ Sample signal: {signal['symbol']} {signal['direction']} - {signal['status']}")
        
        # Check for active, rejected, and closed signals
        statuses = [s['status'] for s in signals]
        unique_statuses = set(statuses)
        print(f"   ✅ Signal statuses found: {list(unique_statuses)}")
    
    return True

def validate_feed_stats_response(data):
    """Validate feed stats response structure"""
    print(f"   📊 Validating feed stats response:")
    
    required_fields = ['accepted', 'rejected', 'active', 'closed']
    for field in required_fields:
        if field not in data:
            print(f"   ❌ Missing required field: {field}")
            return False
        print(f"   ✅ {field}: {data[field]}")
    
    return True

def main():
    """Run all pattern endpoint tests"""
    print("🚀 PATTERN UI BACKEND ENDPOINTS TESTING")
    print("=" * 60)
    
    test_results = []
    
    # Test 1: GET /api/pattern/components/{symbol} for EURUSD
    print("\n📋 TEST 1: Pattern Components for EURUSD")
    eurusd_data = test_endpoint("GET", "/pattern/components/EURUSD")
    if eurusd_data:
        if validate_pattern_components_response(eurusd_data, "EURUSD"):
            test_results.append("✅ EURUSD pattern components")
        else:
            test_results.append("❌ EURUSD pattern components validation failed")
    else:
        test_results.append("❌ EURUSD pattern components endpoint failed")
    
    # Test 2: GET /api/pattern/components/{symbol} for XAUUSD
    print("\n📋 TEST 2: Pattern Components for XAUUSD")
    xauusd_data = test_endpoint("GET", "/pattern/components/XAUUSD")
    if xauusd_data:
        if validate_pattern_components_response(xauusd_data, "XAUUSD"):
            test_results.append("✅ XAUUSD pattern components")
        else:
            test_results.append("❌ XAUUSD pattern components validation failed")
    else:
        test_results.append("❌ XAUUSD pattern components endpoint failed")
    
    # Test 3: GET /api/pattern/status
    print("\n📋 TEST 3: Pattern Engine Status")
    status_data = test_endpoint("GET", "/pattern/status")
    if status_data:
        print(f"   📊 Pattern Engine Status: {status_data}")
        test_results.append("✅ Pattern engine status")
    else:
        test_results.append("❌ Pattern engine status failed")
    
    # Test 4: GET /api/pattern/market-state
    print("\n📋 TEST 4: Pattern Market State")
    market_state_data = test_endpoint("GET", "/pattern/market-state")
    if market_state_data:
        print(f"   📊 Market State: {market_state_data}")
        test_results.append("✅ Pattern market state")
    else:
        test_results.append("❌ Pattern market state failed")
    
    # Test 5: GET /api/signals/feed
    print("\n📋 TEST 5: Signals Feed")
    feed_data = test_endpoint("GET", "/signals/feed")
    if feed_data:
        if validate_signal_feed_response(feed_data):
            test_results.append("✅ Signals feed")
        else:
            test_results.append("❌ Signals feed validation failed")
    else:
        test_results.append("❌ Signals feed endpoint failed")
    
    # Test 6: GET /api/signals/feed/stats
    print("\n📋 TEST 6: Signals Feed Stats")
    stats_data = test_endpoint("GET", "/signals/feed/stats")
    if stats_data:
        if validate_feed_stats_response(stats_data):
            test_results.append("✅ Signals feed stats")
        else:
            test_results.append("❌ Signals feed stats validation failed")
    else:
        test_results.append("❌ Signals feed stats endpoint failed")
    
    # Additional Pattern Engine Tests
    print("\n📋 ADDITIONAL TESTS: Pattern Engine Integration")
    
    # Test 7: Pattern Engine Configuration
    print("\n📋 TEST 7: Pattern Engine Configuration")
    config_data = test_endpoint("GET", "/pattern/config")
    if config_data:
        print(f"   📊 Pattern Config: {config_data}")
        test_results.append("✅ Pattern engine config")
    else:
        test_results.append("❌ Pattern engine config failed")
    
    # Test 8: Pattern Performance
    print("\n📋 TEST 8: Pattern Performance")
    perf_data = test_endpoint("GET", "/pattern/performance")
    if perf_data:
        print(f"   📊 Pattern Performance: {perf_data}")
        test_results.append("✅ Pattern performance")
    else:
        test_results.append("❌ Pattern performance failed")
    
    # Test 9: Pattern Tracker Status
    print("\n📋 TEST 9: Pattern Tracker Status")
    tracker_data = test_endpoint("GET", "/pattern/tracker/status")
    if tracker_data:
        print(f"   📊 Pattern Tracker: {tracker_data}")
        test_results.append("✅ Pattern tracker status")
    else:
        test_results.append("❌ Pattern tracker status failed")
    
    # Summary
    print("\n" + "=" * 60)
    print("📊 PATTERN UI BACKEND TESTING SUMMARY")
    print("=" * 60)
    
    passed = sum(1 for result in test_results if result.startswith("✅"))
    total = len(test_results)
    
    for result in test_results:
        print(result)
    
    print(f"\n🎯 OVERALL RESULT: {passed}/{total} tests passed ({passed/total*100:.1f}%)")
    
    if passed == total:
        print("🎉 ALL PATTERN ENDPOINT TESTS PASSED!")
        return True
    else:
        print("⚠️  SOME PATTERN ENDPOINT TESTS FAILED")
        return False

if __name__ == "__main__":
    success = main()
    sys.exit(0 if success else 1)