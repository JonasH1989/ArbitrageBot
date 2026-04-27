# Trade Flows - Detaillierte Beschreibung aller 8 Fälle

## Übersicht

| Fall | Trade | Strategie | Limit-Seite hat kleineres Vol |
|------|-------|-----------|------------------------------|
| M→K_1_a | M→K | USDT | KuCoin |
| M→K_1_b | M→K | USDT | MEXC |
| M→K_2_a | M→K | COINS | KuCoin |
| M→K_2_b | M→K | COINS | MEXC |
| K→M_1_a | K→M | USDT | MEXC |
| K→M_1_b | K→M | USDT | KuCoin |
| K→M_2_a | K→M | COINS | MEXC |
| K→M_2_b | K→M | COINS | KuCoin |

---

## M→K Trades (MEXC kaufen, KuCoin verkaufen)

Grundlagen:
- **Buy Side** = MEXC (Market Order, wir kaufen MPC)
- **Sell Side** = KuCoin (Limit Order, wir verkaufen MPC)
- pK = KuCoin Bid Preis
- pM = MEXC Ask Preis

---

## M→K_1_a: USDT Strategie + KuCoin (Verkaufsseite) hat kleineres Volumen

1. Bot sieht: "KuCoin Bid ist höher als MEXC Ask" und speichert Preise pK und pM
2. Bot prüft, auf welcher Seite das aktuelle Volumen im Orderbook Level 1 kleiner ist → Fall 1a, also **KuCoin** hat weniger Volumen
3. Bot prüft, ob das Volumen auf KuCoin die Mindestordermenge von MEXC UND KuCoin erreicht
   → Wenn nein: KuCoin Orderbook Level 2 prüfen → wenn Threshold + Mindestvolumen Level 1 + Level 2 erfüllt sind → weiter zu Schritt 4. Wenn Threshold + Mindestvolumen Level 1 + Level 2 **nicht** erfüllt sind → kein Trade ausführen!
   → Wenn ja: weiter zu Schritt 4
4. Bot führt Market **Buy** auf MEXC mit dem Volumen von Level 1 oder Level 1+2 oder weiteren Leveln (KuCoin-seitig) aus → wir kaufen X MPC
5. MEXC antwortet: "OK, du hast X MPC gekauft für Y USDT zum Preis pM" → prüfen ob der zu Beginn gespeicherte Preis pM erreicht wurde. Wenn ja, weitermachen. Wenn nein → prüfen ob zum gespeicherten Preis der Gegenseite pK die Profitabilität noch gegeben ist. Wenn nein → Preis für Limit Order auf KuCoin so anpassen, dass sich der gleiche Spread wie bei pK und pM ergibt.
6. USD-Strategie: **Limit Sell** auf KuCoin mit X MPC zu Preis pK (oder angepasstem Preis)
7. Limit Order wird im Bestfall später gefüllt (oder auch nicht → dann abwarten und offen lassen)

---

## M→K_1_b: USDT Strategie + MEXC (Kaufseite) hat kleineres Volumen

1. Bot sieht: "KuCoin Bid ist höher als MEXC Ask" und speichert Preise pK und pM
2. Bot prüft, auf welcher Seite das aktuelle Volumen im Orderbook Level 1 kleiner ist → Fall 1b, also **MEXC** hat weniger Volumen
3. Bot prüft, ob das Volumen auf MEXC die Mindestordermenge von MEXC UND KuCoin erreicht
   → Wenn nein: MEXC Orderbook Level 2 prüfen → wenn Threshold + Mindestvolumen Level 1 + Level 2 erfüllt sind → weiter zu Schritt 4. Wenn Threshold + Mindestvolumen Level 1 + Level 2 **nicht** erfüllt sind → kein Trade ausführen!
   → Wenn ja: weiter zu Schritt 4
