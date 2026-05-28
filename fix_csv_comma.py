#!/usr/bin/env python3
"""
Fix MPCUSDT_trades_edit2.csv
- Replace German comma decimals with points
- Fix any structural issues
"""

import csv
import json
from pathlib import Path

INPUT = "/home/openclaw/.openclaw/media/inbound/MPCUSDT_trades_edit2---53bf64bb-3f81-4daf-a690-67036f656c15.csv"
OUTPUT = "/home/openclaw/.openclaw/workspace/trading/arbitrage-bot/logs/MPCUSDT_trades.csv"

def to_float(val):
    """Convert German decimal to float"""
    if not val or val == '':
        return 0.0
    return float(str(val).replace(',', '.'))

def format_float(val, decimals=6):
    """Format float with German comma decimal"""
    if val == 0:
        return ''
    return f"{val:.{decimals}f}".replace('.', ',')

def format_qty(val):
    """Format quantity with 2 decimals and German comma"""
    if val == 0:
        return ''
    return f"{val:.2f}".replace('.', ',')

def format_usdt(val):
    """Format USDT value with 6 decimals and German comma"""
    if val == 0:
        return ''
    return f"{val:.6f}".replace('.', ',')

# Columns that use German comma
COMMA_COLS = [10, 11, 12, 13, 14, 15, 22, 23, 24, 25, 26, 27, 30, 31, 32, 33]

with open(INPUT, 'r') as f:
    reader = csv.reader(f, delimiter=';')
    header = next(reader)
    rows = list(reader)

print(f"Loaded {len(rows)} rows")

# Fix and write
fixed = 0
with open(OUTPUT, 'w', newline='') as f:
    writer = csv.writer(f, delimiter=';')
    writer.writerow(header)
    
    for row in rows:
        new_row = list(row)
        
        # Fix comma decimals in numeric columns
        for i in COMMA_COLS:
            if i < len(row) and row[i] and ',' in row[i]:
                # Convert to float then back with point
                val = to_float(row[i])
                if val != 0:
                    # Keep original precision
                    if i in [10, 11, 22, 23]:  # Quantities - 2 decimals
                        new_row[i] = f"{val:.2f}".replace('.', ',')
                    elif i in [26, 27]:  # USDT values - 6 decimals
                        new_row[i] = f"{val:.6f}".replace('.', ',')
                    else:  # Prices - 6 decimals
                        new_row[i] = f"{val:.6f}".replace('.', ',')
                else:
                    new_row[i] = ''
        
        writer.writerow(new_row)
        fixed += 1

print(f"Written {fixed} rows to {OUTPUT}")

# Verify
print("\n=== VERIFICATION ===")
with open(OUTPUT, 'r') as f:
    reader = csv.reader(f, delimiter=';')
    header = next(reader)
    
    comma_count = 0
    for row in reader:
        if row[11] and ',' in row[11]:
            comma_count += 1
    
    print(f"Rows with comma in ex1_qty_filled: {comma_count} (should be 0)")
    
    # Check first few rows
    f.seek(0)
    next(reader)
    for i, row in enumerate(reader):
        if i < 3:
            print(f"\n{row[0]}:")
            print(f"  ex1_qty_filled: {row[11]}")

print("\n=== DONE ===")
print(f"Fixed CSV written to: {OUTPUT}")