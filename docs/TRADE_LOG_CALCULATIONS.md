# Trade-Log Berechnungen — Pro Zeile & Spalte

> **Stand:** 2026-10-19 (Counter-Fix + Doku)
> **Zweck:** Vollständige Referenz wie jede Zeile und Spalte des Trade-Logs
> berechnet wird und woher die Daten kommen.
> **Siehe auch:**
> - `docs/TRADE_LOG_STRUCTURE.md` — Spalten-Definitionen (43 Spalten, was wo steht)
> - `docs/LOGGER_IMPROVEMENTS.md` — Bekannte Probleme + Priorisierte Fixes
> - `docs/API_CSV_MAPPING.md` — Welche API-Felder in welche CSV-Spalten fließen
> - `docs/TRADE_FLOWS.md` — Trade-Flow-Logik pro Strategie (USDT/COINS)
> - `docs/EXCHANGE_NOTES.md` — Exchange-spezifische Besonderheiten

---

## Multi-Row-Pattern (Überblick)

Ein Trade erzeugt **4-7 CSV-Zeilen** (Multi-Row-Pattern). Dies ist KEIN Fehler,
sondern gewollt — die Zeilen erlauben es, jeden Fill einzeln zu tracken UND
gleichzeitig aggregierte Summen zu haben.

```
Zeile 1 (Header — nur einmal pro Datei)

Zeile 2: Main Trade         → trade_id OHNE Suffix (z.B. "0c102f0747")
Zeile 3: ex1p1              → "0c102f0747_ex1p1"   (Market Fill #1)
Zeile 4: ex1p2              → "0c102f0747_ex1p2"   (Market Fill #2, nur wenn 2+ Fills)
…
Zeile N: ex2sum             → "0c102f0747_ex2sum"  (Limit-Order Summary + Profit)
Zeile N+1: ex2p1            → "0c102f0747_ex2p1"   (Limit Fill #1)
Zeile N+2: ex2p2            → "0c102f0747_ex2p2"   (Limit Fill #2, nur wenn 2+ Fills)
…
```

**Anzahl Zeilen pro Trade:**
| Konstellation | Zeilen pro Trade |
|---|---|
| 1 Market Fill + 1 Limit Fill | 4 (Main + ex1p1 + ex2sum + ex2p1) |
| 2 Market Fills + 1 Limit Fill | 5 (+ ex1p2) |
| 1 Market Fill + 2 Limit Fills | 5 (+ ex2p2) |
| 2 Market Fills + 2 Limit Fills | 6 (+ ex1p2 + ex2p2) |
| 3+ Fills | bis zu 10+ (in der Praxis sehr selten) |

**trade_id Suffix-Logik:**
| Zeile | trade_id Suffix | Bedeutung |
|---|---|---|
| Main | (kein Suffix) | Trade-Zusammenfassung ex1 (Market) |
| ex1p1, ex1p2, ... | `_ex1pN` | Market-Order Teil-Fill N |
| ex2sum | `_ex2sum` | Limit-Order Zusammenfassung + Profit |
| ex2p1, ex2p2, ... | `_ex2pN` | Limit-Order Teil-Fill N |

---

## Pro Zeile: Berechnung & Quelle

### Zeile 2 — Main Trade (Market-Zusammenfassung)

**Zweck:** Übersicht über den Market-Trade (ex1), Pair-Info, Strategie, Spread.

**Felder und Berechnung:**