4. Bot führt Market **Buy** auf MEXC mit dem Volumen von Level 1 oder Level 1+2 oder weiteren Leveln (MEXC-seitig) aus → wir kaufen Y MPC
5. MEXC antwortet: "OK, du hast Y MPC gekauft für Z USDT zum Preis pM" → prüfen ob der zu Beginn gespeicherte Preis pM erreicht wurde. Wenn ja, weitermachen. Wenn nein → prüfen ob zum gespeicherten Preis der Gegenseite pK die Profitabilität noch gegeben ist. Wenn nein → Preis für Limit Order auf KuCoin so anpassen, dass sich der gleiche Spread wie bei pK und pM ergibt.
6. USD-Strategie: **Limit Sell** auf KuCoin mit Y MPC zu Preis pK (oder angepasstem Preis)
7. Limit Order wird im Bestfall später gefüllt (oder auch nicht → dann abwarten und offen lassen)

---

## M→K_2_a: COINS Strategie + KuCoin (Verkaufsseite) hat kleineres Volumen

1. Bot sieht: "KuCoin Bid ist höher als MEXC Ask" und speichert Preise pK und pM
2. Bot prüft, auf welcher Seite das aktuelle Volumen im Orderbook Level 1 kleiner ist → Fall 2a, also **KuCoin** hat weniger Volumen
3. Bot prüft, ob das Volumen auf KuCoin die Mindestordermenge von MEXC UND KuCoin erreicht
   → Wenn nein: KuCoin Orderbook Level 2 prüfen → wenn Threshold + Mindestvolumen Level 1 + Level 2 erfüllt sind → weiter zu Schritt 4. Wenn Threshold + Mindestvolumen Level 1 + Level 2 **nicht** erfüllt sind → kein Trade ausführen!
   → Wenn ja: weiter zu Schritt 4
4. Bot führt Market **Buy** auf MEXC mit dem Volumen von Level 1 oder Level 1+2 oder weiteren Leveln (KuCoin-seitig) aus → wir kaufen X MPC
5. MEXC antwortet: "OK, du hast X MPC gekauft für Y USDT zum Preis pM" → prüfen ob der zu Beginn gespeicherte Preis pM erreicht wurde. Wenn ja, weitermachen. Wenn nein → prüfen ob zum gespeicherten Preis der Gegenseite pK die Profitabilität noch gegeben ist. Wenn nein → Preis für Limit Order auf KuCoin so anpassen, dass sich der gleiche Spread wie bei pK und pM ergibt.
6. COINS-Strategie: Wir haben X MPC gekauft für Y USDT → wir verkaufen NICHT X MPC
   - Stattdessen: Wir verkaufen Y USDT / pK = **(X × pM) / pK MPC**
   - Da pK > pM, ist (X × pM) / pK **< X** → wir verkaufen weniger MPC als wir gekauft haben!
7. **Limit Sell** auf KuCoin mit **(X × pM) / pK** MPC zu Preis pK (oder angepasstem Preis)
8. → **Gewinn = X - (X × pM) / pK = X × (pK - pM) / pK MPC**
9. Limit Order wird im Bestfall später gefüllt (oder auch nicht → dann abwarten und offen lassen)

---

## M→K_2_b: COINS Strategie + MEXC (Kaufseite) hat kleineres Volumen

1. Bot sieht: "KuCoin Bid ist höher als MEXC Ask" und speichert Preise pK und pM
2. Bot prüft, auf welcher Seite das aktuelle Volumen im Orderbook Level 1 kleiner ist → Fall 2b, also **MEXC** hat weniger Volumen
3. Bot prüft, ob das Volumen auf MEXC die Mindestordermenge von MEXC UND KuCoin erreicht
   → Wenn nein: MEXC Orderbook Level 2 prüfen → wenn Threshold + Mindestvolumen Level 1 + Level 2 erfüllt sind → weiter zu Schritt 4. Wenn Threshold + Mindestvolumen Level 1 + Level 2 **nicht** erfüllt sind → kein Trade ausführen!
   → Wenn ja: weiter zu Schritt 4
