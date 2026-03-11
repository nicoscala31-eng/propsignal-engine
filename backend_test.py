#!/usr/bin/env python3
"""
PropSignal Engine Backend Testing Suite
======================================

Focus: NEW Data-Fetch/Scanner Separation Architecture Testing

Testing Plan:
1. NEW Endpoints - Data Cache/Fetch Engine separation
2. Verify cache statistics and hit rates
3. Verify API usage is within free tier limits
4. Verify scanner performance and speed
5. Existing endpoint compatibility checks

Expected Architecture:
- Scanner runs every 5 seconds (fast)
- Fetch engine fetches every 30 seconds (slow) 
- Scanner reads from cache only (zero API calls)
- Cache hit rate should be ~100%
"""

import asyncio
import aiohttp
import json
from datetime import datetime
from typing import Dict, Any, Optional
import time
import logging

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# Backend URL from environment
BACKEND_URL = "https://eurusd-alerts.preview.emergentagent.com"
API_BASE = f"{BACKEND_URL}/api"

class TestResult:
    def __init__(self):
        self.passed = []
        self.failed = []
        self.warnings = []
        self.critical_failures = []
    
    def add_pass(self, test_name: str, message: str = ""):
        self.passed.append(f"✅ {test_name}: {message}")
        logger.info(f"PASS: {test_name} - {message}")
    
    def add_fail(self, test_name: str, error: str, is_critical: bool = False):
        failure_msg = f"❌ {test_name}: {error}"
        self.failed.append(failure_msg)
        
        if is_critical:
            self.critical_failures.append(failure_msg)
            logger.error(f"CRITICAL FAIL: {test_name} - {error}")
        else:
            logger.warning(f"FAIL: {test_name} - {error}")
    
    def add_warning(self, test_name: str, message: str):
        warning_msg = f"⚠️  {test_name}: {message}"
        self.warnings.append(warning_msg)
        logger.info(f"WARNING: {test_name} - {message}")
    
    def print_summary(self):
        print("\n" + "="*80)
        print("🎯 PROPSIGNAL ENGINE - NEW DATA ARCHITECTURE TEST RESULTS")
        print("="*80)
        
        print(f"\n📊 SUMMARY:")
        print(f"   ✅ Passed: {len(self.passed)}")
        print(f"   ❌ Failed: {len(self.failed)}")
        print(f"   ⚠️  Warnings: {len(self.warnings)}")
        print(f"   🚨 Critical: {len(self.critical_failures)}")
        
        if self.critical_failures:
            print(f"\n🚨 CRITICAL FAILURES:")
            for failure in self.critical_failures:
                print(f"   {failure}")
        
        if self.failed:
            print(f"\n❌ FAILED TESTS:")
            for failure in self.failed:
                if failure not in [f"   {cf}" for cf in self.critical_failures]:
                    print(f"   {failure}")
        
        if self.warnings:
            print(f"\n⚠️  WARNINGS:")
            for warning in self.warnings:
                print(f"   {warning}")
        
        if self.passed:
            print(f"\n✅ PASSED TESTS:")
            for passed in self.passed:
                print(f"   {passed}")
        
        print("\n" + "="*80)


async def make_request(session: aiohttp.ClientSession, endpoint: str, method: str = "GET", 
                      json_data: Dict = None, expect_json: bool = True) -> tuple:
    """Make HTTP request and return (success, data, status_code)"""
    try:
        url = f"{API_BASE}{endpoint}"
        
        async with session.request(method, url, json=json_data) as response:
            status = response.status
            
            if expect_json:
                try:
                    data = await response.json()
                except:
                    text = await response.text()
                    return False, f"Invalid JSON response: {text[:200]}", status
            else:
                data = await response.text()
            
            return status < 400, data, status
            
    except Exception as e:
        return False, f"Request error: {str(e)}", 0


