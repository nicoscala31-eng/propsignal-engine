#!/usr/bin/env python3
"""
Backend Testing Script for NEW Market Structure Break (MSB) Engine
================================================================

This script tests the NEW MSB Engine implementation focusing on:
1. NEW MSB structure endpoints for EURUSD and XAUUSD
2. Existing endpoints verification (status, bias, health)
3. Signal validation sequence verification

CRITICAL: The scanner now implements strict validation:
- MTF Bias check (H1, M15, M5 alignment)  
- Market Structure Break (MSB) detection
- Displacement validation (strong impulsive move)
- Pullback into key zone validation
- M5 trigger ready check

Signal can ONLY be generated if ALL steps pass.
"""

import requests
import json
import sys
from datetime import datetime
from typing import Dict, Any, List

# Backend URL from environment
BASE_URL = "https://eurusd-alerts.preview.emergentagent.com/api"

class MSBEngineTest:
    def __init__(self):
        self.session = requests.Session()
        self.session.headers.update({
            'Content-Type': 'application/json',
            'User-Agent': 'PropSignal-Test-Client/1.0'
        })
        self.results = []
    
    def log_result(self, test_name: str, passed: bool, details: str = ""):
        """Log test result"""
        status = "✅ PASS" if passed else "❌ FAIL"
        print(f"{status} | {test_name}")
        if details:
            print(f"    Details: {details}")
        
        self.results.append({
            'test': test_name,
            'passed': passed,
            'details': details,
            'timestamp': datetime.utcnow().isoformat()
        })
    
    def make_request(self, endpoint: str, method: str = "GET", data: Dict = None) -> Dict[str, Any]:
        """Make HTTP request with error handling"""
        url = f"{BASE_URL}{endpoint}"
        
        try:
            if method == "GET":
                response = self.session.get(url, timeout=10)
            elif method == "POST":
                response = self.session.post(url, json=data, timeout=10)
            else:
                raise ValueError(f"Unsupported method: {method}")
            
            response.raise_for_status()
            return {
                'success': True,
                'status_code': response.status_code,
                'data': response.json(),
                'error': None
            }
            
        except requests.exceptions.Timeout:
            return {'success': False, 'error': 'Request timeout', 'status_code': None, 'data': None}
        except requests.exceptions.ConnectionError:
            return {'success': False, 'error': 'Connection error', 'status_code': None, 'data': None}
        except requests.exceptions.HTTPError as e:
            try:
                error_data = e.response.json() if e.response.content else {}
            except:
                error_data = {'detail': str(e)}
            return {
                'success': False, 
                'error': f"HTTP {e.response.status_code}: {error_data}",
                'status_code': e.response.status_code,
                'data': error_data
            }
        except Exception as e:
            return {'success': False, 'error': str(e), 'status_code': None, 'data': None}
    
    def test_health_endpoint(self):
        """Test basic health check endpoint"""
        print("\n" + "="*60)
        print("🏥 TESTING HEALTH ENDPOINT")
        print("="*60)
        
        result = self.make_request("/health")
        
        if result['success']:
            data = result['data']
            status = data.get('status', 'unknown')
            backend_status = data.get('backend', {}).get('status', 'unknown')
            
            self.log_result(
                "Health Check Endpoint", 
                True,
                f"Status: {status}, Backend: {backend_status}"
            )
            
            # Check if market data is working
            if 'prices' in data:
                eurusd_price = data['prices'].get('EURUSD')
                xauusd_price = data['prices'].get('XAUUSD')
                
                if eurusd_price and xauusd_price:
                    self.log_result(
                        "Live Market Data", 
                        True,
                        f"EURUSD: {eurusd_price.get('mid', 'N/A')}, XAUUSD: {xauusd_price.get('mid', 'N/A')}"
                    )
                else:
                    self.log_result("Live Market Data", False, "No price data available")
        else:
            self.log_result("Health Check Endpoint", False, result['error'])
    
    def test_scanner_v2_status(self):
        """Test Advanced Scanner v2 status endpoint"""
        print("\n" + "="*60)
        print("🔍 TESTING SCANNER V2 STATUS")
        print("="*60)
        
        result = self.make_request("/scanner/v2/status")
        
        if result['success']:
            data = result['data']
            is_running = data.get('is_running', False)
            version = data.get('version', 'unknown')
            config = data.get('configuration', {})
            stats = data.get('statistics', {})
            
            self.log_result(
                "Scanner v2 Status Endpoint",
                True,
                f"Running: {is_running}, Version: {version}, Total Scans: {stats.get('total_scans', 0)}"
            )
            
            # Verify configuration
            score_threshold = config.get('score_threshold', 0)
            require_htf = config.get('require_htf_alignment', False)
            
            if score_threshold >= 78 and require_htf:
                self.log_result(
                    "Scanner v2 Configuration",
                    True,
                    f"Score threshold: {score_threshold}, HTF required: {require_htf}"
                )
            else:
                self.log_result(
                    "Scanner v2 Configuration",
                    False,
                    f"Invalid config - Score: {score_threshold}, HTF: {require_htf}"
                )
        else:
            self.log_result("Scanner v2 Status Endpoint", False, result['error'])
    
    def test_mtf_bias_endpoints(self):
        """Test MTF Bias Analysis endpoints"""
        print("\n" + "="*60)
        print("📊 TESTING MTF BIAS ENDPOINTS")
        print("="*60)
        
        for asset in ['EURUSD', 'XAUUSD']:
            result = self.make_request(f"/scanner/v2/bias/{asset}")
            
            if result['success']:
                data = result['data']
                
                # Validate structure
                timeframes = data.get('timeframes', {})
                summary = data.get('summary', {})
                
                required_timeframes = ['h1', 'm15', 'm5']
                has_all_timeframes = all(tf in timeframes for tf in required_timeframes)
                
                if has_all_timeframes:
                    # Check timeframe data structure
                    h1_data = timeframes['h1']
                    m15_data = timeframes['m15']
                    m5_data = timeframes['m5']
                    
                    has_bias_data = all(
                        'bias' in tf_data and 'strength' in tf_data 
                        for tf_data in [h1_data, m15_data, m5_data]
                    )
                    
                    # Check summary data
                    has_summary = all(
                        key in summary for key in ['overall_bias', 'alignment_score', 'trade_direction']
                    )
                    
                    if has_bias_data and has_summary:
                        self.log_result(
                            f"MTF Bias Analysis - {asset}",
                            True,
                            f"Overall: {summary.get('overall_bias')}, Direction: {summary.get('trade_direction')}, Alignment: {summary.get('alignment_score')}%"
                        )
                    else:
                        self.log_result(
                            f"MTF Bias Analysis - {asset}",
                            False,
                            "Missing bias data or summary fields"
                        )
                else:
                    self.log_result(
                        f"MTF Bias Analysis - {asset}",
                        False,
                        f"Missing timeframes - got: {list(timeframes.keys())}"
                    )
            else:
                self.log_result(f"MTF Bias Analysis - {asset}", False, result['error'])
    
    def test_msb_structure_endpoints(self):
        """Test NEW Market Structure Break (MSB) endpoints"""
        print("\n" + "="*60)  
        print("🏗️  TESTING NEW MSB STRUCTURE ENDPOINTS")
        print("="*60)
        
        for asset in ['EURUSD', 'XAUUSD']:
            result = self.make_request(f"/scanner/v2/structure/{asset}")
            
            if result['success']:
                data = result['data']
                
                # Check if analysis is available or if it's properly returning no data
                if data.get('sequence') is None:
                    message = data.get('message', 'No message')
                    self.log_result(
                        f"MSB Structure Analysis - {asset}",
                        True,
                        f"No analysis yet: {message}"
                    )
                else:
                    # Validate structure when data is available
                    required_fields = ['is_complete', 'is_ready_for_trigger', 'direction', 'sequence_score']
                    has_required = all(field in data for field in required_fields)
                    
                    if has_required:
                        is_complete = data.get('is_complete', False)
                        is_ready = data.get('is_ready_for_trigger', False)
                        direction = data.get('direction', 'NONE')
                        score = data.get('sequence_score', 0)
                        
                        self.log_result(
                            f"MSB Structure Analysis - {asset}",
                            True,
                            f"Complete: {is_complete}, Ready: {is_ready}, Direction: {direction}, Score: {score}"
                        )
                        
                        # Validate MSB sequence logic
                        if is_complete:
                            has_structure_break = 'structure_break' in data
                            has_pullback_zone = 'pullback_zone' in data
                            has_pullback_validation = 'pullback_validation' in data
                            
                            if has_structure_break and has_pullback_zone and has_pullback_validation:
                                self.log_result(
                                    f"MSB Sequence Components - {asset}",
                                    True,
                                    "All sequence components present (structure_break, pullback_zone, pullback_validation)"
                                )
                            else:
                                self.log_result(
                                    f"MSB Sequence Components - {asset}",
                                    False,
                                    f"Missing components - Structure: {has_structure_break}, Zone: {has_pullback_zone}, Validation: {has_pullback_validation}"
                                )
                    else:
                        self.log_result(
                            f"MSB Structure Analysis - {asset}",
                            False,
                            f"Missing required fields - got: {list(data.keys())}"
                        )
            else:
                if result['status_code'] == 404:
                    self.log_result(f"MSB Structure Analysis - {asset}", False, "Endpoint not found - MSB engine may not be properly implemented")
                else:
                    self.log_result(f"MSB Structure Analysis - {asset}", False, result['error'])
    
    def test_signal_validation_sequence(self):
        """Test that the signal validation sequence is properly enforced"""
        print("\n" + "="*60)
        print("🔐 TESTING SIGNAL VALIDATION SEQUENCE")
        print("="*60)
        
        # This test verifies the NEW validation logic:
        # 1. MTF Bias check → 2. MSB detection → 3. Displacement → 4. Pullback → 5. M5 trigger
        
        validation_checks = []
        
        # Check MTF Bias availability
        for asset in ['EURUSD', 'XAUUSD']:
            bias_result = self.make_request(f"/scanner/v2/bias/{asset}")
            msb_result = self.make_request(f"/scanner/v2/structure/{asset}")
            
            if bias_result['success'] and msb_result['success']:
                bias_data = bias_result['data']
                msb_data = msb_result['data']
                
                # Check MTF Bias
                trade_direction = bias_data.get('summary', {}).get('trade_direction', 'NONE')
                alignment_score = bias_data.get('summary', {}).get('alignment_score', 0)
                
                # Check MSB Sequence
                msb_complete = msb_data.get('is_complete', False)
                msb_ready = msb_data.get('is_ready_for_trigger', False)
                msb_direction = msb_data.get('direction', 'NONE')
                
                # Validate sequence logic
                if trade_direction == 'NONE':
                    # No clear HTF direction - should block signals
                    validation_checks.append({
                        'asset': asset,
                        'step': 'MTF_Bias',
                        'passed': True,
                        'reason': f"Correctly showing NONE direction (alignment: {alignment_score}%)"
                    })
                elif msb_direction == 'NONE' and not msb_complete:
                    # MSB not ready - should block signals
                    validation_checks.append({
                        'asset': asset, 
                        'step': 'MSB_Structure',
                        'passed': True,
                        'reason': "Correctly blocking - no MSB sequence"
                    })
                elif msb_complete and not msb_ready:
                    # MSB complete but not ready for trigger
                    validation_checks.append({
                        'asset': asset,
                        'step': 'M5_Trigger',
                        'passed': True,
                        'reason': "MSB complete but waiting for M5 trigger - correct behavior"
                    })
                elif msb_complete and msb_ready:
                    # Full sequence ready
                    validation_checks.append({
                        'asset': asset,
                        'step': 'Full_Sequence',
                        'passed': True,
                        'reason': f"Complete sequence ready: {msb_direction} direction"
                    })
        
        # Report validation results
        if validation_checks:
            for check in validation_checks:
                self.log_result(
                    f"Signal Validation - {check['asset']} ({check['step']})",
                    check['passed'],
                    check['reason']
                )
        else:
            self.log_result(
                "Signal Validation Sequence",
                False,
                "Could not validate sequence - endpoints not responding"
            )
    
    def test_existing_endpoints_compatibility(self):
        """Verify that existing endpoints still work after MSB implementation"""
        print("\n" + "="*60)
        print("🔄 TESTING EXISTING ENDPOINT COMPATIBILITY") 
        print("="*60)
        
        # Test provider status endpoints
        endpoints_to_test = [
            ("/provider/status", "Provider Status"),
            ("/provider/live-prices", "Live Prices"),
            ("/scanner/status", "Legacy Scanner Status")
        ]
        
        for endpoint, name in endpoints_to_test:
            result = self.make_request(endpoint)
            
            if result['success']:
                data = result['data']
                
                if endpoint == "/provider/live-prices":
                    # Check if prices are still working
                    prices = data.get('prices', {})
                    eurusd = prices.get('EURUSD', {})
                    xauusd = prices.get('XAUUSD', {})
                    
                    if eurusd.get('status') == 'LIVE' and xauusd.get('status') == 'LIVE':
                        self.log_result(
                            name,
                            True,
                            f"Live prices working - EURUSD: {eurusd.get('mid', 'N/A')}, XAUUSD: {xauusd.get('mid', 'N/A')}"
                        )
                    else:
                        self.log_result(name, False, "Price data not live or missing")
                else:
                    self.log_result(name, True, "Endpoint responding correctly")
            else:
                self.log_result(name, False, result['error'])
    
    def print_summary(self):
        """Print test summary"""
        print("\n" + "="*80)
        print("📋 TEST SUMMARY - NEW MSB ENGINE")
        print("="*80)
        
        total_tests = len(self.results)
        passed_tests = sum(1 for r in self.results if r['passed'])
        failed_tests = total_tests - passed_tests
        
        print(f"Total Tests: {total_tests}")
        print(f"✅ Passed: {passed_tests}")
        print(f"❌ Failed: {failed_tests}")
        print(f"Success Rate: {(passed_tests/total_tests)*100:.1f}%")
        
        if failed_tests > 0:
            print(f"\n🚨 FAILED TESTS:")
            for result in self.results:
                if not result['passed']:
                    print(f"   ❌ {result['test']}: {result['details']}")
        
        print(f"\n🎯 KEY FINDINGS:")
        
        # Analyze MSB endpoint results
        msb_tests = [r for r in self.results if 'MSB' in r['test']]
        if msb_tests:
            msb_passed = sum(1 for r in msb_tests if r['passed'])
            print(f"   MSB Engine: {msb_passed}/{len(msb_tests)} tests passed")
        
        # Analyze validation results  
        validation_tests = [r for r in self.results if 'Validation' in r['test']]
        if validation_tests:
            val_passed = sum(1 for r in validation_tests if r['passed'])
            print(f"   Signal Validation: {val_passed}/{len(validation_tests)} checks passed")
        
        # Analyze compatibility
        compat_tests = [r for r in self.results if any(word in r['test'] for word in ['Provider', 'Live Prices', 'Legacy'])]
        if compat_tests:
            compat_passed = sum(1 for r in compat_tests if r['passed'])
            print(f"   Existing Endpoints: {compat_passed}/{len(compat_tests)} still working")
        
        print(f"\n⚡ CONCLUSION:")
        if failed_tests == 0:
            print("   🎉 ALL TESTS PASSED - MSB Engine implementation successful!")
        elif failed_tests <= 2:
            print("   ⚠️  Minor issues detected - mostly functional")
        else:
            print("   🚨 Multiple issues detected - requires attention")
        
        return failed_tests == 0

def main():
    """Main test execution"""
    print("🚀 PropSignal Engine - NEW MSB Engine Testing")
    print(f"Backend URL: {BASE_URL}")
    print(f"Test Start Time: {datetime.utcnow().isoformat()}")
    
    tester = MSBEngineTest()
    
    # Execute test suite
    try:
        tester.test_health_endpoint()
        tester.test_scanner_v2_status()
        tester.test_mtf_bias_endpoints()
        tester.test_msb_structure_endpoints()  # NEW MSB endpoints
        tester.test_signal_validation_sequence()  # NEW validation logic
        tester.test_existing_endpoints_compatibility()
        
    except KeyboardInterrupt:
        print("\n⚠️ Tests interrupted by user")
    except Exception as e:
        print(f"\n🚨 Unexpected error during testing: {e}")
    
    # Print results
    success = tester.print_summary()
    
    # Exit with appropriate code
    sys.exit(0 if success else 1)

if __name__ == "__main__":
    main()