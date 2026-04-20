# MPC Arbitrage Bot

**Phase 1: Orderbook Analyzer** - Read-only analysis of spreads between KuCoin and MEXC

## Features

### Security
- 🔐 Admin registration with mandatory 2FA (TOTP)
- 🔒 Single-user system (no additional registrations after first admin)
- 📊 All activity logged

### Analysis
- 📡 Real-time orderbook monitoring (KuCoin + MEXC)
- 📈 Spread calculation and visualization
- 📊 Statistics: average, min, max spreads
- 🔔 Opportunity detection with hysteresis

### Configuration
- 🎚️ Start/Stop thresholds (0-50% adjustable)
- ⏱️ Hysteresis: Start > threshold, Stop < threshold
- 📝 Configurable via YAML file

## Quick Start

### Local Development

```bash
# Clone and setup
cd trading/arbitrage-bot
./start.sh

# Terminal 1: Start the bot
source venv/bin/activate
python -m bot.main_bot

# Terminal 2: Start dashboard
source venv/bin/activate
streamlit run dashboard/app.py
```

### Docker (Recommended for Production)

```bash
# Build and run
docker-compose up -d

# View logs
docker-compose logs -f

# Stop
docker-compose down
```

### Coolify Deployment

1. Push to your Git repository
2. Connect repository to Coolify
3. Add Docker Compose file
4. Deploy!

## Architecture

```
┌─────────────────────────────────────────────────────────────┐
│                     MPC Arbitrage Bot                       │
├─────────────────────────────────────────────────────────────┤
│                                                             │
│  ┌─────────────┐  ┌─────────────┐  ┌─────────────────┐     │
│  │   KuCoin    │  │    MEXC     │  │   Dashboard     │     │
│  │  Orderbook  │  │  Orderbook  │  │   (Streamlit)   │     │
│  │   Reader    │  │   Reader    │  │                 │     │
│  └──────┬──────┘  └──────┬──────┘  └────────┬────────┘     │
│         │                │                   │              │
│         └────────────────┼──────────────────┘              │
│                          │                                   │
│                   ┌───────▼───────┐                          │
│                   │  Spread       │                          │
│                   │  Analyzer     │                          │
│                   │  + Stats      │                          │
│                   │  + Opp. Det. │                          │
│                   └───────────────┘                          │
│                                                             │
└─────────────────────────────────────────────────────────────┘
```

## Configuration

Edit `config/config.yaml`:

```yaml
trading:
  pair: "MPC-USDT"
  thresholds:
    start: 2.0   # Start arbitrage when spread > 2%
    stop: 1.0    # Stop arbitrage when spread < 1%
  mode: "test"   # test or live

# API Keys (for Phase 2+)
kucoin:
  api_key: "your-key"
  api_secret: "your-secret"
  api_passphrase: "your-passphrase"

mexc:
  api_key: "your-key"
  api_secret: "your-secret"
```

## Phases

### Phase 1: Orderbook Analysis (Current) ✅
- Read-only orderbook monitoring
- Spread analysis and statistics
- Dashboard visualization
- **No trading**

### Phase 2: Mini-Test Orders (Planned)
- Execute small real orders
- Validate algorithm
- Fine-tune thresholds

### Phase 3: Live Trading (Planned)
- Full arbitrage execution
- Automatic mode
- Profit/loss tracking

## API Keys Required

### KuCoin
1. Go to [KuCoin API](https://www.kucoin.com/account/api)
2. Create API Key with "Trade" permission
3. Copy Key, Secret, and Passphrase

### MEXC
1. Go to [MEXC API](https://www.mexc.com/account/api)
2. Create API Key with "Spot Trading" permission
3. Copy Key and Secret

## Troubleshooting

### Bot not connecting
- Check internet connection
- Verify API keys are correct
- Check if exchanges are operational

### Dashboard not loading
- Ensure port 8501 is not in use
- Check if bot is running

### "No opportunities found"
- This is normal in Phase 1 (read-only)
- Spread thresholds may need adjustment
- MPC may have low volatility

## License

Private - For Jonas Hillmann use only