4. Bot führt Market **Buy** auf MEXC mit dem Volumen von Level 1 oder Level 1+2 oder weiteren Leveln (MEXC-seitig) aus → wir kaufen Y MPC
5. MEXC antwortet: "OK, du hast Y MPC gekauft für Z USDT zum Preis pM" → prüfen ob der zu Beginn gespeicherte Preis pM erreicht wurde. Wenn ja, weitermachen. Wenn nein → prüfen ob zum gespeicherten Preis der Gegenseite pK die Profitabilität noch gegeben ist. Wenn nein → Preis für Limit Order auf KuCoin so anpassen, dass sich der gleiche Spread wie bei pK und pM ergibt.
6. COINS-Strategie: Wir haben Y MPC gekauft für Z USDT → wir verkaufen NICHT Y MPC
   - Stattdessen: Wir verkaufen Z USDT / pK = **(Y × pM) / pK MPC**
   - Da pK > pM, ist (Y × pM) / pK **< Y** → wir verkaufen weniger MPC als wir gekauft haben!
7. **Limit Sell** auf KuCoin mit **(Y × pM) / pK** MPC zu Preis pK (oder angepasstem Preis)
8. → **Gewinn = Y - (Y × pM) / pK = Y × (pK - pM) / pK MPC**
9. Limit Order wird im Bestfall später gefüllt (oder auch nicht → dann abwarten und offen lassen)

---

## K→M Trades (KuCoin kaufen, MEXC verkaufen)

Grundlagen:
- **Buy Side** = KuCoin (Market Order, wir kaufen MPC)
- **Sell Side** = MEXC (Limit Order, wir verkaufen MPC)
- pK = KuCoin Ask Preis
- pM = MEXC Bid Preis

---

## K→M_1_a: USDT Strategie + MEXC (Verkaufsseite) hat kleineres Volumen

1. Bot sieht: "MEXC Bid ist höher als KuCoin Ask" und speichert Preise pM und pK
2. Bot prüft, auf welcher Seite das aktuelle Volumen im Orderbook Level 1 kleiner ist → Fall 1a, also **MEXC** hat weniger Volumen
3. Bot prüft, ob das Volumen auf MEXC die Mindestordermenge von MEXC UND KuCoin erreicht
   → Wenn nein: MEXC Orderbook Level 2 prüfen → wenn Threshold + Mindestvolumen Level 1 + Level 2 erfüllt sind → weiter zu Schritt 4. Wenn Threshold + Mindestvolumen Level 1 + Level 2 **nicht** erfüllt sind → kein Trade ausführen!
   → Wenn ja: weiter zu Schritt 4
4. Bot führt Market **Sell** auf MEXC mit dem Volumen von Level 1 oder Level 1+2 oder weiteren Leveln aus → wir verkaufen X MPC
5. MEXC antwortet: "OK, du hast X MPC verkauft für Y USDT zum Preis pM" → prüfen ob der zu Beginn gespeicherte Preis pM erreicht wurde. Wenn ja, weitermachen. Wenn nein → prüfen ob zum gespeicherten Preis der Gegenseite pK die Profitabilität noch gegeben ist. Wenn nein → Preis für Limit Order auf KuCoin so anpassen, dass sich der gleiche Spread wie bei pK und pM ergibt.
6. USD-Strategie: **Limit Buy** auf KuCoin mit X MPC zu Preis pK (oder angepasstem Preis)
7. Limit Order wird im Bestfall später gefüllt (oder auch nicht → dann abwarten und offen lassen)

---

## K→M_1_b: USDT Strategie + KuCoin (Kaufseite) hat kleineres Volumen

1. Bot sieht: "MEXC Bid ist höher als KuCoin Ask" und speichert Preise pM und pK
2. Bot prüft, auf welcher Seite das aktuelle Volumen im Orderbook Level 1 kleiner ist → Fall 1b, also **KuCoin** hat weniger Volumen
3. Bot prüft, ob das Volumen auf KuCoin die Mindestordermenge von MEXC UND KuCoin erreicht
   → Wenn nein: KuCoin Orderbook Level 2 prüfen → wenn Threshold + Mindestvolumen Level 1 + Level 2 erfüllt sind → weiter zu Schritt 4. Wenn Threshold + Mindestvolumen Level 1 + Level 2 **nicht** erfüllt sind → kein Trade ausführen!
   → Wenn ja: weiter zu Schritt 4
