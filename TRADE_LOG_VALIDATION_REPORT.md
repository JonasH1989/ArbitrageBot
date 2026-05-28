# TRADE LOG VALIDATION REPORT
## MPCUSDT Trades - 2026-05-27 bis 2026-05-28

---

## ✅ API QUERIES ERFOLGREICH

### KuCoin Replacement Orders abgefragt:

| Trade | Original Order | Replacement Order | Gefüllt | Preis |
|-------|---------------|-------------------|---------|-------|
| 1b16113062 | 6a17516caf78b5000775da5a | **6a1751979c8d050007ecf50d** | ✅ 33 MPC | 0.018941 |
| 1b16113647 | 6a175172571a870007c90fa9 | **6a1751910970a10007e9173d** | ✅ 68 MPC | 0.018935 |
| 1b16122f50 | 6a1751a76950e40007d52a0a | **6a1751c530aa00000711dc0d** | ✅ 31 MPC | 0.018941 |
| 1b16181516 | 6a1752f5a7f17f000770d374 | **6a17578642a70a00075963c5** | ✅ 37 MPC | 0.019 |
| 1b161c1e42 | 6a1753eeeaee1500079a122c | **6a1753eeeaee1500079a122c** (SAME!) | ❌ 0 MPC | - |

---

## ⚠️ PROBLEME IDENTIFIZIERT

### 1. Trade 1b161c1e42 - KRITISCH
- Original und Replacement Order ID sind **IDENTISCH**!
- Order 6a1753eeeaee1500079a122c hat 0 MPC gefüllt
- **Kein Ersatz-Fill gefunden** - Order hängt als offene Limit Order
- Mögliche Ursache: Bot hat versucht, Order zu canceln, aber Cancel ist fehlgeschlagen
- Oder: Order wurde nie wirklich platziert

### 2. CSV Struktur Issues
- ex2p1 rows haben teilweise 0 MPC filled (erwartet bei Cancelled)
- aber die Ersatz-Order-Daten sind NICHT in den ex2p1 rows eingetragen
- Die ex2sum rows zeigen WATCHING statt FILLED

### 3. TRADE_LOG_STRUCTURE.md vs. Realität
- Die Doku beschreibt ein 4-Zeilen-System (Main + ex1p1 + ex2sum + ex2p1)
- Aber: Wenn eine Limit Order cancelled wird und Ersatz-Orders existieren,
  sollten die Ersatz-Daten in ex2p1 rows sein (nicht original cancelled!)
- **Dokumentationslücke:** Wie man Cancelled Orders mit Replacement填补t

---

## 📊 DATENSATZ ÜBERSICHT

### Input CSV:
- 21 main rows (Trades)
- 37 ex1p rows (21× ex1p1, 12× ex1p2, 4× ex1p3)
- 21 ex2sum rows
- 21 ex2p1 rows

### Problem Trades (5):
- 1b16113062, 1b16113647, 1b16122f50, 1b16181516 → Ersatz-Orders vorhanden ✅
- 1b161c1e42 → Ersatz-Order identisch mit Original, 0 MPC filled ❌

### Vollständig FILLED: 16 Trades
- Alle haben vollständige ex1p und ex2p Daten
- ex2_status: FILLED
- limit_watch_status: FILLED

---

## 🔧 KORREKTUR-BEDARF

### Für 4 Trades: ex2p1 rows aktualisieren mit Replacement-Daten:

**Trade 1b16113062:**
```
ex2_qty_filled: 33
ex2_price_actual: 0.018941
ex2_value_usdt: 0.625053
ex2_fees: 0.001875159
ex2_status: FILLED
limit_watch_status: FILLED
ex2_order_id: 6a1751979c8d050007ecf50d (NEU!)
```

**Trade 1b16113647:**
```
ex2_qty_filled: 68
ex2_price_actual: 0.018935
ex2_value_usdt: 1.28758
ex2_fees: 0.00386274
ex2_status: FILLED
limit_watch_status: FILLED
ex2_order_id: 6a1751910970a10007e9173d (NEU!)
```

**Trade 1b16122f50:**
```
ex2_qty_filled: 31
ex2_price_actual: 0.018941
ex2_value_usdt: 0.587171
ex2_fees: 0.001761513
ex2_status: FILLED
limit_watch_status: FILLED
ex2_order_id: 6a1751c530aa00000711dc0d (NEU!)
```

**Trade 1b16181516:**
```
ex2_qty_filled: 37
ex2_price_actual: 0.019
ex2_value_usdt: 0.703
ex2_fees: 0.002109
ex2_status: FILLED
limit_watch_status: FILLED
ex2_order_id: 6a17578642a70a00075963c5 (NEU!)
```

**Trade 1b161c1e42:** → UNRESOLVED - Order hat 0 MPC, braucht manuelle Prüfung

---

## 📝 CODE vs. DOKU DISKREPANZEN

### Issue 1: ex2_value_usdt Berechnung
- TRADE_LOG_STRUCTURE.md sagt: `ex2_value_usdt = SUM(ex2p_values)`
- Aber in der CSV ist ex2_value_usdt bei MANCHEN Trades 0
- Ursache: Bot schreibt value erst nach COMPLETEN Fill
- Bei PARTIAL/CANCELLED bleibt value 0

