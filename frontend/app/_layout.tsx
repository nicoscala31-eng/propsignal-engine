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
        <Stack.Screen 
          name="index" 
          options={{ 
            headerShown: false,
            title: 'PropSignal Engine'
          }} 
        />
        <Stack.Screen 
          name="signals" 
          options={{ 
            title: 'Signal Feed',
            presentation: 'card'
          }} 
        />
        <Stack.Screen 
          name="signal-snapshot" 
          options={{ 
            title: 'Signal Details',
            presentation: 'card'
          }} 
        />
        <Stack.Screen 
          name="signal-detail" 
          options={{ 
            title: 'Signal Details',
            presentation: 'card'
          }} 
        />
        <Stack.Screen 
          name="analytics" 
          options={{ 
            title: 'Analytics',
            presentation: 'card'
          }} 
        />
        <Stack.Screen 
          name="prop-profiles" 
          options={{ 
            title: 'Prop Profiles',
            presentation: 'card'
          }} 
        />
      </Stack>
    </SafeAreaProvider>
  );
}
