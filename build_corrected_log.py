#!/usr/bin/env python3
"""
Trade Log Generator - Build correct reference log from CSV + API data
Simulates how the bot's trade_logger would write the log
"""
import csv
from datetime import datetime

# ============================================================
# COLUMN MAPPING (based on TRADE_LOG_STRUCTURE.md)
# Col 1-41 mapping:
# ============================================================
# trade_id;internal_ts;direction;pair;strategy;spread_pct;ex1;ex1_order_id;ex1_type;ex1_side;ex1_qty_ordered;ex1_qty_filled;ex1_price_expected;ex1_price_actual;ex1_value_usdt;ex1_fees;ex1_create_ts;ex1_status;ex2;ex2_order_id;ex2_type;ex2_side;ex2_qty_ordered;ex2_qty_filled;ex2_price_expected;ex2_price_actual;ex2_value_usdt;ex2_fees;ex2_create_ts;ex2_status;profit_usdt_expected;profit_mpc_expected;profit_usdt_actual;profit_mpc_actual;limit_watch_status;limit_last_check;error_code;error_message;raw_ex1_response;raw_ex2_response;raw_ex2_response_ts

# ============================================================
# REPLACEMENT ORDER DATA (from KuCoin API)
# ============================================================
REPLACEMENT_FILLS = {
    '1b16113062': {'order_id': '6a1751979c8d050007ecf50d', 'filled': 33.0, 'price': 0.018941, 'value': 0.625053, 'fee': 0.001875159, 'created_at': 1779913111512},
    '1b16113647': {'order_id': '6a1751910970a10007e9173d', 'filled': 68.0, 'price': 0.018935, 'value': 1.28758, 'fee': 0.00386274, 'created_at': 1779913105052},
    '1b16122f50': {'order_id': '6a1751c530aa00000711dc0d', 'filled': 31.0, 'price': 0.018941, 'value': 0.587171, 'fee': 0.001761513, 'created_at': 1779913157972},
    '1b16181516': {'order_id': '6a17578642a70a00075963c5', 'filled': 37.0, 'price': 0.019, 'value': 0.703, 'fee': 0.002109, 'created_at': 1779914630060},
    # 1b161c1e42 - REPLACEMENT SAME AS ORIGINAL - NO FILL
    '1b161c1e42': {'order_id': '6a1753eeeaee1500079a122c', 'filled': 0, 'price': 0, 'value': 0, 'fee': 0, 'created_at': 1779913710545},
}

