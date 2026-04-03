import React, { useState, useEffect, useCallback } from 'react';
import {
  View,
  Text,
  StyleSheet,
  TouchableOpacity,
  FlatList,
  ActivityIndicator,
  RefreshControl,
  Platform,
} from 'react-native';
import { SafeAreaView } from 'react-native-safe-area-context';
import { useRouter } from 'expo-router';
import Constants from 'expo-constants';

// ============================================
// API CONFIGURATION - ROBUST MULTI-SOURCE
// ============================================

const PRODUCTION_URL = 'https://propsignal-engine-production-b22b.up.railway.app';
const EMERGENT_URL = process.env.EXPO_PUBLIC_BACKEND_URL || '';

const getApiUrl = (): string => {
  // In dev/preview, try Emergent URL first
  if (__DEV__ && EMERGENT_URL && !EMERGENT_URL.includes('undefined')) {
    return EMERGENT_URL;
  }
  // Fallback to production
  return PRODUCTION_URL;
};

const API_BASE = getApiUrl();
console.log('📡 Signal Feed API:', API_BASE);

// ============================================
// TYPES
// ============================================

interface SignalFeedItem {
  signal_id: string;
  timestamp: string;
  symbol: string;
  direction: string;
  status: string;
  score: number;
  entry: number;
  sl: number;
  tp: number;
  rr: number;
  session: string;
  setup_type: string;
  short_reason: string;
  rejection_reason: string;
  blocking_filter: string;
  confidence_bucket: string;
  outcome: string;
  final_r: number;
}

interface FeedStats {
  total: number;
  accepted: number;
  rejected: number;
  active: number;
  closed: number;
}

// ============================================
// STATUS COLORS
// ============================================

const STATUS_COLORS: Record<string, { bg: string; text: string }> = {
  accepted: { bg: '#00ff8820', text: '#00ff88' },
  rejected: { bg: '#ff444420', text: '#ff4444' },
  active: { bg: '#00aaff20', text: '#00aaff' },
  tp_hit: { bg: '#00ff8840', text: '#00ff88' },
  sl_hit: { bg: '#ff444440', text: '#ff4444' },
  expired: { bg: '#88888840', text: '#888888' },
  closed: { bg: '#88888840', text: '#888888' },
};

// Filter tabs
const FILTER_TABS = [
  { key: 'all', label: 'All' },
  { key: 'accepted', label: 'Accepted' },
  { key: 'rejected', label: 'Rejected' },
  { key: 'active', label: 'Active' },
  { key: 'closed', label: 'Closed' },
];

// ============================================
// MAIN COMPONENT
// ============================================

