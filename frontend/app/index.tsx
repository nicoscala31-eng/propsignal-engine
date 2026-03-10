import React, { useState, useEffect, useCallback, useRef } from 'react';
import {
  View,
  Text,
  StyleSheet,
  TouchableOpacity,
  ScrollView,
  ActivityIndicator,
  RefreshControl,
  Alert,
  AppState,
  AppStateStatus
} from 'react-native';
import { SafeAreaView } from 'react-native-safe-area-context';
import { useRouter } from 'expo-router';
import { notificationService } from '../services/NotificationService';

const BACKEND_URL = process.env.EXPO_PUBLIC_BACKEND_URL;

// Mock user ID for MVP (in production, this would come from auth)
const MOCK_USER_ID = '1773156899.291813';
const MOCK_PROFILE_ID = '1773156903.940538';

// Auto-refresh interval (30 seconds)
const SIGNAL_POLL_INTERVAL = 30000;

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
  live_bid?: number;
  live_ask?: number;
  live_spread_pips?: number;
  data_provider?: string;
  created_at: string;
}

interface LivePrice {
  bid: number;
  ask: number;
  mid: number;
  spread_pips: number;
  timestamp: string;
  status: 'LIVE' | 'ERROR';
  error?: string;
}

interface ProviderStatus {
  provider: string;
  is_production: boolean;
  prices: {
    EURUSD?: LivePrice;
    XAUUSD?: LivePrice;
  };
}

