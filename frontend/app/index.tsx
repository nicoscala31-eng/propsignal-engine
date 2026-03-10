import React, { useState, useEffect } from 'react';
import {
  View,
  Text,
  StyleSheet,
  TouchableOpacity,
  ScrollView,
  ActivityIndicator,
  RefreshControl,
  Alert
} from 'react-native';
import { SafeAreaView } from 'react-native-safe-area-context';
import { useRouter } from 'expo-router';

const BACKEND_URL = process.env.EXPO_PUBLIC_BACKEND_URL;

// Mock user ID for MVP (in production, this would come from auth)
const MOCK_USER_ID = '1773156899.291813';
const MOCK_PROFILE_ID = '1773156903.940538';

interface Signal {
  id: string;
  signal_type: 'BUY' | 'SELL' | 'NEXT';
  asset: 'EURUSD' | 'XAUUSD';
  market_regime: string;
  entry_price?: number;
  stop_loss?: number;
  take_profit_1?: number;
  take_profit_2?: number;
  confidence_score: number;
  success_probability?: number;
  strategy_type?: string;
  explanation?: string;
  next_reason?: string;
  prop_rule_safety: 'SAFE' | 'CAUTION' | 'BLOCKED';
  session: string;
  created_at: string;
}

export default function HomeScreen() {
  const router = useRouter();
  const [loading, setLoading] = useState(false);
  const [refreshing, setRefreshing] = useState(false);
  const [eurusdSignal, setEurusdSignal] = useState<Signal | null>(null);
  const [xauusdSignal, setXauusdSignal] = useState<Signal | null>(null);

  const fetchLatestSignals = async () => {
    try {
      // Fetch EURUSD signal
      const eurusdResponse = await fetch(
        `${BACKEND_URL}/api/users/${MOCK_USER_ID}/signals/latest?asset=EURUSD`
      );
      if (eurusdResponse.ok) {
        const data = await eurusdResponse.json();
        setEurusdSignal(data);
      }

      // Fetch XAUUSD signal
      const xauusdResponse = await fetch(
        `${BACKEND_URL}/api/users/${MOCK_USER_ID}/signals/latest?asset=XAUUSD`
      );
      if (xauusdResponse.ok) {
        const data = await xauusdResponse.json();
        setXauusdSignal(data);
      }
    } catch (error) {
      console.error('Error fetching signals:', error);
    }
  };

  const generateSignal = async (asset: 'EURUSD' | 'XAUUSD') => {
    setLoading(true);
    try {
      const response = await fetch(
        `${BACKEND_URL}/api/users/${MOCK_USER_ID}/signals/generate`,
        {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({
            asset: asset,
            prop_profile_id: MOCK_PROFILE_ID
          })
        }
      );

      if (response.ok) {
        const signal = await response.json();
        if (asset === 'EURUSD') {
          setEurusdSignal(signal);
        } else {
          setXauusdSignal(signal);
        }

        if (signal.signal_type !== 'NEXT') {
          Alert.alert(
            `${signal.signal_type} Signal`,
            `${asset}: ${signal.explanation || 'New signal generated'}`,
            [{ text: 'View Details', onPress: () => router.push(`/signal-detail?id=${signal.id}`) }]
          );
        }
      } else {
        Alert.alert('Error', 'Failed to generate signal');
      }
    } catch (error) {
      console.error('Error generating signal:', error);
      Alert.alert('Error', 'Network error occurred');
    } finally {
      setLoading(false);
    }
  };

  const onRefresh = async () => {
    setRefreshing(true);
    await fetchLatestSignals();
    setRefreshing(false);
  };

  useEffect(() => {
    fetchLatestSignals();
  }, []);

  const renderSignalCard = (signal: Signal | null, asset: 'EURUSD' | 'XAUUSD') => {
    if (!signal) {
      return (
        <View style={styles.signalCard}>
          <Text style={styles.assetTitle}>{asset}</Text>
          <Text style={styles.noSignalText}>No signal available</Text>
          <TouchableOpacity
            style={styles.generateButton}
            onPress={() => generateSignal(asset)}
            disabled={loading}
          >
            <Text style={styles.generateButtonText}>Generate Signal</Text>
          </TouchableOpacity>
        </View>
      );
    }

    const signalColor = 
      signal.signal_type === 'BUY' ? '#00ff88' : 
      signal.signal_type === 'SELL' ? '#ff3366' : 
      '#888888';

    return (
      <TouchableOpacity
        style={[styles.signalCard, { borderLeftColor: signalColor, borderLeftWidth: 4 }]}
        onPress={() => signal.signal_type !== 'NEXT' && router.push(`/signal-detail?id=${signal.id}`)}
      >
        <View style={styles.signalHeader}>
          <Text style={styles.assetTitle}>{asset}</Text>
          <View style={[styles.signalBadge, { backgroundColor: signalColor }]}>
            <Text style={styles.signalBadgeText}>{signal.signal_type}</Text>
          </View>
        </View>

        {signal.signal_type === 'NEXT' ? (
          <View>
            <Text style={styles.nextReasonText}>{signal.next_reason}</Text>
            <Text style={styles.regimeText}>Regime: {signal.market_regime}</Text>
            <TouchableOpacity
              style={styles.regenButton}
              onPress={() => generateSignal(asset)}
              disabled={loading}
            >
              <Text style={styles.regenButtonText}>Regenerate</Text>
            </TouchableOpacity>
          </View>
        ) : (
          <View>
            <View style={styles.priceRow}>
              <Text style={styles.priceLabel}>Entry:</Text>
              <Text style={styles.priceValue}>{signal.entry_price?.toFixed(5)}</Text>
            </View>
            <View style={styles.priceRow}>
              <Text style={styles.priceLabel}>Stop Loss:</Text>
              <Text style={[styles.priceValue, { color: '#ff3366' }]}>
                {signal.stop_loss?.toFixed(5)}
              </Text>
            </View>
            <View style={styles.priceRow}>
              <Text style={styles.priceLabel}>TP1:</Text>
              <Text style={[styles.priceValue, { color: '#00ff88' }]}>
                {signal.take_profit_1?.toFixed(5)}
              </Text>
            </View>

            <View style={styles.statsRow}>
              <View style={styles.statBox}>
                <Text style={styles.statLabel}>Confidence</Text>
                <Text style={styles.statValue}>{signal.confidence_score.toFixed(0)}%</Text>
              </View>
              <View style={styles.statBox}>
                <Text style={styles.statLabel}>Win Prob</Text>
                <Text style={styles.statValue}>{signal.success_probability?.toFixed(0)}%</Text>
              </View>
              <View style={styles.statBox}>
                <Text style={styles.statLabel}>Safety</Text>
                <Text style={[styles.statValue, {
                  color: signal.prop_rule_safety === 'SAFE' ? '#00ff88' :
                         signal.prop_rule_safety === 'CAUTION' ? '#ffaa00' : '#ff3366'
                }]}>
                  {signal.prop_rule_safety}
                </Text>
              </View>
            </View>

            <Text style={styles.explanationText} numberOfLines={2}>
              {signal.explanation}
            </Text>
          </View>
        )}
      </TouchableOpacity>
    );
  };

  return (
    <SafeAreaView style={styles.container} edges={['top']}>
      <View style={styles.header}>
        <Text style={styles.headerTitle}>PropSignal Engine</Text>
        <Text style={styles.headerSubtitle}>Professional Trading Signals</Text>
      </View>

      <ScrollView
        style={styles.content}
        refreshControl={
          <RefreshControl refreshing={refreshing} onRefresh={onRefresh} tintColor="#00ff88" />
        }
      >
        {renderSignalCard(eurusdSignal, 'EURUSD')}
        {renderSignalCard(xauusdSignal, 'XAUUSD')}

        <View style={styles.actionButtons}>
          <TouchableOpacity
            style={styles.actionButton}
            onPress={() => router.push('/analytics')}
          >
            <Text style={styles.actionButtonText}>📊 Analytics</Text>
          </TouchableOpacity>

          <TouchableOpacity
            style={styles.actionButton}
            onPress={() => router.push('/prop-profiles')}
          >
            <Text style={styles.actionButtonText}>⚙️ Prop Profiles</Text>
          </TouchableOpacity>
        </View>
      </ScrollView>

      {loading && (
        <View style={styles.loadingOverlay}>
          <ActivityIndicator size="large" color="#00ff88" />
          <Text style={styles.loadingText}>Analyzing market...</Text>
        </View>
      )}
    </SafeAreaView>
  );
}

