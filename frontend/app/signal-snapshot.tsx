import React, { useState, useEffect } from 'react';
import {
  View,
  Text,
  StyleSheet,
  ScrollView,
  TouchableOpacity,
  ActivityIndicator,
} from 'react-native';
import { SafeAreaView } from 'react-native-safe-area-context';
import { useLocalSearchParams, useRouter } from 'expo-router';
import { BACKEND_URL } from '../config/api';

// Types
interface FactorContribution {
  factor_key: string;
  factor_name: string;
  raw_value: number;
  normalized_value: number;
  weight_pct: number;
  score_contribution: number;
  status: string;
  reason: string;
}

interface PenaltyApplied {
  penalty_key: string;
  penalty_name: string;
  penalty_value: number;
  trigger_condition: string;
  raw_measurement: number;
  reason: string;
}

interface FilterCheck {
  filter_name: string;
  threshold: number;
  actual_value: number;
  passed: boolean;
  blocks_trade: boolean;
  reason: string;
}

// NEW: Pattern sub-component
interface PatternSubComponent {
  key: string;
  name: string;
  active: boolean;
  description: string;
}

// NEW: Pattern data for V3 engine
interface PatternData {
  active_count?: number;
  active_patterns?: string[];
  primary_pattern?: string;
  combination_key?: string;
  sub_components?: { [patternKey: string]: PatternSubComponent[] };
}

// NEW: Math Metrics from Deterministic Engine
interface MathMetrics {
  mu_t?: number;
  sigma_t?: number;
  T_t?: number;
  Z_t?: number;
  ATR_t?: number;
  range_width?: number;
  range_high?: number;
  range_low?: number;
  sl_buffer?: number;
}

interface SignalSnapshot {
  signal_id: string;
  timestamp: string;
  symbol: string;
  direction: string;
  session: string;
  setup_type: string;
  trade_levels: {
    entry: number;
    stop_loss: number;
    take_profit: number;
    rr_ratio: number;
  };
  decision: {
    status: string;
    acceptance_source: string;
    rejection_reason: string;
    blocking_filter: string;
  };
  score_breakdown: {
    score_pre_penalty: number;
    score_post_penalty: number;
    final_score: number;
    confidence_bucket: string;
  };
  factor_contributions: FactorContribution[];
  penalties_applied: PenaltyApplied[];
  filters_checked: FilterCheck[];
  reasoning: {
    summary_short: string;
    summary_full: string;
  };
  outcome: {
    result: string;
    timestamp: string;
    mfe_r: number;
    mae_r: number;
    final_r: number;
    time_to_outcome_minutes: number;
  } | null;
  // NEW: Pattern V3 data
  pattern_data?: PatternData;
  // NEW: Deterministic Pattern Engine data
  pattern_type?: string;
  regime?: string;
  metrics?: MathMetrics;
  expected_edge?: number;
  winrate?: number;
  conditions?: Record<string, boolean>;
}

// Status colors
const STATUS_COLORS: Record<string, { bg: string; text: string; border: string }> = {
  accepted: { bg: '#00ff8815', text: '#00ff88', border: '#00ff8850' },
  rejected: { bg: '#ff444415', text: '#ff4444', border: '#ff444450' },
  active: { bg: '#00aaff15', text: '#00aaff', border: '#00aaff50' },
  tp_hit: { bg: '#00ff8825', text: '#00ff88', border: '#00ff8860' },
  sl_hit: { bg: '#ff444425', text: '#ff4444', border: '#ff444460' },
  expired: { bg: '#88888825', text: '#888888', border: '#88888860' },
};

