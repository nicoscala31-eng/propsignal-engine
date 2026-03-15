import React, { useState, useEffect, useCallback } from 'react';
import {
  View,
  Text,
  StyleSheet,
  ScrollView,
  TouchableOpacity,
  ActivityIndicator,
  RefreshControl,
} from 'react-native';
import { SafeAreaView } from 'react-native-safe-area-context';
import { useRouter } from 'expo-router';
import { BACKEND_URL } from '../config/api';

interface PerformanceData {
  summary: {
    total_signals: number;
    buy_signals: number;
    sell_signals: number;
    next_signals: number;
  };
  performance: {
    win_rate: number;
    loss_rate: number;
    winning_trades: number;
    losing_trades: number;
    pending_trades: number;
  };
  risk_metrics: {
    average_rr_ratio: number;
    profit_factor: number;
    expectancy: number;
    max_drawdown_pct: number;
    current_drawdown_pct: number;
  };
  streaks: {
    longest_winning: number;
    longest_losing: number;
  };
  by_asset: Record<string, number>;
  by_regime: Record<string, number>;
  win_rate_by_asset: Record<string, number>;
  activity: {
    signals_today: number;
    signals_this_week: number;
    signals_this_month: number;
  };
}

interface ScannerStatus {
  is_running: boolean;
  version?: string;
  mode?: string;
  min_confidence_threshold?: number;
  statistics: {
    total_scans: number;
    signals_generated: number;
    notifications_sent: number;
    rejections?: number;
  };
  prop_config?: {
    account_size: number;
    max_daily_loss: number;
    operational_warning: number;
    risk_per_trade: string;
  };
  daily_risk_status?: {
    daily_risk_used: number;
    daily_risk_remaining: number;
    at_warning_level: boolean;
  };
}

