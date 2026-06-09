#!/usr/bin/env python3
"""
Fix MPCUSDT_trades_fresh.csv - Apply replacement fills to cancelled trades
Simple approach: Update ex2p1 rows for the 5 cancelled trades with correct data
"""
import csv
import json
import hmac
import hashlib
import base64
import time
import requests
from datetime import datetime

# ============================================================
# KUCOIN API CREDENTIALS
# ============================================================
KUCOIN_KEY = "69e542868294a100018f076f"
KUCOIN_SECRET = "899189f7-e6fa-4ea4-ad0c-dfd43506ef30"
KUCOIN_PASSPHRASE = "6GEWzwgmfDyjgDk"

# ============================================================
# KUCOIN HELPER FUNCTIONS
# ============================================================
def kucoin_passphrase_enc(secret, passphrase):
    mac = hmac.new(secret.encode(), passphrase.encode(), hashlib.sha256)
    return base64.b64encode(mac.digest()).decode()

def kucoin_sig(secret, timestamp, method, path, body=''):
    message = f'{timestamp}{method}{path}{body}'
    return base64.b64encode(hmac.new(secret.encode(), message.encode(), hashlib.sha256).digest()).decode()

def kucoin_request(method, path, body=''):
    timestamp = str(int(time.time() * 1000))
    sig = kucoin_sig(KUCOIN_SECRET, timestamp, method, path, body)
    passphrase_enc = kucoin_passphrase_enc(KUCOIN_SECRET, KUCOIN_PASSPHRASE)
    headers = {
        'KC-API-KEY': KUCOIN_KEY,
        'KC-API-SIGN': sig,
        'KC-API-TIMESTAMP': timestamp,
        'KC-API-PASSPHRASE': passphrase_enc,
        'KC-API-KEY-VERSION': '2'
    }
    url = f'https://api.kucoin.com{path}'
    resp = requests.request(method, url, headers=headers, timeout=10)
    return resp.json()

# ============================================================
# REPLACEMENT ORDER DATA (from KuCoin API - verified)
# ============================================================
REPLACEMENT_FILLS = {
    '1b16113062': {'order_id': '6a1751979c8d050007ecf50d', 'filled': 33.0, 'price': 0.018941, 'value': 0.625053, 'fee': 0.001875159, 'created_at_ms': 1779913111512},
    '1b16113647': {'order_id': '6a1751910970a10007e9173d', 'filled': 68.0, 'price': 0.018935, 'value': 1.28758, 'fee': 0.00386274, 'created_at_ms': 1779913105052},
    '1b16122f50': {'order_id': '6a1751c530aa00000711dc0d', 'filled': 31.0, 'price': 0.018941, 'value': 0.587171, 'fee': 0.001761513, 'created_at_ms': 1779913157972},
    '1b16181516': {'order_id': '6a17578642a70a00075963c5', 'filled': 37.0, 'price': 0.019, 'value': 0.703, 'fee': 0.002109, 'created_at_ms': 1779914630060},
    '1b161c1e42': {'order_id': '6a17577e0970a10007fb714a', 'filled': 210.0, 'price': 0.019, 'value': 3.99, 'fee': 0.01197, 'created_at_ms': 1779914622090},
}

# ============================================================
# HELPER FUNCTIONS
# ============================================================
def ms_to_datetime_full(ts_ms):
    if ts_ms and int(ts_ms) > 0:
        return datetime.fromtimestamp(int(ts_ms)/1000).strftime('%Y-%m-%d %H:%M:%S.%f')[:-3]
    return ''

def ms_to_german(ts_ms):
    if ts_ms and int(ts_ms) > 0:
        return datetime.fromtimestamp(int(ts_ms)/1000).strftime('%d.%m.%Y %H:%M')
    return ''

def format_float_de(val, decimals=6):
    """Format float with German decimal separator"""
    if val is None or val == '' or val == 'None':
        return ''
    try:
        return str(round(float(val), decimals)).replace('.', ',')
    except:
        return ''

def parse_float(val):
    """Parse float from string with comma or dot"""
    if val is None or val == '':
        return 0.0
    if isinstance(val, (int, float)):
        return float(val)
    val = str(val).replace(',', '.').strip()
    try:
        return float(val)
    except:
        return 0.0

# ============================================================
# MAIN PROCESSING
# ============================================================
print("=" * 80)
print("FIXING MPCUSDT_trades_fresh.csv")
print("=" * 80)

# Read the fresh CSV
input_path = '/home/openclaw/.openclaw/workspace/trading/arbitrage-bot/MPCUSDT_trades_fresh.csv'
with open(input_path, 'r') as f:
    reader = csv.DictReader(f, delimiter=';')
    input_rows = list(reader)

print(f"Read {len(input_rows)} rows")

# Column names
cols = ['trade_id','internal_ts','direction','pair','strategy','spread_pct',
        'ex1','ex1_order_id','ex1_type','ex1_side','ex1_qty_ordered','ex1_qty_filled',
        'ex1_price_expected','ex1_price_actual','ex1_value_usdt','ex1_fees','ex1_create_ts','ex1_status',
        'ex2','ex2_order_id','ex2_type','ex2_side','ex2_qty_ordered','ex2_qty_filled',
        'ex2_price_expected','ex2_price_actual','ex2_value_usdt','ex2_fees','ex2_create_ts','ex2_status',
        'profit_usdt_expected','profit_mpc_expected','profit_usdt_actual','profit_mpc_actual',
        'limit_watch_status','limit_last_check','error_code','error_message',
        'raw_ex1_response','raw_ex2_response','raw_ex2_response_ts']

