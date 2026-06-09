#!/usr/bin/env python3
"""
Generate corrected MPCUSDT_trades.csv with verified replacement fills
Using API data from KuCoin to correct the 5 cancelled trades
"""
import csv
from datetime import datetime

# ============================================================
# VERIFIED REPLACEMENT FILL DATA (from KuCoin API)
# ============================================================
REPLACEMENT_FILLS = {
    '1b16113062': {
        'order_id': '6a1751979c8d050007ecf50d',
        'filled': 33.0,
        'price': 0.018941,
        'value': 0.625053,
        'fee': 0.001875159,
        'created_at_ms': 1779913111512
    },
    '1b16113647': {
        'order_id': '6a1751910970a10007e9173d',
        'filled': 68.0,
        'price': 0.018935,
        'value': 1.28758,
        'fee': 0.00386274,
        'created_at_ms': 1779913105052
    },
    '1b16122f50': {
        'order_id': '6a1751c530aa00000711dc0d',
        'filled': 31.0,
        'price': 0.018941,
        'value': 0.587171,
        'fee': 0.001761513,
        'created_at_ms': 1779913157972
    },
    '1b16181516': {
        'order_id': '6a17578642a70a00075963c5',
        'filled': 37.0,
        'price': 0.019,
        'value': 0.703,
        'fee': 0.002109,
        'created_at_ms': 1779914630060
    },
    '1b161c1e42': {
        'order_id': '6a17577e0970a10007fb714a',
        'filled': 210.0,
        'price': 0.019,
        'value': 3.99,
        'fee': 0.01197,
        'created_at_ms': 1779914622090
    },
}

# ============================================================
# HELPER FUNCTIONS
# ============================================================
def format_float(val, decimals=6):
    """Format float with proper decimal places"""
    if val is None or val == '' or val == 'None':
        return ''
    try:
        return str(round(float(val), decimals))
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

def ms_to_datetime_full(ts_ms):
    """Convert to full datetime format YYYY-MM-DD HH:MM:SS.mmm"""
    if ts_ms and int(ts_ms) > 0:
        return datetime.fromtimestamp(int(ts_ms)/1000).strftime('%Y-%m-%d %H:%M:%S.%f')[:-3]
    return ''

# ============================================================
# TRADE DATA (from original CSV analysis)
# Each trade has: main row, ex1p1 row, ex2sum row, ex2p1 row
# ============================================================
TRADES = [
    # Trade 1: 1b1611d4e - COMPLETE
    {'trade_id': '1b1611d4e', 'ex1_filled': 57.72, 'ex2_filled': 58.0, 'ex2_fees': 0.003160362, 'replacement': None},
    # Trade 2: 1b16111d31 - COMPLETE
    {'trade_id': '1b16111d31', 'ex1_filled': 78.07, 'ex2_filled': 78.0, 'ex2_fees': 0.004249908, 'replacement': None},
    # Trade 3: 1b1611211e - COMPLETE
    {'trade_id': '1b1611211e', 'ex1_filled': 83.15, 'ex2_filled': 83.0, 'ex2_fees': 0.004522338, 'replacement': None},
    # Trade 4: 1b16113062 - CANCELLED → REPLACEMENT FILLED
    {'trade_id': '1b16113062', 'ex1_filled': 32.97, 'ex2_filled': 33.0, 'ex2_fees': 0.001875159, 'replacement': '1b16113062'},
    # Trade 5: 1b16113647 - CANCELLED → REPLACEMENT FILLED
    {'trade_id': '1b16113647', 'ex1_filled': 67.73, 'ex2_filled': 68.0, 'ex2_fees': 0.00386274, 'replacement': '1b16113647'},
    # Trade 6: 1b16121b13 - COMPLETE
    {'trade_id': '1b16121b13', 'ex1_filled': 183.0, 'ex2_filled': 183.0, 'ex2_fees': 0.009963252, 'replacement': None},
    # Trade 7: 1b1612202e - COMPLETE
    {'trade_id': '1b1612202e', 'ex1_filled': 144.0, 'ex2_filled': 144.0, 'ex2_fees': 0.007839936, 'replacement': None},
    # Trade 8: 1b16122f50 - CANCELLED → REPLACEMENT FILLED
    {'trade_id': '1b16122f50', 'ex1_filled': 30.95, 'ex2_filled': 31.0, 'ex2_fees': 0.001761513, 'replacement': '1b16122f50'},
    # Trade 9: 1b16181516 - CANCELLED → REPLACEMENT FILLED
    {'trade_id': '1b16181516', 'ex1_filled': 36.52, 'ex2_filled': 37.0, 'ex2_fees': 0.002109, 'replacement': '1b16181516'},
    # Trade 10: 1b161c1a45 - COMPLETE
    {'trade_id': '1b161c1a45', 'ex1_filled': 250.0, 'ex2_filled': 250.0, 'ex2_fees': 0.0135345, 'replacement': None},
    # Trade 11: 1b161c1e42 - CANCELLED → REPLACEMENT FILLED
    {'trade_id': '1b161c1e42', 'ex1_filled': 210.0, 'ex2_filled': 210.0, 'ex2_fees': 0.01197, 'replacement': '1b161c1e42'},
    # Trade 12: 1b161c2c27 - COMPLETE
    {'trade_id': '1b161c2c27', 'ex1_filled': 75.93, 'ex2_filled': 76.0, 'ex2_fees': 0.00411084, 'replacement': None},
    # Trade 13: 1b161e2f2a - COMPLETE
    {'trade_id': '1b161e2f2a', 'ex1_filled': 86.0, 'ex2_filled': 86.0, 'ex2_fees': 0.004646838, 'replacement': None},
    # Trade 14: 1c8252130 - COMPLETE
    {'trade_id': '1c8252130', 'ex1_filled': 80.45, 'ex2_filled': 80.0, 'ex2_fees': 0.00424728, 'replacement': None},
    # Trade 15: 1c8252549 - COMPLETE
    {'trade_id': '1c8252549', 'ex1_filled': 276.57, 'ex2_filled': 277.0, 'ex2_fees': 0.014707038, 'replacement': None},
    # Trade 16: 1c825365e - COMPLETE
    {'trade_id': '1c825365e', 'ex1_filled': 79.15, 'ex2_filled': 79.0, 'ex2_fees': 0.004191582, 'replacement': None},
    # Trade 17: 1cb36f01 - COMPLETE
    {'trade_id': '1cb36f01', 'ex1_filled': 80.44, 'ex2_filled': 80.0, 'ex2_fees': 0.00415128, 'replacement': None},
    # Trade 18: 1cb361254 - COMPLETE
    {'trade_id': '1cb361254', 'ex1_filled': 496.76, 'ex2_filled': 497.0, 'ex2_fees': 0.0, 'replacement': None},
    # Trade 19: 1cb36224e - COMPLETE
    {'trade_id': '1cb36224e', 'ex1_filled': 117.0, 'ex2_filled': 117.0, 'ex2_fees': 0.006074055, 'replacement': None},
    # Trade 20: 1cb362818 - COMPLETE
    {'trade_id': '1cb362818', 'ex1_filled': 117.0, 'ex2_filled': 117.0, 'ex2_fees': 0.006074757, 'replacement': None},
    # Trade 21: 1cb37048 - COMPLETE
    {'trade_id': '1cb37048', 'ex1_filled': 117.0, 'ex2_filled': 117.0, 'ex2_fees': 0.006062121, 'replacement': None},
]

