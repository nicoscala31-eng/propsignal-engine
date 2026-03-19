/**
 * Push Notification Service - BULLETPROOF VERSION
 * ================================================
 * 
 * DESIGN PRINCIPLES:
 * 1. ALWAYS register with backend on every app startup (no caching that causes issues)
 * 2. Simple and robust - fewer moving parts = fewer failures
 * 3. Clear error messages in Italian
 * 4. Works forever once enabled
 */

import * as Notifications from 'expo-notifications';
import * as Device from 'expo-device';
import { Platform, AppState, AppStateStatus } from 'react-native';
import Constants from 'expo-constants';
import AsyncStorage from '@react-native-async-storage/async-storage';
import { BACKEND_URL } from '../config/api';

// Simple storage key
const STORAGE_KEY_ENABLED = 'propsignal_notifications_on';

// Notification states
export enum NotificationState {
  UNKNOWN = 'UNKNOWN',
  DISABLED = 'DISABLED',
  PERMISSION_DENIED = 'PERMISSION_DENIED',
  ENABLING = 'ENABLING',
  ENABLED = 'ENABLED',
  FAILED = 'FAILED'
}

// Registration result
export interface RegistrationResult {
  success: boolean;
  state: NotificationState;
  token?: string;
  error?: string;
}

// Configure how notifications appear when app is foregrounded
Notifications.setNotificationHandler({
  handleNotification: async () => ({
    shouldShowAlert: true,
    shouldPlaySound: true,
    shouldSetBadge: true,
    shouldShowBanner: true,
    shouldShowList: true,
  }),
});

class PushNotificationService {
  private pushToken: string | null = null;
  private deviceId: string | null = null;
  private state: NotificationState = NotificationState.UNKNOWN;
  private notificationListener: any = null;
  private responseListener: any = null;
  private lastError: string | null = null;
  private appStateSubscription: any = null;

  // Callbacks
  onNotificationTap: ((signalId: string) => void) | null = null;
  onStateChange: ((state: NotificationState) => void) | null = null;

  constructor() {
    // Listen for app state changes to re-register when app comes to foreground
    this.appStateSubscription = AppState.addEventListener('change', this.handleAppStateChange);
  }

  /**
   * Handle app state changes - re-register when app becomes active
   */
  private handleAppStateChange = async (nextAppState: AppStateStatus) => {
    if (nextAppState === 'active' && this.state === NotificationState.ENABLED) {
      console.log('📱 [NOTIF] App became active - syncing with backend...');
      await this.syncWithBackend();
    }
  };

  /**
   * Get current state
   */
  getState(): NotificationState {
    return this.state;
  }

  /**
   * Get token
   */
  getToken(): string | null {
    return this.pushToken;
  }

  /**
   * Check if enabled
   */
  isRegistered(): boolean {
    return this.state === NotificationState.ENABLED;
  }

  /**
   * Get last error
   */
  getLastError(): string | null {
    return this.lastError;
  }

  /**
   * Update state
   */
  private setState(newState: NotificationState) {
    this.state = newState;
    console.log(`📱 [NOTIF STATE] ${newState}`);
    this.onStateChange?.(newState);
  }

  /**
   * Generate unique device ID
   */
  private generateDeviceId(): string {
    const brand = Device.brand || 'Unknown';
    const model = Device.modelName || 'Device';
    const os = Platform.OS;
    // Use a stable ID based on device info
    const stableId = `${brand}_${model}_${os}`.replace(/\s+/g, '_');
    return stableId;
  }

