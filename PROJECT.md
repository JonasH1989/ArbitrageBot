# ArbitrageBot Projekt

## Lokaler Pfad
```
/home/openclaw/.openclaw/workspace/trading/arbitrage-bot/
```

## GitHub
- **Repo:** https://github.com/JonasH1989/ArbitrageBot.git
- **Branch:** main

## Schnellstart
```bash
cd /home/openclaw/.openclaw/workspace/trading/arbitrage-bot
git pull
```

---

## Architektur

### Trading Bot (arb_autotrade.py)
- Führt automatische Arbitrage-Trades zwischen KuCoin und MEXC aus
- Strategy: Coin-Gewinn (MPC akkumulieren)
- Aktivierung via: `touch /home/openclaw/.openclaw/logs/arb_active.flag`
- Deaktivierung via: `rm /home/openclaw/.openclaw/logs/arb_active.flag`

**Thresholds:**
- Start: 2.0% Spread
- Stop: 0.9% Spread

### Trade Logger (trade_logger.py)
- Harmonisiert Daten von verschiedenen Börsen in ein einheitliches Format
- Eine CSV-Datei pro Trading Pair (append-only)
- Multi-Row Pattern: Main Row + ex1pN Fill Rows + ex2sum Row + ex2pN Fill Rows

### Dashboard (dashboard.py)
- Streamlit-basierte Web-UI
- Zugriff: http://localhost:8501

---

## CSV Struktur (43 Spalten)

**Schema:** `docs/TRADE_LOG_STRUCTURE.md` (Quelle der Wahrheit)

| Bereich | Spalten | Felder |
|---------|---------|--------|
| Trade Info | 1-6 | trade_id, internal_ts, direction, pair, strategy, spread_pct |
| ex1 (Market) | 7-19 | ex1, order_id, type, side, qty_ordered/filled, price_expected/actual, value_usdt, fees, create_ts, **fill_ts**, status |
| ex2 (Limit) | 20-32 | ex2, order_id, type, side, qty_ordered/filled, price_expected/actual, value_usdt, fees, create_ts, **fill_ts**, status |
| Profit | 33-36 | profit_usdt/mpc_expected/actual |
| Meta | 37-39 | limit_last_check, error_code, error_message |
| Raw | 40-43 | raw_ex1/ex2_response, raw_ex1/ex2_response_ts |

### ex1/ex2 Status Mapping

**MEXC:**
| API Status | CSV Status |
|------------|-----------|
| NEW | OPEN |
| FILLED | FILLED |
| PARTIALLY_FILLED | PARTIAL |
| PARTIALLY_CANCELED | PARTIAL |
| CANCELED | CANCELLED |

**KuCoin:**
| isActive | cancelExist | dealSize | CSV Status |
|---------|------------|----------|------------|
| false | false | > 0 | FILLED |
| true | false | 0 | OPEN |
| false | true | 0 | CANCELLED |

---

## Logging Struktur

### Log Dateien
```
/home/openclaw/.openclaw/logs/
├── arb_autotrade.log           # Bot Log
├── arb_autotrade_debug.log     # Debug Log
├── arb_active.flag             # Aktivierung Flag
├── MPCUSDT_trades.csv          # Trade Log (43 Spalten!)
└── trade_logger_debug.log       # Logger Debug
```

### CSV Pfad
```python
from trade_logger import get_trade_csv_path
csv_path = get_trade_csv_path("MPC-USDT")
# → /app/logs/MPCUSDT_trades.csv
```

---

## Limit Order Watcher

Der Bot polled regelmäßig offene Limit Orders:
1. Liest Trades mit `ex2_status = OPEN`
2. Fragt Order-Status bei Börse ab
3. Updated `ex2_status` + `ex2_qty_filled`
4. Bei Fill: Berechnet profit_mpc_actual

---

## API Dokumentation

| Dokument | Beschreibung |
|----------|--------------|
| `docs/TRADE_LOG_STRUCTURE.md` | CSV Schema (43 Spalten) |
| `docs/API_CSV_MAPPING.md` | API → CSV Feld-Mapping |
| `docs/TRADE_FLOWS.md` | Alle 8 Trade-Fälle erklärt |
| `docs/EXCHANGE_NOTES.md` | Börsen-spezifische Notes |
| `docs/READONLY_API_ACCESS.md` | API Endpoints |