async def test_new_cache_status_endpoint(session: aiohttp.ClientSession, results: TestResult):
    """Test NEW /api/data/cache/status endpoint"""
    print("\n🔍 Testing NEW Cache Status Endpoint...")
    
    success, data, status = await make_request(session, "/data/cache/status")
    
    if not success:
        results.add_fail("Cache Status Endpoint", f"Request failed: {data} (HTTP {status})", is_critical=True)
        return
    
    # Validate response structure
    required_fields = ["uptime_seconds", "statistics", "configuration", "symbols"]
    for field in required_fields:
        if field not in data:
            results.add_fail("Cache Status Structure", f"Missing field: {field}", is_critical=True)
            return
    
    # Check statistics
    stats = data.get("statistics", {})
    required_stats = ["total_writes", "total_reads", "cache_hits", "hit_rate_percent"]
    
    for stat in required_stats:
        if stat not in stats:
            results.add_fail("Cache Statistics", f"Missing statistic: {stat}")
        
    # Check hit rate - should be high for scanner efficiency
    hit_rate = stats.get("hit_rate_percent", 0)
    if hit_rate >= 95:
        results.add_pass("Cache Hit Rate", f"Excellent hit rate: {hit_rate}%")
    elif hit_rate >= 80:
        results.add_warning("Cache Hit Rate", f"Good hit rate: {hit_rate}% (target: >95%)")
    else:
        results.add_fail("Cache Hit Rate", f"Low hit rate: {hit_rate}% (target: >95%)")
    
    # Check symbol data
    symbols = data.get("symbols", {})
    for asset in ["EURUSD", "XAUUSD"]:
        if asset not in symbols:
            results.add_fail("Symbol Cache", f"Missing asset: {asset}")
            continue
            
        symbol_data = symbols[asset]
        
        # Check if symbol is ready for scanning
        is_ready = symbol_data.get("is_ready", False)
        if is_ready:
            results.add_pass(f"{asset} Cache Ready", "Data available for scanning")
        else:
            results.add_warning(f"{asset} Cache Ready", "Not ready for scanning")
        
        # Check price age
        price_age = symbol_data.get("price_age_seconds")
        if price_age is not None:
            if price_age <= 60:  # Fresh within 1 minute
                results.add_pass(f"{asset} Price Freshness", f"Fresh data ({price_age:.1f}s old)")
            else:
                results.add_warning(f"{asset} Price Freshness", f"Stale data ({price_age:.1f}s old)")
    
    results.add_pass("Cache Status Endpoint", "All validations passed")


async def test_cached_symbol_data(session: aiohttp.ClientSession, results: TestResult):
    """Test NEW /api/data/cache/{asset} endpoints"""
    print("\n🔍 Testing NEW Cached Symbol Data Endpoints...")
    
    for asset in ["EURUSD", "XAUUSD"]:
        success, data, status = await make_request(session, f"/data/cache/{asset}")
        
        if not success:
            results.add_fail(f"{asset} Cache Data", f"Request failed: {data} (HTTP {status})")
            continue
        
        # Check if data is available
        if data.get("data") is None:
            results.add_warning(f"{asset} Cache Data", "No cached data available")
            continue
        
        # Validate structure
        required_fields = ["symbol", "has_price", "is_ready"]
        for field in required_fields:
            if field not in data:
                results.add_fail(f"{asset} Data Structure", f"Missing field: {field}")
                continue
        
        # Check candle data counts
        candle_fields = ["candles_m5_count", "candles_m15_count", "candles_h1_count"]
        candle_counts = []
        
        for field in candle_fields:
            count = data.get(field, 0)
            candle_counts.append(count)
            timeframe = field.replace("candles_", "").replace("_count", "").upper()
            
            if count > 0:
                results.add_pass(f"{asset} {timeframe} Candles", f"{count} candles cached")
            else:
                results.add_warning(f"{asset} {timeframe} Candles", "No candles cached")
        
        # Overall readiness
        is_ready = data.get("is_ready", False)
        if is_ready:
            results.add_pass(f"{asset} Scanner Ready", "All data available")
        else:
            results.add_warning(f"{asset} Scanner Ready", "Data not ready for scanning")