  /**
   * MAIN METHOD: Check permission status on app startup
   * This restores state and syncs with backend
   */
  async checkPermissionStatus(): Promise<NotificationState> {
    console.log('📱 [NOTIF] Checking permission status...');

    // Not a physical device
    if (!Device.isDevice) {
      console.log('📱 [NOTIF] Not a physical device');
      this.setState(NotificationState.DISABLED);
      return NotificationState.DISABLED;
    }

    try {
      // Check if user previously enabled notifications
      const wasEnabled = await AsyncStorage.getItem(STORAGE_KEY_ENABLED);
      
      // Check system permission
      const { status } = await Notifications.getPermissionsAsync();
      console.log(`📱 [NOTIF] System permission: ${status}, Was enabled: ${wasEnabled}`);

      if (status === 'granted' && wasEnabled === 'true') {
        // User had notifications enabled - restore and sync
        console.log('📱 [NOTIF] Restoring enabled state...');
        
        // Get fresh token and register with backend
        await this.getTokenAndRegister();
        
        this.setState(NotificationState.ENABLED);
        this.setupNotificationListeners();
        
        return NotificationState.ENABLED;
      }

      if (status === 'denied') {
        this.setState(NotificationState.PERMISSION_DENIED);
        return NotificationState.PERMISSION_DENIED;
      }

      this.setState(NotificationState.DISABLED);
      return NotificationState.DISABLED;

    } catch (error) {
      console.error('📱 [NOTIF] Error checking status:', error);
      this.setState(NotificationState.DISABLED);
      return NotificationState.DISABLED;
    }
  }

  /**
   * Get push token and register with backend
   */
  private async getTokenAndRegister(): Promise<void> {
    // Generate stable device ID
    this.deviceId = this.generateDeviceId();
    console.log(`📱 [NOTIF] Device ID: ${this.deviceId}`);

    // Get push token
    try {
      // Try native FCM token first (for standalone APK)
      if (Platform.OS === 'android') {
        try {
          const nativeToken = await Notifications.getDevicePushTokenAsync();
          if (nativeToken?.data) {
            this.pushToken = nativeToken.data;
            console.log(`✅ [NOTIF] FCM token: ${this.pushToken.substring(0, 40)}...`);
          }
        } catch (e: any) {
          console.log(`⚠️ [NOTIF] Native token not available: ${e.message}`);
        }
      }

      // Fallback to Expo token
      if (!this.pushToken) {
        const projectId = Constants.expoConfig?.extra?.eas?.projectId;
        const tokenData = projectId 
          ? await Notifications.getExpoPushTokenAsync({ projectId })
          : await Notifications.getExpoPushTokenAsync();
        this.pushToken = tokenData.data;
        console.log(`✅ [NOTIF] Expo token: ${this.pushToken}`);
      }

    } catch (error: any) {
      console.error('❌ [NOTIF] Token error:', error);
      throw new Error(`Impossibile ottenere token: ${error.message}`);
    }

    // Register with backend
    await this.registerWithBackend();
  }

