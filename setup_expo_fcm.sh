#!/bin/bash
# ============================================
# Script per configurare FCM su Expo
# Esegui questo script sul tuo computer
# ============================================

echo "🔧 Configurazione FCM per Expo Push Notifications"
echo ""

# Verifica che il file service account esista
SERVICE_ACCOUNT_FILE="backend/credentials/firebase-service-account.json"

if [ ! -f "$SERVICE_ACCOUNT_FILE" ]; then
    echo "❌ File non trovato: $SERVICE_ACCOUNT_FILE"
    echo "   Assicurati di essere nella directory principale del progetto"
    exit 1
fi

echo "✅ File service account trovato"
echo ""

# Login su Expo
echo "📱 Step 1: Login su Expo..."
npx eas login

# Configura le credenziali
echo ""
echo "📱 Step 2: Caricamento credenziali FCM..."
echo "   Quando richiesto:"
echo "   1. Seleziona 'Google Service Account'"
echo "   2. Seleziona 'Manage your Google Service Account Key for Push Notifications (FCM V1)'"
echo "   3. Seleziona 'Upload a new service account key'"
echo "   4. Conferma il file rilevato automaticamente"
echo ""

cd frontend
npx eas credentials -p android

echo ""
echo "✅ Configurazione completata!"
echo "   Ora le notifiche push funzioneranno."
