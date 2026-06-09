#!/usr/bin/env python3
"""
Rebuild MPCUSDT_trades.csv - PERFEKTE KOPIE des trade_logger.py Formats

UNIFIED_COLUMNS (genau 41 Spalten, 0-40):
 0: trade_id
 1: internal_ts
 2: direction
 3: pair
 4: strategy
 5: spread_pct
 6: ex1
 7: ex1_order_id
 8: ex1_type
 9: ex1_side
10: ex1_qty_ordered
11: ex1_qty_filled
12: ex1_price_expected
13: ex1_price_actual
14: ex1_value_usdt
15: ex1_fees
16: ex1_create_ts
17: ex1_status
18: ex2
19: ex2_order_id
20: ex2_type
21: ex2_side
22: ex2_qty_ordered
23: ex2_qty_filled
24: ex2_price_expected
25: ex2_price_actual
26: ex2_value_usdt
27: ex2_fees
28: ex2_create_ts
29: ex2_status
30: profit_usdt_expected
31: profit_mpc_expected
32: profit_usdt_actual
33: profit_mpc_actual
34: limit_watch_status
35: limit_last_check
36: error_code
37: error_message
38: raw_ex1_response
39: raw_ex2_response
40: raw_ex2_response_ts
"""

import requests
import hmac
import hashlib
import time
import csv
import base64
from datetime import datetime
from collections import defaultdict

# ============================================================
# CREDENTIALS
# ============================================================
with open('config/config.yaml') as f:
    import yaml
    cfg = yaml.safe_load(f)
    KUCOIN_KEY = cfg['kucoin']['api_key']
    KUCOIN_SECRET = cfg['kucoin']['api_secret']
    KUCOIN_PASSPHRASE = cfg['kucoin']['api_passphrase']

