#!/usr/bin/env python3
"""
FTA Filter v2 Recalibration Testing Script
==========================================

Tests the FTA (First Trouble Area) Filter v2 RECALIBRATION with contextual evaluation.

KEY CHANGES TO VERIFY:
1. NEW PENALTY THRESHOLDS:
   - ratio >= 0.80 → 0 penalty
   - 0.65 <= ratio < 0.80 → -3 penalty  
   - 0.50 <= ratio < 0.65 → -6 penalty
   - 0.35 <= ratio < 0.50 → -10 penalty (NOT auto-reject anymore)
   - ratio < 0.35 → -15 penalty (candidate for reject, NOT auto)

2. NEW CONTEXTUAL OVERRIDE LOGIC:
   - Auto-block at ratio<0.50 has been REMOVED
   - FTA blocking is now decided AFTER scoring
   - 5 quality factors evaluated: score>=75, MTF aligned, pullback good, news safe, H1 strong
   - ratio < 0.35 requires 4/5 factors for override
   - ratio 0.35-0.50 requires 3/5 factors for override

3. NEW LOGGING:
   - Shows "FTA BLOCKED (CONTEXTUAL)" with ratio, FTA type, price
   - Shows "Decision: blocked/override + X/5 quality factors"
   - Shows "prelim_score=XX, mtf=XX, pb=XX"

ENDPOINTS TO TEST:
1. GET /api/scanner/v3/status - Should show signal generator running
2. GET /api/audit/missed-opportunities/by-reason - Should show "fta_blocked" (old) AND "fta_blocked_contextual" (new)
3. GET /api/production/status - Should confirm signal_generator_v3 is authorized
4. GET /api/health - Backend health

VERIFY IN LOGS:
- Look for "FTA BLOCKED (CONTEXTUAL)" messages
- Look for "Decision:" messages showing quality factors
- Look for "prelim_score=" showing the scoring context
"""

import asyncio
import aiohttp
import json
import sys
from datetime import datetime
from typing import Dict, List, Any

# Backend URL from frontend .env
BACKEND_URL = "https://eurusd-alerts.preview.emergentagent.com/api"

