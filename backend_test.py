#!/usr/bin/env python3
"""
Backend API Testing Script for PropSignal Engine
Testing Signal Feed API - Include REJECTED signals in feed
"""

import requests
import json
import sys
from typing import Dict, List, Any

# Backend URL from environment
BACKEND_URL = "https://eurusd-alerts.preview.emergentagent.com"
API_BASE = f"{BACKEND_URL}/api"

def test_signal_feed_rejected_signals():
    """Test the /api/signals/feed endpoint fix for including REJECTED signals"""
    
    print("🔍 TESTING SIGNAL FEED API - REJECTED SIGNALS INCLUSION")
    print("=" * 60)
    
    results = {
        "tests_passed": 0,
        "tests_failed": 0,
        "critical_issues": [],
        "test_details": []
    }
    
    # Test 1: status=all - Should return ALL statuses (active, closed, rejected)
    print("\n1. Testing status=all - Should return ALL statuses")
    try:
        response = requests.get(f"{API_BASE}/signals/feed?status=all&limit=200", timeout=10)
        if response.status_code == 200:
            data = response.json()
            signals = data.get('signals', [])
            
            # Count signals by status
            status_counts = {}
            for signal in signals:
                status = signal.get('status', 'unknown')
                status_counts[status] = status_counts.get(status, 0) + 1
            
            print(f"   ✅ Response received: {len(signals)} total signals")
            print(f"   📊 Status breakdown: {status_counts}")
            
            # Check if rejected signals are present
            rejected_count = status_counts.get('rejected', 0)
            if rejected_count > 0:
                print(f"   ✅ CRITICAL: Found {rejected_count} REJECTED signals")
                results["tests_passed"] += 1
                results["test_details"].append(f"status=all returns {rejected_count} rejected signals")
            else:
                print(f"   ❌ CRITICAL: NO REJECTED signals found in status=all")
                results["tests_failed"] += 1
                results["critical_issues"].append("status=all does not return rejected signals")
                
            # Verify all three statuses are present
            expected_statuses = ['active', 'closed', 'rejected']
            missing_statuses = [s for s in expected_statuses if s not in status_counts]
            if not missing_statuses:
                print(f"   ✅ All expected statuses present: {list(status_counts.keys())}")
            else:
                print(f"   ⚠️  Missing statuses: {missing_statuses}")
                
        else:
            print(f"   ❌ API Error: {response.status_code} - {response.text}")
            results["tests_failed"] += 1
            results["critical_issues"].append(f"status=all endpoint failed: {response.status_code}")
            
    except Exception as e:
        print(f"   ❌ Exception: {str(e)}")
        results["tests_failed"] += 1
        results["critical_issues"].append(f"status=all endpoint exception: {str(e)}")
    
    # Test 2: status=rejected - Should return ONLY rejected signals
    print("\n2. Testing status=rejected - Should return ONLY rejected signals")
    try:
        response = requests.get(f"{API_BASE}/signals/feed?status=rejected&limit=50", timeout=10)
        if response.status_code == 200:
            data = response.json()
            signals = data.get('signals', [])
            
            print(f"   ✅ Response received: {len(signals)} signals")
            
            # Verify all signals have status "rejected"
            non_rejected = [s for s in signals if s.get('status') != 'rejected']
            if not non_rejected:
                print(f"   ✅ All {len(signals)} signals have status 'rejected'")
                results["tests_passed"] += 1
                results["test_details"].append(f"status=rejected returns only rejected signals ({len(signals)} found)")
                
                # Check for rejection_reason field
                signals_with_reason = [s for s in signals if 'rejection_reason' in s]
                print(f"   📋 Signals with rejection_reason: {len(signals_with_reason)}/{len(signals)}")
                
            else:
                print(f"   ❌ Found {len(non_rejected)} non-rejected signals in rejected feed")
                results["tests_failed"] += 1
                results["critical_issues"].append(f"status=rejected contains non-rejected signals")
                
        else:
            print(f"   ❌ API Error: {response.status_code} - {response.text}")
            results["tests_failed"] += 1
            results["critical_issues"].append(f"status=rejected endpoint failed: {response.status_code}")
            
    except Exception as e:
        print(f"   ❌ Exception: {str(e)}")
        results["tests_failed"] += 1
        results["critical_issues"].append(f"status=rejected endpoint exception: {str(e)}")
    
    # Test 3: status=active - Should return only active signals
    print("\n3. Testing status=active - Should return only active signals")
    try:
        response = requests.get(f"{API_BASE}/signals/feed?status=active&limit=50", timeout=10)
        if response.status_code == 200:
            data = response.json()
            signals = data.get('signals', [])
            
            print(f"   ✅ Response received: {len(signals)} signals")
            
            # Verify all signals have status "active"
            non_active = [s for s in signals if s.get('status') != 'active']
            if not non_active:
                print(f"   ✅ All {len(signals)} signals have status 'active'")
                results["tests_passed"] += 1
                results["test_details"].append(f"status=active returns only active signals ({len(signals)} found)")
            else:
                print(f"   ❌ Found {len(non_active)} non-active signals in active feed")
                results["tests_failed"] += 1
                results["critical_issues"].append(f"status=active contains non-active signals")
                
        else:
            print(f"   ❌ API Error: {response.status_code} - {response.text}")
            results["tests_failed"] += 1
            results["critical_issues"].append(f"status=active endpoint failed: {response.status_code}")
            
    except Exception as e:
        print(f"   ❌ Exception: {str(e)}")
        results["tests_failed"] += 1
        results["critical_issues"].append(f"status=active endpoint exception: {str(e)}")
    
    # Test 4: status=closed - Should return only closed signals
    print("\n4. Testing status=closed - Should return only closed signals")
    try:
        response = requests.get(f"{API_BASE}/signals/feed?status=closed&limit=50", timeout=10)
        if response.status_code == 200:
            data = response.json()
            signals = data.get('signals', [])
            
            print(f"   ✅ Response received: {len(signals)} signals")
            
            # Verify all signals have status "closed"
            non_closed = [s for s in signals if s.get('status') != 'closed']
            if not non_closed:
                print(f"   ✅ All {len(signals)} signals have status 'closed'")
                results["tests_passed"] += 1
                results["test_details"].append(f"status=closed returns only closed signals ({len(signals)} found)")
            else:
                print(f"   ❌ Found {len(non_closed)} non-closed signals in closed feed")
                results["tests_failed"] += 1
                results["critical_issues"].append(f"status=closed contains non-closed signals")
                
        else:
            print(f"   ❌ API Error: {response.status_code} - {response.text}")
            results["tests_failed"] += 1
            results["critical_issues"].append(f"status=closed endpoint failed: {response.status_code}")
            
    except Exception as e:
        print(f"   ❌ Exception: {str(e)}")
        results["tests_failed"] += 1
        results["critical_issues"].append(f"status=closed endpoint exception: {str(e)}")
    
    # Test 5: Pagination with rejected signals - Verify rejected signals appear with higher offset
    print("\n5. Testing pagination - Verify rejected signals appear with higher offset")
    try:
        response = requests.get(f"{API_BASE}/signals/feed?status=all&limit=50&offset=130", timeout=10)
        if response.status_code == 200:
            data = response.json()
            signals = data.get('signals', [])
            
            print(f"   ✅ Response received: {len(signals)} signals with offset=130")
            
            # Count rejected signals in this page
            rejected_in_page = [s for s in signals if s.get('status') == 'rejected']
            print(f"   📊 Rejected signals in this page: {len(rejected_in_page)}")
            
            if len(rejected_in_page) > 0:
                print(f"   ✅ Found {len(rejected_in_page)} rejected signals with offset=130")
                results["tests_passed"] += 1
                results["test_details"].append(f"Pagination works: {len(rejected_in_page)} rejected signals at offset=130")
            else:
                print(f"   ⚠️  No rejected signals found at offset=130 (may be normal depending on data)")
                
        else:
            print(f"   ❌ API Error: {response.status_code} - {response.text}")
            results["tests_failed"] += 1
            results["critical_issues"].append(f"Pagination endpoint failed: {response.status_code}")
            
    except Exception as e:
        print(f"   ❌ Exception: {str(e)}")
        results["tests_failed"] += 1
        results["critical_issues"].append(f"Pagination endpoint exception: {str(e)}")
    
    # Test 6: /api/signals/feed/stats - Should show correct counts
    print("\n6. Testing /api/signals/feed/stats - Should show correct counts")
    try:
        response = requests.get(f"{API_BASE}/signals/feed/stats", timeout=10)
        if response.status_code == 200:
            data = response.json()
            
            print(f"   ✅ Stats response received")
            print(f"   📊 Stats data: {json.dumps(data, indent=2)}")
            
            # Check if rejected count is present and > 0
            rejected_count = data.get('rejected', 0)
            if rejected_count > 0:
                print(f"   ✅ CRITICAL: Stats show {rejected_count} rejected signals")
                results["tests_passed"] += 1
                results["test_details"].append(f"Stats endpoint shows {rejected_count} rejected signals")
            else:
                print(f"   ❌ CRITICAL: Stats show 0 rejected signals")
                results["tests_failed"] += 1
                results["critical_issues"].append("Stats endpoint shows 0 rejected signals")
                
        else:
            print(f"   ❌ API Error: {response.status_code} - {response.text}")
            results["tests_failed"] += 1
            results["critical_issues"].append(f"Stats endpoint failed: {response.status_code}")
            
    except Exception as e:
        print(f"   ❌ Exception: {str(e)}")
        results["tests_failed"] += 1
        results["critical_issues"].append(f"Stats endpoint exception: {str(e)}")
    
    # Summary
    print("\n" + "=" * 60)
    print("🎯 SIGNAL FEED REJECTED SIGNALS TEST SUMMARY")
    print("=" * 60)
    print(f"✅ Tests Passed: {results['tests_passed']}")
    print(f"❌ Tests Failed: {results['tests_failed']}")
    
    if results["critical_issues"]:
        print(f"\n🚨 CRITICAL ISSUES FOUND:")
        for issue in results["critical_issues"]:
            print(f"   - {issue}")
    
    if results["test_details"]:
        print(f"\n📋 TEST DETAILS:")
        for detail in results["test_details"]:
            print(f"   - {detail}")
    
    return results

def main():
    """Main test execution"""
    print("🚀 PropSignal Engine Backend API Testing")
    print("Testing Signal Feed API - REJECTED signals inclusion")
    print("=" * 60)
    
    # Test signal feed rejected signals functionality
    results = test_signal_feed_rejected_signals()
    
    # Overall result
    total_tests = results["tests_passed"] + results["tests_failed"]
    success_rate = (results["tests_passed"] / total_tests * 100) if total_tests > 0 else 0
    
    print(f"\n🏆 OVERALL RESULT: {results['tests_passed']}/{total_tests} tests passed ({success_rate:.1f}%)")
    
    if results["critical_issues"]:
        print("❌ CRITICAL ISSUES REQUIRE IMMEDIATE ATTENTION")
        return False
    else:
        print("✅ ALL CRITICAL TESTS PASSED")
        return True

if __name__ == "__main__":
    success = main()
    sys.exit(0 if success else 1)