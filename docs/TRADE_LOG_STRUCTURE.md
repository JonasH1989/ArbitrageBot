# MPCUSDT_trades CSV Struktur Dokumentation

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

## Übersicht

Die Trade Log CSV hat **41 Spalten** und besteht pro Trade aus mindestens 4 Zeilen, jedoch abhängig von Teiltrades auch aus mehr Zeilen:
- Row 2: Main Trade (Market Order Zusammenfassung) *
- Row 3: ex1 Teil-Fill 1 (ex1p1) *
- Row 4: ex1 Teil-Fill 2 (ex1p2) - nur wenn mehrere Fills
- Row 5: ex2sum (Limit Order Zusammenfassung) *
- Row 6: ex2p1 (Limit Order Teil 1) *
- Row 7: ex2p2 (Limit Order Teil 2) - nur wenn mehrere Teil-Fills

* = Diese Zeile existiert immer, da jeder Trade aus mindestens einem Teiltrade besteht.

---

## ZEILEN-STRUKTUR PRO TRADE

Ein Trade besteht aus:
- **Row 2:** Main Trade (Zusammenfassung)
- **Row 3-N:** ex1p1, ex1p2, ex1p3... (ein Row pro Market Fill)
- **Row N+1:** ex2sum (Limit Order Zusammenfassung)
- **Row N+2 bis M:** ex2p1, ex2p2, ex2p3... (ein Row pro Limit Fill)

**Anzahl der Zeilen variiert** je nach Anzahl der Teil-Fills:
- 1 Market Fill → nur ex1p1
- 2 Market Fills → ex1p1 + ex1p2
- 3 Market Fills → ex1p1 + ex1p2 + ex1p3 usw.

Gleiches gilt für ex2 (Limit Order Teil-Fills).

| Spalte | Name | Quelle | Fallback |
|--------|------|--------|----------|
| 1 | trade_id | Main ID: `0c102f0747` | - |
| 2 | internal_ts | Wann Bot Trade gestartet hat | - |
| 3 | direction | `MXC->KCN` oder `KCN->MXC` | - |
| 4 | pair | `MPC-USDT` (aus config) | - |
| 5 | strategy | `USDT` oder `COINS` | - |
| 6 | spread_pct | Spread % bei Trigger | - |
| 7 | ex1 | Exchange Short ID (MXC/KCN) | - |
| 8 | ex1_order_id | Order ID von Exchange | - |
| 9 | ex1_type | `market` (immer) | - |
| 10 | ex1_side | `buy` oder `sell` | - |
| 11 | ex1_qty_ordered | 85 (geplant) | - |
| 12 | ex1_qty_filled | **Formel:** `=L4+L3` | Summe der Teil-Fills |
| 13 | ex1_price_expected | Erwarteter Preis | - |
| 14 | ex1_price_actual | **Formel:** `=(L3*N3+L4*N4)/L2` | Avg Preis aller Fills |
| 15 | ex1_value_usdt | **Formel:** `=O3+O4` | Summe aller Fill-Werte |
| 16 | ex1_fees | **Formel:** `=P3+P4` | Summe aller Fill-Fees |
| 17 | ex1_create_ts | Exchange createTime | API Call |
| 18 | ex1_status | `FILLED` (immer nach Fill) | - |
| 19-41 | (leer/verschieden) | - | - |

### Row 3 (ex1p1 - Erster Market Fill)

| Spalte | Name | Quelle | Fallback |
|--------|------|--------|----------|
| 1 | trade_id | `0c102f0747_ex1p1` | - |
| 12 | ex1_qty_filled | 79.75 MPC | API Call |
| 14 | ex1_price_actual | 0.01659 | API Call |
| 15 | ex1_value_usdt | 1.3230525 | `qty * price` |
| 16 | ex1_fees | 0.00066152625 | API Call |
| 17 | ex1_create_ts | `05-12 16:47:06` | API Call (createTime) |
| 18 | ex1_status | `FILLED` | API Call |
| 19 | ex2 | `KCN` (Exchange für Fill) | - |

