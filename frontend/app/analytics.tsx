import React, { useState, useEffect } from 'react';
import { View, Text, StyleSheet, ScrollView, ActivityIndicator } from 'react-native';
import { SafeAreaView } from 'react-native-safe-area-context';

const BACKEND_URL = process.env.EXPO_PUBLIC_BACKEND_URL;
const MOCK_USER_ID = '1773156899.291813';

interface AnalyticsSummary {
  total_signals: number;
  buy_signals: number;
  sell_signals: number;
  next_signals: number;
  trade_signals: number;
  average_confidence: number;
  by_asset: {
    EURUSD: number;
    XAUUSD: number;
  };
}

export default function AnalyticsScreen() {
  const [analytics, setAnalytics] = useState<AnalyticsSummary | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    fetchAnalytics();
  }, []);

  const fetchAnalytics = async () => {
    try {
      const response = await fetch(`${BACKEND_URL}/api/users/${MOCK_USER_ID}/analytics/summary`);
      if (response.ok) {
        const data = await response.json();
        setAnalytics(data);
      }
    } catch (error) {
      console.error('Error fetching analytics:', error);
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

  if (!analytics) {
    return (
      <SafeAreaView style={styles.container}>
        <Text style={styles.errorText}>No analytics data available</Text>
      </SafeAreaView>
    );
  }

  return (
    <SafeAreaView style={styles.container} edges={['bottom']}>
      <ScrollView style={styles.content}>
        {/* Overview */}
        <View style={styles.section}>
          <Text style={styles.sectionTitle}>Signal Overview</Text>
          
          <View style={styles.statsGrid}>
            <View style={styles.statCard}>
              <Text style={styles.statValue}>{analytics.total_signals}</Text>
              <Text style={styles.statLabel}>Total Signals</Text>
            </View>

            <View style={styles.statCard}>
              <Text style={[styles.statValue, { color: '#00ff88' }]}>{analytics.buy_signals}</Text>
              <Text style={styles.statLabel}>BUY Signals</Text>
            </View>

            <View style={styles.statCard}>
              <Text style={[styles.statValue, { color: '#ff3366' }]}>{analytics.sell_signals}</Text>
              <Text style={styles.statLabel}>SELL Signals</Text>
            </View>

            <View style={styles.statCard}>
              <Text style={[styles.statValue, { color: '#888888' }]}>{analytics.next_signals}</Text>
              <Text style={styles.statLabel}>NEXT Signals</Text>
            </View>
          </View>
        </View>

        {/* Trade Quality */}
        <View style={styles.section}>
          <Text style={styles.sectionTitle}>Trade Quality</Text>
          
          <View style={styles.qualityCard}>
            <Text style={styles.qualityLabel}>Average Confidence</Text>
            <Text style={styles.qualityValue}>{analytics.average_confidence.toFixed(1)}%</Text>
            <View style={styles.progressBar}>
              <View 
                style={[
                  styles.progressFill, 
                  { width: `${analytics.average_confidence}%`, backgroundColor: '#00ff88' }
                ]} 
              />
            </View>
          </View>

          <View style={styles.qualityCard}>
            <Text style={styles.qualityLabel}>Trade Signal Rate</Text>
            <Text style={styles.qualityValue}>
              {analytics.total_signals > 0 
                ? ((analytics.trade_signals / analytics.total_signals) * 100).toFixed(1)
                : 0
              }%
            </Text>
            <Text style={styles.qualitySubtext}>
              {analytics.trade_signals} trade signals out of {analytics.total_signals} total
            </Text>
          </View>
        </View>

        {/* By Asset */}
        <View style={styles.section}>
          <Text style={styles.sectionTitle}>Signals by Asset</Text>
          
          <View style={styles.assetCard}>
            <View style={styles.assetRow}>
              <Text style={styles.assetLabel}>EUR/USD</Text>
              <Text style={styles.assetValue}>{analytics.by_asset.EURUSD}</Text>
            </View>
            <View style={styles.progressBar}>
              <View 
                style={[
                  styles.progressFill,
                  { 
                    width: `${(analytics.by_asset.EURUSD / (analytics.by_asset.EURUSD + analytics.by_asset.XAUUSD || 1)) * 100}%`,
                    backgroundColor: '#00aaff'
                  }
                ]} 
              />
            </View>
          </View>

          <View style={styles.assetCard}>
            <View style={styles.assetRow}>
              <Text style={styles.assetLabel}>XAU/USD (Gold)</Text>
              <Text style={styles.assetValue}>{analytics.by_asset.XAUUSD}</Text>
            </View>
            <View style={styles.progressBar}>
              <View 
                style={[
                  styles.progressFill,
                  { 
                    width: `${(analytics.by_asset.XAUUSD / (analytics.by_asset.EURUSD + analytics.by_asset.XAUUSD || 1)) * 100}%`,
                    backgroundColor: '#ffd700'
                  }
                ]} 
              />
            </View>
          </View>
        </View>

        {/* Info */}
        <View style={styles.section}>
          <Text style={styles.infoTitle}>📊 Analytics Information</Text>
          <Text style={styles.infoText}>
            These analytics show your signal generation history. The system prioritizes quality over quantity,
            generating BUY/SELL signals only when high-confidence setups are detected.
          </Text>
          <Text style={styles.infoText}>
            NEXT signals indicate times when the market conditions don't meet the strict quality thresholds
            required for prop firm trading.
          </Text>
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
  section: {
    padding: 20,
    borderBottomWidth: 1,
    borderBottomColor: '#222222',
  },
  sectionTitle: {
    fontSize: 20,
    fontWeight: 'bold',
    color: '#00ff88',
    marginBottom: 16,
  },
  statsGrid: {
    flexDirection: 'row',
    flexWrap: 'wrap',
    gap: 12,
  },
  statCard: {
    flex: 1,
    minWidth: '45%',
    backgroundColor: '#111111',
    padding: 16,
    borderRadius: 12,
    alignItems: 'center',
  },
  statValue: {
    fontSize: 32,
    fontWeight: 'bold',
    color: '#ffffff',
    marginBottom: 4,
  },
  statLabel: {
    fontSize: 12,
    color: '#888888',
  },
  qualityCard: {
    backgroundColor: '#111111',
    padding: 16,
    borderRadius: 12,
    marginBottom: 12,
  },
  qualityLabel: {
    fontSize: 14,
    color: '#888888',
    marginBottom: 8,
  },
  qualityValue: {
    fontSize: 28,
    fontWeight: 'bold',
    color: '#00ff88',
    marginBottom: 12,
  },
  qualitySubtext: {
    fontSize: 12,
    color: '#666666',
    marginTop: 8,
  },
  progressBar: {
    height: 8,
    backgroundColor: '#1a1a1a',
    borderRadius: 4,
    overflow: 'hidden',
  },
  progressFill: {
    height: '100%',
    borderRadius: 4,
  },
  assetCard: {
    backgroundColor: '#111111',
    padding: 16,
    borderRadius: 12,
    marginBottom: 12,
  },
  assetRow: {
    flexDirection: 'row',
    justifyContent: 'space-between',
    alignItems: 'center',
    marginBottom: 12,
  },
  assetLabel: {
    fontSize: 16,
    color: '#ffffff',
    fontWeight: '600',
  },
  assetValue: {
    fontSize: 20,
    color: '#00ff88',
    fontWeight: 'bold',
  },
  infoTitle: {
    fontSize: 16,
    color: '#ffffff',
    fontWeight: '600',
    marginBottom: 12,
  },
  infoText: {
    fontSize: 14,
    color: '#888888',
    lineHeight: 20,
    marginBottom: 12,
  },
  errorText: {
    color: '#ff3366',
    fontSize: 16,
    textAlign: 'center',
    marginTop: 100,
  },
});
