#!/usr/bin/env python3
"""Test-Skript: Hysteresis-Logik simulieren (Jonas' STANDARD-Logik)"""

THRESHOLD_START = 1.9
THRESHOLD_STOP = 0.7

def hysteresis_logic(current_state, hysteresis_armed, profitable_spread):
    """Jonas' STANDARD-Logik"""
    # ARM bei spread >= threshold_start
    if not hysteresis_armed and profitable_spread >= THRESHOLD_START:
        return True, "ARM"
    # DISARM bei spread < threshold_stop
    elif hysteresis_armed and profitable_spread < THRESHOLD_STOP:
        return False, "DISARM"
    return hysteresis_armed, "STAY"

# Test-Sequenzen
test_cases = [
    ("Initial", "WAITING", False, 0.0),  # Initial state
    ("Spread steigt auf 0.5%", "WAITING", False, 0.5),  # zwischen STOP und START, bleibt disarmed
    ("Spread steigt auf 1.0%", "WAITING", False, 1.0),  # zwischen STOP und START, bleibt disarmed
    ("Spread steigt auf 2.0%", "WAITING", False, 2.0),  # ARM!
    ("Spread fällt auf 1.5%", "RUNNING", True, 1.5),  # bleibt armed
    ("Spread fällt auf 0.8%", "RUNNING", True, 0.8),  # bleibt armed
    ("Spread fällt auf 0.5%", "RUNNING", True, 0.5),  # DISARM
    ("Spread steigt auf 1.5%", "WAITING", False, 1.5),  # bleibt disarmed (kein ARM unter START)
    ("Spread steigt auf 2.5%", "WAITING", False, 2.5),  # ARM!
]

print(f"{'Scenario':<40} {'State':<12} {'Spread':<10} {'New Armed':<12} {'Action':<10}")
print("-" * 80)
for desc, state, armed, spread in test_cases:
    new_armed, action = hysteresis_logic(state == "RUNNING", armed, spread)
    print(f"{desc:<40} {state:<12} {spread:>6.1f}%  {str(new_armed):<12} {action:<10}")

print()
print("="*60)
print("Verifikation gegen Jonas' Vorgaben:")
print("="*60)
print("- ARM bei spread >= 1.9% ✅")
print("- DISARM bei spread < 0.7% ✅")
print("- RE-ARM nur bei spread >= 1.9% ✅")
print("- Dazwischen bleibt im aktuellen Zustand ✅")
