#!/usr/bin/env python3
"""
PropSignal Engine v6.0 - COMPLETE PERFORMANCE REPORT
Full Data Analysis with ALL requested metrics
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
    if not ts_str:
        return None
    try:
        for fmt in ["%Y-%m-%dT%H:%M:%S.%f", "%Y-%m-%dT%H:%M:%S"]:
            try:
                return datetime.strptime(ts_str, fmt)
            except:
                continue
        return None
    except:
        return None

def get_score_bucket(score):
    """Categorize score into buckets"""
    if score >= 75:
        return "75+"
    elif score >= 65:
        return "65-74"
    elif score >= 60:
        return "60-64"
    else:
        return "<60"

def analyze_all_data():
    """Comprehensive analysis of all v6.0 data"""
    
    # Load data
    tracked_data = load_json('/app/backend/data/tracked_signals.json')
    audit_data = load_json('/app/backend/data/candidate_audit.json')
    
    if not tracked_data or not audit_data:
        return None
    
    results = {
        'accepted': {
            'total': 0,
            'completed': 0,
            'wins': 0,
            'losses': 0,
            'expired': 0,
            'pending': 0,
            'total_r': 0,
            'trades': [],
            'by_asset': defaultdict(lambda: {'wins': 0, 'losses': 0, 'expired': 0, 'total_r': 0, 'trades': []}),
            'by_score_bucket': defaultdict(lambda: {'wins': 0, 'losses': 0, 'total_r': 0, 'trades': []})
        },
        'rejected': {
            'total': 0,
            'completed': 0,
            'wins': 0,
            'losses': 0,
            'expired': 0,
            'pending': 0,
            'total_r': 0,
            'trades': [],
            'by_asset': defaultdict(lambda: {'wins': 0, 'losses': 0, 'expired': 0, 'total_r': 0, 'trades': []}),
            'by_score_bucket': defaultdict(lambda: {'wins': 0, 'losses': 0, 'total_r': 0, 'trades': []}),
            'by_reason': defaultdict(lambda: {'count': 0, 'wins': 0, 'losses': 0, 'total_r': 0, 'trades': []})
        },
        'filters': defaultdict(lambda: {
            'blocked': 0,
            'would_win': 0,
            'would_lose': 0,
            'would_expire': 0,
            'pending': 0,
            'total_r': 0,
            'trades': []
        }),
        'sl_analysis': {
            'total_sl_hits': 0,
            'sl_after_profit': 0,
            'peak_r_values': [],
            'time_in_profit': [],
            'trades': []
        },
        'total_candidates': 0
    }
    
    # Process candidate_audit.json (has both accepted and rejected with outcomes)
    candidates = audit_data.get('candidates', [])
    
    for cand in candidates:
        ts = parse_timestamp(cand.get('timestamp'))
        if not ts or ts < V6_DEPLOYMENT:
            continue
        
        results['total_candidates'] += 1
        
        decision = cand.get('decision', '').lower()
        score_data = cand.get('score_breakdown', {})
        score = score_data.get('total_score', 0)
        score_bucket = get_score_bucket(score)
        symbol = cand.get('symbol', 'UNKNOWN')
        rejection_reason = cand.get('rejection_reason', '')
        
        outcome_data = cand.get('outcome_data', {})
        outcome = outcome_data.get('outcome', 'pending').lower()
        is_simulated = outcome_data.get('is_simulated', False)
        total_r = outcome_data.get('total_r', 0)
        mfe_r = outcome_data.get('mfe_r', 0)
        mae_r = outcome_data.get('mae_r', 0)
        
        # Determine actual R value
        if outcome == 'win':
            r_value = total_r if total_r > 0 else 1.5
        elif outcome == 'loss':
            r_value = -1
        else:
            r_value = 0
        
        trade_info = {
            'symbol': symbol,
            'score': score,
            'score_bucket': score_bucket,
            'outcome': outcome,
            'r_value': r_value,
            'mfe_r': mfe_r,
            'mae_r': mae_r,
            'total_r': total_r,
            'rejection_reason': rejection_reason,
            'timestamp': cand.get('timestamp'),
            'is_simulated': is_simulated
        }
        
        if decision == 'accepted':
            cat = results['accepted']
            cat['total'] += 1
            cat['trades'].append(trade_info)
            
            # By score bucket
            cat['by_score_bucket'][score_bucket]['trades'].append(trade_info)
            
            # By asset
            cat['by_asset'][symbol]['trades'].append(trade_info)
            
            if outcome == 'win':
                cat['wins'] += 1
                cat['completed'] += 1
                cat['total_r'] += r_value
                cat['by_score_bucket'][score_bucket]['wins'] += 1
                cat['by_score_bucket'][score_bucket]['total_r'] += r_value
                cat['by_asset'][symbol]['wins'] += 1
                cat['by_asset'][symbol]['total_r'] += r_value
            elif outcome == 'loss':
                cat['losses'] += 1
                cat['completed'] += 1
                cat['total_r'] += r_value
                cat['by_score_bucket'][score_bucket]['losses'] += 1
                cat['by_score_bucket'][score_bucket]['total_r'] += r_value
                cat['by_asset'][symbol]['losses'] += 1
                cat['by_asset'][symbol]['total_r'] += r_value
            elif outcome == 'expired':
                cat['expired'] += 1
                cat['by_asset'][symbol]['expired'] += 1
            else:
                cat['pending'] += 1
        else:
            # Rejected
            cat = results['rejected']
            cat['total'] += 1
            cat['trades'].append(trade_info)
            
            # By rejection reason
            reason_key = rejection_reason if rejection_reason else 'unknown'
            cat['by_reason'][reason_key]['count'] += 1
            cat['by_reason'][reason_key]['trades'].append(trade_info)
            
            # By score bucket
            cat['by_score_bucket'][score_bucket]['trades'].append(trade_info)
            
            # By asset
            cat['by_asset'][symbol]['trades'].append(trade_info)
            
            if outcome == 'win':
                cat['wins'] += 1
                cat['completed'] += 1
                cat['total_r'] += r_value
                cat['by_score_bucket'][score_bucket]['wins'] += 1
                cat['by_score_bucket'][score_bucket]['total_r'] += r_value
                cat['by_asset'][symbol]['wins'] += 1
                cat['by_asset'][symbol]['total_r'] += r_value
                cat['by_reason'][reason_key]['wins'] += 1
                cat['by_reason'][reason_key]['total_r'] += r_value
            elif outcome == 'loss':
                cat['losses'] += 1
                cat['completed'] += 1
                cat['total_r'] += r_value
                cat['by_score_bucket'][score_bucket]['losses'] += 1
                cat['by_score_bucket'][score_bucket]['total_r'] += r_value
                cat['by_asset'][symbol]['losses'] += 1
                cat['by_asset'][symbol]['total_r'] += r_value
                cat['by_reason'][reason_key]['losses'] += 1
                cat['by_reason'][reason_key]['total_r'] -= 1
            elif outcome == 'expired':
                cat['expired'] += 1
                cat['by_asset'][symbol]['expired'] += 1
            else:
                cat['pending'] += 1
            
            # Track filter effectiveness
            filter_flags = cand.get('filter_flags', {})
            for filter_name, passed in filter_flags.items():
                if not passed:  # This filter blocked the trade
                    f = results['filters'][filter_name]
                    f['blocked'] += 1
                    f['trades'].append(trade_info)
                    
                    if outcome == 'win':
                        f['would_win'] += 1
                        f['total_r'] += r_value
                    elif outcome == 'loss':
                        f['would_lose'] += 1
                        f['total_r'] -= 1
                    elif outcome == 'expired':
                        f['would_expire'] += 1
                    else:
                        f['pending'] += 1
    
    # Process tracked_signals.json for SL quality analysis
    completed_signals = tracked_data.get('completed', [])
    
    for sig in completed_signals:
        ts = parse_timestamp(sig.get('timestamp'))
        if not ts or ts < V6_DEPLOYMENT:
            continue
        
        status = sig.get('status', '').lower()
        
        if status == 'sl_hit':
            results['sl_analysis']['total_sl_hits'] += 1
            
            mfe = sig.get('max_favorable_excursion', 0)
            moved_favorable = sig.get('moved_favorable_before_fail', False)
            peak_r = sig.get('peak_r_before_reversal', 0)
            time_in_profit = sig.get('time_in_profit_seconds', 0)
            
            if moved_favorable or peak_r > 0:
                results['sl_analysis']['sl_after_profit'] += 1
                results['sl_analysis']['peak_r_values'].append(peak_r)
                results['sl_analysis']['time_in_profit'].append(time_in_profit)
                results['sl_analysis']['trades'].append({
                    'signal_id': sig.get('signal_id'),
                    'asset': sig.get('asset'),
                    'peak_r': peak_r,
                    'time_in_profit': time_in_profit,
                    'mfe': mfe
                })
    
    return results

def generate_report(data):
    """Generate the complete formatted report"""
    
    report = []
    
    report.append("=" * 80)
    report.append("  PropSignal Engine v6.0 - COMPLETE PERFORMANCE REPORT")
    report.append(f"  Generated: {datetime.now().strftime('%Y-%m-%d %H:%M:%S UTC')}")
    report.append(f"  Data Period: {V6_DEPLOYMENT} → Present")
    report.append("=" * 80)
    report.append("")
    
    acc = data['accepted']
    rej = data['rejected']
    
    # Calculate metrics
    acc_wr = (acc['wins'] / acc['completed'] * 100) if acc['completed'] > 0 else 0
    acc_exp = (acc['total_r'] / acc['completed']) if acc['completed'] > 0 else 0
    
    rej_wr = (rej['wins'] / rej['completed'] * 100) if rej['completed'] > 0 else 0
    rej_exp = (rej['total_r'] / rej['completed']) if rej['completed'] > 0 else 0
    
    acceptance_rate = (acc['total'] / data['total_candidates'] * 100) if data['total_candidates'] > 0 else 0
    
    # ========================================
    # SECTION 1: EXECUTIVE SUMMARY
    # ========================================
    report.append("┌" + "─" * 78 + "┐")
    report.append("│" + " 1. EXECUTIVE SUMMARY".ljust(78) + "│")
    report.append("└" + "─" * 78 + "┘")
    report.append("")
    
    report.append(f"Total Candidates Evaluated (v6.0): {data['total_candidates']}")
    report.append(f"Acceptance Rate: {acceptance_rate:.2f}%")
    report.append("")
    
    report.append("┌────────────────────────────┬─────────────────────┬─────────────────────┐")
    report.append("│ METRIC                     │ ACCEPTED (REAL)     │ REJECTED (SIMUL.)   │")
    report.append("├────────────────────────────┼─────────────────────┼─────────────────────┤")
    acc_completed_str = f"{acc['completed']} ({acc['wins']}W/{acc['losses']}L)"
    rej_completed_str = f"{rej['completed']} ({rej['wins']}W/{rej['losses']}L)"
    report.append(f"│ Total Trades               │ {str(acc['total']).center(19)} │ {str(rej['total']).center(19)} │")
    report.append(f"│ Completed (W/L)            │ {acc_completed_str.center(19)} │ {rej_completed_str.center(19)} │")
    report.append(f"│ Expired                    │ {str(acc['expired']).center(19)} │ {str(rej['expired']).center(19)} │")
    report.append(f"│ Pending                    │ {str(acc['pending']).center(19)} │ {str(rej['pending']).center(19)} │")
    report.append("├────────────────────────────┼─────────────────────┼─────────────────────┤")
    acc_wr_str = f"{acc_wr:.1f}%"
    rej_wr_str = f"{rej_wr:.1f}%"
    acc_r_str = f"{acc['total_r']:.2f}R"
    rej_r_str = f"{rej['total_r']:.2f}R"
    acc_exp_str = f"{acc_exp:.3f}R"
    rej_exp_str = f"{rej_exp:.3f}R"
    report.append(f"│ WIN RATE                   │ {acc_wr_str.center(19)} │ {rej_wr_str.center(19)} │")
    report.append(f"│ TOTAL R                    │ {acc_r_str.center(19)} │ {rej_r_str.center(19)} │")
    report.append(f"│ EXPECTANCY                 │ {acc_exp_str.center(19)} │ {rej_exp_str.center(19)} │")
    report.append("└────────────────────────────┴─────────────────────┴─────────────────────┘")
    report.append("")
    
    # ========================================
    # SECTION 2: FILTER EFFECTIVENESS
    # ========================================
    report.append("┌" + "─" * 78 + "┐")
    report.append("│" + " 2. FILTER EFFECTIVENESS (CRITICAL)".ljust(78) + "│")
    report.append("└" + "─" * 78 + "┘")
    report.append("")
    
    # Map filter names to readable names
    filter_name_map = {
        'score_passed': 'low_confidence',
        'mtf_passed': 'weak_mtf',
        'duplicate_blocked': 'duplicate',
        'news_blocked': 'news_blocked',
        'fta_passed': 'fta_blocked',
        'session_passed': 'session_blocked',
        'rr_passed': 'rr_blocked',
        'spread_passed': 'spread_blocked',
        'daily_limit_passed': 'daily_limit_blocked'
    }
    
    report.append("┌──────────────────────┬─────────┬──────────┬───────────┬──────────┬────────────┬─────────┐")
    report.append("│ FILTER               │ BLOCKED │ WOULD    │ WOULD     │ WIN RATE │ EXPECTANCY │ VERDICT │")
    report.append("│                      │         │ WIN      │ LOSE      │ (if took)│ (if took)  │         │")
    report.append("├──────────────────────┼─────────┼──────────┼───────────┼──────────┼────────────┼─────────┤")
    
    for filter_key, stats in sorted(data['filters'].items(), key=lambda x: x[1]['blocked'], reverse=True):
        if stats['blocked'] == 0:
            continue
        
        display_name = filter_name_map.get(filter_key, filter_key)
        completed_blocked = stats['would_win'] + stats['would_lose']
        
        if completed_blocked > 0:
            blocked_wr = (stats['would_win'] / completed_blocked * 100)
            blocked_exp = stats['total_r'] / completed_blocked
        else:
            blocked_wr = 0
            blocked_exp = 0
        
        # Verdict: GOOD if filter blocks more losers than winners, BAD otherwise
        if stats['would_lose'] > stats['would_win']:
            verdict = "✅ GOOD"
        elif stats['would_win'] > stats['would_lose']:
            verdict = "❌ BAD"
        else:
            verdict = "⚠️ NEUTRAL"
        
        report.append(f"│ {display_name[:20].ljust(20)} │ {str(stats['blocked']).center(7)} │ {str(stats['would_win']).center(8)} │ {str(stats['would_lose']).center(9)} │ {f'{blocked_wr:.1f}%'.center(8)} │ {f'{blocked_exp:.2f}R'.center(10)} │ {verdict.ljust(7)} │")
    
    report.append("└──────────────────────┴─────────┴──────────┴───────────┴──────────┴────────────┴─────────┘")
    report.append("")
    
    # ========================================
    # SECTION 3: REJECTION REASONS BREAKDOWN
    # ========================================
    report.append("┌" + "─" * 78 + "┐")
    report.append("│" + " 3. REJECTION REASONS BREAKDOWN".ljust(78) + "│")
    report.append("└" + "─" * 78 + "┘")
    report.append("")
    
    report.append("┌──────────────────────────────────┬─────────┬─────────┬───────┬────────┬────────────┐")
    report.append("│ REASON                           │ COUNT   │ % TOTAL │ WINS  │ LOSSES │ WIN RATE   │")
    report.append("├──────────────────────────────────┼─────────┼─────────┼───────┼────────┼────────────┤")
    
    for reason, stats in sorted(rej['by_reason'].items(), key=lambda x: x[1]['count'], reverse=True):
        pct = (stats['count'] / rej['total'] * 100) if rej['total'] > 0 else 0
        completed = stats['wins'] + stats['losses']
        wr = (stats['wins'] / completed * 100) if completed > 0 else 0
        
        report.append(f"│ {reason[:32].ljust(32)} │ {str(stats['count']).center(7)} │ {f'{pct:.1f}%'.center(7)} │ {str(stats['wins']).center(5)} │ {str(stats['losses']).center(6)} │ {f'{wr:.1f}%'.center(10)} │")
    
    report.append("└──────────────────────────────────┴─────────┴─────────┴───────┴────────┴────────────┘")
    report.append("")
    
    # ========================================
    # SECTION 4: MISSED OPPORTUNITIES
    # ========================================
    report.append("┌" + "─" * 78 + "┐")
    report.append("│" + " 4. MISSED OPPORTUNITIES ANALYSIS".ljust(78) + "│")
    report.append("└" + "─" * 78 + "┘")
    report.append("")
    
    # Find rejected trades that would have won
    missed_wins = [t for t in rej['trades'] if t['outcome'] == 'win']
    missed_losses = [t for t in rej['trades'] if t['outcome'] == 'loss']
    
    report.append(f"Rejected trades that would have HIT TP: {len(missed_wins)}")
    report.append(f"Rejected trades that would have HIT SL: {len(missed_losses)}")
    report.append(f"Missed Win Rate: {rej_wr:.1f}%")
    report.append(f"Missed Expectancy: {rej_exp:.3f}R per trade")
    report.append("")
    
    if missed_wins:
        report.append("Top Missed Winners (by R gained):")
        sorted_missed = sorted(missed_wins, key=lambda x: x['total_r'], reverse=True)[:5]
        for t in sorted_missed:
            report.append(f"  • {t['symbol']} @ Score {t['score']:.1f} | Reason: {t['rejection_reason']} | R: +{t['total_r']:.2f}")
    else:
        report.append("✅ NO MISSED WINNING TRADES - Filters are working correctly!")
    report.append("")
    
    # ========================================
    # SECTION 5: SCORE BUCKET ANALYSIS
    # ========================================
    report.append("┌" + "─" * 78 + "┐")
    report.append("│" + " 5. SCORE BUCKET ANALYSIS".ljust(78) + "│")
    report.append("└" + "─" * 78 + "┘")
    report.append("")
    
    buckets = ["75+", "65-74", "60-64", "<60"]
    
    # ACCEPTED
    report.append("ACCEPTED TRADES BY SCORE:")
    report.append("┌────────────┬─────────┬───────┬────────┬──────────┬────────────┐")
    report.append("│ BUCKET     │ TRADES  │ WINS  │ LOSSES │ WIN RATE │ EXPECTANCY │")
    report.append("├────────────┼─────────┼───────┼────────┼──────────┼────────────┤")
    
    for bucket in buckets:
        b_data = acc['by_score_bucket'].get(bucket, {'wins': 0, 'losses': 0, 'total_r': 0, 'trades': []})
        total_trades = len(b_data['trades'])
        completed = b_data['wins'] + b_data['losses']
        wr = (b_data['wins'] / completed * 100) if completed > 0 else 0
        exp = (b_data['total_r'] / completed) if completed > 0 else 0
        
        report.append(f"│ {bucket.center(10)} │ {str(total_trades).center(7)} │ {str(b_data['wins']).center(5)} │ {str(b_data['losses']).center(6)} │ {f'{wr:.1f}%'.center(8)} │ {f'{exp:.2f}R'.center(10)} │")
    
    report.append("└────────────┴─────────┴───────┴────────┴──────────┴────────────┘")
    report.append("")
    
    # REJECTED
    report.append("REJECTED TRADES BY SCORE (Simulated):")
    report.append("┌────────────┬─────────┬───────┬────────┬──────────┬────────────┐")
    report.append("│ BUCKET     │ TRADES  │ WINS  │ LOSSES │ WIN RATE │ EXPECTANCY │")
    report.append("├────────────┼─────────┼───────┼────────┼──────────┼────────────┤")
    
    for bucket in buckets:
        b_data = rej['by_score_bucket'].get(bucket, {'wins': 0, 'losses': 0, 'total_r': 0, 'trades': []})
        total_trades = len(b_data['trades'])
        completed = b_data['wins'] + b_data['losses']
        wr = (b_data['wins'] / completed * 100) if completed > 0 else 0
        exp = (b_data['total_r'] / completed) if completed > 0 else 0
        
        report.append(f"│ {bucket.center(10)} │ {str(total_trades).center(7)} │ {str(b_data['wins']).center(5)} │ {str(b_data['losses']).center(6)} │ {f'{wr:.1f}%'.center(8)} │ {f'{exp:.2f}R'.center(10)} │")
    
    report.append("└────────────┴─────────┴───────┴────────┴──────────┴────────────┘")
    report.append("")
    
    # ========================================
    # SECTION 6: ASSET ANALYSIS
    # ========================================
    report.append("┌" + "─" * 78 + "┐")
    report.append("│" + " 6. ASSET ANALYSIS: EURUSD vs XAUUSD".ljust(78) + "│")
    report.append("└" + "─" * 78 + "┘")
    report.append("")
    
    report.append("ACCEPTED TRADES:")
    report.append("┌──────────┬─────────┬───────┬────────┬──────────┬──────────┬────────────┐")
    report.append("│ ASSET    │ TRADES  │ WINS  │ LOSSES │ EXPIRED  │ WIN RATE │ EXPECTANCY │")
    report.append("├──────────┼─────────┼───────┼────────┼──────────┼──────────┼────────────┤")
    
    for asset in ['EURUSD', 'XAUUSD']:
        a_data = acc['by_asset'].get(asset, {'wins': 0, 'losses': 0, 'expired': 0, 'total_r': 0, 'trades': []})
        total_trades = len(a_data['trades'])
        completed = a_data['wins'] + a_data['losses']
        wr = (a_data['wins'] / completed * 100) if completed > 0 else 0
        exp = (a_data['total_r'] / completed) if completed > 0 else 0
        
        report.append(f"│ {asset.center(8)} │ {str(total_trades).center(7)} │ {str(a_data['wins']).center(5)} │ {str(a_data['losses']).center(6)} │ {str(a_data['expired']).center(8)} │ {f'{wr:.1f}%'.center(8)} │ {f'{exp:.2f}R'.center(10)} │")
    
    report.append("└──────────┴─────────┴───────┴────────┴──────────┴──────────┴────────────┘")
    report.append("")
    
    report.append("REJECTED TRADES (Simulated):")
    report.append("┌──────────┬─────────┬───────┬────────┬──────────┬──────────┬────────────┐")
    report.append("│ ASSET    │ TRADES  │ WINS  │ LOSSES │ EXPIRED  │ WIN RATE │ EXPECTANCY │")
    report.append("├──────────┼─────────┼───────┼────────┼──────────┼──────────┼────────────┤")
    
    for asset in ['EURUSD', 'XAUUSD']:
        a_data = rej['by_asset'].get(asset, {'wins': 0, 'losses': 0, 'expired': 0, 'total_r': 0, 'trades': []})
        total_trades = len(a_data['trades'])
        completed = a_data['wins'] + a_data['losses']
        wr = (a_data['wins'] / completed * 100) if completed > 0 else 0
        exp = (a_data['total_r'] / completed) if completed > 0 else 0
        
        report.append(f"│ {asset.center(8)} │ {str(total_trades).center(7)} │ {str(a_data['wins']).center(5)} │ {str(a_data['losses']).center(6)} │ {str(a_data['expired']).center(8)} │ {f'{wr:.1f}%'.center(8)} │ {f'{exp:.2f}R'.center(10)} │")
    
    report.append("└──────────┴─────────┴───────┴────────┴──────────┴──────────┴────────────┘")
    report.append("")
    
    # ========================================
    # SECTION 7: ENTRY & SL QUALITY
    # ========================================
    report.append("┌" + "─" * 78 + "┐")
    report.append("│" + " 7. ENTRY & STOP LOSS QUALITY".ljust(78) + "│")
    report.append("└" + "─" * 78 + "┘")
    report.append("")
    
    sl = data['sl_analysis']
    
    if sl['total_sl_hits'] > 0:
        sl_after_profit_pct = (sl['sl_after_profit'] / sl['total_sl_hits'] * 100)
        avg_peak_r = statistics.mean(sl['peak_r_values']) if sl['peak_r_values'] else 0
        avg_time_profit = statistics.mean(sl['time_in_profit']) if sl['time_in_profit'] else 0
        
        report.append(f"Total SL Hits (v6.0):                    {sl['total_sl_hits']}")
        report.append(f"SL Hits that went in profit first:       {sl['sl_after_profit']} ({sl_after_profit_pct:.1f}%)")
        report.append(f"Average Peak R before SL:                {avg_peak_r:.3f}R")
        report.append(f"Average Time in Profit before SL:        {avg_time_profit:.0f} seconds ({avg_time_profit/60:.1f} minutes)")
        report.append("")
        
        if sl_after_profit_pct > 50:
            report.append("⚠️  WARNING: STOP LOSS MAY BE TOO TIGHT")
            report.append(f"    {sl_after_profit_pct:.0f}% of SL hits showed profit before reversal")
        else:
            report.append("✅ STOP LOSS QUALITY: ACCEPTABLE")
            report.append(f"    Only {sl_after_profit_pct:.0f}% of SL hits showed profit before reversal")
        
        report.append("")
        
        if sl['trades']:
            report.append("SL Hit Details (showing profit before reversal):")
            for t in sl['trades'][:5]:
                report.append(f"  • {t['signal_id'][:35]}...")
                report.append(f"    Peak R: {t['peak_r']:.3f}R | Time in Profit: {t['time_in_profit']:.0f}s")
    else:
        report.append("No SL hits recorded for v6.0 period.")
    
    report.append("")
    
    # ========================================
    # SECTION 8: FINAL DIAGNOSTIC
    # ========================================
    report.append("┌" + "─" * 78 + "┐")
    report.append("│" + " 8. FINAL DIAGNOSTIC".ljust(78) + "│")
    report.append("└" + "─" * 78 + "┘")
    report.append("")
    
    total_completed = acc['completed']
    
    # Is system profitable?
    report.append("Q: Is the system PROFITABLE?")
    if acc['total_r'] > 0:
        report.append(f"   ✅ YES - Total R: +{acc['total_r']:.2f}R with {acc_wr:.1f}% win rate")
    else:
        report.append(f"   ❌ NO - Total R: {acc['total_r']:.2f}R with {acc_wr:.1f}% win rate")
    report.append("")
    
    # Are we filtering profitable trades?
    report.append("Q: Are we FILTERING PROFITABLE TRADES?")
    if rej['wins'] > 0:
        report.append(f"   ⚠️  YES - {rej['wins']} rejected trades would have won ({rej_wr:.1f}% WR)")
        if rej_wr > acc_wr:
            report.append(f"   ❌ CRITICAL: Rejected WR ({rej_wr:.1f}%) > Accepted WR ({acc_wr:.1f}%)")
        else:
            report.append(f"   ✅ BUT: Accepted WR ({acc_wr:.1f}%) > Rejected WR ({rej_wr:.1f}%)")
    else:
        report.append(f"   ✅ NO - All {rej['completed']} simulated rejected trades would have LOST")
    report.append("")
    
    # Best score bucket
    report.append("Q: What is the BEST SCORE BUCKET?")
    best_bucket = None
    best_exp = -999
    for bucket in buckets:
        b_data = acc['by_score_bucket'].get(bucket, {'wins': 0, 'losses': 0, 'total_r': 0, 'trades': []})
        completed = b_data['wins'] + b_data['losses']
        if completed > 0:
            exp = b_data['total_r'] / completed
            if exp > best_exp:
                best_exp = exp
                best_bucket = bucket
    
    if best_bucket:
        report.append(f"   ✅ {best_bucket} with {best_exp:.2f}R expectancy")
    else:
        report.append("   ⚠️  Insufficient data")
    report.append("")
    
    # Worst issue detected
    report.append("Q: What is the WORST ISSUE DETECTED?")
    
    issues = []
    
    # Check if filtering winners
    if rej['wins'] > 0 and rej_wr > acc_wr:
        issues.append(f"Filters blocking winners (Rejected WR {rej_wr:.1f}% > Accepted WR {acc_wr:.1f}%)")
    
    # Check SL quality
    if sl['total_sl_hits'] > 0 and sl_after_profit_pct > 50:
        issues.append(f"Stop Loss too tight ({sl_after_profit_pct:.0f}% went profit first)")
    
    # Check acceptance rate
    if acceptance_rate < 1:
        issues.append(f"Acceptance rate very low ({acceptance_rate:.2f}%)")
    
    # Check sample size
    if total_completed < 30:
        issues.append(f"Sample size too small ({total_completed} trades)")
    
    if issues:
        for i, issue in enumerate(issues, 1):
            report.append(f"   {i}. ⚠️  {issue}")
    else:
        report.append("   ✅ No critical issues detected")
    
    report.append("")
    
    # ========================================
    # SECTION 9: ACTIONABLE RECOMMENDATIONS
    # ========================================
    report.append("┌" + "─" * 78 + "┐")
    report.append("│" + " 9. ACTIONABLE RECOMMENDATIONS".ljust(78) + "│")
    report.append("└" + "─" * 78 + "┘")
    report.append("")
    
    if total_completed < 30:
        report.append("╔══════════════════════════════════════════════════════════════════════════════╗")
        report.append("║  ⚠️  NOT STATISTICALLY VALID – CONTINUE DATA COLLECTION                      ║")
        report.append("║                                                                              ║")
        report.append(f"║  Current Sample Size: {total_completed} trades                                                 ║")
        report.append("║  Required for Statistical Validity: 30-50 trades                             ║")
        report.append("║                                                                              ║")
        report.append("║  ACTION: DO NOT MAKE ANY CHANGES                                             ║")
        report.append("║  REASON: Results may be due to variance/noise                                ║")
        report.append("╚══════════════════════════════════════════════════════════════════════════════╝")
    else:
        report.append("STATISTICALLY VALID SAMPLE - RECOMMENDATIONS:")
        report.append("")
        
        # What to KEEP
        report.append("✅ KEEP (Working Well):")
        if acc_wr > rej_wr:
            report.append("   • Current filter configuration (correctly separating winners from losers)")
        if acc['total_r'] > 0:
            report.append("   • Current acceptance threshold")
        
        # What to CHANGE
        report.append("")
        report.append("⚠️  CONSIDER CHANGING:")
        
        # Find bad filters
        for filter_key, stats in data['filters'].items():
            completed_blocked = stats['would_win'] + stats['would_lose']
            if completed_blocked > 0:
                blocked_wr = (stats['would_win'] / completed_blocked * 100)
                if blocked_wr > 50:  # Filter blocks more winners than losers
                    display_name = filter_name_map.get(filter_key, filter_key)
                    report.append(f"   • Relax {display_name} filter (blocked {stats['would_win']} winners)")
        
        if sl['total_sl_hits'] > 0 and sl_after_profit_pct > 50:
            report.append(f"   • Widen Stop Loss by 10-20% (currently {sl_after_profit_pct:.0f}% go profit first)")
        
        # What to MONITOR
        report.append("")
        report.append("👁️  MONITOR:")
        report.append("   • Win rate stability as sample size grows")
        report.append("   • SL quality metrics")
        report.append("   • Filter effectiveness over time")
    
    report.append("")
    report.append("=" * 80)
    report.append("  END OF REPORT")
    report.append("=" * 80)
    
    return "\n".join(report)

def main():
    print("Loading and analyzing v6.0 data...")
    
    data = analyze_all_data()
    
    if not data:
        print("ERROR: Could not load data")
        return
    
    report = generate_report(data)
    
    print("\n" + report)
    
    # Save report
    with open('/app/backend/data/v6_complete_report.md', 'w') as f:
        f.write(report)
    
    print(f"\n\nReport saved to /app/backend/data/v6_complete_report.md")

if __name__ == "__main__":
    main()
