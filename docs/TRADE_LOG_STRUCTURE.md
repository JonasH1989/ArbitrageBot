# MPCUSDT_trades CSV Struktur Dokumentation

> **Quelle der Wahrheit:** `CLEAN_SAMPLE_DATA_MPCUSDT_trade_v1.0.xlsx` (XLSX)
> **DB-Spalten:** 43 (Col 2-44), Col 1 und Col 45-48 sind COMMENT-Felder
> **Zuletzt aktualisiert:** 2026-05-30

---

## trade_id Format

**Format:** `DDHHMMSSms` (Hex-kodiert)
- DD = Tag (01-31)
- HH = Stunde (00-23)
- MM = Minute (00-59)
- SS = Sekunde (00-59)
- ms = Millisekunden (00-99)

**Beispiel:** `0c1500372b`
- `0c` = Tag 12
- `15` = Stunde 21 (hex: 15)
- `00` = Minute 0
- `37` = Sekunde 55 (hex: 37)
- `2b` = Millisekunden 43

**Eindeutig:** Millisekunden-Präzision garantiert Einzigartigkeit
**Sortierbar:** Chronologisch aufsteigend
**Kompakt:** 10 Zeichen statt 20+ bei anderen Formaten

**Teiltrades:**
- `_ex1p1`, `_ex1p2`, `_ex1p3`... = Market (ex1) Teil-Fills
- `_ex2p1`, `_ex2p2`, `_ex2p3`... = Limit (ex2) Teil-Fills
- `_ex2sum` = Zusammenfassung der Limit-Order

---

## CSV Struktur (43 Spalten, Col 2-44)

**Trennzeichen:** `;` (Semikolon)
**Kodierung:** UTF-8
**Header-Zeile:** Row 1

| # | Spaltenname | Typ | Beschreibung |
|---|-------------|-----|--------------|
| 1 | trade_id | TEXT | Eindeutige Trade-ID (Format: DDHHMMSSms) |
| 2 | internal_ts | TEXT | Timestamp wann Bot Trade gestartet hat |
| 3 | direction | TEXT | `MXC->KCN` oder `KCN->MXC` |
| 4 | pair | TEXT | Trading Pair (z.B. `MPC-USDT`) |
| 5 | strategy | TEXT | `USDT` oder `COINS` Strategie |
| 6 | spread_pct | REAL | Spread in Prozent bei Trigger |
| 7 | ex1 | TEXT | Exchange Short ID (`MXC` oder `KCN`) |
| 8 | ex1_order_id | TEXT | Order ID von Exchange (ex1) |
| 9 | ex1_type | TEXT | Order Typ (`market` oder `limit`) |
| 10 | ex1_side | TEXT | Side (`buy` oder `sell`) |
| 11 | ex1_qty_ordered | REAL | Geplante Menge |
| 12 | ex1_qty_filled | REAL | Tatsächlich gefüllte Menge |
| 13 | ex1_price_expected | REAL | Erwarteter Preis |
| 14 | ex1_price_actual | REAL | Tatsächlicher Durchschnittspreis |
| 15 | ex1_value_usdt | REAL | Gesamtwert in USDT |
| 16 | ex1_fees | REAL | Summe aller Fees (USDT) |
| 17 | ex1_create_ts | TEXT | Exchange Order Creation Time |
| 18 | ex1_fill_ts | TEXT | Wann Fill passierte (neu!) |
| 19 | ex1_status | TEXT | Order Status |
| 20 | ex2 | TEXT | Exchange Short ID für ex2 (`KCN` oder `MXC`) |
| 21 | ex2_order_id | TEXT | Order ID von Exchange (ex2) |
| 22 | ex2_type | TEXT | Order Typ (`market` oder `limit`) |
| 23 | ex2_side | TEXT | Side (`buy` oder `sell`) |
| 24 | ex2_qty_ordered | REAL | Geplante Menge |
| 25 | ex2_qty_filled | REAL | Tatsächlich gefüllte Menge |
| 26 | ex2_price_expected | REAL | Erwarteter/Limit Preis |
| 27 | ex2_price_actual | REAL | Tatsächlicher Durchschnittspreis |
| 28 | ex2_value_usdt | REAL | Gesamtwert in USDT |
| 29 | ex2_fees | REAL | Summe aller Fees (USDT) |
| 30 | ex2_create_ts | TEXT | Exchange Order Creation Time |
| 31 | ex2_fill_ts | TEXT | Wann Fill passierte (neu!) |
| 32 | ex2_status | TEXT | Order Status |
| 33 | profit_usdt_expected | REAL | Erwarteter USDT Gewinn |
| 34 | profit_mpc_expected | REAL | Erwarteter MPC Gewinn |
| 35 | profit_usdt_actual | REAL | Tatsächlicher USDT Gewinn |
| 36 | profit_mpc_actual | REAL | Tatsächlicher MPC Gewinn |
| 37 | limit_last_check | TEXT | Timestamp letzte Status-Prüfung |
| 38 | error_code | TEXT | Fehlercode wenn Trade fehlgeschlagen |
| 39 | error_message | TEXT | Fehlermeldung wenn Trade fehlgeschlagen |
| 40 | raw_ex1_response | TEXT | Raw JSON Response von ex1 API |
| 41 | raw_ex1_response_ts | TEXT | Timestamp der ex1 Response |
| 42 | raw_ex2_response | TEXT | Raw JSON Response von ex2 API |
| 43 | raw_ex2_response_ts | TEXT | Timestamp der ex2 Response |

