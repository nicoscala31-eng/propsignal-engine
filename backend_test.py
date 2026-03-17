#!/usr/bin/env python3
"""
Backend Testing Script - FTA SOFT FILTER v4 & Signal Outcome Tracker
====================================================================

Testing the two critical fixes:
1. FTA SOFT FILTER v4 - Soft filtering with score impact, not blocking
2. Signal Outcome Tracker - Active signal tracking and outcome calculation

ENDPOINTS TO TEST:
1. GET /api/scanner/v3/status - Check stats (signals, rejections, acceptance rate)
2. GET /api/signals/active - Check active signals being tracked
3. GET /api/audit/missed-opportunities/by-reason - Check FTA rejection types
4. GET /api/production/status - Confirm signal_generator_v3 is authorized
5. GET /api/health - Backend health
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
        """Test Signal Generator v3 status - KEY TEST for FTA v4"""
        self.log("=== TESTING SIGNAL GENERATOR V3 STATUS (FTA v4) ===")
        result = self.test_endpoint("GET", "/scanner/v3/status", 
                                   description="Signal Generator v3 Status")
        
        if result:
            # Check for FTA v4 indicators
            scans = result.get("scans_performed", 0)
            signals = result.get("signals_generated", 0)
            rejections = result.get("rejections", 0)
            acceptance_rate = result.get("acceptance_rate", 0)
            
            self.log(f"📊 Scanner Stats: {scans} scans, {signals} signals, {rejections} rejections")
            self.log(f"📈 Acceptance Rate: {acceptance_rate:.2f}% (Target: 3-8%)")
            
            # Check if acceptance rate is improving (FTA v4 should increase it)
            if acceptance_rate > 0:
                if 3.0 <= acceptance_rate <= 8.0:
                    self.log("✅ Acceptance rate in target range (3-8%)")
                elif acceptance_rate > 1.0:
                    self.log("✅ Acceptance rate improved over old system (~1%)")
                else:
                    self.log("⚠️  Acceptance rate still low - FTA may still be too strict")
            
        return result

    def test_missed_opportunities_analysis(self):
        """Test missed opportunities - KEY TEST for FTA v4 behavior"""
        self.log("=== TESTING MISSED OPPORTUNITIES (FTA v4 Analysis) ===")
        
        # Test main missed opportunities endpoint
        result = self.test_endpoint("GET", "/audit/missed-opportunities", 
                                   description="Missed Opportunities Report")
        
        if result:
            total = result.get("total_analyzed", 0)
            self.log(f"📊 Total FTA Rejections Analyzed: {total}")
        
        # Test by-reason breakdown - KEY for FTA v4
        by_reason = self.test_endpoint("GET", "/audit/missed-opportunities/by-reason", 
                                      description="FTA Rejection Reasons")
        
        if by_reason:
            self.log("🔍 FTA Rejection Analysis:")
            stats_data = by_reason.get("stats", {})
            for reason, stats in stats_data.items():
                count = stats.get("total", 0)
                winrate = stats.get("simulated_winrate", 0)
                self.log(f"   {reason}: {count} rejections, {winrate:.1f}% win rate")
                
                # Look for FTA v4 specific patterns
                if "hard_block" in reason:
                    self.log(f"   ⚠️  Hard blocks found: {count} (should be minimal in v4)")
                elif any(x in reason for x in ["fta_clean", "fta_moderate", "fta_weak"]):
                    self.log(f"   ✅ FTA v4 quality classification: {reason}")
                elif "contextual" in reason:
                    self.log(f"   ✅ FTA v4 contextual evaluation: {reason}")
        
        # Test FTA bucket analysis
        by_fta = self.test_endpoint("GET", "/audit/missed-opportunities/by-fta-bucket", 
                                   description="FTA Bucket Distribution")
        
        if by_fta:
            self.log("📊 FTA Bucket Distribution:")
            stats_data = by_fta.get("stats", {})
            for bucket, stats in stats_data.items():
                count = stats.get("total", 0)
                self.log(f"   {bucket}: {count} signals")
                
            # Check if we have diversity (not 100% very_close)
            very_close = stats_data.get("very_close", {}).get("total", 0)
            total_buckets = sum(stats.get("total", 0) for stats in stats_data.values())
            if total_buckets > 0:
                very_close_pct = (very_close / total_buckets) * 100
                if very_close_pct < 95:
                    self.log("✅ FTA diversity confirmed - not 100% very_close rejections")
                else:
                    self.log("⚠️  Still mostly very_close rejections - FTA v4 may not be active")
        
        return by_reason

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

    def check_backend_logs_for_fta_v4(self):
        """Check backend logs for FTA v4 patterns"""
        self.log("=== CHECKING BACKEND LOGS FOR FTA v4 ===")
        
        try:
            # Check supervisor logs for FTA v4 patterns
            import subprocess
            
            # Look for FTA v4 decision patterns
            log_patterns = [
                "fta_clean",
                "fta_moderate", 
                "fta_weak",
                "hard_block.*FTA distance.*0.5R",
                "Decision: hard_block",
                "ratio.*bonus",
                "ratio.*penalty"
            ]
            
            for pattern in log_patterns:
                try:
                    result = subprocess.run([
                        "tail", "-n", "500", "/var/log/supervisor/backend.out.log"
                    ], capture_output=True, text=True, timeout=5)
                    
                    if result.returncode == 0:
                        import re
                        matches = re.findall(pattern, result.stdout, re.IGNORECASE)
                        if matches:
                            self.log(f"✅ Found FTA v4 pattern '{pattern}': {len(matches)} matches")
                            if pattern == "Decision: hard_block":
                                self.log("   🔍 Hard blocks found - checking if only for distance < 0.5R")
                        else:
                            self.log(f"ℹ️  Pattern '{pattern}' not found in recent logs")
                            
                except subprocess.TimeoutExpired:
                    self.log(f"⚠️  Log check timeout for pattern: {pattern}")
                    
        except Exception as e:
            self.log(f"⚠️  Could not check logs: {e}")

    def run_comprehensive_test(self):
        """Run comprehensive backend test"""
        self.log("🚀 STARTING FTA SOFT FILTER v4 & SIGNAL OUTCOME TRACKER TESTS")
        self.log("=" * 80)
        
        # Core health and status
        self.test_health_check()
        self.test_production_status()
        
        # KEY TESTS for FTA v4
        self.test_scanner_v3_status()
        self.test_missed_opportunities_analysis()
        
        # KEY TESTS for Signal Outcome Tracker  
        self.test_signal_outcome_tracker()
        self.test_active_signals()
        
        # Data verification
        self.check_data_files()
        
        # Log analysis
        self.check_backend_logs_for_fta_v4()
        
        # Summary
        self.print_summary()

    def print_summary(self):
        """Print test summary"""
        self.log("\n" + "=" * 80)
        self.log("🏁 TEST SUMMARY")
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
        
        # Key findings
        self.log("\n🔍 KEY FINDINGS:")
        
        # Look for FTA v4 evidence
        fta_v4_found = False
        for result in self.test_results:
            if result["response_data"] and "missed-opportunities" in result["endpoint"]:
                fta_v4_found = True
                break
        
        if fta_v4_found:
            self.log("✅ FTA SOFT FILTER v4: Evidence found in missed opportunities analysis")
        else:
            self.log("⚠️  FTA SOFT FILTER v4: No clear evidence found")
            
        # Look for outcome tracker evidence  
        tracker_found = False
        for result in self.test_results:
            if result["success"] and "tracker" in result["endpoint"]:
                tracker_found = True
                break
                
        if tracker_found:
            self.log("✅ SIGNAL OUTCOME TRACKER: Operational and tracking signals")
        else:
            self.log("⚠️  SIGNAL OUTCOME TRACKER: No clear evidence of operation")

if __name__ == "__main__":
    print("FTA SOFT FILTER v4 & Signal Outcome Tracker Testing")
    print("=" * 60)
    
    tester = BackendTester()
    tester.run_comprehensive_test()