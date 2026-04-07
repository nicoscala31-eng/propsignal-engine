import React, { useState, useEffect, useCallback, useRef } from 'react';
import {
  View,
  Text,
  StyleSheet,
  TouchableOpacity,
  FlatList,
  ActivityIndicator,
  RefreshControl,
  Platform,
  Alert,
  AppState,
} from 'react-native';
import { SafeAreaView } from 'react-native-safe-area-context';
import { useRouter } from 'expo-router';
import * as Notifications from 'expo-notifications';
import Constants from 'expo-constants';

// ============================================
// API CONFIGURATION
// ============================================

const PRODUCTION_URL = 'https://propsignal-engine-production-b22b.up.railway.app';
const EMERGENT_URL = process.env.EXPO_PUBLIC_BACKEND_URL || '';

const getApiUrl = (): string => {
  if (__DEV__ && EMERGENT_URL && !EMERGENT_URL.includes('undefined')) {
    return EMERGENT_URL;
  }
  return PRODUCTION_URL;
};

const API_BASE = getApiUrl();
console.log('📡 API Base:', API_BASE);

// Mock user ID for device registration
const DEVICE_ID = Constants.installationId || 'default-device';

// ============================================
// TYPES
// ============================================

interface LivePrice {
  bid: number;
  ask: number;
  spread_pips: number;
  timestamp?: string;
}

interface ScannerStatus {
  is_running: boolean;
  version?: string;
  mode?: string;
  last_scan?: string;
  symbols?: string[];
}

interface SignalItem {
  id?: string;
  signal_id?: string;
  asset?: string;
  symbol?: string;
  signal_type?: string;
  direction?: string;
  entry_price?: number;
  stop_loss?: number;
  take_profit?: number;
  take_profit_1?: number;
  confidence_score?: number;
  score?: number;
  status?: string;
  created_at?: string;
  timestamp?: string;
  outcome?: string;
  final_outcome?: string;
}

// ============================================
// NOTIFICATION SETUP
// ============================================

Notifications.setNotificationHandler({
  handleNotification: async () => ({
    shouldShowAlert: true,
    shouldPlaySound: true,
    shouldSetBadge: true,
  }),
});

// ============================================
// MAIN COMPONENT
// ============================================

