"""
Convert old MPCUSDT_trades.csv to new format with ;
separator and proper column names.
"""

import csv
from datetime import datetime

NEW_COLUMNS = [
    "trade_id", "internal_ts", "direction", "pair", "strategy", "spread_pct",
    "ex1", "ex1_order_id", "ex1_type", "ex1_side", "ex1_qty_ordered", "ex1_qty_filled",
    "ex1_price_expected", "ex1_price_actual", "ex1_price_avg", "ex1_value_usdt",
    "ex1_fees", "ex1_create_ts", "ex1_status",
    "ex2", "ex2_order_id", "ex2_type", "ex2_side", "ex2_qty_ordered", "ex2_qty_filled",
    "ex2_price_expected", "ex2_price_actual", "ex2_price_avg", "ex2_value_usdt",
    "ex2_fees", "ex2_create_ts", "ex2_status",
    "profit_usdt_expected", "profit_mpc_expected", "profit_usdt_actual", "profit_mpc_actual",
    "limit_watch_status", "limit_last_check", "error_code", "error_message",
    "raw_ex1_response", "raw_ex2_response", "raw_ex2_response_ts"
]


def fix_row(row):
    """Convert one row from old format to new format."""
    
    # Parse market_side
    market_side = row.get('market_side', '')
    is_kucoin = 'KUCOIN' in market_side
    is_mexc = 'MEXC' in market_side
    
    # Direction: MEXC Buy = MXC->KCN (Buy on MEXC, Sell on KuCoin)
    if is_mexc and is_kucoin:
        direction = "MXC->KCN" if 'Buy' in market_side else "KCN->MXC"
    elif is_mexc:
        direction = "MXC->KCN"  # MEXC Buy = MXC->KCN
    elif is_kucoin:
        direction = "KCN->MXC"  # KUCOIN Buy = KCN->MXC
    else:
        direction = market_side
    
    # Determine exchanges from direction
    if direction == "MXC->KCN":
        ex1_ex, ex2_ex = "MXC", "KCN"
        ex1_side, ex2_side = "buy", "sell"
    else:
        ex1_ex, ex2_ex = "KCN", "MXC"
        ex1_side, ex2_side = "buy", "sell"
    
    # Parse datetime
    dt_str = row.get('datetime', '')
    try:
        dt = datetime.strptime(dt_str, '%d.%m.%Y %H:%M:%S')
        internal_ts = dt.strftime('%Y-%m-%dT%H:%M:%S')
    except:
        internal_ts = dt_str
    
    # Get values from old CSV
    trade_id = row.get('trade_id', '')
    spread = float(row.get('spread', 0) or 0)
    strategy = row.get('strategy', 'USDT')
    market_qty = float(row.get('market_qty', 0) or 0)
    fill_price = float(row.get('fill_price', 0) or 0)
    
    # ex1_fees is in old position 12 (correct!)
    ex1_fees = float(row.get('ex1_fees', 0) or 0)
    
    # ex2 data - SHIFTED:
    # Old position 13: ex2_exchange = actually STATUS ("FILLED")
    # Old position 14: ex2_order_id = actually EXCHANGE name ("KUCOIN")
    old_ex2_status = row.get('ex2_exchange', 'FILLED')  # This is STATUS!
    actual_exchange = row.get('ex2_order_id', ex2_ex)  # This is EXCHANGE!
    
    # Map exchange names to short IDs
    exchange_map = {'KUCOIN': 'KCN', 'MEXC': 'MXC'}
    if actual_exchange in exchange_map:
        actual_exchange = exchange_map[actual_exchange]
    
    # Use actual exchange if valid
    if actual_exchange in ['KCN', 'MXC']:
        ex2_ex = actual_exchange
        ex1_ex = 'MXC' if ex2_ex == 'KCN' else 'KCN'
    
    # ex2 data at correct positions
    ex2_qty = float(row.get('ex2_qty', 0) or 0)
    ex2_price = float(row.get('ex2_price', 0) or 0)
    
    # Calculate values
    ex1_value = market_qty * fill_price
    ex2_value = ex2_qty * ex2_price if ex2_qty > 0 else 0
    
    # Status
    limit_status = 'FILLED' if old_ex2_status == 'FILLED' else old_ex2_status
    
    # Profit
    profit_usdt = float(row.get('profit_usdt', 0) or 0)
    profit_mpc = float(row.get('profit_mpc', 0) or 0)
    
    return {
        'trade_id': trade_id,
        'internal_ts': internal_ts,
        'direction': direction,
        'pair': 'MPC-USDT',
        'strategy': strategy,
        'spread_pct': spread,
        'ex1': ex1_ex,
        'ex1_order_id': row.get('ex1_order_id', ''),
        'ex1_type': 'market',
        'ex1_side': ex1_side,
        'ex1_qty_ordered': market_qty,
        'ex1_qty_filled': market_qty,
        'ex1_price_expected': fill_price,
        'ex1_price_actual': fill_price,
        'ex1_price_avg': fill_price,
        'ex1_value_usdt': ex1_value,
        'ex1_fees': ex1_fees,
        'ex1_create_ts': internal_ts,
        'ex1_status': 'FILLED',
        'ex2': ex2_ex,
        'ex2_order_id': '',  # Not captured in old format
        'ex2_type': 'limit',
        'ex2_side': ex2_side,
        'ex2_qty_ordered': ex2_qty,
        'ex2_qty_filled': ex2_qty if limit_status == 'FILLED' else 0,
        'ex2_price_expected': ex2_price,
        'ex2_price_actual': ex2_price,
        'ex2_price_avg': ex2_price,
        'ex2_value_usdt': ex2_value,
        'ex2_fees': 0,  # Not captured in old format
        'ex2_create_ts': internal_ts,
        'ex2_status': limit_status,
        'profit_usdt_expected': profit_usdt,
        'profit_mpc_expected': profit_mpc,
        'profit_usdt_actual': profit_usdt,
        'profit_mpc_actual': profit_mpc,
        'limit_watch_status': limit_status,
        'limit_last_check': internal_ts,
        'error_code': '',
        'error_message': '',
        'raw_ex1_response': '',
        'raw_ex2_response': '',
        'raw_ex2_response_ts': '',
    }