# ============================================================
# MEXC FILLS (aus earlier API call)
# ============================================================
MEXC_FILLS = {
    '1b1611d4e': [
        {'qty': 57.72, 'price': 0.01741, 'value': 1.0049, 'fee': 0.0005, 'time': 1779913032000},
        {'qty': 79.28, 'price': 0.01730, 'value': 1.3715, 'fee': 0.0007, 'time': 1779913032000},
    ],
    '1b16111d31': [
        {'qty': 78.07, 'price': 0.01752, 'value': 1.3678, 'fee': 0.0007, 'time': 1779913048000},
        {'qty': 79.93, 'price': 0.01742, 'value': 1.3924, 'fee': 0.0007, 'time': 1779913048000},
    ],
    '1b1611211e': [
        {'qty': 83.15, 'price': 0.01772, 'value': 1.4734, 'fee': 0.0007, 'time': 1779913052000},
        {'qty': 68.39, 'price': 0.01764, 'value': 1.2064, 'fee': 0.0006, 'time': 1779913052000},
        {'qty': 0.46, 'price': 0.01752, 'value': 0.0081, 'fee': 0.0000, 'time': 1779913052000},
    ],
    '1b16113062': [
        {'qty': 32.97, 'price': 0.01793, 'value': 0.5912, 'fee': 0.0003, 'time': 1779913067000},
        {'qty': 79.73, 'price': 0.01789, 'value': 1.4264, 'fee': 0.0007, 'time': 1779913067000},
        {'qty': 0.30, 'price': 0.01772, 'value': 0.0053, 'fee': 0.0000, 'time': 1779913067000},
    ],
    '1b16113647': [
        {'qty': 67.73, 'price': 0.01800, 'value': 1.2191, 'fee': 0.0006, 'time': 1779913073000},
        {'qty': 44.27, 'price': 0.01793, 'value': 0.7938, 'fee': 0.0004, 'time': 1779913073000},
    ],
    '1b16121b13': [
        {'qty': 183.00, 'price': 0.01755, 'value': 3.2117, 'fee': 0.0016, 'time': 1779913106000},
    ],
    '1b1612202e': [
        {'qty': 144.00, 'price': 0.01740, 'value': 2.5056, 'fee': 0.0013, 'time': 1779913111000},
    ],
    '1b16122f50': [
        {'qty': 30.95, 'price': 0.01799, 'value': 0.5568, 'fee': 0.0003, 'time': 1779913126000},
        {'qty': 81.05, 'price': 0.01789, 'value': 1.4500, 'fee': 0.0007, 'time': 1779913126000},
    ],
    '1b16181516': [
        {'qty': 36.52, 'price': 0.01798, 'value': 0.6566, 'fee': 0.0003, 'time': 1779913460000},
        {'qty': 75.48, 'price': 0.01785, 'value': 1.3473, 'fee': 0.0007, 'time': 1779913460000},
    ],
    '1b161c1a45': [
        {'qty': 250.00, 'price': 0.01781, 'value': 4.4525, 'fee': 0.0022, 'time': 1779913705000},
    ],
    '1b161c1e42': [
        {'qty': 210.00, 'price': 0.01780, 'value': 3.7380, 'fee': 0.0019, 'time': 1779913709000},
    ],
    '1b161c2c27': [
        {'qty': 75.93, 'price': 0.01783, 'value': 1.3538, 'fee': 0.0007, 'time': 1779913723000},
    ],
    '1b161e2f2a': [
        {'qty': 86.00, 'price': 0.01777, 'value': 1.5282, 'fee': 0.0008, 'time': 1779913846000},
    ],
    '1c8252130': [
        {'qty': 80.45, 'price': 0.01709, 'value': 1.3749, 'fee': 0.0007, 'time': 1779950252000},
        {'qty': 80.55, 'price': 0.01705, 'value': 1.3734, 'fee': 0.0007, 'time': 1779950252000},
    ],
    '1c8252549': [
        {'qty': 276.57, 'price': 0.01728, 'value': 4.7791, 'fee': 0.0024, 'time': 1779950256000},
        {'qty': 80.36, 'price': 0.01723, 'value': 1.3846, 'fee': 0.0007, 'time': 1779950256000},
        {'qty': 0.07, 'price': 0.01709, 'value': 0.0012, 'fee': 0.0000, 'time': 1779950256000},
    ],
    '1c825365e': [
        {'qty': 79.15, 'price': 0.01743, 'value': 1.3796, 'fee': 0.0007, 'time': 1779950273000},
        {'qty': 82.25, 'price': 0.01730, 'value': 1.4229, 'fee': 0.0007, 'time': 1779950273000},
        {'qty': 0.60, 'price': 0.01728, 'value': 0.0104, 'fee': 0.0000, 'time': 1779950273000},
    ],
    '1cb36f01': [
        {'qty': 80.44, 'price': 0.01691, 'value': 1.3602, 'fee': 0.0007, 'time': 1779960852000},
        {'qty': 81.56, 'price': 0.01679, 'value': 1.3694, 'fee': 0.0007, 'time': 1779960852000},
    ],
    '1cb361254': [
        {'qty': 496.76, 'price': 0.01710, 'value': 8.4946, 'fee': 0.0042, 'time': 1779960858000},
        {'qty': 81.24, 'price': 0.01706, 'value': 1.3859, 'fee': 0.0007, 'time': 1779960858000},
    ],
    '1cb36224e': [
        {'qty': 117.00, 'price': 0.01709, 'value': 1.9995, 'fee': 0.0010, 'time': 1779960873000},
    ],
    '1cb362818': [
        {'qty': 117.00, 'price': 0.01710, 'value': 2.0007, 'fee': 0.0010, 'time': 1779960879000},
    ],
    '1cb37048': [
        {'qty': 117.00, 'price': 0.01710, 'value': 2.0007, 'fee': 0.0010, 'time': 1779960900000},
    ],
}