output_rows = []
output_rows.append(';'.join(cols))  # Header

# Track processed trades for ex1p2 rows
trades_with_ex1p2 = set()

for row in input_rows:
    trade_id = row.get('trade_id', '')
    
    # Check if this is a cancelled trade
    main_tid = trade_id.replace('_ex1p1', '').replace('_ex1p2', '').replace('_ex1p3', '').replace('_ex2sum', '').replace('_ex2p1', '').replace('_ex2p2', '')
    
    # Handle ex2p1 rows for cancelled trades
    if '_ex2p1' in trade_id and main_tid in REPLACEMENT_FILLS:
        repl = REPLACEMENT_FILLS[main_tid]
        
        # Update with replacement data
        row['ex2_order_id'] = repl['order_id']
        row['ex2_qty_filled'] = format_float_de(repl['filled'])
        row['ex2_price_actual'] = format_float_de(repl['price'])
        row['ex2_value_usdt'] = format_float_de(repl['value'])
        row['ex2_fees'] = format_float_de(repl['fee'])
        row['ex2_create_ts'] = ms_to_datetime_full(repl['created_at_ms'])
        row['ex2_status'] = 'FILLED'
        row['limit_watch_status'] = 'FILLED'
        
        print(f"✅ Fixed {trade_id}: {repl['filled']} MPC @ {repl['price']} (Order: {repl['order_id']})")
    
    # Handle ex2sum rows for cancelled trades
    if '_ex2sum' in trade_id and main_tid in REPLACEMENT_FILLS:
        repl = REPLACEMENT_FILLS[main_tid]
        
        # Update ex2sum
        row['ex2_order_id'] = repl['order_id']
        row['ex2_qty_filled'] = format_float_de(repl['filled'])
        row['ex2_price_actual'] = format_float_de(repl['price'])
        row['ex2_value_usdt'] = format_float_de(repl['value'])
        row['ex2_fees'] = format_float_de(repl['fee'])
        row['ex2_create_ts'] = ms_to_datetime_full(repl['created_at_ms'])
        row['ex2_status'] = 'FILLED'
        row['limit_watch_status'] = 'FILLED'
        
        print(f"✅ Fixed ex2sum {trade_id}: {repl['filled']} MPC")
    
    # Track ex1p2 rows
    if '_ex1p2' in trade_id:
        trades_with_ex1p2.add(main_tid)
    
    # Write the row
    output_rows.append(';'.join([row.get(c, '') for c in cols]))

# Check for missing ex1p2 rows
print("\n" + "=" * 80)
print("CHECKING FOR MISSING ex1p2 ROWS")
print("=" * 80)

# Find trades with only ex1p1 but having ex1_qty_filled < ex1_qty_ordered
trades_missing_ex1p2 = []
for row in input_rows:
    if '_ex1p1' in row.get('trade_id', ''):
        tid = row.get('trade_id', '').replace('_ex1p1', '')
        
        # Get the main row qty_ordered and qty_filled
        main_row = None
        for r in input_rows:
            if r.get('trade_id') == tid:
                main_row = r
                break
        
        if main_row:
            qty_ordered = parse_float(main_row.get('ex1_qty_ordered', 0))
            qty_filled = parse_float(row.get('ex1_qty_filled', 0))
            
            if qty_filled < qty_ordered and tid not in trades_with_ex1p2:
                trades_missing_ex1p2.append({
                    'tid': tid,
                    'ordered': qty_ordered,
                    'filled': qty_filled,
                    'missing': qty_ordered - qty_filled,
                    'ex1_order': main_row.get('ex1_order_id', '')
                })

if trades_missing_ex1p2:
    print(f"\nFound {len(trades_missing_ex1p2)} trades with missing ex1p2:")
    for t in trades_missing_ex1p2:
        print(f"  {t['tid']}: ordered={t['ordered']}, filled={t['filled']}, missing={t['missing']}, order={t['ex1_order'][:20]}...")
    
    print("\n⚠️  These trades need their ex1p2 fills queried from MEXC API")
    print("The MEXC API key needs TRADING permissions for myTrades endpoint")
    print("\nSkipping ex1p2 generation for now - need MEXC API access")
else:
    print("\n✅ All trades have their ex1p2 rows")

# Write output
output_path = '/home/openclaw/.openclaw/workspace/trading/arbitrage-bot/MPCUSDT_trades_corrected.csv'
with open(output_path, 'w') as f:
    f.write('\n'.join(output_rows))

print(f"\n✅ Wrote {len(output_rows)} rows to {output_path}")

# Summary
print("\n" + "=" * 80)
print("SUMMARY")
print("=" * 80)

# Count rows by type
main_count = len([r for r in output_rows[1:] if '_' not in r.split(';')[0]])
ex1p1_count = len([r for r in output_rows[1:] if '_ex1p1' in r])
ex1p2_count = len([r for r in output_rows[1:] if '_ex1p2' in r])
ex2sum_count = len([r for r in output_rows[1:] if '_ex2sum' in r])
ex2p1_count = len([r for r in output_rows[1:] if '_ex2p1' in r])

print(f"Main rows: {main_count}")
print(f"ex1p1 rows: {ex1p1_count}")
print(f"ex1p2 rows: {ex1p2_count}")
print(f"ex2sum rows: {ex2sum_count}")
print(f"ex2p1 rows: {ex2p1_count}")
print(f"Total: {len(output_rows) - 1} (excluding header)")

# Verify replacement trades
print("\nVerified replacement fills:")
for tid, repl in REPLACEMENT_FILLS.items():
    print(f"  {tid}: {repl['filled']} MPC @ {repl['price']} (Order: {repl['order_id']})")