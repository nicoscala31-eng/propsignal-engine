import React, { useState, useEffect } from 'react';
import { View, Text, StyleSheet, ScrollView, ActivityIndicator, TouchableOpacity } from 'react-native';
import { SafeAreaView } from 'react-native-safe-area-context';
import { useLocalSearchParams, useRouter } from 'expo-router';
import Constants from 'expo-constants';

// Get backend URL from app.json extra config (works in production builds)
const BACKEND_URL = Constants.expoConfig?.extra?.backendUrl || process.env.EXPO_PUBLIC_BACKEND_URL || 'https://eurusd-alerts.preview.emergentagent.com';

interface LifecycleEvent {
  stage: string;
  timestamp: string;
  price?: number;
  pips?: number;
  rr?: number;
  reason?: string;
}

interface SignalDetail {
  id: string;
  signal_type: 'BUY' | 'SELL' | 'NEXT';
  asset: 'EURUSD' | 'XAUUSD';
  timeframe: string;
  session: string;
  strategy_type?: string;
  market_regime: string;
  entry_price?: number;
  entry_zone_low?: number;
  entry_zone_high?: number;
  stop_loss?: number;
  take_profit_1?: number;
  take_profit_2?: number;
  risk_reward_ratio?: number;
  stop_distance_pips?: number;
  confidence_score: number;
  score_breakdown?: {
    regime_quality: number;
    structure_clarity: number;
    trend_alignment: number;
    entry_quality: number;
    stop_quality: number;
    target_quality: number;
    session_quality: number;
    volatility_quality: number;
    prop_rule_safety: number;
    total: number;
  };
  success_probability?: number;
  failure_probability?: number;
  expected_duration_minutes?: number;
  trade_horizon?: string;
  explanation?: string;
  prop_rule_safety: string;
  prop_rule_warnings: string[];
  created_at: string;
  // News risk fields
  news_risk?: boolean;
  news_event?: string;
  minutes_to_news?: number;
  // Lifecycle fields
  outcome?: string;
  outcome_price?: number;
  outcome_pips?: number;
  outcome_rr_achieved?: number;
  lifecycle_stage?: string;
  lifecycle_history?: LifecycleEvent[];
  is_resolved?: boolean;
  resolved_at?: string;
  // Live data
  live_bid?: number;
  live_ask?: number;
  data_provider?: string;
}

