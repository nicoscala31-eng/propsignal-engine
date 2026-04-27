#!/usr/bin/env python3
"""
NEW Deterministic Pattern Engine V2.0 Testing
Testing the NEW Pattern Engine V2.0 endpoints as requested in review.

ENDPOINTS TO TEST:
1. GET /api/pattern-engine/status - Get Pattern Engine status
2. GET /api/pattern-engine/analyze/EURUSD - Analyze EURUSD pattern
3. GET /api/pattern-engine/analyze/XAUUSD - Analyze XAUUSD pattern
4. GET /api/pattern-engine/statistics - Get engine statistics
5. GET /api/pattern-engine/parameters - Get engine parameters
6. POST /api/pattern-engine/restart - Restart pattern engine
7. GET /api/signals/feed - Verify signal feed still works
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

def validate_pattern_engine_status(data):
    """Validate Pattern Engine status response"""
    print(f"   📊 Validating Pattern Engine status:")
    
    required_fields = ['is_running', 'engine', 'scan_interval_seconds', 'assets', 'statistics']
    for field in required_fields:
        if field not in data:
            print(f"   ❌ Missing required field: {field}")
            return False
        print(f"   ✅ {field}: {data[field]}")
    
    # Verify is_running is true
    if not data.get('is_running'):
        print(f"   ⚠️  Pattern Engine is not running (is_running=false)")
    else:
        print(f"   ✅ Pattern Engine is running")
    
    # Verify assets list contains EURUSD and XAUUSD
    assets = data.get('assets', [])
    expected_assets = ['EURUSD', 'XAUUSD']
    for asset in expected_assets:
        if asset in assets:
            print(f"   ✅ Asset {asset} found in assets list")
        else:
            print(f"   ❌ Asset {asset} missing from assets list")
            return False
    
    # Check engine_stats
    if 'engine_stats' in data:
        engine_stats = data['engine_stats']
        print(f"   ✅ Engine stats: {engine_stats.get('total_analyses', 0)} analyses, {engine_stats.get('acceptance_rate', 0)} acceptance rate")
    
    return True

def validate_pattern_analysis(data, symbol):
    """Validate pattern analysis response"""
    print(f"   📊 Validating pattern analysis for {symbol}:")
    
    required_fields = ['pattern_detected', 'pattern_type', 'regime', 'direction', 'metrics', 'entry', 'stop_loss', 'take_profit', 'rr', 'winrate', 'expected_edge_R', 'conditions']
    for field in required_fields:
        if field not in data:
            print(f"   ❌ Missing required field: {field}")
            return False
        print(f"   ✅ {field}: {data[field]}")
    
    # Validate metrics structure
    metrics = data.get('metrics', {})
    expected_metrics = ['mu_t', 'sigma_t', 'T_t', 'Z_t', 'ATR_t']
    for metric in expected_metrics:
        if metric in metrics:
            print(f"   ✅ Metric {metric}: {metrics[metric]}")
        else:
            print(f"   ❌ Missing metric: {metric}")
            return False
    
    # Check if pattern is detected or rejected with reason
    if data.get('pattern_detected'):
        print(f"   ✅ Pattern detected: {data.get('pattern_type')}")
    else:
        print(f"   ✅ Pattern rejected: {data.get('rejection_reason', 'Unknown reason')}")
    
    return True

def validate_pattern_statistics(data):
    """Validate pattern statistics response"""
    print(f"   📊 Validating pattern statistics:")
    
    required_fields = ['total_analyses', 'valid_signals', 'rejected_signals', 'acceptance_rate', 'by_pattern', 'rejection_breakdown', 'parameters']
    for field in required_fields:
        if field not in data:
            print(f"   ❌ Missing required field: {field}")
            return False
        print(f"   ✅ {field}: {data[field]}")
    
    return True

def validate_pattern_parameters(data):
    """Validate pattern parameters response"""
    print(f"   📊 Validating pattern parameters:")
    
    required_fields = ['trend_strength_threshold', 'mu_neutral_threshold', 'z_threshold', 'min_rr', 'K', 'M', 'N']
    for field in required_fields:
        if field not in data:
            print(f"   ❌ Missing required field: {field}")
            return False
        print(f"   ✅ {field}: {data[field]}")
    
    return True

def validate_signal_feed(data):
    """Validate signal feed response"""
    print(f"   📊 Validating signal feed:")
    
    if isinstance(data, dict):
        if 'signals' in data:
            signals = data['signals']
            print(f"   ✅ Signal feed contains {len(signals)} signals")
            return True
        else:
            print(f"   ❌ Signal feed missing 'signals' field")
            return False
    elif isinstance(data, list):
        print(f"   ✅ Signal feed contains {len(data)} signals")
        return True
    else:
        print(f"   ❌ Signal feed has unexpected format")
        return False

def main():
    """Run all Pattern Engine V2.0 tests"""
    print("🚀 NEW DETERMINISTIC PATTERN ENGINE V2.0 TESTING")
    print("=" * 70)
    
    test_results = []
    
    # Test 1: GET /api/pattern-engine/status
    print("\n📋 TEST 1: Pattern Engine Status")
    status_data = test_endpoint("GET", "/pattern-engine/status")
    if status_data:
        if validate_pattern_engine_status(status_data):
            test_results.append("✅ Pattern Engine status")
        else:
            test_results.append("❌ Pattern Engine status validation failed")
    else:
        test_results.append("❌ Pattern Engine status endpoint failed")
    
    # Test 2: GET /api/pattern-engine/analyze/EURUSD
    print("\n📋 TEST 2: Pattern Analysis for EURUSD")
    eurusd_analysis = test_endpoint("GET", "/pattern-engine/analyze/EURUSD")
    if eurusd_analysis:
        if validate_pattern_analysis(eurusd_analysis, "EURUSD"):
            test_results.append("✅ EURUSD pattern analysis")
        else:
            test_results.append("❌ EURUSD pattern analysis validation failed")
    else:
        test_results.append("❌ EURUSD pattern analysis endpoint failed")
    
    # Test 3: GET /api/pattern-engine/analyze/XAUUSD
    print("\n📋 TEST 3: Pattern Analysis for XAUUSD")
    xauusd_analysis = test_endpoint("GET", "/pattern-engine/analyze/XAUUSD")
    if xauusd_analysis:
        if validate_pattern_analysis(xauusd_analysis, "XAUUSD"):
            test_results.append("✅ XAUUSD pattern analysis")
        else:
            test_results.append("❌ XAUUSD pattern analysis validation failed")
    else:
        test_results.append("❌ XAUUSD pattern analysis endpoint failed")
    
    # Test 4: GET /api/pattern-engine/statistics
    print("\n📋 TEST 4: Pattern Engine Statistics")
    stats_data = test_endpoint("GET", "/pattern-engine/statistics")
    if stats_data:
        if validate_pattern_statistics(stats_data):
            test_results.append("✅ Pattern Engine statistics")
        else:
            test_results.append("❌ Pattern Engine statistics validation failed")
    else:
        test_results.append("❌ Pattern Engine statistics endpoint failed")
    
    # Test 5: GET /api/pattern-engine/parameters
    print("\n📋 TEST 5: Pattern Engine Parameters")
    params_data = test_endpoint("GET", "/pattern-engine/parameters")
    if params_data:
        if validate_pattern_parameters(params_data):
            test_results.append("✅ Pattern Engine parameters")
        else:
            test_results.append("❌ Pattern Engine parameters validation failed")
    else:
        test_results.append("❌ Pattern Engine parameters endpoint failed")
    
    # Test 6: POST /api/pattern-engine/restart
    print("\n📋 TEST 6: Pattern Engine Restart")
    restart_data = test_endpoint("POST", "/pattern-engine/restart")
    if restart_data:
        print(f"   📊 Restart response: {restart_data}")
        test_results.append("✅ Pattern Engine restart")
    else:
        test_results.append("❌ Pattern Engine restart endpoint failed")
    
    # Test 7: GET /api/signals/feed (verify existing functionality)
    print("\n📋 TEST 7: Signal Feed (Existing Functionality)")
    feed_data = test_endpoint("GET", "/signals/feed")
    if feed_data:
        if validate_signal_feed(feed_data):
            test_results.append("✅ Signal feed")
        else:
            test_results.append("❌ Signal feed validation failed")
    else:
        test_results.append("❌ Signal feed endpoint failed")
    
    # Summary
    print("\n" + "=" * 70)
    print("📊 PATTERN ENGINE V2.0 TESTING SUMMARY")
    print("=" * 70)
    
    passed = sum(1 for result in test_results if result.startswith("✅"))
    total = len(test_results)
    
    for result in test_results:
        print(result)
    
    print(f"\n🎯 OVERALL RESULT: {passed}/{total} tests passed ({passed/total*100:.1f}%)")
    
    if passed == total:
        print("🎉 ALL PATTERN ENGINE V2.0 TESTS PASSED!")
        return True
    else:
        print("⚠️  SOME PATTERN ENGINE V2.0 TESTS FAILED")
        return False

if __name__ == "__main__":
    success = main()
    sys.exit(0 if success else 1)