export default function AnalyticsScreen() {
  const router = useRouter();
  const [loading, setLoading] = useState(true);
  const [refreshing, setRefreshing] = useState(false);
  const [performance, setPerformance] = useState<PerformanceData | null>(null);
  const [scannerStatus, setScannerStatus] = useState<ScannerStatus | null>(null);
  const [error, setError] = useState<string | null>(null);

  const fetchData = useCallback(async () => {
    try {
      setError(null);
      const [perfResponse, scannerResponse] = await Promise.all([
        fetch(`${BACKEND_URL}/api/analytics/performance`),
        fetch(`${BACKEND_URL}/api/scanner/v3/status`)  // Use v3 endpoint
      ]);

      if (perfResponse.ok) {
        const perfData = await perfResponse.json();
        setPerformance(perfData);
      }

      if (scannerResponse.ok) {
        const scannerData = await scannerResponse.json();
        setScannerStatus(scannerData);
      }

      if (scannerResponse.ok) {
        const scannerData = await scannerResponse.json();
        setScannerStatus(scannerData);
      }

      setError(null);
    } catch (err) {
      console.error('Error fetching analytics:', err);
      setError('Failed to load analytics');
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    fetchData();
  }, [fetchData]);

  const onRefresh = async () => {
    setRefreshing(true);
    await fetchData();
    setRefreshing(false);
  };

  const toggleScanner = async () => {
    try {
      // Use production control endpoint
      const endpoint = scannerStatus?.is_running ? 'disable' : 'enable';
      const response = await fetch(`${BACKEND_URL}/api/production/scanner/${endpoint}`, {
        method: 'POST'
      });

      if (response.ok) {
        // Refresh status
        const statusResponse = await fetch(`${BACKEND_URL}/api/scanner/v3/status`);
        if (statusResponse.ok) {
          const data = await statusResponse.json();
          setScannerStatus(data);
        }
      }
    } catch (err) {
      console.error('Error toggling scanner:', err);
    }
  };
  };

  if (loading) {
    return (
      <SafeAreaView style={styles.container} edges={['top']}>
        <View style={styles.centered}>
          <ActivityIndicator size="large" color="#00ff88" />
          <Text style={styles.loadingText}>Loading analytics...</Text>
        </View>
      </SafeAreaView>
    );
  }

  return (
    <SafeAreaView style={styles.container} edges={['top']}>
      <View style={styles.header}>
        <TouchableOpacity onPress={() => router.back()}>
          <Text style={styles.backButton}>Back</Text>
        </TouchableOpacity>
        <Text style={styles.title}>Analytics</Text>
        <View style={{ width: 40 }} />
      </View>

      <ScrollView
        style={styles.content}
        refreshControl={
          <RefreshControl refreshing={refreshing} onRefresh={onRefresh} tintColor="#00ff88" />
        }
      >
        {/* Scanner Status Card */}
        <View style={styles.card}>
          <Text style={styles.cardTitle}>Backend Scanner</Text>
          <View style={styles.scannerRow}>
            <View style={[
              styles.statusDot,
              { backgroundColor: scannerStatus?.is_running ? '#00ff88' : '#666666' }
            ]} />
            <Text style={styles.statusText}>
              {scannerStatus?.is_running ? 'Running' : 'Stopped'}
            </Text>
            <TouchableOpacity
              style={[
                styles.toggleButton,
                scannerStatus?.is_running ? styles.toggleStop : styles.toggleStart
              ]}
              onPress={toggleScanner}
            >
              <Text style={styles.toggleButtonText}>
                {scannerStatus?.is_running ? 'Stop' : 'Start'}
              </Text>
            </TouchableOpacity>
          </View>

          {scannerStatus && (
            <View style={styles.scannerStats}>
              <View style={styles.statItem}>
                <Text style={styles.statLabel}>Mode</Text>
                <Text style={styles.statValue}>
                  {scannerStatus.mode === 'confidence_based_enhanced' ? 'Enhanced' : 'Standard'}
                </Text>
              </View>
              <View style={styles.statItem}>
                <Text style={styles.statLabel}>Scans</Text>
                <Text style={styles.statValue}>{scannerStatus.statistics.total_scans}</Text>
              </View>
              <View style={styles.statItem}>
                <Text style={styles.statLabel}>Signals</Text>
                <Text style={styles.statValue}>{scannerStatus.statistics.signals_generated}</Text>
              </View>
              <View style={styles.statItem}>
                <Text style={styles.statLabel}>Notifications</Text>
                <Text style={styles.statValue}>{scannerStatus.statistics.notifications_sent}</Text>
              </View>
            </View>
          )}

          {/* Prop Risk Status */}
          {scannerStatus?.daily_risk_status && (
            <View style={styles.propRiskSection}>
              <Text style={styles.propRiskTitle}>Daily Risk Status</Text>
              <View style={styles.propRiskRow}>
                <View style={styles.propRiskItem}>
                  <Text style={styles.propRiskLabel}>Used</Text>
                  <Text style={[
                    styles.propRiskValue,
                    scannerStatus.daily_risk_status.at_warning_level && { color: '#ffaa00' }
                  ]}>
                    ${scannerStatus.daily_risk_status.daily_risk_used.toFixed(0)}
                  </Text>
                </View>
                <View style={styles.propRiskItem}>
                  <Text style={styles.propRiskLabel}>Remaining</Text>
                  <Text style={[
                    styles.propRiskValue,
                    { color: scannerStatus.daily_risk_status.daily_risk_remaining > 1500 ? '#00ff88' : '#ffaa00' }
                  ]}>
                    ${scannerStatus.daily_risk_status.daily_risk_remaining.toFixed(0)}
                  </Text>
                </View>
              </View>
              {scannerStatus.daily_risk_status.at_warning_level && (
                <Text style={styles.warningText}>⚠️ Approaching daily limit</Text>
              )}
            </View>
          )}
        </View>

        {/* Performance Overview */}
        {performance && (
          <>
            <View style={styles.card}>
              <Text style={styles.cardTitle}>Signal Summary</Text>
              <View style={styles.summaryGrid}>
                <View style={styles.summaryItem}>
                  <Text style={styles.summaryValue}>{performance.summary.total_signals}</Text>
                  <Text style={styles.summaryLabel}>Total</Text>
                </View>
                <View style={[styles.summaryItem, { borderColor: '#00ff88' }]}>
                  <Text style={[styles.summaryValue, { color: '#00ff88' }]}>{performance.summary.buy_signals}</Text>
                  <Text style={styles.summaryLabel}>BUY</Text>
                </View>
                <View style={[styles.summaryItem, { borderColor: '#ff3366' }]}>
                  <Text style={[styles.summaryValue, { color: '#ff3366' }]}>{performance.summary.sell_signals}</Text>
                  <Text style={styles.summaryLabel}>SELL</Text>
                </View>
                <View style={styles.summaryItem}>
                  <Text style={styles.summaryValue}>{performance.summary.next_signals}</Text>
                  <Text style={styles.summaryLabel}>NEXT</Text>
                </View>
              </View>
            </View>

            <View style={styles.card}>
              <Text style={styles.cardTitle}>Performance</Text>
              <View style={styles.metricsRow}>
                <View style={styles.metricBox}>
                  <Text style={[styles.metricValue, { color: '#00ff88' }]}>
                    {performance.performance.win_rate.toFixed(1)}%
                  </Text>
                  <Text style={styles.metricLabel}>Win Rate</Text>
                </View>
                <View style={styles.metricBox}>
                  <Text style={styles.metricValue}>
                    {performance.risk_metrics.profit_factor.toFixed(2)}
                  </Text>
                  <Text style={styles.metricLabel}>Profit Factor</Text>
                </View>
                <View style={styles.metricBox}>
                  <Text style={styles.metricValue}>
                    {performance.risk_metrics.expectancy.toFixed(2)}R
                  </Text>
                  <Text style={styles.metricLabel}>Expectancy</Text>
                </View>
              </View>

              <View style={styles.metricsRow}>
                <View style={styles.metricBox}>
                  <Text style={styles.metricValue}>
                    {performance.risk_metrics.average_rr_ratio.toFixed(2)}
                  </Text>
                  <Text style={styles.metricLabel}>Avg R:R</Text>
                </View>
                <View style={styles.metricBox}>
                  <Text style={[styles.metricValue, { color: '#ff3366' }]}>
                    {performance.risk_metrics.max_drawdown_pct.toFixed(1)}%
                  </Text>
                  <Text style={styles.metricLabel}>Max DD</Text>
                </View>
                <View style={styles.metricBox}>
                  <Text style={styles.metricValue}>
                    {performance.streaks.longest_winning}
                  </Text>
                  <Text style={styles.metricLabel}>Best Streak</Text>
                </View>
              </View>
            </View>

            <View style={styles.card}>
              <Text style={styles.cardTitle}>Activity</Text>
              <View style={styles.activityRow}>
                <View style={styles.activityItem}>
                  <Text style={styles.activityValue}>{performance.activity.signals_today}</Text>
                  <Text style={styles.activityLabel}>Today</Text>
                </View>
                <View style={styles.activityItem}>
                  <Text style={styles.activityValue}>{performance.activity.signals_this_week}</Text>
                  <Text style={styles.activityLabel}>This Week</Text>
                </View>
                <View style={styles.activityItem}>
                  <Text style={styles.activityValue}>{performance.activity.signals_this_month}</Text>
                  <Text style={styles.activityLabel}>This Month</Text>
                </View>
              </View>
            </View>

            {/* Trade Outcomes */}
            <View style={styles.card}>
              <Text style={styles.cardTitle}>Trade Outcomes</Text>
              <View style={styles.outcomeRow}>
                <View style={[styles.outcomeItem, { backgroundColor: 'rgba(0, 255, 136, 0.1)' }]}>
                  <Text style={[styles.outcomeValue, { color: '#00ff88' }]}>
                    {performance.performance.winning_trades}
                  </Text>
                  <Text style={styles.outcomeLabel}>Winners</Text>
                </View>
                <View style={[styles.outcomeItem, { backgroundColor: 'rgba(255, 51, 102, 0.1)' }]}>
                  <Text style={[styles.outcomeValue, { color: '#ff3366' }]}>
                    {performance.performance.losing_trades}
                  </Text>
                  <Text style={styles.outcomeLabel}>Losers</Text>
                </View>
                <View style={[styles.outcomeItem, { backgroundColor: 'rgba(255, 170, 0, 0.1)' }]}>
                  <Text style={[styles.outcomeValue, { color: '#ffaa00' }]}>
                    {performance.performance.pending_trades}
                  </Text>
                  <Text style={styles.outcomeLabel}>Pending</Text>
                </View>
              </View>
            </View>
          </>
        )}

        {error && (
          <View style={styles.errorCard}>
            <Text style={styles.errorText}>{error}</Text>
          </View>
        )}

        <View style={{ height: 40 }} />
      </ScrollView>
    </SafeAreaView>
  );
}