const styles = StyleSheet.create({
  container: {
    flex: 1,
    backgroundColor: '#0a0a0a',
  },
  header: {
    padding: 20,
    backgroundColor: '#111111',
    borderBottomWidth: 1,
    borderBottomColor: '#222222',
  },
  headerTitle: {
    fontSize: 28,
    fontWeight: 'bold',
    color: '#00ff88',
    marginBottom: 4,
  },
  headerSubtitle: {
    fontSize: 14,
    color: '#888888',
  },
  content: {
    flex: 1,
    padding: 16,
  },
  signalCard: {
    backgroundColor: '#111111',
    borderRadius: 12,
    padding: 16,
    marginBottom: 16,
    borderWidth: 1,
    borderColor: '#222222',
  },
  signalHeader: {
    flexDirection: 'row',
    justifyContent: 'space-between',
    alignItems: 'center',
    marginBottom: 16,
  },
  assetTitle: {
    fontSize: 24,
    fontWeight: 'bold',
    color: '#ffffff',
  },
  signalBadge: {
    paddingHorizontal: 12,
    paddingVertical: 6,
    borderRadius: 6,
  },
  signalBadgeText: {
    color: '#0a0a0a',
    fontWeight: 'bold',
    fontSize: 14,
  },
  noSignalText: {
    color: '#666666',
    fontSize: 16,
    marginBottom: 16,
    textAlign: 'center',
  },
  generateButton: {
    backgroundColor: '#00ff88',
    padding: 14,
    borderRadius: 8,
    alignItems: 'center',
  },
  generateButtonText: {
    color: '#0a0a0a',
    fontWeight: 'bold',
    fontSize: 16,
  },
  priceRow: {
    flexDirection: 'row',
    justifyContent: 'space-between',
    marginBottom: 8,
  },
  priceLabel: {
    color: '#888888',
    fontSize: 14,
  },
  priceValue: {
    color: '#ffffff',
    fontSize: 16,
    fontWeight: 'bold',
  },
  statsRow: {
    flexDirection: 'row',
    marginTop: 12,
    marginBottom: 12,
    gap: 8,
  },
  statBox: {
    flex: 1,
    backgroundColor: '#0a0a0a',
    padding: 10,
    borderRadius: 8,
    alignItems: 'center',
  },
  statLabel: {
    color: '#666666',
    fontSize: 11,
    marginBottom: 4,
  },
  statValue: {
    color: '#00ff88',
    fontSize: 16,
    fontWeight: 'bold',
  },
  explanationText: {
    color: '#cccccc',
    fontSize: 13,
    lineHeight: 18,
    marginTop: 8,
  },
  nextReasonText: {
    color: '#cccccc',
    fontSize: 14,
    marginBottom: 12,
    lineHeight: 20,
  },
  regimeText: {
    color: '#666666',
    fontSize: 12,
    marginBottom: 12,
  },
  regenButton: {
    backgroundColor: '#222222',
    padding: 10,
    borderRadius: 6,
    alignItems: 'center',
  },
  regenButtonText: {
    color: '#00ff88',
    fontWeight: '600',
  },
  actionButtons: {
    flexDirection: 'row',
    gap: 12,
    marginTop: 8,
    marginBottom: 24,
  },
  actionButton: {
    flex: 1,
    backgroundColor: '#1a1a1a',
    padding: 16,
    borderRadius: 8,
    alignItems: 'center',
    borderWidth: 1,
    borderColor: '#222222',
  },
  actionButtonText: {
    color: '#ffffff',
    fontSize: 16,
    fontWeight: '600',
  },
  loadingOverlay: {
    position: 'absolute',
    top: 0,
    left: 0,
    right: 0,
    bottom: 0,
    backgroundColor: 'rgba(0, 0, 0, 0.85)',
    justifyContent: 'center',
    alignItems: 'center',
  },
  loadingText: {
    color: '#00ff88',
    marginTop: 12,
    fontSize: 16,
  },
});
