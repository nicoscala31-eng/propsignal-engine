================================================================================
# PropSignal Engine v6.0 - COMPLETE PERFORMANCE REPORT
# Report Generated: 2026-03-27 06:11:18 UTC
# Data Period: v6.0 Deployment (2026-03-25 11:50:00) to Present
================================================================================

## 1. EXECUTIVE SUMMARY
----------------------------------------
Total Candidates Evaluated (v6.0): 953
Acceptance Rate: 1.0%

### ACCEPTED TRADES (REAL)
  - Total Accepted: 10
  - Completed: 10 (W:7 / L:3)
  - Expired: 0
  - Pending: 0
  - **Win Rate: 70.0%**
  - **Total R: 823.95R**
  - **Expectancy: 82.395R per trade**

### REJECTED TRADES (SIMULATED)
  - Total Rejected: 943
  - Simulated Completed: 10 (W:0 / L:10)
  - Simulated Expired: 0
  - Simulated Pending: 933
  - **Simulated Win Rate: 0.0%**
  - **Simulated Total R: -10.00R**
  - **Simulated Expectancy: -1.000R per trade**

## 2. FILTER EFFECTIVENESS ANALYSIS
----------------------------------------
### news_blocked
  - Blocked: 943
  - Would have WON: 0
  - Would have LOST: 10
  - Filter Accuracy: 1.1% (correctly blocked losers)

### duplicate_blocked
  - Blocked: 518
  - Would have WON: 0
  - Would have LOST: 10
  - Filter Accuracy: 1.9% (correctly blocked losers)

### score_passed
  - Blocked: 495
  - Would have WON: 0
  - Would have LOST: 10
  - Filter Accuracy: 2.0% (correctly blocked losers)

### mtf_passed
  - Blocked: 108
  - Would have WON: 0
  - Would have LOST: 10
  - Filter Accuracy: 9.3% (correctly blocked losers)

## 3. REJECTION REASONS BREAKDOWN
----------------------------------------
  - duplicate: 425 (45.1%)
  - low_confidence: 375 (39.8%)
  - weak_mtf: 108 (11.5%)
  - setup_penalty_dropped_score: 35 (3.7%)

## 4. MISSED OPPORTUNITIES (Rejected Winners)
----------------------------------------
No significant missed opportunities detected.

## 5. ASSET COMPARISON: EURUSD vs XAUUSD
----------------------------------------
### EURUSD
  - Wins: 2
  - Losses: 0
  - Expired: 0
  - Win Rate: 100.0%
  - Total R: 3.00R
  - Expectancy: 1.500R per trade

### XAUUSD
  - Wins: 5
  - Losses: 3
  - Expired: 0
  - Win Rate: 62.5%
  - Total R: 5.14R
  - Expectancy: 0.642R per trade

## 6. ENTRY & STOP LOSS QUALITY ANALYSIS
----------------------------------------
Total SL Hits: 3
SL Hit after showing profit (MFE > 0): 2
**Potentially Tight SL Rate: 66.7%**

Average Peak R before SL Hit: 0.078R

### Trades that reached profit before SL:
  - XAUUSD_BUY_20260325_120204... | Peak R: 0.038R | Time in Profit: 510s
  - XAUUSD_BUY_20260325_120626... | Peak R: 0.118R | Time in Profit: 570s

## 7. STATISTICAL VALIDITY CHECK
----------------------------------------
Completed Trades for Analysis: 10
⚠️ **WARNING: SAMPLE SIZE TOO SMALL (<20)**
   Results are NOT statistically significant.
   Continue monitoring until at least 30-50 trades complete.

## 8. FINAL ACTION RECOMMENDATIONS
----------------------------------------
### ✅ FILTERS ARE WORKING
- Accepted WR (70.0%) > Rejected WR (0.0%)
- Current filtering is correctly separating winners from losers
- Recommendation: MAINTAIN current v6.0 settings

### ⚠️ STOP LOSS MAY BE TOO TIGHT
- 67% of SL hits showed profit before reversal
- Consider:
   a) Widening SL by 10-20%
   b) Implementing trailing stop after 0.5R profit
   c) Moving to breakeven after 1R profit

================================================================================
# END OF REPORT
================================================================================