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
          animation: 'slide_from_right',
        }}
      >
        {/* Main screen - Signal Feed (no header, self-contained) */}
        <Stack.Screen 
          name="index" 
          options={{ 
            headerShown: false,
            title: 'Signal Feed'
          }} 
        />
        
        {/* Signal detail screen */}
        <Stack.Screen 
          name="signal-snapshot" 
          options={{ 
            title: 'Signal Details',
            presentation: 'card',
            headerBackTitle: 'Back'
          }} 
        />
        
        {/* Legacy screens - kept for backwards compatibility */}
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
        <Stack.Screen 
          name="signals" 
          options={{ 
            title: 'Signal Feed',
            presentation: 'card'
          }} 
        />
        
        {/* Old home moved - not in navigation stack */}
        <Stack.Screen 
          name="old-home" 
          options={{ 
            title: 'Dashboard',
            presentation: 'card'
          }} 
        />
      </Stack>
    </SafeAreaProvider>
  );
}
