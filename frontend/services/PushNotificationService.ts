/**
 * Push Notification Service - Production-grade push notifications
 * ================================================================
 * 
 * This service handles:
 * - Permission requests
 * - Push token registration
 * - Backend device registration
 * - PERSISTENT STATE (survives app restart)
 * - Prevents duplicate registrations
 * 
 * Architecture:
 * - Backend scanner generates signals
 * - Backend sends push to registered devices via FCM
 * - App receives notifications even when closed
 */

import * as Notifications from 'expo-notifications';
import * as Device from 'expo-device';
import { Platform } from 'react-native';
import Constants from 'expo-constants';
import AsyncStorage from '@react-native-async-storage/async-storage';
import { BACKEND_URL } from '../config/api';

// Storage keys for persistent state
const STORAGE_KEYS = {
  PUSH_TOKEN: 'propsignal_push_token',
  DEVICE_ID: 'propsignal_device_id',
  NOTIFICATIONS_ENABLED: 'propsignal_notifications_enabled',
  REGISTERED_WITH_BACKEND: 'propsignal_registered_backend',
  LAST_REGISTRATION_TIME: 'propsignal_last_registration',
};

// Notification states
export enum NotificationState {
  UNKNOWN = 'UNKNOWN',
  DISABLED = 'DISABLED',
  PERMISSION_DENIED = 'PERMISSION_DENIED',
  ENABLING = 'ENABLING',
  REGISTERING = 'REGISTERING',
  ENABLED = 'ENABLED',
  FAILED = 'FAILED'
}

// Registration result
export interface RegistrationResult {
  success: boolean;
  state: NotificationState;
  token?: string;
  error?: string;
  details?: string;
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
  private isRegisteredWithBackend: boolean = false;
  private lastError: string | null = null;
  private isInitialized: boolean = false;

  // Callbacks
  onNotificationTap: ((signalId: string) => void) | null = null;
  onStateChange: ((state: NotificationState) => void) | null = null;

  /**
   * Get current notification state
   */
  getState(): NotificationState {
    return this.state;
  }

  /**
   * Get push token if available
   */
  getToken(): string | null {
    return this.pushToken;
  }

  /**
   * Check if registered with backend
   */
  isRegistered(): boolean {
    return this.isRegisteredWithBackend;
  }

  /**
   * Get last error message
   */
  getLastError(): string | null {
    return this.lastError;
  }

  /**
   * Update state and notify listeners
   */
  private setState(newState: NotificationState) {
    this.state = newState;
    console.log(`📱 [NOTIF STATE] ${newState}`);
    this.onStateChange?.(newState);
  }

  /**
   * Load persisted state from AsyncStorage
   */
  private async loadPersistedState(): Promise<void> {
    try {
      console.log('📱 [NOTIF] Loading persisted state...');
      
      const [savedToken, savedDeviceId, savedEnabled, savedRegistered] = await Promise.all([
        AsyncStorage.getItem(STORAGE_KEYS.PUSH_TOKEN),
        AsyncStorage.getItem(STORAGE_KEYS.DEVICE_ID),
        AsyncStorage.getItem(STORAGE_KEYS.NOTIFICATIONS_ENABLED),
        AsyncStorage.getItem(STORAGE_KEYS.REGISTERED_WITH_BACKEND),
      ]);

      if (savedToken) {
        this.pushToken = savedToken;
        console.log(`📱 [NOTIF] Loaded saved token: ${savedToken.substring(0, 30)}...`);
      }
      
      if (savedDeviceId) {
        this.deviceId = savedDeviceId;
        console.log(`📱 [NOTIF] Loaded saved device ID: ${savedDeviceId.substring(0, 20)}...`);
      }
      
      if (savedRegistered === 'true') {
        this.isRegisteredWithBackend = true;
        console.log('📱 [NOTIF] Device was previously registered with backend');
      }
      
      if (savedEnabled === 'true' && this.pushToken && this.isRegisteredWithBackend) {
        console.log('📱 [NOTIF] Restoring ENABLED state from persistence');
      }
      
    } catch (error) {
      console.error('📱 [NOTIF] Error loading persisted state:', error);
    }
  }

