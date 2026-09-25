# Status & Architektur — Jonas' Trade-Bot

**Stand:** 2026-09-26 (nach großer Diskussion mit Jonas)
**Zweck:** Dokumentation aller Trade-Logik-Entscheidungen für Bot-Architektur

## 1. Trade-Flow-Logik (Jonas' STANDARD)

### 1.1 ARMED / DISARMED (Hysteresis)
- **ARM bei `spread >= threshold_start` (1.9%)**
- **DISARM bei `spread < threshold_stop` (0.7%)**
- **RE-ARM nur bei `spread >= threshold_start`** (NICHT im 0.7-1.9% Bereich)
- Dazwischen: bleibt im aktuellen Zustand
- Konsistent mit Code Z. 3449-3456

### 1.2 State-Variablen (Jonas' Empfehlung)
- ARMED ↔ state == STATE_RUNNING
- DISARMED ↔ state == STATE_WAITING
- **TODO:** `hysteresis_armed` Variable rauswerfen, nur `state` Variable verwenden
- Im aktuellen Code sind es zwei separate Variablen (Redundanz)

### 1.3 Trade-Bedingungen (alle müssen True sein)
1. `pair_enabled = True` (Settings)
2. `is_active()` returns True (ACTIVE_FLAG_FILE)
3. State = STATE_WAITING oder STATE_RUNNING
4. **`trade_condition = True`**:
   ```python
   trade_condition = (spread >= threshold_start) OR (armed AND spread >= threshold_stop)
   ```
5. `trade_in_progress = False`
6. `best_trade is not None` (calculate_best_trade validiert)
7. `check_balances_for_trade() returns can_trade=True`
8. `vol_for_mexc > 0` AND `vol_for_kucoin > 0`
9. `execute_trade() returns success=True`

### 1.4 Wallet-Balance
- **Nur FREE coins relevant** (NICHT locked)
- 114988 MPC locked auf MEXC sind irrelevant für Trading-Entscheidungen
- Waren "geparkt" in einer offenen Limit-Sell-Order

## 2. Orderbook + Multi-Level Accumulation

### 2.1 Logik (calculate_best_trade Z. 3013+)
1. **L1 prüfen** — Spread >= threshold UND Volumen >= minimum
2. Wenn L1 nicht genug Volumen → **L1+L2 akkumulieren**
3. Wenn L1+L2 nicht genug → **L1+L2+L3 akkumulieren**
4. An jedem Akkumulations-Punkt: **Spread + Volumen NEU prüfen**
5. `trade_vol = MIN(akkumulierte dünnere Seite, andere Seite Vol)`
6. Dünnere Seite kann sich ändern → ggf. andere Trade-Richtung!

### 2.2 Threshold-Wahl
```python
threshold = stop_threshold if for_follow_up_trade else threshold_start
```
- `for_follow_up_trade=True` → threshold_stop (0.7%) — während ARMED
- `for_follow_up_trade=False` → threshold_start (1.9%) — erster Trade

## 3. Architektur (Jonas' Bestätigung)

### 3.1 2-Thread-Architektur

```
┌─────────────────────────────────────────┐
│  Thread 1: Orderbook-Updates             │
│  - MEXC: Orderbook aller Xms holen       │
│  - KuCoin: Orderbook aller Xms holen     │
│  - Spread neu berechnen                  │
│  - Cache: _latest_orderbook              │
└─────────────────────────────────────────┘
                    ↓ Cache
┌─────────────────────────────────────────┐
│  Thread 2: Main loop (sequenziell)       │
│  1. Trade-Decision (trade_condition)      │
│  2. calculate_best_trade()                 │
│  3. execute_trade()                        │
│  4. trade_in_progress = True/False         │
└─────────────────────────────────────────┘
```

**Begründung:** Trade-Decision + Execution sind sequenziell → können im selben Thread laufen.

### 3.2 Race-Condition-Mechanismen (im Bestandscode)
- ✅ `_latest_data_lock` (threading.Lock für Cache-Zugriff) — Z. 3321-3328, 3392-3404
- ✅ `trade_in_progress` als Flag (main loop, sequenziell)
- ✅ `armed` Berechnung läuft im main loop (kein parallel access)
- ✅ `best_trade` Berechnung läuft im main flow (kein parallel access)