### Row 4 (ex1p2 - Zweiter Market Fill)

| Spalte | Name | Quelle | Fallback |
|--------|------|--------|----------|
| 1 | trade_id | `0c102f0747_ex1p2` | - |
| 12 | ex1_qty_filled | 5.25 MPC | API Call |
| 14 | ex1_price_actual | 0.01662 | API Call |
| 15 | ex1_value_usdt | 0.087255 | `qty * price` |
| 16 | ex1_fees | 4.36275e-05 | API Call |
| 17 | ex1_create_ts | `05-12 16:47:06` | API Call |
| 18 | ex1_status | `FILLED` | API Call |
| 19 | ex2 | `KCN` | - |

### Row 5 (ex2sum - Limit Order Zusammenfassung)

| Spalte | Name | Quelle | Formel |
|--------|------|--------|--------|
| 1 | trade_id | `0c102f0747_ex2sum` | - |
| 21 | ex2_type | `limit` | - |
| 22 | ex2_side | `sell` | - |
| 23 | ex2_qty_ordered | 84 | Bot geplant |
| 24 | ex2_qty_filled | `=X6+X7` | Summe der Teil-Fills |
| 25 | ex2_price_expected | 0.0169 | Bot Limit Preis |
| 26 | ex2_price_actual | `=(Z6*X6+Z7*X7)/X5` | Avg Preis |
| 27 | ex2_value_usdt | `=AA7+AA6` | Summe Fill-Werte |
| 28 | ex2_fees | `=AB7+AB6` | Summe Fill-Fees |
| 30 | ex2_status | `FILLED` (wenn alle Teil-Fills FILLED) | - |
| 31 | profit_usdt_expected | `=AA5 - (W5 * Y5) - AB5 - P2` | Siehe unten |
| 32 | profit_mpc_expected | `=K2-W5` | Buy - Sell |
| 33 | profit_usdt_actual | `=AA5-O2-P2-AB5` | Siehe unten |
| 34 | profit_mpc_actual | `=L2-X5` | Filled Buy - Filled Sell |
| 35 | limit_watch_status | `FILLED` (wenn alle Teils FILLED) | - |
| 36 | limit_last_check | `2026-05-12T16:47:44.419259` | - |
| 40 | raw_ex2_response | JSON | API Response |
| 41 | raw_ex2_response_ts | `2026-05-12T16:47:44.419266` | - |

### Row 6 (ex2p1 - Erste Limit Order)

| Spalte | Name | Quelle | Fallback |
|--------|------|--------|----------|
| 1 | trade_id | `0c102f0747_ex2p1` | - |
| 20 | ex2_order_id | `6a033d6b11252d000777b2e9` | API Call |
| 24 | ex2_qty_filled | 10 | API Call |
| 26 | ex2_price_actual | 0.016931 | API Call |
| 27 | ex2_value_usdt | 0.16931 | `qty * price` |
| 28 | ex2_fees | 0.000355551 | API Call |
| 29 | ex2_create_ts | `05/12/2026 16:47:07` | API Call (createTime) |
| 30 | ex2_status | `FILLED` | API Call |
| 35 | limit_watch_status | `FILLED` | API Call |

### Row 7 (ex2p2 - Zweite Limit Order)

| Spalte | Name | Quelle | Fallback |
|--------|------|--------|----------|
| 1 | trade_id | `0c102f0747_ex2p2` | - |
| 20 | ex2_order_id | `6a033d85665f0c00079fafe1` | API Call |
| 24 | ex2_qty_filled | 74 | API Call |
| 26 | ex2_price_actual | 0.01711 | API Call |
| 27 | ex2_value_usdt | 1.26614 | `qty * price` |
| 28 | ex2_fees | 0.002658 | API Call |
| 29 | ex2_create_ts | `05/12/2026 16:47:33` | API Call (createTime) |
| 30 | ex2_status | `FILLED` | API Call |
| 35 | limit_watch_status | `FILLED` | API Call |