  /**
   * Save state to AsyncStorage
   */
  private async persistState(): Promise<void> {
    try {
      const promises: Promise<void>[] = [];
      
      if (this.pushToken) {
        promises.push(AsyncStorage.setItem(STORAGE_KEYS.PUSH_TOKEN, this.pushToken));
      }
      
      if (this.deviceId) {
        promises.push(AsyncStorage.setItem(STORAGE_KEYS.DEVICE_ID, this.deviceId));
      }
      
      promises.push(AsyncStorage.setItem(
        STORAGE_KEYS.NOTIFICATIONS_ENABLED, 
        (this.state === NotificationState.ENABLED).toString()
      ));
      
      promises.push(AsyncStorage.setItem(
        STORAGE_KEYS.REGISTERED_WITH_BACKEND, 
        this.isRegisteredWithBackend.toString()
      ));
      
      promises.push(AsyncStorage.setItem(
        STORAGE_KEYS.LAST_REGISTRATION_TIME,
        new Date().toISOString()
      ));
      
      await Promise.all(promises);
      console.log('📱 [NOTIF] State persisted to storage');
      
    } catch (error) {
      console.error('📱 [NOTIF] Error persisting state:', error);
    }
  }

  /**
   * Check current permission status and restore state
   * This is the MAIN initialization method - call this on app startup
   */
  async checkPermissionStatus(): Promise<NotificationState> {
    try {
      console.log('📱 [NOTIF] Checking permission status...');
      
      // Load persisted state first
      if (!this.isInitialized) {
        await this.loadPersistedState();
        this.isInitialized = true;
      }

      // Not a physical device
      if (!Device.isDevice) {
        console.log('📱 [NOTIF] Not a physical device');
        this.setState(NotificationState.DISABLED);
        this.lastError = 'Push notifications require a physical device';
        return NotificationState.DISABLED;
      }

      // Check system permission
      const { status } = await Notifications.getPermissionsAsync();
      console.log(`📱 [NOTIF] System permission status: ${status}`);
      
      if (status === 'granted') {
        // Permission granted - check if we have valid saved state
        if (this.pushToken && this.isRegisteredWithBackend) {
          console.log('📱 [NOTIF] Already registered - restoring ENABLED state');
          this.setState(NotificationState.ENABLED);
          
          // Set up listeners
          this.setupNotificationListeners();
          
          // Optionally verify token is still valid with backend (background)
          this.verifyBackendRegistration();
          
          return NotificationState.ENABLED;
        }
        
        // Permission granted but not registered - need to complete registration
        console.log('📱 [NOTIF] Permission granted but not fully registered');
        return NotificationState.UNKNOWN;
        
      } else if (status === 'denied') {
        console.log('📱 [NOTIF] Permission denied');
        this.setState(NotificationState.PERMISSION_DENIED);
        return NotificationState.PERMISSION_DENIED;
      }
      
      console.log('📱 [NOTIF] Permission not determined');
      this.setState(NotificationState.DISABLED);
      return NotificationState.DISABLED;
      
    } catch (error) {
      console.error('📱 [NOTIF] Error checking permissions:', error);
      return NotificationState.UNKNOWN;
    }
  }

  /**
   * Verify registration is still valid with backend
   * Called in background, doesn't block UI
   * ALWAYS re-registers to ensure backend has current token
   */
  private async verifyBackendRegistration(): Promise<void> {
    try {
      if (!this.pushToken) {
        console.log('📱 [NOTIF] No push token - cannot verify');
        return;
      }
      
      console.log('📱 [NOTIF] Verifying backend registration...');
      
      // ALWAYS re-register to ensure backend has the token
      // This fixes issues where backend lost device data
      console.log('📱 [NOTIF] Force re-registering with backend to ensure sync...');
      await this.registerWithBackend();
      console.log('📱 [NOTIF] Backend registration verified and synced');
      
    } catch (error) {
      console.error('📱 [NOTIF] Error verifying backend registration:', error);
    }
  }

