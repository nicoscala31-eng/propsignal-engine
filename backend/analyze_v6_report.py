#!/usr/bin/env python3
"""
PropSignal Engine v6.0 - Complete Performance Report Generator
Analyzes ONLY data from v6.0 deployment (2026-03-25 11:50:00 UTC onwards)
"""

import json
from datetime import datetime
from collections import defaultdict
import statistics

# v6.0 deployment timestamp
V6_DEPLOYMENT = datetime(2026, 3, 25, 11, 50, 0)

def load_json(filepath):
    try:
        with open(filepath, 'r') as f:
            return json.load(f)
    except Exception as e:
        print(f"Error loading {filepath}: {e}")
        return None

def parse_timestamp(ts_str):
    """Parse timestamp string to datetime"""
    if not ts_str:
        return None
    try:
        # Handle various formats
        for fmt in ["%Y-%m-%dT%H:%M:%S.%f", "%Y-%m-%dT%H:%M:%S"]:
            try:
                return datetime.strptime(ts_str, fmt)
            except:
                continue
        return None
    except:
        return None

def analyze_tracked_signals(data):
    """Analyze tracked_signals.json for real trades"""
    results = {
        'total': 0,
        'wins': 0,
        'losses': 0,
        'expired': 0,
        'active': 0,
        'total_r': 0,
        'trades': [],
        'by_asset': defaultdict(lambda: {'wins': 0, 'losses': 0, 'expired': 0, 'total_r': 0}),
        'mfe_before_sl': [],  # For SL analysis
        'entry_timing': [],
        'sl_quality': {'tight_sl_count': 0, 'total_sl_hit': 0}
    }
    
    # Process completed signals
    completed = data.get('completed', [])
    for sig in completed:
        ts = parse_timestamp(sig.get('timestamp'))
        if not ts or ts < V6_DEPLOYMENT:
            continue
        
        results['total'] += 1
        asset = sig.get('asset', 'UNKNOWN')
        outcome = sig.get('final_outcome', '').lower()
        status = sig.get('status', '').lower()
        
        # Calculate R
        r_value = 0
        if outcome == 'win' or status == 'tp_hit':
            r_value = sig.get('risk_reward', 1.5)
            results['wins'] += 1
            results['by_asset'][asset]['wins'] += 1
        elif outcome == 'loss' or status == 'sl_hit':
            r_value = -1
            results['losses'] += 1
            results['by_asset'][asset]['losses'] += 1
            
            # SL quality analysis
            results['sl_quality']['total_sl_hit'] += 1
            mfe = sig.get('max_favorable_excursion', 0)
            moved_favorable = sig.get('moved_favorable_before_fail', False)
            reached_half_r = sig.get('reached_half_r', False)
            
            if moved_favorable or reached_half_r:
                results['sl_quality']['tight_sl_count'] += 1
                results['mfe_before_sl'].append({
                    'signal_id': sig.get('signal_id'),
                    'asset': asset,
                    'mfe': mfe,
                    'peak_r': sig.get('peak_r_before_reversal', 0),
                    'time_in_profit': sig.get('time_in_profit_seconds', 0)
                })
        elif outcome == 'expired':
            results['expired'] += 1
            results['by_asset'][asset]['expired'] += 1
        
        results['total_r'] += r_value
        results['by_asset'][asset]['total_r'] += r_value
        
        results['trades'].append({
            'signal_id': sig.get('signal_id'),
            'asset': asset,
            'direction': sig.get('direction'),
            'score': sig.get('confidence_score', 0),
            'outcome': outcome,
            'r_value': r_value,
            'entry': sig.get('entry_price'),
            'sl': sig.get('stop_loss'),
            'tp1': sig.get('take_profit_1'),
            'mfe': sig.get('max_favorable_excursion'),
            'mae': sig.get('max_adverse_excursion'),
            'timestamp': sig.get('timestamp')
        })
    
    # Process active signals
    active = data.get('active', [])
    for sig in active:
        ts = parse_timestamp(sig.get('timestamp'))
        if ts and ts >= V6_DEPLOYMENT:
            results['active'] += 1
    
    return results

