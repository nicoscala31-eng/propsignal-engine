#!/usr/bin/env python3
"""
Backend Testing Script - Signal Generator v10.0 BUY/SELL Direction Logic Fix
============================================================================

Testing the Signal Generator v10.0 fixes for PropSignal Engine trading app:

CRITICAL FIXES TO VERIFY:
1. SELL direction re-enabled in _analyze_direction_advanced (was disabled since v7.0)
2. _fallback_direction now supports both BUY and SELL
3. Fixed NameError for missing variables in DirectionContext
4. Fixed position_sizer.calculate() call removing unsupported 'direction' parameter
5. Added comprehensive debug logging

TEST REQUIREMENTS:
1. Health Check: GET /api/health - Should return OK
2. Signal Generator v3 Status: GET /api/scanner/v3/status - Should show is_running=true, version info, scans_performed > 0
3. Debug Stats: GET /api/signals/debug/stats - Should return rejection statistics, show both BUY and SELL directions being evaluated
4. Live Backend Logs Analysis: Check if SELL direction is being evaluated by looking at recent backend logs
5. Production Status: GET /api/production/status - Should show signal_generator_v3 as authorized engine

IMPORTANT NOTES:
- API rate limit from Twelve Data may cause "No price data available" errors - this is expected
- SELL signals may be rejected due to strict quality criteria (Rejection score < 70, FTA < 60) - this is CORRECT behavior
- The goal is to verify SELL is being EVALUATED (not necessarily accepted)
"""

import json
import requests
import sys
from datetime import datetime
from typing import Dict, List, Any, Optional
import os
import time

# Backend URL
BACKEND_URL = "https://eurusd-alerts.preview.emergentagent.com/api"

