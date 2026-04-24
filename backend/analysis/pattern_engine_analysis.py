#!/usr/bin/env python3
"""
PATTERN ENGINE V3.0 - DEEP ANALYSIS
====================================
Analisi completa e oggettiva per identificare:
- Errori sistemici
- Illusioni di performance
- Edge reale vs illusorio
"""

import json
import os
from collections import defaultdict
from datetime import datetime
from typing import Dict, List, Any, Tuple
import statistics

# Paths
DATA_DIR = "/app/backend/data"
STORAGE_DIR = "/app/backend/storage"

def load_json(filepath: str) -> Any:
    """Load JSON file safely"""
    try:
        with open(filepath, 'r') as f:
            return json.load(f)
    except Exception as e:
        print(f"Error loading {filepath}: {e}")
        return None

def safe_div(a: float, b: float, default: float = 0) -> float:
    """Safe division"""
    return a / b if b != 0 else default

class PatternEngineAnalyzer:
    def __init__(self):
        self.signal_stats = load_json(f"{DATA_DIR}/signal_stats.json") or {}
        self.tracked_signals = load_json(f"{DATA_DIR}/tracked_signals.json") or []
        self.candidate_audit = load_json(f"{DATA_DIR}/candidate_audit.json") or {}
        self.signal_snapshots = load_json(f"{DATA_DIR}/signal_snapshots.json") or {}
        self.missed_opportunities = load_json(f"{STORAGE_DIR}/missed_opportunities.json") or {}
        self.direction_audit = load_json(f"{STORAGE_DIR}/direction_quality_audit.json") or {}
        self.direction_rejections = load_json(f"{STORAGE_DIR}/direction_rejections.json") or {}
        
        # Extract data
        self.candidates = self.candidate_audit.get('candidates', []) if isinstance(self.candidate_audit, dict) else []
        self.snapshots = self.signal_snapshots.get('snapshots', []) if isinstance(self.signal_snapshots, dict) else []
        self.missed_records = self.missed_opportunities.get('records', []) if isinstance(self.missed_opportunities, dict) else []
        
    def analyze_all(self) -> Dict:
        """Run complete analysis"""
        report = {
            "generated_at": datetime.utcnow().isoformat(),
            "data_summary": self._data_summary(),
            "edge_analysis": self._edge_analysis(),
            "filter_analysis": self._filter_analysis(),
            "session_analysis": self._session_analysis(),
            "confidence_analysis": self._confidence_analysis(),
            "asset_analysis": self._asset_analysis(),
            "rejected_analysis": self._rejected_analysis(),
            "factor_analysis": self._factor_analysis(),
            "stability_analysis": self._stability_analysis(),
            "systematic_errors": self._systematic_errors(),
            "final_ranking": self._final_ranking(),
            "recommendations": self._recommendations()
        }
        return report
    
    def _data_summary(self) -> Dict:
        """1. DATA COLLECTION SUMMARY"""
        stats = self.signal_stats
        
        total_tracked = stats.get('total_tracked', 0)
        wins = stats.get('wins', 0)
        losses = stats.get('losses', 0)
        expired = stats.get('expired', 0)
        
        # Calculate from candidates
        accepted = sum(1 for c in self.candidates if c.get('decision') == 'accepted')
        rejected = sum(1 for c in self.candidates if c.get('decision') == 'rejected')
        
        # Outcomes from candidates
        outcomes = defaultdict(int)
        for c in self.candidates:
            if c.get('outcome_data'):
                outcomes[c['outcome_data'].get('outcome', 'unknown')] += 1
        
        return {
            "total_signals_tracked": total_tracked,
            "wins": wins,
            "losses": losses,
            "expired": expired,
            "resolved": wins + losses,
            "winrate_overall": safe_div(wins, wins + losses) * 100,
            "candidates_analyzed": len(self.candidates),
            "accepted_candidates": accepted,
            "rejected_candidates": rejected,
            "acceptance_rate": safe_div(accepted, len(self.candidates)) * 100,
            "outcomes_distribution": dict(outcomes),
            "snapshots_count": len(self.snapshots),
            "missed_opportunities_count": len(self.missed_records)
        }
    
    def _edge_analysis(self) -> Dict:
        """2. EDGE ANALYSIS - CRITICAL"""
        # Analyze executed trades
        executed = []
        for c in self.candidates:
            if c.get('decision') == 'accepted' and c.get('outcome_data'):
                outcome = c['outcome_data']
                if outcome.get('outcome') in ['tp_hit', 'sl_hit', 'win', 'loss']:
                    executed.append({
                        'symbol': c.get('symbol'),
                        'session': c.get('session'),
                        'outcome': outcome.get('outcome'),
                        'total_r': outcome.get('total_r', 0),
                        'mfe_r': outcome.get('mfe_r', 0),
                        'mae_r': outcome.get('mae_r', 0),
                        'score': c.get('score_breakdown', {}).get('total_score', 0),
                        'rr': c.get('trade_levels', {}).get('risk_reward', 1.5)
                    })
        
        # Executed stats
        executed_wins = sum(1 for e in executed if e['outcome'] in ['tp_hit', 'win'])
        executed_losses = sum(1 for e in executed if e['outcome'] in ['sl_hit', 'loss'])
        executed_total = executed_wins + executed_losses
        
        executed_winrate = safe_div(executed_wins, executed_total) * 100
        
        # Calculate expectancy
        total_r_gained = sum(e['total_r'] for e in executed if e['outcome'] in ['tp_hit', 'win'])
        total_r_lost = sum(abs(e['total_r']) for e in executed if e['outcome'] in ['sl_hit', 'loss'])
        
        avg_win = safe_div(total_r_gained, executed_wins)
        avg_loss = safe_div(total_r_lost, executed_losses)
        
        expectancy = (executed_winrate/100 * avg_win) - ((1 - executed_winrate/100) * avg_loss)
        profit_factor = safe_div(total_r_gained, total_r_lost)
        
        # Rejected analysis (would_have_won simulation needed)
        rejected_with_sim = []
        for c in self.candidates:
            if c.get('decision') == 'rejected' and c.get('outcome_data'):
                outcome = c['outcome_data']
                if outcome.get('is_simulated') or outcome.get('outcome') in ['tp_hit', 'sl_hit']:
                    rejected_with_sim.append({
                        'outcome': outcome.get('outcome'),
                        'total_r': outcome.get('total_r', 0),
                        'rejection_reason': c.get('rejection_reason', ''),
                        'score': c.get('score_breakdown', {}).get('total_score', 0)
                    })
        
        rejected_would_win = sum(1 for r in rejected_with_sim if r['outcome'] in ['tp_hit', 'win'])
        rejected_would_lose = sum(1 for r in rejected_with_sim if r['outcome'] in ['sl_hit', 'loss'])
        rejected_total = rejected_would_win + rejected_would_lose
        
        rejected_winrate = safe_div(rejected_would_win, rejected_total) * 100 if rejected_total > 0 else None
        
        return {
            "executed_trades": executed_total,
            "executed_wins": executed_wins,
            "executed_losses": executed_losses,
            "executed_winrate": round(executed_winrate, 2),
            "avg_win_r": round(avg_win, 3),
            "avg_loss_r": round(avg_loss, 3),
            "expectancy_per_trade": round(expectancy, 4),
            "profit_factor": round(profit_factor, 3),
            "total_r_gained": round(total_r_gained, 2),
            "total_r_lost": round(total_r_lost, 2),
            "net_r": round(total_r_gained - total_r_lost, 2),
            "rejected_simulated": rejected_total,
            "rejected_would_win": rejected_would_win,
            "rejected_would_lose": rejected_would_lose,
            "rejected_winrate": round(rejected_winrate, 2) if rejected_winrate else "N/A",
            "edge_verdict": self._edge_verdict(expectancy, executed_winrate, profit_factor)
        }
    
    def _edge_verdict(self, expectancy: float, winrate: float, pf: float) -> str:
        """Determine edge quality"""
        if expectancy > 0.1 and pf > 1.2:
            return "POSITIVE EDGE - System profitable"
        elif expectancy > 0 and pf > 1:
            return "MARGINAL EDGE - Barely profitable"
        elif expectancy > -0.1:
            return "NO EDGE - Break-even or slight loss"
        else:
            return "NEGATIVE EDGE - System losing money"
    
    def _filter_analysis(self) -> Dict:
        """3. FILTER ANALYSIS"""
        filter_stats = defaultdict(lambda: {
            'blocked': 0,
            'blocked_would_win': 0,
            'blocked_would_lose': 0,
            'blocked_expired': 0
        })
        
        # Analyze rejected candidates
        for c in self.candidates:
            if c.get('decision') == 'rejected':
                reason = c.get('rejection_reason', 'unknown')
                filter_stats[reason]['blocked'] += 1
                
                if c.get('outcome_data'):
                    outcome = c['outcome_data'].get('outcome', '')
                    if outcome in ['tp_hit', 'win']:
                        filter_stats[reason]['blocked_would_win'] += 1
                    elif outcome in ['sl_hit', 'loss']:
                        filter_stats[reason]['blocked_would_lose'] += 1
                    elif outcome == 'expired':
                        filter_stats[reason]['blocked_expired'] += 1
        
        # Calculate net effect for each filter
        result = {}
        for filter_name, stats in filter_stats.items():
            wins_blocked = stats['blocked_would_win']
            losses_blocked = stats['blocked_would_lose']
            
            # Net effect: positive = good filter, negative = bad filter
            net_trades = losses_blocked - wins_blocked
            
            result[filter_name] = {
                "total_blocked": stats['blocked'],
                "would_have_won": wins_blocked,
                "would_have_lost": losses_blocked,
                "expired_blocked": stats['blocked_expired'],
                "net_effect": net_trades,
                "verdict": "GOOD FILTER" if net_trades > 0 else ("BAD FILTER - blocks winners" if net_trades < -2 else "NEUTRAL")
            }
        
        return result
    
    def _session_analysis(self) -> Dict:
        """7. SESSION ANALYSIS"""
        stats = self.signal_stats.get('by_session', {})
        
        result = {}
        for session, data in stats.items():
            wins = data.get('wins', 0)
            losses = data.get('losses', 0)
            total = wins + losses
            
            if total > 0:
                winrate = safe_div(wins, total) * 100
                # Assume 1.5 RR for estimation
                expectancy = (winrate/100 * 1.5) - ((1 - winrate/100) * 1)
                
                result[session] = {
                    "trades": total,
                    "wins": wins,
                    "losses": losses,
                    "winrate": round(winrate, 2),
                    "estimated_expectancy": round(expectancy, 3),
                    "verdict": "PROFITABLE" if expectancy > 0 else "UNPROFITABLE"
                }
        
        return result
    
    def _confidence_analysis(self) -> Dict:
        """5. CONFIDENCE/SCORE BUCKET ANALYSIS"""
        stats = self.signal_stats.get('by_confidence', {})
        
        result = {}
        for bucket, data in stats.items():
            wins = data.get('wins', 0)
            losses = data.get('losses', 0)
            total = wins + losses
            
            if total > 0:
                winrate = safe_div(wins, total) * 100
                expectancy = (winrate/100 * 1.5) - ((1 - winrate/100) * 1)
                
                result[bucket] = {
                    "trades": total,
                    "wins": wins,
                    "losses": losses,
                    "winrate": round(winrate, 2),
                    "expectancy": round(expectancy, 3),
                    "verdict": "EDGE" if expectancy > 0 else "NO EDGE"
                }
        
        return result
    
    def _asset_analysis(self) -> Dict:
        """6. ASSET ANALYSIS"""
        stats = self.signal_stats.get('by_asset', {})
        
        result = {}
        for asset, data in stats.items():
            wins = data.get('wins', 0)
            losses = data.get('losses', 0)
            expired = data.get('expired', 0)
            total = wins + losses
            
            if total > 0:
                winrate = safe_div(wins, total) * 100
                expectancy = (winrate/100 * 1.5) - ((1 - winrate/100) * 1)
                
                result[asset] = {
                    "trades": total,
                    "wins": wins,
                    "losses": losses,
                    "expired": expired,
                    "winrate": round(winrate, 2),
                    "expectancy": round(expectancy, 3),
                    "verdict": "PROFITABLE" if expectancy > 0 else "UNPROFITABLE"
                }
        
        return result
    
    def _rejected_analysis(self) -> Dict:
        """9. REJECTED ANALYSIS - THE HEART"""
        rejected = [c for c in self.candidates if c.get('decision') == 'rejected']
        
        # Group by rejection reason
        by_reason = defaultdict(list)
        for c in rejected:
            reason = c.get('rejection_reason', 'unknown')
            by_reason[reason].append(c)
        
        # Calculate would_have stats
        total_rejected = len(rejected)
        would_win = 0
        would_lose = 0
        lost_r = 0
        
        for c in rejected:
            if c.get('outcome_data'):
                outcome = c['outcome_data'].get('outcome', '')
                if outcome in ['tp_hit', 'win']:
                    would_win += 1
                    lost_r += c['outcome_data'].get('total_r', 1.5)
                elif outcome in ['sl_hit', 'loss']:
                    would_lose += 1
        
        main_issue = max(by_reason.keys(), key=lambda k: len(by_reason[k])) if by_reason else "N/A"
        
        return {
            "total_rejected": total_rejected,
            "with_simulation": would_win + would_lose,
            "would_have_won": would_win,
            "would_have_lost": would_lose,
            "would_have_winrate": round(safe_div(would_win, would_win + would_lose) * 100, 2) if (would_win + would_lose) > 0 else "N/A",
            "lost_opportunity_r": round(lost_r, 2),
            "main_rejection_reason": main_issue,
            "main_issue_count": len(by_reason.get(main_issue, [])),
            "rejection_breakdown": {k: len(v) for k, v in by_reason.items()}
        }
    
    def _factor_analysis(self) -> Dict:
        """Analyze individual factors from snapshots"""
        factor_stats = defaultdict(lambda: {
            'pass_count': 0,
            'fail_count': 0,
            'pass_wins': 0,
            'pass_losses': 0,
            'fail_wins': 0,
            'fail_losses': 0,
            'scores': []
        })
        
        for snap in self.snapshots:
            status = snap.get('status', '')
            outcome = snap.get('outcome', {})
            result = outcome.get('result', '') if outcome else ''
            
            for factor in snap.get('factor_contributions', []):
                key = factor.get('factor_key', 'unknown')
                passed = factor.get('status') == 'pass'
                score = factor.get('score_contribution', 0)
                
                factor_stats[key]['scores'].append(score)
                
                if passed:
                    factor_stats[key]['pass_count'] += 1
                    if result == 'win':
                        factor_stats[key]['pass_wins'] += 1
                    elif result == 'loss':
                        factor_stats[key]['pass_losses'] += 1
                else:
                    factor_stats[key]['fail_count'] += 1
                    if result == 'win':
                        factor_stats[key]['fail_wins'] += 1
                    elif result == 'loss':
                        factor_stats[key]['fail_losses'] += 1
        
        result = {}
        for factor, stats in factor_stats.items():
            pass_total = stats['pass_wins'] + stats['pass_losses']
            fail_total = stats['fail_wins'] + stats['fail_losses']
            
            pass_wr = safe_div(stats['pass_wins'], pass_total) * 100 if pass_total > 0 else None
            fail_wr = safe_div(stats['fail_wins'], fail_total) * 100 if fail_total > 0 else None
            
            avg_score = statistics.mean(stats['scores']) if stats['scores'] else 0
            
            result[factor] = {
                "pass_count": stats['pass_count'],
                "fail_count": stats['fail_count'],
                "pass_winrate": round(pass_wr, 2) if pass_wr else "N/A",
                "fail_winrate": round(fail_wr, 2) if fail_wr else "N/A",
                "avg_score": round(avg_score, 2),
                "predictive_value": "HIGH" if (pass_wr and fail_wr and pass_wr > fail_wr + 10) else "LOW"
            }
        
        return result
    
    def _stability_analysis(self) -> Dict:
        """10. STABILITY ANALYSIS"""
        # Compare recent vs historical performance
        if len(self.candidates) < 40:
            return {"status": "Insufficient data for stability analysis"}
        
        recent = self.candidates[-20:]
        historical = self.candidates[-40:-20]
        
        def calc_winrate(cands):
            wins = sum(1 for c in cands if c.get('outcome_data', {}).get('outcome') in ['tp_hit', 'win'])
            losses = sum(1 for c in cands if c.get('outcome_data', {}).get('outcome') in ['sl_hit', 'loss'])
            return safe_div(wins, wins + losses) * 100 if (wins + losses) > 0 else None
        
        recent_wr = calc_winrate(recent)
        historical_wr = calc_winrate(historical)
        
        variance = abs(recent_wr - historical_wr) if (recent_wr and historical_wr) else None
        
        return {
            "recent_20_winrate": round(recent_wr, 2) if recent_wr else "N/A",
            "historical_20_winrate": round(historical_wr, 2) if historical_wr else "N/A",
            "variance_pct": round(variance, 2) if variance else "N/A",
            "stability_verdict": "STABLE" if (variance and variance < 15) else ("UNSTABLE" if variance else "N/A")
        }
    
    def _systematic_errors(self) -> Dict:
        """8. SYSTEMATIC ERRORS"""
        errors = []
        
        # Check session performance
        session_stats = self.signal_stats.get('by_session', {})
        for session, data in session_stats.items():
            wins = data.get('wins', 0)
            losses = data.get('losses', 0)
            total = wins + losses
            if total >= 10:
                wr = safe_div(wins, total)
                if wr < 0.40:
                    errors.append({
                        "type": "SESSION_UNDERPERFORMANCE",
                        "detail": f"{session}: {wr*100:.1f}% winrate ({wins}W/{losses}L)",
                        "severity": "HIGH" if wr < 0.35 else "MEDIUM"
                    })
        
        # Check asset performance
        asset_stats = self.signal_stats.get('by_asset', {})
        for asset, data in asset_stats.items():
            wins = data.get('wins', 0)
            losses = data.get('losses', 0)
            total = wins + losses
            if total >= 10:
                wr = safe_div(wins, total)
                if wr < 0.40:
                    errors.append({
                        "type": "ASSET_UNDERPERFORMANCE",
                        "detail": f"{asset}: {wr*100:.1f}% winrate ({wins}W/{losses}L)",
                        "severity": "HIGH" if wr < 0.35 else "MEDIUM"
                    })
        
        # Check confidence bucket inversion
        conf_stats = self.signal_stats.get('by_confidence', {})
        high_conf = conf_stats.get('strong_80_100', {})
        low_conf = conf_stats.get('acceptable_60_69', {})
        
        high_wr = safe_div(high_conf.get('wins', 0), high_conf.get('wins', 0) + high_conf.get('losses', 0))
        low_wr = safe_div(low_conf.get('wins', 0), low_conf.get('wins', 0) + low_conf.get('losses', 0))
        
        if high_wr and low_wr and low_wr > high_wr:
            errors.append({
                "type": "CONFIDENCE_INVERSION",
                "detail": f"Low confidence ({low_wr*100:.1f}%) outperforms high confidence ({high_wr*100:.1f}%)",
                "severity": "CRITICAL"
            })
        
        # High expired rate
        total = self.signal_stats.get('total_tracked', 0)
        expired = self.signal_stats.get('expired', 0)
        if total > 0 and safe_div(expired, total) > 0.25:
            errors.append({
                "type": "HIGH_EXPIRED_RATE",
                "detail": f"{expired}/{total} trades expired ({safe_div(expired,total)*100:.1f}%)",
                "severity": "MEDIUM"
            })
        
        return {
            "errors_found": len(errors),
            "errors": errors
        }
    
    def _final_ranking(self) -> Dict:
        """11. FINAL EDGE RANKING"""
        # Session ranking
        session_ranking = []
        for session, data in self.signal_stats.get('by_session', {}).items():
            wins = data.get('wins', 0)
            losses = data.get('losses', 0)
            total = wins + losses
            if total >= 5:
                wr = safe_div(wins, total)
                exp = (wr * 1.5) - ((1-wr) * 1)
                session_ranking.append({
                    "name": session,
                    "trades": total,
                    "winrate": round(wr * 100, 2),
                    "expectancy": round(exp, 3)
                })
        
        session_ranking.sort(key=lambda x: x['expectancy'], reverse=True)
        
        # Asset ranking
        asset_ranking = []
        for asset, data in self.signal_stats.get('by_asset', {}).items():
            wins = data.get('wins', 0)
            losses = data.get('losses', 0)
            total = wins + losses
            if total >= 5:
                wr = safe_div(wins, total)
                exp = (wr * 1.5) - ((1-wr) * 1)
                asset_ranking.append({
                    "name": asset,
                    "trades": total,
                    "winrate": round(wr * 100, 2),
                    "expectancy": round(exp, 3)
                })
        
        asset_ranking.sort(key=lambda x: x['expectancy'], reverse=True)
        
        return {
            "best_sessions": session_ranking[:3],
            "worst_sessions": session_ranking[-3:] if len(session_ranking) >= 3 else session_ranking,
            "best_assets": asset_ranking[:2],
            "worst_assets": asset_ranking[-2:] if len(asset_ranking) >= 2 else asset_ranking
        }
    
    def _recommendations(self) -> List[Dict]:
        """12. RECOMMENDATIONS"""
        recommendations = []
        
        # Session recommendations
        session_stats = self.signal_stats.get('by_session', {})
        for session, data in session_stats.items():
            wins = data.get('wins', 0)
            losses = data.get('losses', 0)
            total = wins + losses
            if total >= 10:
                wr = safe_div(wins, total)
                if wr < 0.35:
                    recommendations.append({
                        "category": "SESSION",
                        "problem": f"{session} has very low winrate ({wr*100:.1f}%)",
                        "impact": f"Losing {losses - wins} net trades",
                        "solution": f"Consider removing or restricting {session} trading"
                    })
        
        # Confidence recommendations
        conf_stats = self.signal_stats.get('by_confidence', {})
        strong = conf_stats.get('strong_80_100', {})
        strong_wr = safe_div(strong.get('wins', 0), strong.get('wins', 0) + strong.get('losses', 0))
        
        if strong_wr and strong_wr < 0.35:
            recommendations.append({
                "category": "SCORING",
                "problem": f"High confidence trades underperforming ({strong_wr*100:.1f}%)",
                "impact": "Scoring system may be miscalibrated",
                "solution": "Review score weighting - high scores should correlate with wins"
            })
        
        # Asset recommendations
        asset_stats = self.signal_stats.get('by_asset', {})
        for asset, data in asset_stats.items():
            wins = data.get('wins', 0)
            losses = data.get('losses', 0)
            total = wins + losses
            if total >= 20:
                wr = safe_div(wins, total)
                if wr < 0.40:
                    recommendations.append({
                        "category": "ASSET",
                        "problem": f"{asset} underperforming ({wr*100:.1f}%)",
                        "impact": "Losing trades on this asset",
                        "solution": f"Increase quality threshold for {asset} or exclude"
                    })
        
        # Expired rate
        total = self.signal_stats.get('total_tracked', 0)
        expired = self.signal_stats.get('expired', 0)
        if total > 0 and safe_div(expired, total) > 0.25:
            recommendations.append({
                "category": "EXECUTION",
                "problem": f"High expired rate ({safe_div(expired,total)*100:.1f}%)",
                "impact": "Many trades not reaching TP or SL",
                "solution": "Review trade duration limits or TP/SL placement"
            })
        
        return recommendations