| Spalte | Quelle | Berechnung / Format |
|---|---|---|
| `trade_id` | `generate_trade_id()` | Format `DDHHMMSSms` hex (z.B. `0c102f0747` = Tag 12, 21:02:55.43) |
| `internal_ts` | `datetime.now().isoformat()` | Wann Bot Trade gestartet hat (nach Balance-Check) |
| `direction` | Caller | `MXC->KCN` oder `KCN->MXC` |
| `pair` | `TRADING_PAIR` config | z.B. `MPC-USDT` |
| `strategy` | Caller | `USDT` oder `COINS` |
| `spread_pct` | Caller | Spread in % bei Trigger, 3 Nachkommastellen |
| `ex1` | `get_exchange_short_id(ex1_data.exchange)` | `MXC` oder `KCN` |
| `ex1_order_id` | `ex1_data.order_id` | Order-ID der Market-Order |
| `ex1_type` | hardcoded | `market` |
| `ex1_side` | `ex1_data.side` | `buy` (M→K) oder `sell` (K→M) |
| `ex1_qty_ordered` | `ex1_data.qty_ordered` | Geplante Menge |
| `ex1_qty_filled` | **Berechnet** aus `ex1_partial_fills` | `SUM(qty_filled)` aller Fills (Fallback: ex1_data.qty_filled) |
| `ex1_price_expected` | Caller | `market_price_expected` (vor Trade) |
| `ex1_price_actual` | **Berechnet** | `ex1_value_usdt / ex1_qty_filled` (gewichteter Durchschnitt) |
| `ex1_value_usdt` | **Berechnet** aus `ex1_partial_fills` | `SUM(value_usdt)` aller Fills |
| `ex1_fees` | **Berechnet** aus `ex1_partial_fills` | `SUM(fees)` aller Fills |
| `ex1_create_ts` | `ex1_data.create_ts` (Unix ms) | konvertiert zu `YYYY-MM-DD HH:MM:SS.mmm` |
| `ex1_status` | **Berechnet** | `FILLED` wenn `qty_filled >= qty_ordered`, sonst `PARTIAL` |
| `error_code` | Caller (nur bei Fehler) | z.B. `API_ERROR`, `QTY_ZERO` |
| `error_message` | Caller (nur bei Fehler) | Lesbare Fehlermeldung |
| `raw_ex1_response` | `json.dumps(ex1_data.raw_response)` | Komplette Original-API-Response |
| `raw_ex1_response_ts` | `datetime.now().isoformat()` | Wann Response eingelesen wurde |

**Was in der Main Row LEER ist (wird in anderen Zeilen befüllt):**
- `ex2*` Spalten (Limit-Order-Daten) — stehen in `ex2sum` + `ex2p*`
- `ex1_fill_ts` (Fill-Zeitpunkt) — steht in `ex1p*` Rows
- `profit_*` — steht in `ex2sum` Row
- `limit_last_check`, `raw_ex2_response` — stehen in `ex2sum` Row

---

### Zeile 3+ — ex1p1, ex1p2, … (Market-Order Teil-Fills)

**Zweck:** Pro API-Fill eine Zeile, damit Multi-Fill-Market-Orders exakt abgebildet werden.

**Wann geschrieben:** Nur wenn Market-Order >1 Fill hat (kommt bei MEXC bei großen Orders vor).

**Felder und Berechnung (pro Fill):**

| Spalte | Quelle | Berechnung / Format |
|---|---|---|
| `trade_id` | Konstante | `f"{trade_id}_ex1p{idx}"` (idx = 1, 2, 3, …) |
| `ex1_qty_filled` | Fill-Daten | `fill.qty_filled` |
| `ex1_price_actual` | Fill-Daten | `fill.price_actual` |
| `ex1_value_usdt` | Fill-Daten | `fill.value_usdt` (= MEXC `quoteQty` aus myTrades) |
| `ex1_fees` | Fill-Daten | `fill.fees` |
| `ex1_create_ts` | Fill-Daten | Unix ms → `YYYY-MM-DD HH:MM:SS.mmm` |
| `ex1_fill_ts` | Fill-Daten | Unix ms → `YYYY-MM-DD HH:MM:SS.mmm` (Zeitpunkt des Fills) |
| `ex1_status` | hardcoded | `FILLED` |

**Alle anderen Spalten LEER** (Trade-Info, ex2-Info, Profit, Errors, etc.).

