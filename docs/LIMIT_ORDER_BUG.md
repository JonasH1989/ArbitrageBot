# Bug: Limit Order nicht platziert nach MEXC Market Order

## Datum: 2026-04-27

## Problem
Bei einem Trade wurde:
- MEXC Market Order (Sell ~133 MPC) ✅ ausgeführt
- KuCoin Limit Order → **NIEMALS platziert!**
- Keine cancelled Order, keine pending Order, keine ausgeführte Order

## chronology
1. Jonas setzt threshold auf 0.5%
2. Bot triggert Trade (M→K Direction)
3. Market Sell auf MEXC über ~133 MPC
4. Limit Buy auf KuCoin sollte folgen - passiert NICHT
5. Keine Spuren der KuCoin Order anywhere

## Mögliche Ursachen

### 1. MEXC Market Order Response Problem (VERMUTET)
- MEXC Market Orders sind **asynchron**
- Response enthält möglicherweise `qty_filled=0` oder `value_usdt=0` initially
- Code berechnet `sell_qty = value_usdt / sell_price`
- Wenn `value_usdt = 0` → `sell_qty = 0` → keine Order platziert!

### 2. Fehlerbehandlung
```python
# Aktuell im Code:
if result1.get('code') is None or 'orderId' in result1:
    # success
else:
    log(f"❌ MEXC Error: {result1}")
    return False, None
```
Mexc gibt bei Market Orders möglicherweise anderen ResponseCode!

## Debug Fix (commit 9c13b62)
```python
log(f"DEBUG MEXC Response: {result1}")
```
→ Zeigt die rohe Response vor der Verarbeitung

## Nächste Schritte
1. Code deployen (hat Jonas noch nicht gemacht als von 13:05)
2. Nächsten Trade abwarten
3. Coolify Logs checken für "DEBUG MEXC Response"
4. Prüfen was MEXC wirklich zurückgibt

## Code-Änderungen
- `arb_autotrade.py` - DEBUG logging für MEXC/KuCoin responses
- Commit: `9c13b62`

## Prüf-Punkte wenn Debug-Logs da sind
1. Was ist `result.code`? (erwartet: None oder nicht 0)
2. Was ist `orderId`? (sollte vorhanden sein)
3. Was ist `quantity` (filled qty)? (sollte > 0 sein)
4. Was ist `amount` (USD value)? (sollte > 0 sein)

## Falls Problem bestätigt
→ MEXC Market Order braucht Poll/Retry bis `quantity` > 0
→ Oder: Alternative MEXC API für synchrone Market Orders nutzen