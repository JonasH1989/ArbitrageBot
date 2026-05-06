# ArbitrageBot Projekt

## Lokaler Pfad
```
/home/openclaw/.openclaw/workspace/trading/arbitrage-bot/
```

## GitHub
- **Repo:** https://github.com/JonasH1989/ArbitrageBot.git
- **Branch:** main

## Git Workflow
```bash
cd /home/openclaw/.openclaw/workspace/trading/arbitrage-bot
git pull
# Änderungen machen
git add .
git commit -m "Beschreibung"
git push
```

---

## Architektur

### Trading Bot (arb_autotrade.py)
- Führt automatische Arbitrage-Trades zwischen KuCoin und MEXC aus
- Strategy: Coin-Gewinn (MPC akkumulieren)
- Aktivierung via: `touch /home/openclaw/.openclaw/logs/arb_active.flag`
- Deaktivierung via: `rm /home/openclaw/.openclaw/logs/arb_active.flag`

**Thresholds:**
- Start: 1.0% Spread
- Stop: 0.5% Spread

### Trade Logger (trade_logger.py)
- Harmonisiert Daten von verschiedenen Börsen in ein einheitliches Format
- Eine CSV-Datei pro Trading Pair
- Alle Trades werden append-only geloggt

**UNIFIED_COLUMNS Schema:**
```
trade_id, internal_ts, direction, pair,
ex1_exchange, ex1_order_id, ex1_type, ex1_side, ex1_qty_ordered, ex1_qty_filled,
ex1_price_avg, ex1_value_usdt, ex1_fees, ex1_create_ts, ex1_status,
ex2_exchange, ex2_order_id, ex2_type, ex2_side, ex2_qty_ordered, ex2_qty_filled,
ex2_price_avg, ex2_value_usdt, ex2_fees, ex2_create_ts, ex2_status,
limit_watch_status, limit_last_check,
raw_ex1_response, raw_ex2_response, updated_at
```

### Dashboard (dashboard.py)
- Streamlit-basierte Web-UI
- Zeigt Preise, Spreads, Portfolio und Trade-History
- Zugriff: http://localhost:8501

---

## Harmonization Layer

### Problem
Unterschiedliche Börsen liefern unterschiedliche Datenstrukturen:
- KuCoin: `dealSize`, `dealFunds`, `fee`, `createTime`
- MEXC: `quantity`, `amount`, `fees`, `createTime`

### Lösung
**harmonize_kucoin_order()** und **harmonize_mexc_order()** normalisieren die Responses in unified fields:

| Unified Field | KuCoin Response | MEXC Response |
|---------------|-----------------|---------------|
| exchange | "KUCOIN" | "MEXC" |
| order_id | `orderId` | `orderId` |
| qty_filled | `dealSize` | `quantity` |
| value_usdt | `dealFunds` | `amount` |
| fees | `fee` | `fees` |
| create_ts | `createTime` (ms) | `createTime` (ms) |
| status | "FILLED"/"OPEN" | "Filled"/"New" |

---

## Logging Struktur

### Log Dateien
```
/home/openclaw/.openclaw/logs/
├── arb_autotrade.log           # Bot Log (print statements)
├── arb_active.flag             # Aktivierung Flag
├── MPC-USDT_trades.csv         # Trade Log für MPC Pair
├── BTC-USDT_trades.csv         # Trade Log für BTC Pair (falls aktiv)
└── exports/                     # Exportierte CSV Dateien
```

### Trade Log CSV Format
Jede Zeile = ein Trade mit vollständigen Daten von beiden Börsen.

**Direction Encoding:**
- `K->M` = Buy KuCoin (market), Sell MEXC (limit)
- `M->K` = Buy MEXC (market), Sell KuCoin (limit)

**limit_watch_status Werte:**
- `WATCHING` = Limit Order offen, wird auf Fill geprüft
- `FILLED` = Limit Order vollständig gefüllt
- `PARTIAL` = Limit Order teilweise gefüllt
- `CANCELLED` = Limit Order abgebrochen
- `EXPIRED` = Limit Order abgelaufen

---

## Limit Order Watcher

Der Bot polled regelmäßig (alle 10 Sekunden) offene Limit Orders:
1. Liest alle Trades mit `limit_watch_status = WATCHING`
2. Fragt Order-Status bei der jeweiligen Börse ab
3. Updated `limit_watch_status` basierend auf Response
4. Speichert Fill-Daten (qty_filled, price_avg, fees)

---

## Docker Deployment

### Dashboard Container
```bash
docker build -f Dockerfile.dashboard -t arbitrage-dashboard:latest .
docker run -d --name arb-dashboard -p 8501:8501 arbitrage-dashboard:latest
```

### Logs ansehen
```bash
docker logs arb-dashboard
docker logs -f arb-dashboard
```

### Stoppen
```bash
docker stop arb-dashboard && docker rm arb-dashboard
```

---

## Bot starten/stoppen (manuell)

### Start
```bash
cd /home/openclaw/.openclaw/workspace/trading/arbitrage-bot
python3 arb_autotrade.py &
```

### Aktivieren
```bash
touch /home/openclaw/.openclaw/logs/arb_active.flag
```

### Deaktivieren
```bash
rm /home/openclaw/.openclaw/logs/arb_active.flag
```

### Status prüfen
```bash
tail -f /home/openclaw/.openclaw/logs/arb_autotrade.log
```

---

## Changelog

### 2026-04-23 - Harmonized Logging eingeführt
- trade_logger.py komplett neu geschrieben
- exchange_spezifische Daten werden harmonisiert
- Ein CSV pro Pair (MPC-USDT_trades.csv)
- limit_watch_status für Fill-Tracking
- Limit Order Watcher implementiert

### Vorher (älteres Format)
- JSON-basiertes arb_trades.json
- Keine Harmonisierung
- Kein Fill-Tracking

---

*Stand: 2026-04-23*
---

## ⚠️ WICHTIG: KuCoin Teil-Fills Bug (gefixt in Commit 47d2902)

KuCoin Limit Orders können MEHRERE Teil-Fills haben:
- **API Problem:** `/api/v1/orders/{id}` gibt nur `dealSize` = letzten Fill zurück
- **Lösung:** `/api/v1/fills?orderId=X` abrufen und alle Fills summieren

**Betroffene Funktion:** `check_limit_order_fills()` in `arb_autotrade.py`

**MEXC hat das Problem NICHT:** `executedQty` ist bereits kumulativ.

**Deployment:** Nach `git pull origin main` → Bot neu starten!
