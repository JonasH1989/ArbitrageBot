# API zu CSV Zellen Mapping

> **Quellen:** XLSX SAMPLES + Mapping Tab + API Dokumentation
> **Stand:** 2026-05-30
> **WICHTIG:** `raw_ex1_response` und `raw_ex2_response` sind die ORIGINALEN API Responses, nicht transformierte Bot-Daten!

---

## MEXC API (ex1 = Market Order)

### raw_ex1_response - Direkte API Response bei Order-Ausführung

**MEXC Create Order Response (Market Order):**
```json
{
  "status": "FILLED",
  "orderId": "C02__688414764631461888119",
  "quantity": "183.0",
  "amount": "3.21165",
  "fees": 0.0,
  "price": "0.01755",
  "executedQty": "183.0",
  "cummulativeQuoteQty": "3.21165",
  "type": "MARKET"
}
```

| CSV Spalte | API Feld | Bemerkung |
|------------|----------|-----------|
| ex1_order_id | orderId | |
| ex1_qty_filled | quantity oder executedQty | |
| ex1_value_usdt | **amount** (NICHT quoteQty!) | Direkt in raw Response |
| ex1_price_actual | price | |
| ex1_create_ts | **time** (wird aus timestamp abgeleitet) | |
| ex1_fees | fees | |
| ex1_status | status (mapped) | "FILLED" |

---

### myTrades API - Für MEXC Multi-Fill Abgleich (Fallback)

**MEXC myTrades Response:**
```json
[
  {
    "symbol": "MPCUSDT",
    "id": "688414627339358208X1",
    "orderId": "C02__688414764631461888119",
    "price": "0.01793",
    "qty": "44.27",
    "quoteQty": "0.7937611",
    "commission": "0.00039688055",
    "time": 1779913106000
  }
]
```

| CSV Spalte | API Feld | Bemerkung |
|------------|----------|-----------|
| ex1_qty_filled | qty | Pro Fill |
| ex1_price_actual | price | Pro Fill |
| ex1_value_usdt | **quoteQty** | Pro Fill |
| ex1_fees | commission | Pro Fill |
| **ex1_fill_ts** | time | Fill-Zeitpunkt |

**WICHTIG:** 
- `raw_ex1_response` → `amount` (USDT Gesamtwert)
- `myTrades` → `quoteQty` (USDT pro Fill)
- Für erste Fill-Daten: `raw_ex1_response` reicht aus
- Für Multi-Fill Abgleich: `myTrades` mit `quoteQty`!

---

## KuCoin API (ex2 = Limit Order)

### raw_ex2_response - Oft UNVOLLSTÄNDIG!

**KuCoin Create Order Response (Limit Order):**
```json
{"orderId": "6a1751931296f100074bae96"}
```
⚠️ **KuCoin gibt oft nur die Order-ID zurück!**

| CSV Spalte | API Feld | Bemerkung |
|------------|----------|-----------|
| ex2_order_id | orderId | Das ist alles was oft kommt! |
| ex2_create_ts | **MUSS separat abgefragt werden** | Siehe unten |

---

### KuCoin Order Status API (Fallback für create_ts)

**GET /api/v1/orders/{orderId}?symbol=MPC-USDT:**
```json
{
  "id": "6a1751931296f100074bae96",
  "symbol": "MPC-USDT",
  "type": "limit",
  "side": "sell",
  "price": "0.018148",
  "size": "183",
  "dealSize": "183",
  "dealFunds": "3.321084",
  "fee": "0.009963252",
  "isActive": false,
  "cancelExist": false,
  "createdAt": 1779913111512
}
```

| CSV Spalte | API Feld | Bemerkung |
|------------|----------|-----------|
| ex2_create_ts | createdAt | Wann Order erstellt |
| ex2_qty_filled | dealSize | |
| ex2_value_usdt | dealFunds | |
| ex2_fees | fee | |
| ex2_status | isActive, cancelExist | Siehe Status-Mapping |

---

### KuCoin Fills API - Für vollständige Fill-Daten (IMMER nötig!)

**GET /api/v1/fills?orderId={orderId}&symbol=MPC-USDT:**
```json
{
  "code": "200000",
  "data": {
    "items": [
      {
        "orderId": "6a1751931296f100074bae96",
        "side": "sell",
        "price": "0.018148",
        "size": "183",
        "funds": "3.321084",
        "fee": "0.009963252",
        "feeRate": "0.003",
        "liquidity": "maker",
        "tradeId": "23531736214409229",
        "createdAt": 1779964156001
      }
    ]
  }
}
```

| CSV Spalte | API Feld | Bemerkung |
|------------|----------|-----------|
| **ex2_fill_ts** | createdAt | Wann Fill PASSIERTE |
| ex2_qty_filled | size | Pro Fill |
| ex2_price_actual | price | Pro Fill |
| ex2_value_usdt | funds | Pro Fill |
| ex2_fees | fee | Pro Fill |

---

## Zusammenfassung: Timestamp-Quellen

### MEXC
| Feld | API Quelle | Feldname |
|------|------------|-----------|
| `ex1_create_ts` | raw_ex1_response | time |
| `ex1_fill_ts` | myTrades | time |

### KuCoin
| Feld | API Quelle | Feldname |
|------|------------|-----------|
| `ex2_create_ts` | orders API | createdAt |
| `ex2_fill_ts` | **fills API** | createdAt |

---

## Zusammenfassung: Dual-Path Datenbeschaffung

| Exchange | raw_response | Reicht aus? | Fallback |
|----------|-------------|-------------|----------|
| **MEXC** | Vollständig (Order + Fill-Daten inkl. amount) | Oft ja | myTrades für Multi-Fill |
| **KuCoin** | Oft nur `{"orderId": "..."}` | **Nein** | IMMER fills API + orders API |

---

## Status-Mapping

### MEXC
| API Status | CSV Status |
|------------|-----------|
| NEW | OPEN |
| FILLED | FILLED |
| PARTIALLY_FILLED | PARTIAL |
| PARTIALLY_CANCELED | PARTIAL |
| CANCELED | CANCELLED |

### KuCoin
| isActive | cancelExist | dealSize | CSV Status |
|---------|------------|----------|------------|
| false | false | > 0 | FILLED |
| true | false | 0 | OPEN |
| false | true | 0 | CANCELLED |

---

## Wichtige Feldnamen-Unterschiede

| Was | MEXC | KuCoin |
|-----|------|--------|
| USDT Wert (Order) | `amount` oder `cummulativeQuoteQty` | `dealFunds` |
| USDT Wert (Fill) | `quoteQty` | `funds` |
| Qty (Order) | `quantity` oder `executedQty` | `dealSize` |
| Qty (Fill) | `qty` | `size` |
| Fee | `fees` oder `commission` | `fee` |

---

## Hinweis zu XLSX SAMPLES

Die XLSX SAMPLES Tab zeigt echte aufgezeichnete Daten:
- Row 3: MEXC vollständige Response mit `amount: "3.21165"`
- Row 5: KuCoin nur `{"orderId": "6a1751931296f100074bae96"}` - unvollständig!
- Row 6: KuCoin vollständige Fill-Daten (über fills API)

Dies bestätigt: KuCoin MUSS immer separat über fills API abgefragt werden!

---

*Stand: 2026-05-30*