const styles = StyleSheet.create({
  container: {
    flex: 1,
    backgroundColor: '#0a0a0a',
  },
  centered: {
    flex: 1,
    justifyContent: 'center',
    alignItems: 'center',
  },
  loadingText: {
    color: '#666666',
    marginTop: 12,
  },
  header: {
    flexDirection: 'row',
    alignItems: 'center',
    justifyContent: 'space-between',
    padding: 16,
    borderBottomWidth: 1,
    borderBottomColor: '#222222',
  },
  backButton: {
    color: '#00ff88',
    fontSize: 16,
  },
  title: {
    fontSize: 18,
    fontWeight: 'bold',
    color: '#ffffff',
  },
  content: {
    flex: 1,
    padding: 16,
  },
  card: {
    backgroundColor: '#111111',
    borderRadius: 12,
    padding: 16,
    marginBottom: 16,
    borderWidth: 1,
    borderColor: '#222222',
  },
  cardTitle: {
    fontSize: 16,
    fontWeight: '600',
    color: '#888888',
    marginBottom: 12,
  },
  scannerRow: {
    flexDirection: 'row',
    alignItems: 'center',
    marginBottom: 12,
  },
  statusDot: {
    width: 10,
    height: 10,
    borderRadius: 5,
    marginRight: 8,
  },
  statusText: {
    color: '#ffffff',
    fontSize: 16,
    flex: 1,
  },
  toggleButton: {
    paddingHorizontal: 16,
    paddingVertical: 8,
    borderRadius: 6,
  },
  toggleStart: {
    backgroundColor: '#00ff88',
  },
  toggleStop: {
    backgroundColor: '#ff3366',
  },
  toggleButtonText: {
    color: '#0a0a0a',
    fontWeight: 'bold',
  },
  scannerStats: {
    flexDirection: 'row',
    justifyContent: 'space-around',
    paddingTop: 12,
    borderTopWidth: 1,
    borderTopColor: '#222222',
    marginBottom: 12,
  },
  statItem: {
    alignItems: 'center',
  },
  statLabel: {
    color: '#666666',
    fontSize: 11,
    marginBottom: 4,
  },
  statValue: {
    color: '#ffffff',
    fontSize: 14,
    fontWeight: '600',
  },
  profileSelector: {
    flexDirection: 'row',
    alignItems: 'center',
    flexWrap: 'wrap',
    gap: 8,
    paddingTop: 12,
    borderTopWidth: 1,
    borderTopColor: '#222222',
  },
  profileLabel: {
    color: '#666666',
    fontSize: 12,
    marginRight: 4,
  },
  profileButton: {
    paddingHorizontal: 10,
    paddingVertical: 6,
    borderRadius: 4,
    backgroundColor: '#1a1a1a',
    borderWidth: 1,
    borderColor: '#333333',
  },
  profileButtonActive: {
    backgroundColor: '#00ff88',
    borderColor: '#00ff88',
  },
  profileButtonText: {
    color: '#888888',
    fontSize: 11,
  },
  profileButtonTextActive: {
    color: '#0a0a0a',
    fontWeight: 'bold',
  },
  summaryGrid: {
    flexDirection: 'row',
    justifyContent: 'space-between',
  },
  summaryItem: {
    alignItems: 'center',
    padding: 12,
    borderRadius: 8,
    borderWidth: 1,
    borderColor: '#333333',
    flex: 1,
    marginHorizontal: 4,
  },
  summaryValue: {
    color: '#ffffff',
    fontSize: 24,
    fontWeight: 'bold',
  },
  summaryLabel: {
    color: '#666666',
    fontSize: 11,
    marginTop: 4,
  },
  metricsRow: {
    flexDirection: 'row',
    justifyContent: 'space-between',
    marginBottom: 12,
  },
  metricBox: {
    flex: 1,
    alignItems: 'center',
    padding: 12,
    backgroundColor: '#0a0a0a',
    borderRadius: 8,
    marginHorizontal: 4,
  },
  metricValue: {
    color: '#ffffff',
    fontSize: 20,
    fontWeight: 'bold',
  },
  metricLabel: {
    color: '#666666',
    fontSize: 11,
    marginTop: 4,
  },
  activityRow: {
    flexDirection: 'row',
    justifyContent: 'space-around',
  },
  activityItem: {
    alignItems: 'center',
  },
  activityValue: {
    color: '#00ff88',
    fontSize: 28,
    fontWeight: 'bold',
  },
  activityLabel: {
    color: '#666666',
    fontSize: 12,
    marginTop: 4,
  },
  outcomeRow: {
    flexDirection: 'row',
    gap: 8,
  },
  outcomeItem: {
    flex: 1,
    alignItems: 'center',
    padding: 16,
    borderRadius: 8,
  },
  outcomeValue: {
    fontSize: 24,
    fontWeight: 'bold',
  },
  outcomeLabel: {
    color: '#888888',
    fontSize: 12,
    marginTop: 4,
  },
  errorCard: {
    backgroundColor: '#1a0a0a',
    borderRadius: 8,
    padding: 16,
    borderWidth: 1,
    borderColor: '#ff3366',
  },
  errorText: {
    color: '#ff6666',
    textAlign: 'center',
  },
  // NEW: Prop Risk Section Styles
  propRiskSection: {
    marginTop: 12,
    padding: 12,
    backgroundColor: '#0a0a1a',
    borderRadius: 8,
    borderWidth: 1,
    borderColor: '#333366',
  },
  propRiskTitle: {
    color: '#00ff88',
    fontSize: 14,
    fontWeight: 'bold',
    marginBottom: 12,
    textAlign: 'center',
  },
  propRiskRow: {
    flexDirection: 'row',
    justifyContent: 'space-around',
    marginBottom: 8,
  },
  propRiskItem: {
    alignItems: 'center',
  },
  propRiskLabel: {
    color: '#888888',
    fontSize: 10,
    textTransform: 'uppercase',
  },
  propRiskValue: {
    color: '#ffffff',
    fontSize: 18,
    fontWeight: 'bold',
    marginTop: 2,
  },
  warningText: {
    color: '#ffaa00',
    fontSize: 12,
    textAlign: 'center',
    marginTop: 8,
  },
});
