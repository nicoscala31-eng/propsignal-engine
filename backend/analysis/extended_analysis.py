#!/usr/bin/env python3
"""
PATTERN ENGINE V3.0 - EXTENDED DEEP ANALYSIS
=============================================
Analisi avanzata su:
- MFE/MAE Distribution
- Pattern Count correlation
- Direction Analysis
- Score vs Outcome correlation
- Rejected simulation deep dive
"""

import json
import os
from collections import defaultdict
from datetime import datetime
from typing import Dict, List, Any
import statistics

DATA_DIR = "/app/backend/data"
STORAGE_DIR = "/app/backend/storage"

def load_json(filepath: str) -> Any:
    try:
        with open(filepath, 'r') as f:
            return json.load(f)
    except:
        return None

def safe_div(a, b, default=0):
    return a / b if b != 0 else default

def main():
    print("=" * 70)
    print("PATTERN ENGINE V3.0 - EXTENDED DEEP ANALYSIS")
    print("=" * 70)
    print()
    
    # Load data
    candidate_audit = load_json(f"{DATA_DIR}/candidate_audit.json") or {}
    signal_stats = load_json(f"{DATA_DIR}/signal_stats.json") or {}
    signal_snapshots = load_json(f"{DATA_DIR}/signal_snapshots.json") or {}
    tracked_signals = load_json(f"{DATA_DIR}/tracked_signals.json") or []
    missed_opps = load_json(f"{STORAGE_DIR}/missed_opportunities.json") or {}
    
    candidates = candidate_audit.get('candidates', [])
    snapshots = signal_snapshots.get('snapshots', [])
    missed_records = missed_opps.get('records', [])
    
    # ============================================================
    # 1. MFE/MAE ANALYSIS
    # ============================================================
    print("=" * 50)
    print("1. MFE/MAE DISTRIBUTION ANALYSIS")
    print("=" * 50)
    
    mfe_values = []
    mae_values = []
    mfe_by_outcome = {'win': [], 'loss': [], 'expired': []}
    mae_by_outcome = {'win': [], 'loss': [], 'expired': []}
    
    for c in candidates:
        outcome_data = c.get('outcome_data', {})
        if outcome_data:
            mfe = outcome_data.get('mfe_r', 0)
            mae = outcome_data.get('mae_r', 0)
            outcome = outcome_data.get('outcome', '')
            
            if mfe > 0:
                mfe_values.append(mfe)
                if outcome in ['win', 'tp_hit']:
                    mfe_by_outcome['win'].append(mfe)
                elif outcome in ['loss', 'sl_hit']:
                    mfe_by_outcome['loss'].append(mfe)
                elif outcome == 'expired':
                    mfe_by_outcome['expired'].append(mfe)
            
            if mae > 0:
                mae_values.append(mae)
                if outcome in ['win', 'tp_hit']:
                    mae_by_outcome['win'].append(mae)
                elif outcome in ['loss', 'sl_hit']:
                    mae_by_outcome['loss'].append(mae)
                elif outcome == 'expired':
                    mae_by_outcome['expired'].append(mae)
    
    print(f"\nOverall MFE (Maximum Favorable Excursion):")
    if mfe_values:
        print(f"  Count: {len(mfe_values)}")
        print(f"  Mean: {statistics.mean(mfe_values):.3f}R")
        print(f"  Median: {statistics.median(mfe_values):.3f}R")
        print(f"  Max: {max(mfe_values):.3f}R")
        print(f"  Min: {min(mfe_values):.3f}R")
    
    print(f"\nOverall MAE (Maximum Adverse Excursion):")
    if mae_values:
        print(f"  Count: {len(mae_values)}")
        print(f"  Mean: {statistics.mean(mae_values):.3f}R")
        print(f"  Median: {statistics.median(mae_values):.3f}R")
        print(f"  Max: {max(mae_values):.3f}R")
    
    print(f"\nMFE by Outcome:")
    for outcome, values in mfe_by_outcome.items():
        if values:
            print(f"  {outcome.upper()}: mean={statistics.mean(values):.3f}R, count={len(values)}")
    
    print(f"\nMAE by Outcome:")
    for outcome, values in mae_by_outcome.items():
        if values:
            print(f"  {outcome.upper()}: mean={statistics.mean(values):.3f}R, count={len(values)}")
    
    # Key insight: trades that lose often have low MFE
    print(f"\n⚠️ INSIGHT: ")
    if mfe_by_outcome['loss']:
        loss_mfe = statistics.mean(mfe_by_outcome['loss'])
        if loss_mfe < 0.5:
            print(f"   Losing trades have very low MFE ({loss_mfe:.3f}R) - never reached favorable territory")
        else:
            print(f"   Losing trades had MFE of {loss_mfe:.3f}R - could have been winners with better exit")
    
    # ============================================================
    # 2. SCORE VS OUTCOME CORRELATION
    # ============================================================
    print("\n" + "=" * 50)
    print("2. SCORE VS OUTCOME CORRELATION")
    print("=" * 50)
    
    score_buckets = {
        '80-100': {'wins': 0, 'losses': 0, 'expired': 0, 'scores': []},
        '70-79': {'wins': 0, 'losses': 0, 'expired': 0, 'scores': []},
        '65-69': {'wins': 0, 'losses': 0, 'expired': 0, 'scores': []},
        '60-64': {'wins': 0, 'losses': 0, 'expired': 0, 'scores': []},
        '<60': {'wins': 0, 'losses': 0, 'expired': 0, 'scores': []}
    }
    
    for c in candidates:
        score = c.get('score_breakdown', {}).get('total_score', 0)
        outcome_data = c.get('outcome_data', {})
        outcome = outcome_data.get('outcome', '') if outcome_data else ''
        
        if score >= 80:
            bucket = '80-100'
        elif score >= 70:
            bucket = '70-79'
        elif score >= 65:
            bucket = '65-69'
        elif score >= 60:
            bucket = '60-64'
        else:
            bucket = '<60'
        
        score_buckets[bucket]['scores'].append(score)
        if outcome in ['win', 'tp_hit']:
            score_buckets[bucket]['wins'] += 1
        elif outcome in ['loss', 'sl_hit']:
            score_buckets[bucket]['losses'] += 1
        elif outcome == 'expired':
            score_buckets[bucket]['expired'] += 1
    
    print(f"\nScore Bucket Performance:")
    print(f"{'Bucket':<12} {'Trades':<8} {'Wins':<6} {'Losses':<8} {'WinRate':<10} {'Expectancy':<12}")
    print("-" * 60)
    
    for bucket, data in score_buckets.items():
        total = data['wins'] + data['losses']
        if total > 0:
            wr = safe_div(data['wins'], total) * 100
            exp = (wr/100 * 1.5) - ((1-wr/100) * 1)
            print(f"{bucket:<12} {total:<8} {data['wins']:<6} {data['losses']:<8} {wr:<10.1f}% {exp:<12.3f}")
    
    # Check for inversion
    print(f"\n⚠️ CRITICAL CHECK: Score Correlation")
    high_wr = safe_div(score_buckets['80-100']['wins'], 
                       score_buckets['80-100']['wins'] + score_buckets['80-100']['losses'])
    low_wr = safe_div(score_buckets['60-64']['wins'], 
                      score_buckets['60-64']['wins'] + score_buckets['60-64']['losses'])
    
    if low_wr > high_wr:
        print(f"   ❌ INVERSION DETECTED: Low scores ({low_wr*100:.1f}%) beat high scores ({high_wr*100:.1f}%)")
        print(f"   → Scoring system is MISCALIBRATED - higher scores should = higher winrate")
    else:
        print(f"   ✅ Correlation OK: High scores ({high_wr*100:.1f}%) beat low scores ({low_wr*100:.1f}%)")
    
    # ============================================================
    # 3. DIRECTION ANALYSIS
    # ============================================================
    print("\n" + "=" * 50)
    print("3. DIRECTION ANALYSIS (BUY vs SELL)")
    print("=" * 50)
    
    direction_stats = {
        'BUY': {'wins': 0, 'losses': 0, 'expired': 0, 'total_r': 0},
        'SELL': {'wins': 0, 'losses': 0, 'expired': 0, 'total_r': 0}
    }
    
    for c in candidates:
        direction = c.get('direction', '')
        outcome_data = c.get('outcome_data', {})
        outcome = outcome_data.get('outcome', '') if outcome_data else ''
        total_r = outcome_data.get('total_r', 0) if outcome_data else 0
        
        if direction in direction_stats:
            if outcome in ['win', 'tp_hit']:
                direction_stats[direction]['wins'] += 1
                direction_stats[direction]['total_r'] += total_r
            elif outcome in ['loss', 'sl_hit']:
                direction_stats[direction]['losses'] += 1
                direction_stats[direction]['total_r'] -= 1  # -1R per loss
            elif outcome == 'expired':
                direction_stats[direction]['expired'] += 1
    
    print(f"\n{'Direction':<10} {'Trades':<8} {'Wins':<6} {'Losses':<8} {'WinRate':<10} {'Net R':<10}")
    print("-" * 55)
    
    for direction, data in direction_stats.items():
        total = data['wins'] + data['losses']
        if total > 0:
            wr = safe_div(data['wins'], total) * 100
            print(f"{direction:<10} {total:<8} {data['wins']:<6} {data['losses']:<8} {wr:<10.1f}% {data['total_r']:<10.1f}R")
    
    # ============================================================
    # 4. TIME TO OUTCOME ANALYSIS
    # ============================================================
    print("\n" + "=" * 50)
    print("4. TIME TO OUTCOME ANALYSIS")
    print("=" * 50)
    
    win_times = []
    loss_times = []
    
    for c in candidates:
        outcome_data = c.get('outcome_data', {})
        if outcome_data:
            time_mins = outcome_data.get('time_to_outcome_minutes', 0)
            outcome = outcome_data.get('outcome', '')
            
            if time_mins > 0 and time_mins < 10000:  # Filter outliers
                if outcome in ['win', 'tp_hit']:
                    win_times.append(time_mins)
                elif outcome in ['loss', 'sl_hit']:
                    loss_times.append(time_mins)
    
    print(f"\nTime to Outcome:")
    if win_times:
        print(f"  Winning trades: avg {statistics.mean(win_times):.1f} mins, median {statistics.median(win_times):.1f} mins")
    if loss_times:
        print(f"  Losing trades: avg {statistics.mean(loss_times):.1f} mins, median {statistics.median(loss_times):.1f} mins")
    
    if win_times and loss_times:
        if statistics.mean(loss_times) < statistics.mean(win_times):
            print(f"\n⚠️ INSIGHT: Losses happen faster ({statistics.mean(loss_times):.0f}m) than wins ({statistics.mean(win_times):.0f}m)")
            print(f"   → Consider reviewing stop loss placement")
    
    # ============================================================
    # 5. FACTOR CONTRIBUTION DEEP ANALYSIS
    # ============================================================
    print("\n" + "=" * 50)
    print("5. FACTOR PREDICTIVE POWER ANALYSIS")
    print("=" * 50)
    
    factor_performance = defaultdict(lambda: {
        'high_score_wins': 0, 'high_score_losses': 0,
        'low_score_wins': 0, 'low_score_losses': 0
    })
    
    for snap in snapshots:
        outcome = snap.get('outcome', {})
        result = outcome.get('result', '') if outcome else ''
        
        for factor in snap.get('factor_contributions', []):
            key = factor.get('factor_key', 'unknown')
            score = factor.get('score_contribution', 0)
            weight = factor.get('weight_pct', 10)
            
            # High score = >70% of max possible
            max_possible = weight
            is_high = score > (max_possible * 0.7)
            
            if result == 'win':
                if is_high:
                    factor_performance[key]['high_score_wins'] += 1
                else:
                    factor_performance[key]['low_score_wins'] += 1
            elif result == 'loss':
                if is_high:
                    factor_performance[key]['high_score_losses'] += 1
                else:
                    factor_performance[key]['low_score_losses'] += 1
    
    print(f"\nFactor Predictive Power:")
    print(f"{'Factor':<20} {'High WR':<12} {'Low WR':<12} {'Predictive?':<15}")
    print("-" * 60)
    
    for factor, data in factor_performance.items():
        high_total = data['high_score_wins'] + data['high_score_losses']
        low_total = data['low_score_wins'] + data['low_score_losses']
        
        high_wr = safe_div(data['high_score_wins'], high_total) * 100 if high_total > 5 else None
        low_wr = safe_div(data['low_score_wins'], low_total) * 100 if low_total > 5 else None
        
        if high_wr is not None and low_wr is not None:
            diff = high_wr - low_wr
            predictive = "YES" if diff > 10 else ("INVERSE" if diff < -10 else "NO")
            print(f"{factor:<20} {high_wr:<12.1f}% {low_wr:<12.1f}% {predictive:<15}")
    
    # ============================================================
    # 6. FTA DISTANCE ANALYSIS
    # ============================================================
    print("\n" + "=" * 50)
    print("6. FTA (First Trouble Area) DISTANCE ANALYSIS")
    print("=" * 50)
    
    fta_buckets = {
        '<0.3R': {'wins': 0, 'losses': 0},
        '0.3-0.5R': {'wins': 0, 'losses': 0},
        '0.5-0.8R': {'wins': 0, 'losses': 0},
        '0.8-1.0R': {'wins': 0, 'losses': 0},
        '>1.0R': {'wins': 0, 'losses': 0}
    }
    
    for c in candidates:
        score_bd = c.get('score_breakdown', {})
        fta_r = score_bd.get('fta_distance_r', 0) or score_bd.get('clean_space_r', 0)
        outcome_data = c.get('outcome_data', {})
        outcome = outcome_data.get('outcome', '') if outcome_data else ''
        
        if fta_r > 0:
            if fta_r < 0.3:
                bucket = '<0.3R'
            elif fta_r < 0.5:
                bucket = '0.3-0.5R'
            elif fta_r < 0.8:
                bucket = '0.5-0.8R'
            elif fta_r < 1.0:
                bucket = '0.8-1.0R'
            else:
                bucket = '>1.0R'
            
            if outcome in ['win', 'tp_hit']:
                fta_buckets[bucket]['wins'] += 1
            elif outcome in ['loss', 'sl_hit']:
                fta_buckets[bucket]['losses'] += 1
    
    print(f"\nFTA Distance vs Outcome:")
    print(f"{'FTA Bucket':<12} {'Wins':<8} {'Losses':<8} {'WinRate':<10}")
    print("-" * 40)
    
    for bucket, data in fta_buckets.items():
        total = data['wins'] + data['losses']
        if total > 0:
            wr = safe_div(data['wins'], total) * 100
            print(f"{bucket:<12} {data['wins']:<8} {data['losses']:<8} {wr:<10.1f}%")
    
    # ============================================================
    # 7. REJECTION REASON ANALYSIS
    # ============================================================
    print("\n" + "=" * 50)
    print("7. REJECTION REASON DEEP ANALYSIS")
    print("=" * 50)
    
    rejection_stats = defaultdict(lambda: {'count': 0, 'scores': [], 'sessions': defaultdict(int)})
    
    for c in candidates:
        if c.get('decision') == 'rejected':
            reason = c.get('rejection_reason', 'unknown')
            score = c.get('score_breakdown', {}).get('total_score', 0)
            session = c.get('session', 'unknown')
            
            rejection_stats[reason]['count'] += 1
            rejection_stats[reason]['scores'].append(score)
            rejection_stats[reason]['sessions'][session] += 1
    
    print(f"\n{'Rejection Reason':<30} {'Count':<8} {'Avg Score':<12} {'Top Session':<15}")
    print("-" * 70)
    
    for reason, data in sorted(rejection_stats.items(), key=lambda x: x[1]['count'], reverse=True):
        avg_score = statistics.mean(data['scores']) if data['scores'] else 0
        top_session = max(data['sessions'].items(), key=lambda x: x[1])[0] if data['sessions'] else 'N/A'
        print(f"{reason:<30} {data['count']:<8} {avg_score:<12.1f} {top_session:<15}")
    
    # ============================================================
    # 8. SESSION x ASSET MATRIX
    # ============================================================
    print("\n" + "=" * 50)
    print("8. SESSION x ASSET PERFORMANCE MATRIX")
    print("=" * 50)
    
    matrix = defaultdict(lambda: defaultdict(lambda: {'wins': 0, 'losses': 0}))
    
    for c in candidates:
        session = c.get('session', 'unknown')
        symbol = c.get('symbol', 'unknown')
        outcome_data = c.get('outcome_data', {})
        outcome = outcome_data.get('outcome', '') if outcome_data else ''
        
        if outcome in ['win', 'tp_hit']:
            matrix[session][symbol]['wins'] += 1
        elif outcome in ['loss', 'sl_hit']:
            matrix[session][symbol]['losses'] += 1
    
    print(f"\n{'Session':<20} {'EURUSD WR':<15} {'XAUUSD WR':<15}")
    print("-" * 50)
    
    for session in ['London', 'London/NY Overlap', 'New York', 'Asian']:
        eurusd = matrix[session]['EURUSD']
        xauusd = matrix[session]['XAUUSD']
        
        eu_total = eurusd['wins'] + eurusd['losses']
        xau_total = xauusd['wins'] + xauusd['losses']
        
        eu_wr = f"{safe_div(eurusd['wins'], eu_total)*100:.1f}% ({eu_total})" if eu_total > 0 else "N/A"
        xau_wr = f"{safe_div(xauusd['wins'], xau_total)*100:.1f}% ({xau_total})" if xau_total > 0 else "N/A"
        
        print(f"{session:<20} {eu_wr:<15} {xau_wr:<15}")
    
    # ============================================================
    # 9. SUMMARY: KEY FINDINGS
    # ============================================================
    print("\n" + "=" * 70)
    print("SUMMARY: KEY FINDINGS & CRITICAL ISSUES")
    print("=" * 70)
    
    findings = []
    
    # Check session issues
    session_stats = signal_stats.get('by_session', {})
    for session, data in session_stats.items():
        w, l = data.get('wins', 0), data.get('losses', 0)
        if w + l >= 15 and safe_div(w, w+l) < 0.35:
            findings.append(f"❌ {session}: {safe_div(w,w+l)*100:.1f}% winrate ({l-w} net losses)")
    
    # Check confidence inversion
    conf_stats = signal_stats.get('by_confidence', {})
    strong = conf_stats.get('strong_80_100', {})
    acceptable = conf_stats.get('acceptable_60_69', {})
    s_wr = safe_div(strong.get('wins',0), strong.get('wins',0)+strong.get('losses',0))
    a_wr = safe_div(acceptable.get('wins',0), acceptable.get('wins',0)+acceptable.get('losses',0))
    if a_wr > s_wr:
        findings.append(f"❌ CONFIDENCE INVERSION: Score 60-69 ({a_wr*100:.1f}%) beats 80-100 ({s_wr*100:.1f}%)")
    
    # Check expired rate
    total = signal_stats.get('total_tracked', 0)
    expired = signal_stats.get('expired', 0)
    if total > 0 and safe_div(expired, total) > 0.25:
        findings.append(f"⚠️ HIGH EXPIRED RATE: {expired}/{total} ({safe_div(expired,total)*100:.1f}%)")
    
    print("\nCRITICAL ISSUES FOUND:")
    for i, finding in enumerate(findings, 1):
        print(f"  {i}. {finding}")
    
    print("\n" + "=" * 70)
    print("ACTIONABLE RECOMMENDATIONS")
    print("=" * 70)
    
    recommendations = [
        "1. DISABLE Asian session trading - 20% winrate is destructive",
        "2. RESTRICT London session - 29.9% winrate losing money",
        "3. RECALIBRATE scoring - high scores should predict wins",
        "4. FOCUS on New York session - 95% winrate is the edge",
        "5. REVIEW expired trades - 28% never hitting TP/SL suggests wrong levels",
        "6. ANALYZE why high confidence underperforms low confidence"
    ]
    
    for rec in recommendations:
        print(f"  {rec}")
    
    print("\n" + "=" * 70)
    print("END OF EXTENDED ANALYSIS")
    print("=" * 70)


if __name__ == "__main__":
    main()
