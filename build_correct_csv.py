#!/usr/bin/env python3
"""
Build complete corrected MPCUSDT_trades.csv
Queries KuCoin API for all missing fill data
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
# TRADE DATA STRUCTURE
# ============================================================
TRADES = [
    {'trade_id': '1b1611d4e', 'ex1_order': 'C02__688414456513777664119', 'ex2_order': '6a17514967c9710007139cef', 'replacement': None},
    {'trade_id': '1b16111d31', 'ex1_order': 'C02__688414521529683969119', 'ex2_order': '6a17515967c971000713d108', 'replacement': None},
    {'trade_id': '1b1611211e', 'ex1_order': 'C02__688414538755608579119', 'ex2_order': '6a17515d1296f100074afb9f', 'replacement': None},
    {'trade_id': '1b16113062', 'ex1_order': 'C02__688414602798489601119', 'ex2_order': '6a17516caf78b5000775da5a', 'replacement': '1b16113062'},
    {'trade_id': '1b16113647', 'ex1_order': 'C02__688414627339358208119', 'ex2_order': '6a175172571a870007c90fa9', 'replacement': '1b16113647'},
    {'trade_id': '1b16121b13', 'ex1_order': 'C02__688414764631461888119', 'ex2_order': '6a1751931296f100074bae96', 'replacement': None},
    {'trade_id': '1b1612202e', 'ex1_order': 'C02__688414786253148160119', 'ex2_order': '6a175198f7247100073a7423', 'replacement': None},
    {'trade_id': '1b16122f50', 'ex1_order': 'C02__688414850790903809119', 'ex2_order': '6a1751a76950e40007d52a0a', 'replacement': '1b16122f50'},
    {'trade_id': '1b16181516', 'ex1_order': 'C02__688416249486381056119', 'ex2_order': '6a1752f5a7f17f000770d374', 'replacement': '1b16181516'},
    {'trade_id': '1b161c1a45', 'ex1_order': 'C02__688417278021996544119', 'ex2_order': '6a1753ea8d7f740007fc976b', 'replacement': None},
    {'trade_id': '1b161c1e42', 'ex1_order': 'C02__688417295872958465119', 'ex2_order': '6a1753eeeaee1500079a122c', 'replacement': '1b161c1e42'},
    {'trade_id': '1b161c2c27', 'ex1_order': 'C02__688417353221672960119', 'ex2_order': '6a1753fc30aa00000718e8bf', 'replacement': None},
    {'trade_id': '1b161e2f2a', 'ex1_order': 'C02__688417869540503552119', 'ex2_order': '6a1754774e1cb600073c7de2', 'replacement': None},
    {'trade_id': '1c8252130', 'ex1_order': 'C02__688570566356905984119', 'ex2_order': '6a17e2adf103be00072e301c', 'replacement': None},
    {'trade_id': '1c8252549', 'ex1_order': 'C02__688570583591292928119', 'ex2_order': '6a17e2b167c971000744051f', 'replacement': None},
    {'trade_id': '1c825365e', 'ex1_order': 'C02__688570656337301504119', 'ex2_order': '6a17e2c2f828df000769e0a7', 'replacement': None},
    {'trade_id': '1cb36f01', 'ex1_order': 'C02__688620065544654849119', 'ex2_order': '6a1810c6eaee1500076691ce', 'replacement': None},
    {'trade_id': '1cb361254', 'ex1_order': 'C02__688620082586062848119', 'ex2_order': '6a1810cae1d8f800075b948e', 'replacement': None},
    {'trade_id': '1cb36224e', 'ex1_order': 'C02__688620148457660416119', 'ex2_order': '6a1810da4afdd0000792a8d7', 'replacement': None},
    {'trade_id': '1cb362818', 'ex1_order': 'C02__688620171375337472119', 'ex2_order': '6a1810e0f103be0007d34ea6', 'replacement': None},
    {'trade_id': '1cb37048', 'ex1_order': 'C02__688620258105106433119', 'ex2_order': '6a1810f442a70a00071b70c5', 'replacement': None},
]

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

def format_float(val, decimals=6):
    if val is None or val == '' or val == 'None':
        return ''
    try:
        return str(round(float(val), decimals)).replace('.', ',')
    except:
        return ''

# ============================================================
# QUERY ALL REPLACEMENT ORDERS
# ============================================================
print("=" * 80)
print("QUERYING KUCOIN FOR ALL REPLACEMENT ORDERS")
print("=" * 80)

all_replacement_data = {}

for tid, data in REPLACEMENT_FILLS.items():
    order_id = data['order_id']
    print(f"\n{tid}: Querying order {order_id}")
    
    # Get order details
    path = f'/api/v1/orders/{order_id}?symbol=MPC-USDT'
    result = kucoin_request('GET', path)
    
    if result.get('code') == '200000':
        order_data = result['data']
        all_replacement_data[tid] = {
            'order_id': order_id,
            'filled': float(order_data.get('dealSize', 0) or 0),
            'price': float(order_data.get('price', 0) or 0),
            'value': float(order_data.get('dealFunds', 0) or 0),
            'fee': float(order_data.get('fee', 0) or 0),
            'created_at_ms': order_data.get('createdAt'),
            'status': order_data.get('status'),
        }
        
        # Get fills
        fills_path = f'/api/v1/fills?symbol=MPC-USDT&orderId={order_id}'
        fills_result = kucoin_request('GET', fills_path)
        
        if fills_result.get('code') == '200000':
            fills = fills_result['data']['items']
            print(f"  Fills: {len(fills)}")
            for f in fills:
                print(f"    - size: {f.get('size')}, price: {f.get('price')}, fee: {f.get('fee')}")
        else:
            print(f"  Fills error: {fills_result}")
    else:
        print(f"  Order error: {result}")

print("\n" + "=" * 80)
print("VERIFIED REPLACEMENT DATA")
print("=" * 80)
for tid, data in all_replacement_data.items():
    print(f"{tid}: {data['filled']} MPC @ {data['price']} (Order: {data['order_id']})")

# ============================================================
# BUILD THE COMPLETE CORRECTED CSV
# ============================================================
print("\n" + "=" * 80)
print("BUILDING CORRECTED CSV")
print("=" * 80)

# CSV columns
cols = ['trade_id','internal_ts','direction','pair','strategy','spread_pct',
        'ex1','ex1_order_id','ex1_type','ex1_side','ex1_qty_ordered','ex1_qty_filled',
        'ex1_price_expected','ex1_price_actual','ex1_value_usdt','ex1_fees','ex1_create_ts','ex1_status',
        'ex2','ex2_order_id','ex2_type','ex2_side','ex2_qty_ordered','ex2_qty_filled',
        'ex2_price_expected','ex2_price_actual','ex2_value_usdt','ex2_fees','ex2_create_ts','ex2_status',
        'profit_usdt_expected','profit_mpc_expected','profit_usdt_actual','profit_mpc_actual',
        'limit_watch_status','limit_last_check','error_code','error_message',
        'raw_ex1_response','raw_ex2_response','raw_ex2_response_ts']

# Read original CSV to get base data
input_csv = '/home/openclaw/.openclaw/workspace/trading/arbitrage-bot/MPCUSDT_trades_fresh.csv'

rows = []
with open(input_csv, 'r') as f:
    reader = csv.DictReader(f, delimiter=';')
    input_rows = list(reader)

print(f"Read {len(input_rows)} rows from {input_csv}")

# Process each trade
output_rows = []
output_rows.append(';'.join(cols))  # Header

for row in input_rows:
    trade_id = row.get('trade_id', '')
    
    # Skip if it's a partial fill row that needs special handling
    if '_ex2sum' in trade_id or '_ex1p' in trade_id:
        # These will be regenerated
        continue
    
    if '_ex2p' in trade_id:
        # Check if this is a replacement trade
        main_tid = trade_id.replace('_ex2p1', '').replace('_ex2p2', '')
        if main_tid in all_replacement_data:
            repl = all_replacement_data[main_tid]
            # Update with replacement data
            row['ex2_qty_filled'] = format_float(repl['filled'])
            row['ex2_price_actual'] = format_float(repl['price'])
            row['ex2_value_usdt'] = format_float(repl['value'])
            row['ex2_fees'] = format_float(repl['fee'])
            row['ex2_order_id'] = repl['order_id']
            row['ex2_status'] = 'FILLED'
            row['limit_watch_status'] = 'FILLED'
        
        output_rows.append(';'.join([row.get(c, '') for c in cols]))
    else:
        # Main trade row
        output_rows.append(';'.join([row.get(c, '') for c in cols]))

# Generate proper output
print("\nGenerating correct structure for each trade...")

# Final output
final_rows = ['trade_id;internal_ts;direction;pair;strategy;spread_pct;ex1;ex1_order_id;ex1_type;ex1_side;ex1_qty_ordered;ex1_qty_filled;ex1_price_expected;ex1_price_actual;ex1_value_usdt;ex1_fees;ex1_create_ts;ex1_status;ex2;ex2_order_id;ex2_type;ex2_side;ex2_qty_ordered;ex2_qty_filled;ex2_price_expected;ex2_price_actual;ex2_value_usdt;ex2_fees;ex2_create_ts;ex2_status;profit_usdt_expected;profit_mpc_expected;profit_usdt_actual;profit_mpc_actual;limit_watch_status;limit_last_check;error_code;error_message;raw_ex1_response;raw_ex2_response;raw_ex2_response_ts']

# Process trades properly
for trade in TRADES:
    tid = trade['trade_id']
    repl_key = trade['replacement']
    
    # Find original row data
    main_row = None
    ex1p_rows = []
    ex2sum_row = None
    ex2p_rows = []
    
    for row in input_rows:
        if row.get('trade_id') == tid:
            main_row = row
        elif row.get('trade_id') == f"{tid}_ex1p1":
            ex1p_rows.append(row)
        elif row.get('trade_id') == f"{tid}_ex1p2":
            ex1p_rows.append(row)
        elif row.get('trade_id') == f"{tid}_ex1p3":
            ex1p_rows.append(row)
        elif row.get('trade_id') == f"{tid}_ex2sum":
            ex2sum_row = row
        elif row.get('trade_id') == f"{tid}_ex2p1":
            ex2p_rows.append(row)
    
    if not main_row:
        continue
    
    # Calculate totals from ex1p rows
    total_ex1_filled = sum(float(r.get('ex1_qty_filled', 0).replace(',', '.') or 0) for r in ex1p_rows)
    
    # Build main row
    main_cols = [
        tid,
        main_row.get('internal_ts', ''),
        main_row.get('direction', ''),
        main_row.get('pair', ''),
        main_row.get('strategy', ''),
        main_row.get('spread_pct', ''),
        main_row.get('ex1', ''),
        main_row.get('ex1_order_id', ''),
        main_row.get('ex1_type', ''),
        main_row.get('ex1_side', ''),
        main_row.get('ex1_qty_ordered', ''),
        format_float(total_ex1_filled),
        main_row.get('ex1_price_expected', ''),
        main_row.get('ex1_price_actual', ''),
        main_row.get('ex1_value_usdt', ''),
        main_row.get('ex1_fees', ''),
        main_row.get('ex1_create_ts', ''),
        'PARTIAL' if total_ex1_filled < float(main_row.get('ex1_qty_ordered', 0).replace(',', '.') or 0) else 'FILLED',
        'KCN',  # ex2
        main_row.get('ex2_order_id', ''),  # Will be updated for replacements
        main_row.get('ex2_type', ''),
        main_row.get('ex2_side', ''),
        main_row.get('ex2_qty_ordered', ''),
        '',  # ex2_qty_filled - will be set from replacement or original
        main_row.get('ex2_price_expected', ''),
        '',  # ex2_price_actual
        '',  # ex2_value_usdt
        '',  # ex2_fees
        '',  # ex2_create_ts
        '',  # ex2_status
        main_row.get('profit_usdt_expected', ''),
        main_row.get('profit_mpc_expected', ''),
        '',  # profit_usdt_actual
        '',  # profit_mpc_actual
        '',  # limit_watch_status
        '',  # limit_last_check
        '',  # error_code
        '',  # error_message
        main_row.get('raw_ex1_response', ''),
        '',  # raw_ex2_response
        '',  # raw_ex2_response_ts
    ]
    final_rows.append(';'.join(main_cols))
    
    # ex1p rows
    for ex1p_row in sorted(ex1p_rows, key=lambda x: x.get('trade_id', '')):
        ex1p_cols = [
            ex1p_row.get('trade_id', ''),
            '', '', '', '', '', '', '', '', '', '',  # cols 2-12 empty
            ex1p_row.get('ex1_qty_filled', ''),
            '',
            ex1p_row.get('ex1_price_actual', ''),
            ex1p_row.get('ex1_value_usdt', ''),
            ex1p_row.get('ex1_fees', ''),
            ex1p_row.get('ex1_create_ts', ''),
            'FILLED',
            'KCN', '', '', '', '', '', '', '', '', '', '', '', '', '', '', '', '', '', '', ''
        ]
        final_rows.append(';'.join(ex1p_cols))
    
    # ex2sum row
    if ex2sum_row:
        ex2_qty_filled = 0
        ex2_price = 0
        ex2_value = 0
        ex2_fees = 0
        ex2_order_id = ex2sum_row.get('ex2_order_id', '')
        ex2_create_ts = ''
        limit_status = 'WATCHING'
        ex2_status = 'PARTIAL'
        
        if repl_key and repl_key in all_replacement_data:
            repl = all_replacement_data[repl_key]
            ex2_qty_filled = repl['filled']
            ex2_price = repl['price']
            ex2_value = repl['value']
            ex2_fees = repl['fee']
            ex2_order_id = repl['order_id']
            ex2_create_ts = ms_to_datetime_full(repl['created_at_ms'])
            limit_status = 'FILLED'
            ex2_status = 'FILLED'
        
        ex2sum_cols = [
            f"{tid}_ex2sum",
            '', '', '', '', '', '', '', '', '', '', '', '', '', '', '', '', '',
            'KCN',
            ex2_order_id,
            'limit',
            'sell',
            ex2sum_row.get('ex2_qty_ordered', ''),
            format_float(ex2_qty_filled),
            ex2sum_row.get('ex2_price_expected', ''),
            format_float(ex2_price),
            format_float(ex2_value),
            format_float(ex2_fees),
            ex2_create_ts,
            ex2_status,
            ex2sum_row.get('profit_usdt_expected', ''),
            ex2sum_row.get('profit_mpc_expected', ''),
            '',  # profit_usdt_actual
            '',  # profit_mpc_actual
            limit_status,
            ex2sum_row.get('limit_last_check', ''),
            '', '', '',
            ex2sum_row.get('raw_ex2_response', ''),
            ex2sum_row.get('raw_ex2_response_ts', ''),
        ]
        final_rows.append(';'.join(ex2sum_cols))
    
    # ex2p1 row
    ex2p1_cols = [
        f"{tid}_ex2p1",
        '', '', '', '', '', '', '', '', '', '', '', '', '', '', '', '', '',
        'KCN',
        ex2_order_id if repl_key and repl_key in all_replacement_data else (ex2p_rows[0].get('ex2_order_id', '') if ex2p_rows else ''),
        'limit',
        'sell',
        '',  # ex2_qty_ordered
        format_float(ex2_qty_filled if repl_key and repl_key in all_replacement_data else 0),
        '',
        format_float(ex2_price if repl_key and repl_key in all_replacement_data else 0),
        format_float(ex2_value if repl_key and repl_key in all_replacement_data else 0),
        format_float(ex2_fees if repl_key and repl_key in all_replacement_data else 0),
        ex2_create_ts if repl_key and repl_key in all_replacement_data else '',
        'FILLED' if (repl_key and repl_key in all_replacement_data and ex2_qty_filled > 0) else 'PENDING',
        '', '', '', '', '', '', '', '', '', '', '',  # remaining empty
    ]
    final_rows.append(';'.join(ex2p1_cols))

# Write output
output_path = '/home/openclaw/.openclaw/workspace/trading/arbitrage-bot/MPCUSDT_trades_corrected.csv'
with open(output_path, 'w') as f:
    f.write('\n'.join(final_rows))

print(f"\n✅ Wrote {len(final_rows)} rows to {output_path}")
print("\nVerifying output...")
with open(output_path, 'r') as f:
    lines = f.readlines()
    print(f"Total rows: {len(lines)}")
    print(f"Main trades: {len([l for l in lines if '_' not in l.split(';')[0]])}")

print("\nFirst 10 lines:")
for line in lines[:10]:
    print(line[:150])