### Issue 2: ex2_status vs. limit_watch_status
- Doku sagt: "Spalte 30 vs 35 - nur 35 behalten"
- Realität: Bot schreibt in beide Spalten
- ex2_status (30): Exchange-Side
- limit_watch_status (35): Interne Bot-Logik
- **Tatsächlich existieren beide!** Doku ist falsch

### Issue 3: create_ts für Replacement Orders
- Original Order create_at wird beibehalten
- Aber: Replacement Order hat ANDERE create_at timestamp
- Beispiel: Trade 1b16113062 Original created: 1779913066000
- Replacement created: 1779913111512 (5 Sekunden später!)
- **Frage:** Welcher Timestamp gilt als "Order Erstellung"?

### Issue 4: Profit Berechnung bei Partial Fills
- Bei Trade 1b1611d4e: ex1 ordered=137, filled=57.72
- profit_mpc_expected = ex1_qty_filled - ex2_qty_ordered = 57.72 - 58 = -0.28
- ABER: Bot versucht 137 MPC zu verkaufen (ex2_qty_ordered=58 ist FALSE!)
- Korrektur wäre: profit_mpc_expected = 57.72 - 58 = -0.28 MPC (Verlust)
- Das zeigt: Bot erwartet MORE MPC zu verkaufen als er gekauft hat!

---

## ✅ REFERENZ-IMPLEMENTIERUNG

### Korrekt geschriebener Trade (Beispiel: 1b1611d4e):

**Main Row (1b1611d4e):**
```
trade_id: 1b1611d4e
internal_ts: 2026-05-27T22:17:11.640815
direction: MXC->KCN
pair: MPC-USDT
strategy: USDT
spread_pct: 4.325100517
ex1: MXC
ex1_order_id: C02__688414456513777664119
ex1_type: market
ex1_side: buy
ex1_qty_ordered: 137
ex1_qty_filled: 57.72
ex1_price_expected: 0.01741
ex1_price_actual: 0.01741
ex1_value_usdt: 1.0049052
ex1_fees: 0
ex1_create_ts: 27.05.2026 22:17 (aus create_ts: 1779913032000)
ex1_status: PARTIAL
ex2: KCN
ex2_order_id: 6a17514967c9710007139cef
ex2_type: limit
ex2_side: sell
ex2_qty_ordered: 58
ex2_qty_filled: 58.0
ex2_price_expected: 0.018163
ex2_price_actual: 0.018163
ex2_value_usdt: 1.054 (berechnet: 58 * 0.018163)
ex2_fees: 0.003160362
ex2_create_ts: (from KuCoin API)
ex2_status: FILLED
profit_usdt_expected: 0.0485488
profit_mpc_expected: -0.28 (57.72 - 58)
profit_usdt_actual: (berechnet)
profit_mpc_actual: -0.28
limit_watch_status: FILLED
limit_last_check: 2026-05-27T22:17:19.615854
raw_ex1_response: {...}
raw_ex2_response: {...}
raw_ex2_response_ts: 2026-05-27T22:17:13.783106
```

**ex1p1 Row (1b1611d4e_ex1p1):**
```
trade_id: 1b1611d4e_ex1p1
ex1_qty_filled: 57.72
ex1_price_actual: 0.01741
ex1_value_usdt: 1.0049052
ex1_fees: 0
ex1_create_ts: 2026-05-27 22:17:12.000
ex1_status: FILLED
```

**ex2sum Row (1b1611d4e_ex2sum):**
```
trade_id: 1b1611d4e_ex2sum
ex2_order_id: 6a17514967c9710007139cef
ex2_type: limit
ex2_side: sell
ex2_qty_ordered: 58
ex2_qty_filled: 58.0
ex2_price_expected: 0.018163
ex2_price_actual: 0.018163
ex2_value_usdt: 1.054
ex2_fees: 0.003160362
ex2_status: FILLED
profit_usdt_expected: 0.0485488
profit_mpc_expected: -0.28
profit_usdt_actual: (berechnet)
profit_mpc_actual: -0.28
limit_watch_status: FILLED
limit_last_check: 2026-05-27T22:17:19.615854
```

**ex2p1 Row (1b1611d4e_ex2p1):**
```
trade_id: 1b1611d4e_ex2p1
ex2_order_id: 6a17514967c9710007139cef
ex2_qty_filled: 58.0
ex2_price_actual: 0.018163
ex2_value_usdt: 1.054
ex2_fees: 0.003160362
ex2_status: FILLED
limit_watch_status: FILLED
```

---

## 🎯 FAZIT

### Was funktioniert:
- KuCoin API Abfragen für Order-Details ✅
- Fill-Daten für Replacement Orders abrufen ✅
- CSV Struktur korrekt interpretieren ✅

### Was korrigiert werden muss:
- 4 Trades brauchen ex2p1 rows mit Replacement-Daten
- 1 Trade (1b161c1e42) ist ungelöst
- profit_usdt_actual und profit_mpc_actual sind teilweise leer

### Nächste Schritte:
1. Korrigierte CSV mit Replacement-Daten generieren
2. Trade 1b161c1e42 manuell prüfen (Order ID 6a1753eeeaee1500079a122c)
3. TRADE_LOG_STRUCTURE.md aktualisieren für Cancelled Orders mit Replacements

---

*Report erstellt: 2026-05-28 23:15*
*Usta - Arbitrage Bot Validator*