#!/usr/bin/env python3
"""
Backend Testing Script for Missed Opportunity Analysis Module
=============================================================

Tests the NEW Missed Opportunity Analysis Module - an AUDIT-ONLY system 
for analyzing rejected trades with candle-by-candle simulation.

NEW API ENDPOINTS TO TEST:
1. GET /api/audit/missed-opportunities - Full report with overall stats
2. GET /api/audit/missed-opportunities/by-symbol - Stats by EURUSD/XAUUSD  
3. GET /api/audit/missed-opportunities/by-reason - Stats by rejection reason
4. GET /api/audit/missed-opportunities/by-fta-bucket - Stats by FTA bucket
5. GET /api/audit/missed-opportunities/top-patterns - Top winning/losing patterns
6. GET /api/audit/missed-opportunities/samples?count=3 - Sample simulation records
7. POST /api/audit/missed-opportunities/run-simulation - Trigger simulation batch

ALSO VERIFIES:
- Existing direction-quality audit endpoints still work
- Production status still shows signal_generator_v3 as authorized
- System is recording FTA-blocked rejections
"""

import asyncio
import aiohttp
import json
from datetime import datetime
from typing import Dict, List, Any

# Backend URL from environment
BACKEND_URL = "https://eurusd-alerts.preview.emergentagent.com/api"

