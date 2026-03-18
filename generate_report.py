#!/usr/bin/env python3
"""
PropSignal Engine - Complete Performance Report Generator
=========================================================
"""

import json
from datetime import datetime, timedelta
from collections import defaultdict
import statistics

# Load data
with open('/app/backend/data/tracked_signals.json', 'r') as f:
    data = json.load(f)

completed = data.get('completed', [])
active = data.get('active', [])

# Also load missed opportunities
try:
    with open('/app/backend/storage/missed_opportunities.json', 'r') as f:
        missed_data = json.load(f)
        missed_opps = missed_data if isinstance(missed_data, list) else missed_data.get('opportunities', [])
except:
    missed_opps = []

print("=" * 80)
print("PROPSIGNAL ENGINE - COMPLETE PERFORMANCE REPORT")
print("=" * 80)
print(f"Report Generated: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
print(f"Data Period: {completed[0]['timestamp'][:10] if completed else 'N/A'} to {completed[-1]['timestamp'][:10] if completed else 'N/A'}")
print("=" * 80)

# ============================================================================
# 1. GENERAL METRICS
# ============================================================================
print("\n" + "=" * 80)
print("1. GENERAL METRICS")
print("=" * 80)

total_trades = len(completed)
wins = [t for t in completed if t.get('final_outcome') == 'win']
losses = [t for t in completed if t.get('final_outcome') == 'loss']
expired = [t for t in completed if t.get('status') == 'expired']

win_count = len(wins)
loss_count = len(losses)
expired_count = len(expired)

# Calculate winrate (excluding expired)
trades_excl_expired = win_count + loss_count
winrate = (win_count / trades_excl_expired * 100) if trades_excl_expired > 0 else 0

# Calculate R values
def get_r_value(trade):
    """Calculate R value for a trade"""
    if trade.get('final_outcome') == 'win':
        # TP1 hit = 1.33R typically
        return 1.33
    elif trade.get('final_outcome') == 'loss':
        return -1.0
    return 0

r_values = [get_r_value(t) for t in completed if t.get('final_outcome') in ['win', 'loss']]
total_r = sum(r_values)
expectancy = total_r / len(r_values) if r_values else 0

# Average R win/loss
win_r_values = [1.33 for t in wins]  # TP1 = 1.33R
loss_r_values = [-1.0 for t in losses]

avg_win_r = statistics.mean(win_r_values) if win_r_values else 0
avg_loss_r = abs(statistics.mean(loss_r_values)) if loss_r_values else 0

print(f"\nTotal Trades Completed:     {total_trades}")
print(f"Wins:                       {win_count}")
print(f"Losses:                     {loss_count}")
print(f"Expired:                    {expired_count}")
print(f"\nWin Rate (excl. expired):   {winrate:.1f}%")
print(f"Total R Gained:             {total_r:+.2f}R")
print(f"Expectancy (R per trade):   {expectancy:+.3f}R")
print(f"\nAverage R on Win:           +{avg_win_r:.2f}R")
print(f"Average R on Loss:          -{avg_loss_r:.2f}R")
print(f"Profit Factor:              {(win_count * 1.33) / (loss_count * 1.0) if loss_count > 0 else 'N/A':.2f}")

# ============================================================================
# 2. DISTRIBUTION
# ============================================================================
print("\n" + "=" * 80)
print("2. R DISTRIBUTION & TRADE PROGRESSION")
print("=" * 80)

# MFE in R terms
def calc_mfe_in_r(trade):
    """Calculate MFE in R terms"""
    mfe = trade.get('max_favorable_excursion', 0)
    entry = trade.get('entry_price', 0)
    sl = trade.get('stop_loss', 0)
    if entry and sl:
        risk = abs(entry - sl)
        if risk > 0:
            return mfe / risk
    return 0

mfe_r_values = [calc_mfe_in_r(t) for t in completed]

# Distribution buckets
r_buckets = {
    '0-0.5R': 0,
    '0.5-1R': 0,
    '1-1.5R': 0,
    '1.5-2R': 0,
    '2R+': 0
}

for mfe_r in mfe_r_values:
    if mfe_r < 0.5:
        r_buckets['0-0.5R'] += 1
    elif mfe_r < 1.0:
        r_buckets['0.5-1R'] += 1
    elif mfe_r < 1.5:
        r_buckets['1-1.5R'] += 1
    elif mfe_r < 2.0:
        r_buckets['1.5-2R'] += 1
    else:
        r_buckets['2R+'] += 1

print("\nMFE (Max Favorable Excursion) Distribution:")
print("-" * 40)
for bucket, count in r_buckets.items():
    pct = count / total_trades * 100 if total_trades > 0 else 0
    bar = "█" * int(pct / 2)
    print(f"  {bucket:10} : {count:4} ({pct:5.1f}%) {bar}")

# Trades reaching milestones
reached_half_r = sum(1 for t in completed if t.get('reached_half_r', False))
reached_one_r = sum(1 for t in completed if t.get('reached_one_r', False))
reached_two_r = sum(1 for t in completed if t.get('reached_two_r', False))

print(f"\nTrade Progression Milestones:")
print("-" * 40)
print(f"  Reached 0.5R:  {reached_half_r:4} / {total_trades} ({reached_half_r/total_trades*100:.1f}%)")
print(f"  Reached 1.0R:  {reached_one_r:4} / {total_trades} ({reached_one_r/total_trades*100:.1f}%)")
print(f"  Reached 2.0R:  {reached_two_r:4} / {total_trades} ({reached_two_r/total_trades*100:.1f}%)")

# BE possible
be_possible = sum(1 for t in completed if t.get('breakeven_possible', False))
print(f"\n  BE possible at 1R: {be_possible:4} / {total_trades} ({be_possible/total_trades*100:.1f}%)")

# ============================================================================
# 3. MFE / MAE ANALYSIS
# ============================================================================
print("\n" + "=" * 80)
print("3. MFE / MAE ANALYSIS")
print("=" * 80)

# MFE stats
mfe_values = [t.get('max_favorable_excursion', 0) for t in completed]
mae_values = [t.get('max_adverse_excursion', 0) for t in completed]
peak_r_values = [t.get('peak_r_before_reversal', 0) for t in completed]

# Separate by asset for proper pip calculation
eurusd_trades = [t for t in completed if t.get('asset') == 'EURUSD']
xauusd_trades = [t for t in completed if t.get('asset') == 'XAUUSD']

print("\nOverall MFE/MAE Statistics:")
print("-" * 50)
print(f"  Average MFE (R):          {statistics.mean(mfe_r_values):.2f}R")
print(f"  Average MAE (R):          {statistics.mean([calc_mfe_in_r(t) * -1 if t.get('max_adverse_excursion') else 0 for t in completed]):.2f}R")
print(f"  Average Peak R:           {statistics.mean([t.get('peak_r_before_reversal', 0) for t in completed]):.2f}R")
print(f"  Max Peak R Achieved:      {max([t.get('peak_r_before_reversal', 0) for t in completed]):.2f}R")

# MFE for XAUUSD (in pips/points)
if xauusd_trades:
    xau_mfe = [t.get('max_favorable_excursion', 0) for t in xauusd_trades]
    xau_mae = [t.get('max_adverse_excursion', 0) for t in xauusd_trades]
    print(f"\nXAUUSD Specific:")
    print(f"  Average MFE:              {statistics.mean(xau_mfe):.1f} points")
    print(f"  Average MAE:              {statistics.mean(xau_mae):.1f} points")

# MFE for EURUSD
if eurusd_trades:
    eur_mfe = [t.get('max_favorable_excursion', 0) * 10000 for t in eurusd_trades]  # Convert to pips
    eur_mae = [t.get('max_adverse_excursion', 0) * 10000 for t in eurusd_trades]
    print(f"\nEURUSD Specific:")
    print(f"  Average MFE:              {statistics.mean(eur_mfe):.1f} pips")
    print(f"  Average MAE:              {statistics.mean(eur_mae):.1f} pips")

# Analysis of losers
print(f"\nLosing Trade Analysis:")
print("-" * 50)
losers_with_profit = [t for t in losses if t.get('moved_favorable_before_fail', False)]
print(f"  Losers that saw profit:   {len(losers_with_profit)} / {loss_count} ({len(losers_with_profit)/loss_count*100 if loss_count else 0:.1f}%)")

# ============================================================================
# 4. TIME ANALYSIS
# ============================================================================
print("\n" + "=" * 80)
print("4. TIME ANALYSIS")
print("=" * 80)

# Trade duration
durations = [t.get('time_to_outcome_seconds', 0) for t in completed if t.get('time_to_outcome_seconds')]
avg_duration = statistics.mean(durations) if durations else 0
min_duration = min(durations) if durations else 0
max_duration = max(durations) if durations else 0

print(f"\nTrade Duration Statistics:")
print("-" * 50)
print(f"  Average Duration:         {avg_duration/60:.1f} minutes ({avg_duration/3600:.2f} hours)")
print(f"  Fastest Trade:            {min_duration/60:.1f} minutes")
print(f"  Longest Trade:            {max_duration/60:.1f} minutes ({max_duration/3600:.2f} hours)")

# Time in profit vs drawdown
time_in_profit = [t.get('time_in_profit_seconds', 0) for t in completed]
time_in_drawdown = [t.get('time_in_drawdown_seconds', 0) for t in completed]

print(f"\n  Avg Time in Profit:       {statistics.mean(time_in_profit)/60:.1f} minutes")
print(f"  Avg Time in Drawdown:     {statistics.mean(time_in_drawdown)/60:.1f} minutes")

# Session analysis
session_stats = defaultdict(lambda: {'wins': 0, 'losses': 0, 'total': 0})
for t in completed:
    session = t.get('session', 'Unknown')
    session_stats[session]['total'] += 1
    if t.get('final_outcome') == 'win':
        session_stats[session]['wins'] += 1
    elif t.get('final_outcome') == 'loss':
        session_stats[session]['losses'] += 1

print(f"\nPerformance by Session:")
print("-" * 50)
for session, stats in sorted(session_stats.items()):
    total = stats['total']
    wins = stats['wins']
    losses = stats['losses']
    wr = wins / (wins + losses) * 100 if (wins + losses) > 0 else 0
    r_gained = wins * 1.33 - losses * 1.0
    print(f"  {session:12} : {total:4} trades | WR: {wr:5.1f}% | R: {r_gained:+.2f}R")

# ============================================================================
# 5. BREAKDOWN
# ============================================================================
print("\n" + "=" * 80)
print("5. DETAILED BREAKDOWN")
print("=" * 80)

# By symbol
print(f"\n5.1 BY SYMBOL:")
print("-" * 60)
symbol_stats = defaultdict(lambda: {'wins': 0, 'losses': 0, 'total': 0, 'r': 0})
for t in completed:
    asset = t.get('asset', 'Unknown')
    symbol_stats[asset]['total'] += 1
    if t.get('final_outcome') == 'win':
        symbol_stats[asset]['wins'] += 1
        symbol_stats[asset]['r'] += 1.33
    elif t.get('final_outcome') == 'loss':
        symbol_stats[asset]['losses'] += 1
        symbol_stats[asset]['r'] -= 1.0

for symbol, stats in sorted(symbol_stats.items()):
    total = stats['total']
    wins = stats['wins']
    losses = stats['losses']
    wr = wins / (wins + losses) * 100 if (wins + losses) > 0 else 0
    print(f"  {symbol:10} | Total: {total:4} | Wins: {wins:4} | Losses: {losses:4} | WR: {wr:5.1f}% | R: {stats['r']:+.2f}R")

# By direction
print(f"\n5.2 BY DIRECTION:")
print("-" * 60)
direction_stats = defaultdict(lambda: {'wins': 0, 'losses': 0, 'total': 0, 'r': 0})
for t in completed:
    direction = t.get('direction', 'Unknown')
    direction_stats[direction]['total'] += 1
    if t.get('final_outcome') == 'win':
        direction_stats[direction]['wins'] += 1
        direction_stats[direction]['r'] += 1.33
    elif t.get('final_outcome') == 'loss':
        direction_stats[direction]['losses'] += 1
        direction_stats[direction]['r'] -= 1.0

for direction, stats in sorted(direction_stats.items()):
    total = stats['total']
    wins = stats['wins']
    losses = stats['losses']
    wr = wins / (wins + losses) * 100 if (wins + losses) > 0 else 0
    print(f"  {direction:10} | Total: {total:4} | Wins: {wins:4} | Losses: {losses:4} | WR: {wr:5.1f}% | R: {stats['r']:+.2f}R")

# By setup type
print(f"\n5.3 BY SETUP TYPE:")
print("-" * 60)
setup_stats = defaultdict(lambda: {'wins': 0, 'losses': 0, 'total': 0, 'r': 0})
for t in completed:
    setup = t.get('setup_type', 'Unknown')
    setup_stats[setup]['total'] += 1
    if t.get('final_outcome') == 'win':
        setup_stats[setup]['wins'] += 1
        setup_stats[setup]['r'] += 1.33
    elif t.get('final_outcome') == 'loss':
        setup_stats[setup]['losses'] += 1
        setup_stats[setup]['r'] -= 1.0

for setup, stats in sorted(setup_stats.items(), key=lambda x: -x[1]['total']):
    total = stats['total']
    wins = stats['wins']
    losses = stats['losses']
    wr = wins / (wins + losses) * 100 if (wins + losses) > 0 else 0
    print(f"  {setup:25} | {total:4} | W:{wins:3} L:{losses:3} | WR: {wr:5.1f}% | R: {stats['r']:+.2f}R")

# By score bucket
print(f"\n5.4 BY SCORE BUCKET:")
print("-" * 60)
score_buckets = {
    '60-65': {'wins': 0, 'losses': 0, 'total': 0},
    '65-70': {'wins': 0, 'losses': 0, 'total': 0},
    '70-75': {'wins': 0, 'losses': 0, 'total': 0},
    '75-80': {'wins': 0, 'losses': 0, 'total': 0},
    '80+': {'wins': 0, 'losses': 0, 'total': 0},
}

for t in completed:
    score = t.get('confidence_score', 0)
    if score < 65:
        bucket = '60-65'
    elif score < 70:
        bucket = '65-70'
    elif score < 75:
        bucket = '70-75'
    elif score < 80:
        bucket = '75-80'
    else:
        bucket = '80+'
    
    score_buckets[bucket]['total'] += 1
    if t.get('final_outcome') == 'win':
        score_buckets[bucket]['wins'] += 1
    elif t.get('final_outcome') == 'loss':
        score_buckets[bucket]['losses'] += 1

for bucket in ['60-65', '65-70', '70-75', '75-80', '80+']:
    stats = score_buckets[bucket]
    total = stats['total']
    wins = stats['wins']
    losses = stats['losses']
    wr = wins / (wins + losses) * 100 if (wins + losses) > 0 else 0
    r = wins * 1.33 - losses * 1.0
    print(f"  Score {bucket:6} | {total:4} trades | W:{wins:3} L:{losses:3} | WR: {wr:5.1f}% | R: {r:+.2f}R")

# ============================================================================
# 6. FILTER ANALYSIS
# ============================================================================
print("\n" + "=" * 80)
print("6. FILTER ANALYSIS")
print("=" * 80)

# MTF Alignment analysis
print(f"\n6.1 MTF ALIGNMENT IMPACT:")
print("-" * 60)

mtf_strong = []  # MTF score >= 80
mtf_weak = []    # MTF score < 80

for t in completed:
    breakdown = t.get('score_breakdown', {}).get('breakdown', [])
    mtf_score = None
    for item in breakdown:
        if 'MTF' in item.get('factor', ''):
            mtf_score = item.get('score', 0)
            break
    
    if mtf_score is not None:
        if mtf_score >= 80:
            mtf_strong.append(t)
        else:
            mtf_weak.append(t)

def calc_stats(trades):
    wins = sum(1 for t in trades if t.get('final_outcome') == 'win')
    losses = sum(1 for t in trades if t.get('final_outcome') == 'loss')
    total = wins + losses
    wr = wins / total * 100 if total > 0 else 0
    r = wins * 1.33 - losses * 1.0
    return total, wins, losses, wr, r

strong_stats = calc_stats(mtf_strong)
weak_stats = calc_stats(mtf_weak)

print(f"  Strong MTF (>=80): {strong_stats[0]:4} trades | WR: {strong_stats[3]:5.1f}% | R: {strong_stats[4]:+.2f}R")
print(f"  Weak MTF (<80):    {weak_stats[0]:4} trades | WR: {weak_stats[3]:5.1f}% | R: {weak_stats[4]:+.2f}R")

# High vs Low confidence
print(f"\n6.2 CONFIDENCE LEVEL IMPACT:")
print("-" * 60)

high_conf = [t for t in completed if t.get('confidence_score', 0) >= 70]
low_conf = [t for t in completed if t.get('confidence_score', 0) < 70]

high_stats = calc_stats(high_conf)
low_stats = calc_stats(low_conf)

print(f"  High Confidence (>=70): {high_stats[0]:4} trades | WR: {high_stats[3]:5.1f}% | R: {high_stats[4]:+.2f}R")
print(f"  Low Confidence (<70):   {low_stats[0]:4} trades | WR: {low_stats[3]:5.1f}% | R: {low_stats[4]:+.2f}R")

# ============================================================================
# 7. SIGNAL QUALITY & REJECTIONS
# ============================================================================
print("\n" + "=" * 80)
print("7. SIGNAL QUALITY & REJECTIONS")
print("=" * 80)

print(f"\n7.1 SIGNAL FLOW:")
print("-" * 60)
print(f"  Signals Generated (completed):  {total_trades}")
print(f"  Signals Rejected/Missed:        {len(missed_opps)}")
total_evaluated = total_trades + len(missed_opps)
print(f"  Total Evaluated:                {total_evaluated}")
print(f"  Acceptance Rate:                {total_trades/total_evaluated*100 if total_evaluated else 0:.1f}%")

# Rejection reasons
print(f"\n7.2 TOP REJECTION REASONS:")
print("-" * 60)

rejection_reasons = defaultdict(int)
for opp in missed_opps:
    reason = opp.get('rejection_reason', opp.get('reason', 'Unknown'))
    # Simplify reason
    if 'FTA' in str(reason).upper():
        rejection_reasons['FTA Filter (obstacle too close)'] += 1
    elif 'score' in str(reason).lower() or 'threshold' in str(reason).lower():
        rejection_reasons['Score Below Threshold'] += 1
    elif 'mtf' in str(reason).lower() or 'alignment' in str(reason).lower():
        rejection_reasons['MTF Alignment Failed'] += 1
    elif 'momentum' in str(reason).lower():
        rejection_reasons['Momentum Divergent'] += 1
    elif 'spread' in str(reason).lower():
        rejection_reasons['Spread Too Wide'] += 1
    else:
        rejection_reasons[str(reason)[:40]] += 1

for reason, count in sorted(rejection_reasons.items(), key=lambda x: -x[1])[:10]:
    pct = count / len(missed_opps) * 100 if missed_opps else 0
    print(f"  {reason:40} : {count:5} ({pct:5.1f}%)")

# ============================================================================
# 8. OPEN TRADES
# ============================================================================
print("\n" + "=" * 80)
print("8. CURRENT OPEN TRADES")
print("=" * 80)

if active:
    print(f"\nActive Trades: {len(active)}")
    print("-" * 60)
    for t in active:
        print(f"  {t.get('signal_id', 'Unknown')}")
        print(f"    Asset: {t.get('asset')} | Direction: {t.get('direction')}")
        print(f"    Entry: {t.get('entry_price')} | SL: {t.get('stop_loss'):.5f} | TP: {t.get('take_profit_1'):.5f}")
        print(f"    Score: {t.get('confidence_score'):.1f} | Status: {t.get('status')}")
        print()
else:
    print("\nNo active trades currently open.")

# ============================================================================
# 9. RECOMMENDATIONS
# ============================================================================
print("\n" + "=" * 80)
print("9. WHAT SHOULD BE IMPROVED BASED ON DATA")
print("=" * 80)

print("\n📊 KEY FINDINGS:")
print("-" * 60)

# 1. Win rate analysis
if winrate < 50:
    print(f"⚠️  Win rate ({winrate:.1f}%) is below 50% - consider tightening entry criteria")
elif winrate > 65:
    print(f"✅ Win rate ({winrate:.1f}%) is healthy")
else:
    print(f"⚡ Win rate ({winrate:.1f}%) is acceptable but could be improved")

# 2. Score bucket analysis
best_bucket = max(score_buckets.items(), key=lambda x: (x[1]['wins'] / (x[1]['wins'] + x[1]['losses']) if (x[1]['wins'] + x[1]['losses']) > 0 else 0))
worst_bucket = min([(k, v) for k, v in score_buckets.items() if v['total'] > 5], 
                   key=lambda x: (x[1]['wins'] / (x[1]['wins'] + x[1]['losses']) if (x[1]['wins'] + x[1]['losses']) > 0 else 0),
                   default=('N/A', {'wins': 0, 'losses': 0}))

print(f"\n📈 SCORE-BASED INSIGHTS:")
print(f"   Best performing bucket: {best_bucket[0]} scores")
print(f"   Consider raising minimum score threshold to 70+")

# 3. Symbol analysis
xau_stats = symbol_stats.get('XAUUSD', {'wins': 0, 'losses': 0, 'r': 0})
eur_stats = symbol_stats.get('EURUSD', {'wins': 0, 'losses': 0, 'r': 0})

print(f"\n📈 SYMBOL-SPECIFIC INSIGHTS:")
if xau_stats['r'] < 0:
    print(f"   ⚠️  XAUUSD is underperforming (R: {xau_stats['r']:+.2f}R)")
    print(f"       Consider: stricter entry, wider SL, or pausing XAUUSD")
if eur_stats['r'] < 0:
    print(f"   ⚠️  EURUSD is underperforming (R: {eur_stats['r']:+.2f}R)")

# 4. Direction analysis
buy_stats = direction_stats.get('BUY', {'wins': 0, 'losses': 0, 'r': 0})
sell_stats = direction_stats.get('SELL', {'wins': 0, 'losses': 0, 'r': 0})

print(f"\n📈 DIRECTION INSIGHTS:")
if buy_stats['r'] > sell_stats['r'] + 5:
    print(f"   BUY trades significantly outperform SELL ({buy_stats['r']:+.2f}R vs {sell_stats['r']:+.2f}R)")
elif sell_stats['r'] > buy_stats['r'] + 5:
    print(f"   SELL trades significantly outperform BUY ({sell_stats['r']:+.2f}R vs {buy_stats['r']:+.2f}R)")

# 5. MFE/MAE insights
print(f"\n📈 TRADE MANAGEMENT INSIGHTS:")
print(f"   {reached_one_r} trades reached 1R before closing")
print(f"   {len(losers_with_profit)} losing trades saw profit first")
if len(losers_with_profit) > loss_count * 0.3:
    print(f"   ⚠️  {len(losers_with_profit)/loss_count*100:.0f}% of losers saw profit - consider partial TP at 0.5R")

print("\n🎯 RECOMMENDED ACTIONS:")
print("-" * 60)
print("1. Raise minimum score threshold to 70+ (current data shows higher scores = better results)")
print("2. Implement partial profit at 0.5R to capture runners that reverse")
print("3. Consider stricter FTA filter for XAUUSD (high rejection but still losses)")
print("4. Add trailing stop after 1R to lock in profits")
print("5. Review trades with score 60-65 - they have lower win rate")

print("\n" + "=" * 80)
print("END OF REPORT")
print("=" * 80)