  /**
   * Full enable notifications flow
   * Returns detailed result of each step
   */
  async enableNotifications(): Promise<RegistrationResult> {
    console.log('🔔 [NOTIF] Starting notification enable flow...');
    this.lastError = null;

    // Load persisted state if not already done
    if (!this.isInitialized) {
      await this.loadPersistedState();
      this.isInitialized = true;
    }

    // Step 1: Check if physical device
    if (!Device.isDevice) {
      this.setState(NotificationState.DISABLED);
      this.lastError = 'Le notifiche push richiedono un dispositivo fisico (non simulatore)';
      return {
        success: false,
        state: NotificationState.DISABLED,
        error: this.lastError,
        details: 'Device.isDevice returned false'
      };
    }

    // Step 2: Check if already fully enabled
    if (this.state === NotificationState.ENABLED && this.pushToken && this.isRegisteredWithBackend) {
      console.log('📱 [NOTIF] Already enabled - skipping registration');
      return {
        success: true,
        state: NotificationState.ENABLED,
        token: this.pushToken,
        details: 'Already registered'
      };
    }

    // Step 3: Request permissions
    this.setState(NotificationState.ENABLING);
    console.log('📱 [NOTIF] Requesting notification permissions...');

    try {
      const { status: existingStatus } = await Notifications.getPermissionsAsync();
      let finalStatus = existingStatus;

      if (existingStatus !== 'granted') {
        console.log('📱 [NOTIF] Permission not granted, requesting...');
        const { status } = await Notifications.requestPermissionsAsync();
        finalStatus = status;
      }

      if (finalStatus !== 'granted') {
        this.setState(NotificationState.PERMISSION_DENIED);
        this.lastError = 'Permesso notifiche negato. Vai in Impostazioni > Notifiche per abilitarle.';
        return {
          success: false,
          state: NotificationState.PERMISSION_DENIED,
          error: this.lastError,
          details: `Permission status: ${finalStatus}`
        };
      }

      console.log('✅ [NOTIF] Permission granted');

    } catch (error: any) {
      console.error('❌ [NOTIF] Permission error:', error);
      this.setState(NotificationState.FAILED);
      this.lastError = `Errore permessi: ${error.message}`;
      return {
        success: false,
        state: NotificationState.FAILED,
        error: this.lastError,
        details: error.toString()
      };
    }

    // Step 4: Get push token
    this.setState(NotificationState.REGISTERING);
    console.log('📱 [NOTIF] Getting push token...');

    try {
      // PRIORITY: Get native FCM token for direct FCM v1 API communication
      if (Platform.OS === 'android') {
        try {
          console.log('📱 [NOTIF] Attempting to get native FCM token...');
          const nativeTokenData = await Notifications.getDevicePushTokenAsync();
          if (nativeTokenData?.data) {
            this.pushToken = nativeTokenData.data;
            console.log('✅ [NOTIF] Native FCM token obtained:', this.pushToken.substring(0, 30) + '...');
          }
        } catch (nativeError: any) {
          console.log('⚠️ [NOTIF] Native token failed (expected in Expo Go):', nativeError.message);
        }
      }

      // Fallback: Get Expo push token if native token not available
      if (!this.pushToken) {
        console.log('📱 [NOTIF] Falling back to Expo push token...');
        const projectId = Constants.expoConfig?.extra?.eas?.projectId;
        console.log('📱 [NOTIF] Project ID:', projectId || 'not set');

        let tokenData;
        
        if (projectId) {
          tokenData = await Notifications.getExpoPushTokenAsync({
            projectId: projectId,
          });
        } else {
          tokenData = await Notifications.getExpoPushTokenAsync();
        }
        
        this.pushToken = tokenData.data;
        console.log('✅ [NOTIF] Expo push token obtained:', this.pushToken);
      }

      if (!this.pushToken) {
        throw new Error('Token non valido ricevuto');
      }

    } catch (error: any) {
      console.error('❌ [NOTIF] Token error:', error);
      this.setState(NotificationState.FAILED);
      this.lastError = `Errore token: ${error.message}`;
      return {
        success: false,
        state: NotificationState.FAILED,
        error: this.lastError,
        details: error.toString()
      };
    }

    // Step 5: Register with backend
    console.log('📱 [NOTIF] Registering with backend...');

    try {
      await this.registerWithBackend();
      
      // Step 6: Set up listeners and persist state
      this.setupNotificationListeners();
      await this.persistState();
      
      this.setState(NotificationState.ENABLED);
      
      return {
        success: true,
        state: NotificationState.ENABLED,
        token: this.pushToken!,
        details: 'Successfully registered with backend'
      };

    } catch (error: any) {
      console.error('❌ [NOTIF] Backend registration error:', error);
      this.setState(NotificationState.FAILED);
      this.lastError = `Errore registrazione: ${error.message}`;
      return {
        success: false,
        state: NotificationState.FAILED,
        error: this.lastError,
        details: error.toString()
      };
    }
  }