# ============================================================
# BUILD CSV
# ============================================================
def build_csv():
    rows = []
    
    # Header
    header = 'trade_id;internal_ts;direction;pair;strategy;spread_pct;ex1;ex1_order_id;ex1_type;ex1_side;ex1_qty_ordered;ex1_qty_filled;ex1_price_expected;ex1_price_actual;ex1_value_usdt;ex1_fees;ex1_create_ts;ex1_status;ex2;ex2_order_id;ex2_type;ex2_side;ex2_qty_ordered;ex2_qty_filled;ex2_price_expected;ex2_price_actual;ex2_value_usdt;ex2_fees;ex2_create_ts;ex2_status;profit_usdt_expected;profit_mpc_expected;profit_usdt_actual;profit_mpc_actual;limit_watch_status;limit_last_check;error_code;error_message;raw_ex1_response;raw_ex2_response;raw_ex2_response_ts'
    rows.append(header)
    
    for trade in TRADES:
        tid = trade['trade_id']
        repl_key = trade['replacement']
        
        # Get replacement data if applicable
        if repl_key and repl_key in REPLACEMENT_FILLS:
            repl = REPLACEMENT_FILLS[repl_key]
            ex2_filled = repl['filled']
            ex2_price = repl['price']
            ex2_value = repl['value']
            ex2_fees = repl['fee']
            ex2_order_id = repl['order_id']
            ex2_create_ts = ms_to_datetime_full(repl['created_at_ms'])
            limit_status = 'FILLED'
            ex2_status = 'FILLED'
        else:
            ex2_filled = trade['ex2_filled']
            ex2_price = 0  # Will be from CSV
            ex2_value = 0  # Will be from CSV
            ex2_fees = trade['ex2_fees']
            ex2_order_id = ''  # From CSV
            ex2_create_ts = ''
            limit_status = 'FILLED'
            ex2_status = 'FILLED'
        
        # Placeholder rows - these need to be filled from actual CSV data
        # For now, create the structure with known data
        rows.append(f"{tid};;;;" + ";" * 40)  # Main row placeholder
        rows.append(f"{tid}_ex1p1;;;;;;" + ";" * 40)  # ex1p1 placeholder
        rows.append(f"{tid}_ex2sum;;;;" + ";" * 40)  # ex2sum placeholder
        rows.append(f"{tid}_ex2p1;;;;" + ";" * 40)  # ex2p1 placeholder
    
    return rows

print("This script needs the original CSV to be processed.")
print("The replacement data is ready:")
for tid, data in REPLACEMENT_FILLS.items():
    print(f"  {tid}: {data['filled']} MPC @ {data['price']} (Order: {data['order_id']})")
print("\nNeed to apply this to the actual CSV file.")