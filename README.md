# PropSignal Engine

Professional trading signal platform with real-time market data, automated scanning, and push notifications.

## Features

- **Live Market Data**: Real-time EURUSD and XAUUSD prices via Twelve Data API
- **Automated Scanner**: Background service scanning markets every 30 seconds
- **Push Notifications**: Instant alerts for BUY/SELL signals via Expo Push
- **Signal Tracking**: Automatic outcome tracking (Take Profit / Stop Loss)
- **Analytics Dashboard**: Performance metrics and historical analysis
- **Prop Firm Profiles**: Multiple operational profiles (Aggressive, Defensive, Prop Firm Safe)

## Architecture

```
├── backend/                 # FastAPI backend
│   ├── server.py           # Main application
│   ├── services/           # Core services
│   │   ├── market_scanner.py
│   │   ├── market_data_engine.py
│   │   ├── push_notification_service.py
│   │   └── signal_outcome_tracker.py
│   ├── providers/          # Data providers
│   │   └── twelve_data_provider.py
│   └── engines/            # Analysis engines
└── frontend/               # Expo React Native app
    └── app/                # Screens
```

## Railway Deployment

### Environment Variables Required

```bash
# Required
MONGO_URL=mongodb+srv://username:password@cluster.mongodb.net/dbname
DB_NAME=propsignal

# Required for live market data
TWELVE_DATA_API_KEY=your_twelve_data_api_key

# Railway auto-sets this
PORT=8001
```

### Deploy Command

Railway will use the `Procfile`:
```
web: uvicorn server:app --host 0.0.0.0 --port $PORT
```

### Quick Deploy Steps

1. Push this repo to GitHub
2. Create new project on Railway
3. Connect to your GitHub repository
4. Add environment variables in Railway dashboard
5. Deploy

## API Endpoints

| Endpoint | Description |
|----------|-------------|
| `GET /api/health` | Full health check with diagnostics |
| `GET /api/provider/live-prices` | Current EURUSD/XAUUSD prices |
| `GET /api/scanner/status` | Scanner running status |
| `POST /api/scanner/start` | Start the scanner |
| `POST /api/scanner/stop` | Stop the scanner |
| `GET /api/analytics/summary` | Performance metrics |
| `POST /api/register-device` | Register for push notifications |

## Health Check Response

```json
{
  "status": "healthy",
  "timestamp": "2024-01-01T00:00:00.000Z",
  "backend": { "status": "running", "version": "1.0.0" },
  "twelve_data": { "status": "connected", "is_production": true },
  "prices": {
    "EURUSD": { "bid": 1.0850, "ask": 1.0852 },
    "XAUUSD": { "bid": 2650.50, "ask": 2651.00 }
  },
  "scanner": { "running": true, "total_scans": 100 },
  "tracker": { "running": true, "checks_performed": 50 }
}
```

## Mobile App (Expo)

The frontend is built with Expo SDK 54. To build the Android APK:

```bash
cd frontend
npx eas build --platform android --profile preview
```

## Local Development

### Backend
```bash
cd backend
pip install -r requirements.txt
uvicorn server:app --host 0.0.0.0 --port 8001 --reload
```

### Frontend
```bash
cd frontend
yarn install
npx expo start
```

## License

Proprietary - All rights reserved
