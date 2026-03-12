/**
 * Push Notification Service - Production-grade push notifications
 * ================================================================
 * 
 * This service handles:
 * - Permission requests
 * - Push token registration
 * - Backend device registration
 * - Real push notification delivery (works with app closed)
 * 
 * Architecture:
 * - Backend scanner generates signals
 * - Backend sends push to registered devices via Expo Push API
 * - App receives notifications even when closed
 */

import * as Notifications from 'expo-notifications';
import * as Device from 'expo-device';
import { Platform } from 'react-native';
import Constants from 'expo-constants';

// Backend URL from environment - dynamically set by deployment
const getBackendUrl = (): string => {
  // First check environment variable (set by deployment)
  if (process.env.EXPO_PUBLIC_BACKEND_URL) {
    return process.env.EXPO_PUBLIC_BACKEND_URL;
  }
  // Check expo config extra
  if (Constants.expoConfig?.extra?.backendUrl) {
    return Constants.expoConfig.extra.backendUrl;
  }
  // Fallback to Railway production URL
  return 'https://propsignal-engine-production-b22b.up.railway.app';
};

const BACKEND_URL = getBackendUrl();

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
    console.log(`📱 Notification state: ${newState}`);
    this.onStateChange?.(newState);
  }

  /**
   * Check current permission status without requesting
   */
  async checkPermissionStatus(): Promise<NotificationState> {
    try {
      if (!Device.isDevice) {
        this.setState(NotificationState.DISABLED);
        this.lastError = 'Push notifications require a physical device';
        return NotificationState.DISABLED;
      }

      const { status } = await Notifications.getPermissionsAsync();
      
      if (status === 'granted') {
        // Check if we have a valid token
        if (this.pushToken && this.isRegisteredWithBackend) {
          this.setState(NotificationState.ENABLED);
          return NotificationState.ENABLED;
        }
        // Permission granted but not fully registered
        return NotificationState.UNKNOWN;
      } else if (status === 'denied') {
        this.setState(NotificationState.PERMISSION_DENIED);
        return NotificationState.PERMISSION_DENIED;
      }
      
      this.setState(NotificationState.DISABLED);
      return NotificationState.DISABLED;
    } catch (error) {
      console.error('Error checking permissions:', error);
      return NotificationState.UNKNOWN;
    }
  }

  /**
   * Full enable notifications flow
   * Returns detailed result of each step
   */
  async enableNotifications(): Promise<RegistrationResult> {
    console.log('🔔 Starting notification enable flow...');
    this.lastError = null;

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

    // Step 2: Request permissions
    this.setState(NotificationState.ENABLING);
    console.log('📱 Requesting notification permissions...');

    try {
      const { status: existingStatus } = await Notifications.getPermissionsAsync();
      let finalStatus = existingStatus;

      if (existingStatus !== 'granted') {
        console.log('📱 Permission not granted, requesting...');
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

      console.log('✅ Permission granted');
    } catch (error: any) {
      this.setState(NotificationState.FAILED);
      this.lastError = `Errore permessi: ${error.message}`;
      return {
        success: false,
        state: NotificationState.FAILED,
        error: this.lastError,
        details: error.toString()
      };
    }

    // Step 3: Get push token
    this.setState(NotificationState.REGISTERING);
    console.log('📱 Getting push token...');

    try {
      // Get project ID from config
      const projectId = Constants.expoConfig?.extra?.eas?.projectId;
      console.log('📱 Project ID:', projectId || 'not set');

      let tokenData;
      
      if (projectId) {
        tokenData = await Notifications.getExpoPushTokenAsync({
          projectId: projectId,
        });
      } else {
        // Fallback without projectId
        tokenData = await Notifications.getExpoPushTokenAsync();
      }

      this.pushToken = tokenData.data;
      console.log('✅ Push token obtained:', this.pushToken);

      if (!this.pushToken || !this.pushToken.startsWith('ExponentPushToken[')) {
        throw new Error('Token non valido ricevuto');
      }
    } catch (error: any) {
      console.error('❌ Token error:', error);
      this.setState(NotificationState.FAILED);
      this.lastError = `Errore token: ${error.message}`;
      return {
        success: false,
        state: NotificationState.FAILED,
        error: this.lastError,
        details: error.toString()
      };
    }

    // Step 4: Setup Android notification channel
    if (Platform.OS === 'android') {
      console.log('📱 Setting up Android notification channel...');
      await Notifications.setNotificationChannelAsync('signals', {
        name: 'Trading Signals',
        importance: Notifications.AndroidImportance.MAX,
        vibrationPattern: [0, 250, 250, 250],
        lightColor: '#00FF88',
        sound: 'default',
        enableVibrate: true,
        showBadge: true,
        lockscreenVisibility: Notifications.AndroidNotificationVisibility.PUBLIC,
      });
    }

    // Step 5: Register with backend
    console.log('📱 Registering with backend...');
    
    try {
      // Generate unique device ID
      this.deviceId = `${Device.modelName || 'device'}_${Platform.OS}_${Date.now()}`;

      const response = await fetch(`${BACKEND_URL}/api/register-device`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          push_token: this.pushToken,
          platform: Platform.OS,
          device_id: this.deviceId,
          device_name: Device.deviceName || Device.modelName || 'Unknown Device',
          device_model: Device.modelName,
          os_version: Device.osVersion,
          app_version: Constants.expoConfig?.version || '1.0.0'
        })
      });

      if (!response.ok) {
        const errorText = await response.text();
        throw new Error(`Backend error: ${response.status} - ${errorText}`);
      }

      const data = await response.json();
      console.log('✅ Backend registration:', data);

      if (data.status === 'registered' || data.status === 'updated') {
        this.isRegisteredWithBackend = true;
      } else {
        throw new Error(`Unexpected response: ${JSON.stringify(data)}`);
      }
    } catch (error: any) {
      console.error('❌ Backend registration error:', error);
      this.setState(NotificationState.FAILED);
      this.lastError = `Errore registrazione backend: ${error.message}`;
      return {
        success: false,
        state: NotificationState.FAILED,
        token: this.pushToken || undefined,
        error: this.lastError,
        details: error.toString()
      };
    }

    // Step 6: Setup listeners
    this.setupListeners();

    // Success!
    this.setState(NotificationState.ENABLED);
    console.log('🎉 Notifications fully enabled!');

    return {
      success: true,
      state: NotificationState.ENABLED,
      token: this.pushToken
    };
  }

  /**
   * Setup notification listeners
   */
  private setupListeners() {
    // Remove existing listeners
    this.cleanup();

    // Handle notifications received while app is foregrounded
    this.notificationListener = Notifications.addNotificationReceivedListener(notification => {
      console.log('📬 Notification received:', notification.request.content.title);
    });

    // Handle notification taps
    this.responseListener = Notifications.addNotificationResponseReceivedListener(response => {
      console.log('👆 Notification tapped');
      const data = response.notification.request.content.data;
      
      if (data?.signalId) {
        this.onNotificationTap?.(data.signalId as string);
      }
    });

    console.log('📱 Notification listeners setup complete');
  }

  /**
   * Cleanup listeners
   */
  cleanup() {
    if (this.notificationListener) {
      Notifications.removeNotificationSubscription(this.notificationListener);
      this.notificationListener = null;
    }
    if (this.responseListener) {
      Notifications.removeNotificationSubscription(this.responseListener);
      this.responseListener = null;
    }
  }

  /**
   * Verify backend can send notifications
   * This triggers a test push from the backend
   */
  async verifyBackendPush(): Promise<{ success: boolean; message: string }> {
    if (!this.isRegisteredWithBackend) {
      return { success: false, message: 'Device not registered with backend' };
    }

    try {
      const response = await fetch(`${BACKEND_URL}/api/push/test`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ device_id: this.deviceId })
      });

      if (!response.ok) {
        const errorText = await response.text();
        return { success: false, message: `Backend error: ${errorText}` };
      }

      const data = await response.json();
      return { 
        success: data.successful > 0, 
        message: data.successful > 0 
          ? 'Test notification sent!' 
          : `No notifications sent: ${JSON.stringify(data)}`
      };
    } catch (error: any) {
      return { success: false, message: error.message };
    }
  }

  /**
   * Get status summary for debugging
   */
  getStatusSummary(): object {
    return {
      state: this.state,
      hasToken: !!this.pushToken,
      tokenPrefix: this.pushToken?.substring(0, 30) + '...',
      isRegisteredWithBackend: this.isRegisteredWithBackend,
      deviceId: this.deviceId,
      lastError: this.lastError,
      isPhysicalDevice: Device.isDevice,
      platform: Platform.OS,
      backendUrl: BACKEND_URL
    };
  }
}

// Export singleton instance
export const pushNotificationService = new PushNotificationService();
