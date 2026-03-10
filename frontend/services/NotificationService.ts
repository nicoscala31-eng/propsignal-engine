import * as Notifications from 'expo-notifications';
import * as Device from 'expo-device';
import { Platform } from 'react-native';
import Constants from 'expo-constants';

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
  private notificationListener: any = null;
  private responseListener: any = null;

  async initialize(): Promise<string | null> {
    try {
      // Request permissions
      const token = await this.registerForPushNotifications();
      
      // Set up listeners
      this.setupListeners();
      
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
        const projectId = Constants.expoConfig?.extra?.eas?.projectId;
        token = (await Notifications.getExpoPushTokenAsync({
          projectId: projectId,
        })).data;
        console.log('Expo Push Token:', token);
      } catch (e) {
        console.log('Error getting push token:', e);
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
    }

    this.expoPushToken = token;
    return token;
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
      // Navigation will be handled by the component that uses this service
      if (data?.signalId) {
        // Emit event for navigation
        this.onNotificationTap?.(data.signalId as string);
      }
    });
  }

  // Callback for when notification is tapped
  onNotificationTap: ((signalId: string) => void) | null = null;

  async sendLocalSignalNotification(signal: SignalNotification): Promise<void> {
    const { signalType, asset, entryPrice, confidence, signalId } = signal;
    
    const title = `${signalType} Signal: ${asset}`;
    const body = entryPrice 
      ? `Entry: ${asset === 'EURUSD' ? entryPrice.toFixed(5) : entryPrice.toFixed(2)} | Confidence: ${confidence?.toFixed(0)}%`
      : `New ${signalType} opportunity detected!`;

    await Notifications.scheduleNotificationAsync({
      content: {
        title,
        body,
        data: { signalId, signalType, asset },
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

  cleanup() {
    if (this.notificationListener) {
      Notifications.removeNotificationSubscription(this.notificationListener);
    }
    if (this.responseListener) {
      Notifications.removeNotificationSubscription(this.responseListener);
    }
  }
}

export const notificationService = new NotificationService();
