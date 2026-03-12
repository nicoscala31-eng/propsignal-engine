import * as Notifications from 'expo-notifications';
import * as Device from 'expo-device';
import { Platform } from 'react-native';
import Constants from 'expo-constants';

// Get backend URL from app.json extra config (works in production builds)
const BACKEND_URL = Constants.expoConfig?.extra?.backendUrl || process.env.EXPO_PUBLIC_BACKEND_URL || 'https://eurusd-alerts.preview.emergentagent.com';

// Configure how notifications appear when app is in foreground
Notifications.setNotificationHandler({
  handleNotification: async () => ({
    shouldShowAlert: true,
    shouldPlaySound: true,
    shouldSetBadge: true,
    shouldShowBanner: true,
    shouldShowList: true,
  }),
});

export interface SignalNotification {
  signalType: 'BUY' | 'SELL';
  asset: 'EURUSD' | 'XAUUSD';
  entryPrice?: number;
  confidence?: number;
  signalId: string;
}

class NotificationService {
  private expoPushToken: string | null = null;
  private deviceId: string | null = null;
  private notificationListener: any = null;
  private responseListener: any = null;
  private isRegisteredWithBackend: boolean = false;

  async initialize(): Promise<string | null> {
    try {
      // Request permissions and get token
      const token = await this.registerForPushNotifications();
      
      // Set up listeners
      this.setupListeners();
      
      // Register device with backend
      if (token) {
        await this.registerDeviceWithBackend(token);
      }
      
      return token;
    } catch (error) {
      console.error('Failed to initialize notifications:', error);
      return null;
    }
  }

  private async registerForPushNotifications(): Promise<string | null> {
    let token = null;

    // Check if physical device (push notifications don't work on simulators)
    if (Device.isDevice) {
      const { status: existingStatus } = await Notifications.getPermissionsAsync();
      let finalStatus = existingStatus;

      if (existingStatus !== 'granted') {
        const { status } = await Notifications.requestPermissionsAsync();
        finalStatus = status;
      }

      if (finalStatus !== 'granted') {
        console.log('Failed to get push token for notifications!');
        return null;
      }

      // Get Expo push token
      try {
        const projectId = Constants.expoConfig?.extra?.eas?.projectId || 'propsignal-engine-2026';
        token = (await Notifications.getExpoPushTokenAsync({
          projectId: projectId,
        })).data;
        console.log('Expo Push Token:', token);
      } catch (e) {
        // Try without projectId as fallback
        console.log('Error getting push token with projectId, trying fallback:', e);
        try {
          token = (await Notifications.getExpoPushTokenAsync()).data;
          console.log('Expo Push Token (fallback):', token);
        } catch (e2) {
          console.log('Error getting push token (fallback):', e2);
        }
      }
    } else {
      console.log('Must use physical device for push notifications');
    }

    // Android specific channel setup
    if (Platform.OS === 'android') {
      await Notifications.setNotificationChannelAsync('signals', {
        name: 'Trading Signals',
        importance: Notifications.AndroidImportance.MAX,
        vibrationPattern: [0, 250, 250, 250],
        lightColor: '#00FF88',
        sound: 'default',
        enableVibrate: true,
        showBadge: true,
      });
      
      // Create alerts channel for pre-signal notifications
      await Notifications.setNotificationChannelAsync('alerts', {
        name: 'Market Alerts',
        importance: Notifications.AndroidImportance.HIGH,
        vibrationPattern: [0, 150, 150, 150],
        lightColor: '#FFaa00',
        sound: 'default',
      });
    }

    this.expoPushToken = token;
    return token;
  }

  private async registerDeviceWithBackend(token: string): Promise<void> {
    try {
      // Generate a unique device ID
      this.deviceId = `${Device.modelName || 'unknown'}_${Device.osName}_${Date.now()}`;
      
      const response = await fetch(`${BACKEND_URL}/api/register-device`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          push_token: token,
          platform: Platform.OS,
          device_id: this.deviceId,
          device_name: Device.deviceName || Device.modelName
        })
      });
      
      if (response.ok) {
        const data = await response.json();
        this.isRegisteredWithBackend = true;
        console.log(`📱 Device registered with backend: ${data.status}`);
      } else {
        console.error('Failed to register device with backend');
      }
    } catch (error) {
      console.error('Error registering device:', error);
    }
  }

  private setupListeners() {
    // Handle notifications received while app is foregrounded
    this.notificationListener = Notifications.addNotificationReceivedListener(notification => {
      console.log('Notification received:', notification);
    });

    // Handle notification responses (when user taps notification)
    this.responseListener = Notifications.addNotificationResponseReceivedListener(response => {
      console.log('Notification response:', response);
      const data = response.notification.request.content.data;
      
      // Handle different notification types
      if (data?.type === 'signal' && data?.signalId) {
        this.onNotificationTap?.(data.signalId as string);
      } else if (data?.signalId) {
        this.onNotificationTap?.(data.signalId as string);
      }
    });
  }

  // Callback for when notification is tapped
  onNotificationTap: ((signalId: string) => void) | null = null;

  async sendLocalSignalNotification(signal: SignalNotification): Promise<void> {
    const { signalType, asset, entryPrice, confidence, signalId } = signal;
    
    const title = `🔔 ${signalType} Signal: ${asset}`;
    const body = entryPrice 
      ? `Entry: ${asset === 'EURUSD' ? entryPrice.toFixed(5) : entryPrice.toFixed(2)} | Confidence: ${confidence?.toFixed(0)}%`
      : `New ${signalType} opportunity detected!`;

    await Notifications.scheduleNotificationAsync({
      content: {
        title,
        body,
        data: { signalId, signalType, asset, type: 'signal' },
        sound: 'default',
        badge: 1,
        ...(Platform.OS === 'android' && { channelId: 'signals' }),
      },
      trigger: null, // Immediate notification
    });

    console.log(`📢 Notification sent: ${title}`);
  }

  async sendBuyNotification(asset: 'EURUSD' | 'XAUUSD', entryPrice: number, confidence: number, signalId: string): Promise<void> {
    await this.sendLocalSignalNotification({
      signalType: 'BUY',
      asset,
      entryPrice,
      confidence,
      signalId,
    });
  }

  async sendSellNotification(asset: 'EURUSD' | 'XAUUSD', entryPrice: number, confidence: number, signalId: string): Promise<void> {
    await this.sendLocalSignalNotification({
      signalType: 'SELL',
      asset,
      entryPrice,
      confidence,
      signalId,
    });
  }

  getExpoPushToken(): string | null {
    return this.expoPushToken;
  }
  
  isRegistered(): boolean {
    return this.isRegisteredWithBackend;
  }

  cleanup() {
    if (this.notificationListener) {
      this.notificationListener.remove();
    }
    if (this.responseListener) {
      this.responseListener.remove();
    }
  }
}

export const notificationService = new NotificationService();