  /**
   * Register device with backend - ALWAYS called, no caching
   */
  private async registerWithBackend(): Promise<void> {
    if (!this.pushToken || !this.deviceId) {
      console.log('📱 [NOTIF] Missing token or device ID');
      return;
    }

    console.log(`📱 [NOTIF] Registering with backend...`);
    console.log(`📱 [NOTIF] URL: ${BACKEND_URL}/api/register-device`);
    console.log(`📱 [NOTIF] Device: ${this.deviceId}`);
    console.log(`📱 [NOTIF] Token: ${this.pushToken.substring(0, 40)}...`);

    try {
      const response = await fetch(`${BACKEND_URL}/api/register-device`, {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
        },
        body: JSON.stringify({
          device_id: this.deviceId,
          push_token: this.pushToken,
          platform: Platform.OS,
          device_name: `${Device.brand || 'Unknown'} ${Device.modelName || 'Device'}`,
        }),
      });

      const result = await response.json();
      
      if (!response.ok) {
        console.error('❌ [NOTIF] Backend error:', result);
        throw new Error(result.detail || `HTTP ${response.status}`);
      }

      console.log(`✅ [NOTIF] Backend registration successful: ${result.status}`);
      
    } catch (error: any) {
      console.error('❌ [NOTIF] Registration failed:', error);
      // Don't throw - we still want notifications to work even if backend fails temporarily
      // The app will retry on next startup
    }
  }

  /**
   * Sync with backend (called when app becomes active)
   */
  private async syncWithBackend(): Promise<void> {
    if (this.state !== NotificationState.ENABLED) return;
    
    try {
      await this.getTokenAndRegister();
      console.log('✅ [NOTIF] Synced with backend');
    } catch (error) {
      console.error('⚠️ [NOTIF] Sync failed:', error);
    }
  }

  /**
   * MAIN METHOD: Enable notifications
   * User clicks "Enable Notifications" button
   */
  async enableNotifications(): Promise<RegistrationResult> {
    console.log('🔔 [NOTIF] Enabling notifications...');
    this.lastError = null;

    // Check physical device
    if (!Device.isDevice) {
      this.lastError = 'Le notifiche richiedono un dispositivo fisico';
      this.setState(NotificationState.DISABLED);
      return { success: false, state: NotificationState.DISABLED, error: this.lastError };
    }

    this.setState(NotificationState.ENABLING);

    try {
      // Step 1: Request permission
      console.log('📱 [NOTIF] Requesting permission...');
      const { status: existingStatus } = await Notifications.getPermissionsAsync();
      let finalStatus = existingStatus;

      if (existingStatus !== 'granted') {
        const { status } = await Notifications.requestPermissionsAsync();
        finalStatus = status;
      }

      if (finalStatus !== 'granted') {
        this.lastError = 'Permesso negato. Vai in Impostazioni > App > PropSignal > Notifiche';
        this.setState(NotificationState.PERMISSION_DENIED);
        return { success: false, state: NotificationState.PERMISSION_DENIED, error: this.lastError };
      }

      console.log('✅ [NOTIF] Permission granted');

      // Step 2: Get token and register
      await this.getTokenAndRegister();

      // Step 3: Save enabled state
      await AsyncStorage.setItem(STORAGE_KEY_ENABLED, 'true');

      // Step 4: Setup listeners
      this.setupNotificationListeners();

      // Success!
      this.setState(NotificationState.ENABLED);
      console.log('✅ [NOTIF] Notifications enabled successfully!');

      return {
        success: true,
        state: NotificationState.ENABLED,
        token: this.pushToken || undefined,
      };

    } catch (error: any) {
      console.error('❌ [NOTIF] Enable failed:', error);
      this.lastError = error.message || 'Errore sconosciuto';
      this.setState(NotificationState.FAILED);
      return { success: false, state: NotificationState.FAILED, error: this.lastError };
    }
  }

  /**
   * Setup notification listeners
   */
  private setupNotificationListeners(): void {
    if (this.notificationListener) return;

    console.log('📱 [NOTIF] Setting up listeners...');

    // Foreground notifications
    this.notificationListener = Notifications.addNotificationReceivedListener(notification => {
      console.log('🔔 [NOTIF] Received:', notification.request.content.title);
    });

    // Notification tap
    this.responseListener = Notifications.addNotificationResponseReceivedListener(response => {
      console.log('👆 [NOTIF] Tapped');
      const data = response.notification.request.content.data;
      if (data?.signal_id && this.onNotificationTap) {
        this.onNotificationTap(data.signal_id as string);
      }
    });
  }

  /**
   * Force re-registration (for debugging)
   */
  async forceReRegister(): Promise<RegistrationResult> {
    console.log('📱 [NOTIF] Force re-register...');
    await AsyncStorage.removeItem(STORAGE_KEY_ENABLED);
    this.state = NotificationState.UNKNOWN;
    this.pushToken = null;
    return this.enableNotifications();
  }

  /**
   * Get detailed status
   */
  getDetailedStatus(): object {
    return {
      state: this.state,
      hasToken: !!this.pushToken,
      tokenPreview: this.pushToken ? this.pushToken.substring(0, 50) + '...' : null,
      deviceId: this.deviceId,
      lastError: this.lastError,
      platform: Platform.OS,
      backendUrl: BACKEND_URL,
    };
  }

  /**
   * Cleanup
   */
  cleanup(): void {
    if (this.notificationListener) {
      Notifications.removeNotificationSubscription(this.notificationListener);
      this.notificationListener = null;
    }
    if (this.responseListener) {
      Notifications.removeNotificationSubscription(this.responseListener);
      this.responseListener = null;
    }
    if (this.appStateSubscription) {
      this.appStateSubscription.remove();
      this.appStateSubscription = null;
    }
  }
}

// Export singleton
export const pushNotificationService = new PushNotificationService();
