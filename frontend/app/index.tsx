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
  AppStateStatus,
  Modal
} from 'react-native';
import { SafeAreaView } from 'react-native-safe-area-context';
import { useRouter } from 'expo-router';
import Constants from 'expo-constants';
import { pushNotificationService, NotificationState } from '../services/PushNotificationService';

// Get backend URL from app.json extra config (works in production builds)
const BACKEND_URL = Constants.expoConfig?.extra?.backendUrl || process.env.EXPO_PUBLIC_BACKEND_URL || 'https://eurusd-alerts.preview.emergentagent.com';

// Mock user ID for MVP (in production, this would come from auth)
const MOCK_USER_ID = '1773156899.291813';
const MOCK_PROFILE_ID = '1773156903.940538';

// Auto-refresh interval (30 seconds)
const SIGNAL_POLL_INTERVAL = 30000;

interface MarketAnalysis {
  asset: string;
  reason: string;
  market_regime: string;
  session: string;
  waiting_for: string[];
  current_conditions: string[];
  recommendation: string;
}

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
  const [notificationState, setNotificationState] = useState<NotificationState>(NotificationState.UNKNOWN);
  const [autoScanEnabled, setAutoScanEnabled] = useState(false); // Disabled - backend scanner handles this
  const [backendScannerRunning, setBackendScannerRunning] = useState(false);
  const [pushToken, setPushToken] = useState<string | null>(null);
  const [notificationError, setNotificationError] = useState<string | null>(null);
  const [analysisModalVisible, setAnalysisModalVisible] = useState(false);
  const [currentAnalysis, setCurrentAnalysis] = useState<MarketAnalysis | null>(null);
  const [loadingAnalysis, setLoadingAnalysis] = useState(false);
  
  // Track previous signal types to detect new BUY/SELL
  const prevEurusdType = useRef<string | null>(null);
  const prevXauusdType = useRef<string | null>(null);
  const appState = useRef(AppState.currentState);

  // Initialize push notifications
  useEffect(() => {
    const initNotifications = async () => {
      // Check current permission status
      const currentState = await pushNotificationService.checkPermissionStatus();
      setNotificationState(currentState);
      
      // Set up state change listener
      pushNotificationService.onStateChange = (state) => {
        setNotificationState(state);
      };
      
      // Handle notification tap - navigate to signal detail
      pushNotificationService.onNotificationTap = (signalId: string) => {
        router.push(`/signal-detail?id=${signalId}`);
      };
      
      // If already enabled, update token
      if (currentState === NotificationState.ENABLED) {
        setPushToken(pushNotificationService.getToken());
      }
    };
    
    initNotifications();
    
    // Handle app state changes
    const subscription = AppState.addEventListener('change', handleAppStateChange);
    
    return () => {
      pushNotificationService.cleanup();
      subscription.remove();
    };
  }, []);

  // Enable push notifications handler
  const enablePushNotifications = async () => {
    setNotificationError(null);
    
    const result = await pushNotificationService.enableNotifications();
    
    if (result.success) {
      setPushToken(result.token || null);
      Alert.alert(
        '✅ Notifiche Attivate!',
        'Riceverai notifiche push quando vengono generati segnali BUY/SELL, anche con l\'app chiusa.',
        [{ text: 'OK' }]
      );
    } else {
      setNotificationError(result.error || 'Errore sconosciuto');
      Alert.alert(
        '❌ Errore Notifiche',
        result.error || 'Impossibile attivare le notifiche',
        [{ text: 'OK' }]
      );
    }
  };

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

  const fetchMarketAnalysis = async (asset: 'EURUSD' | 'XAUUSD') => {
    setLoadingAnalysis(true);
    try {
      const response = await fetch(`${BACKEND_URL}/api/market-analysis/${asset}`);
      if (response.ok) {
        const analysis = await response.json();
        setCurrentAnalysis(analysis);
        setAnalysisModalVisible(true);
      } else {
        // Fallback analysis if endpoint doesn't exist
        setCurrentAnalysis({
          asset: asset,
          reason: "Il mercato è attualmente in condizioni non favorevoli per operare.",
          market_regime: "CHAOTIC",
          session: getCurrentSession(),
          waiting_for: [
            "Trend più chiaro e definito",
            "Volatilità ridotta",
            "Supporti/Resistenze più evidenti",
            "Conferme da indicatori tecnici"
          ],
          current_conditions: [
            "Alta volatilità",
            "Movimento laterale senza direzione",
            "Mancanza di setup tecnici validi"
          ],
          recommendation: "Attendere condizioni di mercato più favorevoli prima di aprire posizioni. La pazienza è fondamentale nel trading."
        });
        setAnalysisModalVisible(true);
      }
    } catch (error) {
      console.error('Error fetching analysis:', error);
      // Fallback
      setCurrentAnalysis({
        asset: asset,
        reason: "Il mercato è attualmente in condizioni non favorevoli per operare.",
        market_regime: "CHAOTIC",
        session: getCurrentSession(),
        waiting_for: [
          "Trend più chiaro",
          "Volatilità più bassa",
          "Pattern tecnici riconoscibili"
        ],
        current_conditions: [
          "Condizioni di mercato instabili",
          "Nessun setup valido identificato"
        ],
        recommendation: "Attendere migliori condizioni di mercato."
      });
      setAnalysisModalVisible(true);
    } finally {
      setLoadingAnalysis(false);
    }
  };

  const getCurrentSession = (): string => {
    const hour = new Date().getUTCHours();
    if (hour >= 7 && hour < 16) return "London";
    if (hour >= 13 && hour < 22) return "New York";
    if (hour >= 0 && hour < 9) return "Tokyo";
    return "Off-Hours";
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
            <TouchableOpacity
              style={styles.nextButton}
              onPress={() => fetchMarketAnalysis(asset)}
              disabled={loadingAnalysis}
            >
              {loadingAnalysis ? (
                <ActivityIndicator color="#fff" size="small" />
              ) : (
                <>
                  <Text style={styles.nextButtonText}>NEXT</Text>
                  <Text style={styles.nextSubText}>Tap per analisi</Text>
                </>
              )}
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

        {/* Push Notification Enable Button */}
        <TouchableOpacity
          style={[
            styles.notificationButton,
            notificationState === NotificationState.ENABLED && styles.notificationButtonEnabled,
            notificationState === NotificationState.ENABLING && styles.notificationButtonEnabling,
            notificationState === NotificationState.REGISTERING && styles.notificationButtonEnabling,
            notificationState === NotificationState.FAILED && styles.notificationButtonFailed,
            notificationState === NotificationState.PERMISSION_DENIED && styles.notificationButtonFailed,
          ]}
          onPress={enablePushNotifications}
          disabled={
            notificationState === NotificationState.ENABLED ||
            notificationState === NotificationState.ENABLING ||
            notificationState === NotificationState.REGISTERING
          }
        >
          {(notificationState === NotificationState.ENABLING || 
            notificationState === NotificationState.REGISTERING) ? (
            <View style={styles.notificationButtonContent}>
              <ActivityIndicator size="small" color="#0a0a0a" />
              <Text style={styles.notificationButtonTextDark}>
                {notificationState === NotificationState.ENABLING 
                  ? 'Richiesta permessi...' 
                  : 'Registrazione...'}
              </Text>
            </View>
          ) : notificationState === NotificationState.ENABLED ? (
            <Text style={styles.notificationButtonTextDark}>✅ Notifiche Attive</Text>
          ) : notificationState === NotificationState.FAILED ? (
            <Text style={styles.notificationButtonText}>❌ Riprova Attivazione</Text>
          ) : notificationState === NotificationState.PERMISSION_DENIED ? (
            <Text style={styles.notificationButtonText}>⚠️ Permesso Negato - Riprova</Text>
          ) : (
            <Text style={styles.notificationButtonText}>🔔 Attiva Notifiche Push</Text>
          )}
        </TouchableOpacity>

        {/* Notification Error Message */}
        {notificationError && (
          <View style={styles.errorMessageContainer}>
            <Text style={styles.errorMessageText}>{notificationError}</Text>
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
          <Text style={[
            styles.notificationStatusText,
            notificationState === NotificationState.ENABLED && { color: '#00ff88' },
            notificationState === NotificationState.FAILED && { color: '#ff3366' },
          ]}>
            {notificationState === NotificationState.ENABLED 
              ? '🔔 Notifiche Push: Attive' 
              : notificationState === NotificationState.FAILED 
                ? '❌ Notifiche: Errore'
                : notificationState === NotificationState.PERMISSION_DENIED
                  ? '⚠️ Notifiche: Permesso negato'
                  : '🔕 Notifiche: Non attive'}
          </Text>
          {backendScannerRunning && (
            <Text style={styles.autoScanStatusText}>
              Backend scanner active - checking every 5s
            </Text>
          )}
          {notificationState === NotificationState.ENABLED && (
            <Text style={styles.notificationInfoText}>
              Riceverai notifiche anche con app chiusa
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

      {/* Market Analysis Modal */}
      <Modal
        visible={analysisModalVisible}
        transparent={true}
        animationType="slide"
        onRequestClose={() => setAnalysisModalVisible(false)}
      >
        <View style={styles.modalOverlay}>
          <View style={styles.modalContent}>
            <View style={styles.modalHeader}>
              <Text style={styles.modalTitle}>
                {currentAnalysis?.asset} - Analisi di Mercato
              </Text>
              <TouchableOpacity
                onPress={() => setAnalysisModalVisible(false)}
                style={styles.modalCloseButton}
              >
                <Text style={styles.modalCloseText}>✕</Text>
              </TouchableOpacity>
            </View>

            <ScrollView style={styles.modalBody}>
              {/* Reason */}
              <View style={styles.analysisSection}>
                <Text style={styles.analysisSectionTitle}>Perché NEXT?</Text>
                <Text style={styles.analysisText}>{currentAnalysis?.reason}</Text>
              </View>

              {/* Market Regime */}
              <View style={styles.analysisSection}>
                <Text style={styles.analysisSectionTitle}>Regime di Mercato</Text>
                <View style={styles.regimeBadge}>
                  <Text style={styles.regimeBadgeText}>{currentAnalysis?.market_regime}</Text>
                </View>
                <Text style={styles.sessionText}>Sessione: {currentAnalysis?.session}</Text>
              </View>

              {/* Current Conditions */}
              <View style={styles.analysisSection}>
                <Text style={styles.analysisSectionTitle}>Condizioni Attuali</Text>
                {currentAnalysis?.current_conditions.map((condition, index) => (
                  <View key={index} style={styles.bulletItem}>
                    <Text style={styles.bulletDot}>•</Text>
                    <Text style={styles.bulletText}>{condition}</Text>
                  </View>
                ))}
              </View>

              {/* Waiting For */}
              <View style={styles.analysisSection}>
                <Text style={styles.analysisSectionTitle}>In Attesa Di...</Text>
                {currentAnalysis?.waiting_for.map((item, index) => (
                  <View key={index} style={styles.bulletItem}>
                    <Text style={styles.bulletDot}>⏳</Text>
                    <Text style={styles.bulletText}>{item}</Text>
                  </View>
                ))}
              </View>

              {/* Recommendation */}
              <View style={[styles.analysisSection, styles.recommendationSection]}>
                <Text style={styles.analysisSectionTitle}>Raccomandazione</Text>
                <Text style={styles.recommendationText}>{currentAnalysis?.recommendation}</Text>
              </View>
            </ScrollView>

            <TouchableOpacity
              style={styles.modalCloseButtonBottom}
              onPress={() => setAnalysisModalVisible(false)}
            >
              <Text style={styles.modalCloseButtonText}>Chiudi</Text>
            </TouchableOpacity>
          </View>
        </View>
      </Modal>
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
  notificationInfoText: {
    color: '#00cc66',
    fontSize: 11,
    marginTop: 4,
    fontStyle: 'italic',
  },
  // Push Notification Button Styles
  notificationButton: {
    backgroundColor: '#222222',
    padding: 16,
    borderRadius: 12,
    alignItems: 'center',
    marginBottom: 16,
    borderWidth: 2,
    borderColor: '#00ff88',
  },
  notificationButtonEnabled: {
    backgroundColor: '#00ff88',
    borderColor: '#00ff88',
  },
  notificationButtonEnabling: {
    backgroundColor: '#ffaa00',
    borderColor: '#ffaa00',
  },
  notificationButtonFailed: {
    backgroundColor: '#1a1a1a',
    borderColor: '#ff3366',
  },
  notificationButtonContent: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: 8,
  },
  notificationButtonText: {
    color: '#00ff88',
    fontSize: 16,
    fontWeight: '600',
  },
  notificationButtonTextDark: {
    color: '#0a0a0a',
    fontSize: 16,
    fontWeight: '600',
  },
  errorMessageContainer: {
    backgroundColor: '#1a0a0a',
    borderRadius: 8,
    padding: 12,
    marginBottom: 16,
    borderWidth: 1,
    borderColor: '#ff3366',
  },
  errorMessageText: {
    color: '#ff6666',
    fontSize: 12,
    textAlign: 'center',
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
  // NEXT Button Styles
  nextButton: {
    backgroundColor: '#333333',
    paddingVertical: 20,
    paddingHorizontal: 40,
    borderRadius: 12,
    alignItems: 'center',
    borderWidth: 2,
    borderColor: '#ffaa00',
  },
  nextButtonText: {
    color: '#ffaa00',
    fontSize: 32,
    fontWeight: 'bold',
  },
  nextSubText: {
    color: '#888888',
    fontSize: 12,
    marginTop: 4,
  },
  // Modal Styles
  modalOverlay: {
    flex: 1,
    backgroundColor: 'rgba(0, 0, 0, 0.9)',
    justifyContent: 'center',
    alignItems: 'center',
  },
  modalContent: {
    backgroundColor: '#1a1a1a',
    borderRadius: 16,
    width: '90%',
    maxHeight: '80%',
    borderWidth: 1,
    borderColor: '#333333',
  },
  modalHeader: {
    flexDirection: 'row',
    justifyContent: 'space-between',
    alignItems: 'center',
    padding: 16,
    borderBottomWidth: 1,
    borderBottomColor: '#333333',
  },
  modalTitle: {
    color: '#ffaa00',
    fontSize: 18,
    fontWeight: 'bold',
  },
  modalCloseButton: {
    padding: 8,
  },
  modalCloseText: {
    color: '#888888',
    fontSize: 20,
  },
  modalBody: {
    padding: 16,
  },
  analysisSection: {
    marginBottom: 20,
  },
  analysisSectionTitle: {
    color: '#00ff88',
    fontSize: 14,
    fontWeight: 'bold',
    marginBottom: 8,
    textTransform: 'uppercase',
  },
  analysisText: {
    color: '#ffffff',
    fontSize: 15,
    lineHeight: 22,
  },
  regimeBadge: {
    backgroundColor: '#ff3366',
    paddingVertical: 6,
    paddingHorizontal: 12,
    borderRadius: 6,
    alignSelf: 'flex-start',
    marginBottom: 8,
  },
  regimeBadgeText: {
    color: '#ffffff',
    fontSize: 14,
    fontWeight: 'bold',
  },
  sessionText: {
    color: '#888888',
    fontSize: 13,
  },
  bulletItem: {
    flexDirection: 'row',
    marginBottom: 6,
  },
  bulletDot: {
    color: '#ffaa00',
    fontSize: 16,
    marginRight: 8,
  },
  bulletText: {
    color: '#cccccc',
    fontSize: 14,
    flex: 1,
  },
  recommendationSection: {
    backgroundColor: '#222222',
    padding: 12,
    borderRadius: 8,
    borderLeftWidth: 3,
    borderLeftColor: '#00ff88',
  },
  recommendationText: {
    color: '#ffffff',
    fontSize: 14,
    lineHeight: 20,
    fontStyle: 'italic',
  },
  modalCloseButtonBottom: {
    backgroundColor: '#333333',
    padding: 16,
    alignItems: 'center',
    borderBottomLeftRadius: 16,
    borderBottomRightRadius: 16,
  },
  modalCloseButtonText: {
    color: '#ffffff',
    fontSize: 16,
    fontWeight: '600',
  },
});
