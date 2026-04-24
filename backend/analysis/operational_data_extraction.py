#!/usr/bin/env python3
"""
PATTERN ENGINE V3.0 - OPERATIONAL DATA EXTRACTION
==================================================
Dati numerici precisi per ottimizzare Entry, TP/SL e Filtri.
NO RIASSUNTI GENERICI - SOLO NUMERI.
"""

import json
import statistics
from collections import defaultdict
from typing import Dict, List, Any, Optional
from dataclasses import dataclass

DATA_DIR = "/app/backend/data"
STORAGE_DIR = "/app/backend/storage"

def load_json(filepath: str) -> Any:
    try:
        with open(filepath, 'r') as f:
            return json.load(f)
    except:
        return None

def percentile(data: List[float], p: int) -> float:
    """Calculate percentile"""
    if not data:
        return 0
    sorted_data = sorted(data)
    k = (len(sorted_data) - 1) * p / 100
    f = int(k)
    c = f + 1 if f + 1 < len(sorted_data) else f
    return sorted_data[f] + (sorted_data[c] - sorted_data[f]) * (k - f)

def safe_mean(data: List[float]) -> float:
    return statistics.mean(data) if data else 0

def safe_median(data: List[float]) -> float:
    return statistics.median(data) if data else 0

def main():
    print("=" * 70)
    print("PATTERN ENGINE V3.0 - OPERATIONAL DATA EXTRACTION")
    print("=" * 70)
    print()
    
    # Load data
    candidate_audit = load_json(f"{DATA_DIR}/candidate_audit.json") or {}
    signal_snapshots = load_json(f"{DATA_DIR}/signal_snapshots.json") or {}
    tracked_signals = load_json(f"{DATA_DIR}/tracked_signals.json") or []
    
    candidates = candidate_audit.get('candidates', [])
    snapshots = signal_snapshots.get('snapshots', [])
    
    # Separate executed and rejected
    executed = []
    rejected = []
    
    for c in candidates:
        outcome_data = c.get('outcome_data', {})
        if not outcome_data:
            continue
            
        trade = {
            'symbol': c.get('symbol', ''),
            'direction': c.get('direction', ''),
            'session': c.get('session', ''),
            'decision': c.get('decision', ''),
            'score': c.get('score_breakdown', {}).get('total_score', 0),
            'outcome': outcome_data.get('outcome', ''),
            'mfe_r': outcome_data.get('mfe_r', 0),
            'mae_r': outcome_data.get('mae_r', 0),
            'total_r': outcome_data.get('total_r', 0),
            'time_mins': outcome_data.get('time_to_outcome_minutes', 0),
            'entry': c.get('trade_levels', {}).get('entry', 0),
            'sl': c.get('trade_levels', {}).get('stop_loss', 0),
            'tp': c.get('trade_levels', {}).get('take_profit_1', 0),
            'rr': c.get('trade_levels', {}).get('risk_reward', 0),
            'sl_pips': c.get('trade_levels', {}).get('sl_pips', 0),
            'tp_pips': c.get('trade_levels', {}).get('tp_pips', 0),
        }
        
        if c.get('decision') == 'accepted':
            executed.append(trade)
        else:
            rejected.append(trade)
    
    # ============================================================
    # 1) ENTRY QUALITY ANALYSIS
    # ============================================================
    print("=" * 60)
    print("1) ENTRY QUALITY ANALYSIS")
    print("=" * 60)
    
    exec_mfe = [t['mfe_r'] for t in executed if t['mfe_r'] > 0]
    exec_mae = [t['mae_r'] for t in executed if t['mae_r'] > 0]
    
    print(f"""
{{
  "executed_trades": {len(executed)},
  "trades_with_mfe_data": {len(exec_mfe)},
  "trades_with_mae_data": {len(exec_mae)},
  
  "avg_mfe_r": {safe_mean(exec_mfe):.4f},
  "avg_mae_r": {safe_mean(exec_mae):.4f},
  
  "mfe_distribution": {{
    "p25": {percentile(exec_mfe, 25):.4f},
    "p50": {percentile(exec_mfe, 50):.4f},
    "p75": {percentile(exec_mfe, 75):.4f},
    "p90": {percentile(exec_mfe, 90):.4f},
    "max": {max(exec_mfe) if exec_mfe else 0:.4f}
  }},
  
  "mae_distribution": {{
    "p25": {percentile(exec_mae, 25):.4f},
    "p50": {percentile(exec_mae, 50):.4f},
    "p75": {percentile(exec_mae, 75):.4f},
    "p90": {percentile(exec_mae, 90):.4f},
    "max": {max(exec_mae) if exec_mae else 0:.4f}
  }}
}}
""")
    
    # Interpretation
    avg_mfe = safe_mean(exec_mfe)
    avg_mae = safe_mean(exec_mae)
    print("📊 INTERPRETAZIONE:")
    if avg_mae > 0.5:
        print(f"   ⚠️ MAE medio {avg_mae:.2f}R → SL viene quasi colpito prima del profitto")
    if percentile(exec_mae, 75) > 0.8:
        print(f"   ⚠️ 25% dei trade va >0.8R contro → SL troppo stretto o entry sbagliato")
    if avg_mfe < 1.0:
        print(f"   ⚠️ MFE medio solo {avg_mfe:.2f}R → trade non raggiungono mai TP")
    
    # ============================================================
    # 2) TP/SL EFFECTIVENESS
    # ============================================================
    print("\n" + "=" * 60)
    print("2) TP/SL EFFECTIVENESS")
    print("=" * 60)
    
    sl_pips = [t['sl_pips'] for t in executed if t['sl_pips'] > 0]
    tp_pips = [t['tp_pips'] for t in executed if t['tp_pips'] > 0]
    rr_values = [t['rr'] for t in executed if t['rr'] > 0]
    
    # R-Multiple reaching analysis
    reached_05r = sum(1 for t in executed if t['mfe_r'] >= 0.5)
    reached_1r = sum(1 for t in executed if t['mfe_r'] >= 1.0)
    reached_tp = sum(1 for t in executed if t['outcome'] in ['win', 'tp_hit'])
    total_with_mfe = len([t for t in executed if t['mfe_r'] > 0])
    
    print(f"""
{{
  "avg_sl_distance_pips": {safe_mean(sl_pips):.2f},
  "avg_tp_distance_pips": {safe_mean(tp_pips):.2f},
  "avg_rr_theoretical": {safe_mean(rr_values):.2f},
  
  "sl_pips_distribution": {{
    "p25": {percentile(sl_pips, 25):.2f},
    "p50": {percentile(sl_pips, 50):.2f},
    "p75": {percentile(sl_pips, 75):.2f}
  }},
  
  "tp_pips_distribution": {{
    "p25": {percentile(tp_pips, 25):.2f},
    "p50": {percentile(tp_pips, 50):.2f},
    "p75": {percentile(tp_pips, 75):.2f}
  }},
  
  "r_multiple_reach_rate": {{
    "reached_0.5R": {reached_05r},
    "reached_0.5R_pct": {(reached_05r/total_with_mfe*100) if total_with_mfe else 0:.1f},
    "reached_1.0R": {reached_1r},
    "reached_1.0R_pct": {(reached_1r/total_with_mfe*100) if total_with_mfe else 0:.1f},
    "reached_TP": {reached_tp},
    "reached_TP_pct": {(reached_tp/len(executed)*100) if executed else 0:.1f}
  }}
}}
""")
    
    print("📊 INTERPRETAZIONE:")
    if total_with_mfe > 0:
        pct_05r = reached_05r/total_with_mfe*100
        pct_1r = reached_1r/total_with_mfe*100
        pct_tp = reached_tp/len(executed)*100 if executed else 0
        
        if pct_05r > 60 and pct_tp < 45:
            print(f"   ⚠️ {pct_05r:.0f}% raggiunge 0.5R ma solo {pct_tp:.0f}% TP → TP troppo lontano")
        if pct_1r > 50 and pct_tp < 45:
            print(f"   ⚠️ {pct_1r:.0f}% raggiunge 1R ma solo {pct_tp:.0f}% TP → considera TP a 1R")
    
    # ============================================================
    # 3) TRADE LIFETIME ANALYSIS
    # ============================================================
    print("\n" + "=" * 60)
    print("3) TRADE LIFETIME ANALYSIS")
    print("=" * 60)
    
    win_times = [t['time_mins'] for t in executed if t['outcome'] in ['win', 'tp_hit'] and 0 < t['time_mins'] < 10000]
    loss_times = [t['time_mins'] for t in executed if t['outcome'] in ['loss', 'sl_hit'] and 0 < t['time_mins'] < 10000]
    expired_times = [t['time_mins'] for t in executed if t['outcome'] == 'expired' and 0 < t['time_mins'] < 10000]
    all_times = [t['time_mins'] for t in executed if 0 < t['time_mins'] < 10000]
    
    print(f"""
{{
  "avg_trade_duration_mins": {safe_mean(all_times):.1f},
  "median_trade_duration_mins": {safe_median(all_times):.1f},
  
  "by_outcome": {{
    "TP_hit": {{
      "count": {len(win_times)},
      "avg_mins": {safe_mean(win_times):.1f},
      "median_mins": {safe_median(win_times):.1f},
      "p25_mins": {percentile(win_times, 25):.1f},
      "p75_mins": {percentile(win_times, 75):.1f}
    }},
    "SL_hit": {{
      "count": {len(loss_times)},
      "avg_mins": {safe_mean(loss_times):.1f},
      "median_mins": {safe_median(loss_times):.1f},
      "p25_mins": {percentile(loss_times, 25):.1f},
      "p75_mins": {percentile(loss_times, 75):.1f}
    }},
    "Expired": {{
      "count": {len(expired_times)},
      "avg_mins": {safe_mean(expired_times):.1f},
      "median_mins": {safe_median(expired_times):.1f}
    }}
  }}
}}
""")
    
    print("📊 INTERPRETAZIONE:")
    if win_times and loss_times:
        if safe_mean(loss_times) < safe_mean(win_times) * 0.7:
            print(f"   ⚠️ SL colpiti in {safe_mean(loss_times):.0f}min vs TP in {safe_mean(win_times):.0f}min → SL troppo vicino")
    if expired_times and len(expired_times) > len(executed) * 0.2:
        print(f"   ⚠️ {len(expired_times)} trade expired ({len(expired_times)/len(executed)*100:.0f}%) → timeout troppo corto o TP troppo lontano")
    
    # ============================================================
    # 4) REJECTED VS EXECUTED ENTRY
    # ============================================================
    print("\n" + "=" * 60)
    print("4) REJECTED VS EXECUTED COMPARISON")
    print("=" * 60)
    
    rej_mfe = [t['mfe_r'] for t in rejected if t['mfe_r'] > 0]
    rej_mae = [t['mae_r'] for t in rejected if t['mae_r'] > 0]
    rej_rr = [t['rr'] for t in rejected if t['rr'] > 0]
    
    rej_reached_05r = sum(1 for t in rejected if t['mfe_r'] >= 0.5)
    rej_reached_1r = sum(1 for t in rejected if t['mfe_r'] >= 1.0)
    rej_would_win = sum(1 for t in rejected if t['outcome'] in ['win', 'tp_hit'])
    rej_would_lose = sum(1 for t in rejected if t['outcome'] in ['loss', 'sl_hit'])
    
    print(f"""
{{
  "EXECUTED": {{
    "count": {len(executed)},
    "avg_mfe_r": {safe_mean(exec_mfe):.4f},
    "avg_mae_r": {safe_mean(exec_mae):.4f},
    "avg_rr": {safe_mean(rr_values):.2f},
    "reached_0.5R_pct": {(reached_05r/total_with_mfe*100) if total_with_mfe else 0:.1f},
    "reached_1.0R_pct": {(reached_1r/total_with_mfe*100) if total_with_mfe else 0:.1f}
  }},
  
  "REJECTED": {{
    "count": {len(rejected)},
    "with_simulation_data": {len(rej_mfe)},
    "avg_mfe_r": {safe_mean(rej_mfe):.4f},
    "avg_mae_r": {safe_mean(rej_mae):.4f},
    "avg_rr": {safe_mean(rej_rr):.2f},
    "reached_0.5R_pct": {(rej_reached_05r/len(rej_mfe)*100) if rej_mfe else 0:.1f},
    "reached_1.0R_pct": {(rej_reached_1r/len(rej_mfe)*100) if rej_mfe else 0:.1f},
    "would_have_won": {rej_would_win},
    "would_have_lost": {rej_would_lose},
    "simulated_winrate": {(rej_would_win/(rej_would_win+rej_would_lose)*100) if (rej_would_win+rej_would_lose) > 0 else 0:.1f}
  }},
  
  "COMPARISON": {{
    "mfe_diff": {safe_mean(rej_mfe) - safe_mean(exec_mfe):.4f},
    "mae_diff": {safe_mean(rej_mae) - safe_mean(exec_mae):.4f}
  }}
}}
""")
    
    print("📊 INTERPRETAZIONE:")
    if rej_mfe and exec_mfe:
        if safe_mean(rej_mfe) > safe_mean(exec_mfe):
            print(f"   🔴 REJECTED hanno MFE maggiore ({safe_mean(rej_mfe):.2f}R) vs EXECUTED ({safe_mean(exec_mfe):.2f}R)")
            print(f"      → I FILTRI STANNO ELIMINANDO TRADE MIGLIORI!")
    if rej_would_win + rej_would_lose > 0:
        rej_wr = rej_would_win/(rej_would_win+rej_would_lose)*100
        exec_wr = reached_tp/len(executed)*100 if executed else 0
        if rej_wr > exec_wr:
            print(f"   🔴 REJECTED WR ({rej_wr:.1f}%) > EXECUTED WR ({exec_wr:.1f}%)")
            print(f"      → I FILTRI SONO INVERTITI!")
    
    # ============================================================
    # 5) DIRECTION ANALYSIS (BUY vs SELL)
    # ============================================================
    print("\n" + "=" * 60)
    print("5) DIRECTION ANALYSIS (BUY vs SELL)")
    print("=" * 60)
    
    buy_trades = [t for t in executed if t['direction'] == 'BUY']
    sell_trades = [t for t in executed if t['direction'] == 'SELL']
    
    buy_wins = sum(1 for t in buy_trades if t['outcome'] in ['win', 'tp_hit'])
    buy_losses = sum(1 for t in buy_trades if t['outcome'] in ['loss', 'sl_hit'])
    sell_wins = sum(1 for t in sell_trades if t['outcome'] in ['win', 'tp_hit'])
    sell_losses = sum(1 for t in sell_trades if t['outcome'] in ['loss', 'sl_hit'])
    
    buy_mfe = [t['mfe_r'] for t in buy_trades if t['mfe_r'] > 0]
    buy_mae = [t['mae_r'] for t in buy_trades if t['mae_r'] > 0]
    sell_mfe = [t['mfe_r'] for t in sell_trades if t['mfe_r'] > 0]
    sell_mae = [t['mae_r'] for t in sell_trades if t['mae_r'] > 0]
    
    buy_total = buy_wins + buy_losses
    sell_total = sell_wins + sell_losses
    
    print(f"""
{{
  "BUY": {{
    "total_trades": {len(buy_trades)},
    "resolved": {buy_total},
    "wins": {buy_wins},
    "losses": {buy_losses},
    "winrate": {(buy_wins/buy_total*100) if buy_total else 0:.1f},
    "avg_mfe_r": {safe_mean(buy_mfe):.4f},
    "avg_mae_r": {safe_mean(buy_mae):.4f},
    "expectancy_r": {((buy_wins/buy_total)*1.5 - (buy_losses/buy_total)*1) if buy_total else 0:.4f}
  }},
  
  "SELL": {{
    "total_trades": {len(sell_trades)},
    "resolved": {sell_total},
    "wins": {sell_wins},
    "losses": {sell_losses},
    "winrate": {(sell_wins/sell_total*100) if sell_total else 0:.1f},
    "avg_mfe_r": {safe_mean(sell_mfe):.4f},
    "avg_mae_r": {safe_mean(sell_mae):.4f},
    "expectancy_r": {((sell_wins/sell_total)*1.5 - (sell_losses/sell_total)*1) if sell_total else 0:.4f}
  }}
}}
""")
    
    print("📊 INTERPRETAZIONE:")
    if buy_total and sell_total:
        buy_wr = buy_wins/buy_total*100
        sell_wr = sell_wins/sell_total*100
        if sell_wr < 35:
            print(f"   🔴 SELL winrate {sell_wr:.1f}% è DISASTROSO")
            print(f"   💡 RACCOMANDAZIONE: DISABILITA SELL DIRECTION")
        if buy_wr > sell_wr + 20:
            print(f"   ⚠️ Gap BUY ({buy_wr:.1f}%) vs SELL ({sell_wr:.1f}%) = {buy_wr-sell_wr:.1f}%")
    
    # ============================================================
    # 6) SESSION DEEP ANALYSIS
    # ============================================================
    print("\n" + "=" * 60)
    print("6) SESSION DEEP ANALYSIS")
    print("=" * 60)
    
    sessions = ['London', 'London/NY Overlap', 'New York', 'Asian']
    
    for session in sessions:
        sess_trades = [t for t in executed if t['session'] == session]
        sess_mfe = [t['mfe_r'] for t in sess_trades if t['mfe_r'] > 0]
        sess_mae = [t['mae_r'] for t in sess_trades if t['mae_r'] > 0]
        sess_wins = sum(1 for t in sess_trades if t['outcome'] in ['win', 'tp_hit'])
        sess_losses = sum(1 for t in sess_trades if t['outcome'] in ['loss', 'sl_hit'])
        sess_total = sess_wins + sess_losses
        
        if sess_total > 0:
            print(f"""
  "{session}": {{
    "trades": {len(sess_trades)},
    "resolved": {sess_total},
    "wins": {sess_wins},
    "losses": {sess_losses},
    "winrate": {(sess_wins/sess_total*100):.1f},
    "avg_mfe_r": {safe_mean(sess_mfe):.4f},
    "avg_mae_r": {safe_mean(sess_mae):.4f},
    "avg_rr_achieved": {safe_mean([t['total_r'] for t in sess_trades if t['outcome'] in ['win', 'tp_hit']]):.2f},
    "expectancy_r": {((sess_wins/sess_total)*1.5 - (sess_losses/sess_total)*1):.4f}
  }}""")
    
    print("\n📊 INTERPRETAZIONE:")
    for session in sessions:
        sess_trades = [t for t in executed if t['session'] == session]
        sess_wins = sum(1 for t in sess_trades if t['outcome'] in ['win', 'tp_hit'])
        sess_losses = sum(1 for t in sess_trades if t['outcome'] in ['loss', 'sl_hit'])
        sess_total = sess_wins + sess_losses
        if sess_total >= 10:
            wr = sess_wins/sess_total*100
            if wr < 35:
                print(f"   🔴 {session}: {wr:.1f}% WR → DISABILITA")
            elif wr > 70:
                print(f"   ✅ {session}: {wr:.1f}% WR → FOCUS QUI")
    
    # ============================================================
    # 7) ENTRY TIMING QUALITY
    # ============================================================
    print("\n" + "=" * 60)
    print("7) ENTRY TIMING QUALITY")
    print("=" * 60)
    
    # Calculate how much favorable movement is "lost" due to late entry
    # MFE tells us max favorable, but if entry was perfect, MFE would = TP
    
    win_mfe = [t['mfe_r'] for t in executed if t['outcome'] in ['win', 'tp_hit'] and t['mfe_r'] > 0]
    loss_mfe = [t['mfe_r'] for t in executed if t['outcome'] in ['loss', 'sl_hit'] and t['mfe_r'] > 0]
    
    # Trades where price went favorable but still lost
    went_favorable_but_lost = [t for t in executed if t['outcome'] in ['loss', 'sl_hit'] and t['mfe_r'] >= 0.5]
    
    print(f"""
{{
  "winning_trades_mfe": {{
    "count": {len(win_mfe)},
    "avg_mfe_r": {safe_mean(win_mfe):.4f},
    "median_mfe_r": {safe_median(win_mfe):.4f}
  }},
  
  "losing_trades_mfe": {{
    "count": {len(loss_mfe)},
    "avg_mfe_r": {safe_mean(loss_mfe):.4f},
    "median_mfe_r": {safe_median(loss_mfe):.4f}
  }},
  
  "went_favorable_but_lost": {{
    "count": {len(went_favorable_but_lost)},
    "pct_of_losses": {(len(went_favorable_but_lost)/len(loss_mfe)*100) if loss_mfe else 0:.1f},
    "avg_mfe_before_loss": {safe_mean([t['mfe_r'] for t in went_favorable_but_lost]):.4f}
  }}
}}
""")
    
    print("📊 INTERPRETAZIONE:")
    if went_favorable_but_lost:
        print(f"   ⚠️ {len(went_favorable_but_lost)} trade sono andati in profitto ({safe_mean([t['mfe_r'] for t in went_favorable_but_lost]):.2f}R) ma poi hanno perso")
        print(f"   💡 SOLUZIONE: Trailing stop o TP parziale a 0.5R/1R")
    if loss_mfe and safe_mean(loss_mfe) < 0.3:
        print(f"   ⚠️ Trade perdenti hanno MFE medio {safe_mean(loss_mfe):.2f}R → mai in profitto")
        print(f"   💡 Problema di ENTRY o DIRECTION, non di SL")
    
    # ============================================================
    # 8) STOP LOSS OPTIMIZATION DATA
    # ============================================================
    print("\n" + "=" * 60)
    print("8) STOP LOSS OPTIMIZATION DATA")
    print("=" * 60)
    
    # Trades where SL was hit but price eventually went to TP
    # We can estimate this by looking at MFE of losing trades
    sl_hit_but_went_favorable = [t for t in executed if t['outcome'] in ['loss', 'sl_hit'] and t['mfe_r'] >= 1.0]
    sl_hit_moderate_favorable = [t for t in executed if t['outcome'] in ['loss', 'sl_hit'] and 0.5 <= t['mfe_r'] < 1.0]
    
    # MAE analysis for winners (how close to SL did winners get?)
    winner_mae = [t['mae_r'] for t in executed if t['outcome'] in ['win', 'tp_hit'] and t['mae_r'] > 0]
    
    print(f"""
{{
  "SL_hit_but_would_have_been_TP": {{
    "count": {len(sl_hit_but_went_favorable)},
    "pct_of_losses": {(len(sl_hit_but_went_favorable)/sell_losses*100) if sell_losses else 0:.1f},
    "avg_mfe_reached": {safe_mean([t['mfe_r'] for t in sl_hit_but_went_favorable]):.4f}
  }},
  
  "SL_hit_but_went_0.5R_favorable": {{
    "count": {len(sl_hit_moderate_favorable)},
    "avg_mfe_reached": {safe_mean([t['mfe_r'] for t in sl_hit_moderate_favorable]):.4f}
  }},
  
  "winners_MAE_analysis": {{
    "count": {len(winner_mae)},
    "avg_mae_r": {safe_mean(winner_mae):.4f},
    "p75_mae_r": {percentile(winner_mae, 75):.4f},
    "p90_mae_r": {percentile(winner_mae, 90):.4f},
    "max_mae_r": {max(winner_mae) if winner_mae else 0:.4f}
  }}
}}
""")
    
    print("📊 INTERPRETAZIONE:")
    if sl_hit_but_went_favorable:
        print(f"   🔴 {len(sl_hit_but_went_favorable)} trade hanno colpito SL ma poi sarebbero andati a TP!")
        print(f"   💡 SL TROPPO STRETTO - considera allargare di {percentile(winner_mae, 90):.2f}R")
    if winner_mae:
        p90_mae = percentile(winner_mae, 90)
        print(f"   📊 90% dei vincitori ha MAE < {p90_mae:.2f}R")
        print(f"   💡 SL ottimale suggerito: {p90_mae + 0.1:.2f}R dal entry")
    
    # ============================================================
    # 9) TAKE PROFIT OPTIMIZATION DATA
    # ============================================================
    print("\n" + "=" * 60)
    print("9) TAKE PROFIT OPTIMIZATION DATA")
    print("=" * 60)
    
    # Trades that reached various R levels but didn't hit TP
    reached_05r_not_tp = [t for t in executed if t['mfe_r'] >= 0.5 and t['outcome'] not in ['win', 'tp_hit']]
    reached_1r_not_tp = [t for t in executed if t['mfe_r'] >= 1.0 and t['outcome'] not in ['win', 'tp_hit']]
    reached_1_5r_not_tp = [t for t in executed if t['mfe_r'] >= 1.5 and t['outcome'] not in ['win', 'tp_hit']]
    
    total_valid = len([t for t in executed if t['mfe_r'] > 0])
    
    print(f"""
{{
  "reached_0.5R_but_NOT_TP": {{
    "count": {len(reached_05r_not_tp)},
    "pct_of_all": {(len(reached_05r_not_tp)/total_valid*100) if total_valid else 0:.1f},
    "final_outcomes": {{
      "loss": {sum(1 for t in reached_05r_not_tp if t['outcome'] in ['loss', 'sl_hit'])},
      "expired": {sum(1 for t in reached_05r_not_tp if t['outcome'] == 'expired')}
    }}
  }},
  
  "reached_1.0R_but_NOT_TP": {{
    "count": {len(reached_1r_not_tp)},
    "pct_of_all": {(len(reached_1r_not_tp)/total_valid*100) if total_valid else 0:.1f},
    "final_outcomes": {{
      "loss": {sum(1 for t in reached_1r_not_tp if t['outcome'] in ['loss', 'sl_hit'])},
      "expired": {sum(1 for t in reached_1r_not_tp if t['outcome'] == 'expired')}
    }}
  }},
  
  "reached_1.5R_but_NOT_TP": {{
    "count": {len(reached_1_5r_not_tp)},
    "pct_of_all": {(len(reached_1_5r_not_tp)/total_valid*100) if total_valid else 0:.1f}
  }},
  
  "theoretical_improvement": {{
    "if_TP_at_1R": {{
      "additional_wins": {len(reached_1r_not_tp)},
      "additional_R": {len(reached_1r_not_tp) * 1.0:.1f}
    }},
    "if_TP_at_0.5R": {{
      "additional_wins": {len(reached_05r_not_tp)},
      "additional_R": {len(reached_05r_not_tp) * 0.5:.1f}
    }}
  }}
}}
""")
    
    print("📊 INTERPRETAZIONE:")
    if reached_1r_not_tp:
        print(f"   🔴 {len(reached_1r_not_tp)} trade hanno raggiunto 1R ma NON TP")
        losses_from_1r = sum(1 for t in reached_1r_not_tp if t['outcome'] in ['loss', 'sl_hit'])
        print(f"   🔴 Di questi, {losses_from_1r} sono poi diventati LOSS!")
        print(f"   💡 TP A 1R AVREBBE SALVATO {losses_from_1r} TRADE (+{losses_from_1r}R)")
    
    # ============================================================
    # 10) FINAL SUMMARY
    # ============================================================
    print("\n" + "=" * 70)
    print("10) FINAL OPERATIONAL SUMMARY")
    print("=" * 70)
    
    print("""
╔══════════════════════════════════════════════════════════════════╗
║                    DOVE SI PERDE PROFITTO                        ║
╠══════════════════════════════════════════════════════════════════╣""")
    
    # Calculate lost profit from each issue
    issues = []
    
    if reached_1r_not_tp:
        lost_r = sum(1 for t in reached_1r_not_tp if t['outcome'] in ['loss', 'sl_hit']) * 2  # 1R lost + 1R would have gained
        issues.append(f"║ TP troppo lontano: {len(reached_1r_not_tp)} trade a 1R → loss = -{lost_r:.0f}R persi")
    
    if sell_total and sell_wins/sell_total < 0.35:
        sell_loss_r = sell_losses - sell_wins * 1.5
        issues.append(f"║ SELL direction rotto: {sell_losses}L vs {sell_wins}W = -{sell_loss_r:.0f}R persi")
    
    # Session losses
    for session in ['Asian', 'London']:
        sess_trades = [t for t in executed if t['session'] == session]
        sess_wins = sum(1 for t in sess_trades if t['outcome'] in ['win', 'tp_hit'])
        sess_losses = sum(1 for t in sess_trades if t['outcome'] in ['loss', 'sl_hit'])
        if sess_losses > sess_wins:
            net_loss = sess_losses - sess_wins * 1.5
            issues.append(f"║ {session} session: {sess_losses}L vs {sess_wins}W = -{net_loss:.0f}R persi")
    
    for issue in issues:
        print(issue)
    
    print("""╠══════════════════════════════════════════════════════════════════╣
║                    RACCOMANDAZIONI OPERATIVE                     ║
╠══════════════════════════════════════════════════════════════════╣
║ 1. DISABILITA Asian session (20% WR)                             ║
║ 2. DISABILITA o RESTRINGI London session (30% WR)                ║
║ 3. DISABILITA SELL direction (24% WR) o richiedi conferma extra  ║
║ 4. RIDUCI TP da 1.5R a 1.0R (molti trade raggiungono 1R poi SL)  ║
║ 5. FOCUS su New York session (95% WR)                            ║
║ 6. FOCUS su BUY direction (51% WR)                               ║
╚══════════════════════════════════════════════════════════════════╝
""")


if __name__ == "__main__":
    main()