---

## Zeilen-Struktur pro Trade

Ein Trade besteht aus **mehreren Zeilen** (Multi-Row Pattern):

```
Row 1:        Header
Row 2:        Main Trade Zusammenfassung (berechnete Werte)
Row 3:        ex1 Teil-Fill 1 (ex1p1) - ein API Fill = eine Zeile
Row 4:        ex1 Teil-Fill 2 (ex1p2) - nur wenn 2+ Fills
Row 5:        ex2sum - Limit Order Zusammenfassung (berechnete Werte)
Row 6:        ex2 Teil-Fill 1 (ex2p1) - ein API Fill = eine Zeile
Row 7:        ex2 Teil-Fill 2 (ex2p2) - nur wenn 2+ Fills
```

**Anzahl der Zeilen variiert je nach Anzahl der Teil-Fills:**
- 1 Market Fill + 1 Limit Fill = 4 Zeilen (Row 2-5)
- 2 Market Fills + 1 Limit Fill = 5 Zeilen (Row 2-6)
- 1 Market Fill + 2 Limit Fills = 5 Zeilen (Row 2-6)
- usw.

### trade_id pro Zeile

| Zeile | trade_id Suffix | Bedeutung |
|-------|-----------------|-----------|
| Row 2 | (kein suffix) | Main Trade: `0c102f0747` |
| Row 3 | `_ex1p1` | ex1 Teil 1: `0c102f0747_ex1p1` |
| Row 4 | `_ex1p2` | ex1 Teil 2: `0c102f0747_ex1p2` |
| Row 5 | `_ex2sum` | ex2 Summe: `0c102f0747_ex2sum` |
| Row 6 | `_ex2p1` | ex2 Teil 1: `0c102f0747_ex2p1` |
| Row 7 | `_ex2p2` | ex2 Teil 2: `0c102f0747_ex2p2` |

---

## Berechnungsformeln (Row 2 + Row 5)

### Row 2 - Main Trade Zusammenfassung (ex1)

```
ex1_qty_filled  (Col 12) = SUM(ex1p_qty) aller Fills
ex1_price_actual (Col 14) = SUM(qty * price) / ex1_qty_filled
ex1_value_usdt   (Col 15) = SUM(quoteQty) aller Fills
ex1_fees         (Col 16) = SUM(commission) aller Fills
```

### Row 5 - ex2sum Zusammenfassung

```
ex2_qty_filled  (Col 25) = SUM(ex2p_qty) aller Fills
ex2_price_actual (Col 27) = SUM(qty * price) / ex2_qty_filled
ex2_value_usdt   (Col 28) = SUM(funds) aller Fills
ex2_fees         (Col 29) = SUM(fee) aller Fills

profit_usdt_expected (Col 33) = ex2_value - (ex2_qty_ordered * ex2_price_expected) - ex2_fees - ex1_fees
profit_mpc_expected (Col 34) = ex1_qty_filled - ex2_qty_ordered
profit_usdt_actual  (Col 35) = ex2_value - ex1_value - ex1_fees - ex2_fees
profit_mpc_actual   (Col 36) = ex1_qty_filled - ex2_qty_filled
```

