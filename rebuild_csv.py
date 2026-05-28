#!/usr/bin/env python3
"""
Rebuild MPCUSDT_trades.csv with correct fills from MEXC API.
Preserves original ex2 data, only fixes ex1 fills from MEXC myTrades.
"""

import requests
import hmac
import hashlib
import time
import csv
from datetime import datetime

# MEXC API credentials
MEXC_KEY = "mx0vglBgOfyggoJe3I"
MEXC_SECRET = "4d15399a840d494b9a308534f9cf7907"

INPUT = "/home/openclaw/.openclaw/media/inbound/MPCUSDT_trades_edit2---466b916f-fd3c-4bbd-8524-09653e4e5647.csv"
OUTPUT = "/home/openclaw/.openclaw/workspace/trading/arbitrage-bot/logs/MPCUSDT_trades.csv"

def to_float(val):
    if not val or val == '':
        return 0.0
    return float(str(val).replace(',', '.'))

def fmt(val, decimals=2):
    if val == 0:
        return ''
    return f"{val:.{decimals}f}".replace('.', ',')

def fmt_price(val):
    if val == 0:
        return ''
    return f"{val:.6f}".replace('.', ',')

def get_base_id(tid):
    """Extract base trade ID from any row type"""
    if '_ex1p' in tid:
        return tid.rsplit('_ex1p', 1)[0]
    elif '_ex2p' in tid:
        return tid.rsplit('_ex2p', 1)[0]
    elif '_ex2sum' in tid:
        return tid.rsplit('_ex2sum', 1)[0]
    else:
        return tid

def fix_decimals(row):
    """Fix decimal format in a row (comma instead of period)"""
    fixed = list(row)
    # Columns that should have decimal format
    decimal_cols = [10, 11, 12, 13, 14, 15, 22, 23, 24, 25, 26, 27, 30, 31, 32, 33]
    for col in decimal_cols:
        if col < len(fixed) and fixed[col]:
            if '.' in str(fixed[col]):
                fixed[col] = str(fixed[col]).replace('.', ',')
    return fixed

# Read all rows
with open(INPUT, 'r') as f:
    reader = csv.reader(f, delimiter=';')
    header = next(reader)
    input_rows = list(reader)

print(f"Input: {len(input_rows)} rows")

# Group trades by base ID
trades = {}
for row in input_rows:
    tid = row[0]
    if not tid or tid.strip() == '':
        continue
    
    base_id = get_base_id(tid)
    
    if base_id not in trades:
        trades[base_id] = {
            'main': None, 
            'ex1p': [], 
            'ex2sum': None, 
            'ex2p': [], 
            'fills': [],
            'order_id': None
        }
    
    if tid == base_id:
        trades[base_id]['main'] = list(row)
        # Extract order_id from main row
        if len(row) > 7:
            trades[base_id]['order_id'] = row[7]
    elif '_ex2sum' in tid:
        trades[base_id]['ex2sum'] = list(row)
    elif '_ex1p' in tid:
        trades[base_id]['ex1p'].append(list(row))
    elif '_ex2p' in tid:
        trades[base_id]['ex2p'].append(list(row))

print(f"Grouped into {len(trades)} trades")

# Query MEXC for partial orders with multiple fills
partial_order_ids = [
    ('1b1611d4e', 'C02__688414456513777664119'),
    ('1b16111d31', 'C02__688414521529683969119'),
    ('1b1611211e', 'C02__688414538755608579119'),
    ('1b16113062', 'C02__688414602798489601119'),
    ('1b16113647', 'C02__688414627339358208119'),
    ('1b16122f50', 'C02__688414850790903809119'),
    ('1b16181516', 'C02__688416249486381056119'),
    ('1b161c2c27', 'C02__688417353221672960119'),
    ('1c8252130', 'C02__688570566356905984119'),
    ('1c8252549', 'C02__688570583591292928119'),
    ('1c825365e', 'C02__688570656337301504119'),
    ('1cb36f01', 'C02__688620065544654849119'),
    ('1cb361254', 'C02__688620082586062848119'),
]

print("\n=== Querying MEXC myTrades ===")

for trade_id, order_id in partial_order_ids:
    ts = str(int(time.time() * 1000))
    params = f'symbol=MPCUSDT&orderId={order_id}&timestamp={ts}'
    sig = hmac.new(MEXC_SECRET.encode('utf-8'), params.encode('utf-8'), hashlib.sha256).hexdigest()
    
    url = f'https://api.mexc.com/api/v3/myTrades?{params}&signature={sig}'
    headers = {'X-MEXC-APIKEY': MEXC_KEY}
    
    try:
        resp = requests.get(url, headers=headers, timeout=10)
        data = resp.json()
        
        if resp.status_code == 200 and isinstance(data, list):
            fills = []
            for t in data:
                fills.append({
                    'qty': float(t.get('qty', 0)),
                    'price': float(t.get('price', 0)),
                    'value': float(t.get('quoteQty', 0)),
                    'fees': float(t.get('commission', 0)),
                    'time': int(t.get('time', 0)),
                })
            
            if trade_id in trades:
                trades[trade_id]['fills'] = fills
                total = sum(f['qty'] for f in fills)
                print(f"{trade_id}: {len(fills)} fills, total={total:.2f} MPC")
    except Exception as e:
        print(f"{trade_id}: Error - {e}")

