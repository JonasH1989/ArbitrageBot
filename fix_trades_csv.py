#!/usr/bin/env python3
"""
Fix MPCUSDT_trades.csv according to new structure
- ex1_qty_ordered = EMPTY in _ex1pN rows
- ex2_qty_ordered = EMPTY in _ex2pN rows  
- profit_mpc_expected = ex1_qty_filled - ex2_qty_ordered (only in _ex2sum)
- profit_mpc_actual = ex1_qty_filled - ex2_qty_filled (only when FILLED)
"""

import csv
from datetime import datetime
from pathlib import Path

INPUT_FILE = "/home/openclaw/.openclaw/media/inbound/MPCUSDT_trades_edit---39120646-221a-46e5-bc21-5e22244c3443.csv"
OUTPUT_FILE = "/home/openclaw/.openclaw/workspace/trading/arbitrage-bot/logs/MPCUSDT_trades.csv"

def to_float(val):
    """Convert string to float, handling comma decimal separator"""
    if val is None or val == '':
        return 0.0
    s = str(val).strip()
    if s == '' or s == 'None':
        return 0.0
    s = s.replace(',', '.')
    try:
        return float(s)
    except:
        return 0.0

def process_csv():
    """Process the CSV and fix all issues"""
    
    rows = []
    with open(INPUT_FILE, 'r', newline='', encoding='utf-8') as f:
        reader = csv.reader(f, delimiter=';')
        header = next(reader)
        for row in reader:
            rows.append(row)
    
    print(f"Loaded {len(rows)} rows from CSV")
    
    # Group rows by trade base ID
    trades = {}
    for row in rows:
        tid = row[0]
        
        # Determine base trade_id and row type
        if '_ex1p' in tid:
            base_id = tid.rsplit('_ex1p', 1)[0]
        elif '_ex2p' in tid:
            base_id = tid.rsplit('_ex2p', 1)[0]
        elif '_ex2sum' in tid:
            base_id = tid.rsplit('_ex2sum', 1)[0]
        elif '_ex1sum' in tid:
            base_id = tid.rsplit('_ex1sum', 1)[0]
        else:
            base_id = tid
        
        if base_id not in trades:
            trades[base_id] = {}
        
        # Store by type
        if tid == base_id:
            trades[base_id]['main'] = row
        elif tid.endswith('_ex2sum'):
            trades[base_id]['ex2sum'] = row
        elif '_ex1p' in tid:
            trades[base_id]['ex1p'] = row
        elif '_ex2p' in tid:
            if 'ex2p' not in trades[base_id]:
                trades[base_id]['ex2p'] = []
            trades[base_id]['ex2p'].append(row)
    
    print(f"Found {len(trades)} unique trades")
    
    # Now fix each row
    fixed_rows = []
    for row in rows:
        tid = row[0]
        
        # Determine row type
        if '_ex1p' in tid:
            row_type = '_ex1pN'
        elif '_ex2p' in tid:
            row_type = '_ex2pN'
        elif '_ex2sum' in tid:
            row_type = '_ex2sum'
        elif '_ex1sum' in tid:
            row_type = '_ex1sum'
        else:
            row_type = 'main'
        
        # Make mutable
        row = list(row)
        
        if row_type == '_ex1pN':
            # ex1_qty_ordered = EMPTY in ex1 partial rows
            row[10] = ''
            
        elif row_type == '_ex2pN':
            # ex2_qty_ordered = EMPTY in ex2 partial rows
            row[22] = ''
            
        elif row_type == '_ex2sum':
            # Get base trade to find ex1_qty_filled
            base_id = tid.rsplit('_ex2sum', 1)[0]
            main_row = trades.get(base_id, {}).get('main', None)
            
            ex1_qty_filled = 0.0
            if main_row:
                ex1_qty_filled = to_float(main_row[11])  # ex1_qty_filled in main row
            
            ex2_qty_ordered = to_float(row[22]) if row[22] else 0.0
            ex2_qty_filled = to_float(row[23]) if row[23] else 0.0
            
            # profit_mpc_expected = ex1_qty_filled - ex2_qty_ordered
            profit_mpc_expected = ex1_qty_filled - ex2_qty_ordered
            row[31] = str(profit_mpc_expected).replace('.', ',')
            
            # profit_mpc_actual = only when FILLED
            limit_status = row[34].strip() if row[34] else ''
            if limit_status == 'FILLED' and ex2_qty_filled > 0:
                profit_mpc_actual = ex1_qty_filled - ex2_qty_filled
                row[33] = str(profit_mpc_actual).replace('.', ',')
            else:
                row[33] = ''  # Clear if not FILLED
        
        fixed_rows.append(row)
    
    # Write output
    with open(OUTPUT_FILE, 'w', newline='', encoding='utf-8') as f:
        writer = csv.writer(f, delimiter=';')
        writer.writerow(header)
        writer.writerows(fixed_rows)
    
    print(f"Written {len(fixed_rows)} rows to {OUTPUT_FILE}")
    
    # Verify a specific trade
    with open(OUTPUT_FILE, 'r') as f:
        reader = csv.reader(f, delimiter=';')
        header = next(reader)
        for row in reader:
            if row[0] == '1bec1e1f_ex2sum':
                print(f"\nVerification - 1bec1e1f_ex2sum:")
                print(f"  ex2_qty_ordered (22): {row[22]}")
                print(f"  profit_mpc_expected (31): {row[31]}")
                print(f"  profit_mpc_actual (33): {row[33]}")
                print(f"  limit_watch_status (34): {row[34]}")
                break
    
    # Statistics
    main_count = len([r for r in fixed_rows if not any(s in r[0] for s in ['_ex1p', '_ex2p', '_ex2sum', '_ex1sum'])])
    watching_count = len([r for r in fixed_rows if r[34] == 'WATCHING'])
    filled_count = len([r for r in fixed_rows if r[34] == 'FILLED'])
    
    print(f"\nStatistics:")
    print(f"  Main trades: {main_count}")
    print(f"  WATCHING: {watching_count}")
    print(f"  FILLED: {filled_count}")

if __name__ == '__main__':
    process_csv()