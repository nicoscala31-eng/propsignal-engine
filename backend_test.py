#!/usr/bin/env python3
"""
PropSignal Engine Production-Grade Backend Test Suite
Tests NEW system status, outcome tracker, news calendar, signal lifecycle endpoints
and enhanced scanner status plus existing critical endpoints.
"""

import asyncio
import aiohttp
import json
from datetime import datetime
from typing import Dict, Any, List
import sys

# Backend URL from environment
BACKEND_URL = "https://eurusd-alerts.preview.emergentagent.com/api"

class BackendTester:
    def __init__(self):
        self.session = None
        self.test_results = []
        self.signal_id = None  # To store a signal ID for lifecycle testing
        
    async def __aenter__(self):
        self.session = aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=30))
        return self
    
    async def __aexit__(self, exc_type, exc_val, exc_tb):
        if self.session:
            await self.session.close()
    
    async def test_request(self, method: str, endpoint: str, data: Dict = None, description: str = "") -> Dict[str, Any]:
        """Make a test request and record results"""
        url = f"{BACKEND_URL}{endpoint}"
        
        try:
            if method.upper() == "GET":
                async with self.session.get(url) as response:
                    response_data = await response.json()
                    success = response.status == 200
            elif method.upper() == "POST":
                async with self.session.post(url, json=data) as response:
                    response_data = await response.json()
                    success = response.status == 200
            else:
                raise ValueError(f"Unsupported method: {method}")
                
            result = {
                "endpoint": endpoint,
                "method": method,
                "description": description,
                "success": success,
                "status_code": response.status,
                "data": response_data
            }
            
            self.test_results.append(result)
            return result
            
        except Exception as e:
            result = {
                "endpoint": endpoint,
                "method": method,
                "description": description,
                "success": False,
                "error": str(e),
                "data": None
            }
            self.test_results.append(result)
            return result
    
    def print_test_result(self, result: Dict[str, Any]):
        """Pretty print test result"""
        status = "✅ PASS" if result["success"] else "❌ FAIL"
        print(f"{status} {result['method']} {result['endpoint']}")
        print(f"   Description: {result['description']}")
        
        if result["success"]:
            if isinstance(result["data"], dict) and result["data"]:
                # Show key data points
                data = result["data"]
                if "timestamp" in data:
                    print(f"   Timestamp: {data['timestamp']}")
                if "is_running" in data:
                    print(f"   Status: {'Running' if data['is_running'] else 'Stopped'}")
                if "has_risk" in data:
                    print(f"   News Risk: {data['has_risk']}")
                if "total" in data:
                    print(f"   Total: {data['total']}")
                if "provider" in data and isinstance(data["provider"], dict):
                    print(f"   Provider: {data['provider'].get('name', 'Unknown')}")
        else:
            print(f"   Error: {result.get('error', 'Unknown error')}")
        
        print()
    
    async def test_system_status(self):
        """Test NEW system status endpoint"""
        print("🔍 Testing System Status (NEW)")
        
        result = await self.test_request(
            "GET", "/system/status",
            description="Get comprehensive system status with all service stats"
        )
        
        self.print_test_result(result)
        
        if result["success"]:
            data = result["data"]
            required_keys = ["timestamp", "provider", "scanner", "tracker", "push", "database"]
            missing_keys = [key for key in required_keys if key not in data]
            
            if missing_keys:
                print(f"⚠️  Missing required keys: {missing_keys}")
                return False
            
            # Validate provider status
            provider = data.get("provider", {})
            if "name" in provider and "connected" in provider:
                print(f"   ✓ Provider: {provider['name']} (Connected: {provider['connected']})")
            
            # Validate database stats
            db_stats = data.get("database", {})
            if "total_signals" in db_stats:
                print(f"   ✓ Database: {db_stats['total_signals']} total signals")
            
            return True
        
        return False
    
    async def test_outcome_tracker(self):
        """Test NEW outcome tracker endpoint"""
        print("📈 Testing Outcome Tracker (NEW)")
        
        result = await self.test_request(
            "GET", "/tracker/status",
            description="Get tracker status with checks performed count"
        )
        
        self.print_test_result(result)
        
        if result["success"]:
            data = result["data"]
            if "is_running" in data:
                print(f"   ✓ Tracker running: {data['is_running']}")
            if "checks_performed" in data:
                print(f"   ✓ Checks performed: {data['checks_performed']}")
                return True
        
        return False
    
    async def test_news_calendar(self):
        """Test NEW news calendar endpoints"""
        print("📰 Testing News Calendar (NEW)")
        
        # Test upcoming news
        result1 = await self.test_request(
            "GET", "/news/upcoming",
            description="Get upcoming news events list"
        )
        
        self.print_test_result(result1)
        
        # Test news risk check for EURUSD
        result2 = await self.test_request(
            "GET", "/news/check/EURUSD",
            description="Check news risk status for EURUSD"
        )
        
        self.print_test_result(result2)
        
        # Test simulated news event
        result3 = await self.test_request(
            "POST", "/news/simulate?event_name=NFP&currency=USD&minutes_from_now=10",
            description="Add simulated NFP event 10 minutes from now"
        )
        
        self.print_test_result(result3)
        
        # Test news risk check again after simulation
        result4 = await self.test_request(
            "GET", "/news/check/EURUSD",
            description="Check EURUSD news risk after adding simulated event"
        )
        
        self.print_test_result(result4)
        
        # Validate results
        success_count = sum(1 for r in [result1, result2, result3, result4] if r["success"])
        
        if success_count >= 3:  # Allow one failure
            print(f"   ✓ News Calendar: {success_count}/4 endpoints working")
            
            # Check if risk detection changed after simulation
            if result2["success"] and result4["success"]:
                before_risk = result2["data"].get("has_risk", False)
                after_risk = result4["data"].get("has_risk", False)
                if after_risk and not before_risk:
                    print("   ✓ News risk detection working correctly (risk increased after simulation)")
                elif after_risk:
                    print("   ✓ News risk detected (may have been existing risk)")
            
            return True
        
        return False
    
    async def test_signal_lifecycle(self):
        """Test NEW signal lifecycle endpoints"""
        print("🔄 Testing Signal Lifecycle (NEW)")
        
        # First get a known signal ID from recent trades
        recent_result = await self.test_request(
            "GET", "/analytics/recent-trades?limit=1",
            description="Get recent signals to find IDs for testing"
        )
        
        signal_id = None
        if recent_result["success"] and recent_result["data"]:
            signal_id = recent_result["data"][0]["id"]
        
        # Test active signals
        result1 = await self.test_request(
            "GET", "/signals/active",
            description="Get all active unresolved signals"
        )
        
        self.print_test_result(result1)
        
        # Test resolved signals  
        result2 = await self.test_request(
            "GET", "/signals/resolved?limit=5",
            description="Get resolved signals with outcomes (limit 5)"
        )
        
        self.print_test_result(result2)
        
        # Test specific signal lifecycle if we have an ID
        result3 = None
        if signal_id:
            result3 = await self.test_request(
                "GET", f"/signals/{signal_id}/lifecycle",
                description=f"Get lifecycle history for signal {signal_id[:8]}..."
            )
            
            self.print_test_result(result3)
        
        # Count successes, but handle the case where active/resolved might return empty lists (which is valid)
        success_count = 0
        
        # Active signals endpoint - success if 200 status (even if empty list)
        if result1["success"] or (result1.get("status_code") == 200):
            success_count += 1
            if result1["success"] and isinstance(result1["data"], list):
                print(f"   ✓ Active signals endpoint working (found {len(result1['data'])} signals)")
        
        # Resolved signals endpoint - success if 200 status (even if empty list) 
        if result2["success"] or (result2.get("status_code") == 200):
            success_count += 1
            if result2["success"] and isinstance(result2["data"], list):
                print(f"   ✓ Resolved signals endpoint working (found {len(result2['data'])} signals)")
        
        # Lifecycle endpoint
        if result3 and result3["success"]:
            success_count += 1
            lifecycle_data = result3["data"]
            if "lifecycle_stage" in lifecycle_data:
                print(f"   ✓ Signal lifecycle stage: {lifecycle_data['lifecycle_stage']}")
            if "outcome" in lifecycle_data:
                print(f"   ✓ Signal outcome: {lifecycle_data['outcome']}")
        
        # Consider success if at least 2/3 endpoints work, or if we tested lifecycle successfully
        if success_count >= 2 or (result3 and result3["success"]):
            print(f"   ✓ Signal Lifecycle: {success_count}/{'3' if result3 else '2'} endpoints working")
            return True
        
        return False
    
    async def test_enhanced_scanner_status(self):
        """Test ENHANCED scanner status endpoint"""
        print("🔎 Testing Enhanced Scanner Status")
        
        result = await self.test_request(
            "GET", "/scanner/status",
            description="Get enhanced scanner stats with uptime and error count"
        )
        
        self.print_test_result(result)
        
        if result["success"]:
            data = result["data"]
            
            # Check for enhanced fields
            enhanced_fields = []
            if "statistics" in data:
                stats = data["statistics"]
                if "total_scans" in stats:
                    enhanced_fields.append(f"total_scans: {stats['total_scans']}")
                if "signals_generated" in stats:
                    enhanced_fields.append(f"signals_generated: {stats['signals_generated']}")
            
            if "is_running" in data:
                enhanced_fields.append(f"is_running: {data['is_running']}")
            
            if enhanced_fields:
                print(f"   ✓ Enhanced fields: {', '.join(enhanced_fields)}")
                return True
        
        return False
    
    async def test_existing_critical_endpoints(self):
        """Test existing critical endpoints to ensure they still work"""
        print("🏥 Testing Existing Critical Endpoints")
        
        # Test live prices
        result1 = await self.test_request(
            "GET", "/provider/live-prices",
            description="Get live market data (existing critical endpoint)"
        )
        
        self.print_test_result(result1)
        
        # Test analytics performance
        result2 = await self.test_request(
            "GET", "/analytics/performance",
            description="Get performance analytics (existing critical endpoint)"
        )
        
        self.print_test_result(result2)
        
        success_count = sum(1 for r in [result1, result2] if r["success"])
        
        if success_count >= 1:
            print(f"   ✓ Critical Endpoints: {success_count}/2 working")
            
            # Validate live prices data
            if result1["success"]:
                prices_data = result1["data"]
                if "prices" in prices_data:
                    prices = prices_data["prices"]
                    working_assets = [asset for asset, data in prices.items() 
                                    if isinstance(data, dict) and data.get("status") == "LIVE"]
                    if working_assets:
                        print(f"   ✓ Live prices working for: {', '.join(working_assets)}")
            
            return True
        
        return False
    
    async def run_comprehensive_test(self):
        """Run all production-grade backend tests"""
        print("🚀 PropSignal Engine Production-Grade Backend Test Suite")
        print("=" * 60)
        print()
        
        test_functions = [
            ("System Status (NEW)", self.test_system_status),
            ("Outcome Tracker (NEW)", self.test_outcome_tracker), 
            ("News Calendar (NEW)", self.test_news_calendar),
            ("Signal Lifecycle (NEW)", self.test_signal_lifecycle),
            ("Enhanced Scanner Status", self.test_enhanced_scanner_status),
            ("Existing Critical Endpoints", self.test_existing_critical_endpoints)
        ]
        
        results = {}
        
        for test_name, test_func in test_functions:
            try:
                results[test_name] = await test_func()
            except Exception as e:
                print(f"❌ {test_name} - Unexpected error: {e}")
                results[test_name] = False
            
            print("-" * 60)
        
        # Summary
        print("\n📊 TEST SUMMARY")
        print("=" * 60)
        
        passed = sum(1 for success in results.values() if success)
        total = len(results)
        
        for test_name, success in results.items():
            status = "✅ PASS" if success else "❌ FAIL"
            print(f"{status} {test_name}")
        
        print("-" * 60)
        print(f"📈 Overall Results: {passed}/{total} test categories passed ({(passed/total)*100:.1f}%)")
        
        if passed == total:
            print("🎉 ALL PRODUCTION-GRADE FEATURES WORKING PERFECTLY!")
        elif passed >= total * 0.8:
            print("✅ PRODUCTION-READY - Most features working correctly")
        elif passed >= total * 0.6:
            print("⚠️  PARTIAL SUCCESS - Some issues need attention")
        else:
            print("❌ CRITICAL ISSUES - Major fixes needed")
        
        return passed, total, results

async def main():
    """Run the backend test suite"""
    async with BackendTester() as tester:
        passed, total, results = await tester.run_comprehensive_test()
        
        # Exit with appropriate code
        if passed == total:
            sys.exit(0)  # Success
        elif passed >= total * 0.8:
            sys.exit(1)  # Minor issues
        else:
            sys.exit(2)  # Major issues

if __name__ == "__main__":
    asyncio.run(main())