# MPC Arbitrage Bot

**Live Arbitrage Trading** zwischen KuCoin und MEXC für MPC-USDT

## Quick Start

```bash
# Projekt-Verzeichnis
cd /home/openclaw/.openclaw/workspace/trading/arbitrage-bot

# Bot aktivieren
touch /home/openclaw/.openclaw/logs/arb_active.flag

# Logs beobachten
tail -f /home/openclaw/.openclaw/logs/arb_autotrade.log
```

## Aktueller Stand (Phase 3 ✅)

- **Live Trading** aktiv mit automatischer Arbitrage
- **Strategy:** Coin-Gewinn (MPC akkumulieren)
- **Thresholds:** Start 2.0%, Stop 0.9%
- **Trade Logging:** 43-Spalten CSV (`docs/TRADE_LOG_STRUCTURE.md`)

## Projekt-Dokumentation

| Dokument | Beschreibung |
|----------|--------------|
| `PROJECT.md` | **Hauptdokumentation** - Architektur, Deployment, Status |
| `docs/TRADE_LOG_STRUCTURE.md` | CSV Schema (43 Spalten) |
| `docs/API_CSV_MAPPING.md` | API → CSV Feld-Mapping |
| `docs/TRADE_FLOWS.md` | Alle 8 Trade-Fälle erklärt |
| `docs/READONLY_API_ACCESS.md` | API Endpoints |

## Architektur

```
┌──────────────────────────────────────────────────────┐
│                    Arbitrage Bot                      │
├──────────────────────────────────────────────────────┤
│  KuCoin ←→ MEXC Arbitrage                           │
│  • Market Order (ex1) auf einer Börse                │
│  • Limit Order (ex2) auf anderer Börse               │
│  • Multi-Row Trade Logging (43 Spalten)             │
│  • Limit Order Watcher (pollen bis Fill)             │
│                                                       │
│  Dashboard: http://192.168.113.14:8501              │
│  API:      http://192.168.113.14:18888               │
└──────────────────────────────────────────────────────┘
```

## Trade CSV Struktur

**Datei:** `MPCUSDT_trades.csv` (43 Spalten, Semikolon-getrennt)

```
Row 1:        Header
Row 2:        Main Trade Zusammenfassung
Row 3-N:      ex1 Fill Zeilen (_ex1p1, _ex1p2, ...)
Row N+1:      ex2sum Zusammenfassung
Row N+2-M:    ex2 Fill Zeilen (_ex2p1, _ex2p2, ...)
```

**Wichtigste Felder:**
- `ex1_status` (Col 19): OPEN, FILLED, PARTIAL
- `ex2_status` (Col 32): OPEN, FILLED, PARTIAL, CANCELLED
- `profit_mpc_actual` (Col 36): Tatsächlicher MPC Gewinn/Verlust

## CSV Format (43 Spalten)

| Bereich | Spalten | Beschreibung |
|---------|---------|--------------|
| Trade Info | 1-6 | trade_id, internal_ts, direction, pair, strategy, spread_pct |
| ex1 (Market) | 7-19 | Order + Status + **ex1_fill_ts** |
| ex2 (Limit) | 20-32 | Order + Status + **ex2_fill_ts** |
| Profit | 33-36 | USDT/MPC expected/actual |
| Meta | 37-43 | Fehler + Raw Responses |

**NEU (2026-05-30):**
- `ex1_fill_ts` (Col 18) - Wann Market Fill passierte
- `ex2_fill_ts` (Col 31) - Wann Limit Fill passierte
- `limit_watch_status` ENTFERNT → jetzt `ex2_status`

## API Keys

| Börse | Key Typ | verwendet für |
|-------|---------|--------------|
| MEXC | Trading Key | myTrades, Order Status |
| KuCoin | Trading Key | Orders, Fills |

**Siehe:** `docs/READONLY_API_ACCESS.md`

## Deployment (Coolify)

1. Git push zu `JonasH1989/ArbitrageBot`
2. Coolify deployed automatisch
3. Container startet mit Docker Compose

## Troubleshooting

```bash
# Bot läuft?
ps aux | grep arb_autotrade

# Logs?
tail -100 /home/openclaw/.openclaw/logs/arb_autotrade.log

# CSV prüfen?
head -1 /home/openclaw/.openclaw/logs/MPCUSDT_trades.csv
wc -l /home/openclaw/.openclaw/logs/MPCUSDT_trades.csv
```

## Changelog

| Datum | Änderung |
|-------|----------|
| 2026-05-30 | 43-Spalten Format: ex1_fill_ts, ex2_fill_ts, kein limit_watch_status |
| 2026-05-15 | MEXC Multi-Fill Support |
| 2026-04-23 | Harmonized Logging eingeführt |

---

*Siehe auch: `PROJECT.md` für detaillierte Dokumentation*