**Fill-Daten-Quellen:**
- MEXC: `GET /api/v3/myTrades?symbol={pair}` → `quoteQty`, `qty`, `commission`, `time`
- KuCoin: `GET /api/v1/fills?orderId={orderId}` → `funds`, `size`, `fee`, `createdAt`

---

### Zeile N — ex2sum (Limit-Order Zusammenfassung + Profit)

**Zweck:** Aggregierte Limit-Order-Daten + Profit-Berechnung. **HIER** steht der
realisierte Gewinn (`profit_usdt_actual`).

**Felder und Berechnung:**

| Spalte | Quelle | Berechnung / Format |
|---|---|---|
| `trade_id` | Konstante | `f"{trade_id}_ex2sum"` |
| `ex2` | `get_exchange_short_id(ex2_data.exchange)` | `KCN` oder `MXC` |
| `ex2_order_id` | `ex2_data.order_id` | Order-ID der Limit-Order |
| `ex2_type` | hardcoded | `limit` |
| `ex2_side` | `ex2_data.side` | `sell` (M→K) oder `buy` (K→M) |
| `ex2_qty_ordered` | `ex2_data.qty_ordered` | Geplante Menge |
| `ex2_qty_filled` | **Berechnet** | `SUM(qty_filled)` aus `ex2_partial_fills` (Fallback: ex2_data.qty_filled) |
| `ex2_price_expected` | Caller | `limit_price_expected` (vor Trade) |
| `ex2_price_actual` | **Berechnet** | `ex2_value_usdt / ex2_qty_filled` (gewichteter Durchschnitt) |
| `ex2_value_usdt` | **Berechnet** | `SUM(value_usdt)` aus `ex2_partial_fills` (KuCoin `funds`) |
| `ex2_fees` | **Berechnet** | `SUM(fees)` aus `ex2_partial_fills` |
| `ex2_create_ts` | `ex2_data.create_ts` (Unix ms) | konvertiert zu `YYYY-MM-DD HH:MM:SS.mmm` |
| `ex2_status` | **Berechnet** | `FILLED` wenn `qty_filled >= qty_ordered`, sonst `OPEN` |
| **`profit_usdt_expected`** | Caller | Erwarteter USDT-Gewinn (vor Trade) |
| **`profit_mpc_expected`** | Caller | Erwarteter MPC-Gewinn (vor Trade) |
| **`profit_usdt_actual`** | **Berechnet** | `ex2_value_usdt - ex1_value_usdt - ex1_fees - ex2_fees` |
| **`profit_mpc_actual`** | **Berechnet** | `ex1_qty_filled - ex2_qty_filled` |
| `limit_last_check` | `datetime.now().isoformat()` | Letzte Status-Prüfung (vom Background-Service aktualisiert) |
| `raw_ex2_response` | `json.dumps(ex2_data.raw_response)` | Original-API-Response |
| `raw_ex2_response_ts` | `datetime.now().isoformat()` | Wann Response eingelesen wurde |

**Profit-Update durch Background-Service:**
- `profit_usdt_actual` und `profit_mpc_actual` werden **initial beim Trade-Start** berechnet (Limit noch nicht gefüllt → Wert evtl. negativ).
- Sobald der Background-Service (`trade_logger_service.py`) den Fill pollt, werden die Felder **aktualisiert** auf den realisierten Wert.
- `update_limit_watch()` schreibt die neuen Werte in die ex2sum-Row.

**Warum `ex2_value_usdt` nur HIER befüllt ist (nicht in Main Row):**
Damit das `total_profit_usdt()`-Helper im Dashboard einfach `SUM(profit_usdt_actual)`
aus _ex2sum-Rows rechnen kann, ohne Doppelzählung in ex2p*-Rows zu riskieren.

---

### Zeile N+1+ — ex2p1, ex2p2, … (Limit-Order Teil-Fills)

**Zweck:** Pro API-Fill eine Zeile, damit Multi-Fill-Limit-Orders exakt abgebildet werden.

**Wann geschrieben:** Nur wenn Limit-Order >1 Fill hat (kommt vor, wenn Order über mehrere Preislevel gefüllt wird).

