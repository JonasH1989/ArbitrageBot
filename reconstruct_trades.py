#!/usr/bin/env python3
"""
Parse arb_live_log.txt and reconstruct trades that were logged.
This extracts trade details from the log for dates where CSV may be incomplete.
"""
import re
import csv
from datetime import datetime
from pathlib import Path

LOG_FILE = '/home/openclaw/.openclaw/logs/arb_live_log.txt'
OUTPUT_CSV = '/home/openclaw/.openclaw/logs/MPC-USDT_trades.csv'

# 41-column header
HEADER = [
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

def parse_log_for_trades():
    """Parse the live log file and extract trade information."""
    
    trades = []
    
    with open(LOG_FILE, 'r') as f:
        content = f.read()
    
    # Split into lines
    lines = content.split('\n')
    
    # Regex patterns
    trade_pattern = re.compile(r'\[(\d{2}:\d{2}:\d{2})\] \[INFO\s*\] (?:📝 Trade logged.*?: (\S+)|EXECUTING TRADE (\w+)->(\w+) \(strategy=(\w+)\))')
    market_buy_pattern = re.compile(r'Market BUY on (\w+): (\d+(?:\.\d+)?) MPC @ \$(\d+\.\d+)')
    limit_sell_pattern = re.compile(r'Limit SELL on (\w+): @ \$(\d+\.\d+)')
    balance_pattern = re.compile(r'✅ Balance check passed|BALANCE CHECK FAILED')
    order_placed_pattern = re.compile(r'✅ (\w+) Order placed: (\S+)')
    step_pattern = re.compile(r'Step (\d): (\w+) (Market BUY|Limit SELL)')
    
    current_trade = None
    current_block = []
    
    for line in lines:
        # Check for trade execution start
        if 'EXECUTING TRADE' in line:
            # Extract direction
            if 'M->K' in line or 'M→K' in line:
                direction = 'M->K'
            elif 'K->M' in line or 'K→M' in line:
                direction = 'K->M'
            else:
                continue
            
            # Extract strategy
            strategy_match = re.search(r'strategy=(\w+)', line)
            strategy = strategy_match.group(1) if strategy_match else 'USDT'
            
            # Extract time
            time_match = re.search(r'\[(\d{2}:\d{2}:\d{2})\]', line)
            time_str = time_match.group(1) if time_match else '00:00:00'
            
            current_trade = {
                'direction': direction,
                'strategy': strategy.upper(),
                'time': time_str,
                'market_exchange': None,
                'limit_exchange': None,
                'qty': 0,
                'buy_price': 0,
                'sell_price': 0,
                'balance_passed': False,
                'ex1_order_id': None,
                'ex2_order_id': None,
                'status': 'UNKNOWN'
            }
            current_block = [line]
            
        elif current_trade and line.strip():
            current_block.append(line)
            
            # Parse Market BUY
            if 'Market BUY on' in line:
                match = market_buy_pattern.search(line)
                if match:
                    current_trade['market_exchange'] = match.group(1)
                    current_trade['qty'] = float(match.group(2))
                    current_trade['buy_price'] = float(match.group(3))
            
            # Parse Limit SELL
            elif 'Limit SELL on' in line:
                match = limit_sell_pattern.search(line)
                if match:
                    current_trade['limit_exchange'] = match.group(1)
                    current_trade['sell_price'] = float(match.group(2))
            
            # Check balance
            elif '✅ Balance check passed' in line:
                current_trade['balance_passed'] = True
            elif 'BALANCE CHECK FAILED' in line:
                current_trade['balance_passed'] = False
                current_trade['status'] = 'REJECTED'
            
            # Check order placement
            elif '✅' in line and 'Order placed:' in line:
                match = re.search(r'✅ (\w+) Order placed: (\S+)', line)
                if match:
                    exch = match.group(1)
                    order_id = match.group(2)
                    if exch == 'MEXC' or exch == 'KUCOIN':
                        if current_trade['market_exchange'] == exch:
                            current_trade['ex1_order_id'] = order_id
                        else:
                            current_trade['ex2_order_id'] = order_id
            
            # Check if trade completed
            elif '📝 Trade logged' in line:
                match = re.search(r'📝 Trade logged.*?(\S+)', line)
                if match:
                    current_trade['trade_id'] = match.group(1)
                    
                    if 'error' in line:
                        current_trade['status'] = 'ERROR'
                    else:
                        current_trade['status'] = 'SUCCESS'
                    
                    # Calculate timestamps
                    today = datetime.now().strftime('%Y-%m-%d')
                    ts = datetime.strptime(f"{today} {current_trade['time']}", '%Y-%m-%d %H:%M:%S')
                    current_trade['internal_ts'] = ts.isoformat()
                    current_trade['updated_at'] = ts.isoformat()
                    
                    trades.append(current_trade)
                    current_trade = None
                    current_block = []
    
    return trades


def trades_to_csv(trades, output_csv):
    """Write parsed trades to CSV."""
    
    # Read existing trades from CSV
    existing_ids = set()
    existing_rows = []
    
    try:
        with open(output_csv, 'r', newline='') as f:
            reader = csv.DictReader(f)
            for row in reader:
                existing_ids.add(row['trade_id'])
                existing_rows.append(row)
    except FileNotFoundError:
        pass
    
    # Filter out trades we already have
    new_trades = [t for t in trades if t.get('trade_id') and t['trade_id'] not in existing_ids]
    
    if not new_trades:
        print(f"No new trades to add (found {len(existing_ids)} existing)")
        return 0
    
    # Write all trades
    with open(output_csv, 'w', newline='') as f:
        writer = csv.DictWriter(f, fieldnames=HEADER)
        writer.writeheader()
        
        # Write existing
        writer.writerows(existing_rows)
        
        # Write new
        for t in new_trades:
            row = {
                'trade_id': t.get('trade_id', ''),
                'internal_ts': t.get('internal_ts', ''),
                'direction': t.get('direction', ''),
                'pair': 'MPC-USDT',
                'strategy': t.get('strategy', ''),
                'spread_pct': t.get('spread_pct', 0),
                'ex1_exchange': t.get('market_exchange', ''),
                'ex1_order_id': t.get('ex1_order_id', ''),
                'ex1_type': 'market',
                'ex1_side': 'buy' if t.get('direction') == 'M->K' else 'sell',
                'ex1_qty_ordered': t.get('qty', 0),
                'ex1_qty_filled': t.get('qty', 0) if t.get('status') == 'SUCCESS' else 0,
                'ex1_price_expected': t.get('buy_price', 0),
                'ex1_price_actual': t.get('buy_price', 0),
                'ex1_value_usdt': t.get('qty', 0) * t.get('buy_price', 0),
                'ex1_fees': 0,
                'ex1_create_ts': 0,
                'ex1_status': 'FILLED' if t.get('status') == 'SUCCESS' else 'REJECTED',
                'ex2_exchange': t.get('limit_exchange', ''),
                'ex2_order_id': t.get('ex2_order_id', ''),
                'ex2_type': 'limit',
                'ex2_side': 'sell' if t.get('direction') == 'M->K' else 'buy',
                'ex2_qty_ordered': t.get('qty', 0) * 0.99,  # coins strategy = slightly less
                'ex2_qty_filled': 0,
                'ex2_price_expected': t.get('sell_price', 0),
                'ex2_price_actual': 0,
                'ex2_value_usdt': 0,
                'ex2_fees': 0,
                'ex2_create_ts': 0,
                'ex2_status': 'PENDING',
                'profit_usdt_expected': 0,
                'profit_mpc_expected': 0,
                'profit_usdt_actual': 0,
                'profit_mpc_actual': 0,
                'limit_watch_status': 'WATCHING' if t.get('status') == 'SUCCESS' else 'ERROR',
                'limit_last_check': '',
                'error_code': 'BALANCE_CHECK_FAILED' if t.get('status') == 'REJECTED' else '',
                'error_message': 'Balance check failed - insufficient funds' if t.get('status') == 'REJECTED' else '',
                'raw_ex1_response': '{}',
                'raw_ex2_response': '{}',
                'updated_at': t.get('updated_at', ''),
            }
            writer.writerow(row)
    
    return len(new_trades)


if __name__ == '__main__':
    print("Parsing arb_live_log.txt for trades...")
    trades = parse_log_for_trades()
    
    print(f"Found {len(trades)} trades in log")
    
    # Show summary
    success = sum(1 for t in trades if t.get('status') == 'SUCCESS')
    rejected = sum(1 for t in trades if t.get('status') == 'REJECTED')
    unknown = sum(1 for t in trades if t.get('status') == 'UNKNOWN')
    
    print(f"  SUCCESS: {success}")
    print(f"  REJECTED: {rejected}")
    print(f"  UNKNOWN: {unknown}")
    
    # Write to CSV
    count = trades_to_csv(trades, OUTPUT_CSV)
    print(f"\nAdded {count} new trades to CSV")