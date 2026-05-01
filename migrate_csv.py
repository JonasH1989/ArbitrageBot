#!/usr/bin/env python3
"""
Migrate old 31-column trade CSV to new 41-column format.
Old format was missing: strategy, spread_pct, price_expected/price_actual, 
profit fields, error_code, error_message
"""
import csv
import sys
import json
from datetime import datetime

def migrate_csv(csv_path: str) -> int:
    """Migrate old 31-column format to new 41-column format.
    
    Returns number of rows migrated.
    """
    
    # Old 31-column header (in order)
    old_header = [
        'trade_id', 'internal_ts', 'direction', 'pair', 'ex1_exchange', 'ex1_order_id',
        'ex1_type', 'ex1_side', 'ex1_qty_ordered', 'ex1_qty_filled', 'ex1_price_avg',
        'ex1_value_usdt', 'ex1_fees', 'ex1_create_ts', 'ex1_status', 'ex2_exchange',
        'ex2_order_id', 'ex2_type', 'ex2_side', 'ex2_qty_ordered', 'ex2_qty_filled',
        'ex2_price_avg', 'ex2_value_usdt', 'ex2_fees', 'ex2_create_ts', 'ex2_status',
        'limit_watch_status', 'limit_last_check', 'raw_ex1_response', 'raw_ex2_response',
        'updated_at'
    ]
    
    # New 41-column header (from UNIFIED_COLUMNS in trade_logger.py)
    new_header = [
        'trade_id', 'internal_ts', 'direction', 'pair', 'strategy', 'spread_pct',
        'ex1_exchange', 'ex1_order_id', 'ex1_type', 'ex1_side', 'ex1_qty_ordered',
        'ex1_qty_filled', 'ex1_price_expected', 'ex1_price_actual', 'ex1_value_usdt',
        'ex1_fees', 'ex1_create_ts', 'ex1_status', 'ex2_exchange', 'ex2_order_id',
        'ex2_type', 'ex2_side', 'ex2_qty_ordered', 'ex2_qty_filled', 'ex2_price_expected',
        'ex2_price_actual', 'ex2_value_usdt', 'ex2_fees', 'ex2_create_ts', 'ex2_status',
        'profit_usdt_expected', 'profit_mpc_expected', 'profit_usdt_actual', 'profit_mpc_actual',
        'limit_watch_status', 'limit_last_check', 'error_code', 'error_message',
        'raw_ex1_response', 'raw_ex2_response', 'updated_at'
    ]
    
    # Read old data
    with open(csv_path, 'r', newline='') as f:
        reader = csv.DictReader(f, fieldnames=old_header)
        rows = list(reader)
    
    if not rows:
        print(f"No data rows in {csv_path}")
        return 0
    
    # Check if already migrated (has strategy column)
    if 'strategy' in rows[0]:
        print(f"CSV already migrated (has strategy column)")
        return 0
    
    # Migrate each row
    migrated = []
    for row in rows:
        new_row = {}
        
        # Copy known fields
        new_row['trade_id'] = row.get('trade_id', '')
        new_row['internal_ts'] = row.get('internal_ts', '')
        new_row['direction'] = row.get('direction', '')
        new_row['pair'] = row.get('pair', '')
        
        # New fields (default to empty/0)
        new_row['strategy'] = ''
        new_row['spread_pct'] = 0
        
        # ex1 fields
        new_row['ex1_exchange'] = row.get('ex1_exchange', '')
        new_row['ex1_order_id'] = row.get('ex1_order_id', '')
        new_row['ex1_type'] = row.get('ex1_type', '')
        new_row['ex1_side'] = row.get('ex1_side', '')
        new_row['ex1_qty_ordered'] = row.get('ex1_qty_ordered', 0)
        new_row['ex1_qty_filled'] = row.get('ex1_qty_filled', 0)
        # Map old ex1_price_avg to ex1_price_actual, set ex1_price_expected to 0
        new_row['ex1_price_expected'] = 0
        new_row['ex1_price_actual'] = row.get('ex1_price_avg', 0)
        new_row['ex1_value_usdt'] = row.get('ex1_value_usdt', 0)
        new_row['ex1_fees'] = row.get('ex1_fees', 0)
        new_row['ex1_create_ts'] = row.get('ex1_create_ts', 0)
        new_row['ex1_status'] = row.get('ex1_status', '')
        
        # ex2 fields
        new_row['ex2_exchange'] = row.get('ex2_exchange', '')
        new_row['ex2_order_id'] = row.get('ex2_order_id', '')
        new_row['ex2_type'] = row.get('ex2_type', '')
        new_row['ex2_side'] = row.get('ex2_side', '')
        new_row['ex2_qty_ordered'] = row.get('ex2_qty_ordered', 0)
        new_row['ex2_qty_filled'] = row.get('ex2_qty_filled', 0)
        # Map old ex2_price_avg to ex2_price_actual, set ex2_price_expected to 0
        new_row['ex2_price_expected'] = 0
        new_row['ex2_price_actual'] = row.get('ex2_price_avg', 0)
        new_row['ex2_value_usdt'] = row.get('ex2_value_usdt', 0)
        new_row['ex2_fees'] = row.get('ex2_fees', 0)
        new_row['ex2_create_ts'] = row.get('ex2_create_ts', 0)
        new_row['ex2_status'] = row.get('ex2_status', '')
        
        # Profit fields (default)
        new_row['profit_usdt_expected'] = 0
        new_row['profit_mpc_expected'] = 0
        new_row['profit_usdt_actual'] = 0
        new_row['profit_mpc_actual'] = 0
        
        # Limit watch
        new_row['limit_watch_status'] = row.get('limit_watch_status', '')
        new_row['limit_last_check'] = row.get('limit_last_check', '')
        
        # Error fields (default)
        new_row['error_code'] = ''
        new_row['error_message'] = ''
        
        # Raw responses
        new_row['raw_ex1_response'] = row.get('raw_ex1_response', '{}')
        new_row['raw_ex2_response'] = row.get('raw_ex2_response', '{}')
        new_row['updated_at'] = row.get('updated_at', datetime.now().isoformat())
        
        migrated.append(new_row)
    
    # Write new CSV
    with open(csv_path, 'w', newline='') as f:
        writer = csv.DictWriter(f, fieldnames=new_header)
        writer.writeheader()
        writer.writerows(migrated)
    
    return len(migrated)


if __name__ == '__main__':
    if len(sys.argv) > 1:
        csv_path = sys.argv[1]
    else:
        csv_path = '/home/openclaw/.openclaw/logs/MPC-USDT_trades.csv'
    
    count = migrate_csv(csv_path)
    print(f"Migrated {count} rows to new 41-column format")