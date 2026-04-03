#!/usr/bin/env python3
"""
PropSignal Engine v6.0 - FULL DIAGNOSTIC & OPTIMIZATION REPORT
Deep Performance + Filter + Execution Analysis
"""

import json
from datetime import datetime, timedelta
from collections import defaultdict
import statistics

V6_DEPLOYMENT = datetime(2026, 3, 25, 11, 50, 0)

def load_json(filepath):
    try:
        with open(filepath, 'r') as f:
            return json.load(f)
    except Exception as e:
        print(f"Error loading {filepath}: {e}")
        return None

def parse_ts(ts_str):
    if not ts_str:
        return None
    try:
        return datetime.strptime(ts_str[:19], '%Y-%m-%dT%H:%M:%S')
    except:
        return None

def get_session(ts):
    if not ts:
        return "Unknown"
    hour = ts.hour
    if 0 <= hour < 7:
        return "Asia"
    elif 7 <= hour < 12:
        return "London"
    elif 12 <= hour < 16:
        return "Overlap"
    else:
        return "New York"

def analyze():
    # Load data
    tracked = load_json('/app/backend/data/tracked_signals.json')
    audit = load_json('/app/backend/data/candidate_audit.json')
    
    if not tracked or not audit:
        print("ERROR: Could not load data files")
        return
    
    # Extract v6.0 completed trades
    completed = tracked.get('completed', [])
    v6_trades = []
    
    for sig in completed:
        ts = parse_ts(sig.get('timestamp'))
        if ts and ts >= V6_DEPLOYMENT:
            v6_trades.append(sig)
    
    # Extract audit data for filter analysis
    candidates = audit.get('candidates', [])
    v6_accepted = []
    v6_rejected = []
    
    for cand in candidates:
        ts = parse_ts(cand.get('timestamp'))
        if ts and ts >= V6_DEPLOYMENT:
            if cand.get('decision') == 'accepted':
                v6_accepted.append(cand)
            else:
                v6_rejected.append(cand)
    
    # ================================================================
    # SECTION 1: CORE PERFORMANCE
    # ================================================================
    wins = [t for t in v6_trades if t.get('final_outcome') == 'win']
    losses = [t for t in v6_trades if t.get('final_outcome') == 'loss']
    
    total = len(v6_trades)
    win_count = len(wins)
    loss_count = len(losses)
    win_rate = (win_count / total * 100) if total > 0 else 0
    
    # Calculate R values
    r_values = []
    for t in v6_trades:
        entry = t.get('entry_price', 0)
        sl = t.get('stop_loss', 0)
        tp = t.get('take_profit_1', 0)
        risk = abs(entry - sl)
        
        if t.get('final_outcome') == 'win':
            reward = abs(tp - entry)
            r = reward / risk if risk > 0 else 1.5
            r_values.append(r)
        elif t.get('final_outcome') == 'loss':
            r_values.append(-1.0)
        else:
            r_values.append(0)
    
    total_r = sum(r_values)
    avg_r = total_r / total if total > 0 else 0
    expectancy = avg_r
    
    win_rs = [r for r in r_values if r > 0]
    loss_rs = [abs(r) for r in r_values if r < 0]
    avg_win = statistics.mean(win_rs) if win_rs else 0
    avg_loss = statistics.mean(loss_rs) if loss_rs else 1
    
    profit_factor = (sum(win_rs) / sum(loss_rs)) if loss_rs and sum(loss_rs) > 0 else float('inf')
    
    # Max drawdown calculation
    running_r = 0
    peak_r = 0
    max_dd_r = 0
    for r in r_values:
        running_r += r
        if running_r > peak_r:
            peak_r = running_r
        dd = peak_r - running_r
        if dd > max_dd_r:
            max_dd_r = dd
    
    max_dd_pct = (max_dd_r / peak_r * 100) if peak_r > 0 else 0
    
    # Breakdown by asset
    by_asset = defaultdict(lambda: {'wins': 0, 'losses': 0, 'r': 0, 'trades': []})
    for i, t in enumerate(v6_trades):
        asset = t.get('asset', 'UNKNOWN')
        by_asset[asset]['trades'].append(t)
        by_asset[asset]['r'] += r_values[i]
        if t.get('final_outcome') == 'win':
            by_asset[asset]['wins'] += 1
        elif t.get('final_outcome') == 'loss':
            by_asset[asset]['losses'] += 1
    
    # Breakdown by session
    by_session = defaultdict(lambda: {'wins': 0, 'losses': 0, 'r': 0, 'trades': []})
    for i, t in enumerate(v6_trades):
        ts = parse_ts(t.get('timestamp'))
        session = get_session(ts)
        by_session[session]['trades'].append(t)
        by_session[session]['r'] += r_values[i]
        if t.get('final_outcome') == 'win':
            by_session[session]['wins'] += 1
        elif t.get('final_outcome') == 'loss':
            by_session[session]['losses'] += 1
    
    # Breakdown by direction
    by_direction = defaultdict(lambda: {'wins': 0, 'losses': 0, 'r': 0, 'trades': []})
    for i, t in enumerate(v6_trades):
        direction = t.get('direction', 'UNKNOWN')
        by_direction[direction]['trades'].append(t)
        by_direction[direction]['r'] += r_values[i]
        if t.get('final_outcome') == 'win':
            by_direction[direction]['wins'] += 1
        elif t.get('final_outcome') == 'loss':
            by_direction[direction]['losses'] += 1
    
    # ================================================================
    # SECTION 2: SCORE ANALYSIS
    # ================================================================
    score_buckets = {
        '60-64': {'trades': [], 'wins': 0, 'losses': 0, 'r': 0},
        '65-69': {'trades': [], 'wins': 0, 'losses': 0, 'r': 0},
        '70-74': {'trades': [], 'wins': 0, 'losses': 0, 'r': 0},
        '75+': {'trades': [], 'wins': 0, 'losses': 0, 'r': 0}
    }
    
    for i, t in enumerate(v6_trades):
        score = t.get('confidence_score', 0)
        if score >= 75:
            bucket = '75+'
        elif score >= 70:
            bucket = '70-74'
        elif score >= 65:
            bucket = '65-69'
        else:
            bucket = '60-64'
        
        score_buckets[bucket]['trades'].append(t)
        score_buckets[bucket]['r'] += r_values[i]
        if t.get('final_outcome') == 'win':
            score_buckets[bucket]['wins'] += 1
        elif t.get('final_outcome') == 'loss':
            score_buckets[bucket]['losses'] += 1
    
    # ================================================================
    # SECTION 3: FILTER EFFECTIVENESS
    # ================================================================
    filters = defaultdict(lambda: {'blocked': 0, 'would_win': 0, 'would_lose': 0, 'r': 0})
    
    rejection_reasons = defaultdict(lambda: {'count': 0, 'wins': 0, 'losses': 0, 'r': 0})
    
    for cand in v6_rejected:
        reason = cand.get('rejection_reason', 'unknown')
        outcome_data = cand.get('outcome_data', {})
        outcome = outcome_data.get('outcome', 'pending')
        mfe_r = outcome_data.get('mfe_r', 0)
        
        rejection_reasons[reason]['count'] += 1
        
        if outcome == 'win':
            rejection_reasons[reason]['wins'] += 1
            rejection_reasons[reason]['r'] += 1.5
            filters[reason]['would_win'] += 1
            filters[reason]['r'] += 1.5
        elif outcome == 'loss':
            rejection_reasons[reason]['losses'] += 1
            rejection_reasons[reason]['r'] -= 1
            filters[reason]['would_lose'] += 1
            filters[reason]['r'] -= 1
        
        filters[reason]['blocked'] += 1
    
    # ================================================================
    # SECTION 4: REJECTED vs ACCEPTED
    # ================================================================
    acc_wins = len([c for c in v6_accepted if c.get('outcome_data', {}).get('outcome') == 'win'])
    acc_losses = len([c for c in v6_accepted if c.get('outcome_data', {}).get('outcome') == 'loss'])
    acc_total = acc_wins + acc_losses
    acc_wr = (acc_wins / acc_total * 100) if acc_total > 0 else 0
    acc_r = acc_wins * 1.5 - acc_losses
    acc_exp = acc_r / acc_total if acc_total > 0 else 0
    
    rej_wins = len([c for c in v6_rejected if c.get('outcome_data', {}).get('outcome') == 'win'])
    rej_losses = len([c for c in v6_rejected if c.get('outcome_data', {}).get('outcome') == 'loss'])
    rej_total = rej_wins + rej_losses
    rej_wr = (rej_wins / rej_total * 100) if rej_total > 0 else 0
    rej_r = rej_wins * 1.5 - rej_losses
    rej_exp = rej_r / rej_total if rej_total > 0 else 0
    
    # ================================================================
    # SECTION 5: ENTRY QUALITY
    # ================================================================
    mfe_values = []
    mae_values = []
    profit_before_sl = 0
    peak_r_before_sl = []
    
    for t in v6_trades:
        entry = t.get('entry_price', 0)
        sl = t.get('stop_loss', 0)
        risk = abs(entry - sl)
        
        mfe = t.get('max_favorable_excursion', 0)
        mae = t.get('max_adverse_excursion', 0)
        
        mfe_r = mfe / risk if risk > 0 else 0
        mae_r = mae / risk if risk > 0 else 0
        
        mfe_values.append(mfe_r)
        mae_values.append(mae_r)
        
        if t.get('final_outcome') == 'loss':
            if t.get('moved_favorable_before_fail') or mfe_r > 0:
                profit_before_sl += 1
                peak_r_before_sl.append(t.get('peak_r_before_reversal', mfe_r))
    
    avg_mfe = statistics.mean(mfe_values) if mfe_values else 0
    avg_mae = statistics.mean(mae_values) if mae_values else 0
    pct_profit_before_sl = (profit_before_sl / loss_count * 100) if loss_count > 0 else 0
    avg_peak_before_sl = statistics.mean(peak_r_before_sl) if peak_r_before_sl else 0
    
    # ================================================================
    # SECTION 6: SL/TP QUALITY
    # ================================================================
    tp_clean = 0
    tp_after_dd = 0
    
    for t in wins:
        mae = t.get('max_adverse_excursion', 0)
        entry = t.get('entry_price', 0)
        sl = t.get('stop_loss', 0)
        risk = abs(entry - sl)
        mae_r = mae / risk if risk > 0 else 0
        
        if mae_r < 0.3:
            tp_clean += 1
        else:
            tp_after_dd += 1
    
    pct_tp_clean = (tp_clean / win_count * 100) if win_count > 0 else 0
    
    # Avg RR achieved
    achieved_rr = []
    for t in wins:
        entry = t.get('entry_price', 0)
        sl = t.get('stop_loss', 0)
        tp = t.get('take_profit_1', 0)
        risk = abs(entry - sl)
        reward = abs(tp - entry)
        rr = reward / risk if risk > 0 else 1.5
        achieved_rr.append(rr)
    
    avg_achieved_rr = statistics.mean(achieved_rr) if achieved_rr else 0
    
    # ================================================================
    # SECTION 7: TRADE MANAGEMENT SIMULATION
    # ================================================================
    # Simulate BE at 0.5R
    be_05r_wins = 0
    be_05r_losses = 0
    be_05r_be = 0
    
    for t in v6_trades:
        mfe_r = mfe_values[v6_trades.index(t)]
        outcome = t.get('final_outcome')
        
        if mfe_r >= 0.5:
            if outcome == 'win':
                be_05r_wins += 1
            else:
                be_05r_be += 1  # Would have been BE instead of loss
        else:
            if outcome == 'win':
                be_05r_wins += 1
            else:
                be_05r_losses += 1
    
    # Simulate BE at 1R
    be_1r_wins = 0
    be_1r_losses = 0
    be_1r_be = 0
    
    for t in v6_trades:
        mfe_r = mfe_values[v6_trades.index(t)]
        outcome = t.get('final_outcome')
        
        if mfe_r >= 1.0:
            if outcome == 'win':
                be_1r_wins += 1
            else:
                be_1r_be += 1
        else:
            if outcome == 'win':
                be_1r_wins += 1
            else:
                be_1r_losses += 1
    
    # ================================================================
    # SECTION 8: STREAK ANALYSIS
    # ================================================================
    max_win_streak = 0
    max_loss_streak = 0
    current_win_streak = 0
    current_loss_streak = 0
    
    for t in v6_trades:
        if t.get('final_outcome') == 'win':
            current_win_streak += 1
            current_loss_streak = 0
            if current_win_streak > max_win_streak:
                max_win_streak = current_win_streak
        elif t.get('final_outcome') == 'loss':
            current_loss_streak += 1
            current_win_streak = 0
            if current_loss_streak > max_loss_streak:
                max_loss_streak = current_loss_streak
    
    # ================================================================
    # SECTION 9: CLUSTER ANALYSIS
    # ================================================================
    # Group trades by hour
    trades_by_hour = defaultdict(list)
    for t in v6_trades:
        ts = parse_ts(t.get('timestamp'))
        if ts:
            hour_key = ts.strftime('%Y-%m-%d %H')
            trades_by_hour[hour_key].append(t)
    
    clustered_trades = []
    isolated_trades = []
    
    for hour, trades in trades_by_hour.items():
        if len(trades) >= 3:
            clustered_trades.extend(trades)
        else:
            isolated_trades.extend(trades)
    
    cluster_wins = len([t for t in clustered_trades if t.get('final_outcome') == 'win'])
    cluster_total = len([t for t in clustered_trades if t.get('final_outcome') in ['win', 'loss']])
    cluster_wr = (cluster_wins / cluster_total * 100) if cluster_total > 0 else 0
    
    isolated_wins = len([t for t in isolated_trades if t.get('final_outcome') == 'win'])
    isolated_total = len([t for t in isolated_trades if t.get('final_outcome') in ['win', 'loss']])
    isolated_wr = (isolated_wins / isolated_total * 100) if isolated_total > 0 else 0
    
    # ================================================================
    # GENERATE REPORT
    # ================================================================
    report = []
    
    report.append("=" * 80)
    report.append("  PropSignal Engine v6.0 - FULL DIAGNOSTIC & OPTIMIZATION REPORT")
    report.append(f"  Generated: {datetime.now().strftime('%Y-%m-%d %H:%M:%S UTC')}")
    report.append(f"  Data Period: {V6_DEPLOYMENT.strftime('%Y-%m-%d %H:%M')} → Present")
    report.append("=" * 80)
    report.append("")
    
    # SECTION 1
    report.append("┌" + "─" * 78 + "┐")
    report.append("│ 1. CORE PERFORMANCE (REAL TRADES ONLY)                                      │")
    report.append("└" + "─" * 78 + "┘")
    report.append("")
    report.append(f"  Total Trades:        {total}")
    report.append(f"  Wins / Losses:       {win_count} / {loss_count}")
    report.append(f"  Win Rate:            {win_rate:.1f}%")
    report.append(f"  Avg R per Trade:     {avg_r:.3f}R")
    report.append(f"  Total R:             {total_r:.2f}R")
    report.append(f"  Expectancy:          {expectancy:.3f}R")
    report.append(f"  Profit Factor:       {profit_factor:.2f}")
    report.append(f"  Max Drawdown:        {max_dd_r:.2f}R ({max_dd_pct:.1f}%)")
    report.append(f"  Avg Win Size:        {avg_win:.2f}R")
    report.append(f"  Avg Loss Size:       {avg_loss:.2f}R")
    report.append("")
    
    report.append("  BREAKDOWN BY ASSET:")
    report.append("  ┌──────────┬────────┬──────┬────────┬──────────┬────────────┐")
    report.append("  │ Asset    │ Trades │ W/L  │ WR%    │ Total R  │ Expectancy │")
    report.append("  ├──────────┼────────┼──────┼────────┼──────────┼────────────┤")
    for asset, data in by_asset.items():
        t_count = len(data['trades'])
        wl = f"{data['wins']}/{data['losses']}"
        wr = (data['wins'] / (data['wins'] + data['losses']) * 100) if (data['wins'] + data['losses']) > 0 else 0
        exp = data['r'] / t_count if t_count > 0 else 0
        report.append(f"  │ {asset:<8} │ {t_count:>6} │ {wl:>4} │ {wr:>5.1f}% │ {data['r']:>+7.2f}R │ {exp:>+9.3f}R │")
    report.append("  └──────────┴────────┴──────┴────────┴──────────┴────────────┘")
    report.append("")
    
    report.append("  BREAKDOWN BY SESSION:")
    report.append("  ┌──────────┬────────┬──────┬────────┬──────────┬────────────┐")
    report.append("  │ Session  │ Trades │ W/L  │ WR%    │ Total R  │ Expectancy │")
    report.append("  ├──────────┼────────┼──────┼────────┼──────────┼────────────┤")
    for session in ['London', 'Overlap', 'New York', 'Asia']:
        data = by_session.get(session, {'trades': [], 'wins': 0, 'losses': 0, 'r': 0})
        t_count = len(data['trades'])
        if t_count == 0:
            continue
        wl = f"{data['wins']}/{data['losses']}"
        wr = (data['wins'] / (data['wins'] + data['losses']) * 100) if (data['wins'] + data['losses']) > 0 else 0
        exp = data['r'] / t_count if t_count > 0 else 0
        report.append(f"  │ {session:<8} │ {t_count:>6} │ {wl:>4} │ {wr:>5.1f}% │ {data['r']:>+7.2f}R │ {exp:>+9.3f}R │")
    report.append("  └──────────┴────────┴──────┴────────┴──────────┴────────────┘")
    report.append("")
    
    report.append("  BREAKDOWN BY DIRECTION:")
    report.append("  ┌──────────┬────────┬──────┬────────┬──────────┬────────────┐")
    report.append("  │ Dir      │ Trades │ W/L  │ WR%    │ Total R  │ Expectancy │")
    report.append("  ├──────────┼────────┼──────┼────────┼──────────┼────────────┤")
    for direction, data in by_direction.items():
        t_count = len(data['trades'])
        wl = f"{data['wins']}/{data['losses']}"
        wr = (data['wins'] / (data['wins'] + data['losses']) * 100) if (data['wins'] + data['losses']) > 0 else 0
        exp = data['r'] / t_count if t_count > 0 else 0
        report.append(f"  │ {direction:<8} │ {t_count:>6} │ {wl:>4} │ {wr:>5.1f}% │ {data['r']:>+7.2f}R │ {exp:>+9.3f}R │")
    report.append("  └──────────┴────────┴──────┴────────┴──────────┴────────────┘")
    report.append("")
    
    # SECTION 2
    report.append("┌" + "─" * 78 + "┐")
    report.append("│ 2. SCORE ANALYSIS                                                           │")
    report.append("└" + "─" * 78 + "┘")
    report.append("")
    report.append("  ┌──────────┬────────┬──────┬────────┬──────────┬────────────┐")
    report.append("  │ Bucket   │ Trades │ W/L  │ WR%    │ Total R  │ Expectancy │")
    report.append("  ├──────────┼────────┼──────┼────────┼──────────┼────────────┤")
    
    best_bucket = None
    best_exp = -999
    
    for bucket in ['75+', '70-74', '65-69', '60-64']:
        data = score_buckets[bucket]
        t_count = len(data['trades'])
        if t_count == 0:
            report.append(f"  │ {bucket:<8} │ {0:>6} │  -   │    -   │       -  │         -  │")
            continue
        wl = f"{data['wins']}/{data['losses']}"
        completed = data['wins'] + data['losses']
        wr = (data['wins'] / completed * 100) if completed > 0 else 0
        exp = data['r'] / completed if completed > 0 else 0
        
        if exp > best_exp and completed >= 3:
            best_exp = exp
            best_bucket = bucket
        
        report.append(f"  │ {bucket:<8} │ {t_count:>6} │ {wl:>4} │ {wr:>5.1f}% │ {data['r']:>+7.2f}R │ {exp:>+9.3f}R │")
    
    report.append("  └──────────┴────────┴──────┴────────┴──────────┴────────────┘")
    report.append("")
    report.append(f"  👉 OPTIMAL MIN_CONFIDENCE_SCORE: {best_bucket if best_bucket else 'N/A'} (best expectancy)")
    report.append("")
    
    # SECTION 3
    report.append("┌" + "─" * 78 + "┐")
    report.append("│ 3. FILTER EFFECTIVENESS                                                     │")
    report.append("└" + "─" * 78 + "┘")
    report.append("")
    report.append("  ┌────────────────────┬─────────┬──────────┬───────────┬────────┬──────────┐")
    report.append("  │ Filter             │ Blocked │ Would W  │ Would L   │ WR%    │ VERDICT  │")
    report.append("  ├────────────────────┼─────────┼──────────┼───────────┼────────┼──────────┤")
    
    for reason in ['low_confidence', 'weak_mtf', 'duplicate', 'fta_blocked', 'buffer_zone_failed']:
        data = rejection_reasons.get(reason, {'count': 0, 'wins': 0, 'losses': 0})
        if data['count'] == 0:
            continue
        completed = data['wins'] + data['losses']
        wr = (data['wins'] / completed * 100) if completed > 0 else 0
        
        if data['losses'] > data['wins']:
            verdict = "✅ KEEP"
        elif data['wins'] > data['losses'] * 2:
            verdict = "❌ RELAX"
        else:
            verdict = "⚠️ REVIEW"
        
        report.append(f"  │ {reason:<18} │ {data['count']:>7} │ {data['wins']:>8} │ {data['losses']:>9} │ {wr:>5.1f}% │ {verdict:<8} │")
    
    report.append("  └────────────────────┴─────────┴──────────┴───────────┴────────┴──────────┘")
    report.append("")
    
    # SECTION 4
    report.append("┌" + "─" * 78 + "┐")
    report.append("│ 4. REJECTED vs ACCEPTED COMPARISON                                          │")
    report.append("└" + "─" * 78 + "┘")
    report.append("")
    report.append("  ┌────────────────┬──────────┬──────────┬────────────┐")
    report.append("  │ Category       │ Win Rate │ Total R  │ Expectancy │")
    report.append("  ├────────────────┼──────────┼──────────┼────────────┤")
    report.append(f"  │ ACCEPTED       │ {acc_wr:>7.1f}% │ {acc_r:>+7.2f}R │ {acc_exp:>+9.3f}R │")
    report.append(f"  │ REJECTED (sim) │ {rej_wr:>7.1f}% │ {rej_r:>+7.2f}R │ {rej_exp:>+9.3f}R │")
    report.append("  └────────────────┴──────────┴──────────┴────────────┘")
    report.append("")
    
    if acc_wr > rej_wr:
        report.append("  👉 VERDICT: ✅ FILTERS WORKING - Accepted WR > Rejected WR")
    else:
        report.append("  👉 VERDICT: ⚠️ FILTERS MAY BE TOO AGGRESSIVE - Rejected WR >= Accepted WR")
    report.append("")
    
    # SECTION 5
    report.append("┌" + "─" * 78 + "┐")
    report.append("│ 5. ENTRY QUALITY ANALYSIS                                                   │")
    report.append("└" + "─" * 78 + "┘")
    report.append("")
    report.append(f"  Avg MFE (all trades):           {avg_mfe:.2f}R")
    report.append(f"  Avg MAE (all trades):           {avg_mae:.2f}R")
    report.append(f"  % SL hit after profit:          {pct_profit_before_sl:.1f}%")
    report.append(f"  Avg peak R before SL:           {avg_peak_before_sl:.3f}R")
    report.append("")
    
    if pct_profit_before_sl > 50:
        report.append("  👉 ISSUE: ⚠️ MANY TRADES GO PROFIT BEFORE SL - Consider tighter entries or wider SL")
    elif avg_mae > 0.5:
        report.append("  👉 ISSUE: ⚠️ HIGH AVG MAE - Entries may be early/noisy")
    else:
        report.append("  👉 VERDICT: ✅ ENTRY QUALITY ACCEPTABLE")
    report.append("")
    
    # SECTION 6
    report.append("┌" + "─" * 78 + "┐")
    report.append("│ 6. STOP LOSS & TAKE PROFIT QUALITY                                          │")
    report.append("└" + "─" * 78 + "┘")
    report.append("")
    report.append(f"  % SL hit after showing profit:  {pct_profit_before_sl:.1f}%")
    report.append(f"  % TP reached clean (<0.3R DD):  {pct_tp_clean:.1f}%")
    report.append(f"  Avg RR achieved (wins):         {avg_achieved_rr:.2f}R")
    report.append("")
    
    if pct_profit_before_sl > 60:
        report.append("  👉 SL VERDICT: ⚠️ SL TOO TIGHT - Consider widening by 10-20%")
    else:
        report.append("  👉 SL VERDICT: ✅ SL SIZE ACCEPTABLE")
    report.append("")
    
    # SECTION 7
    report.append("┌" + "─" * 78 + "┐")
    report.append("│ 7. TRADE MANAGEMENT SIMULATION                                              │")
    report.append("└" + "─" * 78 + "┘")
    report.append("")
    
    current_r = win_count * avg_win - loss_count
    be_05_r = be_05r_wins * avg_win - be_05r_losses
    be_1_r = be_1r_wins * avg_win - be_1r_losses
    
    report.append("  ┌────────────────────┬───────┬────────┬────────┬──────────┐")
    report.append("  │ Strategy           │ Wins  │ Losses │ BE     │ Est. R   │")
    report.append("  ├────────────────────┼───────┼────────┼────────┼──────────┤")
    report.append(f"  │ CURRENT            │ {win_count:>5} │ {loss_count:>6} │ {0:>6} │ {current_r:>+7.2f}R │")
    report.append(f"  │ BE at 0.5R         │ {be_05r_wins:>5} │ {be_05r_losses:>6} │ {be_05r_be:>6} │ {be_05_r:>+7.2f}R │")
    report.append(f"  │ BE at 1R           │ {be_1r_wins:>5} │ {be_1r_losses:>6} │ {be_1r_be:>6} │ {be_1_r:>+7.2f}R │")
    report.append("  └────────────────────┴───────┴────────┴────────┴──────────┘")
    report.append("")
    
    if be_05_r > current_r:
        report.append("  👉 RECOMMENDATION: Consider BE at 0.5R (would improve results)")
    elif be_1_r > current_r:
        report.append("  👉 RECOMMENDATION: Consider BE at 1R (would improve results)")
    else:
        report.append("  👉 RECOMMENDATION: Current management is optimal")
    report.append("")
    
    # SECTION 8
    report.append("┌" + "─" * 78 + "┐")
    report.append("│ 8. CONSECUTIVE STREAK ANALYSIS                                              │")
    report.append("└" + "─" * 78 + "┘")
    report.append("")
    report.append(f"  Max Win Streak:   {max_win_streak}")
    report.append(f"  Max Loss Streak:  {max_loss_streak}")
    report.append("")
    
    if max_loss_streak >= 5:
        report.append("  👉 WARNING: ⚠️ HIGH LOSS STREAK DETECTED - Review regime/market conditions")
    else:
        report.append("  👉 VERDICT: ✅ STREAKS WITHIN NORMAL RANGE")
    report.append("")
    
    # SECTION 9
    report.append("┌" + "─" * 78 + "┐")
    report.append("│ 9. CLUSTER ANALYSIS                                                         │")
    report.append("└" + "─" * 78 + "┘")
    report.append("")
    report.append(f"  Clustered trades (3+ per hour): {len(clustered_trades)}")
    report.append(f"  Clustered WR:                   {cluster_wr:.1f}%")
    report.append(f"  Isolated trades:                {len(isolated_trades)}")
    report.append(f"  Isolated WR:                    {isolated_wr:.1f}%")
    report.append("")
    
    if cluster_wr > isolated_wr + 10:
        report.append("  👉 INSIGHT: Clustered trades perform BETTER - momentum signals are stronger")
    elif isolated_wr > cluster_wr + 10:
        report.append("  👉 INSIGHT: Isolated trades perform BETTER - reduce signal clustering")
    else:
        report.append("  👉 INSIGHT: No significant difference between clustered and isolated")
    report.append("")
    
    # SECTION 10
    report.append("┌" + "─" * 78 + "┐")
    report.append("│ 10. FINAL ENGINE VERDICT                                                    │")
    report.append("└" + "─" * 78 + "┘")
    report.append("")
    
    is_profitable = total_r > 0 and win_rate > 50
    
    report.append(f"  1. Is the engine PROFITABLE?")
    if is_profitable:
        report.append(f"     ✅ YES - {total_r:.2f}R total, {win_rate:.1f}% WR, {expectancy:.3f}R expectancy")
    else:
        report.append(f"     ❌ NO - {total_r:.2f}R total, {win_rate:.1f}% WR")
    report.append("")
    
    report.append(f"  2. What is the MAIN EDGE?")
    if by_asset.get('XAUUSD', {}).get('r', 0) > by_asset.get('EURUSD', {}).get('r', 0):
        report.append(f"     → XAUUSD trading (stronger trends, cleaner signals)")
    else:
        report.append(f"     → EURUSD trading")
    report.append("")
    
    report.append(f"  3. What is the BIGGEST WEAKNESS?")
    if pct_profit_before_sl > 50:
        report.append(f"     → SL too tight ({pct_profit_before_sl:.0f}% of losses showed profit first)")
    elif max_loss_streak >= 4:
        report.append(f"     → Vulnerability to loss streaks (max: {max_loss_streak})")
    else:
        report.append(f"     → No critical weakness detected")
    report.append("")
    
    report.append(f"  4. What should be changed NOW?")
    changes = []
    if pct_profit_before_sl > 60:
        changes.append("Widen SL by 15-20%")
    if rej_wr > acc_wr:
        changes.append("Relax overly aggressive filters")
    if not changes:
        changes.append("NO CHANGES NEEDED - System is performing well")
    for c in changes:
        report.append(f"     → {c}")
    report.append("")
    
    report.append(f"  5. What should NOT be touched?")
    report.append(f"     → Core scoring algorithm")
    report.append(f"     → MTF alignment logic")
    report.append(f"     → Entry timing (working well)")
    report.append("")
    
    # SECTION 11
    report.append("┌" + "─" * 78 + "┐")
    report.append("│ 11. ACTION PLAN                                                             │")
    report.append("└" + "─" * 78 + "┘")
    report.append("")
    
    if is_profitable and pct_profit_before_sl < 50 and acc_wr > rej_wr:
        report.append("  ╔════════════════════════════════════════════════════════════════════════╗")
        report.append("  ║  ✅ NO CHANGES REQUIRED - SYSTEM IS OPTIMAL                           ║")
        report.append("  ║                                                                        ║")
        report.append("  ║  The engine is profitable with good filter effectiveness.              ║")
        report.append("  ║  Continue collecting data and monitoring performance.                  ║")
        report.append("  ╚════════════════════════════════════════════════════════════════════════╝")
    else:
        report.append("  RECOMMENDED CHANGES:")
        report.append("")
        if pct_profit_before_sl > 50:
            report.append("  1. WIDEN STOP LOSS")
            report.append(f"     Current issue: {pct_profit_before_sl:.0f}% of SL hits showed profit first")
            report.append("     Action: Increase SL distance by 15-20%")
            report.append("")
        if rej_wr > acc_wr:
            report.append("  2. RELAX FILTERS")
            report.append("     Current issue: Rejected trades outperforming accepted")
            report.append("     Action: Review and relax most aggressive filter")
            report.append("")
        if be_05_r > current_r:
            report.append("  3. IMPLEMENT BE AT 0.5R")
            report.append(f"     Estimated improvement: {be_05_r - current_r:.2f}R")
            report.append("")
    
    report.append("")
    report.append("=" * 80)
    report.append("  END OF REPORT")
    report.append("=" * 80)
    
    # Print and save
    report_text = "\n".join(report)
    print(report_text)
    
    with open('/app/backend/data/v6_full_diagnostic.md', 'w') as f:
        f.write(report_text)
    
    print(f"\n\nReport saved to /app/backend/data/v6_full_diagnostic.md")

if __name__ == "__main__":
    analyze()