export default function SignalDetailScreen() {
  const { id } = useLocalSearchParams<{ id: string }>();
  const router = useRouter();
  const [signal, setSignal] = useState<SignalDetail | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    fetchSignalDetail();
  }, [id]);

  const fetchSignalDetail = async () => {
    try {
      const response = await fetch(`${BACKEND_URL}/api/signals/${id}`);
      if (response.ok) {
        const data = await response.json();
        setSignal(data);
      }
    } catch (error) {
      console.error('Error fetching signal:', error);
    } finally {
      setLoading(false);
    }
  };

  if (loading) {
    return (
      <SafeAreaView style={styles.container}>
        <ActivityIndicator size="large" color="#00ff88" style={{ marginTop: 100 }} />
      </SafeAreaView>
    );
  }

  if (!signal) {
    return (
      <SafeAreaView style={styles.container}>
        <View style={styles.errorContainer}>
          <Text style={styles.errorText}>Signal not found</Text>
          <TouchableOpacity style={styles.backButton} onPress={() => router.back()}>
            <Text style={styles.backButtonText}>Go Back</Text>
          </TouchableOpacity>
        </View>
      </SafeAreaView>
    );
  }

  const signalColor = 
    signal.signal_type === 'BUY' ? '#00ff88' : 
    signal.signal_type === 'SELL' ? '#ff3366' : '#888888';

  const getOutcomeColor = (outcome?: string) => {
    if (!outcome) return '#888888';
    if (outcome.includes('TP')) return '#00ff88';
    if (outcome === 'SL_HIT') return '#ff3366';
    if (outcome === 'INVALIDATED') return '#ffaa00';
    return '#888888';
  };

  const formatLifecycleStage = (stage?: string) => {
    if (!stage) return 'Unknown';
    return stage.replace(/_/g, ' ').replace(/\b\w/g, l => l.toUpperCase());
  };

  return (
    <SafeAreaView style={styles.container} edges={['bottom']}>
      <ScrollView style={styles.content}>
        {/* Header */}
        <View style={[styles.header, { backgroundColor: signalColor + '20' }]}>
          <Text style={styles.assetText}>{signal.asset}</Text>
          <View style={[styles.signalBadge, { backgroundColor: signalColor }]}>
            <Text style={styles.signalBadgeText}>{signal.signal_type}</Text>
          </View>
        </View>

        {/* News Risk Warning */}
        {signal.news_risk && (
          <View style={styles.newsWarning}>
            <Text style={styles.newsWarningText}>
              ⚠️ HIGH NEWS RISK: {signal.news_event}
            </Text>
            {signal.minutes_to_news && (
              <Text style={styles.newsWarningSubtext}>
                {signal.minutes_to_news > 0 
                  ? `Event in ${signal.minutes_to_news} minutes`
                  : `Event was ${Math.abs(signal.minutes_to_news)} minutes ago`}
              </Text>
            )}
          </View>
        )}

        {/* Outcome Banner (if resolved) */}
        {signal.is_resolved && signal.outcome && (
          <View style={[styles.outcomeBanner, { backgroundColor: getOutcomeColor(signal.outcome) + '20' }]}>
            <Text style={[styles.outcomeText, { color: getOutcomeColor(signal.outcome) }]}>
              {signal.outcome === 'TP1_HIT' && '✅ Take Profit 1 Hit'}
              {signal.outcome === 'TP2_HIT' && '✅ Take Profit 2 Hit'}
              {signal.outcome === 'SL_HIT' && '❌ Stop Loss Hit'}
              {signal.outcome === 'INVALIDATED' && '⚠️ Signal Invalidated'}
              {signal.outcome === 'PENDING' && '⏳ Pending'}
            </Text>
            {signal.outcome_pips !== undefined && (
              <Text style={[styles.outcomeSubtext, { color: getOutcomeColor(signal.outcome) }]}>
                {signal.outcome_pips > 0 ? '+' : ''}{signal.outcome_pips.toFixed(1)} pips 
                {signal.outcome_rr_achieved !== undefined && ` (${signal.outcome_rr_achieved > 0 ? '+' : ''}${signal.outcome_rr_achieved.toFixed(2)}R)`}
              </Text>
            )}
          </View>
        )}

        {/* Lifecycle Stage */}
        {signal.lifecycle_stage && signal.signal_type !== 'NEXT' && (
          <View style={styles.lifecycleContainer}>
            <Text style={styles.sectionTitle}>Signal Lifecycle</Text>
            <View style={styles.lifecycleStage}>
              <View style={[styles.lifecycleDot, { backgroundColor: signal.is_resolved ? getOutcomeColor(signal.outcome) : '#ffaa00' }]} />
              <Text style={styles.lifecycleText}>{formatLifecycleStage(signal.lifecycle_stage)}</Text>
            </View>
            
            {/* Lifecycle History */}
            {signal.lifecycle_history && signal.lifecycle_history.length > 0 && (
              <View style={styles.lifecycleHistory}>
                {signal.lifecycle_history.map((event, index) => (
                  <View key={index} style={styles.lifecycleEvent}>
                    <View style={styles.lifecycleEventDot} />
                    <View style={styles.lifecycleEventContent}>
                      <Text style={styles.lifecycleEventStage}>{formatLifecycleStage(event.stage)}</Text>
                      <Text style={styles.lifecycleEventTime}>
                        {new Date(event.timestamp).toLocaleString()}
                      </Text>
                      {event.price && (
                        <Text style={styles.lifecycleEventPrice}>@ {event.price}</Text>
                      )}
                    </View>
                  </View>
                ))}
              </View>
            )}
          </View>
        )}

        {/* Core Info */}
        <View style={styles.section}>
          <Text style={styles.sectionTitle}>Trade Parameters</Text>
          
          <View style={styles.infoRow}>
            <Text style={styles.infoLabel}>Entry Price</Text>
            <Text style={styles.infoValue}>{signal.entry_price?.toFixed(5) || 'N/A'}</Text>
          </View>

          <View style={styles.infoRow}>
            <Text style={styles.infoLabel}>Entry Zone</Text>
            <Text style={styles.infoValue}>
              {signal.entry_zone_low?.toFixed(5)} - {signal.entry_zone_high?.toFixed(5)}
            </Text>
          </View>

          <View style={styles.infoRow}>
            <Text style={styles.infoLabel}>Stop Loss</Text>
            <Text style={[styles.infoValue, { color: '#ff3366' }]}>
              {signal.stop_loss?.toFixed(5)}
            </Text>
          </View>

          <View style={styles.infoRow}>
            <Text style={styles.infoLabel}>Take Profit 1</Text>
            <Text style={[styles.infoValue, { color: '#00ff88' }]}>
              {signal.take_profit_1?.toFixed(5)}
            </Text>
          </View>

          <View style={styles.infoRow}>
            <Text style={styles.infoLabel}>Take Profit 2</Text>
            <Text style={[styles.infoValue, { color: '#00ff88' }]}>
              {signal.take_profit_2?.toFixed(5)}
            </Text>
          </View>

          <View style={styles.infoRow}>
            <Text style={styles.infoLabel}>Risk/Reward</Text>
            <Text style={styles.infoValue}>{signal.risk_reward_ratio?.toFixed(1)}:1</Text>
          </View>

          <View style={styles.infoRow}>
            <Text style={styles.infoLabel}>Stop Distance</Text>
            <Text style={styles.infoValue}>{signal.stop_distance_pips?.toFixed(1)} pips</Text>
          </View>
        </View>

        {/* Strategy Info */}
        <View style={styles.section}>
          <Text style={styles.sectionTitle}>Strategy Details</Text>
          
          <View style={styles.infoRow}>
            <Text style={styles.infoLabel}>Strategy</Text>
            <Text style={styles.infoValue}>
              {signal.strategy_type?.replace('_', ' ') || 'N/A'}
            </Text>
          </View>

          <View style={styles.infoRow}>
            <Text style={styles.infoLabel}>Market Regime</Text>
            <Text style={styles.infoValue}>
              {signal.market_regime.replace('_', ' ')}
            </Text>
          </View>

          <View style={styles.infoRow}>
            <Text style={styles.infoLabel}>Timeframe</Text>
            <Text style={styles.infoValue}>{signal.timeframe}</Text>
          </View>

          <View style={styles.infoRow}>
            <Text style={styles.infoLabel}>Session</Text>
            <Text style={styles.infoValue}>{signal.session}</Text>
          </View>

          <View style={styles.infoRow}>
            <Text style={styles.infoLabel}>Expected Duration</Text>
            <Text style={styles.infoValue}>
              {signal.expected_duration_minutes ? 
                `${Math.floor(signal.expected_duration_minutes / 60)}h ${signal.expected_duration_minutes % 60}m` : 
                'N/A'
              }
            </Text>
          </View>
        </View>

        {/* Probabilities */}
        <View style={styles.section}>
          <Text style={styles.sectionTitle}>Probability Analysis</Text>
          
          <View style={styles.probRow}>
            <View style={styles.probBox}>
              <Text style={styles.probLabel}>Success</Text>
              <Text style={[styles.probValue, { color: '#00ff88' }]}>
                {signal.success_probability?.toFixed(1)}%
              </Text>
            </View>
            <View style={styles.probBox}>
              <Text style={styles.probLabel}>Failure</Text>
              <Text style={[styles.probValue, { color: '#ff3366' }]}>
                {signal.failure_probability?.toFixed(1)}%
              </Text>
            </View>
          </View>
        </View>

        {/* Score Breakdown */}
        {signal.score_breakdown && (
          <View style={styles.section}>
            <Text style={styles.sectionTitle}>Quality Score: {signal.confidence_score.toFixed(0)}/100</Text>
            
            <View style={styles.scoreItem}>
              <Text style={styles.scoreLabel}>Regime Quality</Text>
              <Text style={styles.scoreValue}>{signal.score_breakdown.regime_quality.toFixed(1)}</Text>
            </View>

            <View style={styles.scoreItem}>
              <Text style={styles.scoreLabel}>Structure Clarity</Text>
              <Text style={styles.scoreValue}>{signal.score_breakdown.structure_clarity.toFixed(1)}</Text>
            </View>

            <View style={styles.scoreItem}>
              <Text style={styles.scoreLabel}>Trend Alignment</Text>
              <Text style={styles.scoreValue}>{signal.score_breakdown.trend_alignment.toFixed(1)}</Text>
            </View>

            <View style={styles.scoreItem}>
              <Text style={styles.scoreLabel}>Entry Quality</Text>
              <Text style={styles.scoreValue}>{signal.score_breakdown.entry_quality.toFixed(1)}</Text>
            </View>

            <View style={styles.scoreItem}>
              <Text style={styles.scoreLabel}>Stop Quality</Text>
              <Text style={styles.scoreValue}>{signal.score_breakdown.stop_quality.toFixed(1)}</Text>
            </View>

            <View style={styles.scoreItem}>
              <Text style={styles.scoreLabel}>Target Quality</Text>
              <Text style={styles.scoreValue}>{signal.score_breakdown.target_quality.toFixed(1)}</Text>
            </View>
          </View>
        )}

        {/* Explanation */}
        {signal.explanation && (
          <View style={styles.section}>
            <Text style={styles.sectionTitle}>Analysis</Text>
            <Text style={styles.explanationText}>{signal.explanation}</Text>
          </View>
        )}

        {/* Prop Rule Safety */}
        <View style={styles.section}>
          <Text style={styles.sectionTitle}>Prop Firm Rule Safety</Text>
          <View style={[
            styles.safetyBadge,
            {
              backgroundColor: 
                signal.prop_rule_safety === 'SAFE' ? '#00ff8820' :
                signal.prop_rule_safety === 'CAUTION' ? '#ffaa0020' : '#ff336620'
            }
          ]}>
            <Text style={[
              styles.safetyText,
              {
                color: 
                  signal.prop_rule_safety === 'SAFE' ? '#00ff88' :
                  signal.prop_rule_safety === 'CAUTION' ? '#ffaa00' : '#ff3366'
              }
            ]}>
              {signal.prop_rule_safety}
            </Text>
          </View>

          {signal.prop_rule_warnings.length > 0 && (
            <View style={styles.warningsBox}>
              {signal.prop_rule_warnings.map((warning, index) => (
                <Text key={index} style={styles.warningText}>• {warning}</Text>
              ))}
            </View>
          )}
        </View>
      </ScrollView>
    </SafeAreaView>
  );
}