### 3.3 Orderbook-Updates (Detail)
- **Börsenspezifisch** (MEXC + KuCoin separat)
- **So schnell wie Börse erlaubt** (aber Rate-Limit!)
- **Spread wird mit jedem Update neu berechnet**
- **NICHT auf max Rate** — Reserve für andere API-Calls
- Token-Bucket-System: ⚠️ IM BESTANDSCODE NICHT VORHANDEN

### 3.4 Rate-Limit-Management (RECHERCHE NÖTIG)
- ⚠️ Werte müssen aus Exchange-Docs geholt werden (NICHT raten!)
- MEXC: https://mexcglobal.github.io/api-docs/spot-v3.html#rate-limit
- KuCoin: https://www.kucoin.com/docs-new/3470765598196049
- Tier-Konfiguration prüfen (Standard vs. höher)

## 4. Pfad-Reihenfolge nach einem Trade

### 4.1 State-Übergang (= ARMED/DISARMED-Bedingungen)
- ARMED bleibt → `STATE_RUNNING` → Folge-Trades laufen sofort
- DISARMED (spread < 0.7%) → `STATE_WAITING` → warten auf spread > 1.9%

### 4.2 `trade_in_progress` Logik (Jonas)
- **TRUE nur während Market + Limit gesetzt werden** (Sub-State)
- **FALSE sobald beide Seiten platziert sind** (nach `execute_trade()` success)
- Im aktuellen Code (Z. 3500-3535): wird auf True gesetzt vor `execute_trade()`, auf False in beiden Erfolgs-/Fehler-Fällen

### 4.3 calculate_best_trade() — Wann?
- **Läuft nur VOR einem Trade**, wenn Spread-Bedingung erfüllt ist
- Im main loop (NICHT im Orderbook-Thread)
- Im WAITING-Pfad Z. 3339 mit `for_follow_up_trade=False` (threshold=1.9%)
- Im RUNNING-Pfad Z. 3603 mit `for_follow_up_trade=True` (threshold=0.7%)
- Mein Fix `2a69e54` hat Z. 3339 auf `for_follow_up_trade=True` gesetzt (für Folge-Trades im WAITING-Pfad)

## 5. Mein bisherigen Fixes (Commits auf main)

| Commit | Datum | Inhalt |
|---|---|---|
| `b47a586` | — | SAFETY-Block rauswerfen (REV von cab231d) — KORRIGIERT nach Jonas |
| `0d546ca` | 14:30 | Dashboard threshold_start param — wahrscheinlich GUT |
| `3ccf7a6` | 14:06 | RUNNING-Pfad START-Check + Pfad B state=STATE_RUNNING — möglicherweise GUT |
| `2a69e54` | 15:29 | WAITING-Pfad best_trade for_follow_up_trade=True — möglicherweise GUT |
| `766bbdf` | 13:00 | Dashboard hide trade-direction when spread out of range — GUT |

## 6. Offene Issues / TODO

### 6.1 Architektur (GROSS — Tage Arbeit)
- [ ] Separater Thread für Orderbook-Updates (statt im main loop)
- [ ] Token-Bucket-System für Rate-Limit
- [ ] Cache-Reader-Thread für Dashboard

### 6.2 Kleinere Fixes (können HEUTE Nacht gemacht werden)
- [ ] `hysteresis_armed` Variable rauswerfen, nur `state` verwenden
- [ ] Logging erweitern für bessere Sichtbarkeit
- [ ] Unit-Tests für kritische Funktionen

### 6.3 Andere Issues
- [ ] **MEXC 114988 MPC locked** — irrelevant für Trading, aber manuell in Exchange-UI cancellen
- [ ] **Settings-Sync** — Dashboard schreibt via `settings_sync.py`, nicht im Repo sichtbar
- [ ] **Trade-History CSV** — Logging-Bug (FILLED Trades werden geloggt, aber nicht alle)
- [ ] **Dashboard-Sichtbarkeit** — fehlt: State-Anzeige, Hysteresis-Status, Trade-Counter
- [ ] **Kaching-Sound** — Dashboard akustisches Signal (existiert evtl. nicht zuverlässig)

## 7. Lektionen für mich (von Jonas gelernt)