export default function SignalFeedScreen() {
  const router = useRouter();
  const [signals, setSignals] = useState<SignalFeedItem[]>([]);
  const [stats, setStats] = useState<FeedStats | null>(null);
  const [loading, setLoading] = useState(true);
  const [refreshing, setRefreshing] = useState(false);
  const [activeFilter, setActiveFilter] = useState('all');
  const [error, setError] = useState<string | null>(null);
  const [errorDetails, setErrorDetails] = useState<string | null>(null);

  // ============================================
  // DATA FETCHING - ROBUST WITH FALLBACKS
  // ============================================

  const fetchSignals = useCallback(async (filter: string = activeFilter) => {
    try {
      setError(null);
      setErrorDetails(null);
      
      const statusParam = filter !== 'all' ? `&status=${filter}` : '';
      const url = `${API_BASE}/api/signals/feed?limit=200${statusParam}`;
      
      console.log('📡 Fetching signals from:', url);
      
      const controller = new AbortController();
      const timeoutId = setTimeout(() => controller.abort(), 15000);
      
      const response = await fetch(url, {
        signal: controller.signal,
        headers: {
          'Accept': 'application/json',
          'Content-Type': 'application/json',
        },
      });
      
      clearTimeout(timeoutId);
      
      console.log('📡 Response status:', response.status);
      
      if (!response.ok) {
        const errorText = await response.text();
        console.error('📡 Error response:', errorText);
        
        if (response.status === 404) {
          setError('Endpoint not found');
          setErrorDetails('The signals API may not be deployed yet. Try refreshing.');
        } else if (response.status >= 500) {
          setError('Server error');
          setErrorDetails(`Server returned ${response.status}. The backend may be restarting.`);
        } else {
          setError(`HTTP ${response.status}`);
          setErrorDetails(errorText.substring(0, 200));
        }
        return;
      }
      
      const data = await response.json();
      console.log('📡 Response data keys:', Object.keys(data));
      console.log('📡 Signals count:', data.signals?.length || 0);
      
      // Handle different response formats
      let signalsList: SignalFeedItem[] = [];
      
      if (Array.isArray(data)) {
        signalsList = data;
      } else if (data.signals && Array.isArray(data.signals)) {
        signalsList = data.signals;
      } else if (data.data && Array.isArray(data.data)) {
        signalsList = data.data;
      } else if (data.items && Array.isArray(data.items)) {
        signalsList = data.items;
      }
      
      // Validate and sanitize signals
      signalsList = signalsList.map(sig => ({
        signal_id: sig.signal_id || sig.id || `unknown_${Date.now()}`,
        timestamp: sig.timestamp || sig.created_at || new Date().toISOString(),
        symbol: sig.symbol || sig.asset || 'UNKNOWN',
        direction: sig.direction || sig.signal_type || 'UNKNOWN',
        status: sig.status || 'unknown',
        score: parseFloat(sig.score) || parseFloat(sig.total_score) || parseFloat(sig.confidence_score) || 0,
        entry: parseFloat(sig.entry) || parseFloat(sig.entry_price) || 0,
        sl: parseFloat(sig.sl) || parseFloat(sig.stop_loss) || 0,
        tp: parseFloat(sig.tp) || parseFloat(sig.take_profit) || parseFloat(sig.take_profit_1) || 0,
        rr: parseFloat(sig.rr) || parseFloat(sig.rr_ratio) || parseFloat(sig.risk_reward) || 0,
        session: sig.session || '',
        setup_type: sig.setup_type || '',
        short_reason: sig.short_reason || sig.summary_short || '',
        rejection_reason: sig.rejection_reason || '',
        blocking_filter: sig.blocking_filter || '',
        confidence_bucket: sig.confidence_bucket || '',
        outcome: sig.outcome || sig.final_outcome || '',
        final_r: parseFloat(sig.final_r) || 0,
      }));
      
      setSignals(signalsList);
      
    } catch (err: any) {
      console.error('📡 Fetch error:', err);
      
      if (err.name === 'AbortError') {
        setError('Request timeout');
        setErrorDetails('Server took too long to respond. Please try again.');
      } else if (err.message?.includes('Network')) {
        setError('Network error');
        setErrorDetails('Cannot connect to server. Check your internet connection.');
      } else {
        setError('Failed to load signals');
        setErrorDetails(err.message || 'Unknown error occurred');
      }
    }
  }, [activeFilter]);

  const fetchStats = useCallback(async () => {
    try {
      const url = `${API_BASE}/api/signals/feed/stats`;
      const response = await fetch(url, {
        headers: { 'Accept': 'application/json' },
      });
      
      if (response.ok) {
        const data = await response.json();
        setStats(data);
      }
    } catch (err) {
      console.log('📡 Stats fetch error (non-critical):', err);
      // Non-critical, don't show error
    }
  }, []);

  // ============================================
  // LIFECYCLE
  // ============================================

  useEffect(() => {
    const loadData = async () => {
      setLoading(true);
      await Promise.all([fetchSignals(), fetchStats()]);
      setLoading(false);
    };
    loadData();
    
    // Auto-refresh every 30 seconds
    const interval = setInterval(() => {
      fetchSignals();
      fetchStats();
    }, 30000);
    
    return () => clearInterval(interval);
  }, []);

  const onRefresh = useCallback(async () => {
    setRefreshing(true);
    await Promise.all([fetchSignals(), fetchStats()]);
    setRefreshing(false);
  }, [fetchSignals, fetchStats]);

  const handleFilterChange = useCallback((filter: string) => {
    setActiveFilter(filter);
    fetchSignals(filter);
  }, [fetchSignals]);

  const handleSignalPress = (signalId: string) => {
    router.push({
      pathname: '/signal-snapshot',
      params: { signalId }
    });
  };

  // ============================================
  // HELPERS
  // ============================================

  const formatPrice = (price: number, symbol: string) => {
    if (!price || isNaN(price)) return '-';
    if (symbol === 'XAUUSD') {
      return price.toFixed(2);
    }
    return price.toFixed(5);
  };

  const formatTimestamp = (ts: string) => {
    if (!ts) return '-';
    try {
      const date = new Date(ts);
      if (isNaN(date.getTime())) return ts;
      
      const now = new Date();
      const diff = now.getTime() - date.getTime();
      
      if (diff < 60000) return 'Just now';
      if (diff < 3600000) return `${Math.floor(diff / 60000)}m ago`;
      if (diff < 86400000) return `${Math.floor(diff / 3600000)}h ago`;
      
      return date.toLocaleDateString('en-US', { 
        month: 'short', 
        day: 'numeric',
        hour: '2-digit',
        minute: '2-digit'
      });
    } catch {
      return ts;
    }
  };

  // ============================================
  // RENDER SIGNAL CARD
  // ============================================

  const renderSignalCard = ({ item }: { item: SignalFeedItem }) => {
    const statusColor = STATUS_COLORS[item.status] || STATUS_COLORS.rejected;
    const isBuy = item.direction === 'BUY';
    
    return (
      <TouchableOpacity 
        style={styles.signalCard}
        onPress={() => handleSignalPress(item.signal_id)}
        activeOpacity={0.7}
      >
        {/* Header */}
        <View style={styles.cardHeader}>
          <View style={styles.symbolContainer}>
            <Text style={styles.symbolText}>{item.symbol}</Text>
            <View style={[
              styles.directionBadge,
              { backgroundColor: isBuy ? '#00ff8830' : '#ff444430' }
            ]}>
              <Text style={[
                styles.directionText,
                { color: isBuy ? '#00ff88' : '#ff4444' }
              ]}>
                {item.direction}
              </Text>
            </View>
          </View>
          <View style={[
            styles.statusBadge,
            { backgroundColor: statusColor.bg }
          ]}>
            <Text style={[styles.statusText, { color: statusColor.text }]}>
              {item.status.toUpperCase().replace('_', ' ')}
            </Text>
          </View>
        </View>

        {/* Score & Session */}
        <View style={styles.scoreRow}>
          <View style={styles.scoreContainer}>
            <Text style={styles.scoreLabel}>Score</Text>
            <Text style={[
              styles.scoreValue,
              { color: item.score >= 70 ? '#00ff88' : item.score >= 60 ? '#ffaa00' : '#ff4444' }
            ]}>
              {item.score?.toFixed(1) || '-'}
            </Text>
          </View>
          <View style={styles.sessionContainer}>
            <Text style={styles.sessionLabel}>{item.session || '-'}</Text>
            <Text style={styles.setupType} numberOfLines={1}>{item.setup_type || '-'}</Text>
          </View>
          <View style={styles.rrContainer}>
            <Text style={styles.rrLabel}>R:R</Text>
            <Text style={styles.rrValue}>{item.rr?.toFixed(2) || '-'}</Text>
          </View>
        </View>

        {/* Trade Levels */}
        <View style={styles.levelsRow}>
          <View style={styles.levelItem}>
            <Text style={styles.levelLabel}>Entry</Text>
            <Text style={styles.levelValue}>{formatPrice(item.entry, item.symbol)}</Text>
          </View>
          <View style={styles.levelItem}>
            <Text style={[styles.levelLabel, { color: '#ff4444' }]}>SL</Text>
            <Text style={[styles.levelValue, { color: '#ff4444' }]}>
              {formatPrice(item.sl, item.symbol)}
            </Text>
          </View>
          <View style={styles.levelItem}>
            <Text style={[styles.levelLabel, { color: '#00ff88' }]}>TP</Text>
            <Text style={[styles.levelValue, { color: '#00ff88' }]}>
              {formatPrice(item.tp, item.symbol)}
            </Text>
          </View>
        </View>

        {/* Reason */}
        <View style={styles.reasonContainer}>
          <Text style={styles.reasonText} numberOfLines={2}>
            {item.short_reason || item.rejection_reason || 'No details available'}
          </Text>
        </View>

        {/* Outcome (if closed) */}
        {item.outcome && item.outcome !== '' && (
          <View style={[
            styles.outcomeContainer,
            { backgroundColor: item.outcome === 'tp_hit' ? '#00ff8820' : '#ff444420' }
          ]}>
            <Text style={[
              styles.outcomeText,
              { color: item.outcome === 'tp_hit' ? '#00ff88' : '#ff4444' }
            ]}>
              {item.outcome === 'tp_hit' ? '✓ TP Hit' : item.outcome === 'sl_hit' ? '✗ SL Hit' : item.outcome}
              {item.final_r !== 0 && ` (${item.final_r > 0 ? '+' : ''}${item.final_r.toFixed(2)}R)`}
            </Text>
          </View>
        )}

        {/* Timestamp */}
        <Text style={styles.timestamp}>{formatTimestamp(item.timestamp)}</Text>
      </TouchableOpacity>
    );
  };

  // ============================================
  // RENDER HEADER
  // ============================================

  const renderHeader = () => (
    <View style={styles.headerContainer}>
      {/* Title */}
      <Text style={styles.mainTitle}>PropSignal Feed</Text>
      
      {/* Stats */}
      {stats && (
        <View style={styles.statsContainer}>
          <View style={styles.statItem}>
            <Text style={styles.statValue}>{stats.total || 0}</Text>
            <Text style={styles.statLabel}>Total</Text>
          </View>
          <View style={styles.statItem}>
            <Text style={[styles.statValue, { color: '#00ff88' }]}>{stats.accepted || 0}</Text>
            <Text style={styles.statLabel}>Accepted</Text>
          </View>
          <View style={styles.statItem}>
            <Text style={[styles.statValue, { color: '#ff4444' }]}>{stats.rejected || 0}</Text>
            <Text style={styles.statLabel}>Rejected</Text>
          </View>
          <View style={styles.statItem}>
            <Text style={[styles.statValue, { color: '#00aaff' }]}>{stats.active || 0}</Text>
            <Text style={styles.statLabel}>Active</Text>
          </View>
        </View>
      )}

      {/* Filter Tabs */}
      <View style={styles.filterContainer}>
        {FILTER_TABS.map(tab => (
          <TouchableOpacity
            key={tab.key}
            style={[
              styles.filterTab,
              activeFilter === tab.key && styles.filterTabActive
            ]}
            onPress={() => handleFilterChange(tab.key)}
          >
            <Text style={[
              styles.filterTabText,
              activeFilter === tab.key && styles.filterTabTextActive
            ]}>
              {tab.label}
            </Text>
          </TouchableOpacity>
        ))}
      </View>
    </View>
  );

  // ============================================
  // RENDER EMPTY/ERROR STATES
  // ============================================

  const renderEmptyComponent = () => {
    if (error) {
      return (
        <View style={styles.emptyContainer}>
          <Text style={styles.errorIcon}>⚠️</Text>
          <Text style={styles.errorText}>{error}</Text>
          {errorDetails && (
            <Text style={styles.errorDetails}>{errorDetails}</Text>
          )}
          <TouchableOpacity 
            style={styles.retryButton}
            onPress={onRefresh}
          >
            <Text style={styles.retryButtonText}>Tap to Retry</Text>
          </TouchableOpacity>
        </View>
      );
    }
    
    return (
      <View style={styles.emptyContainer}>
        <Text style={styles.emptyIcon}>📭</Text>
        <Text style={styles.emptyText}>No signals yet</Text>
        <Text style={styles.emptySubtext}>
          Signals will appear here when the engine generates them
        </Text>
      </View>
    );
  };

  // ============================================
  // LOADING STATE
  // ============================================

  if (loading) {
    return (
      <SafeAreaView style={styles.container}>
        <View style={styles.loadingContainer}>
          <ActivityIndicator size="large" color="#00ff88" />
          <Text style={styles.loadingText}>Loading signals...</Text>
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
        data={signals}
        keyExtractor={(item, index) => `${item.signal_id}-${index}`}
        renderItem={renderSignalCard}
        ListHeaderComponent={renderHeader}
        ListEmptyComponent={renderEmptyComponent}
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
  headerContainer: {
    paddingHorizontal: 16,
    paddingTop: 16,
    paddingBottom: 16,
  },
  mainTitle: {
    color: '#fff',
    fontSize: 28,
    fontWeight: 'bold',
    marginBottom: 16,
    textAlign: 'center',
  },
  statsContainer: {
    flexDirection: 'row',
    justifyContent: 'space-around',
    backgroundColor: '#1a1a1a',
    borderRadius: 12,
    paddingVertical: 16,
    marginBottom: 16,
  },
  statItem: {
    alignItems: 'center',
  },
  statValue: {
    color: '#fff',
    fontSize: 24,
    fontWeight: 'bold',
  },
  statLabel: {
    color: '#888',
    fontSize: 12,
    marginTop: 4,
  },
  filterContainer: {
    flexDirection: 'row',
    backgroundColor: '#1a1a1a',
    borderRadius: 8,
    padding: 4,
  },
  filterTab: {
    flex: 1,
    paddingVertical: 10,
    paddingHorizontal: 8,
    borderRadius: 6,
    alignItems: 'center',
  },
  filterTabActive: {
    backgroundColor: '#00ff8830',
  },
  filterTabText: {
    color: '#888',
    fontSize: 12,
    fontWeight: '600',
  },
  filterTabTextActive: {
    color: '#00ff88',
  },
  listContent: {
    paddingHorizontal: 16,
    paddingBottom: 20,
  },
  signalCard: {
    backgroundColor: '#1a1a1a',
    borderRadius: 12,
    padding: 16,
    marginBottom: 12,
    borderWidth: 1,
    borderColor: '#2a2a2a',
  },
  cardHeader: {
    flexDirection: 'row',
    justifyContent: 'space-between',
    alignItems: 'center',
    marginBottom: 12,
  },
  symbolContainer: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: 8,
  },
  symbolText: {
    color: '#fff',
    fontSize: 18,
    fontWeight: 'bold',
  },
  directionBadge: {
    paddingHorizontal: 8,
    paddingVertical: 4,
    borderRadius: 4,
  },
  directionText: {
    fontSize: 12,
    fontWeight: 'bold',
  },
  statusBadge: {
    paddingHorizontal: 10,
    paddingVertical: 4,
    borderRadius: 4,
  },
  statusText: {
    fontSize: 10,
    fontWeight: 'bold',
  },
  scoreRow: {
    flexDirection: 'row',
    justifyContent: 'space-between',
    alignItems: 'center',
    marginBottom: 12,
    paddingBottom: 12,
    borderBottomWidth: 1,
    borderBottomColor: '#2a2a2a',
  },
  scoreContainer: {
    alignItems: 'center',
  },
  scoreLabel: {
    color: '#888',
    fontSize: 10,
  },
  scoreValue: {
    fontSize: 24,
    fontWeight: 'bold',
  },
  sessionContainer: {
    alignItems: 'center',
    flex: 1,
    paddingHorizontal: 8,
  },
  sessionLabel: {
    color: '#00aaff',
    fontSize: 12,
    fontWeight: '600',
  },
  setupType: {
    color: '#666',
    fontSize: 10,
    marginTop: 2,
    textAlign: 'center',
  },
  rrContainer: {
    alignItems: 'center',
  },
  rrLabel: {
    color: '#888',
    fontSize: 10,
  },
  rrValue: {
    color: '#fff',
    fontSize: 16,
    fontWeight: 'bold',
  },
  levelsRow: {
    flexDirection: 'row',
    justifyContent: 'space-between',
    marginBottom: 12,
  },
  levelItem: {
    alignItems: 'center',
    flex: 1,
  },
  levelLabel: {
    color: '#888',
    fontSize: 10,
    marginBottom: 2,
  },
  levelValue: {
    color: '#fff',
    fontSize: 14,
    fontWeight: '500',
  },
  reasonContainer: {
    backgroundColor: '#0f0f0f',
    borderRadius: 6,
    padding: 10,
    marginBottom: 8,
  },
  reasonText: {
    color: '#aaa',
    fontSize: 12,
    lineHeight: 18,
  },
  outcomeContainer: {
    borderRadius: 6,
    padding: 8,
    alignItems: 'center',
    marginBottom: 8,
  },
  outcomeText: {
    fontSize: 12,
    fontWeight: 'bold',
  },
  timestamp: {
    color: '#666',
    fontSize: 10,
    textAlign: 'right',
  },
  emptyContainer: {
    flex: 1,
    justifyContent: 'center',
    alignItems: 'center',
    paddingVertical: 60,
    paddingHorizontal: 20,
  },
  emptyIcon: {
    fontSize: 48,
    marginBottom: 16,
  },
  emptyText: {
    color: '#888',
    fontSize: 18,
    fontWeight: '600',
    marginBottom: 8,
  },
  emptySubtext: {
    color: '#666',
    fontSize: 14,
    textAlign: 'center',
  },
  errorIcon: {
    fontSize: 48,
    marginBottom: 16,
  },
  errorText: {
    color: '#ff4444',
    fontSize: 18,
    fontWeight: '600',
    marginBottom: 8,
  },
  errorDetails: {
    color: '#888',
    fontSize: 12,
    textAlign: 'center',
    marginBottom: 16,
    paddingHorizontal: 20,
  },
  retryButton: {
    backgroundColor: '#00ff8830',
    paddingHorizontal: 24,
    paddingVertical: 12,
    borderRadius: 8,
  },
  retryButtonText: {
    color: '#00ff88',
    fontSize: 14,
    fontWeight: '600',
  },
});