**Felder und Berechnung (pro Fill):**

| Spalte | Quelle | Berechnung / Format |
|---|---|---|
| `trade_id` | Konstante | `f"{trade_id}_ex2p{idx}"` (idx = 1, 2, 3, …) |
| `ex2_qty_ordered` | Fill-Daten | `fill.qty_ordered` (oder `ex2_qty_ordered` als Fallback) |
| `ex2_qty_filled` | Fill-Daten | `fill.qty_filled` |
| `ex2_price_actual` | Fill-Daten | `fill.price_actual` |
| `ex2_value_usdt` | Fill-Daten | `fill.value_usdt` (KuCoin `funds`) |
| `ex2_fees` | Fill-Daten | `fill.fees` |
| `ex2_create_ts` | Fill-Daten | Unix ms → `YYYY-MM-DD HH:MM:SS.mmm` |
| `ex2_fill_ts` | Fill-Daten | Unix ms → `YYYY-MM-DD HH:MM:SS.mmm` (Zeitpunkt des Fills) |
| `ex2_status` | hardcoded | `FILLED` |

**Alle anderen Spalten LEER.**

**Wichtig für Counter:**
- Jede ex2p-Row zählt **nicht** als eigener Trade
- Jede ex2p-Row hat `ex2_value_usdt` → würde bei naivem `sum()` doppelt gezählt
- → **Immer Suffix-Filter verwenden** (siehe `is_main_trade_row()` / `is_ex2sum_row()`)

---

## Pro Spalte: Berechnung & Quelle (Übersicht)

### Identifikation

| Spalte | Typ | Quelle |
|---|---|---|
| `trade_id` (Col 1) | TEXT | `generate_trade_id()` — Format `DDHHMMSSms` hex (z.B. `0c102f0747`) |
| `internal_ts` (Col 2) | TEXT | `datetime.now().isoformat()` beim Trade-Start |

### Trade-Info

| Spalte | Typ | Zeile | Quelle / Berechnung |
|---|---|---|---|
| `direction` (Col 3) | TEXT | Main | `MXC->KCN` oder `KCN->MXC` (vom Caller) |
| `pair` (Col 4) | TEXT | Main | `TRADING_PAIR` aus Config |
| `strategy` (Col 5) | TEXT | Main | `USDT` oder `COINS` (vom Caller) |
| `spread_pct` (Col 6) | REAL | Main | Spread in % bei Trigger |

### ex1 (Market) — Cols 7-19

| Spalte | Typ | Zeile | Quelle |
|---|---|---|---|
| `ex1` (Col 7) | TEXT | Main | `MXC` oder `KCN` |
| `ex1_order_id` (Col 8) | TEXT | Main | API Response |
| `ex1_type` (Col 9) | TEXT | Main | hardcoded `market` |
| `ex1_side` (Col 10) | TEXT | Main | `buy` oder `sell` |
| `ex1_qty_ordered` (Col 11) | REAL | Main | API Response |
| `ex1_qty_filled` (Col 12) | REAL | Main + ex1p* | **SUM** in Main, **einzeln** in ex1p* |
| `ex1_price_expected` (Col 13) | REAL | Main | Vor Trade gespeichert |
| `ex1_price_actual` (Col 14) | REAL | Main + ex1p* | **Gewichteter Durchschnitt** in Main, einzeln in ex1p* |
| `ex1_value_usdt` (Col 15) | REAL | Main + ex1p* | **SUM** in Main (= `quoteQty` für MEXC), einzeln in ex1p* |
| `ex1_fees` (Col 16) | REAL | Main + ex1p* | **SUM** (`commission` bei MEXC, `fee` bei KuCoin) |
| `ex1_create_ts` (Col 17) | TEXT | Main + ex1p* | Unix ms → lesbar, `time` (MEXC) / `createdAt` (KuCoin) |
| `ex1_fill_ts` (Col 18) | TEXT | ex1p* | Unix ms → lesbar, Fill-Zeitpunkt |
| `ex1_status` (Col 19) | TEXT | Main + ex1p* | `FILLED` / `PARTIAL` / `OPEN` / `REJECTED` |

