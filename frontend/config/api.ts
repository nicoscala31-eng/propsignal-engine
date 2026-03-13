/**
 * API Configuration - Centralized backend URL management
 * ======================================================
 * 
 * This module ensures the app ALWAYS uses the production Railway backend
 * in APK builds, preventing the app from breaking when the Emergent
 * development environment goes offline.
 */

import Constants from 'expo-constants';

// Production backend URL - Railway deployment
const PRODUCTION_BACKEND_URL = 'https://propsignal-engine-production-b22b.up.railway.app';

/**
 * Get the backend URL for API calls
 * 
 * In production (APK builds): Always returns Railway URL
 * In development (__DEV__): Can use local/custom URLs for testing
 */
export const getBackendUrl = (): string => {
  // In development mode, allow override for local testing
  if (__DEV__) {
    const envUrl = process.env.EXPO_PUBLIC_BACKEND_URL;
    const configUrl = Constants.expoConfig?.extra?.backendUrl;
    
    // Only use dev URLs if they're NOT Emergent/ngrok URLs
    // This prevents accidentally using dev URLs in production
    if (envUrl && !envUrl.includes('emergentagent.com') && !envUrl.includes('ngrok')) {
      console.log('🔧 Using env backend URL:', envUrl);
      return envUrl;
    }
    if (configUrl && !configUrl.includes('emergentagent.com') && !configUrl.includes('ngrok')) {
      console.log('🔧 Using config backend URL:', configUrl);
      return configUrl;
    }
  }
  
  // Always return production URL for APK builds and as fallback
  return PRODUCTION_BACKEND_URL;
};

// Export the URL for direct use
export const BACKEND_URL = getBackendUrl();

// Log which backend is being used (only once at import time)
console.log('🔗 API Config: Using backend:', BACKEND_URL);
