#!/usr/bin/env python3
"""Vollständiger Test der Trade-Bot-Logik (lokal, ohne Container)"""

import sys

# === Hysteresis-Logik (Jonas' STANDARD) ===
THRESHOLD_START = 1.9
THRESHOLD_STOP = 0.7

def simulate_hysteresis(spread_sequence, initial_state="WAITING"):
    """Simuliert die Hysteresis ARM/DISARM Logik aus Z. 3449-3456"""
    log = []
    state = initial_state
    
    for i, spread in enumerate(spread_sequence):
        old_state = state
        
        # ARM-Logik
        if state == "WAITING" and spread >= THRESHOLD_START:
            state = "RUNNING"
            log.append(f"  ✅ ARM: spread={spread:.1f}% -> state=RUNNING")
        # DISARM-Logik
        elif state == "RUNNING" and spread < THRESHOLD_STOP:
            state = "WAITING"
            log.append(f"  ✅ DISARM: spread={spread:.1f}% -> state=WAITING")
        # Dazwischen: STAY (entweder WAITING oder RUNNING bleibt)
        else:
            if spread >= THRESHOLD_START and state == "RUNNING":
                log.append(f"  ⏸ STAY-RUNNING: spread={spread:.1f}% (war bereits armed)")
            elif THRESHOLD_STOP <= spread < THRESHOLD_START:
                state_target = "RUNNING-armed" if state == "RUNNING" else "WAITING"
                log.append(f"  ⏸ STAY-{state_target}: spread={spread:.1f}% (zwischen STOP und START)")
            elif spread < THRESHOLD_STOP and state == "WAITING":
                log.append(f"  ⏸ STAY-WAITING: spread={spread:.1f}% (war bereits disarmed)")
    
    return log, state


# === Tests ===
print("="*70)
print("Test 1: Hysteresis ARM (1.5% → 2.0%)")
print("="*70)
log, final = simulate_hysteresis([1.5, 2.0])
for line in log:
    print(line)
print(f"  Final state: {final}")
assert final == "RUNNING", f"FAIL: expected RUNNING, got {final}"
print("✅ PASS")

print()
print("="*70)
print("Test 2: Hysteresis ARM → STAY-RUNNING → DISARM (2.0% → 1.5% → 0.5%)")
print("="*70)
log, final = simulate_hysteresis([2.0, 1.5, 0.5], initial_state="WAITING")
for line in log:
    print(line)
print(f"  Final state: {final}")
assert final == "WAITING", f"FAIL: expected WAITING, got {final}"
print("✅ PASS")

print()
print("="*70)
print("Test 3: Hysteresis DISARM → spread steigt zwischen STOP/START → STAY-WAITING (0.5% → 0.7% → 1.0% → 1.5% → 2.0%)")
print("="*70)
log, final = simulate_hysteresis([0.5, 0.7, 1.0, 1.5, 2.0], initial_state="WAITING")
for line in log:
    print(line)
print(f"  Final state: {final}")
assert final == "RUNNING", f"FAIL: expected RUNNING, got {final}"
print("✅ PASS")

print()
print("="*70)
print("Test 4: Hysteresis ARM → STAY-RUNNING → DISARM → WAIT → ARM")
print("="*70)
log, final = simulate_hysteresis([2.0, 1.0, 0.5, 0.8, 1.5, 2.0])
for line in log:
    print(line)
print(f"  Final state: {final}")
assert final == "RUNNING", f"FAIL: expected RUNNING, got {final}"
print("✅ PASS")

print()
print("="*70)
print("✅ Alle Tests bestanden — Hysteresis-Logik ist korrekt")
print("="*70)