### ex2 (Limit) — Cols 20-32

| Spalte | Typ | Zeile | Quelle |
|---|---|---|---|
| `ex2` (Col 20) | TEXT | ex2sum + ex2p* | `KCN` oder `MXC` |
| `ex2_order_id` (Col 21) | TEXT | ex2sum + ex2p* | API Response |
| `ex2_type` (Col 22) | TEXT | ex2sum + ex2p* | hardcoded `limit` |
| `ex2_side` (Col 23) | TEXT | ex2sum + ex2p* | `buy` oder `sell` |
| `ex2_qty_ordered` (Col 24) | REAL | ex2sum + ex2p* | API Response |
| `ex2_qty_filled` (Col 25) | REAL | ex2sum + ex2p* | **SUM** in ex2sum, einzeln in ex2p* |
| `ex2_price_expected` (Col 26) | REAL | ex2sum | Vor Trade gespeichert |
| `ex2_price_actual` (Col 27) | REAL | ex2sum + ex2p* | **Gewichteter Durchschnitt** in ex2sum, einzeln in ex2p* |
| `ex2_value_usdt` (Col 28) | REAL | ex2sum + ex2p* | **SUM** (`dealFunds` KuCoin Order / `funds` KuCoin Fills) |
| `ex2_fees` (Col 29) | REAL | ex2sum + ex2p* | **SUM** (`fee`) |
| `ex2_create_ts` (Col 30) | TEXT | ex2sum + ex2p* | Unix ms → lesbar, `createdAt` |
| `ex2_fill_ts` (Col 31) | TEXT | ex2p* | Unix ms → lesbar, Fill-Zeitpunkt |
| `ex2_status` (Col 32) | TEXT | ex2sum + ex2p* | `OPEN` / `FILLED` / `PARTIAL` / `CANCELLED` |

### Profit — Cols 33-36

| Spalte | Typ | Zeile | Berechnung |
|---|---|---|---|
| `profit_usdt_expected` (Col 33) | REAL | ex2sum | Vom Caller berechnet (vor Trade) |
| `profit_mpc_expected` (Col 34) | REAL | ex2sum | Vom Caller berechnet (vor Trade) |
| **`profit_usdt_actual`** (Col 35) | REAL | ex2sum | `ex2_value_usdt - ex1_value_usdt - ex1_fees - ex2_fees` |
| **`profit_mpc_actual`** (Col 36) | REAL | ex2sum | `ex1_qty_filled - ex2_qty_filled` |

### Meta — Cols 37-43

| Spalte | Typ | Zeile | Quelle |
|---|---|---|---|
| `limit_last_check` (Col 37) | TEXT | ex2sum | Timestamp letzte Status-Prüfung (Background-Service) |
| `error_code` (Col 38) | TEXT | Main | z.B. `API_ERROR`, `QTY_ZERO` |
| `error_message` (Col 39) | TEXT | Main | Lesbare Fehlermeldung |
| `raw_ex1_response` (Col 40) | TEXT | Main | Komplette Original-API-Response als JSON |
| `raw_ex1_response_ts` (Col 41) | TEXT | Main | Timestamp der Response |
| `raw_ex2_response` (Col 42) | TEXT | ex2sum | Komplette Original-API-Response als JSON |
| `raw_ex2_response_ts` (Col 43) | TEXT | ex2sum | Timestamp der Response |

---

## Beispiel: 1 Trade mit allen Row-Typen

**Szenario:** M→K Trade (MEXC kaufen, KuCoin verkaufen), 2 Market-Fills + 1 Limit-Fill.

- trade_id: 0c102f0747
- direction: MXC->KCN
- strategy: USDT
- spread_pct: 1.85
- ex1 (Market, MEXC): 183.0 MPC gekauft in 2 Fills
- ex2 (Limit, KuCoin): 183.0 MPC verkauft in 1 Fill