def analyze_candidate_audit(data):
    """Analyze candidate_audit.json for accepted vs rejected comparison"""
    results = {
        'total_candidates': 0,
        'accepted': {
            'count': 0,
            'wins': 0,
            'losses': 0,
            'expired': 0,
            'pending': 0,
            'total_r': 0,
            'trades': [],
            'by_reason': defaultdict(int)
        },
        'rejected': {
            'count': 0,
            'simulated_wins': 0,
            'simulated_losses': 0,
            'simulated_expired': 0,
            'simulated_pending': 0,
            'simulated_total_r': 0,
            'by_reason': defaultdict(int),
            'trades': []
        },
        'filter_effectiveness': defaultdict(lambda: {'blocked': 0, 'would_win': 0, 'would_lose': 0}),
        'missed_opportunities': []
    }
    
    candidates = data.get('candidates', [])
    
    for cand in candidates:
        ts = parse_timestamp(cand.get('timestamp'))
        if not ts or ts < V6_DEPLOYMENT:
            continue
        
        results['total_candidates'] += 1
        decision = cand.get('decision', '').lower()
        outcome_data = cand.get('outcome_data', {})
        outcome = outcome_data.get('outcome', 'pending').lower()
        is_simulated = outcome_data.get('is_simulated', False)
        total_r = outcome_data.get('total_r', 0)
        mfe_r = outcome_data.get('mfe_r', 0)
        
        score = cand.get('score_breakdown', {}).get('total_score', 0)
        symbol = cand.get('symbol', 'UNKNOWN')
        rejection_reason = cand.get('rejection_reason', '')
        
        if decision == 'accepted':
            results['accepted']['count'] += 1
            
            if outcome == 'win':
                results['accepted']['wins'] += 1
                results['accepted']['total_r'] += total_r if total_r > 0 else 1.5
            elif outcome == 'loss':
                results['accepted']['losses'] += 1
                results['accepted']['total_r'] -= 1
            elif outcome == 'expired':
                results['accepted']['expired'] += 1
            else:
                results['accepted']['pending'] += 1
            
            results['accepted']['trades'].append({
                'symbol': symbol,
                'score': score,
                'outcome': outcome,
                'total_r': total_r,
                'mfe_r': mfe_r,
                'timestamp': cand.get('timestamp')
            })
        else:
            # Rejected
            results['rejected']['count'] += 1
            results['rejected']['by_reason'][rejection_reason] += 1
            
            # Track filter effectiveness
            filter_flags = cand.get('filter_flags', {})
            for filter_name, passed in filter_flags.items():
                if not passed:
                    results['filter_effectiveness'][filter_name]['blocked'] += 1
                    if outcome == 'win' or (is_simulated and mfe_r >= 1.0):
                        results['filter_effectiveness'][filter_name]['would_win'] += 1
                    elif outcome == 'loss' or (is_simulated and outcome_data.get('mae_r', 0) >= 1.0):
                        results['filter_effectiveness'][filter_name]['would_lose'] += 1
            
            # Simulated outcomes for rejected
            if outcome == 'win':
                results['rejected']['simulated_wins'] += 1
                results['rejected']['simulated_total_r'] += total_r if total_r > 0 else 1.5
            elif outcome == 'loss':
                results['rejected']['simulated_losses'] += 1
                results['rejected']['simulated_total_r'] -= 1
            elif outcome == 'expired':
                results['rejected']['simulated_expired'] += 1
            else:
                results['rejected']['simulated_pending'] += 1
            
            # Check for missed opportunities (rejected that would have won)
            if outcome == 'win' or (mfe_r >= 1.5):
                results['missed_opportunities'].append({
                    'symbol': symbol,
                    'score': score,
                    'rejection_reason': rejection_reason,
                    'mfe_r': mfe_r,
                    'total_r': total_r,
                    'timestamp': cand.get('timestamp')
                })
            
            results['rejected']['trades'].append({
                'symbol': symbol,
                'score': score,
                'outcome': outcome,
                'rejection_reason': rejection_reason,
                'mfe_r': mfe_r,
                'total_r': total_r,
                'timestamp': cand.get('timestamp')
            })
    
    return results

