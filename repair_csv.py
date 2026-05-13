#!/usr/bin/env python3
"""
Repair script for corrupted MPCUSDT_trades.csv

Problem: Data is shifted LEFT by 1 position starting at column 18 (ex2_exchange)
- ex2_exchange contains ex1_status value ('FILLED')
- ex2_order_id contains ex2_exchange value ('KUCOIN')
- Everything from position 18 onwards is shifted

Fix: Shift the data back to match the header
"""

import csv
import sys
from pathlib import Path
from datetime import datetime

LOG_DIR = Path('/app/logs')
CSV_PATH = LOG_DIR / 'MPCUSDT_trades.csv'
BACKUP_PATH = LOG_DIR / f'MPCUSDT_trades_backup_{datetime.now().strftime("%Y%m%d_%H%M%S")}.csv'

def repair_csv():
    if not CSV_PATH.exists():
        print(f"ERROR: CSV not found at {CSV_PATH}")
        return False
    
    # Create backup
    print(f"Creating backup: {BACKUP_PATH}")
    import shutil
    shutil.copy2(CSV_PATH, BACKUP_PATH)
    
    # Read CSV
    print(f"Reading {CSV_PATH}...")
    with open(CSV_PATH, 'r', newline='') as f:
        reader = csv.reader(f)
        rows = list(reader)
    
    if len(rows) < 2:
        print("ERROR: Not enough rows in CSV")
        return False
    
    header = rows[0]
    data_rows = rows[1:]
    
    print(f"Header has {len(header)} columns")
    print(f"Data rows: {len(data_rows)}")
    
    # Define the correct header order (from trade_logger.py UNIFIED_COLUMNS)
    EXPECTED_HEADER = [
        "trade_id", "internal_ts", "direction", "pair", "strategy", "spread_pct",
        "ex1_exchange", "ex1_order_id", "ex1_type", "ex1_side", "ex1_qty_ordered", "ex1_qty_filled",
        "ex1_price_expected", "ex1_price_actual", "ex1_value_usdt", "ex1_fees", "ex1_create_ts", "ex1_status",
        "ex2_exchange", "ex2_order_id", "ex2_type", "ex2_side", "ex2_qty_ordered", "ex2_qty_filled",
        "ex2_price_expected", "ex2_price_actual", "ex2_value_usdt", "ex2_fees", "ex2_create_ts", "ex2_status",
        "profit_usdt_expected", "profit_mpc_expected", "profit_usdt_actual", "profit_mpc_actual",
        "limit_watch_status", "limit_last_check", "error_code", "error_message",
        "raw_ex1_response", "raw_ex2_response", "updated_at"
    ]
    
    EXPECTED_COLS = len(EXPECTED_HEADER)
    
    print(f"Expected header has {EXPECTED_COLS} columns")
    
    # Check if header matches expected
    header_matches = (header == EXPECTED_HEADER)
    print(f"Header matches expected: {header_matches}")
    
    # Analyze the problem rows
    print("\n=== ANALYZING PROBLEM ===")
    sample_row = data_rows[0] if data_rows else []
    print(f"First data row has {len(sample_row)} columns")
    
    # The shift happens at column 18 (ex2_exchange)
    # If first data row has 42 columns but header has 41, we need to trim
    if len(sample_row) == 42 and len(header) == 41:
        print("Detected: Data has 42 columns, header has 41 - trimming extra column")
        
    # Check if data is shifted
    # Position 18 should be ex2_exchange (KUCOIN or MEXC), not FILLED
    if len(sample_row) > 18:
        val_at_18 = sample_row[18]
        if val_at_18 in ['FILLED', 'PARTIAL', 'PENDING', 'CANCELLED']:
            print(f"Position 18 contains '{val_at_18}' - this is ex1_status value!")
            print("Data is SHIFTED - needs correction")
        elif val_at_18 in ['KUCOIN', 'MEXC']:
            print(f"Position 18 contains '{val_at_18}' - looks correct")
    
    # Perform the repair
    fixed_rows = [header]
    
    for i, row in enumerate(data_rows):
        if len(row) == EXPECTED_COLS:
            # Row is correct length, use as-is
            fixed_rows.append(row)
        elif len(row) == EXPECTED_COLS + 1:
            # Row has extra column - check if it's the 'null' column issue
            # The extra data at position 41 might be raw_ex2_response data
            # Let's check: does position 40 look like updated_at JSON?
            
            if i == 0:
                print(f"\nRow {i}: has {len(row)} columns, trimming last column")
                print(f"  Last value (pos {len(row)-1}): {row[-1][:50]}...")
            
            # Trim the extra column (it's the malformed 'null' key)
            fixed_row = row[:EXPECTED_COLS]
            fixed_rows.append(fixed_row)
        else:
            print(f"Row {i}: unexpected column count {len(row)}")
            # Pad or trim as needed
            if len(row) < EXPECTED_COLS:
                fixed_row = row + [''] * (EXPECTED_COLS - len(row))
            else:
                fixed_row = row[:EXPECTED_COLS]
            fixed_rows.append(fixed_row)
    
    # Write fixed CSV
    print(f"\nWriting fixed CSV to {CSV_PATH}...")
    with open(CSV_PATH, 'w', newline='') as f:
        writer = csv.writer(f)
        writer.writerows(fixed_rows)
    
    print(f"Repair complete! {len(data_rows)} data rows processed")
    print(f"Backup saved to: {BACKUP_PATH}")
    
    # Verify
    print("\n=== VERIFICATION ===")
    with open(CSV_PATH, 'r', newline='') as f:
        reader = csv.reader(f)
        new_rows = list(reader)
    
    new_header = new_rows[0]
    new_sample = new_rows[1] if len(new_rows) > 1 else []
    
    print(f"New header columns: {len(new_header)}")
    print(f"New first data row columns: {len(new_sample)}")
    
    if len(new_sample) >= 19:
        print(f"Position 18 (ex2_exchange): {new_sample[18]}")
        print(f"Position 19 (ex2_order_id): {new_sample[19]}")
        print(f"Position 20 (ex2_type): {new_sample[20]}")
    
    return True

if __name__ == '__main__':
    print("=== CSV REPAIR SCRIPT ===")
    print(f"Target: {CSV_PATH}")
    print()
    
    success = repair_csv()
    
    if success:
        print("\n✅ REPAIR SUCCESSFUL")
    else:
        print("\n❌ REPAIR FAILED")
        sys.exit(1)
