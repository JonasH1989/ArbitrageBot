# Arbitrage Bot Logger — Verbesserungen

> Basierend auf Analyse der Trades vom 2026-06-08
> Quelle: `20260608MPCUSDT_trades---d06ff674-26f1-4ff8-8216-4831de6af5dd.csv`

---

## Priorisierte Implementierungsliste

### 🔴 PRIORITÄT 1 — KRITISCH (Kein Trade ohne Fix)

#### 1.1 trade_id Format korrigieren
**Problem:** trade_id ist random Hex (`08c222e30`) statt Zeitstempel (`0812074400`)
**Doku:** `DDHHMMSSms` (Tag, Stunde, Minute, Sekunde, Millisekunden in Hex)
**Beispiel:** `0812074400` = Tag 8, 12:07:44.00

**Fix:**
```python
now = datetime.now()
trade_id = f"{now.day:02x}{now.hour:02x}{now.minute:02x}{now.second:02x}{now.microsecond//10000:02x}"
```

---

#### 1.2 Fehlgeschlagene Trades NICHT loggen
**Problem:** 337 Orders mit API-Error werden geloggt
**Filter:** Nur loggen wenn `ex1_status == 'FILLED'` oder `ex1_status == 'PARTIAL'`

**Fix:**
```python
if ex1_status not in ('FILLED', 'PARTIAL'):
    return  # Nicht loggen
```

---

### 🟡 PRIORITÄT 2 — WICHTIG (Datenqualität)

#### 2.1 ex1_fill_ts in MAIN ROW setzen
**Problem:** `ex1_fill_ts` ist in Main Row leer, nur in `_ex1p1` gesetzt
**Doku:** Col 18 = Fill-Zeitpunkt (sollte in Main Row stehen)

**Fix:**
```python
# In Main Row: ex1_fill_ts = Zeit des letzten Fill
ex1_fill_ts = max(fill['timestamp'] for fill in ex1_fills)
```

---

#### 2.2 ex2_create_ts in lesbare Zeit umwandeln
**Problem:** `_ex2sum` zeigt Unix ms (`1780914886359`), `_ex2p1` zeigt `0,0`
**Doku:** Sollte lesbarer Timestamp sein (`2026-06-08 12:34:46.491178`)

**Fix:**
```python
from datetime import datetime
ts_ms = int(r['ex2_create_ts'])
ex2_create_ts = datetime.fromtimestamp(ts_ms / 1000).strftime('%Y-%m-%d %H:%M:%S.%f')[:-3]
```

---

#### 2.3 ex2_fill_ts setzen
**Problem:** `ex2_fill_ts` ist immer leer
**Doku:** Col 31 = Fill-Zeitpunkt für ex2

**Fix:**
```python
# Nach Limit Fill: fill_ts aus API Response extrahieren
ex2_fill_ts = fill_response.get('transactTime')
```

---

#### 2.4 ex2_value_usdt in _ex2sum KORREKT berechnen
**Problem:** `_ex2sum` zeigt `0,0000`, sollte aber `SUM(funds)` sein
**Doku:** `ex2_value_usdt = SUM(funds) aller Fills`

**Fix:**
```python
# In _ex2sum Row:
ex2_value_usdt = sum(fill['funds'] for fill in ex2_fills)
```

---

#### 2.5 Profit berechnen
**Problem:** `profit_usdt_actual` und `profit_mpc_actual` sind leer
**Doku:** 
```
profit_usdt_actual = ex2_value - ex1_value - ex1_fees - ex2_fees
profit_mpc_actual = ex1_qty_filled - ex2_qty_filled
```

**Fix:**
```python
profit_usdt_actual = ex2_value_usdt - ex1_value_usdt - ex1_fees - ex2_fees
profit_mpc_actual = ex1_qty_filled - ex2_qty_filled
```

---

### 🟠 PRIORITÄT 3 — NIEDRIG (Nice to have)

#### 3.1 Zahlenformat vereinheitlichen
**Problem:** Main Row: `87,00` (Komma), _ex2p1: `87.0` (Punkt)
**Doku:** Keine explizite Angabe, aber XLSX nutzt Punkt