// Collapsible Section Component
const CollapsibleSection = ({ 
  title, 
  children, 
  defaultOpen = false 
}: { 
  title: string; 
  children: React.ReactNode; 
  defaultOpen?: boolean;
}) => {
  const [isOpen, setIsOpen] = useState(defaultOpen);
  
  return (
    <View style={styles.section}>
      <TouchableOpacity 
        style={styles.sectionHeader}
        onPress={() => setIsOpen(!isOpen)}
        activeOpacity={0.7}
      >
        <Text style={styles.sectionTitle}>{title}</Text>
        <Text style={styles.sectionArrow}>{isOpen ? '▼' : '▶'}</Text>
      </TouchableOpacity>
      {isOpen && (
        <View style={styles.sectionContent}>
          {children}
        </View>
      )}
    </View>
  );
};

export default function SignalSnapshotScreen() {
  const { signalId } = useLocalSearchParams<{ signalId: string }>();
  const router = useRouter();
  const [snapshot, setSnapshot] = useState<SignalSnapshot | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    const fetchSnapshot = async () => {
      try {
        setLoading(true);
        setError(null);
        
        const response = await fetch(`${BACKEND_URL}/api/signals/snapshot/${signalId}`);
        
        if (!response.ok) {
          throw new Error(`HTTP ${response.status}`);
        }
        
        const data = await response.json();
        setSnapshot(data);
      } catch (err) {
        console.error('Error fetching snapshot:', err);
        setError('Failed to load signal details');
      } finally {
        setLoading(false);
      }
    };

    if (signalId) {
      fetchSnapshot();
    }
  }, [signalId]);

  const formatPrice = (price: number, symbol: string) => {
    if (symbol === 'XAUUSD') {
      return price.toFixed(2);
    }
    return price.toFixed(5);
  };

  const formatTimestamp = (ts: string) => {
    // Ensure timestamp is treated as UTC if no timezone specified
    let timestamp = ts;
    if (!ts.endsWith('Z') && !ts.includes('+') && !ts.includes('-', 10)) {
      timestamp = ts + 'Z';
    }
    return new Date(timestamp).toLocaleString('en-US', {
      month: 'short',
      day: 'numeric',
      year: 'numeric',
      hour: '2-digit',
      minute: '2-digit',
      second: '2-digit'
    });
  };

  const getStatusColor = (status: string) => {
    if (status === 'pass') return '#00ff88';
    if (status === 'fail') return '#ff4444';
    return '#ffaa00';
  };

  if (loading) {
    return (
      <SafeAreaView style={styles.container}>
        <View style={styles.loadingContainer}>
          <ActivityIndicator size="large" color="#00ff88" />
          <Text style={styles.loadingText}>Loading signal details...</Text>
        </View>
      </SafeAreaView>
    );
  }

  if (error || !snapshot) {
    return (
      <SafeAreaView style={styles.container}>
        <View style={styles.errorContainer}>
          <Text style={styles.errorText}>{error || 'Signal not found'}</Text>
          <TouchableOpacity 
            style={styles.backButton}
            onPress={() => router.back()}
          >
            <Text style={styles.backButtonText}>Go Back</Text>
          </TouchableOpacity>
        </View>
      </SafeAreaView>
    );
  }

  const statusColor = STATUS_COLORS[snapshot.decision.status] || STATUS_COLORS.rejected;
  const isBuy = snapshot.direction === 'BUY';

  return (
    <SafeAreaView style={styles.container} edges={['bottom']}>
      <ScrollView contentContainerStyle={styles.scrollContent}>
        
        {/* Header */}
        <View style={[styles.headerCard, { borderColor: statusColor.border }]}>
          <View style={styles.headerTop}>
            <View style={styles.symbolRow}>
              <Text style={styles.symbolText}>{snapshot.symbol}</Text>
              <View style={[
                styles.directionBadge,
                { backgroundColor: isBuy ? '#00ff8830' : '#ff444430' }
              ]}>
                <Text style={[
                  styles.directionText,
                  { color: isBuy ? '#00ff88' : '#ff4444' }
                ]}>
                  {snapshot.direction}
                </Text>
              </View>
            </View>
            <View style={[styles.statusBadge, { backgroundColor: statusColor.bg }]}>
              <Text style={[styles.statusText, { color: statusColor.text }]}>
                {snapshot.decision.status.toUpperCase().replace('_', ' ')}
              </Text>
            </View>
          </View>
          
          <View style={styles.scoreDisplay}>
            <Text style={styles.scoreLabel}>Final Score</Text>
            <Text style={[
              styles.scoreValue,
              { color: snapshot.score_breakdown.final_score >= 70 ? '#00ff88' : 
                       snapshot.score_breakdown.final_score >= 60 ? '#ffaa00' : '#ff4444' }
            ]}>
              {snapshot.score_breakdown.final_score.toFixed(1)}
            </Text>
            <Text style={styles.scoreBucket}>{snapshot.score_breakdown.confidence_bucket}</Text>
          </View>
          
          <View style={styles.metaRow}>
            <Text style={styles.metaText}>{snapshot.session}</Text>
            <Text style={styles.metaDot}>•</Text>
            <Text style={styles.metaText}>{snapshot.setup_type}</Text>
          </View>
          <Text style={styles.timestampText}>{formatTimestamp(snapshot.timestamp)}</Text>
        </View>

        {/* Trade Levels */}
        <View style={styles.levelsCard}>
          <Text style={styles.cardTitle}>Trade Levels</Text>
          <View style={styles.levelsGrid}>
            <View style={styles.levelBox}>
              <Text style={styles.levelLabel}>Entry</Text>
              <Text style={styles.levelValue}>
                {formatPrice(snapshot.trade_levels.entry, snapshot.symbol)}
              </Text>
            </View>
            <View style={[styles.levelBox, { borderColor: '#ff4444' }]}>
              <Text style={[styles.levelLabel, { color: '#ff4444' }]}>Stop Loss</Text>
              <Text style={[styles.levelValue, { color: '#ff4444' }]}>
                {formatPrice(snapshot.trade_levels.stop_loss, snapshot.symbol)}
              </Text>
            </View>
            <View style={[styles.levelBox, { borderColor: '#00ff88' }]}>
              <Text style={[styles.levelLabel, { color: '#00ff88' }]}>Take Profit</Text>
              <Text style={[styles.levelValue, { color: '#00ff88' }]}>
                {formatPrice(snapshot.trade_levels.take_profit, snapshot.symbol)}
              </Text>
            </View>
            <View style={styles.levelBox}>
              <Text style={styles.levelLabel}>R:R</Text>
              <Text style={styles.levelValue}>
                {snapshot.trade_levels.rr_ratio.toFixed(2)}
              </Text>
            </View>
          </View>
        </View>

        {/* Score Breakdown / Pattern Info */}
        {snapshot.pattern_type ? (
          /* NEW: Deterministic Pattern Engine Display */
          <View style={styles.scoreBreakdownCard}>
            <Text style={styles.cardTitle}>Pattern Detection</Text>
            <View style={styles.patternInfoRow}>
              <View style={styles.patternInfoBox}>
                <Text style={styles.sbLabel}>Pattern</Text>
                <Text style={[styles.sbValue, { color: '#00aaff', fontSize: 14 }]}>
                  {snapshot.pattern_type?.replace(/_/g, ' ') || 'NONE'}
                </Text>
              </View>
              <View style={styles.patternInfoBox}>
                <Text style={styles.sbLabel}>Regime</Text>
                <Text style={[styles.sbValue, { color: '#ffaa00', fontSize: 14 }]}>
                  {snapshot.regime || 'NONE'}
                </Text>
              </View>
            </View>
            {(snapshot.expected_edge !== undefined || snapshot.winrate !== undefined) && (
              <View style={styles.patternInfoRow}>
                <View style={styles.patternInfoBox}>
                  <Text style={styles.sbLabel}>Winrate</Text>
                  <Text style={styles.sbValue}>
                    {((snapshot.winrate || 0) * 100).toFixed(0)}%
                  </Text>
                </View>
                <View style={styles.patternInfoBox}>
                  <Text style={styles.sbLabel}>Expected Edge</Text>
                  <Text style={[styles.sbValue, { 
                    color: (snapshot.expected_edge || 0) > 0 ? '#00ff88' : '#ff4444' 
                  }]}>
                    {(snapshot.expected_edge || 0).toFixed(4)}R
                  </Text>
                </View>
              </View>
            )}
          </View>
        ) : (
          /* Legacy Score Breakdown */
          <View style={styles.scoreBreakdownCard}>
            <Text style={styles.cardTitle}>Score Breakdown</Text>
            <View style={styles.scoreBreakdownRow}>
              <View style={styles.scoreBreakdownItem}>
                <Text style={styles.sbLabel}>Pre-Penalty</Text>
                <Text style={styles.sbValue}>
                  {snapshot.score_breakdown.score_pre_penalty.toFixed(1)}
                </Text>
              </View>
              <Text style={styles.sbArrow}>→</Text>
              <View style={styles.scoreBreakdownItem}>
                <Text style={styles.sbLabel}>Penalties</Text>
                <Text style={[styles.sbValue, { color: '#ff4444' }]}>
                  -{(snapshot.score_breakdown.score_pre_penalty - snapshot.score_breakdown.final_score).toFixed(1)}
                </Text>
              </View>
              <Text style={styles.sbArrow}>→</Text>
              <View style={styles.scoreBreakdownItem}>
                <Text style={styles.sbLabel}>Final</Text>
                <Text style={[styles.sbValue, { color: '#00ff88' }]}>
                  {snapshot.score_breakdown.final_score.toFixed(1)}
                </Text>
              </View>
            </View>
          </View>
        )}

        {/* Math Metrics (for Deterministic Pattern Engine) */}
        {snapshot.metrics && (
          <CollapsibleSection title="Math Metrics" defaultOpen={true}>
            <View style={styles.metricsGrid}>
              <View style={styles.metricItem}>
                <Text style={styles.metricLabel}>T (Trend)</Text>
                <Text style={[styles.metricValue, {
                  color: (snapshot.metrics.T_t || 0) >= 0.6 ? '#00ff88' : '#888'
                }]}>
                  {(snapshot.metrics.T_t || 0).toFixed(3)}
                </Text>
              </View>
              <View style={styles.metricItem}>
                <Text style={styles.metricLabel}>Z (Deviation)</Text>
                <Text style={[styles.metricValue, {
                  color: Math.abs(snapshot.metrics.Z_t || 0) >= 1.5 ? '#00ff88' : '#888'
                }]}>
                  {(snapshot.metrics.Z_t || 0).toFixed(3)}
                </Text>
              </View>
              <View style={styles.metricItem}>
                <Text style={styles.metricLabel}>μ (Mean Return)</Text>
                <Text style={styles.metricValue}>
                  {((snapshot.metrics.mu_t || 0) * 10000).toFixed(2)}bp
                </Text>
              </View>
              <View style={styles.metricItem}>
                <Text style={styles.metricLabel}>σ (Volatility)</Text>
                <Text style={styles.metricValue}>
                  {((snapshot.metrics.sigma_t || 0) * 10000).toFixed(2)}bp
                </Text>
              </View>
              <View style={styles.metricItem}>
                <Text style={styles.metricLabel}>ATR</Text>
                <Text style={styles.metricValue}>
                  {snapshot.symbol === 'XAUUSD' 
                    ? (snapshot.metrics.ATR_t || 0).toFixed(2)
                    : ((snapshot.metrics.ATR_t || 0) * 10000).toFixed(1) + 'p'}
                </Text>
              </View>
              <View style={styles.metricItem}>
                <Text style={styles.metricLabel}>Range Width</Text>
                <Text style={styles.metricValue}>
                  {snapshot.symbol === 'XAUUSD'
                    ? (snapshot.metrics.range_width || 0).toFixed(2)
                    : ((snapshot.metrics.range_width || 0) * 10000).toFixed(1) + 'p'}
                </Text>
              </View>
            </View>
          </CollapsibleSection>
        )}

        {/* Pattern Analysis (replaces Factor Contributions) */}
        <CollapsibleSection title="Pattern Analysis" defaultOpen={true}>
          {snapshot.factor_contributions.map((factor, index) => (
            <View key={index} style={styles.factorRow}>
              <View style={styles.factorHeader}>
                <Text style={styles.factorName}>{factor.factor_name}</Text>
                <View style={[
                  styles.factorStatusBadge,
                  { backgroundColor: getStatusColor(factor.status) + '20' }
                ]}>
                  <Text style={[
                    styles.factorStatusText,
                    { color: getStatusColor(factor.status) }
                  ]}>
                    {factor.status === 'pass' ? 'ACTIVE' : 'INACTIVE'}
                  </Text>
                </View>
              </View>
              <View style={styles.factorDetails}>
                {factor.status === 'pass' ? (
                  <Text style={styles.factorDetail}>
                    <Text style={{ color: '#00ff88' }}>✓</Text> Pattern detected
                  </Text>
                ) : (
                  <Text style={styles.factorDetail}>
                    <Text style={{ color: '#ff4444' }}>✗</Text> Not detected
                  </Text>
                )}
                <Text style={styles.factorReason}>{factor.reason}</Text>
              </View>
            </View>
          ))}
        </CollapsibleSection>

        {/* Penalties Applied */}
        {snapshot.penalties_applied.length > 0 && (
          <CollapsibleSection title="Penalties Applied" defaultOpen={true}>
            {snapshot.penalties_applied.map((penalty, index) => (
              <View key={index} style={styles.penaltyRow}>
                <View style={styles.penaltyHeader}>
                  <Text style={styles.penaltyName}>{penalty.penalty_name}</Text>
                  <Text style={styles.penaltyValue}>
                    {penalty.penalty_value > 0 ? '-' : '+'}{Math.abs(penalty.penalty_value).toFixed(1)}
                  </Text>
                </View>
                <Text style={styles.penaltyReason}>{penalty.reason}</Text>
                <Text style={styles.penaltyCondition}>
                  Trigger: {penalty.trigger_condition}
                </Text>
              </View>
            ))}
          </CollapsibleSection>
        )}

        {/* Filter Checks */}
        <CollapsibleSection title="Filter Checks" defaultOpen={false}>
          {snapshot.filters_checked.map((filter, index) => (
            <View key={index} style={[
              styles.filterRow,
              { borderLeftColor: filter.passed ? '#00ff88' : '#ff4444' }
            ]}>
              <View style={styles.filterHeader}>
                <Text style={styles.filterName}>
                  {filter.filter_name.replace(/_/g, ' ')}
                </Text>
                <View style={[
                  styles.filterPassBadge,
                  { backgroundColor: filter.passed ? '#00ff8820' : '#ff444420' }
                ]}>
                  <Text style={[
                    styles.filterPassText,
                    { color: filter.passed ? '#00ff88' : '#ff4444' }
                  ]}>
                    {filter.passed ? '✓ PASS' : '✗ FAIL'}
                  </Text>
                </View>
              </View>
              {filter.threshold > 0 && (
                <Text style={styles.filterDetail}>
                  Value: {filter.actual_value.toFixed(1)} | Threshold: {filter.threshold.toFixed(1)}
                </Text>
              )}
              {filter.blocks_trade && (
                <Text style={styles.filterBlocking}>⚠ BLOCKING FILTER</Text>
              )}
            </View>
          ))}
        </CollapsibleSection>

        {/* Final Explanation */}
        <View style={styles.explanationCard}>
          <Text style={styles.cardTitle}>Final Explanation</Text>
          <Text style={styles.explanationText}>
            {snapshot.reasoning.summary_full}
          </Text>
        </View>

        {/* Outcome (if completed) */}
        {snapshot.outcome && (
          <View style={[
            styles.outcomeCard,
            { 
              backgroundColor: snapshot.outcome.result === 'tp_hit' ? '#00ff8815' : '#ff444415',
              borderColor: snapshot.outcome.result === 'tp_hit' ? '#00ff8850' : '#ff444450'
            }
          ]}>
            <Text style={styles.cardTitle}>Trade Outcome</Text>
            <View style={styles.outcomeHeader}>
              <Text style={[
                styles.outcomeResult,
                { color: snapshot.outcome.result === 'tp_hit' ? '#00ff88' : '#ff4444' }
              ]}>
                {snapshot.outcome.result === 'tp_hit' ? '✓ TP HIT' : 
                 snapshot.outcome.result === 'sl_hit' ? '✗ SL HIT' : 
                 snapshot.outcome.result.toUpperCase()}
              </Text>
              <Text style={[
                styles.outcomeR,
                { color: snapshot.outcome.final_r >= 0 ? '#00ff88' : '#ff4444' }
              ]}>
                {snapshot.outcome.final_r >= 0 ? '+' : ''}{snapshot.outcome.final_r.toFixed(2)}R
              </Text>
            </View>
            <View style={styles.outcomeDetails}>
              <View style={styles.outcomeItem}>
                <Text style={styles.outcomeLabel}>MFE</Text>
                <Text style={styles.outcomeValue}>+{snapshot.outcome.mfe_r.toFixed(2)}R</Text>
              </View>
              <View style={styles.outcomeItem}>
                <Text style={styles.outcomeLabel}>MAE</Text>
                <Text style={styles.outcomeValue}>-{snapshot.outcome.mae_r.toFixed(2)}R</Text>
              </View>
              <View style={styles.outcomeItem}>
                <Text style={styles.outcomeLabel}>Time</Text>
                <Text style={styles.outcomeValue}>
                  {Math.floor(snapshot.outcome.time_to_outcome_minutes / 60)}h {Math.floor(snapshot.outcome.time_to_outcome_minutes % 60)}m
                </Text>
              </View>
            </View>
          </View>
        )}

      </ScrollView>
    </SafeAreaView>
  );
}