export default function HomeScreen() {
  const router = useRouter();
  const [loading, setLoading] = useState(false);
  const [refreshing, setRefreshing] = useState(false);
  const [eurusdSignal, setEurusdSignal] = useState<Signal | null>(null);
  const [xauusdSignal, setXauusdSignal] = useState<Signal | null>(null);
  const [providerStatus, setProviderStatus] = useState<ProviderStatus | null>(null);
  const [lastUpdate, setLastUpdate] = useState<Date | null>(null);
  const [notificationsEnabled, setNotificationsEnabled] = useState(false);
  const [autoScanEnabled, setAutoScanEnabled] = useState(false); // Disabled - backend scanner handles this
  const [backendScannerRunning, setBackendScannerRunning] = useState(false);
  
  // Track previous signal types to detect new BUY/SELL
  const prevEurusdType = useRef<string | null>(null);
  const prevXauusdType = useRef<string | null>(null);
  const appState = useRef(AppState.currentState);

  // Initialize notifications
  useEffect(() => {
    const initNotifications = async () => {
      const token = await notificationService.initialize();
      if (token) {
        setNotificationsEnabled(true);
        console.log('Notifications enabled');
      }
      
      // Handle notification tap - navigate to signal detail
      notificationService.onNotificationTap = (signalId: string) => {
        router.push(`/signal-detail?id=${signalId}`);
      };
    };
    
    initNotifications();
    
    // Handle app state changes
    const subscription = AppState.addEventListener('change', handleAppStateChange);
    
    return () => {
      notificationService.cleanup();
      subscription.remove();
    };
  }, []);

  const handleAppStateChange = (nextAppState: AppStateStatus) => {
    if (appState.current.match(/inactive|background/) && nextAppState === 'active') {
      // App came to foreground - refresh data
      console.log('App came to foreground, refreshing...');
      fetchLatestSignals();
      fetchProviderStatus();
    }
    appState.current = nextAppState;
  };

  const fetchProviderStatus = useCallback(async () => {
    try {
      const response = await fetch(`${BACKEND_URL}/api/provider/live-prices`);
      if (response.ok) {
        const data = await response.json();
        setProviderStatus(data);
        setLastUpdate(new Date());
      }
    } catch (error) {
      console.error('Error fetching provider status:', error);
    }
  }, []);

  const fetchLatestSignals = async () => {
    try {
      const [eurusdResponse, xauusdResponse] = await Promise.all([
        fetch(`${BACKEND_URL}/api/users/${MOCK_USER_ID}/signals/latest?asset=EURUSD`),
        fetch(`${BACKEND_URL}/api/users/${MOCK_USER_ID}/signals/latest?asset=XAUUSD`)
      ]);

      if (eurusdResponse.ok) {
        const data = await eurusdResponse.json();
        setEurusdSignal(data);
      }

      if (xauusdResponse.ok) {
        const data = await xauusdResponse.json();
        setXauusdSignal(data);
      }
    } catch (error) {
      console.error('Error fetching signals:', error);
    }
  };

  // Auto-scan for new signals
  const autoScanForSignals = useCallback(async () => {
    if (!autoScanEnabled) return;
    
    console.log('Auto-scanning for signals...');
    
    for (const asset of ['EURUSD', 'XAUUSD'] as const) {
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
          const prevType = asset === 'EURUSD' ? prevEurusdType.current : prevXauusdType.current;
          
          // Update state
          if (asset === 'EURUSD') {
            setEurusdSignal(signal);
            prevEurusdType.current = signal.signal_type;
          } else {
            setXauusdSignal(signal);
            prevXauusdType.current = signal.signal_type;
          }
          
          // Send notification for new BUY/SELL signals
          if (signal.signal_type !== 'NEXT' && prevType !== signal.signal_type && notificationsEnabled) {
            if (signal.signal_type === 'BUY') {
              await notificationService.sendBuyNotification(
                asset,
                signal.entry_price || 0,
                signal.confidence_score || 0,
                signal.id
              );
            } else if (signal.signal_type === 'SELL') {
              await notificationService.sendSellNotification(
                asset,
                signal.entry_price || 0,
                signal.confidence_score || 0,
                signal.id
              );
            }
          }
        }
      } catch (error) {
        console.error(`Auto-scan error for ${asset}:`, error);
      }
    }
    
    await fetchProviderStatus();
  }, [autoScanEnabled, notificationsEnabled, fetchProviderStatus]);

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
          prevEurusdType.current = signal.signal_type;
        } else {
          setXauusdSignal(signal);
          prevXauusdType.current = signal.signal_type;
        }

        // Refresh live prices after signal generation
        await fetchProviderStatus();

        if (signal.signal_type !== 'NEXT') {
          // Send notification
          if (notificationsEnabled) {
            if (signal.signal_type === 'BUY') {
              await notificationService.sendBuyNotification(asset, signal.entry_price, signal.confidence_score, signal.id);
            } else {
              await notificationService.sendSellNotification(asset, signal.entry_price, signal.confidence_score, signal.id);
            }
          }
          
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
    await Promise.all([fetchLatestSignals(), fetchProviderStatus()]);
    setRefreshing(false);
  };

  useEffect(() => {
    fetchLatestSignals();
    fetchProviderStatus();

    // Auto-refresh prices every 10 seconds
    const priceInterval = setInterval(fetchProviderStatus, 10000);
    
    return () => {
      clearInterval(priceInterval);
    };
  }, [fetchProviderStatus]);
  
  // Check backend scanner status instead of frontend auto-scan
  useEffect(() => {
    const checkScannerStatus = async () => {
      try {
        const response = await fetch(`${BACKEND_URL}/api/scanner/status`);
        if (response.ok) {
          const data = await response.json();
          setBackendScannerRunning(data.is_running);
        }
      } catch (error) {
        console.log('Could not check scanner status');
      }
    };
    
    checkScannerStatus();
    const interval = setInterval(checkScannerStatus, 30000);
    return () => clearInterval(interval);
  }, []);

  const toggleBackendScanner = async () => {
    try {
      const endpoint = backendScannerRunning ? 'stop' : 'start';
      const response = await fetch(`${BACKEND_URL}/api/scanner/${endpoint}`, {
        method: 'POST'
      });
      if (response.ok) {
        setBackendScannerRunning(!backendScannerRunning);
        Alert.alert(
          backendScannerRunning ? 'Scanner Stopped' : 'Scanner Started',
          backendScannerRunning 
            ? 'Background signal scanning has been stopped.'
            : 'Background scanner will check for BUY/SELL signals every 30 seconds and send push notifications.',
          [{ text: 'OK' }]
        );
      }
    } catch (error) {
      Alert.alert('Error', 'Could not toggle scanner');
    }
  };

  const getLivePrice = (asset: 'EURUSD' | 'XAUUSD'): LivePrice | null => {
    return providerStatus?.prices?.[asset] || null;
  };

  const formatPrice = (price: number | undefined, asset: 'EURUSD' | 'XAUUSD'): string => {
    if (price === undefined) return '--';
    return asset === 'EURUSD' ? price.toFixed(5) : price.toFixed(2);
  };

  const renderLivePriceBar = (asset: 'EURUSD' | 'XAUUSD') => {
    const livePrice = getLivePrice(asset);
    
    if (!livePrice || livePrice.status === 'ERROR') {
      return (
        <View style={styles.priceBarError}>
          <Text style={styles.priceBarErrorText}>
            Price unavailable - {livePrice?.error || 'Connecting...'}
          </Text>
        </View>
      );
    }

    return (
      <View style={styles.priceBar}>
        <View style={styles.priceCell}>
          <Text style={styles.priceCellLabel}>BID</Text>
          <Text style={styles.priceCellValue}>{formatPrice(livePrice.bid, asset)}</Text>
        </View>
        <View style={styles.priceCellSpread}>
          <Text style={styles.spreadLabel}>SPREAD</Text>
          <Text style={styles.spreadValue}>{livePrice.spread_pips.toFixed(1)}</Text>
        </View>
        <View style={styles.priceCell}>
          <Text style={styles.priceCellLabel}>ASK</Text>
          <Text style={styles.priceCellValue}>{formatPrice(livePrice.ask, asset)}</Text>
        </View>
      </View>
    );
  };

  const renderSignalCard = (signal: Signal | null, asset: 'EURUSD' | 'XAUUSD') => {
    const livePrice = getLivePrice(asset);

    return (
      <View style={styles.signalCard}>
        <View style={styles.signalHeader}>
          <Text style={styles.assetTitle}>{asset}</Text>
          {signal && (
            <View style={[
              styles.signalBadge, 
              { 
                backgroundColor: signal.signal_type === 'BUY' ? '#00ff88' : 
                                signal.signal_type === 'SELL' ? '#ff3366' : '#666666'
              }
            ]}>
              <Text style={styles.signalBadgeText}>{signal.signal_type}</Text>
            </View>
          )}
        </View>

        {/* Live Price Bar */}
        {renderLivePriceBar(asset)}

        {!signal ? (
          <View style={styles.noSignalContainer}>
            <Text style={styles.noSignalText}>No signal available</Text>
            <TouchableOpacity
              style={styles.generateButton}
              onPress={() => generateSignal(asset)}
              disabled={loading}
            >
              <Text style={styles.generateButtonText}>Generate Signal</Text>
            </TouchableOpacity>
          </View>
        ) : signal.signal_type === 'NEXT' ? (
          <View style={styles.nextSignalContainer}>
            <Text style={styles.nextReasonText}>{signal.next_reason}</Text>
            <View style={styles.metaRow}>
              <Text style={styles.metaLabel}>Regime:</Text>
              <Text style={styles.metaValue}>{signal.market_regime}</Text>
            </View>
            <View style={styles.metaRow}>
              <Text style={styles.metaLabel}>Session:</Text>
              <Text style={styles.metaValue}>{signal.session}</Text>
            </View>
            {signal.data_provider && (
              <View style={styles.metaRow}>
                <Text style={styles.metaLabel}>Provider:</Text>
                <Text style={[styles.metaValue, { color: '#00ff88' }]}>{signal.data_provider}</Text>
              </View>
            )}
            <TouchableOpacity
              style={styles.regenButton}
              onPress={() => generateSignal(asset)}
              disabled={loading}
            >
              <Text style={styles.regenButtonText}>Regenerate Signal</Text>
            </TouchableOpacity>
          </View>
        ) : (
          <TouchableOpacity
            onPress={() => router.push(`/signal-detail?id=${signal.id}`)}
            style={styles.tradeSignalContainer}
          >
            <View style={styles.priceRow}>
              <Text style={styles.priceLabel}>Entry:</Text>
              <Text style={styles.priceValue}>{formatPrice(signal.entry_price, asset)}</Text>
            </View>
            <View style={styles.priceRow}>
              <Text style={styles.priceLabel}>Stop Loss:</Text>
              <Text style={[styles.priceValue, { color: '#ff3366' }]}>
                {formatPrice(signal.stop_loss, asset)}
              </Text>
            </View>
            <View style={styles.priceRow}>
              <Text style={styles.priceLabel}>TP1:</Text>
              <Text style={[styles.priceValue, { color: '#00ff88' }]}>
                {formatPrice(signal.take_profit_1, asset)}
              </Text>
            </View>

            <View style={styles.statsRow}>
              <View style={styles.statBox}>
                <Text style={styles.statLabel}>Confidence</Text>
                <Text style={styles.statValue}>{signal.confidence_score.toFixed(0)}%</Text>
              </View>
              <View style={styles.statBox}>
                <Text style={styles.statLabel}>Win Prob</Text>
                <Text style={styles.statValue}>{signal.success_probability?.toFixed(0) || '--'}%</Text>
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

            {signal.explanation && (
              <Text style={styles.explanationText} numberOfLines={2}>
                {signal.explanation}
              </Text>
            )}

            <View style={styles.tapHint}>
              <Text style={styles.tapHintText}>Tap for details</Text>
            </View>
          </TouchableOpacity>
        )}
      </View>
    );
  };

  return (
    <SafeAreaView style={styles.container} edges={['top']}>
      <View style={styles.header}>
        <Text style={styles.headerTitle}>PropSignal Engine</Text>
        <View style={styles.headerRow}>
          <Text style={styles.headerSubtitle}>Professional Trading Signals</Text>
          {providerStatus && (
            <View style={[
              styles.providerBadge,
              { backgroundColor: providerStatus.is_production ? '#00ff88' : '#ff9500' }
            ]}>
              <Text style={styles.providerBadgeText}>
                {providerStatus.is_production ? 'LIVE' : 'SIM'}
              </Text>
            </View>
          )}
        </View>
        {lastUpdate && (
          <Text style={styles.lastUpdateText}>
            Last update: {lastUpdate.toLocaleTimeString()}
          </Text>
        )}
      </View>

      <ScrollView
        style={styles.content}
        refreshControl={
          <RefreshControl refreshing={refreshing} onRefresh={onRefresh} tintColor="#00ff88" />
        }
      >
        {renderSignalCard(eurusdSignal, 'EURUSD')}
        {renderSignalCard(xauusdSignal, 'XAUUSD')}

        {/* Provider Status Card */}
        {providerStatus && (
          <View style={styles.providerCard}>
            <Text style={styles.providerCardTitle}>Data Provider</Text>
            <View style={styles.providerInfo}>
              <Text style={styles.providerName}>{providerStatus.provider}</Text>
              <Text style={[
                styles.providerMode,
                { color: providerStatus.is_production ? '#00ff88' : '#ff9500' }
              ]}>
                {providerStatus.is_production ? 'Production Mode' : 'Simulation Mode'}
              </Text>
            </View>
          </View>
        )}

        <View style={styles.actionButtons}>
          <TouchableOpacity
            style={[
              styles.actionButton, 
              backendScannerRunning && styles.actionButtonActive
            ]}
            onPress={toggleBackendScanner}
          >
            <Text style={[
              styles.actionButtonText,
              backendScannerRunning && { color: '#0a0a0a' }
            ]}>
              {backendScannerRunning ? 'Scanner ON' : 'Scanner OFF'}
            </Text>
          </TouchableOpacity>
          <TouchableOpacity
            style={styles.actionButton}
            onPress={() => router.push('/analytics')}
          >
            <Text style={styles.actionButtonText}>Analytics</Text>
          </TouchableOpacity>
        </View>
        
        {/* Notification Status */}
        <View style={styles.notificationStatus}>
          <Text style={styles.notificationStatusText}>
            Notifications: {notificationsEnabled ? 'Enabled' : 'Disabled'}
          </Text>
          {backendScannerRunning && (
            <Text style={styles.autoScanStatusText}>
              Backend scanner active - checking every 30s
            </Text>
          )}
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
  headerRow: {
    flexDirection: 'row',
    alignItems: 'center',
    justifyContent: 'space-between',
  },
  headerSubtitle: {
    fontSize: 14,
    color: '#888888',
  },
  providerBadge: {
    paddingHorizontal: 8,
    paddingVertical: 3,
    borderRadius: 4,
  },
  providerBadgeText: {
    fontSize: 10,
    fontWeight: 'bold',
    color: '#000000',
  },
  lastUpdateText: {
    fontSize: 11,
    color: '#666666',
    marginTop: 4,
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
    marginBottom: 12,
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
  priceBar: {
    flexDirection: 'row',
    backgroundColor: '#0a0a0a',
    borderRadius: 8,
    padding: 10,
    marginBottom: 12,
    justifyContent: 'space-between',
    alignItems: 'center',
  },
  priceBarError: {
    backgroundColor: '#1a0a0a',
    borderRadius: 8,
    padding: 12,
    marginBottom: 12,
    borderWidth: 1,
    borderColor: '#ff3366',
  },
  priceBarErrorText: {
    color: '#ff6666',
    fontSize: 12,
    textAlign: 'center',
  },
  priceCell: {
    alignItems: 'center',
    flex: 1,
  },
  priceCellSpread: {
    alignItems: 'center',
    backgroundColor: '#1a1a1a',
    paddingHorizontal: 12,
    paddingVertical: 6,
    borderRadius: 6,
  },
  priceCellLabel: {
    fontSize: 10,
    color: '#666666',
    marginBottom: 2,
  },
  priceCellValue: {
    fontSize: 16,
    fontWeight: 'bold',
    color: '#ffffff',
  },
  spreadLabel: {
    fontSize: 9,
    color: '#666666',
    marginBottom: 1,
  },
  spreadValue: {
    fontSize: 12,
    fontWeight: 'bold',
    color: '#00ff88',
  },
  noSignalContainer: {
    alignItems: 'center',
    paddingVertical: 20,
  },
  noSignalText: {
    color: '#666666',
    fontSize: 16,
    marginBottom: 16,
  },
  generateButton: {
    backgroundColor: '#00ff88',
    padding: 14,
    borderRadius: 8,
    alignItems: 'center',
    width: '100%',
  },
  generateButtonText: {
    color: '#0a0a0a',
    fontWeight: 'bold',
    fontSize: 16,
  },
  nextSignalContainer: {
    paddingVertical: 8,
  },
  nextReasonText: {
    color: '#cccccc',
    fontSize: 14,
    marginBottom: 12,
    lineHeight: 20,
  },
  metaRow: {
    flexDirection: 'row',
    marginBottom: 6,
  },
  metaLabel: {
    color: '#666666',
    fontSize: 12,
    width: 70,
  },
  metaValue: {
    color: '#ffffff',
    fontSize: 12,
    fontWeight: '500',
  },
  regenButton: {
    backgroundColor: '#222222',
    padding: 12,
    borderRadius: 6,
    alignItems: 'center',
    marginTop: 12,
  },
  regenButtonText: {
    color: '#00ff88',
    fontWeight: '600',
  },
  tradeSignalContainer: {
    paddingVertical: 8,
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
  tapHint: {
    alignItems: 'center',
    marginTop: 12,
    paddingTop: 8,
    borderTopWidth: 1,
    borderTopColor: '#222222',
  },
  tapHintText: {
    color: '#666666',
    fontSize: 12,
  },
  providerCard: {
    backgroundColor: '#111111',
    borderRadius: 12,
    padding: 16,
    marginBottom: 16,
    borderWidth: 1,
    borderColor: '#222222',
  },
  providerCardTitle: {
    fontSize: 14,
    fontWeight: '600',
    color: '#888888',
    marginBottom: 8,
  },
  providerInfo: {
    flexDirection: 'row',
    justifyContent: 'space-between',
    alignItems: 'center',
  },
  providerName: {
    fontSize: 16,
    fontWeight: 'bold',
    color: '#ffffff',
  },
  providerMode: {
    fontSize: 12,
    fontWeight: '500',
  },
  actionButtons: {
    flexDirection: 'row',
    gap: 12,
    marginTop: 8,
    marginBottom: 12,
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
  actionButtonActive: {
    backgroundColor: '#00ff88',
    borderColor: '#00ff88',
  },
  actionButtonText: {
    color: '#ffffff',
    fontSize: 16,
    fontWeight: '600',
  },
  notificationStatus: {
    backgroundColor: '#111111',
    borderRadius: 8,
    padding: 12,
    marginBottom: 24,
    alignItems: 'center',
  },
  notificationStatusText: {
    color: '#666666',
    fontSize: 12,
  },
  autoScanStatusText: {
    color: '#00ff88',
    fontSize: 12,
    marginTop: 4,
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