async def test_fetch_engine_status(session: aiohttp.ClientSession, results: TestResult):
    """Test NEW /api/data/fetch-engine/status endpoint"""
    print("\n🔍 Testing NEW Fetch Engine Status Endpoint...")
    
    success, data, status = await make_request(session, "/data/fetch-engine/status")
    
    if not success:
        results.add_fail("Fetch Engine Status", f"Request failed: {data} (HTTP {status})", is_critical=True)
        return
    
    # Validate response structure
    required_sections = ["engine", "is_running", "configuration", "statistics", "timing"]
    for section in required_sections:
        if section not in data:
            results.add_fail("Fetch Engine Structure", f"Missing section: {section}")
    
    # Check if engine is running
    is_running = data.get("is_running", False)
    if is_running:
        results.add_pass("Fetch Engine Running", "Engine is operational")
    else:
        results.add_fail("Fetch Engine Running", "Engine is not running", is_critical=True)
        return
    
    # Check configuration
    config = data.get("configuration", {})
    price_interval = config.get("price_fetch_interval_seconds")
    candle_interval = config.get("candle_fetch_interval_seconds")
    
    # Verify intervals match architecture spec
    if price_interval:
        if price_interval == 30:
            results.add_pass("Price Fetch Interval", f"Correct interval: {price_interval}s")
        else:
            results.add_warning("Price Fetch Interval", f"Expected 30s, got {price_interval}s")
    
    if candle_interval:
        if candle_interval == 120:
            results.add_pass("Candle Fetch Interval", f"Correct interval: {candle_interval}s")
        else:
            results.add_warning("Candle Fetch Interval", f"Expected 120s, got {candle_interval}s")
    
    # Check statistics
    stats = data.get("statistics", {})
    api_calls_per_min = stats.get("api_calls_per_minute", 0)
    
    if api_calls_per_min > 0:
        results.add_pass("API Call Rate", f"{api_calls_per_min} calls/min")
    else:
        results.add_warning("API Call Rate", "No API calls recorded yet")
    
    results.add_pass("Fetch Engine Status", "All validations passed")


async def test_api_usage_estimate(session: aiohttp.ClientSession, results: TestResult):
    """Test NEW /api/data/api-usage endpoint"""
    print("\n🔍 Testing NEW API Usage Estimation Endpoint...")
    
    success, data, status = await make_request(session, "/data/api-usage")
    
    if not success:
        results.add_fail("API Usage Endpoint", f"Request failed: {data} (HTTP {status})")
        return
    
    # Validate response structure
    required_fields = ["price_calls_per_minute", "candle_calls_per_minute", 
                      "total_calls_per_minute", "within_free_tier"]
    
    for field in required_fields:
        if field not in data:
            results.add_fail("API Usage Structure", f"Missing field: {field}")
    
    # Check API usage rates
    price_calls = data.get("price_calls_per_minute", 0)
    candle_calls = data.get("candle_calls_per_minute", 0) 
    total_calls = data.get("total_calls_per_minute", 0)
    within_free_tier = data.get("within_free_tier", False)
    
    # Log usage breakdown
    results.add_pass("Price API Calls", f"{price_calls} calls/min")
    results.add_pass("Candle API Calls", f"{candle_calls} calls/min")
    results.add_pass("Total API Calls", f"{total_calls} calls/min")
    
    # Check free tier compliance (Twelve Data: 8 credits/min)
    if within_free_tier:
        results.add_pass("Free Tier Compliance", f"Within limits: {total_calls}/8 calls/min")
    else:
        results.add_fail("Free Tier Compliance", f"Exceeds limit: {total_calls}/8 calls/min", is_critical=True)
    
    # Warn if approaching limits
    if total_calls >= 7:
        results.add_warning("API Usage Warning", f"Close to limit: {total_calls}/8 calls/min")


async def test_scanner_v2_performance(session: aiohttp.ClientSession, results: TestResult):
    """Test Scanner v2 performance and configuration"""
    print("\n🔍 Testing Scanner v2 Performance...")
    
    success, data, status = await make_request(session, "/scanner/v2/status")
    
    if not success:
        results.add_fail("Scanner v2 Status", f"Request failed: {data} (HTTP {status})")
        return
    
    # Check if scanner is running
    is_running = data.get("is_running", False)
    if is_running:
        results.add_pass("Scanner v2 Running", "Advanced scanner operational")
    else:
        results.add_fail("Scanner v2 Running", "Scanner not running")
        return
    
    # Check scan interval (should be 5 seconds for fast operation)
    scan_interval = data.get("scan_interval_seconds")
    if scan_interval:
        if scan_interval <= 5:
            results.add_pass("Scanner Interval", f"Fast scanning: {scan_interval}s")
        else:
            results.add_warning("Scanner Interval", f"Slower than expected: {scan_interval}s (target: ≤5s)")
    
    # Check statistics
    stats = data.get("statistics", {})
    total_scans = stats.get("total_scans", 0)
    
    if total_scans > 0:
        results.add_pass("Scanner Activity", f"{total_scans} scans completed")
    else:
        results.add_warning("Scanner Activity", "No scans recorded yet")
    
    # Verify configuration for quality signals
    config = data.get("configuration", {})
    score_threshold = config.get("score_threshold")
    
    if score_threshold and score_threshold >= 78:
        results.add_pass("Quality Threshold", f"High quality signals: {score_threshold}% threshold")
    elif score_threshold:
        results.add_warning("Quality Threshold", f"Lower threshold: {score_threshold}%")