# ============================================================
# TRADE MAPPING
# ============================================================
TRADE_MEXC = {
    '1b1611d4e': 'C02__688414456513777664119',
    '1b16111d31': 'C02__688414521529683969119',
    '1b1611211e': 'C02__688414538755608579119',
    '1b16113062': 'C02__688414602798489601119',
    '1b16113647': 'C02__688414627339358208119',
    '1b16121b13': 'C02__688414764631461888119',
    '1b1612202e': 'C02__688414786253148160119',
    '1b16122f50': 'C02__688414850790903809119',
    '1b16181516': 'C02__688416249486381056119',
    '1b161c1a45': 'C02__688417278021996544119',
    '1b161c1e42': 'C02__688417295872958465119',
    '1b161c2c27': 'C02__688417353221672960119',
    '1b161e2f2a': 'C02__688417869540503552119',
    '1c8252130': 'C02__688570566356905984119',
    '1c8252549': 'C02__688570583591292928119',
    '1c825365e': 'C02__688570656337301504119',
    '1cb36f01': 'C02__688620065544654849119',
    '1cb361254': 'C02__688620082586062848119',
    '1cb36224e': 'C02__688620148457660416119',
    '1cb362818': 'C02__688620171375337472119',
    '1cb37048': 'C02__688620258105106433119',
}

TRADE_KCN = {
    '1b1611d4e': '6a17514967c9710007139cef',
    '1b16111d31': '6a17515967c971000713d108',
    '1b1611211e': '6a17515d1296f100074afb9f',
    '1b16113062': '6a1751979c8d050007ecf50d',
    '1b16113647': '6a1751910970a10007e9173d',
    '1b16121b13': '6a1751931296f100074bae96',
    '1b1612202e': '6a175198f7247100073a7423',
    '1b16122f50': '6a1751c530aa00000711dc0d',
    '1b16181516': '6a17578642a70a00075963c5',
    '1b161c1a45': '6a1753ea8d7f740007fc976b',
    '1b161c1e42': '6a17577e0970a10007fb714a',
    '1b161c2c27': '6a1753fc30aa00000718e8bf',
    '1b161e2f2a': '6a1754774e1cb600073c7de2',
    '1c8252130': '6a17e2adf103be00072e301c',
    '1c8252549': '6a17e2b167c971000744051f',
    '1c825365e': '6a17e2c2f828df000769e0a7',
    '1cb36f01': '6a1810c6eaee1500076691ce',
    '1cb361254': '6a1810cae1d8f800075b948e',
    '1cb36224e': '6a1810da4afdd0000792a8d7',
    '1cb362818': '6a1810e0f103be0007d34ea6',
    '1cb37048': '6a1810f442a70a00071b70c5',
}

# ============================================================
# HEADER (genau 41 Spalten wie trade_logger.py)
# ============================================================
UNIFIED_COLUMNS = [
    "trade_id", "internal_ts", "direction", "pair", "strategy", "spread_pct",
    "ex1", "ex1_order_id", "ex1_type", "ex1_side",
    "ex1_qty_ordered", "ex1_qty_filled", "ex1_price_expected", "ex1_price_actual",
    "ex1_value_usdt", "ex1_fees", "ex1_create_ts", "ex1_status",
    "ex2", "ex2_order_id", "ex2_type", "ex2_side",
    "ex2_qty_ordered", "ex2_qty_filled", "ex2_price_expected", "ex2_price_actual",
    "ex2_value_usdt", "ex2_fees", "ex2_create_ts", "ex2_status",
    "profit_usdt_expected", "profit_mpc_expected", "profit_usdt_actual", "profit_mpc_actual",
    "limit_watch_status", "limit_last_check", "error_code", "error_message",
    "raw_ex1_response", "raw_ex2_response", "raw_ex2_response_ts"
]

# ============================================================
# HELPERS
# ============================================================
def fmt(v, d=2):
    if v is None or v == 0:
        return ''
    return f"{v:.{d}f}".replace('.', ',')

def fmt_price(v):
    if v is None or v == 0:
        return ''
    return f"{v:.6f}".replace('.', ',')

def kucoin_sig(secret, ts, method, path):
    msg = f'{ts}{method}{path}'
    return base64.b64encode(hmac.new(secret.encode(), msg.encode(), hashlib.sha256).digest()).decode()

def kucoin_pass(secret, passphrase):
    return base64.b64encode(hmac.new(secret.encode(), passphrase.encode(), hashlib.sha256).digest()).decode()