4. Bot führt Market **Sell** auf KuCoin mit dem Volumen von Level 1 oder Level 1+2 oder weiteren Leveln aus → wir verkaufen Y MPC
5. KuCoin antwortet: "OK, du hast Y MPC verkauft für Z USDT zum Preis pK" → prüfen ob der zu Beginn gespeicherte Preis pK erreicht wurde. Wenn ja, weitermachen. Wenn nein → prüfen ob zum gespeicherten Preis der Gegenseite pM die Profitabilität noch gegeben ist. Wenn nein → Preis für Limit Order auf MEXC so anpassen, dass sich der gleiche Spread wie bei pK und pM ergibt.
6. USD-Strategie: **Limit Buy** auf MEXC mit Y MPC zu Preis pM (oder angepasstem Preis)
7. Limit Order wird im Bestfall später gefüllt (oder auch nicht → dann abwarten und offen lassen)

---

## K→M_2_a: COINS Strategie + MEXC (Verkaufsseite) hat kleineres Volumen

1. Bot sieht: "MEXC Bid ist höher als KuCoin Ask" und speichert Preise pM und pK
2. Bot prüft, auf welcher Seite das aktuelle Volumen im Orderbook Level 1 kleiner ist → Fall 2a, also **MEXC** hat weniger Volumen
3. Bot prüft, ob das Volumen auf MEXC die Mindestordermenge von MEXC UND KuCoin erreicht
   → Wenn nein: MEXC Orderbook Level 2 prüfen → wenn Threshold + Mindestvolumen Level 1 + Level 2 erfüllt sind → weiter zu Schritt 4. Wenn Threshold + Mindestvolumen Level 1 + Level 2 **nicht** erfüllt sind → kein Trade ausführen!
   → Wenn ja: weiter zu Schritt 4
4. Bot führt Market **Buy** auf KuCoin mit dem Volumen von Level 1 oder Level 1+2 oder weiteren Leveln (MEXC-seitig) aus → wir kaufen X MPC
5. KuCoin antwortet: "OK, du hast X MPC gekauft für Y USDT zum Preis pK" → prüfen ob der zu Beginn gespeicherte Preis pK erreicht wurde. Wenn ja, weitermachen. Wenn nein → prüfen ob zum gespeicherten Preis der Gegenseite pM die Profitabilität noch gegeben ist. Wenn nein → Preis für Limit Order auf MEXC so anpassen, dass sich der gleiche Spread wie bei pK und pM ergibt.
6. COINS-Strategie: Wir haben X MPC gekauft für Y USDT → wir verkaufen NICHT X MPC
   - Stattdessen: Wir verkaufen Y USDT / pM = **(X × pK) / pM MPC**
   - Da pM > pK, ist (X × pK) / pM **< X** → wir verkaufen weniger MPC als wir gekauft haben!
7. **Limit Sell** auf MEXC mit **(X × pK) / pM** MPC zu Preis pM (oder angepasstem Preis)
8. → **Gewinn = X - (X × pK) / pM = X × (pM - pK) / pM MPC**
9. Limit Order wird im Bestfall später gefüllt (oder auch nicht → dann abwarten und offen lassen)

---

## K→M_2_b: COINS Strategie + KuCoin (Kaufseite) hat kleineres Volumen