async def test_existing_endpoints_compatibility(session: aiohttp.ClientSession, results: TestResult):
    """Test that existing endpoints still work with new architecture"""
    print("\n🔍 Testing Existing Endpoint Compatibility...")
    
    # Test health endpoint
    success, data, status = await make_request(session, "/health")
    if success and data.get("status") in ["healthy", "degraded"]:
        results.add_pass("Health Endpoint", f"Status: {data.get('status')}")
    else:
        results.add_fail("Health Endpoint", f"Unhealthy response: {data}")
    
    # Test live prices endpoint (should still work)
    success, data, status = await make_request(session, "/provider/live-prices")
    if success:
        prices = data.get("prices", {})
        
        for asset in ["EURUSD", "XAUUSD"]:
            asset_data = prices.get(asset, {})
            
            if asset_data.get("status") == "LIVE":
                bid = asset_data.get("bid")
                ask = asset_data.get("ask")
                
                if bid and ask and bid > 0 and ask > 0:
                    results.add_pass(f"{asset} Live Price", f"Bid: {bid}, Ask: {ask}")
                else:
                    results.add_warning(f"{asset} Live Price", "Invalid price data")
            else:
                results.add_warning(f"{asset} Live Price", f"Status: {asset_data.get('status', 'Unknown')}")
    else:
        results.add_fail("Live Prices Endpoint", f"Request failed: {data}")


async def measure_scanner_cycle_time(session: aiohttp.ClientSession, results: TestResult):
    """Measure scanner cycle performance - should be ultra-fast with cache"""
    print("\n⏱️  Measuring Scanner Cycle Performance...")
    
    # Make multiple rapid requests to scanner endpoints to test cache performance
    endpoints = [
        "/scanner/v2/bias/EURUSD",
        "/scanner/v2/bias/XAUUSD", 
        "/scanner/v2/structure/EURUSD",
        "/scanner/v2/structure/XAUUSD"
    ]
    
    total_time = 0
    successful_calls = 0
    
    for endpoint in endpoints:
        start_time = time.time()
        success, data, status = await make_request(session, endpoint)
        end_time = time.time()
        
        duration_ms = (end_time - start_time) * 1000
        
        if success:
            successful_calls += 1
            total_time += duration_ms
            
            # Log individual response times
            if duration_ms <= 100:  # Sub-100ms is excellent for cache reads
                results.add_pass(f"Scanner Response Time", f"{endpoint}: {duration_ms:.1f}ms")
            elif duration_ms <= 500:
                results.add_warning(f"Scanner Response Time", f"{endpoint}: {duration_ms:.1f}ms (target: <100ms)")
            else:
                results.add_fail(f"Scanner Response Time", f"{endpoint}: {duration_ms:.1f}ms (too slow)")
        else:
            results.add_fail(f"Scanner Endpoint", f"{endpoint}: {data}")
    
    # Calculate average cycle time
    if successful_calls > 0:
        avg_time = total_time / successful_calls
        
        if avg_time <= 100:
            results.add_pass("Average Scanner Time", f"{avg_time:.1f}ms (ultra-fast cache reads)")
        elif avg_time <= 500:
            results.add_warning("Average Scanner Time", f"{avg_time:.1f}ms (acceptable)")
        else:
            results.add_fail("Average Scanner Time", f"{avg_time:.1f}ms (too slow for cache-based system)")


async def run_comprehensive_tests():
    """Run all tests for the new Data-Fetch/Scanner architecture"""
    print("🚀 STARTING PROPSIGNAL ENGINE - DATA ARCHITECTURE TESTS")
    print(f"Backend URL: {BACKEND_URL}")
    print(f"Test Start Time: {datetime.now().isoformat()}")
    
    results = TestResult()
    
    async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=30)) as session:
        
        # Test NEW endpoints in order of importance
        await test_new_cache_status_endpoint(session, results)
        await test_cached_symbol_data(session, results)  
        await test_fetch_engine_status(session, results)
        await test_api_usage_estimate(session, results)
        
        # Test scanner performance
        await test_scanner_v2_performance(session, results)
        await measure_scanner_cycle_time(session, results)
        
        # Test existing endpoint compatibility
        await test_existing_endpoints_compatibility(session, results)
    
    # Print comprehensive results
    results.print_summary()
    
    # Return success status for automation
    return len(results.critical_failures) == 0


if __name__ == "__main__":
    asyncio.run(run_comprehensive_tests())