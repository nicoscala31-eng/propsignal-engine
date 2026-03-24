#!/bin/bash
REPORT_NUM=$1
echo ""
echo "============================================================"
echo "     DATA COLLECTION REPORT #$REPORT_NUM - $(date '+%Y-%m-%d %H:%M UTC')"
echo "============================================================"
curl -s localhost:8001/api/scanner/v3/status | python3 -c "
import sys, json
d=json.load(sys.stdin)

stats = d.get('statistics', {})
bzm = d.get('buffer_zone_metrics', {})
rr = d.get('rejection_reasons', {})

total_scans = stats.get('total_scans', 0)
signals = stats.get('signals_generated', 0)
rejections = stats.get('rejections', 0)
total_candidates = signals + rejections
acceptance_rate = (signals / total_candidates * 100) if total_candidates > 0 else 0

print()
print('1. TOTAL CANDIDATES:', f'{total_candidates:,}')
print('2. TOTAL ACCEPTED:', signals, f'(Target: 50 - {\"✅ REACHED\" if signals >= 50 else f\"{signals}/50\"})')
print('3. ACCEPTANCE RATE:', f'{acceptance_rate:.2f}%')
print()
print('4. BUFFER ZONE BREAKDOWN:')
main = bzm.get('accepted_main_threshold', 0)
buf = bzm.get('accepted_buffer_zone', 0)
buf_fail = rr.get('buffer_zone_failed', 0)
print(f'   Main (>=65): {main} | Buffer (60-64): {buf} | Buffer Failed: {buf_fail}')
print()
print('5. TOP REJECTION REASONS:')
total_rej = sum(rr.values())
for reason, count in sorted(rr.items(), key=lambda x: -x[1])[:5]:
    pct = count/total_rej*100 if total_rej > 0 else 0
    print(f'   {reason}: {count:,} ({pct:.1f}%)')
"
echo ""
echo "6. OUTCOME STATS:"
curl -s localhost:8001/api/tracker/status | python3 -c "
import sys, json
d=json.load(sys.stdin)
print(f'   Wins: {d.get(\"wins\", 0)} | Losses: {d.get(\"losses\", 0)} | Active: {d.get(\"active_trades\", 0)}')
"
echo ""
echo "============================================================"