1. Bot sieht: "MEXC Bid ist höher als KuCoin Ask" und speichert Preise pM und pK
2. Bot prüft, auf welcher Seite das aktuelle Volumen im Orderbook Level 1 kleiner ist → Fall 2b, also **KuCoin** hat weniger Volumen
3. Bot prüft, ob das Volumen auf KuCoin die Mindestordermenge von MEXC UND KuCoin erreicht
   → Wenn nein: KuCoin Orderbook Level 2 prüfen → wenn Threshold + Mindestvolumen Level 1 + Level 2 erfüllt sind → weiter zu Schritt 4. Wenn Threshold + Mindestvolumen Level 1 + Level 2 **nicht** erfüllt sind → kein Trade ausführen!
   → Wenn ja: weiter zu Schritt 4
4. Bot führt Market **Buy** auf KuCoin mit dem Volumen von Level 1 oder Level 1+2 oder weiteren Leveln (KuCoin-seitig) aus → wir kaufen Y MPC
5. KuCoin antwortet: "OK, du hast Y MPC gekauft für Z USDT zum Preis pK" → prüfen ob der zu Beginn gespeicherte Preis pK erreicht wurde. Wenn ja, weitermachen. Wenn nein → prüfen ob zum gespeicherten Preis der Gegenseite pM die Profitabilität noch gegeben ist. Wenn nein → Preis für Limit Order auf MEXC so anpassen, dass sich der gleiche Spread wie bei pK und pM ergibt.
6. COINS-Strategie: Wir haben Y MPC gekauft für Z USDT → wir verkaufen NICHT Y MPC
   - Stattdessen: Wir verkaufen Z USDT / pM = **(Y × pK) / pM MPC**
   - Da pM > pK, ist (Y × pK) / pM **< Y** → wir verkaufen weniger MPC als wir gekauft haben!
7. **Limit Sell** auf MEXC mit **(Y × pK) / pM** MPC zu Preis pM (oder angepasstem Preis)
8. → **Gewinn = Y - (Y × pK) / pM = Y × (pM - pK) / pM MPC**
9. Limit Order wird im Bestfall später gefüllt (oder auch nicht → dann abwarten und offen lassen)

---

## Zusammenfassung COINS-Strategie Gewinnformeln

| Fall | Volumen gekauft | Volumen verkauft | MPC Gewinn |
|------|-----------------|------------------|------------|
| M→K_2_a | X | (X × pM) / pK | X × (pK - pM) / pK |
| M→K_2_b | Y | (Y × pM) / pK | Y × (pK - pM) / pK |
| K→M_2_a | X | (X × pK) / pM | X × (pM - pK) / pM |
| K→M_2_b | Y | (Y × pK) / pM | Y × (pM - pK) / pM |

---

## Trade-Log Schema (Exchange-Agnostisch)

**Wichtig:** Das Schema ist Exchange-Agnostisch designed. Es können beliebige Börsen integriert werden (KuCoin, MEXC, Binance, etc.), ohne das Schema zu ändern.

### Grundstruktur: Market-Side + Limit-Side

| Feld | Typ | Beschreibung |
|------|-----|--------------|
| `trade_id` | string | Interne ID (Format: `YYYYMMDD_HHMMSS_MMMMMM`) |
| `direction` | string | `M→K` oder `K→M` |
| `strategy` | string | `USDT` oder `COINS` |
| `spread_pct` | float | Spread in % beim Trade |
| `created_at` | timestamp | Wann der Trade initiiert wurde |

### Market-Side (wer kauft ein - immer MARKET Order)

| Feld | Typ | Beschreibung |
|------|-----|--------------|
| `market_exchange` | string | Exchange Name (z.B. `MEXC`, `KUCOIN`, `BINANCE`) |
| `market_side` | string | `BUY` oder `SELL` |
| `market_type` | string | Immer `MARKET` |
| `market_order_id` | string | Order ID der Exchange |
| `market_qty_ordered` | float | Quantität bestellt |
| `market_qty_filled` | float | Quantität gefüllt |
| `market_price_expected` | float | Erwarteter Preis (pK oder pM) |
| `market_price_actual` | float | Tatsächlicher Ausführungspreis |
| `market_value_usdt` | float | USDT Wert |
| `market_fees` | float | Fees in USDT |
| `market_status` | string | `FILLED` / `PARTIAL` / `REJECTED` / `PENDING` |
| `market_timestamp` | timestamp | Wann die Order ausgeführt wurde |
| `market_raw_response` | JSON | Komplette Roh-Antwort der Exchange |