**CSV-Zeilen:**

| trade_id | direction | ex1_qty_filled | ex1_value_usdt | ex2_qty_filled | ex2_value_usdt | profit_usdt_actual |
|---|---|---|---|---|---|---|
| 0c102f0747 | MXC->KCN | 183.0 | 3.21165 |  |  |  |
| 0c102f0747_ex1p1 |  | 90.0 | 1.58000 |  |  |  |
| 0c102f0747_ex1p2 |  | 93.0 | 1.63165 |  |  |  |
| 0c102f0747_ex2sum |  |  |  | 183.0 | 3.321084 | 0.097865 |
| 0c102f0747_ex2p1 |  |  |  | 183.0 | 3.321084 |  |

**Berechnungen:**

- ex1_qty_filled (Main) = 90.0 + 93.0 = 183.0
- ex1_value_usdt (Main) = 1.58000 + 1.63165 = 3.21165
- ex1_fees (Main) = 0.000790 + 0.000816 = 0.001606
- ex1_price_actual (Main) = 3.21165 / 183.0 = 0.01755
- ex2_qty_filled (ex2sum) = 183.0 (einziger Fill)
- ex2_value_usdt (ex2sum) = 3.321084
- ex2_fees (ex2sum) = 0.009963
- ex2_price_actual (ex2sum) = 3.321084 / 183.0 = 0.018148
- profit_usdt_actual = 3.321084 - 3.21165 - 0.001606 - 0.009963 = 0.097865
- profit_mpc_actual = 183.0 - 183.0 = 0.0

---

## Counter-Bug Historie (warum diese Doku entsteht)

**Symptom (2026-10-19, Jonas):** Dashboard zeigt zu viele Trades und falsche Gewinne.

**Root Cause:**
1. `dashboard.py` zählte `len(trades)` (= CSV-Zeilen) statt unique trade_ids → 4-7× zu viele Trades
2. `dashboard.py` summierte `r['net']` über ALLE Zeilen → ex2_value_usdt wurde in ex2sum + ex2p* mehrfach gezählt → massiv überhöhte Gewinne
3. `get_trades(limit=1000)` lud nur die 1000 neuesten Zeilen → bei 6 Zeilen/Trade nur ~166 echte Trades sichtbar
4. `t.get('limit_watch_status', 'UNKNOWN')` las eine Spalte die es nicht gibt → Status immer `UNKNOWN`

**Fix (2026-10-19):**
- Neue Helper in `trade_logger.py`: `count_main_trades()` + `total_profit_usdt()` — iterieren über ALLE Zeilen (kein 1000-Limit), deduplizieren korrekt
- Neue Helper in `dashboard.py`: `is_main_trade_row()` + `is_ex2sum_row()` — Suffix-Filter für Detail-View
- Tile Overview nutzt jetzt `count_main_trades()` + `total_profit_usdt()`
- Detail-View filtert `rows` mit `is_main_trade_row()` für filled/winning Counts und nutzt ex2sum-Rows für Profit
- `limit_watch_status` → `ex2_status` (korrekte Spalte gemäß TRADE_LOG_STRUCTURE.md)
- Tests: `tests/test_dashboard_counter.py` verifiziert die Filter-Logik

---

## Wartung

**Bei neuen Spalten:** Diese Doku erweitern, sowie `TRADE_LOG_STRUCTURE.md` und `API_CSV_MAPPING.md`.

**Bei neuen Zeilen-Typen:** Suffix in `TRADE_ROW_SUFFIXES` (in `trade_logger.py`) ergänzen.

**Bei Logik-Änderungen:** Tests in `tests/test_dashboard_counter.py` aktualisieren.

---

*Erstellt: 2026-10-19 (Usta, auf Jonas' Anweisung)*
*Quelle: trade_logger.py Z. 442-700 (log_trade-Funktion), docs/TRADE_LOG_STRUCTURE.md, docs/API_CSV_MAPPING.md*