---

## FORMELN (YELLOW FIELDS)

### Row 2 - Main Trade

```
ex1_qty_filled (Col 12) = ex1p1_qty + ex1p2_qty = L3 + L4
ex1_price_actual (Col 14) = (ex1p1_qty * ex1p1_price + ex1p2_qty * ex1p2_price) / ex1_qty_filled
                          = (L3*N3 + L4*N4) / L2
ex1_value_usdt (Col 15) = ex1p1_value + ex1p2_value = O3 + O4
ex1_fees (Col 16) = ex1p1_fees + ex1p2_fees = P3 + P4
```

### Row 5 - ex2sum

```
ex2_qty_filled (Col 24) = ex2p1_qty + ex2p2_qty = X6 + X7
ex2_price_actual (Col 26) = (ex2p1_price * ex2p1_qty + ex2p2_price * ex2p2_qty) / ex2_qty_filled
                          = (Z6*X6 + Z7*X7) / X5
ex2_value_usdt (Col 27) = ex2p1_value + ex2p2_value = AA6 + AA7
ex2_fees (Col 28) = ex2p1_fees + ex2p2_fees = AB6 + AB7

profit_usdt_expected (Col 31) = ex2_value - (ex2_qty_ordered * ex2_price_expected) - ex2_fees - ex1_fees
                               = AA5 - (W5 * Y5) - AB5 - P2

profit_mpc_expected (Col 32) = ex1_qty_filled - ex2_qty_ordered
                             = K2 - W5

profit_usdt_actual (Col 33) = ex2_value - ex1_value - ex1_fees - ex2_fees
                            = AA5 - O2 - P2 - AB5

profit_mpc_actual (Col 34) = ex1_qty_filled - ex2_qty_filled
                           = L2 - X5
```

---

## API CALLS

### KUCOIN API

#### Get Fills for Order
```
GET /api/v1/fills?orderId={orderId}
Headers: KC-API-KEY, KC-API-SIGN, KC-API-TIMESTAMP, KC-API-PASSPHRASE, KC-API-KEY-VERSION

Response:
{
  "code": "200000",
  "data": {
    "items": [
      {
        "symbol": "MPC-USDT",
        "tradeId": "23033909761544192",
        "orderId": "6a05d3d509447600077f136e",
        "counterOrderId": "...",
        "side": "sell",
        "liquidity": "taker",
        "price": "0.014914",
        "size": "3072",
        "funds": "45.815808",
        "fee": "0.0962131968",
        "feeRate": "0.003",
        "feeCurrency": "USDT",
        "stop": "",
        "tradeType": "TRADE",
        "type": "limit",
        "createdAt": 1778766805344  // <-- createTime in ms
      }
    ]
  }
}
```

**Mapping:**
- `size` → qty_filled
- `price` → price_actual
- `funds` → value_usdt
- `fee` → fees
- `createdAt` → create_ts

#### Get Order Details
```
GET /api/v1/orders/{orderId}?symbol=MPC-USDT
Headers: Same as above

Response:
{
  "code": "200000",
  "data": {
    "orderId": "6a05d3d509447600077f136e",
    "symbol": "MPC-USDT",
    "type": "limit",
    "side": "sell",
    "price": "0.0165",
    "size": "100",
    "dealSize": "85",
    "dealFunds": "1.35",
    "fee": "0.0027",
    "feeCurrency": "USDT",
    "status": "FILLED",
    "createdAt": 1747066805344,
    "updatedAt": 1747066812345
  }
}
```

**Mapping:**
- `createdAt` → create_ts (wichtig: NICHT updatedAt!)
- `status` → ex_status
- `dealSize` → qty_filled
- `dealFunds` → value_usdt