def kucoin_request(method, path):
    ts = str(int(time.time() * 1000))
    sig = kucoin_sig(KUCOIN_SECRET, ts, method, path)
    pwd = kucoin_pass(KUCOIN_SECRET, KUCOIN_PASSPHRASE)
    headers = {
        'KC-API-KEY': KUCOIN_KEY,
        'KC-API-SIGN': sig,
        'KC-API-TIMESTAMP': ts,
        'KC-API-PASSPHRASE': pwd,
        'KC-API-KEY-VERSION': '2'
    }
    resp = requests.request(method, f'https://api.kucoin.com{path}', headers=headers, timeout=10)
    return resp.json()

def create_empty_row(trade_id):
    """Create row dict with all columns initialized to empty"""
    return {col: "" for col in UNIFIED_COLUMNS}

# ============================================================
# FETCH KUCOIN FILLS
# ============================================================
print("Fetching KuCoin fills...")
kcn_fills = {}
for tid, oid in TRADE_KCN.items():
    try:
        data = kucoin_request('GET', f'/api/v1/fills?orderId={oid}&limit=10')
        if data.get('code') == '200000':
            kcn_fills[tid] = data['data']['items']
            print(f"  {tid}: {len(kcn_fills[tid])} KCN fills")
        else:
            kcn_fills[tid] = []
            print(f"  {tid}: ERROR")
    except Exception as e:
        kcn_fills[tid] = []
        print(f"  {tid}: EXCEPTION")

# ============================================================
# BUILD ROWS
# ============================================================
print("\nBuilding rows...")
rows = [UNIFIED_COLUMNS]  # Header

for tid in sorted(TRADE_MEXC.keys()):
    mexc_oid = TRADE_MEXC[tid]
    kcn_oid = TRADE_KCN[tid]
    
    # MEXC fills
    fills = sorted(MEXC_FILLS.get(tid, []), key=lambda x: x['time'])
    total_mexc_qty = sum(f['qty'] for f in fills)
    total_mexc_val = sum(f['value'] for f in fills)
    total_mexc_fee = sum(f['fee'] for f in fills)
    avg_mexc_price = total_mexc_val / total_mexc_qty if total_mexc_qty > 0 else 0
    
    # KCN fills
    kfills = kcn_fills.get(tid, [])
    total_kcn_qty = sum(float(f['size']) for f in kfills)
    total_kcn_val = sum(float(f['funds']) for f in kfills)
    total_kcn_fee = sum(float(f['fee']) for f in kfills)
    avg_kcn_price = total_kcn_val / total_kcn_qty if total_kcn_qty > 0 else 0
    
    # ---- MAIN ROW (row1) ----
    mr = create_empty_row(tid)
    mr['direction'] = 'MXC->KCN'
    mr['pair'] = 'MPC-USDT'
    mr['strategy'] = 'USDT'
    mr['ex1'] = 'MXC'
    mr['ex1_order_id'] = mexc_oid
    mr['ex1_type'] = 'market'
    mr['ex1_side'] = 'buy'
    mr['ex1_qty_filled'] = total_mexc_qty
    mr['ex1_price_actual'] = avg_mexc_price
    mr['ex1_value_usdt'] = total_mexc_val
    mr['ex1_fees'] = total_mexc_fee
    mr['ex1_status'] = 'FILLED' if total_mexc_qty > 0 else 'PARTIAL'
    mr['ex2'] = 'KCN'
    mr['ex2_order_id'] = kcn_oid
    mr['ex2_type'] = 'limit'
    mr['ex2_side'] = 'sell'
    mr['ex2_qty_ordered'] = total_mexc_qty  # was our buy qty
    mr['ex2_qty_filled'] = total_kcn_qty
    mr['ex2_price_actual'] = avg_kcn_price
    mr['ex2_value_usdt'] = total_kcn_val
    mr['ex2_fees'] = total_kcn_fee
    mr['ex2_status'] = 'FILLED' if total_kcn_qty >= total_mexc_qty else 'PARTIAL'
    mr['profit_mpc_actual'] = total_mexc_qty - total_kcn_qty
    mr['limit_watch_status'] = 'FILLED'
    rows.append(mr)
    
    # ---- EX1P ROWS (MEXC fills) ----
    for i, f in enumerate(fills):
        ts_dt = datetime.fromtimestamp(f['time'] / 1000)
        ex1p = create_empty_row(f"{tid}_ex1p{i+1}")
        ex1p['ex1_qty_filled'] = f['qty']
        ex1p['ex1_price_actual'] = f['price']
        ex1p['ex1_value_usdt'] = f['value']
        ex1p['ex1_fees'] = f['fee']
        ex1p['ex1_create_ts'] = ts_dt.strftime('%Y-%m-%d %H:%M:%S.000')
        ex1p['ex1_status'] = 'FILLED'
        rows.append(ex1p)
    
    # ---- EX2SUM ROW ----
    ex2sum = create_empty_row(f"{tid}_ex2sum")
    ex2sum['ex2'] = 'KCN'
    ex2sum['ex2_order_id'] = kcn_oid
    ex2sum['ex2_type'] = 'limit'
    ex2sum['ex2_side'] = 'sell'
    ex2sum['ex2_qty_ordered'] = total_mexc_qty
    ex2sum['ex2_qty_filled'] = total_kcn_qty
    ex2sum['ex2_price_actual'] = avg_kcn_price
    ex2sum['ex2_value_usdt'] = total_kcn_val
    ex2sum['ex2_fees'] = total_kcn_fee
    ex2sum['ex2_status'] = 'FILLED' if total_kcn_qty >= total_mexc_qty else 'PARTIAL'
    ex2sum['profit_mpc_actual'] = total_mexc_qty - total_kcn_qty
    ex2sum['limit_watch_status'] = 'FILLED'
    rows.append(ex2sum)
    
    # ---- EX2P ROWS (KCN fills) ----
    for i, kf in enumerate(kfills):
        ts_k = datetime.fromtimestamp(int(kf['createdAt']) / 1000)
        ex2p = create_empty_row(f"{tid}_ex2p{i+1}")
        ex2p['ex2_qty_filled'] = float(kf['size'])
        ex2p['ex2_price_actual'] = float(kf['price'])
        ex2p['ex2_value_usdt'] = float(kf['funds'])
        ex2p['ex2_fees'] = float(kf['fee'])
        ex2p['ex2_create_ts'] = ts_k.strftime('%Y-%m-%d %H:%M:%S.000')
        ex2p['ex2_status'] = 'FILLED'
        ex2p['limit_watch_status'] = 'FILLED'
        rows.append(ex2p)