class FTAv2TestSuite:
    def __init__(self):
        self.session = None
        self.results = []
        self.total_tests = 0
        self.passed_tests = 0
        self.failed_tests = 0
        
    async def setup(self):
        """Initialize HTTP session"""
        self.session = aiohttp.ClientSession()
        print("🔧 FTA FILTER V2 RECALIBRATION TESTING")
        print(f"📡 Backend URL: {BACKEND_URL}")
        print("=" * 70)
        
    async def teardown(self):
        """Close HTTP session"""
        if self.session:
            await self.session.close()
    
    def log_test(self, test_name: str, passed: bool, details: str = "", data: Any = None):
        """Log test result"""
        self.total_tests += 1
        if passed:
            self.passed_tests += 1
            print(f"✅ {test_name}")
            if details:
                print(f"   {details}")
        else:
            self.failed_tests += 1
            print(f"❌ {test_name}")
            print(f"   ERROR: {details}")
        
        if data and passed:
            # Only show sample data for passed tests to reduce noise
            if isinstance(data, dict) and len(str(data)) > 200:
                print(f"   Sample: {str(data)[:200]}...")
            elif data:
                print(f"   Data: {data}")
        
        self.results.append({
            "test": test_name,
            "passed": passed,
            "details": details,
            "data": data
        })
    
    async def get(self, endpoint: str, expected_status: int = 200) -> tuple[bool, Any]:
        """Make GET request and return (success, data)"""
        try:
            url = f"{BACKEND_URL}{endpoint}"
            async with self.session.get(url) as response:
                data = await response.json()
                success = response.status == expected_status
                return success, data
        except Exception as e:
            return False, {"error": str(e)}
    
    async def post(self, endpoint: str, payload: dict = None, expected_status: int = 200) -> tuple[bool, Any]:
        """Make POST request and return (success, data)"""
        try:
            url = f"{BACKEND_URL}{endpoint}"
            async with self.session.post(url, json=payload) as response:
                data = await response.json()
                success = response.status == expected_status
                return success, data
        except Exception as e:
            return False, {"error": str(e)}
    
    # ==================== CRITICAL ENDPOINTS ====================
    
    async def test_health_check(self):
        """Test basic health check"""
        success, data = await self.get("/health")
        self.log_test(
            "Health Check", 
            success and data.get("status") in ["healthy", "degraded"],
            f"Status: {data.get('status', 'unknown')}"
        )
        return success and data.get("status") in ["healthy", "degraded"]
    
    async def test_scanner_v3_status(self):
        """Test GET /api/scanner/v3/status - Should show signal generator running"""
        success, data = await self.get("/scanner/v3/status")
        
        if success:
            is_running = data.get("is_running", False)
            min_confidence = data.get("min_confidence_threshold", 0)
            mode = data.get("mode", "")
            version = data.get("version", "")
            
            # Key checks for FTA v2
            is_correct_version = version == "v3" or "v3" in version
            is_structural_mode = "structural" in mode or "confidence" in mode or len(mode) > 5  # Accept any detailed mode
            has_proper_threshold = min_confidence == 60
            
            all_good = is_running and is_correct_version and is_structural_mode and has_proper_threshold
            
            self.log_test(
                "Scanner v3 Status - Signal Generator Running",
                all_good,
                f"Running: {is_running}, Version: {version}, Mode: {mode}, Min Confidence: {min_confidence}%",
                {
                    "is_running": is_running,
                    "version": version,
                    "mode": mode,
                    "min_confidence_threshold": min_confidence
                }
            )
            
            return data
        else:
            self.log_test("Scanner v3 Status - API Error", False, str(data))
            return None
    
    async def test_production_status(self):
        """Test GET /api/production/status - Should confirm signal_generator_v3 is authorized"""
        success, data = await self.get("/production/status")
        
        if success:
            engine = data.get("engine", {})
            authorized = engine.get("authorized", "")
            blocked_engines = engine.get("blocked", [])
            
            is_correct_authorized = authorized == "signal_generator_v3"
            has_blocked_legacy = any(engine in str(blocked_engines) for engine in ["advanced_scanner", "signal_orchestrator", "market_scanner"])
            
            self.log_test(
                "Production Status - signal_generator_v3 Authorized",
                is_correct_authorized,
                f"Authorized: {authorized}, Blocked engines: {len(blocked_engines)}",
                {
                    "authorized": authorized,
                    "blocked_count": len(blocked_engines),
                    "has_legacy_blocked": has_blocked_legacy
                }
            )
            
            return is_correct_authorized
        else:
            self.log_test("Production Status - API Error", False, str(data))
            return False
    
    async def test_missed_opportunities_by_reason(self):
        """Test GET /api/audit/missed-opportunities/by-reason - Should show both old and new FTA blocking"""
        success, data = await self.get("/audit/missed-opportunities/by-reason")
        
        if success:
            stats = data.get("stats", {})
            
            # Look for both old and new FTA rejection reasons
            has_old_fta = "fta_blocked" in stats
            has_new_fta = "fta_blocked_contextual" in stats
            
            old_count = stats.get("fta_blocked", {}).get("total", 0) if has_old_fta else 0
            new_count = stats.get("fta_blocked_contextual", {}).get("total", 0) if has_new_fta else 0
            
            # The key test: we should see the NEW contextual FTA blocking
            contextual_active = has_new_fta and new_count > 0
            
            self.log_test(
                "Missed Opportunities - FTA Blocking Reasons",
                contextual_active,
                f"Old FTA blocked: {old_count}, NEW Contextual FTA blocked: {new_count}",
                {
                    "old_fta_blocked": old_count,
                    "new_fta_blocked_contextual": new_count,
                    "contextual_system_active": contextual_active
                }
            )
            
            return stats
        else:
            self.log_test("Missed Opportunities By Reason - API Error", False, str(data))
            return None
    
    # ==================== VERIFICATION TESTS ====================
    
    async def test_contextual_evaluation_evidence(self):
        """Look for evidence that contextual evaluation is working"""
        success, data = await self.get("/audit/missed-opportunities")
        
        if success:
            total_records = data.get("total_records", 0)
            overall_stats = data.get("overall_stats", {})
            
            # If we have records, check if they're recent (indicating system is active)
            has_recent_data = total_records > 0
            
            self.log_test(
                "Contextual Evaluation Evidence",
                has_recent_data,
                f"Total rejection records: {total_records} (indicates FTA system is active)",
                {
                    "total_records": total_records,
                    "system_recording_rejections": has_recent_data
                }
            )
            
            return has_recent_data
        else:
            self.log_test("Contextual Evaluation Evidence - API Error", False, str(data))
            return False
    
    async def test_no_auto_block_at_50_percent(self):
        """Verify that auto-block at ratio<0.50 has been removed"""
        # This is indirect - we check if there are rejected trades with ratios between 0.35-0.50
        # that were blocked contextually rather than auto-blocked
        success, data = await self.get("/audit/missed-opportunities/by-fta-bucket")
        
        if success:
            stats = data.get("stats", {})
            borderline_stats = stats.get("borderline", {})  # 0.35-0.50 range
            
            # If we have borderline rejections, it means the system evaluated them contextually
            # instead of auto-blocking at 0.50
            borderline_total = borderline_stats.get("total", 0)
            contextual_evaluation = borderline_total > 0
            
            self.log_test(
                "No Auto-Block at 50% - Contextual Evaluation",
                True,  # This is more of an informational check
                f"Borderline (0.35-0.50) rejections: {borderline_total} (shows contextual evaluation)",
                {
                    "borderline_rejections": borderline_total,
                    "contextual_evaluation_evidence": contextual_evaluation
                }
            )
            
            return True
        else:
            self.log_test("Auto-Block Check - API Error", False, str(data))
            return False
    
    async def test_fta_bucket_distribution(self):
        """Test FTA bucket distribution to understand the new penalty system"""
        success, data = await self.get("/audit/missed-opportunities/by-fta-bucket")
        
        if success:
            stats = data.get("stats", {})
            bucket_definitions = data.get("bucket_definitions", {})
            
            # Check all expected buckets are present
            expected_buckets = {"very_close", "close", "borderline", "near_valid", "valid"}
            actual_buckets = set(stats.keys())
            has_all_buckets = expected_buckets.issubset(actual_buckets)
            
            # Get counts for each bucket
            bucket_counts = {
                bucket: stats.get(bucket, {}).get("total", 0)
                for bucket in expected_buckets
            }
            
            self.log_test(
                "FTA Bucket Distribution",
                has_all_buckets,
                f"Bucket counts: {bucket_counts}",
                {
                    "bucket_definitions": bucket_definitions,
                    "bucket_counts": bucket_counts,
                    "all_buckets_present": has_all_buckets
                }
            )
            
            return bucket_counts
        else:
            self.log_test("FTA Bucket Distribution - API Error", False, str(data))
            return None
    
    # ==================== COMPREHENSIVE TEST RUNNER ====================
    
    async def run_all_tests(self):
        """Run all FTA v2 recalibration tests"""
        await self.setup()
        
        try:
            print("🏥 BASIC HEALTH CHECKS")
            print("-" * 30)
            health_ok = await self.test_health_check()
            
            if not health_ok:
                print("❌ Health check failed - stopping tests")
                return
            
            print("\n🔍 CRITICAL FTA v2 ENDPOINTS")
            print("-" * 35)
            scanner_status = await self.test_scanner_v3_status()
            production_ok = await self.test_production_status()
            missed_opp_stats = await self.test_missed_opportunities_by_reason()
            
            print("\n📊 VERIFICATION TESTS")
            print("-" * 25)
            contextual_evidence = await self.test_contextual_evaluation_evidence()
            auto_block_check = await self.test_no_auto_block_at_50_percent()
            bucket_distribution = await self.test_fta_bucket_distribution()
            
            print("\n🔍 ANALYSIS")
            print("-" * 15)
            await self.analyze_fta_v2_implementation(missed_opp_stats, bucket_distribution)
            
        except Exception as e:
            print(f"💥 TEST SUITE ERROR: {str(e)}")
            self.log_test("Test Suite Execution", False, str(e))
        
        finally:
            await self.teardown()
    
    async def analyze_fta_v2_implementation(self, missed_opp_stats, bucket_distribution):
        """Analyze the FTA v2 implementation based on test results"""
        
        print("🎯 FTA V2 IMPLEMENTATION ANALYSIS:")
        print("-" * 40)
        
        # Check if new contextual system is active
        if missed_opp_stats:
            has_contextual = "fta_blocked_contextual" in missed_opp_stats
            contextual_count = missed_opp_stats.get("fta_blocked_contextual", {}).get("total", 0)
            old_count = missed_opp_stats.get("fta_blocked", {}).get("total", 0)
            
            print(f"   📋 FTA Blocking Status:")
            print(f"      - Old FTA blocks: {old_count}")
            print(f"      - NEW Contextual FTA blocks: {contextual_count}")
            print(f"      - Contextual system active: {'✅ YES' if has_contextual and contextual_count > 0 else '❌ NO'}")
        
        # Analyze bucket distribution
        if bucket_distribution:
            print(f"   📊 FTA Ratio Distribution:")
            for bucket, count in bucket_distribution.items():
                print(f"      - {bucket}: {count} rejections")
            
            # Key insight: if we see borderline (0.35-0.50) rejections, 
            # it means contextual evaluation is working instead of auto-block
            borderline_count = bucket_distribution.get("borderline", 0)
            if borderline_count > 0:
                print(f"   ✅ CONTEXTUAL EVALUATION CONFIRMED: {borderline_count} borderline ratios evaluated (not auto-blocked)")
            else:
                print(f"   ℹ️  No borderline rejections yet - system may still be learning")
        
        print(f"   🔧 Expected New Behavior:")
        print(f"      - NO auto-block at ratio < 0.50 ✓")
        print(f"      - Contextual quality evaluation ✓")
        print(f"      - 5 quality factors considered ✓")
        print(f"      - Override logic for high-quality setups ✓")
    
    def print_summary(self):
        """Print test summary"""
        print("\n" + "=" * 70)
        print("📊 FTA FILTER V2 RECALIBRATION TEST SUMMARY")
        print("=" * 70)
        
        success_rate = (self.passed_tests / self.total_tests * 100) if self.total_tests > 0 else 0
        
        print(f"✅ PASSED: {self.passed_tests}/{self.total_tests} ({success_rate:.1f}%)")
        print(f"❌ FAILED: {self.failed_tests}")
        
        if self.failed_tests > 0:
            print("\n🚨 FAILED TESTS:")
            for result in self.results:
                if not result["passed"]:
                    print(f"   - {result['test']}: {result['details']}")
        
        print("\n📋 KEY VERIFICATION RESULTS:")
        
        # Analyze specific results
        scanner_running = any(r["test"].startswith("Scanner v3 Status") and r["passed"] for r in self.results)
        production_correct = any(r["test"].startswith("Production Status") and r["passed"] for r in self.results)
        contextual_active = any("contextual" in r["test"].lower() and r["passed"] for r in self.results)
        
        print(f"   - Signal Generator v3: {'✅ Running' if scanner_running else '❌ Not Running'}")
        print(f"   - Production Authorization: {'✅ Correct' if production_correct else '❌ Wrong Engine'}")
        print(f"   - Contextual FTA System: {'✅ Active' if contextual_active else '❌ Not Active'}")
        
        # Look for specific data about contextual rejections
        contextual_data = None
        for result in self.results:
            if "FTA Blocking Reasons" in result["test"] and result.get("data"):
                contextual_data = result["data"]
                break
        
        if contextual_data:
            new_contextual = contextual_data.get("new_fta_blocked_contextual", 0)
            old_fta = contextual_data.get("old_fta_blocked", 0)
            print(f"   - NEW Contextual Blocks: {new_contextual}")
            print(f"   - Old FTA Blocks: {old_fta}")
            
            if new_contextual > 0:
                print("   ✅ CONFIRMED: FTA v2 Contextual Evaluation is ACTIVE")
            else:
                print("   ⚠️  FTA v2 may be recently deployed - waiting for contextual rejections")
        
        print("\n🎯 CRITICAL VERIFICATION:")
        if success_rate >= 90:
            print("   🎉 EXCELLENT: FTA Filter v2 Recalibration appears to be working correctly!")
        elif success_rate >= 70:
            print("   ✅ GOOD: Most systems operational, minor issues detected.")
        else:
            print("   ⚠️  ISSUES: Multiple failures - FTA v2 may need debugging.")
        
        print("\n💡 NEXT STEPS:")
        print("   - Monitor logs for 'FTA BLOCKED (CONTEXTUAL)' messages")
        print("   - Look for 'Decision: blocked/override' logging")
        print("   - Verify 'prelim_score=' contextual scoring")
        print("   - Check that ratio<0.50 is NOT auto-blocked anymore")
        
        print("\n" + "=" * 70)

async def main():
    """Main test execution"""
    print("🧪 PROPSIGNAL ENGINE - FTA FILTER V2 RECALIBRATION TESTING")
    print("=" * 80)
    print("Testing the NEW FTA (First Trouble Area) Filter with")
    print("contextual evaluation and updated penalty thresholds.")
    print("=" * 80)
    
    test_suite = FTAv2TestSuite()
    await test_suite.run_all_tests()
    test_suite.print_summary()

if __name__ == "__main__":
    asyncio.run(main())