---

### MEXC API

#### Get Order Details
```
GET /api/v3/order?symbol=MPCUSDT&orderId={orderId}&timestamp={ts}&signature={sig}
Headers: X-MEXC-APIKEY: {api_key}

Response:
{
  "symbol": "MPCUSDT",
  "orderId": "1316493343560908801",
  "price": "0.0165",
  "quantity": "100",
  "dealQuantity": "85",
  "dealAmount": "1.35",
  "status": "FILLED",
  "createTime": 1747066805344,
  "updateTime": 1747066812345
}
```

**Mapping:**
- `createTime` → create_ts (wichtig: NICHT updateTime!)
- `status` → ex_status
- `dealQuantity` → qty_filled
- `dealAmount` → value_usdt

#### Get Trades (myTrades)
```
GET /api/v3/myTrades?symbol=MPCUSDT&timestamp={ts}&signature={sig}
Headers: X-MEXC-APIKEY: {api_key}

Response:
[
  {
    "symbol": "MPCUSDT",
    "id": "683606826998018048X2",
    "orderId": "C02__683606826998018048119",
    "price": "0.01419",
    "qty": "3071.63",
    "quoteQty": "43.5864297",
    "commission": "0.02179321485",
    "commissionAsset": "USDT",
    "time": 1778766804000,
    "isBuyer": true,
    "isMaker": false
  }
]
```

**Mapping:**
- `commission` → fees
- `time` → fill timestamp
- `qty` → qty_filled
- `quoteQty` → value_usdt

---

## FELDER MIT API FALLBACKS

### ex1_create_ts (Col 17)
1. **Primary:** `createdAt` aus KuCoin `/api/v1/orders/{orderId}`
2. **Fallback:** `time` aus KuCoin `/api/v1/fills`
3. **Fallback:** intern_ts (wenn nichts verfügbar)

### ex2_create_ts (Col 29)
1. **Primary:** `createdAt` aus KuCoin `/api/v1/orders/{orderId}`
2. **Fallback:** `createTime` aus MEXC `/api/v3/order`
3. **Fallback:** `updateTime` aus MEXC (wenn createTime = null)
4. **Fallback:** `time` aus MEXC `/api/v3/myTrades`
5. **Fallback:** leer lassen (wenn nichts verfügbar)

### ex1_fees / ex2_fees (Col 16 / Col 28)
1. **Primary:** `fee` aus `/api/v1/fills` (KuCoin) oder `commission` aus `/api/v3/myTrades` (MEXC)
2. **Fallback:** Berechnung aus `funds * feeRate` (KuCoin)
3. **Fallback:** 0 (wenn nicht ermittelbar)

**⚠️ WICHTIG MEXC:** Die `myTrades` API liefert NUR Fills für FILLED Orders. Bei PARTIALLY_FILLED Orders muss man `myTrades` abfragen um ALLE Fills zu summieren!

Beispiel Limit Order `C02__682912199902982145119`:
- Order status: PARTIALLY_FILLED
- ex2_fees: 0.000659379 USDT (aus `myTrades` commission)

### ex1_status (Col 18) / ex2_status (Col 30)
1. **Primary:** `status` aus `/api/v1/orders` (KuCoin) oder `/api/v3/order` (MEXC)
2. **Fallback:** `FILLED` wenn qty_filled > 0

### profit_usdt_expected (Col 31)
```
= ex2_value_usdt - (ex2_qty_ordered * ex2_price_expected) - ex2_fees - ex1_fees
```
Basiert auf:
- ex2_value_usdt (berechnet aus Summe der Teil-Fills)
- ex2_qty_ordered (geplant)
- ex2_price_expected (Limit Preis)
- ex1_fees + ex2_fees (summiert)