---

## Leer-Felder (keine Daten)

Folgende Felder sind nur in bestimmten Zeilen relevant:

| Zeilen | Leere Spalten | Bedeutung |
|--------|---------------|-----------|
| Row 3-4 (ex1 Fills) | Col 20-43 | Nur ex1 Fill-Daten relevant |
| Row 6-7 (ex2 Fills) | Col 1 (nur trade_id), Col 7-19 | Nur ex2 Fill-Daten relevant |
| Row 2 (Main) | Col 20-39 | Zusammenfassung, keine Fill-Details |

---

## Status-Mapping

### MEXC Status
| API Status | CSV Status |
|------------|-----------|
| NEW | OPEN |
| FILLED | FILLED |
| PARTIALLY_FILLED | PARTIAL |
| PARTIALLY_CANCELED | PARTIAL |
| CANCELED | CANCELLED |
| REJECTED | REJECTED |

### KuCoin Status
| cancelExist | dealSize | CSV Status |
|-------------|----------|------------|
| false | > 0 | FILLED |
| false | 0 | OPEN |
| true | 0 | CANCELLED |

---

## ⚠️ WICHTIGE REGELN

### 1. createTime vs Fill Time
- **`create_ts` (Col 17/30)** = Wann die Order **erstellt** wurde, NICHT wann sie gefüllt wurde!
- **`fill_ts` (Col 18/31)** = Wann der Fill **tatsächlich passierte**
- KuCoin: `createdAt` = Order Creation
- MEXC: `time` = Order Creation

### 2. MEXC Multi-Fill Orders
MEXC Market Orders können MEHRERE Fills haben. Jeder Fill = eine eigene Zeile in CSV.
- `myTrades` API für ALLE Fills summieren
- **Nicht nur den ersten Fill verwenden!**

### 3. KuCoin Order Replacement
KuCoin kann eine Order ersetzen. Erkennung:
- Original: `cancelExist: true`, `dealSize: 0`
- Replacement: `cancelExist: false`, `dealSize > 0`
- Beide haben **gleiche `clientOid`**
- Nur Replacement-Order in CSV loggen

###4. limit_watch_status gibt es NICHT!
Dieses Feld wurde entfernt. Nur `ex1_status` (Col 19) und `ex2_status` (Col 32) existieren.

---

## Änderungshistorie

| Datum | Änderung |
|-------|----------|
| 2026-05-30 | Struktur auf 43 Spalten korrigiert (Col 18 + Col 31 = fill_ts, limit_watch_status entfernt) |
| 2026-05-30 | Erste Korrektur auf41 Spalten |
| 2026-05-29 | KuCoin Replacement Logik dokumentiert |
| 2026-05-15 | MEXC Multi-Fill Support dokumentiert |
| 2026-05-14 | Initiale Version |

---

## NOTIZEN (Kontext für Entwickler)

### trade_id Encoding
Der trade_id verwendet Hex für Stunde, Minute, Sekunde, Millisekunden:
- `15` in hex = 21 (Stunde)
- `37` in hex = 55 (Sekunde)
- `2b` in hex = 43 (Millisekunden)

### Zeitstempel in Berlin (CEST = UTC+2)
Alle internen Timestamps in Berliner Zeit. Börsen-APIs liefern UTC.

### CSV vs XLSX
- CSV: `MPCUSDT_trades_v5.csv` (aktuell noch 41 Spalten, muss auf 43 aktualisiert werden!)
- XLSX: `CLEAN_SAMPLE_DATA_MPCUSDT_trade_v1.0.xlsx` - Quelle der Wahrheit
- COMMENT-Felder (Col 1, 45-48) sind nur Hilfsfelder, NICHT Teil der DB

---

*Quelle: `/home/openclaw/.openclaw/workspace/CLEAN_SAMPLE_DATA_MPCUSDT_trade_v1.0.xlsx`
*Siehe auch: `API_CSV_MAPPING.md`, `TRADE_FLOWS.md`*