**Empfehlung:** Immer Punkt als Dezimaltrennzeichen (CSV Standard)

---

#### 3.2 ex2_create_ts in _ex2p1 korrigieren
**Problem:** `_ex2p1` zeigt `0,0` statt korrektem Timestamp

**Fix:** Das richtige `create_ts` aus dem Fill extrahieren

---

## Zusätzliche Probleme (Jonas, 2026-06-08)

### 1. ex1_status bei Trade 3 = PARTIAL obwohl Fills FILLED
**Problem:** Trade `08d151c3b` hat `ex1_status=PARTIAL`, aber die Teilfills sind FILLED
**Ursache:** Die Market Order wurde nur teilweise gefüllt (120/126), aber der Status wird nicht korrekt gemappt

### 2. ex1_create_ts bei KCN->MXC LEER
**Problem:** Trade `08d151c3b` hat `ex1_create_ts=` (leer)
**Ursache:** KuCoin gibt `createdAt` in ms zurück, wird nicht korrekt umgewandelt

### 3. ex2_fees bei MXC = 0
**Problem:** Trade 3 (MXC sell) hat `ex2_fees=0.0`
**Ursache:** MEXC hat Fees, aber sie werden nicht gezogen

### 4. OFFENE Limit Order (Trade 5)
**Problem:** Trade `081272806` hat `ex2_status=OPEN` - Limit Order noch nicht gefüllt
**Handlung:** Offene Orders müssen überwacht/gemanaged werden

### 5. Zahlenformat GEMISCHT
**Problem:** Main Row: `87,00` (Komma), Teilfill-Zeilen: `87.0` (Punkt)
**Empfehlung:** Immer Punkt als Dezimaltrennzeichen

### 6. Alle Profit-Felder LEER
**Problem:** `profit_usdt_expected`, `profit_mpc_expected`, `profit_usdt_actual`, `profit_mpc_actual` = LEER
**Ursache:** Profit-Berechnung wird nicht ausgeführt

---

## Korrigierte Zusammenfassung (9 Probleme)

| Priorität | Problem | Aufwand |
|-----------|---------|---------|
| 🔴 1.1 | trade_id Format | Klein |
| 🔴 1.2 | Fehlgeschlagene nicht loggen | Klein |
| 🔴 1.3 | OFFENE Limit Orders speziel loggen/tracking | Mittel |
| 🟡 2.1 | ex1_fill_ts in Main Row | Klein |
| 🟡 2.2 | ex2_create_ts Format (Unix ms → lesbar) | Mittel |
| 🟡 2.3 | ex2_fill_ts setzen | Mittel |
| 🟡 2.4 | ex2_value_usdt in _ex2sum berechnen | Mittel |
| 🟡 2.5 | Profit berechnen (alle 4 Felder) | Mittel |
| 🟡 2.6 | ex1_create_ts bei KuCoin umwandeln | Mittel |
| 🟡 2.7 | ex2_fees bei MXC ziehen | Mittel |
| 🟡 2.8 | ex1_status PARTIAL korrekt setzen | Klein |
| 🟠 3.1 | Zahlenformat vereinheitlichen (Punkt) | Klein |
| 🟠 3.2 | ex2_create_ts in _ex2p1 korrigieren | Klein |

---

## Test-Szenarien (5 valide Trades)

1. **08c222e30** — MXC->KCN, 87 MPC, FILLED
2. **08c223818** — MXC->KCN, 96 MPC, 2 Fills
3. **08d151c3b** — KCN->MXC, PARTIAL (120/126), Fees prüfen
4. **081271808** — MXC->KCN, 92 MPC, FILLED
5. **081272806** — MXC->KCN, 86 MPC, OPEN (Limit nicht gefüllt)

**Gegencheck API:**
- MEXC: `GET /api/v3/myTrades?symbol=MPCUSDT`
- KuCoin: `GET /api/v1/limit有机户历史`

---

*Erstellt: 2026-06-08*
*Aktualisiert: 2026-06-08 (Jonas Feedback)*
*Quelle Log: `20260608MPCUSDT_trades---d06ff674-26f1-4ff8-8216-4831de6af5dd.csv`*