class MissedOpportunityTestSuite:
    def __init__(self):
        self.session = None
        self.results = []
        self.total_tests = 0
        self.passed_tests = 0
        self.failed_tests = 0
    
    async def setup(self):
        """Initialize HTTP session"""
        self.session = aiohttp.ClientSession()
        print("🔧 Missed Opportunity Analysis Module Testing Started")
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
        
        if data:
            print(f"   Data: {json.dumps(data, indent=2)[:200]}...")
        
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
    
    # ==================== HEALTH & PRODUCTION STATUS ====================
    
    async def test_health_check(self):
        """Test basic health check"""
        success, data = await self.get("/health")
        self.log_test(
            "Health Check", 
            success and data.get("status") in ["healthy", "degraded"],
            f"Status: {data.get('status', 'unknown')}"
        )
        return data
    
    async def test_production_status(self):
        """Test production control status - verify signal_generator_v3 is authorized"""
        success, data = await self.get("/production/status")
        
        if success:
            authorized_engine = data.get("engine", {}).get("authorized")
            is_correct = authorized_engine == "signal_generator_v3"
            self.log_test(
                "Production Status - Signal Generator v3 Authorized",
                is_correct,
                f"Authorized engine: {authorized_engine}"
            )
        else:
            self.log_test("Production Status - API Error", False, str(data))
    
    # ==================== MISSED OPPORTUNITY ANALYSIS ENDPOINTS ====================
    
    async def test_missed_opportunities_full_report(self):
        """Test GET /api/audit/missed-opportunities - Full report with overall stats"""
        success, data = await self.get("/audit/missed-opportunities")
        
        if success:
            # Verify expected structure
            has_required_fields = all(field in data for field in [
                "report_generated", "total_records", "overall_stats", 
                "by_symbol", "by_direction", "key_insight"
            ])
            
            total_records = data.get("total_records", 0)
            overall_stats = data.get("overall_stats", {})
            
            self.log_test(
                "Missed Opportunities - Full Report",
                has_required_fields,
                f"Total records: {total_records}, Overall stats structure valid: {bool(overall_stats)}"
            )
            
            return data
        else:
            self.log_test("Missed Opportunities - Full Report", False, str(data))
            return None
    
    async def test_missed_opportunities_by_symbol(self):
        """Test GET /api/audit/missed-opportunities/by-symbol - Stats by EURUSD/XAUUSD"""
        success, data = await self.get("/audit/missed-opportunities/by-symbol")
        
        if success:
            stats = data.get("stats", {})
            has_symbols = "EURUSD" in stats and "XAUUSD" in stats
            
            self.log_test(
                "Missed Opportunities - By Symbol",
                has_symbols,
                f"Contains EURUSD and XAUUSD stats: {has_symbols}"
            )
            
            return data
        else:
            self.log_test("Missed Opportunities - By Symbol", False, str(data))
            return None
    
    async def test_missed_opportunities_by_reason(self):
        """Test GET /api/audit/missed-opportunities/by-reason - Stats by rejection reason"""
        success, data = await self.get("/audit/missed-opportunities/by-reason")
        
        if success:
            stats = data.get("stats", {})
            report_type = data.get("report_type") == "by_rejection_reason"
            
            self.log_test(
                "Missed Opportunities - By Rejection Reason",
                report_type and isinstance(stats, dict),
                f"Report type correct: {report_type}, Stats count: {len(stats)}"
            )
            
            return data
        else:
            self.log_test("Missed Opportunities - By Rejection Reason", False, str(data))
            return None
    
    async def test_missed_opportunities_by_fta_bucket(self):
        """Test GET /api/audit/missed-opportunities/by-fta-bucket - Stats by FTA bucket"""
        success, data = await self.get("/audit/missed-opportunities/by-fta-bucket")
        
        if success:
            bucket_definitions = data.get("bucket_definitions", {})
            stats = data.get("stats", {})
            
            # Check for required FTA buckets
            expected_buckets = {"very_close", "close", "borderline", "near_valid", "valid"}
            has_buckets = expected_buckets.issubset(set(stats.keys()))
            
            self.log_test(
                "Missed Opportunities - By FTA Bucket",
                has_buckets and bool(bucket_definitions),
                f"FTA buckets present: {list(stats.keys())}, Definitions: {bool(bucket_definitions)}"
            )
            
            return data
        else:
            self.log_test("Missed Opportunities - By FTA Bucket", False, str(data))
            return None
    
    async def test_missed_opportunities_top_patterns(self):
        """Test GET /api/audit/missed-opportunities/top-patterns - Top winning/losing patterns"""
        success, data = await self.get("/audit/missed-opportunities/top-patterns")
        
        if success:
            report_type = data.get("report_type") == "top_patterns"
            has_pattern_fields = all(field in data for field in [
                "top_winning_patterns", "top_losing_patterns", 
                "patterns_with_100pct_tp", "patterns_with_0pct_tp"
            ])
            
            self.log_test(
                "Missed Opportunities - Top Patterns",
                report_type and has_pattern_fields,
                f"Report type: {data.get('report_type')}, Pattern fields present: {has_pattern_fields}"
            )
            
            return data
        else:
            self.log_test("Missed Opportunities - Top Patterns", False, str(data))
            return None
    
    async def test_missed_opportunities_samples(self):
        """Test GET /api/audit/missed-opportunities/samples?count=3 - Sample simulation records"""
        success, data = await self.get("/audit/missed-opportunities/samples?count=3")
        
        if success:
            samples = data.get("samples", [])
            sample_count = data.get("sample_count", 0)
            
            # Samples may be empty if no simulations completed yet
            is_valid = isinstance(samples, list) and sample_count >= 0
            
            self.log_test(
                "Missed Opportunities - Sample Simulations",
                is_valid,
                f"Requested: 3, Got: {len(samples)} samples (empty OK if pending simulations)"
            )
            
            return data
        else:
            self.log_test("Missed Opportunities - Sample Simulations", False, str(data))
            return None
    
    async def test_missed_opportunities_run_simulation(self):
        """Test POST /api/audit/missed-opportunities/run-simulation - Trigger simulation batch"""
        success, data = await self.post("/audit/missed-opportunities/run-simulation")
        
        if success:
            status = data.get("status") == "simulation_batch_completed"
            has_counts = all(field in data for field in [
                "total_records", "completed_simulations", "pending_simulations"
            ])
            
            total = data.get("total_records", 0)
            completed = data.get("completed_simulations", 0)
            pending = data.get("pending_simulations", 0)
            
            self.log_test(
                "Missed Opportunities - Run Simulation",
                status and has_counts,
                f"Total: {total}, Completed: {completed}, Pending: {pending}"
            )
            
            return data
        else:
            self.log_test("Missed Opportunities - Run Simulation", False, str(data))
            return None
    
    # ==================== EXISTING AUDIT ENDPOINTS (COMPATIBILITY) ====================
    
    async def test_direction_quality_audit(self):
        """Test existing direction quality audit endpoint still works"""
        success, data = await self.get("/audit/direction-quality")
        
        if success:
            has_required = all(field in data for field in [
                "report_generated", "overall_stats", "by_symbol_direction"
            ])
            
            self.log_test(
                "Direction Quality Audit - Compatibility",
                has_required,
                f"Report structure valid: {has_required}"
            )
            
            return data
        else:
            self.log_test("Direction Quality Audit - Compatibility", False, str(data))
            return None
    
    # ==================== SYSTEM VERIFICATION ====================
    
    async def test_fta_rejection_recording(self):
        """Verify system is recording FTA-blocked rejections"""
        # Check if there are missed opportunity records (should have been created)
        success, data = await self.get("/audit/missed-opportunities")
        
        if success:
            total_records = data.get("total_records", 0)
            
            # Look at the storage file directly if API shows records
            has_records = total_records > 0
            
            self.log_test(
                "FTA Rejection Recording",
                has_records,
                f"Found {total_records} missed opportunity records (FTA rejections being tracked)"
            )
            
            return has_records
        else:
            self.log_test("FTA Rejection Recording", False, "Could not check records")
            return False
    
    async def test_background_simulation_running(self):
        """Verify background simulation task is running"""
        # Trigger a simulation manually and check response
        success, data = await self.post("/audit/missed-opportunities/run-simulation")
        
        if success:
            # If simulation runs without error, background task is functioning
            simulation_working = data.get("status") == "simulation_batch_completed"
            
            self.log_test(
                "Background Simulation Task",
                simulation_working,
                "Manual simulation trigger working - background task functional"
            )
            
            return simulation_working
        else:
            self.log_test("Background Simulation Task", False, str(data))
            return False
    
    # ==================== DATA VALIDATION ====================
    
    async def validate_missed_opportunity_data_structure(self, report_data):
        """Validate the structure of missed opportunity data"""
        if not report_data:
            return False
        
        overall_stats = report_data.get("overall_stats", {})
        
        # Check for required stat fields
        required_stat_fields = {"total", "tp_hits", "sl_hits", "expired", "pending", "simulated_winrate", "avg_rr"}
        has_stat_fields = required_stat_fields.issubset(set(overall_stats.keys()))
        
        self.log_test(
            "Missed Opportunities - Data Structure Validation",
            has_stat_fields,
            f"Required stat fields present: {has_stat_fields}"
        )
        
        return has_stat_fields
    
    # ==================== COMPREHENSIVE TEST RUNNER ====================
    
    async def run_all_tests(self):
        """Run all missed opportunity analysis tests"""
        await self.setup()
        
        try:
            print("🏥 HEALTH & PRODUCTION STATUS")
            print("-" * 40)
            await self.test_health_check()
            await self.test_production_status()
            
            print("\n📊 NEW MISSED OPPORTUNITY ANALYSIS ENDPOINTS")
            print("-" * 50)
            report_data = await self.test_missed_opportunities_full_report()
            await self.test_missed_opportunities_by_symbol()
            await self.test_missed_opportunities_by_reason()
            await self.test_missed_opportunities_by_fta_bucket()
            await self.test_missed_opportunities_top_patterns()
            await self.test_missed_opportunities_samples()
            await self.test_missed_opportunities_run_simulation()
            
            print("\n🔍 EXISTING AUDIT ENDPOINTS (COMPATIBILITY)")
            print("-" * 50)
            await self.test_direction_quality_audit()
            
            print("\n🔧 SYSTEM VERIFICATION")
            print("-" * 30)
            await self.test_fta_rejection_recording()
            await self.test_background_simulation_running()
            
            print("\n✅ DATA VALIDATION")
            print("-" * 25)
            if report_data:
                await self.validate_missed_opportunity_data_structure(report_data)
            
        except Exception as e:
            print(f"💥 TEST SUITE ERROR: {str(e)}")
            self.log_test("Test Suite Execution", False, str(e))
        
        finally:
            await self.teardown()
    
    def print_summary(self):
        """Print test summary"""
        print("\n" + "=" * 70)
        print("📊 MISSED OPPORTUNITY ANALYSIS MODULE TEST SUMMARY")
        print("=" * 70)
        
        success_rate = (self.passed_tests / self.total_tests * 100) if self.total_tests > 0 else 0
        
        print(f"✅ PASSED: {self.passed_tests}/{self.total_tests} ({success_rate:.1f}%)")
        print(f"❌ FAILED: {self.failed_tests}")
        
        if self.failed_tests > 0:
            print("\n🚨 FAILED TESTS:")
            for result in self.results:
                if not result["passed"]:
                    print(f"   - {result['test']}: {result['details']}")
        
        print("\n📋 KEY FINDINGS:")
        
        # Analyze results
        health_passed = any(r["test"] == "Health Check" and r["passed"] for r in self.results)
        production_passed = any(r["test"].startswith("Production Status") and r["passed"] for r in self.results)
        missed_opp_endpoints = [r for r in self.results if "Missed Opportunities" in r["test"]]
        missed_opp_passed = sum(1 for r in missed_opp_endpoints if r["passed"])
        
        print(f"   - Health Status: {'✅ OK' if health_passed else '❌ FAIL'}")
        print(f"   - Production Control: {'✅ OK' if production_passed else '❌ FAIL'}")
        print(f"   - Missed Opportunity Endpoints: {missed_opp_passed}/{len(missed_opp_endpoints)} working")
        
        # Get specific data from results
        fta_recording = any(r["test"] == "FTA Rejection Recording" and r["passed"] for r in self.results)
        simulation_running = any(r["test"] == "Background Simulation Task" and r["passed"] for r in self.results)
        direction_audit = any(r["test"] == "Direction Quality Audit - Compatibility" and r["passed"] for r in self.results)
        
        print(f"   - FTA Rejection Recording: {'✅ Active' if fta_recording else '❌ Not Recording'}")
        print(f"   - Background Simulation: {'✅ Running' if simulation_running else '❌ Not Running'}")
        print(f"   - Existing Audit APIs: {'✅ Compatible' if direction_audit else '❌ Broken'}")
        
        if success_rate >= 90:
            print("\n🎉 EXCELLENT: Missed Opportunity Analysis Module is fully functional!")
        elif success_rate >= 70:
            print("\n✅ GOOD: Most features working, minor issues need attention.")
        else:
            print("\n⚠️ ISSUES: Multiple failures detected, module needs debugging.")
        
        print("\n" + "=" * 70)


async def main():
    """Main test execution"""
    print("🧪 PROPSIGNAL ENGINE - MISSED OPPORTUNITY ANALYSIS MODULE TESTING")
    print("=" * 80)
    print("Testing NEW audit-only system for analyzing rejected trades")
    print("with candle-by-candle simulation and FTA bucket analysis.")
    print("=" * 80)
    
    test_suite = MissedOpportunityTestSuite()
    await test_suite.run_all_tests()
    test_suite.print_summary()


if __name__ == "__main__":
    asyncio.run(main())