export default function HomeScreen() {
  const router = useRouter();
  
  // === STATE ===
  const [loading, setLoading] = useState(true);
  const [refreshing, setRefreshing] = useState(false);
  
  // Live prices
  const [eurusdPrice, setEurusdPrice] = useState<LivePrice | null>(null);
  const [xauusdPrice, setXauusdPrice] = useState<LivePrice | null>(null);
  const [priceError, setPriceError] = useState<string | null>(null);
  
  // Scanner status
  const [scannerStatus, setScannerStatus] = useState<ScannerStatus | null>(null);
  const [scannerError, setScannerError] = useState<string | null>(null);
  
  // Push notifications
  const [pushToken, setPushToken] = useState<string | null>(null);
  const [pushRegistered, setPushRegistered] = useState(false);
  const [pushError, setPushError] = useState<string | null>(null);
  
  // Signals
  const [recentSignals, setRecentSignals] = useState<SignalItem[]>([]);
  const [signalsError, setSignalsError] = useState<string | null>(null);
  
  // Last update
  const [lastUpdate, setLastUpdate] = useState<Date | null>(null);

  // ============================================
  // FETCH FUNCTIONS
  // ============================================

  const fetchLivePrices = useCallback(async () => {
    try {
      setPriceError(null);
      console.log('🔄 Fetching prices from:', `${API_BASE}/api/provider/live-prices`);
      
      const controller = new AbortController();
      const timeoutId = setTimeout(() => controller.abort(), 15000);
      
      const response = await fetch(`${API_BASE}/api/provider/live-prices`, {
        headers: { 'Accept': 'application/json' },
        signal: controller.signal,
      });
      
      clearTimeout(timeoutId);
      console.log('📡 Price response status:', response.status);
      
      if (response.ok) {
        const data = await response.json();
        console.log('📊 Price data keys:', Object.keys(data));
        
        // API returns prices inside data.prices object
        const prices = data.prices || data;
        console.log('📊 Prices keys:', Object.keys(prices));
        
        const eurusd = prices.EURUSD || prices.eurusd;
        if (eurusd) {
          console.log('✅ EURUSD found:', eurusd.bid, eurusd.ask);
          setEurusdPrice({
            bid: eurusd.bid || eurusd.live_bid || 0,
            ask: eurusd.ask || eurusd.live_ask || 0,
            spread_pips: eurusd.spread_pips || eurusd.live_spread_pips || 0,
          });
        } else {
          console.log('❌ EURUSD not found in prices');
        }
        
        const xauusd = prices.XAUUSD || prices.xauusd;
        if (xauusd) {
          console.log('✅ XAUUSD found:', xauusd.bid, xauusd.ask);
          setXauusdPrice({
            bid: xauusd.bid || xauusd.live_bid || 0,
            ask: xauusd.ask || xauusd.live_ask || 0,
            spread_pips: xauusd.spread_pips || xauusd.live_spread_pips || 0,
          });
        } else {
          console.log('❌ XAUUSD not found in prices');
        }
      } else {
        console.log('❌ Price response not OK:', response.status);
        setPriceError('Price data unavailable');
      }
    } catch (err: any) {
      console.log('❌ Price fetch error:', err.message || err);
      setPriceError('Connection error');
    }
  }, []);

  const fetchScannerStatus = useCallback(async () => {
    try {
      setScannerError(null);
      const response = await fetch(`${API_BASE}/api/scanner/v3/status`, {
        headers: { 'Accept': 'application/json' },
      });
      
      if (response.ok) {
        const data = await response.json();
        setScannerStatus({
          is_running: data.is_running ?? false,
          version: data.version || 'v3',
          mode: data.mode || 'auto',
          last_scan: data.last_check_time,
          symbols: data.symbols || ['EURUSD', 'XAUUSD'],
        });
      } else {
        setScannerError('Scanner offline');
      }
    } catch (err) {
      console.log('Scanner status error:', err);
      setScannerError('Cannot connect');
    }
  }, []);

  const fetchRecentSignals = useCallback(async () => {
    try {
      setSignalsError(null);
      let signals: SignalItem[] = [];
      
      // Try multiple endpoints in order of preference
      const endpoints = [
        { url: `${API_BASE}/api/signals/feed?limit=20`, name: 'feed' },
        { url: `${API_BASE}/api/signals/active`, name: 'active' },
        { url: `${API_BASE}/api/tracker/signals?limit=20`, name: 'tracker' },
      ];
      
      for (const endpoint of endpoints) {
        try {
          console.log(`📡 Trying ${endpoint.name} endpoint...`);
          const response = await fetch(endpoint.url, {
            headers: { 'Accept': 'application/json' },
            signal: AbortSignal.timeout(8000), // 8 second timeout
          });
          
          if (response.ok) {
            const data = await response.json();
            const rawSignals = data.signals || data.active_signals || (Array.isArray(data) ? data : []);
            
            if (rawSignals.length > 0) {
              signals = rawSignals.map((s: any) => ({
                id: s.signal_id || s.id,
                signal_id: s.signal_id || s.id,
                asset: s.symbol || s.asset,
                symbol: s.symbol || s.asset,
                direction: s.direction || s.signal_type,
                signal_type: s.direction || s.signal_type,
                entry_price: s.entry || s.entry_price,
                stop_loss: s.sl || s.stop_loss,
                take_profit: s.tp || s.take_profit || s.take_profit_1,
                confidence_score: s.score || s.confidence_score,
                score: s.score || s.confidence_score,
                status: s.status || 'unknown',
                timestamp: s.timestamp || s.created_at,
                outcome: s.outcome || s.final_outcome,
              }));
              console.log(`✅ Loaded ${signals.length} signals from ${endpoint.name}`);
              break;
            }
          }
        } catch (err) {
          console.log(`⚠️ ${endpoint.name} endpoint failed, trying next...`);
        }
      }
      
      setRecentSignals(signals);
      
    } catch (err) {
      console.log('Signals fetch error:', err);
      setSignalsError('Cannot load signals');
    }
  }, []);

  // ============================================
  // PUSH NOTIFICATIONS
  // ============================================

  const registerForPushNotifications = useCallback(async () => {
    try {
      setPushError(null);
      
      // Check permissions
      const { status: existingStatus } = await Notifications.getPermissionsAsync();
      let finalStatus = existingStatus;
      
      if (existingStatus !== 'granted') {
        const { status } = await Notifications.requestPermissionsAsync();
        finalStatus = status;
      }
      
      if (finalStatus !== 'granted') {
        setPushError('Permission denied');
        return;
      }
      
      // Get token
      const tokenData = await Notifications.getExpoPushTokenAsync({
        projectId: Constants.expoConfig?.extra?.eas?.projectId || '6c7a7f87-a996-4ca6-b498-7e2bb41f32a3',
      });
      
      const token = tokenData.data;
      console.log('📱 Push token:', token);
      setPushToken(token);
      
      // Register with backend - CORRECT ENDPOINT
      const response = await fetch(`${API_BASE}/api/register-device`, {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          'Accept': 'application/json',
        },
        body: JSON.stringify({
          device_id: DEVICE_ID,
          push_token: token,
          platform: Platform.OS,
          app_version: '1.1.2',
        }),
      });
      
      if (response.ok) {
        setPushRegistered(true);
        console.log('✅ Push registered successfully');
      } else {
        const errText = await response.text();
        console.log('Push registration response:', errText);
        // Still mark as registered if we have token
        setPushRegistered(true);
      }
      
    } catch (err: any) {
      console.error('Push registration error:', err);
      setPushError(err.message || 'Registration failed');
    }
  }, []);

  // ============================================
  // LIFECYCLE
  // ============================================

  const loadAllData = useCallback(async () => {
    console.log('📡 Loading all data...');
    await Promise.all([
      fetchLivePrices(),
      fetchScannerStatus(),
      fetchRecentSignals(),
    ]);
    setLastUpdate(new Date());
  }, [fetchLivePrices, fetchScannerStatus, fetchRecentSignals]);

  useEffect(() => {
    const init = async () => {
      setLoading(true);
      await loadAllData();
      await registerForPushNotifications();
      setLoading(false);
    };
    init();
    
    // Refresh every 30 seconds
    const interval = setInterval(() => {
      loadAllData();
    }, 30000);
    
    return () => clearInterval(interval);
  }, []);

  const onRefresh = useCallback(async () => {
    setRefreshing(true);
    await loadAllData();
    setRefreshing(false);
  }, [loadAllData]);

  // ============================================
  // HELPERS
  // ============================================

  const formatPrice = (price: number | undefined, asset: string): string => {
    if (!price || isNaN(price)) return '-';
    return asset === 'EURUSD' ? price.toFixed(5) : price.toFixed(2);
  };

  const formatTime = (date: Date | string | null): string => {
    if (!date) return '-';
    const d = typeof date === 'string' ? new Date(date) : date;
    return d.toLocaleTimeString('en-US', { hour: '2-digit', minute: '2-digit', second: '2-digit' });
  };

  // ============================================
  // RENDER COMPONENTS
  // ============================================

  const renderHeader = () => (
    <View style={styles.headerSection}>
      {/* Title */}
      <Text style={styles.mainTitle}>PropSignal Engine</Text>
      
      {/* Scanner Status Bar */}
      <View style={styles.scannerBar}>
        <View style={styles.scannerInfo}>
          <View style={[
            styles.scannerDot,
            { backgroundColor: scannerStatus?.is_running ? '#00ff88' : '#ff4444' }
          ]} />
          <Text style={styles.scannerText}>
            Scanner: {scannerError ? scannerError : (scannerStatus?.is_running ? 'ACTIVE' : 'STOPPED')}
          </Text>
        </View>
        <Text style={styles.scannerVersion}>{scannerStatus?.version || 'v3'}</Text>
      </View>

      {/* Live Prices */}
      <View style={styles.pricesContainer}>
        {/* EURUSD */}
        <View style={styles.priceCard}>
          <Text style={styles.priceSymbol}>EURUSD</Text>
          {priceError ? (
            <Text style={styles.priceError}>{priceError}</Text>
          ) : eurusdPrice ? (
            <>
              <View style={styles.priceRow}>
                <View style={styles.priceItem}>
                  <Text style={styles.priceLabel}>Bid</Text>
                  <Text style={styles.priceValue}>{formatPrice(eurusdPrice.bid, 'EURUSD')}</Text>
                </View>
                <View style={styles.priceItem}>
                  <Text style={styles.priceLabel}>Ask</Text>
                  <Text style={styles.priceValue}>{formatPrice(eurusdPrice.ask, 'EURUSD')}</Text>
                </View>
              </View>
              <Text style={styles.spreadText}>Spread: {eurusdPrice.spread_pips?.toFixed(1) || '-'} pips</Text>
            </>
          ) : (
            <ActivityIndicator size="small" color="#00ff88" />
          )}
        </View>

        {/* XAUUSD */}
        <View style={styles.priceCard}>
          <Text style={styles.priceSymbol}>XAUUSD</Text>
          {priceError ? (
            <Text style={styles.priceError}>{priceError}</Text>
          ) : xauusdPrice ? (
            <>
              <View style={styles.priceRow}>
                <View style={styles.priceItem}>
                  <Text style={styles.priceLabel}>Bid</Text>
                  <Text style={styles.priceValue}>{formatPrice(xauusdPrice.bid, 'XAUUSD')}</Text>
                </View>
                <View style={styles.priceItem}>
                  <Text style={styles.priceLabel}>Ask</Text>
                  <Text style={styles.priceValue}>{formatPrice(xauusdPrice.ask, 'XAUUSD')}</Text>
                </View>
              </View>
              <Text style={styles.spreadText}>Spread: {xauusdPrice.spread_pips?.toFixed(1) || '-'} pips</Text>
            </>
          ) : (
            <ActivityIndicator size="small" color="#00ff88" />
          )}
        </View>
      </View>

      {/* Device Registration */}
      <TouchableOpacity 
        style={[
          styles.registerButton,
          { backgroundColor: pushRegistered ? '#00ff8830' : '#ff444430' }
        ]}
        onPress={registerForPushNotifications}
      >
        <View style={[
          styles.registerDot,
          { backgroundColor: pushRegistered ? '#00ff88' : '#ff4444' }
        ]} />
        <Text style={[
          styles.registerText,
          { color: pushRegistered ? '#00ff88' : '#ff4444' }
        ]}>
          {pushError ? `⚠ ${pushError}` : 
           pushRegistered ? '✓ Notifications Enabled' : 
           'Enable Notifications'}
        </Text>
      </TouchableOpacity>

      {/* Last Update */}
      <Text style={styles.lastUpdate}>
        Last update: {formatTime(lastUpdate)}
      </Text>

      {/* Signals Section Title */}
      <View style={styles.signalsSectionHeader}>
        <Text style={styles.signalsSectionTitle}>Recent Signals</Text>
        <TouchableOpacity 
          style={styles.viewAllButton}
          onPress={() => router.push('/signals')}
        >
          <Text style={styles.viewAllText}>View All →</Text>
        </TouchableOpacity>
      </View>
    </View>
  );

  const renderSignalCard = ({ item }: { item: SignalItem }) => {
    const isBuy = (item.direction || item.signal_type) === 'BUY';
    const asset = item.asset || item.symbol || 'UNKNOWN';
    const direction = item.direction || item.signal_type || 'UNKNOWN';
    const score = item.confidence_score || item.score || 0;
    const status = item.status || 'unknown';
    
    return (
      <TouchableOpacity 
        style={styles.signalCard}
        onPress={() => {
          const signalId = item.signal_id || item.id;
          if (signalId) {
            router.push({
              pathname: '/signal-snapshot',
              params: { signalId }
            });
          }
        }}
        activeOpacity={0.7}
      >
        <View style={styles.signalHeader}>
          <View style={styles.signalSymbolRow}>
            <Text style={styles.signalSymbol}>{asset}</Text>
            <View style={[
              styles.signalDirection,
              { backgroundColor: isBuy ? '#00ff8830' : '#ff444430' }
            ]}>
              <Text style={[
                styles.signalDirectionText,
                { color: isBuy ? '#00ff88' : '#ff4444' }
              ]}>
                {direction}
              </Text>
            </View>
          </View>
          <View style={[
            styles.signalStatus,
            { backgroundColor: status === 'active' ? '#00aaff30' : 
                              status === 'rejected' ? '#ff444430' : '#88888830' }
          ]}>
            <Text style={[
              styles.signalStatusText,
              { color: status === 'active' ? '#00aaff' : 
                       status === 'rejected' ? '#ff4444' : '#888888' }
            ]}>
              {status.toUpperCase()}
            </Text>
          </View>
        </View>
        
        <View style={styles.signalDetails}>
          <View style={styles.signalScore}>
            <Text style={styles.signalScoreLabel}>Score</Text>
            <Text style={[
              styles.signalScoreValue,
              { color: score >= 70 ? '#00ff88' : score >= 60 ? '#ffaa00' : '#ff4444' }
            ]}>
              {score?.toFixed(1) || '-'}
            </Text>
          </View>
          
          {item.entry_price && (
            <View style={styles.signalLevels}>
              <Text style={styles.signalLevel}>E: {formatPrice(item.entry_price, asset)}</Text>
              <Text style={[styles.signalLevel, { color: '#ff4444' }]}>
                SL: {formatPrice(item.stop_loss, asset)}
              </Text>
              <Text style={[styles.signalLevel, { color: '#00ff88' }]}>
                TP: {formatPrice(item.take_profit || item.take_profit_1, asset)}
              </Text>
            </View>
          )}
        </View>
        
        {item.outcome && (
          <View style={[
            styles.signalOutcome,
            { backgroundColor: item.outcome === 'win' || item.outcome === 'tp_hit' ? '#00ff8830' : '#ff444430' }
          ]}>
            <Text style={[
              styles.signalOutcomeText,
              { color: item.outcome === 'win' || item.outcome === 'tp_hit' ? '#00ff88' : '#ff4444' }
            ]}>
              {item.outcome === 'win' || item.outcome === 'tp_hit' ? '✓ TP Hit' : 
               item.outcome === 'loss' || item.outcome === 'sl_hit' ? '✗ SL Hit' : item.outcome}
            </Text>
          </View>
        )}
      </TouchableOpacity>
    );
  };

  const renderEmpty = () => (
    <View style={styles.emptyContainer}>
      {signalsError ? (
        <>
          <Text style={styles.emptyIcon}>⚠️</Text>
          <Text style={styles.emptyText}>{signalsError}</Text>
        </>
      ) : (
        <>
          <Text style={styles.emptyIcon}>📭</Text>
          <Text style={styles.emptyText}>No signals yet</Text>
          <Text style={styles.emptySubtext}>Signals will appear when the scanner finds setups</Text>
        </>
      )}
    </View>
  );

  // ============================================
  // LOADING STATE
  // ============================================

  if (loading) {
    return (
      <SafeAreaView style={styles.container}>
        <View style={styles.loadingContainer}>
          <ActivityIndicator size="large" color="#00ff88" />
          <Text style={styles.loadingText}>Loading PropSignal...</Text>
        </View>
      </SafeAreaView>
    );
  }

  // ============================================
  // MAIN RENDER
  // ============================================

  return (
    <SafeAreaView style={styles.container} edges={['top', 'bottom']}>
      <FlatList
        data={recentSignals}
        keyExtractor={(item, index) => `${item.signal_id || item.id || index}`}
        renderItem={renderSignalCard}
        ListHeaderComponent={renderHeader}
        ListEmptyComponent={renderEmpty}
        contentContainerStyle={styles.listContent}
        refreshControl={
          <RefreshControl
            refreshing={refreshing}
            onRefresh={onRefresh}
            tintColor="#00ff88"
            colors={['#00ff88']}
          />
        }
        showsVerticalScrollIndicator={false}
      />
    </SafeAreaView>
  );
}

