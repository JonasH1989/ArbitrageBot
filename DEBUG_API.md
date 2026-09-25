# Debug API — Arbitrage Bot

> **Erstellt:** 2026-09-24 (Jonas' Hinweis: "nimm dir die Info aus dem code in git")
> **Quelle:** `arb_autotrade.py` — Funktion `start_http_log_server()` (Zeile 342)
> **Stack:** Flask

## 🌐 Verbindung

- **URL:** `http://<server-ip>:8505` (Port von `main()` gesetzt, default 8503)
- **Server-IP:** TBD — der Bot läuft im Coolify-Container, IP vom Proxmox-Host `192.168.180.40` ist wahrscheinlich
- **Auth:** ⚠️ **KEINE** — alle Endpoints sind offen (kein Token, kein Auth-Header). Nur in trusted Netzwerken exponieren!

## 📊 Endpoint-Übersicht

### Status & Health
| Method | Endpoint | Zweck |
|---|---|---|
| GET | `/status` | Bot-Status, Memory, CPU, Threads, Uptime, Active-Flag |
| GET | `/health` | Health-Check mit Disk-Auslastung und Memory-Limit (500 MB) |
| GET | `/config/changelog` | Letzte 50 Config-Änderungen |

### Balances (Wallet-Status)
| Method | Endpoint | Zweck |
|---|---|---|
| GET | `/balances` | Aktuelle MPC + USDT Balances beider Exchanges (nutzt Cache F1!) |
| GET | `/api/kucoin/wallets` | Alle KuCoin Wallet-Typen |
| GET | `/api/kucoin/wallet` | KuCoin Trading-Wallet (default) |
| GET | `/api/kucoin/wallets/<coin>` | KuCoin Balance für spezifische Coin |

### Trades (Trade-History & Status)
| Method | Endpoint | Zweck |
|---|---|---|
| GET | `/trades/<pair>` | Trade-History für Pair (z.B. `/trades/MPC-USDT`) |
| GET | `/trades/summary/<pair>` | Aggregierte Trade-Statistiken |
| GET | `/trades/pending` | Aktuell offene/pending Trades |

### Debug (MEXC + Logs)
| Method | Endpoint | Zweck |
|---|---|---|
| GET | `/debug/mexc/order/<order_id>` | MEXC Order-Details |
| GET | `/debug/mexc/trades` | MEXC Trade-History |
| GET | `/debug/log/files` | Verfügbare Log-Files |
| GET | `/debug/log/file/<kind>` | Komplettes Log-File (kind = z.B. `arb_autotrade`) |
| GET | `/debug/log/last/<kind>` | Letzte Log-Zeile |
| GET | `/debug/log/since/<since>` | Logs seit Timestamp |
| GET | `/debug/log/level` | Aktuelles Log-Level |
| POST | `/debug/log/level/<int:new_level>` | Log-Level ändern |

### Misc
| Method | Endpoint | Zweck |
|---|---|---|
| POST | `/log` | Log-Zeile senden (POST) |
| GET | `/logs` | HTTP-Log-Buffer |
| GET | `/logs/today` | Heutige Logs |
| GET | `/logs/level/<level>` | Logs nach Level filtern |
| GET | `/logs/file` | Log-File-Inhalt |
| POST | `/clear` | Log-Buffer löschen |
| GET | `/api/files` | File-Liste |

## 🛠 Beispiel-Calls (curl)

```bash
# Server-IP setzen
SERVER="192.168.180.40:8505"  # TODO: echte IP verifizieren!

# Bot-Status (RAM, CPU, Uptime)
curl -s http://$SERVER/status | python3 -m json.tool

# Health-Check (Memory-Limit 500 MB Warnung)
curl -s http://$SERVER/health | python3 -m json.tool

# Aktuelle Balances (nutzt F1-Cache)
curl -s http://$SERVER/balances | python3 -m json.tool

# Trade-History für MPC-USDT
curl -s http://$SERVER/trades/MPC-USDT | python3 -m json.tool

# Pending Trades
curl -s http://$SERVER/trades/pending | python3 -m json.tool

# Letzte Logs (z.B. arb_autotrade.log)
curl -s http://$SERVER/debug/log/last/arb_autotrade | python3 -m json.tool

# Log-Level auf 0 (alle Logs) setzen
curl -s -X POST http://$SERVER/debug/log/level/0
```

## ⚠️ Sicherheits-Hinweis

**Die API hat KEINE Authentifizierung!** Das ist nur sicher in trusted Netzwerken.
Falls der Bot mal öffentlich exponiert wird:
- Alle Balances sind abrufbar (auch API-Keys-ableitend)
- Trade-History ist abrufbar
- Log-Level kann von außen geändert werden

→ **Empfehlung:** Reverse-Proxy mit Auth (Traefik, Nginx) oder Firewall auf das Netzwerk beschränken.

## 🔗 Cross-References

- **F1 (Wallet-Cache):** `/balances` Endpoint nutzt den Cache → weniger API-Calls
- **F3 (Fast Polling):** Bot pollt 5x/s, Debug-API sieht Live-Daten
- **Source:** `arb_autotrade.py` Zeile 342 (`start_http_log_server`)