const styles = StyleSheet.create({
  container: {
    flex: 1,
    backgroundColor: '#0a0a0a',
  },
  loadingContainer: {
    flex: 1,
    justifyContent: 'center',
    alignItems: 'center',
  },
  loadingText: {
    color: '#888',
    marginTop: 12,
    fontSize: 14,
  },
  errorContainer: {
    flex: 1,
    justifyContent: 'center',
    alignItems: 'center',
    padding: 20,
  },
  errorText: {
    color: '#ff4444',
    fontSize: 16,
    marginBottom: 20,
  },
  backButton: {
    backgroundColor: '#1a1a1a',
    paddingHorizontal: 24,
    paddingVertical: 12,
    borderRadius: 8,
  },
  backButtonText: {
    color: '#00ff88',
    fontSize: 14,
    fontWeight: '600',
  },
  scrollContent: {
    padding: 16,
    paddingBottom: 40,
  },
  headerCard: {
    backgroundColor: '#1a1a1a',
    borderRadius: 16,
    padding: 20,
    marginBottom: 16,
    borderWidth: 1,
  },
  headerTop: {
    flexDirection: 'row',
    justifyContent: 'space-between',
    alignItems: 'center',
    marginBottom: 16,
  },
  symbolRow: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: 10,
  },
  symbolText: {
    color: '#fff',
    fontSize: 28,
    fontWeight: 'bold',
  },
  directionBadge: {
    paddingHorizontal: 12,
    paddingVertical: 6,
    borderRadius: 6,
  },
  directionText: {
    fontSize: 14,
    fontWeight: 'bold',
  },
  statusBadge: {
    paddingHorizontal: 14,
    paddingVertical: 6,
    borderRadius: 6,
  },
  statusText: {
    fontSize: 12,
    fontWeight: 'bold',
  },
  scoreDisplay: {
    alignItems: 'center',
    marginBottom: 16,
  },
  scoreLabel: {
    color: '#888',
    fontSize: 12,
    marginBottom: 4,
  },
  scoreValue: {
    fontSize: 48,
    fontWeight: 'bold',
  },
  scoreBucket: {
    color: '#666',
    fontSize: 12,
    marginTop: 4,
  },
  metaRow: {
    flexDirection: 'row',
    justifyContent: 'center',
    alignItems: 'center',
    gap: 8,
  },
  metaText: {
    color: '#00aaff',
    fontSize: 14,
  },
  metaDot: {
    color: '#444',
  },
  timestampText: {
    color: '#666',
    fontSize: 12,
    textAlign: 'center',
    marginTop: 8,
  },
  levelsCard: {
    backgroundColor: '#1a1a1a',
    borderRadius: 12,
    padding: 16,
    marginBottom: 16,
  },
  cardTitle: {
    color: '#fff',
    fontSize: 16,
    fontWeight: 'bold',
    marginBottom: 12,
  },
  levelsGrid: {
    flexDirection: 'row',
    flexWrap: 'wrap',
    gap: 12,
  },
  levelBox: {
    flex: 1,
    minWidth: '45%',
    backgroundColor: '#0f0f0f',
    borderRadius: 8,
    padding: 12,
    borderWidth: 1,
    borderColor: '#2a2a2a',
    alignItems: 'center',
  },
  levelLabel: {
    color: '#888',
    fontSize: 11,
    marginBottom: 4,
  },
  levelValue: {
    color: '#fff',
    fontSize: 16,
    fontWeight: 'bold',
  },
  scoreBreakdownCard: {
    backgroundColor: '#1a1a1a',
    borderRadius: 12,
    padding: 16,
    marginBottom: 16,
  },
  scoreBreakdownRow: {
    flexDirection: 'row',
    alignItems: 'center',
    justifyContent: 'space-between',
  },
  scoreBreakdownItem: {
    alignItems: 'center',
    flex: 1,
  },
  sbLabel: {
    color: '#888',
    fontSize: 11,
    marginBottom: 4,
  },
  sbValue: {
    color: '#fff',
    fontSize: 20,
    fontWeight: 'bold',
  },
  sbArrow: {
    color: '#444',
    fontSize: 16,
  },
  section: {
    backgroundColor: '#1a1a1a',
    borderRadius: 12,
    marginBottom: 16,
    overflow: 'hidden',
  },
  sectionHeader: {
    flexDirection: 'row',
    justifyContent: 'space-between',
    alignItems: 'center',
    padding: 16,
    backgroundColor: '#1f1f1f',
  },
  sectionTitle: {
    color: '#fff',
    fontSize: 14,
    fontWeight: 'bold',
  },
  sectionArrow: {
    color: '#888',
    fontSize: 12,
  },
  sectionContent: {
    padding: 12,
  },
  factorRow: {
    backgroundColor: '#0f0f0f',
    borderRadius: 8,
    padding: 12,
    marginBottom: 8,
  },
  factorHeader: {
    flexDirection: 'row',
    justifyContent: 'space-between',
    alignItems: 'center',
    marginBottom: 8,
  },
  factorName: {
    color: '#fff',
    fontSize: 13,
    fontWeight: '600',
    flex: 1,
  },
  factorStatusBadge: {
    paddingHorizontal: 8,
    paddingVertical: 3,
    borderRadius: 4,
  },
  factorStatusText: {
    fontSize: 10,
    fontWeight: 'bold',
  },
  factorDetails: {},
  factorDetail: {
    color: '#888',
    fontSize: 12,
    marginBottom: 4,
  },
  factorReason: {
    color: '#666',
    fontSize: 11,
    fontStyle: 'italic',
  },
  penaltyRow: {
    backgroundColor: '#1a0a0a',
    borderRadius: 8,
    padding: 12,
    marginBottom: 8,
    borderLeftWidth: 3,
    borderLeftColor: '#ff4444',
  },
  penaltyHeader: {
    flexDirection: 'row',
    justifyContent: 'space-between',
    alignItems: 'center',
    marginBottom: 6,
  },
  penaltyName: {
    color: '#ff4444',
    fontSize: 13,
    fontWeight: '600',
  },
  penaltyValue: {
    color: '#ff4444',
    fontSize: 16,
    fontWeight: 'bold',
  },
  penaltyReason: {
    color: '#888',
    fontSize: 12,
    marginBottom: 4,
  },
  penaltyCondition: {
    color: '#666',
    fontSize: 11,
  },
  filterRow: {
    backgroundColor: '#0f0f0f',
    borderRadius: 8,
    padding: 12,
    marginBottom: 8,
    borderLeftWidth: 3,
  },
  filterHeader: {
    flexDirection: 'row',
    justifyContent: 'space-between',
    alignItems: 'center',
    marginBottom: 4,
  },
  filterName: {
    color: '#fff',
    fontSize: 13,
    fontWeight: '500',
    textTransform: 'capitalize',
  },
  filterPassBadge: {
    paddingHorizontal: 8,
    paddingVertical: 3,
    borderRadius: 4,
  },
  filterPassText: {
    fontSize: 10,
    fontWeight: 'bold',
  },
  filterDetail: {
    color: '#888',
    fontSize: 11,
  },
  filterBlocking: {
    color: '#ff4444',
    fontSize: 11,
    fontWeight: 'bold',
    marginTop: 4,
  },
  explanationCard: {
    backgroundColor: '#1a1a1a',
    borderRadius: 12,
    padding: 16,
    marginBottom: 16,
  },
  explanationText: {
    color: '#aaa',
    fontSize: 14,
    lineHeight: 22,
  },
  outcomeCard: {
    borderRadius: 12,
    padding: 16,
    borderWidth: 1,
  },
  outcomeHeader: {
    flexDirection: 'row',
    justifyContent: 'space-between',
    alignItems: 'center',
    marginBottom: 12,
  },
  outcomeResult: {
    fontSize: 18,
    fontWeight: 'bold',
  },
  outcomeR: {
    fontSize: 24,
    fontWeight: 'bold',
  },
  outcomeDetails: {
    flexDirection: 'row',
    justifyContent: 'space-around',
  },
  outcomeItem: {
    alignItems: 'center',
  },
  outcomeLabel: {
    color: '#888',
    fontSize: 11,
    marginBottom: 4,
  },
  outcomeValue: {
    color: '#fff',
    fontSize: 14,
    fontWeight: '600',
  },
  // NEW: Pattern Info Styles
  patternInfoRow: {
    flexDirection: 'row',
    justifyContent: 'space-around',
    marginBottom: 12,
  },
  patternInfoBox: {
    alignItems: 'center',
    flex: 1,
  },
  // NEW: Metrics Grid Styles
  metricsGrid: {
    flexDirection: 'row',
    flexWrap: 'wrap',
    gap: 8,
  },
  metricItem: {
    width: '48%',
    backgroundColor: '#0f0f0f',
    borderRadius: 8,
    padding: 12,
    alignItems: 'center',
  },
  metricLabel: {
    color: '#888',
    fontSize: 11,
    marginBottom: 4,
  },
  metricValue: {
    color: '#fff',
    fontSize: 16,
    fontWeight: 'bold',
  },
});
