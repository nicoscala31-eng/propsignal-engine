import { Stack } from 'expo-router';
import { SafeAreaProvider } from 'react-native-safe-area-context';

export default function RootLayout() {
  return (
    <SafeAreaProvider>
      <Stack
        screenOptions={{
          headerStyle: {
            backgroundColor: '#0a0a0a',
          },
          headerTintColor: '#00ff88',
          headerTitleStyle: {
            fontWeight: 'bold',
          },
        }}
      >
        <Stack.Screen name="index" options={{ headerShown: false }} />
        <Stack.Screen name="signal-detail" options={{ title: 'Signal Details' }} />
        <Stack.Screen name="prop-profiles" options={{ title: 'Prop Profiles' }} />
        <Stack.Screen name="create-profile" options={{ title: 'Create Profile' }} />
        <Stack.Screen name="analytics" options={{ title: 'Analytics' }} />
      </Stack>
    </SafeAreaProvider>
  );
}
