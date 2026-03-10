import React, { useState, useEffect } from 'react';
import { View, Text, StyleSheet, ScrollView, ActivityIndicator } from 'react-native';
import { SafeAreaView } from 'react-native-safe-area-context';
import { useLocalSearchParams } from 'expo-router';

const BACKEND_URL = process.env.EXPO_PUBLIC_BACKEND_URL;

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
}

export default function SignalDetailScreen() {
  const { id } = useLocalSearchParams<{ id: string }>();
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
        <Text style={styles.errorText}>Signal not found</Text>
      </SafeAreaView>
    );
  }

  const signalColor = 
    signal.signal_type === 'BUY' ? '#00ff88' : 
    signal.signal_type === 'SELL' ? '#ff3366' : '#888888';

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
  errorText: {
    color: '#ff3366',
    fontSize: 16,
    textAlign: 'center',
    marginTop: 100,
  },
});