### Limit-Side (wer verkauft - immer LIMIT Order)

| Feld | Typ | Beschreibung |
|------|-----|--------------|
| `limit_exchange` | string | Exchange Name |
| `limit_side` | string | `BUY` oder `SELL` |
| `limit_type` | string | Immer `LIMIT` |
| `limit_order_id` | string | Order ID der Exchange |
| `limit_qty_ordered` | float | Quantität bestellt |
| `limit_qty_filled` | float | Quantität gefüllt (0 = Pending) |
| `limit_price_expected` | float | Erwarteter Preis |
| `limit_price_actual` | float | Tatsächlicher Preis (bei Fill) |
| `limit_fees` | float | Fees in USDT |
| `limit_status` | string | `PENDING` / `FILLED` / `PARTIAL` / `CANCELLED` |
| `limit_timestamp` | timestamp | Wann die Order platziert wurde |
| `limit_raw_response` | JSON | Komplette Roh-Antwort der Exchange |

### Profit-Berechnung

| Feld | Typ | Beschreibung |
|------|-----|--------------|
| `profit_usdt_expected` | float | Erwarteter USDT Gewinn |
| `profit_mpc_expected` | float | Erwarteter MPC Gewinn |
| `profit_usdt_actual` | float | Tatsächlicher USDT Gewinn (nach Limit Fill) |
| `profit_mpc_actual` | float | Tatsächlicher MPC Gewinn (nach Limit Fill) |

### Error-Handling

| Feld | Typ | Beschreibung |
|------|-----|--------------|
| `error_code` | string | Fehler-Code (z.B. `QTY_ZERO`, `PRICE_SLIPPAGE`, `API_ERROR`) |
| `error_message` | string | Menschlich lesbare Fehlerbeschreibung |

### Beispiel-JSON

```json
{
  "trade_id": "20260427_234156_789012",
  "direction": "M→K",
  "strategy": "COINS",
  "spread_pct": 1.25,
  "created_at": 1777315123000,
  
  "market_exchange": "MEXC",
  "market_side": "BUY",
  "market_type": "MARKET",
  "market_order_id": "mx_123456789",
  "market_qty_ordered": 100,
  "market_qty_filled": 100,
  "market_price_expected": 0.01100,
  "market_price_actual": 0.01105,
  "market_value_usdt": 1.105,
  "market_fees": 0.004,
  "market_status": "FILLED",
  "market_timestamp": 1777315123,
  "market_raw_response": { ... },
  
  "limit_exchange": "KUCOIN",
  "limit_side": "SELL",
  "limit_type": "LIMIT",
  "limit_order_id": "kc_abc123def",
  "limit_qty_ordered": 95,
  "limit_qty_filled": 0,
  "limit_price_expected": 0.01120,
  "limit_price_actual": 0,
  "limit_fees": 0,
  "limit_status": "PENDING",
  "limit_timestamp": 1777315124,
  "limit_raw_response": { ... },
  
  "profit_usdt_expected": 0.020,
  "profit_mpc_expected": 1.79,
  "profit_usdt_actual": null,
  "profit_mpc_actual": null,
  
  "error_code": null,
  "error_message": null
}
```

### Trade-Audit-Trail (Zustandsübergänge)

Jeder Trade durchläuft definierte Zustände:

```
INITIATED → MARKET_ORDER_SENT → MARKET_FILLED → LIMIT_ORDER_SENT → FILLED
                ↓                    ↓                 ↓
            ERROR_SEND          ERROR_FILL        ERROR_NOT_APPEARING
```

Bei jedem Zustandsübergang:
- Timestamp loggen
- Bei ERROR: `error_code` und `error_message` setzen
- Bei ERROR: Alert senden und in STATE_WAITING wechseln