  /**
   * Register device with backend
   */
  private async registerWithBackend(): Promise<void> {
    // Generate device ID if needed
    if (!this.deviceId) {
      const deviceBrand = Device.brand || 'Unknown';
      const deviceModel = Device.modelName || 'Device';
      const timestamp = Date.now();
      this.deviceId = `${deviceModel.replace(/\s+/g, '_')}_${Platform.OS}_${timestamp}`;
    }

    console.log(`📱 [NOTIF] Registering device: ${this.deviceId.substring(0, 25)}...`);
    console.log(`📱 [NOTIF] Token: ${this.pushToken?.substring(0, 40)}...`);

    const response = await fetch(`${BACKEND_URL}/api/register-device`, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
      },
      body: JSON.stringify({
        device_id: this.deviceId,
        push_token: this.pushToken,
        platform: Platform.OS,
        device_name: `${Device.brand} ${Device.modelName}`,
      }),
    });

    if (!response.ok) {
      const errorData = await response.json().catch(() => ({}));
      throw new Error(errorData.detail || `HTTP ${response.status}`);
    }

    const result = await response.json();
    console.log(`✅ [NOTIF] Backend registration: ${result.status}`);
    
    this.isRegisteredWithBackend = true;
  }

  /**
   * Set up notification listeners
   */
  private setupNotificationListeners(): void {
    // Only set up once
    if (this.notificationListener) return;
    
    console.log('📱 [NOTIF] Setting up notification listeners...');

    // Foreground notifications
    this.notificationListener = Notifications.addNotificationReceivedListener(notification => {
      console.log('🔔 [NOTIF] Received notification:', notification.request.identifier);
    });

    // Notification tap handler
    this.responseListener = Notifications.addNotificationResponseReceivedListener(response => {
      console.log('👆 [NOTIF] Notification tapped');
      const data = response.notification.request.content.data;
      
      if (data?.signal_id && this.onNotificationTap) {
        this.onNotificationTap(data.signal_id as string);
      }
    });
  }

  /**
   * Get detailed status for debugging
   */
  getDetailedStatus(): object {
    return {
      state: this.state,
      isInitialized: this.isInitialized,
      hasToken: !!this.pushToken,
      tokenPreview: this.pushToken ? this.pushToken.substring(0, 40) + '...' : null,
      hasDeviceId: !!this.deviceId,
      isRegisteredWithBackend: this.isRegisteredWithBackend,
      lastError: this.lastError,
      platform: Platform.OS,
      isPhysicalDevice: Device.isDevice,
    };
  }

  /**
   * Force re-registration (for debugging)
   */
  async forceReRegister(): Promise<RegistrationResult> {
    console.log('📱 [NOTIF] Force re-registration requested');
    
    // Clear persisted state
    this.isRegisteredWithBackend = false;
    this.isInitialized = false;
    
    await AsyncStorage.multiRemove([
      STORAGE_KEYS.PUSH_TOKEN,
      STORAGE_KEYS.REGISTERED_WITH_BACKEND,
    ]);
    
    return this.enableNotifications();
  }

  /**
   * Clean up resources
   */
  cleanup(): void {
    console.log('📱 [NOTIF] Cleaning up...');
    
    if (this.notificationListener) {
      Notifications.removeNotificationSubscription(this.notificationListener);
      this.notificationListener = null;
    }
    
    if (this.responseListener) {
      Notifications.removeNotificationSubscription(this.responseListener);
      this.responseListener = null;
    }
  }
}

// Export singleton
export const pushNotificationService = new PushNotificationService();