### profit_mpc_expected (Col 32)
```
= ex1_qty_filled - ex2_qty_ordered
```
Basiert auf:
- ex1_qty_filled (Summe Market Fills)
- ex2_qty_ordered (geplante Sell Qty)

### profit_usdt_actual (Col 33)
```
= ex2_value_usdt - ex1_value_usdt - ex1_fees - ex2_fees
```
Basiert auf:
- ex2_value_usdt (Summe Limit Fills)
- ex1_value_usdt (Summe Market Fills)
- ex1_fees + ex2_fees (summiert)

### profit_mpc_actual (Col 34)
```
= ex1_qty_filled - ex2_qty_filled
```
Basiert auf:
- ex1_qty_filled (Summe Market Fills)
- ex2_qty_filled (Summe Limit Fills)

---

## DOPPELUNG: Spalte 30 vs Spalte 35

- **ex2_status (Col 30):** Exchange-Side Status
- **limit_watch_status (Col 35):** Interne Bot-Logik

**Entscheidung:** Nur Spalte 35 behalten (interner Tracker).
Spalte 30 kann entfernt werden wenn alle API Responses reliable sind.

---

## WHITE FIELDS (nicht füllen)

Folgende Felder/Positionen bleiben leer:
- Row 3-4, Col 1: Nur trade_id (keine weiteren Spalten nötig)
- Row 6-7, Col 1: Nur trade_id
- Row 2, Col 19-36: Zusammenfassungsfelder
- Row 3-4, Col 1,20-41: Nur Fill-Daten relevant
- Row 6-7, Col 1,21-28: Nur Limit-Fill-Daten relevant

---

## TRADE ID NAMING

| Zeile | trade_id Suffix | Bedeutung |
|-------|-----------------|-----------|
| Row 2 | (kein suffix) | Main Trade: `0c102f0747` |
| Row 3 | `_ex1p1` | ex1 Teil 1: `0c102f0747_ex1p1` |
| Row 4 | `_ex1p2` | ex1 Teil 2: `0c102f0747_ex1p2` |
| Row 5 | `_ex2sum` | ex2 Summe: `0c102f0747_ex2sum` |
| Row 6 | `_ex2p1` | ex2 Teil 1: `0c102f0747_ex2p1` |
| Row 7 | `_ex2p2` | ex2 Teil 2: `0c102f0747_ex2p2` |

Wenn nur 1 Fill pro Side existiert, nur _ex1p1 und _ex2p1 schreiben (kein _ex2p2).

---

## NOTIZEN

- **createTime vs Fill Time:** WICHTIG! Das Feld heißt `create_ts` und soll die ERSTELLUNG der Order enthalten, NICHT die Fill-Zeit
- **KuCoin:** `createdAt` = Order Creation, `tradeTime` oder `updatedAt` = Fill Zeit
- **MEXC:** `createTime` = Order Creation, `updateTime` = Letzte Änderung
- **Multi-Fill:** Wenn eine Order mehrere Fills hat (z.B. Market Order teilt sich), wird pro Fill eine Zeile geschrieben
- **Partial Fills:** Wenn Limit Order nur teilweise gefüllt, nur die Rows schreiben die tatsächlich Fill-Daten haben

---

*Stand: 2026-05-14*
---

## 🚨 CRITICAL: MEXC Multi-Fill Orders

**Siehe:** `/memory/mexc-multi-fill-issue.md`

MEXC Market Orders können MEHRERE Fills haben. Der Bot logged bisher nur den ersten Fill!

**Beispiel:**
- Order ID: `C02__682895673279864832119`
- Fill 1: 73.88 MPC @ 0.01672 (1.2352736 USDT)
- Fill 2: 67.12 MPC @ 0.01662 (1.1155344 USDT)
- **Total: 141 MPC** (aber Bot logged nur 73.88!)

**Lösung:** `myTrades` API für ALLE Fills summieren, nicht nur den ersten Fill verwenden.

---

*Stand: 2026-05-15*
