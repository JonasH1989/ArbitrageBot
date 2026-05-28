#!/usr/bin/env python3
"""
Fix MPCUSDT_trades_edit2.csv - einheitliches German decimal format
"""

import csv

INPUT = "/home/openclaw/.openclaw/media/inbound/MPCUSDT_trades_edit2---53bf64bb-3f81-4daf-a690-67036f656c15.csv"
OUTPUT = "/home/openclaw/.openclaw/workspace/trading/arbitrage-bot/logs/MPCUSDT_trades.csv"

def to_float(val):
    """Convert German decimal to float"""
    if not val or val == '':
        return 0.0
    return float(str(val).replace(',', '.'))

with open(INPUT, 'r') as f:
    reader = csv.reader(f, delimiter=';')
    header = next(reader)
    rows = list(reader)

print(f"Loaded {len(rows)} rows")

with open(OUTPUT, 'w', newline='') as f:
    writer = csv.writer(f, delimiter=';')
    writer.writerow(header)
    
    for row in rows:
        new_row = list(row)
        
        # Fix decimal format issues ( Punkt → Komma für German)
        # Columns: 10,11,12,13,14,15,22,23,24,25,26,27,30,31,32,33
        for col in [10, 11, 12, 13, 14, 15, 22, 23, 24, 25, 26, 27, 30, 31, 32, 33]:
            if col < len(row):
                val = row[col]
                if val and '.' in str(val):
                    # Convert Punkt to Komma
                    new_val = str(val).replace('.', ',')
                    new_row[col] = new_val
        
        writer.writerow(new_row)

print(f"Written to {OUTPUT}")

# Verify
with open(OUTPUT, 'r') as f:
    reader = csv.reader(f, delimiter=';')
    header = next(reader)
    
    punkte = 0
    kommas = 0
    for row in reader:
        for col in [11, 23]:
            if col < len(row) and row[col]:
                if '.' in str(row[col]):
                    punkte += 1
                elif ',' in str(row[col]):
                    kommas += 1
    
    print(f"\nVerification:")
    print(f"  Werte mit PUNKT: {punkte} (sollte 0 sein)")
    print(f"  Werte mit KOMMA: {kommas}")

print("\n=== FERTIG ===")