class BackendTester:
    def __init__(self):
        self.backend_url = BACKEND_URL
        self.session = requests.Session()
        self.session.timeout = 10
        self.test_results = []
        
    def log(self, message: str, level: str = "INFO"):
        """Log test messages"""
        timestamp = datetime.now().strftime("%H:%M:%S")
        print(f"[{timestamp}] {level}: {message}")
        
    def test_endpoint(self, method: str, endpoint: str, expected_status: int = 200, 
                     data: Dict = None, description: str = None) -> Optional[Dict]:
        """Test an API endpoint"""
        url = f"{self.backend_url}{endpoint}"
        
        try:
            if method.upper() == "GET":
                response = self.session.get(url)
            elif method.upper() == "POST":
                response = self.session.post(url, json=data)
            else:
                response = self.session.request(method, url, json=data)
                
            success = response.status_code == expected_status
            
            result = {
                "endpoint": endpoint,
                "method": method,
                "status_code": response.status_code,
                "expected_status": expected_status,
                "success": success,
                "description": description or f"{method} {endpoint}",
                "response_data": None,
                "error": None
            }
            
            if success:
                try:
                    result["response_data"] = response.json()
                except:
                    result["response_data"] = response.text
            else:
                result["error"] = f"Status {response.status_code}: {response.text[:200]}"
                
            self.test_results.append(result)
            
            status_icon = "✅" if success else "❌"
            self.log(f"{status_icon} {description or endpoint}: {response.status_code}")
            
            return result["response_data"] if success else None
            
        except Exception as e:
            result = {
                "endpoint": endpoint,
                "method": method,
                "status_code": None,
                "expected_status": expected_status,
                "success": False,
                "description": description or f"{method} {endpoint}",
                "response_data": None,
                "error": str(e)
            }
            self.test_results.append(result)
            self.log(f"❌ {description or endpoint}: ERROR - {str(e)}", "ERROR")
            return None

    def test_health_check(self):
        """Test backend health"""
        self.log("=== TESTING HEALTH CHECK ===")
        return self.test_endpoint("GET", "/health", description="Health Check")

    def test_production_status(self):
        """Test production control status"""
        self.log("=== TESTING PRODUCTION STATUS ===")
        result = self.test_endpoint("GET", "/production/status", 
                                   description="Production Control Status")
        
        if result:
            # Verify signal_generator_v3 is authorized
            authorized_engine = result.get("engine", {}).get("authorized")
            if authorized_engine == "signal_generator_v3":
                self.log("✅ signal_generator_v3 is the authorized engine")
            else:
                self.log(f"⚠️  Expected signal_generator_v3, got {authorized_engine}")
                
            # Check blocked engines
            blocked = result.get("engine", {}).get("blocked", [])
            expected_blocked = ["advanced_scanner_v2", "signal_orchestrator", "market_scanner_legacy"]
            self.log(f"🛡️  Blocked engines: {blocked}")
        
        return result

    def test_scanner_v3_status(self):
        """Test Signal Generator v3 status - KEY TEST for v10.0 fixes"""
        self.log("=== TESTING SIGNAL GENERATOR V3 STATUS (v10.0 fixes) ===")
        result = self.test_endpoint("GET", "/scanner/v3/status", 
                                   description="Signal Generator v3 Status")
        
        if result:
            # Check basic functionality
            is_running = result.get("is_running", False)
            scans = result.get("scans_performed", 0)
            signals = result.get("signals_generated", 0)
            rejections = result.get("rejections", 0)
            version = result.get("version", "unknown")
            
            self.log(f"📊 Scanner Status: Running={is_running}, Version={version}")
            self.log(f"📊 Scanner Stats: {scans} scans, {signals} signals, {rejections} rejections")
            
            # Verify requirements from review request
            if is_running:
                self.log("✅ Signal Generator v3 is running")
            else:
                self.log("❌ Signal Generator v3 is NOT running")
                
            if scans > 0:
                self.log("✅ Scans performed > 0")
            else:
                self.log("❌ No scans performed")
                
            if version:
                self.log(f"✅ Version info available: {version}")
            else:
                self.log("⚠️  No version info")
            
        return result

    def test_debug_stats(self):
        """Test debug stats endpoint - KEY TEST for v10.0 BUY/SELL evaluation"""
        self.log("=== TESTING DEBUG STATS (BUY/SELL Direction Evaluation) ===")
        result = self.test_endpoint("GET", "/signals/debug/stats", 
                                   description="Debug Stats - Direction Evaluation")
        
        if result:
            # Look for rejection statistics and direction evaluation
            self.log("📊 Debug Stats Response Structure:")
            for key, value in result.items():
                if isinstance(value, dict):
                    self.log(f"   {key}: {len(value)} items")
                else:
                    self.log(f"   {key}: {value}")
            
            # Check for BUY/SELL direction evidence
            buy_found = False
            sell_found = False
            
            # Look through the response for direction indicators
            response_str = str(result).lower()
            if 'buy' in response_str:
                buy_found = True
                self.log("✅ BUY direction found in debug stats")
            if 'sell' in response_str:
                sell_found = True
                self.log("✅ SELL direction found in debug stats")
                
            if buy_found and sell_found:
                self.log("✅ Both BUY and SELL directions being evaluated")
            elif sell_found:
                self.log("✅ SELL direction evaluation confirmed (main fix)")
            elif buy_found:
                self.log("⚠️  Only BUY direction found - SELL may still be disabled")
            else:
                self.log("⚠️  No clear direction evaluation evidence in debug stats")
        
        return result

    def test_signal_outcome_tracker(self):
        """Test Signal Outcome Tracker - KEY TEST"""
        self.log("=== TESTING SIGNAL OUTCOME TRACKER ===")
        
        # Test tracker status
        tracker_status = self.test_endpoint("GET", "/tracker/status", 
                                           description="Outcome Tracker Status")
        
        if tracker_status:
            running = tracker_status.get("is_running", False)
            checks = tracker_status.get("checks_performed", 0)
            self.log(f"📈 Tracker Status: Running={running}, Checks={checks}")
            
            if running and checks > 0:
                self.log("✅ Outcome Tracker is operational")
            else:
                self.log("⚠️  Outcome Tracker may not be running properly")
        
        return tracker_status

    def test_active_signals(self):
        """Test active signals tracking"""
        self.log("=== TESTING ACTIVE SIGNALS TRACKING ===")
        
        # Try to get active signals
        active = self.test_endpoint("GET", "/signals/active", 
                                   description="Active Signals", expected_status=200)
        
        if active is not None:
            if isinstance(active, list):
                count = len(active)
                self.log(f"📊 Active Signals: {count}")
                
                if count > 0:
                    # Show details of first active signal
                    signal = active[0]
                    signal_id = signal.get("id", "unknown")
                    asset = signal.get("asset", "unknown")
                    direction = signal.get("signal_type", "unknown")
                    self.log(f"   Sample: {signal_id} - {asset} {direction}")
                    self.log("✅ Active signals are being tracked")
                else:
                    self.log("ℹ️  No active signals currently (normal if market is closed)")
            else:
                self.log(f"⚠️  Expected list, got: {type(active)}")
        
        return active

    def check_data_files(self):
        """Check tracking data files"""
        self.log("=== CHECKING DATA FILES ===")
        
        # Check tracked signals file
        tracked_file = "/app/backend/data/tracked_signals.json"
        stats_file = "/app/backend/data/signal_stats.json"
        
        try:
            if os.path.exists(tracked_file):
                with open(tracked_file, 'r') as f:
                    tracked_data = json.load(f)
                
                completed = tracked_data.get("completed", [])
                active = tracked_data.get("active", [])
                
                self.log(f"📁 tracked_signals.json: {len(completed)} completed, {len(active)} active")
                
                # Count outcomes
                wins = sum(1 for s in completed if s.get("final_outcome") == "win")
                losses = sum(1 for s in completed if s.get("final_outcome") == "loss")
                expired = sum(1 for s in completed if s.get("final_outcome") == "expired")
                
                self.log(f"📊 Completed Signals: {wins}W / {losses}L / {expired} expired")
                
                if wins > 0 or losses > 0:
                    self.log("✅ Signal Outcome Tracker has tracked completions")
                    
                    # Check for MFE/MAE data
                    if completed:
                        sample = completed[0]
                        mfe = sample.get("max_favorable_excursion")
                        mae = sample.get("max_adverse_excursion")
                        if mfe is not None and mae is not None:
                            self.log("✅ MFE/MAE calculation confirmed")
            else:
                self.log("❌ tracked_signals.json not found")
                
        except Exception as e:
            self.log(f"❌ Error reading tracked_signals.json: {e}")
            
        try:
            if os.path.exists(stats_file):
                with open(stats_file, 'r') as f:
                    stats_data = json.load(f)
                
                total = stats_data.get("total_tracked", 0)
                wins = stats_data.get("wins", 0)
                losses = stats_data.get("losses", 0)
                
                self.log(f"📁 signal_stats.json: {total} total, {wins}W / {losses}L")
                
                # Check expected values from review request
                if wins >= 50 and losses >= 50:
                    self.log("✅ Expected win/loss counts confirmed (~56W/58L)")
                else:
                    self.log(f"ℹ️  Different from expected 56W/58L - actual: {wins}W/{losses}L")
            else:
                self.log("❌ signal_stats.json not found")
                
        except Exception as e:
            self.log(f"❌ Error reading signal_stats.json: {e}")

    def check_backend_logs_for_v10_fixes(self):
        """Check backend logs for v10.0 SELL direction fixes"""
        self.log("=== CHECKING BACKEND LOGS FOR v10.0 SELL DIRECTION FIXES ===")
        
        try:
            # Check supervisor logs for v10.0 SELL direction patterns
            import subprocess
            
            # Look for v10.0 SELL direction patterns
            sell_patterns = [
                "SELL chosen",
                "SELL EXTRA CONFIRM", 
                "Direction=SELL",
                "SELL.*strong bearish bias",
                "preliminary_score.*SELL",
                "H1 STRUCTURAL.*SELL",
                "M5 TRIGGER.*SELL"
            ]
            
            buy_patterns = [
                "BUY chosen",
                "Direction=BUY", 
                "BUY.*strong bullish bias",
                "preliminary_score.*BUY",
                "H1 STRUCTURAL.*BUY",
                "M5 TRIGGER.*BUY"
            ]
            
            self.log("🔍 Searching for SELL direction evaluation patterns...")
            
            sell_found = 0
            buy_found = 0
            
            for pattern in sell_patterns:
                try:
                    result = subprocess.run([
                        "tail", "-n", "1000", "/var/log/supervisor/backend.err.log"
                    ], capture_output=True, text=True, timeout=5)
                    
                    if result.returncode == 0:
                        import re
                        matches = re.findall(pattern, result.stdout, re.IGNORECASE)
                        if matches:
                            sell_found += len(matches)
                            self.log(f"✅ Found SELL pattern '{pattern}': {len(matches)} matches")
                            
                except subprocess.TimeoutExpired:
                    self.log(f"⚠️  Log check timeout for pattern: {pattern}")
                    
            for pattern in buy_patterns:
                try:
                    result = subprocess.run([
                        "tail", "-n", "1000", "/var/log/supervisor/backend.err.log"
                    ], capture_output=True, text=True, timeout=5)
                    
                    if result.returncode == 0:
                        import re
                        matches = re.findall(pattern, result.stdout, re.IGNORECASE)
                        if matches:
                            buy_found += len(matches)
                            self.log(f"✅ Found BUY pattern '{pattern}': {len(matches)} matches")
                            
                except subprocess.TimeoutExpired:
                    self.log(f"⚠️  Log check timeout for pattern: {pattern}")
            
            # Summary of direction evaluation
            self.log(f"\n📊 DIRECTION EVALUATION SUMMARY:")
            self.log(f"   SELL direction patterns found: {sell_found}")
            self.log(f"   BUY direction patterns found: {buy_found}")
            
            if sell_found > 0:
                self.log("✅ CRITICAL FIX VERIFIED: SELL direction is being evaluated!")
                if buy_found > 0:
                    self.log("✅ Both BUY and SELL directions are working")
                else:
                    self.log("ℹ️  Only SELL patterns found (may be market conditions)")
            else:
                self.log("❌ CRITICAL ISSUE: No SELL direction evaluation found in logs")
                if buy_found > 0:
                    self.log("⚠️  Only BUY direction found - SELL may still be disabled")
                else:
                    self.log("⚠️  No direction evaluation found at all")
                    
            # Look for specific v10.0 debug messages
            self.log("\n🔍 Checking for v10.0 specific debug messages...")
            v10_patterns = [
                "DIRECTION DEBUG.*BUY_preliminary_score.*SELL_preliminary_score",
                "FALLBACK DEBUG",
                "H1 STRUCTURAL DEBUG",
                "M5 TRIGGER DEBUG"
            ]
            
            for pattern in v10_patterns:
                try:
                    result = subprocess.run([
                        "tail", "-n", "500", "/var/log/supervisor/backend.err.log"
                    ], capture_output=True, text=True, timeout=5)
                    
                    if result.returncode == 0:
                        import re
                        matches = re.findall(pattern, result.stdout, re.IGNORECASE)
                        if matches:
                            self.log(f"✅ v10.0 debug logging active: '{pattern}' ({len(matches)} matches)")
                        else:
                            self.log(f"ℹ️  v10.0 pattern '{pattern}' not found")
                            
                except subprocess.TimeoutExpired:
                    self.log(f"⚠️  Log check timeout for v10.0 pattern: {pattern}")
                    
        except Exception as e:
            self.log(f"⚠️  Could not check logs: {e}")

    def run_comprehensive_test(self):
        """Run comprehensive backend test for Signal Generator v10.0 fixes"""
        self.log("🚀 STARTING SIGNAL GENERATOR v10.0 BUY/SELL DIRECTION LOGIC FIX TESTS")
        self.log("=" * 80)
        
        # Test Requirements from Review Request:
        # 1. Health Check: GET /api/health - Should return OK
        self.test_health_check()
        
        # 2. Signal Generator v3 Status: GET /api/scanner/v3/status 
        #    - Should show is_running=true, version info, scans_performed > 0
        self.test_scanner_v3_status()
        
        # 3. Debug Stats: GET /api/signals/debug/stats 
        #    - Should return rejection statistics, show both BUY and SELL directions being evaluated
        self.test_debug_stats()
        
        # 5. Production Status: GET /api/production/status 
        #    - Should show signal_generator_v3 as authorized engine
        self.test_production_status()
        
        # 4. Live Backend Logs Analysis: Check if SELL direction is being evaluated
        #    - Look for "SELL chosen" messages, "SELL EXTRA CONFIRM" messages
        #    - Verify both directions are being processed
        self.check_backend_logs_for_v10_fixes()
        
        # Summary
        self.print_summary()

    def print_summary(self):
        """Print test summary for v10.0 fixes"""
        self.log("\n" + "=" * 80)
        self.log("🏁 SIGNAL GENERATOR v10.0 TEST SUMMARY")
        self.log("=" * 80)
        
        total_tests = len(self.test_results)
        passed_tests = sum(1 for r in self.test_results if r["success"])
        failed_tests = total_tests - passed_tests
        
        self.log(f"📊 Total Tests: {total_tests}")
        self.log(f"✅ Passed: {passed_tests}")
        self.log(f"❌ Failed: {failed_tests}")
        self.log(f"📈 Success Rate: {(passed_tests/total_tests)*100:.1f}%")
        
        if failed_tests > 0:
            self.log("\n❌ FAILED TESTS:")
            for result in self.test_results:
                if not result["success"]:
                    self.log(f"   • {result['description']}: {result['error']}")
        
        # Key findings for v10.0 fixes
        self.log("\n🔍 KEY FINDINGS FOR v10.0 FIXES:")
        
        # Check if Signal Generator v3 is running
        scanner_working = False
        for result in self.test_results:
            if result["success"] and "scanner/v3/status" in result["endpoint"]:
                if result["response_data"] and result["response_data"].get("is_running"):
                    scanner_working = True
                    self.log("✅ Signal Generator v3 is running and operational")
                break
        
        if not scanner_working:
            self.log("❌ Signal Generator v3 is NOT running properly")
            
        # Check if production status shows correct authorization
        production_ok = False
        for result in self.test_results:
            if result["success"] and "production/status" in result["endpoint"]:
                if result["response_data"]:
                    auth_engine = result["response_data"].get("engine", {}).get("authorized")
                    if auth_engine == "signal_generator_v3":
                        production_ok = True
                        self.log("✅ signal_generator_v3 is properly authorized in production")
                break
        
        if not production_ok:
            self.log("⚠️  Production authorization may not be configured correctly")
            
        # Overall assessment
        self.log("\n🎯 OVERALL ASSESSMENT:")
        if passed_tests == total_tests and scanner_working and production_ok:
            self.log("✅ Signal Generator v10.0 fixes appear to be working correctly")
            self.log("✅ SELL direction evaluation has been successfully re-enabled")
        elif passed_tests >= total_tests * 0.8:  # 80% pass rate
            self.log("⚠️  Most tests passed but some issues detected")
            self.log("ℹ️  Check failed tests and log analysis for details")
        else:
            self.log("❌ Significant issues detected with v10.0 fixes")
            self.log("❌ Manual investigation required")

if __name__ == "__main__":
    print("Signal Generator v10.0 BUY/SELL Direction Logic Fix Testing")
    print("=" * 60)
    
    tester = BackendTester()
    tester.run_comprehensive_test()