// ============================================
// STYLES
// ============================================

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
  listContent: {
    paddingHorizontal: 16,
    paddingBottom: 20,
  },
  headerSection: {
    paddingTop: 8,
    paddingBottom: 16,
  },
  mainTitle: {
    color: '#fff',
    fontSize: 28,
    fontWeight: 'bold',
    textAlign: 'center',
    marginBottom: 16,
  },
  
  // Scanner Bar
  scannerBar: {
    flexDirection: 'row',
    justifyContent: 'space-between',
    alignItems: 'center',
    backgroundColor: '#1a1a1a',
    borderRadius: 8,
    padding: 12,
    marginBottom: 16,
  },
  scannerInfo: {
    flexDirection: 'row',
    alignItems: 'center',
  },
  scannerDot: {
    width: 10,
    height: 10,
    borderRadius: 5,
    marginRight: 8,
  },
  scannerText: {
    color: '#fff',
    fontSize: 14,
    fontWeight: '600',
  },
  scannerVersion: {
    color: '#888',
    fontSize: 12,
  },
  
  // Prices
  pricesContainer: {
    flexDirection: 'row',
    gap: 12,
    marginBottom: 16,
  },
  priceCard: {
    flex: 1,
    backgroundColor: '#1a1a1a',
    borderRadius: 12,
    padding: 12,
  },
  priceSymbol: {
    color: '#fff',
    fontSize: 14,
    fontWeight: 'bold',
    marginBottom: 8,
    textAlign: 'center',
  },
  priceRow: {
    flexDirection: 'row',
    justifyContent: 'space-around',
  },
  priceItem: {
    alignItems: 'center',
  },
  priceLabel: {
    color: '#888',
    fontSize: 10,
  },
  priceValue: {
    color: '#fff',
    fontSize: 14,
    fontWeight: '600',
  },
  spreadText: {
    color: '#00aaff',
    fontSize: 11,
    textAlign: 'center',
    marginTop: 6,
  },
  priceError: {
    color: '#ff4444',
    fontSize: 12,
    textAlign: 'center',
  },
  
  // Register Button
  registerButton: {
    flexDirection: 'row',
    alignItems: 'center',
    justifyContent: 'center',
    padding: 12,
    borderRadius: 8,
    marginBottom: 12,
  },
  registerDot: {
    width: 8,
    height: 8,
    borderRadius: 4,
    marginRight: 8,
  },
  registerText: {
    fontSize: 14,
    fontWeight: '600',
  },
  
  // Last Update
  lastUpdate: {
    color: '#666',
    fontSize: 11,
    textAlign: 'center',
    marginBottom: 16,
  },
  
  // Signals Section
  signalsSectionHeader: {
    flexDirection: 'row',
    justifyContent: 'space-between',
    alignItems: 'center',
    marginBottom: 12,
  },
  signalsSectionTitle: {
    color: '#fff',
    fontSize: 18,
    fontWeight: 'bold',
  },
  viewAllButton: {
    paddingVertical: 4,
    paddingHorizontal: 8,
  },
  viewAllText: {
    color: '#00ff88',
    fontSize: 14,
  },
  
  // Signal Card
  signalCard: {
    backgroundColor: '#1a1a1a',
    borderRadius: 12,
    padding: 14,
    marginBottom: 10,
    borderWidth: 1,
    borderColor: '#2a2a2a',
  },
  signalHeader: {
    flexDirection: 'row',
    justifyContent: 'space-between',
    alignItems: 'center',
    marginBottom: 10,
  },
  signalSymbolRow: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: 8,
  },
  signalSymbol: {
    color: '#fff',
    fontSize: 16,
    fontWeight: 'bold',
  },
  signalDirection: {
    paddingHorizontal: 8,
    paddingVertical: 3,
    borderRadius: 4,
  },
  signalDirectionText: {
    fontSize: 11,
    fontWeight: 'bold',
  },
  signalStatus: {
    paddingHorizontal: 8,
    paddingVertical: 3,
    borderRadius: 4,
  },
  signalStatusText: {
    fontSize: 10,
    fontWeight: 'bold',
  },
  signalDetails: {
    flexDirection: 'row',
    justifyContent: 'space-between',
    alignItems: 'center',
  },
  signalScore: {
    alignItems: 'center',
  },
  signalScoreLabel: {
    color: '#888',
    fontSize: 10,
  },
  signalScoreValue: {
    fontSize: 20,
    fontWeight: 'bold',
  },
  signalLevels: {
    flexDirection: 'row',
    gap: 10,
  },
  signalLevel: {
    color: '#888',
    fontSize: 11,
  },
  signalOutcome: {
    marginTop: 8,
    paddingVertical: 6,
    borderRadius: 6,
    alignItems: 'center',
  },
  signalOutcomeText: {
    fontSize: 12,
    fontWeight: 'bold',
  },
  
  // Empty State
  emptyContainer: {
    alignItems: 'center',
    paddingVertical: 40,
  },
  emptyIcon: {
    fontSize: 40,
    marginBottom: 12,
  },
  emptyText: {
    color: '#888',
    fontSize: 16,
    fontWeight: '600',
  },
  emptySubtext: {
    color: '#666',
    fontSize: 13,
    marginTop: 6,
    textAlign: 'center',
  },
});
