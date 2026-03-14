#!/bin/bash
# =============================================================================
# CONFIGURAZIONE FCM PER EXPO PUSH NOTIFICATIONS
# =============================================================================
#
# Questo script configura le credenziali FCM su Expo per abilitare
# le notifiche push su Android.
#
# PREREQUISITI:
# 1. Devi avere accesso al progetto Firebase "propsignal-16806"
# 2. Devi generare un Service Account Key da Firebase
#
# COME OTTENERE IL SERVICE ACCOUNT KEY:
# 1. Vai su https://console.firebase.google.com/
# 2. Seleziona il progetto "propsignal-16806"
# 3. Vai su ⚙️ Project Settings → Service Accounts
# 4. Clicca "Generate New Private Key"
# 5. Salva il file JSON scaricato
# 6. Rinomina il file in: firebase-service-account.json
# 7. Copialo nella cartella: /app/frontend/
#
# COME USARE QUESTO SCRIPT:
# 1. Metti il file firebase-service-account.json in /app/frontend/
# 2. Esegui: bash /app/frontend/setup-fcm.sh
#
# =============================================================================

set -e

# Colori
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

echo "=============================================="
echo "  CONFIGURAZIONE FCM PER EXPO"
echo "=============================================="
echo ""

# Verifica che il file esista
SERVICE_ACCOUNT_FILE="/app/frontend/firebase-service-account.json"

if [ ! -f "$SERVICE_ACCOUNT_FILE" ]; then
    echo -e "${RED}ERRORE: File non trovato!${NC}"
    echo ""
    echo "Per favore:"
    echo "1. Vai su Firebase Console → Project Settings → Service Accounts"
    echo "2. Genera un nuovo Private Key"
    echo "3. Salva il file come: $SERVICE_ACCOUNT_FILE"
    echo ""
    exit 1
fi

echo -e "${GREEN}✓ File Service Account trovato${NC}"

# Verifica il contenuto del file
if ! python3 -c "import json; json.load(open('$SERVICE_ACCOUNT_FILE'))" 2>/dev/null; then
    echo -e "${RED}ERRORE: Il file non è un JSON valido${NC}"
    exit 1
fi

PROJECT_ID=$(python3 -c "import json; print(json.load(open('$SERVICE_ACCOUNT_FILE')).get('project_id', ''))")
CLIENT_EMAIL=$(python3 -c "import json; print(json.load(open('$SERVICE_ACCOUNT_FILE')).get('client_email', ''))")

echo -e "${GREEN}✓ Project ID: $PROJECT_ID${NC}"
echo -e "${GREEN}✓ Client Email: $CLIENT_EMAIL${NC}"
echo ""

# Verifica token EAS
if [ -z "$EXPO_TOKEN" ]; then
    export EXPO_TOKEN="jdd8CuJ33AOqUbjMXnOL-TKeKByL7wLhC2PQvPSB"
fi

echo "Configurazione credenziali FCM su Expo..."
echo ""

cd /app/frontend

# Usa EAS CLI per configurare le credenziali
# Questo richiede interazione, quindi usiamo expect se disponibile
if command -v expect &> /dev/null; then
    expect << 'EXPECT_SCRIPT'
    set timeout 60
    spawn env EXPO_TOKEN=jdd8CuJ33AOqUbjMXnOL-TKeKByL7wLhC2PQvPSB eas credentials --platform android
    
    expect "What do you want to configure?"
    send "2\r"
    
    expect "What do you want to do?"
    send "1\r"
    
    expect "path to your Google Service Account Key"
    send "/app/frontend/firebase-service-account.json\r"
    
    expect eof
EXPECT_SCRIPT
else
    echo -e "${YELLOW}Expect non installato. Esegui manualmente:${NC}"
    echo ""
    echo "  cd /app/frontend"
    echo "  EXPO_TOKEN=jdd8CuJ33AOqUbjMXnOL-TKeKByL7wLhC2PQvPSB eas credentials --platform android"
    echo ""
    echo "E seleziona:"
    echo "  1. Push Notifications"
    echo "  2. Upload Google Service Account Key"
    echo "  3. Inserisci il path: $SERVICE_ACCOUNT_FILE"
fi

echo ""
echo "=============================================="
echo -e "${GREEN}  CONFIGURAZIONE COMPLETATA${NC}"
echo "=============================================="
echo ""
echo "Prossimi passi:"
echo "1. Ricompila l'APK con: eas build --platform android --profile preview"
echo "2. Installa il nuovo APK"
echo "3. Attiva le notifiche nell'app"
echo "4. Testa con: curl -X POST https://propsignal-engine-production-b22b.up.railway.app/api/push/test"