const styles = StyleSheet.create({
  container: {
    flex: 1,
    backgroundColor: '#0a0a0a',
  },
  content: {
    flex: 1,
  },
  header: {
    padding: 24,
    flexDirection: 'row',
    justifyContent: 'space-between',
    alignItems: 'center',
    borderBottomWidth: 1,
    borderBottomColor: '#222222',
  },
  assetText: {
    fontSize: 32,
    fontWeight: 'bold',
    color: '#ffffff',
  },
  signalBadge: {
    paddingHorizontal: 16,
    paddingVertical: 8,
    borderRadius: 8,
  },
  signalBadgeText: {
    color: '#0a0a0a',
    fontWeight: 'bold',
    fontSize: 18,
  },
  section: {
    padding: 20,
    borderBottomWidth: 1,
    borderBottomColor: '#222222',
  },
  sectionTitle: {
    fontSize: 18,
    fontWeight: 'bold',
    color: '#00ff88',
    marginBottom: 16,
  },
  infoRow: {
    flexDirection: 'row',
    justifyContent: 'space-between',
    marginBottom: 12,
  },
  infoLabel: {
    color: '#888888',
    fontSize: 14,
  },
  infoValue: {
    color: '#ffffff',
    fontSize: 16,
    fontWeight: '600',
  },
  probRow: {
    flexDirection: 'row',
    gap: 12,
  },
  probBox: {
    flex: 1,
    backgroundColor: '#111111',
    padding: 16,
    borderRadius: 8,
    alignItems: 'center',
  },
  probLabel: {
    color: '#888888',
    fontSize: 12,
    marginBottom: 8,
  },
  probValue: {
    fontSize: 24,
    fontWeight: 'bold',
  },
  scoreItem: {
    flexDirection: 'row',
    justifyContent: 'space-between',
    marginBottom: 8,
    paddingVertical: 4,
  },
  scoreLabel: {
    color: '#cccccc',
    fontSize: 14,
  },
  scoreValue: {
    color: '#00ff88',
    fontSize: 14,
    fontWeight: '600',
  },
  explanationText: {
    color: '#cccccc',
    fontSize: 15,
    lineHeight: 22,
  },
  safetyBadge: {
    padding: 16,
    borderRadius: 8,
    alignItems: 'center',
  },
  safetyText: {
    fontSize: 20,
    fontWeight: 'bold',
  },
  warningsBox: {
    marginTop: 12,
    backgroundColor: '#1a1a1a',
    padding: 12,
    borderRadius: 8,
  },
  warningText: {
    color: '#ffaa00',
    fontSize: 13,
    marginBottom: 4,
  },
  errorContainer: {
    flex: 1,
    justifyContent: 'center',
    alignItems: 'center',
    padding: 20,
  },
  errorText: {
    color: '#ff3366',
    fontSize: 16,
    textAlign: 'center',
    marginBottom: 20,
  },
  backButton: {
    backgroundColor: '#222222',
    paddingHorizontal: 24,
    paddingVertical: 12,
    borderRadius: 8,
  },
  backButtonText: {
    color: '#00ff88',
    fontSize: 16,
    fontWeight: '600',
  },
  newsWarning: {
    backgroundColor: 'rgba(255, 170, 0, 0.15)',
    borderWidth: 1,
    borderColor: '#ffaa00',
    padding: 16,
    marginHorizontal: 16,
    marginTop: 16,
    borderRadius: 8,
  },
  newsWarningText: {
    color: '#ffaa00',
    fontSize: 16,
    fontWeight: 'bold',
    textAlign: 'center',
  },
  newsWarningSubtext: {
    color: '#ffaa00',
    fontSize: 12,
    textAlign: 'center',
    marginTop: 4,
  },
  outcomeBanner: {
    padding: 16,
    marginHorizontal: 16,
    marginTop: 16,
    borderRadius: 8,
    alignItems: 'center',
  },
  outcomeText: {
    fontSize: 18,
    fontWeight: 'bold',
  },
  outcomeSubtext: {
    fontSize: 14,
    marginTop: 4,
  },
  lifecycleContainer: {
    padding: 20,
    borderBottomWidth: 1,
    borderBottomColor: '#222222',
  },
  lifecycleStage: {
    flexDirection: 'row',
    alignItems: 'center',
    marginBottom: 16,
  },
  lifecycleDot: {
    width: 12,
    height: 12,
    borderRadius: 6,
    marginRight: 8,
  },
  lifecycleText: {
    color: '#ffffff',
    fontSize: 16,
    fontWeight: '600',
  },
  lifecycleHistory: {
    borderLeftWidth: 2,
    borderLeftColor: '#333333',
    marginLeft: 5,
    paddingLeft: 20,
  },
  lifecycleEvent: {
    flexDirection: 'row',
    marginBottom: 12,
    position: 'relative',
  },
  lifecycleEventDot: {
    width: 8,
    height: 8,
    borderRadius: 4,
    backgroundColor: '#555555',
    position: 'absolute',
    left: -24,
    top: 4,
  },
  lifecycleEventContent: {
    flex: 1,
  },
  lifecycleEventStage: {
    color: '#ffffff',
    fontSize: 14,
    fontWeight: '500',
  },
  lifecycleEventTime: {
    color: '#666666',
    fontSize: 11,
    marginTop: 2,
  },
  lifecycleEventPrice: {
    color: '#00ff88',
    fontSize: 12,
    marginTop: 2,
  },
});