---

## API Keys — Zugriffsregel (Jonas, 2026-10-28)

`config/config.yaml` enthaelt echte Exchange-Keys und ist **tabu** fuer jeden, dessen
Kontext protokolliert werden kann (KI-Assistent, Chat, Logs). Verbindliche Regel:

- **Nicht direkt lesen.** Kein `read`, `cat`, `grep`, `sed`, kein Ausgeben von Datei-Inhalten.
- **Ausschliesslich ueber ENV.** `KUCOIN_KEY`, `KUCOIN_SECRET`, `KUCOIN_PASSPHRASE`,
  `MEXC_KEY`, `MEXC_SECRET`.
- **Wer liest, ist der Container.** `scripts/load_keys_to_env.py` laeuft als Entry-Point
  in `arbitrage-bot` und `arbitrage-dashboard`. Es liest `config.yaml`, legt die Werte in
  die ENV des Kindprozesses und startet per `exec()` den eigentlichen Prozess.
- **Erlaubte Ausgabe nur maskiert:** gesetzt/nicht gesetzt, Laenge, Quelle. Kein Klartext,
  kein Prefix/Suffix, kein Base64. <!-- project: path:/home/openclaw/.openclaw/workspace -->
- **Vorrang:** ENV aus `docker-compose`/`env_file` schlaegt `config.yaml`; die Datei fuellt
  nur leere Werte auf.

Nutzung ausserhalb der Container (z.B. lokaler Test):
```bash
python3 scripts/load_keys_to_env.py python3 arb_autotrade.py
```

---

## Docker Deployment

### Bauen
```bash
docker build -t arbitrage-bot:latest .
```

### Logs ansehen
```bash
docker logs <container>
docker logs -f <container>
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

### 2026-05-30 - 43-Spalten Format (dc236a2)
- `limit_watch_status` ENTFERNT → ersetzt durch `ex2_status`
- `ex1_fill_ts` (Col 18) und `ex2_fill_ts` (Col 31) HINZUFÜGT
- Status-Mapping vereinheitlicht
- `docs/TRADE_LOG_STRUCTURE.md` aktualisiert

### 2026-05-15 - MEXC Multi-Fill Support
- myTrades API für alle Fills summiert
- KuCoin Teil-Fills Bug gefixt

### 2026-04-23 - Harmonized Logging eingeführt
- trade_logger.py komplett neu geschrieben

---

## Wichtige Links

- **Bot Server:** http://192.168.113.14:18888 (Dashboard)
- **Bot API:** http://192.168.113.14:18888/api

---

*Stand: 2026-05-30*

## Betrieb: Coolify ist die einzige Instanz

Der Bot laeuft auf CoolifyDev als Coolify-Application, nicht per Hand:

| | |
|---|---|
| Projekt | Trading (`s7zjinhdkfxocaqaxwodr1py`) |
| Environment | production (`rhmph7rpop3phedzg3wm5uh0`) |
| Application | `6vqgknob3trgvpxiulcqtymu` (Name `arbitrage-bot`) |
| Compose | `/docker-compose.coolify.yaml` (absolute Pfade, Bind-IP `0.0.0.0`) |
| Bot-API | http://192.168.13.57:18888 |
| Dashboard | http://192.168.13.57:8501 und :8502 |
| Daten | `/opt/arb/ArbitrageBot/config` + `/logs` (Bind-Mount) |

**Regeln:**
- Container nur ueber Coolify erstellen, deployen, neustarten, Logs lesen.
- Kein manuelles `docker compose up` / `docker run` / systemd-Unit / cron-Start auf einem Host.
- `docker-compose.yaml` (Standard-Variante, Default-Bind-IP `192.168.113.14`) ist NICHT der
  Betriebspfad auf Dev - sie dient dem Prod-Host. Auf Dev nutzt Coolify die `.coolify.yaml`.
- `config.yaml` wird ausschliesslich im Container ueber `scripts/load_keys_to_env.py` gelesen.