# Build output CSV preserving original structure
print("\n=== Rebuilding CSV ===")

output_rows = [header]

for trade_id, trade in trades.items():
    main = trade['main']
    if not main:
        print(f"WARNING: No main row for {trade_id}")
        continue
    
    # Calculate correct ex1_qty_filled from MEXC API fills
    fills = trade['fills']
    if fills:
        total_filled = sum(f['qty'] for f in fills)
    else:
        # Use original value
        total_filled = to_float(main[11])
    
    # Fix main row with correct totalFilled and decimal format
    main_row = fix_decimals(main)
    main_row[11] = fmt(total_filled)  # ex1_qty_filled
    main_row[17] = 'FILLED'  # ex1_status - if fills exist, order is FILLED
    
    # Add main row
    output_rows.append(main_row)
    
    # Handle ex1p rows - create from API fills
    if fills:
        # Clear old ex1p rows (they'll be replaced with correct ones)
        # Actually, we just add new ones - the old ones from input won't be included
        
        for i, fill in enumerate(fills):
            ex1p_row = [''] * len(header)
            ex1p_row[0] = f"{trade_id}_ex1p{i+1}"
            ex1p_row[11] = fmt(fill['qty'])  # ex1_qty_filled
            ex1p_row[13] = fmt_price(fill['price'])  # ex1_price_actual
            ex1p_row[14] = fmt(fill['value'], 6)  # ex1_value_usdt
            ex1p_row[15] = fmt(fill['fees'], 6)  # ex1_fees
            ts = datetime.fromtimestamp(fill['time'] / 1000)
            ex1p_row[16] = ts.strftime('%Y-%m-%d %H:%M:%S.000')
            ex1p_row[17] = 'FILLED'
            ex1p_row[18] = 'KCN'  # ex2 exchange
            output_rows.append(ex1p_row)
    else:
        # No fills from API - use original ex1p rows with decimals fixed
        for ex1p in trade['ex1p']:
            ex1p_row = fix_decimals(ex1p)
            output_rows.append(ex1p_row)
    
    # Keep original ex2sum row (with decimal fix)
    ex2sum = trade['ex2sum']
    if ex2sum:
        ex2sum_row = fix_decimals(ex2sum)
        
        # Recalculate profit_mpc_expected based on corrected total_filled
        ex2_qty_ordered = to_float(ex2sum_row[22])
        ex2_qty_filled = to_float(ex2sum_row[23])
        
        profit_mpc_expected = total_filled - ex2_qty_ordered
        ex2sum_row[31] = fmt(profit_mpc_expected)
        
        # Recalculate profit_mpc_actual if FILLED
        if ex2sum_row[34] == 'FILLED':
            profit_mpc_actual = total_filled - ex2_qty_filled
            ex2sum_row[33] = fmt(profit_mpc_actual)
        
        output_rows.append(ex2sum_row)
    
    # Keep original ex2p rows (with decimal fix)
    for ex2p in trade['ex2p']:
        ex2p_row = fix_decimals(ex2p)
        output_rows.append(ex2p_row)

# Write output
with open(OUTPUT, 'w', newline='') as f:
    writer = csv.writer(f, delimiter=';')
    for row in output_rows:
        writer.writerow(row)

print(f"\nWrote {len(output_rows)} rows to {OUTPUT}")

# Verify
print("\n=== VERIFICATION ===")
with open(OUTPUT, 'r') as f:
    reader = csv.reader(f, delimiter=';')
    next(reader)
    
    counts = {'main': 0, 'ex1p1': 0, 'ex1p2': 0, 'ex1p3': 0, 'ex2sum': 0, 'ex2p1': 0}
    
    for row in reader:
        tid = row[0]
        if tid.endswith('_ex1p1'):
            counts['ex1p1'] += 1
        elif tid.endswith('_ex1p2'):
            counts['ex1p2'] += 1
        elif tid.endswith('_ex1p3'):
            counts['ex1p3'] += 1
        elif tid.endswith('_ex2sum'):
            counts['ex2sum'] += 1
        elif tid.endswith('_ex2p1'):
            counts['ex2p1'] += 1
        elif '_' not in tid:
            counts['main'] += 1
    
    for k, v in counts.items():
        print(f"{k}: {v}")

print("\n=== DONE ===")