# ============================================================
# TRADE DATA (from CSV + verification)
# ============================================================
# Format: trade_id -> trade data
TRADES = {
    '1b1611d4e': {
        'internal_ts': '2026-05-27T22:17:11.640815',
        'direction': 'MXC->KCN',
        'pair': 'MPC-USDT',
        'strategy': 'USDT',
        'spread_pct': 4.325100517,
        'ex1': 'MXC',
        'ex1_order_id': 'C02__688414456513777664119',
        'ex1_type': 'market',
        'ex1_side': 'buy',
        'ex1_qty_ordered': 137,
        'ex1_qty_filled': 57.72,
        'ex1_price_expected': 0.01741,
        'ex1_price_actual': 0.01741,
        'ex1_value_usdt': 1.0049052,
        'ex1_fees': 0,
        'ex1_create_ts': 1779913032000,
        'ex1_status': 'PARTIAL',
        'ex2': 'KCN',
        'ex2_order_id': '6a17514967c9710007139cef',
        'ex2_type': 'limit',
        'ex2_side': 'sell',
        'ex2_qty_ordered': 58,
        'ex2_qty_filled': 58.0,
        'ex2_price_expected': 0.018163,
        'ex2_price_actual': 0.018163,
        'ex2_value_usdt': 0,  # needs calculation
        'ex2_fees': 0.003160362,
        'ex2_create_ts': 1779913231062,  # needs verification
        'ex2_status': 'FILLED',
        'profit_usdt_expected': 0.0485488,
        'profit_mpc_expected': -0.28,
        'profit_usdt_actual': -0.28,  # needs calculation
        'profit_mpc_actual': -0.28,  # needs calculation
        'limit_watch_status': 'FILLED',
    },
    '1b16111d31': {
        'internal_ts': '2026-05-27T22:17:27.147203',
        'direction': 'MXC->KCN',
        'pair': 'MPC-USDT',
        'strategy': 'USDT',
        'spread_pct': 3.664383562,
        'ex1': 'MXC',
        'ex1_order_id': 'C02__688414521529683969119',
        'ex1_type': 'market',
        'ex1_side': 'buy',
        'ex1_qty_ordered': 158,
        'ex1_qty_filled': 78.07,
        'ex1_price_expected': 0.01752,
        'ex1_price_actual': 0.01752,
        'ex1_value_usdt': 1.3677864,
        'ex1_fees': 0,
        'ex1_create_ts': 1779913048000,
        'ex1_status': 'PARTIAL',
        'ex2': 'KCN',
        'ex2_order_id': '6a17515967c971000713d108',
        'ex2_type': 'limit',
        'ex2_side': 'sell',
        'ex2_qty_ordered': 78,
        'ex2_qty_filled': 78.0,
        'ex2_price_expected': 0.018162,
        'ex2_price_actual': 0.018162,
        'ex2_value_usdt': 0,  # needs calculation
        'ex2_fees': 0.004249908,
        'ex2_create_ts': 1779913269777,
        'ex2_status': 'FILLED',
        'profit_usdt_expected': 0.0488496,
        'profit_mpc_expected': 0.07,
        'profit_usdt_actual': 0.07,
        'profit_mpc_actual': 0.07,
        'limit_watch_status': 'FILLED',
    },
}

def format_timestamp(ts_ms):
    """Convert millisecond timestamp to ISO format"""
    if ts_ms:
        return datetime.fromtimestamp(int(ts_ms)/1000).strftime('%Y-%m-%dT%H:%M:%S.%f')[:-3]
    return ''

def ts_to_date_only(ts_ms):
    """Convert to German date format"""
    if ts_ms:
        return datetime.fromtimestamp(int(ts_ms)/1000).strftime('%d.%m.%Y %H:%M')
    return ''

def ts_to_datetime_only(ts_ms):
    """Convert to datetime format"""
    if ts_ms:
        return datetime.fromtimestamp(int(ts_ms)/1000).strftime('%Y-%m-%d %H:%M:%S.%f')[:-3]
    return ''

# ============================================================
# BUILD OUTPUT CSV
# ============================================================
def build_trade_rows():
    """Build all rows for the CSV output"""
    rows = []
    
    # Header row
    header = 'trade_id;internal_ts;direction;pair;strategy;spread_pct;ex1;ex1_order_id;ex1_type;ex1_side;ex1_qty_ordered;ex1_qty_filled;ex1_price_expected;ex1_price_actual;ex1_value_usdt;ex1_fees;ex1_create_ts;ex1_status;ex2;ex2_order_id;ex2_type;ex2_side;ex2_qty_ordered;ex2_qty_filled;ex2_price_expected;ex2_price_actual;ex2_value_usdt;ex2_fees;ex2_create_ts;ex2_status;profit_usdt_expected;profit_mpc_expected;profit_usdt_actual;profit_mpc_actual;limit_watch_status;limit_last_check;error_code;error_message;raw_ex1_response;raw_ex2_response;raw_ex2_response_ts'
    rows.append(header)
    
    return rows

print("Building corrected trade log CSV...")
print("Based on TRADE_LOG_STRUCTURE.md column layout")
print("\nThis is a reference implementation showing how the bot should write the log.")
print("\nNOTE: The actual CSV data needs to be parsed from the input file first.")