def generate_report(tracked_results, audit_results):
    """Generate the complete markdown report"""
    
    report = []
    report.append("=" * 80)
    report.append("# PropSignal Engine v6.0 - COMPLETE PERFORMANCE REPORT")
    report.append(f"# Report Generated: {datetime.now().strftime('%Y-%m-%d %H:%M:%S UTC')}")
    report.append(f"# Data Period: v6.0 Deployment ({V6_DEPLOYMENT}) to Present")
    report.append("=" * 80)
    report.append("")
    
    # ========================================
    # SECTION 1: EXECUTIVE SUMMARY
    # ========================================
    report.append("## 1. EXECUTIVE SUMMARY")
    report.append("-" * 40)
    
    acc = audit_results['accepted']
    rej = audit_results['rejected']
    
    # Accepted trades metrics
    acc_total = acc['wins'] + acc['losses'] + acc['expired']
    acc_completed = acc['wins'] + acc['losses']
    acc_wr = (acc['wins'] / acc_completed * 100) if acc_completed > 0 else 0
    acc_expectancy = (acc['total_r'] / acc_completed) if acc_completed > 0 else 0
    
    # Rejected trades metrics (simulated)
    rej_completed = rej['simulated_wins'] + rej['simulated_losses']
    rej_wr = (rej['simulated_wins'] / rej_completed * 100) if rej_completed > 0 else 0
    rej_expectancy = (rej['simulated_total_r'] / rej_completed) if rej_completed > 0 else 0
    
    report.append(f"Total Candidates Evaluated (v6.0): {audit_results['total_candidates']}")
    report.append(f"Acceptance Rate: {(acc['count'] / audit_results['total_candidates'] * 100):.1f}%")
    report.append("")
    report.append("### ACCEPTED TRADES (REAL)")
    report.append(f"  - Total Accepted: {acc['count']}")
    report.append(f"  - Completed: {acc_completed} (W:{acc['wins']} / L:{acc['losses']})")
    report.append(f"  - Expired: {acc['expired']}")
    report.append(f"  - Pending: {acc['pending']}")
    report.append(f"  - **Win Rate: {acc_wr:.1f}%**")
    report.append(f"  - **Total R: {acc['total_r']:.2f}R**")
    report.append(f"  - **Expectancy: {acc_expectancy:.3f}R per trade**")
    report.append("")
    report.append("### REJECTED TRADES (SIMULATED)")
    report.append(f"  - Total Rejected: {rej['count']}")
    report.append(f"  - Simulated Completed: {rej_completed} (W:{rej['simulated_wins']} / L:{rej['simulated_losses']})")
    report.append(f"  - Simulated Expired: {rej['simulated_expired']}")
    report.append(f"  - Simulated Pending: {rej['simulated_pending']}")
    report.append(f"  - **Simulated Win Rate: {rej_wr:.1f}%**")
    report.append(f"  - **Simulated Total R: {rej['simulated_total_r']:.2f}R**")
    report.append(f"  - **Simulated Expectancy: {rej_expectancy:.3f}R per trade**")
    report.append("")
    
    # ========================================
    # SECTION 2: FILTER EFFECTIVENESS
    # ========================================
    report.append("## 2. FILTER EFFECTIVENESS ANALYSIS")
    report.append("-" * 40)
    
    for filter_name, stats in sorted(audit_results['filter_effectiveness'].items(), 
                                     key=lambda x: x[1]['blocked'], reverse=True):
        if stats['blocked'] > 0:
            accuracy = ((stats['would_lose']) / stats['blocked'] * 100) if stats['blocked'] > 0 else 0
            report.append(f"### {filter_name}")
            report.append(f"  - Blocked: {stats['blocked']}")
            report.append(f"  - Would have WON: {stats['would_win']}")
            report.append(f"  - Would have LOST: {stats['would_lose']}")
            report.append(f"  - Filter Accuracy: {accuracy:.1f}% (correctly blocked losers)")
            report.append("")
    
    # ========================================
    # SECTION 3: REJECTION REASONS BREAKDOWN
    # ========================================
    report.append("## 3. REJECTION REASONS BREAKDOWN")
    report.append("-" * 40)
    
    for reason, count in sorted(rej['by_reason'].items(), key=lambda x: x[1], reverse=True):
        if reason:
            pct = (count / rej['count'] * 100) if rej['count'] > 0 else 0
            report.append(f"  - {reason}: {count} ({pct:.1f}%)")
    report.append("")
    
    # ========================================
    # SECTION 4: MISSED OPPORTUNITIES
    # ========================================
    report.append("## 4. MISSED OPPORTUNITIES (Rejected Winners)")
    report.append("-" * 40)
    
    missed = audit_results['missed_opportunities']
    if missed:
        report.append(f"Total Missed Opportunities: {len(missed)}")
        report.append("")
        
        # Group by rejection reason
        by_reason = defaultdict(list)
        for m in missed:
            by_reason[m['rejection_reason']].append(m)
        
        for reason, trades in sorted(by_reason.items(), key=lambda x: len(x[1]), reverse=True)[:5]:
            report.append(f"### {reason if reason else 'Unknown'}: {len(trades)} missed")
            for t in trades[:3]:  # Show top 3 examples
                report.append(f"    - {t['symbol']} @ {t['timestamp'][:16]} | Score: {t['score']:.1f} | MFE: {t['mfe_r']:.2f}R")
            report.append("")
    else:
        report.append("No significant missed opportunities detected.")
    report.append("")
    
    # ========================================
    # SECTION 5: ASSET COMPARISON (EURUSD vs XAUUSD)
    # ========================================
    report.append("## 5. ASSET COMPARISON: EURUSD vs XAUUSD")
    report.append("-" * 40)
    
    for asset in ['EURUSD', 'XAUUSD']:
        asset_data = tracked_results['by_asset'].get(asset, {'wins': 0, 'losses': 0, 'expired': 0, 'total_r': 0})
        total = asset_data['wins'] + asset_data['losses']
        wr = (asset_data['wins'] / total * 100) if total > 0 else 0
        exp = (asset_data['total_r'] / total) if total > 0 else 0
        
        report.append(f"### {asset}")
        report.append(f"  - Wins: {asset_data['wins']}")
        report.append(f"  - Losses: {asset_data['losses']}")
        report.append(f"  - Expired: {asset_data['expired']}")
        report.append(f"  - Win Rate: {wr:.1f}%")
        report.append(f"  - Total R: {asset_data['total_r']:.2f}R")
        report.append(f"  - Expectancy: {exp:.3f}R per trade")
        report.append("")
    
    # ========================================
    # SECTION 6: ENTRY/SL QUALITY ANALYSIS
    # ========================================
    report.append("## 6. ENTRY & STOP LOSS QUALITY ANALYSIS")
    report.append("-" * 40)
    
    sl_quality = tracked_results['sl_quality']
    if sl_quality['total_sl_hit'] > 0:
        tight_pct = (sl_quality['tight_sl_count'] / sl_quality['total_sl_hit'] * 100)
        report.append(f"Total SL Hits: {sl_quality['total_sl_hit']}")
        report.append(f"SL Hit after showing profit (MFE > 0): {sl_quality['tight_sl_count']}")
        report.append(f"**Potentially Tight SL Rate: {tight_pct:.1f}%**")
        report.append("")
        
        if tracked_results['mfe_before_sl']:
            avg_mfe = statistics.mean([t['peak_r'] for t in tracked_results['mfe_before_sl']])
            report.append(f"Average Peak R before SL Hit: {avg_mfe:.3f}R")
            report.append("")
            report.append("### Trades that reached profit before SL:")
            for t in tracked_results['mfe_before_sl'][:5]:
                report.append(f"  - {t['signal_id'][:30]}... | Peak R: {t['peak_r']:.3f}R | Time in Profit: {t['time_in_profit']:.0f}s")
    else:
        report.append("Insufficient SL hit data for analysis.")
    report.append("")
    
    # ========================================
    # SECTION 7: SAMPLE SIZE & STATISTICAL VALIDITY
    # ========================================
    report.append("## 7. STATISTICAL VALIDITY CHECK")
    report.append("-" * 40)
    
    total_completed = acc_completed
    report.append(f"Completed Trades for Analysis: {total_completed}")
    
    if total_completed < 20:
        report.append("⚠️ **WARNING: SAMPLE SIZE TOO SMALL (<20)**")
        report.append("   Results are NOT statistically significant.")
        report.append("   Continue monitoring until at least 30-50 trades complete.")
    elif total_completed < 50:
        report.append("⚠️ **CAUTION: MODERATE SAMPLE SIZE (20-49)**")
        report.append("   Results show directional trends but may have variance.")
        report.append("   Avoid major strategy changes until 50+ trades.")
    else:
        report.append("✅ **SUFFICIENT SAMPLE SIZE (50+)**")
        report.append("   Results are statistically meaningful.")
    report.append("")
    
    # ========================================
    # SECTION 8: FINAL RECOMMENDATIONS
    # ========================================
    report.append("## 8. FINAL ACTION RECOMMENDATIONS")
    report.append("-" * 40)
    
    # Decision logic based on data
    if total_completed < 10:
        report.append("### ACTION: CONTINUE MONITORING")
        report.append("- Insufficient data for any conclusions")
        report.append("- Do NOT make any filter changes")
        report.append("- Let the system run for more trades")
    else:
        # Check if accepted WR > rejected WR
        if acc_wr > rej_wr:
            report.append("### ✅ FILTERS ARE WORKING")
            report.append(f"- Accepted WR ({acc_wr:.1f}%) > Rejected WR ({rej_wr:.1f}%)")
            report.append("- Current filtering is correctly separating winners from losers")
            report.append("- Recommendation: MAINTAIN current v6.0 settings")
        else:
            report.append("### ⚠️ FILTERS MAY BE TOO AGGRESSIVE")
            report.append(f"- Rejected WR ({rej_wr:.1f}%) > Accepted WR ({acc_wr:.1f}%)")
            report.append("- Consider relaxing filters that block the most winners")
            
            # Find the most problematic filter
            for filter_name, stats in sorted(audit_results['filter_effectiveness'].items(), 
                                             key=lambda x: x[1]['would_win'], reverse=True)[:3]:
                if stats['would_win'] > 0:
                    report.append(f"   - Consider relaxing: {filter_name} (blocked {stats['would_win']} potential winners)")
        
        # Check SL quality
        if sl_quality['total_sl_hit'] > 0 and tight_pct > 50:
            report.append("")
            report.append("### ⚠️ STOP LOSS MAY BE TOO TIGHT")
            report.append(f"- {tight_pct:.0f}% of SL hits showed profit before reversal")
            report.append("- Consider:")
            report.append("   a) Widening SL by 10-20%")
            report.append("   b) Implementing trailing stop after 0.5R profit")
            report.append("   c) Moving to breakeven after 1R profit")
    
    report.append("")
    report.append("=" * 80)
    report.append("# END OF REPORT")
    report.append("=" * 80)
    
    return "\n".join(report)

def main():
    print("Loading data files...")
    
    # Load files
    tracked_data = load_json('/app/backend/data/tracked_signals.json')
    audit_data = load_json('/app/backend/data/candidate_audit.json')
    
    if not tracked_data or not audit_data:
        print("ERROR: Could not load data files")
        return
    
    print(f"Analyzing data post v6.0 deployment ({V6_DEPLOYMENT})...")
    
    # Analyze data
    tracked_results = analyze_tracked_signals(tracked_data)
    audit_results = analyze_candidate_audit(audit_data)
    
    # Generate report
    report = generate_report(tracked_results, audit_results)
    
    # Print report
    print("\n" + report)
    
    # Save report
    with open('/app/backend/data/v6_performance_report.md', 'w') as f:
        f.write(report)
    
    print(f"\nReport saved to /app/backend/data/v6_performance_report.md")

if __name__ == "__main__":
    main()