def convert(input_file, output_file):
    """Convert CSV from old format to new format."""
    
    with open(input_file, 'r', newline='') as f:
        reader = csv.DictReader(f)  # Comma separated
        old_rows = list(reader)
    
    print(f"Read {len(old_rows)} rows")
    
    new_rows = []
    for old in old_rows:
        new = fix_row(old)
        new_rows.append(new)
        
        # Debug output
        if len(new_rows) <= 3:
            print(f"\n{new['trade_id']}: {new['direction']}")
            print(f"  ex1: {new['ex1']} qty={new['ex1_qty_filled']} price={new['ex1_price_actual']:.6f}")
            print(f"  ex2: {new['ex2']} qty={new['ex2_qty_filled']} price={new['ex2_price_actual']:.6f}")
            print(f"  profit_usdt: {new['profit_usdt_actual']}")
    
    # Write new CSV with ; separator
    with open(output_file, 'w', newline='') as f:
        writer = csv.DictWriter(f, fieldnames=NEW_COLUMNS, delimiter=';')
        writer.writeheader()
        writer.writerows(new_rows)
    
    print(f"\nWrote {len(new_rows)} rows to {output_file}")
    
    # Show some statistics
    directions = {}
    for r in new_rows:
        d = r['direction']
        directions[d] = directions.get(d, 0) + 1
    print(f"\nDirection breakdown:")
    for d, c in directions.items():
        print(f"  {d}: {c}")


if __name__ == '__main__':
    input_file = '/home/openclaw/.openclaw/media/inbound/MPC_trades_20260514_1654---e60b281d-155c-436f-9520-32ccc2cf9669.csv'
    output_file = '/home/openclaw/.openclaw/workspace/trading/arbitrage-bot/logs/MPCUSDT_trades_new.csv'
    convert(input_file, output_file)