def main():
    """Run analysis and output report"""
    print("=" * 60)
    print("PATTERN ENGINE V3.0 - DEEP ANALYSIS REPORT")
    print("=" * 60)
    print()
    
    analyzer = PatternEngineAnalyzer()
    report = analyzer.analyze_all()
    
    # Print formatted report
    print("1. DATA SUMMARY")
    print("-" * 40)
    for k, v in report['data_summary'].items():
        print(f"  {k}: {v}")
    print()
    
    print("2. EDGE ANALYSIS (CRITICAL)")
    print("-" * 40)
    for k, v in report['edge_analysis'].items():
        print(f"  {k}: {v}")
    print()
    
    print("3. FILTER ANALYSIS")
    print("-" * 40)
    for filter_name, stats in report['filter_analysis'].items():
        print(f"  {filter_name}:")
        for k, v in stats.items():
            print(f"    {k}: {v}")
    print()
    
    print("4. SESSION ANALYSIS")
    print("-" * 40)
    for session, stats in report['session_analysis'].items():
        print(f"  {session}: {stats['winrate']}% WR, {stats['trades']} trades - {stats['verdict']}")
    print()
    
    print("5. CONFIDENCE BUCKET ANALYSIS")
    print("-" * 40)
    for bucket, stats in report['confidence_analysis'].items():
        print(f"  {bucket}: {stats['winrate']}% WR, {stats['trades']} trades - {stats['verdict']}")
    print()
    
    print("6. ASSET ANALYSIS")
    print("-" * 40)
    for asset, stats in report['asset_analysis'].items():
        print(f"  {asset}: {stats['winrate']}% WR, {stats['trades']} trades - {stats['verdict']}")
    print()
    
    print("7. REJECTED TRADE ANALYSIS (CORE)")
    print("-" * 40)
    for k, v in report['rejected_analysis'].items():
        print(f"  {k}: {v}")
    print()
    
    print("8. SYSTEMATIC ERRORS")
    print("-" * 40)
    errors = report['systematic_errors']
    print(f"  Errors found: {errors['errors_found']}")
    for err in errors['errors']:
        print(f"  [{err['severity']}] {err['type']}: {err['detail']}")
    print()
    
    print("9. STABILITY ANALYSIS")
    print("-" * 40)
    for k, v in report['stability_analysis'].items():
        print(f"  {k}: {v}")
    print()
    
    print("10. FINAL RANKING")
    print("-" * 40)
    ranking = report['final_ranking']
    print("  Best Sessions:", ranking['best_sessions'])
    print("  Worst Sessions:", ranking['worst_sessions'])
    print("  Best Assets:", ranking['best_assets'])
    print()
    
    print("11. RECOMMENDATIONS")
    print("-" * 40)
    for rec in report['recommendations']:
        print(f"  [{rec['category']}]")
        print(f"    Problem: {rec['problem']}")
        print(f"    Impact: {rec['impact']}")
        print(f"    Solution: {rec['solution']}")
        print()
    
    # Save full report
    output_path = f"{DATA_DIR}/pattern_analysis_report.json"
    with open(output_path, 'w') as f:
        json.dump(report, f, indent=2)
    print(f"\nFull report saved to: {output_path}")
    
    return report


if __name__ == "__main__":
    main()