# ============================================================
# WRITE OUTPUT
# ============================================================
OUTPUT = '/home/openclaw/.openclaw/workspace/trading/arbitrage-bot/MPCUSDT_trades_final.csv'

# Convert rows to lists with comma formatting
output_rows = []
for row_dict in rows:
    result = []
    for col in UNIFIED_COLUMNS:
        val = row_dict.get(col, "")
        if isinstance(val, (int, float)) and not isinstance(val, bool):
            if col in ('ex1_qty_ordered', 'ex1_qty_filled', 'ex2_qty_ordered', 'ex2_qty_filled',
                       'profit_mpc_expected', 'profit_mpc_actual'):
                val = fmt(val, 2)
            elif col in ('ex1_price_expected', 'ex1_price_actual', 'ex2_price_expected', 'ex2_price_actual'):
                val = fmt_price(val)
            elif col in ('ex1_value_usdt', 'ex1_fees', 'ex2_value_usdt', 'ex2_fees',
                         'profit_usdt_expected', 'profit_usdt_actual'):
                val = fmt(val, 4)
            else:
                val = fmt(val)
        result.append(str(val) if val is not None else "")
    output_rows.append(result)

with open(OUTPUT, 'w', newline='') as f:
    writer = csv.writer(f, delimiter=';')
    for row in output_rows:
        writer.writerow(row)

print(f"\nWrote {len(output_rows)} rows to {OUTPUT}")

# SUMMARY
counts = {'main': 0, 'ex1p': 0, 'ex2sum': 0, 'ex2p': 0}
for row in output_rows[1:]:
    t = row[0]
    if '_ex1p' in t: counts['ex1p'] += 1
    elif '_ex2sum' in t: counts['ex2sum'] += 1
    elif '_ex2p' in t: counts['ex2p'] += 1
    elif t: counts['main'] += 1
print(f"Summary: {counts}")
print("DONE!")