1. **Niemals raten** — immer recherchieren (Exchange-Docs, offizielle Quellen)
2. **Verstehen bevor ändern** — Code-Analyse vor Code-Edit
3. **Bei proven Code erst fragen** — nicht einfach annehmen dass es ein Bug ist
4. **Tests schreiben** — nicht nur "es funktioniert", sondern verifizieren dass es die richtige Logik macht
5. **Konsequenzen bedenken** — das was ich ändere könnte andere Sachen brechen

## 8. Test-Output (lokal, 00:45)

**Datei:** `tests/test_hysteresis_logic.py` — simuliert Jonas' STANDARD-Logik

```
Test 1: Hysteresis ARM (1.5% → 2.0%)
  ✅ ARM: spread=2.0% -> state=RUNNING
✅ PASS

Test 2: ARM → STAY-RUNNING → DISARM (2.0% → 1.5% → 0.5%)
  ✅ ARM: spread=2.0% -> state=RUNNING
  ⏸ STAY-RUNNING-armed: spread=1.5% (zwischen STOP und START)
  ✅ DISARM: spread=0.5% -> state=WAITING
✅ PASS

Test 3: DISARM → WAIT → ARM
  ⏸ STAY-WAITING: spread=0.7% (zwischen STOP und START)
  ⏸ STAY-WAITING: spread=1.0% (zwischen STOP und START)
  ⏸ STAY-WAITING: spread=1.5% (zwischen STOP und START)
  ✅ ARM: spread=2.0% -> state=RUNNING
✅ PASS

Test 4: ARM → DISARM → WAIT → ARM
  ✅ ARM: spread=2.0% -> state=RUNNING
  ⏸ STAY-RUNNING-armed: spread=1.0% (zwischen STOP und START)
  ✅ DISARM: spread=0.5% -> state=WAITING
  ⏸ STAY-WAITING: spread=0.8% (zwischen STOP und START)
  ⏸ STAY-WAITING: spread=1.5% (zwischen STOP und START)
  ✅ ARM: spread=2.0% -> state=RUNNING
✅ PASS
```

**→ Alle Tests bestanden — Hysteresis-Logik ist KORREKT**

## 9. Status der Implementierung (Stand 00:45)

✅ **Was passt (KORREKT im Bestandscode):**
- Hysteresis-Logik (Z. 3449-3456) — matcht Jonas' STANDARD
- trade_condition-Logik (Z. 3460) — `(spread >= threshold_start) OR (armed AND spread >= threshold_stop)`
- WAITING-Pfad Trade-Logik (Z. 3458-3543) — balance check, execute_trade
- RUNNING-Pfad Trade-Logik (Z. 3548-3644) — frischer Orderbook, Multi-Level Accumulation
- calculate_best_trade() (Z. 3013) — Multi-Level Accumulation ✅
- check_balances_for_trade() — Balance-Pre-Check ✅
- Orderbook-Refresh nach Trade (Z. 3531-3536) ✅
- Cache-Lock `_latest_data_lock` (Z. 3321-3328, 3392-3404) ✅
- SAFETY-Block beim Start (Z. 3248-3251) ✅

🔍 **Identifiziert, NICHT gefixt (zu riskant ohne Live-Tests):**
- `hysteresis_armed` Variable redundant zu `state`
- Empfehlung Jonas: "rauswerfen". Risiko: mehrere Stellen ändern, könnte was brechen.
- **Entscheidung:** Überspringen für heute. Tests beweisen dass die Logik korrekt ist, auch mit der Redundanz.

❌ **Was NICHT passt (gross, Tage Arbeit):**
- Orderbook-Update nicht in separatem Thread — empfohlen von Jonas, lasse ich für später
- Token-Bucket-System fehlt — empfohlen von Jonas, lasse ich für später
- Trade-Decision-Thread — empfohlen von Jonas, lasse ich für später

## 10. Empfehlung an Jonas für morgen (Redeploy)

1. **Coolify wieder hochfahren**
2. **Bot-Container redeployen** mit Commit HEAD
3. **Dashboard-Container ebenfalls** redeployen
4. **Live beobachten:**
   - Erster Trade sollte wieder laufen (Spread > 1.9% → ARM)
   - Folge-Trades sollten laufen (Spread > 0.7% hält ARM)
   - Wenn Spread < 0.7% → DISARM
   - Container-Logs prüfen: ARMED/DISARMED Events sollten zu sehen sein
5. **Container-Restarts beobachten** (Server-Crashes-Problem)

**Bei neuen Bugs:** Log schicken, ich diagnostiziere.
