#!/usr/bin/env python3
"""
Arbitrage Auto-Trade Bot
Executes trades automatically when opportunities arise
"""
import sys
sys.path.insert(0, '/home/openclaw/.openclaw/workspace/trading/arbitrage-bot')

import requests
import yaml
import time
import json
import hashlib
import hmac
import base64
import json as json_lib
from datetime import datetime
import os

LOG_FILE = '/home/openclaw/.openclaw/logs/arb_autotrade.log'
CONFIG_FILE = '/home/openclaw/.openclaw/workspace/trading/arbitrage-bot/config/config.yaml'

# Exchange configs
KUCOIN_KEY = "69e6445dd56900000160af01"
KUCOIN_SECRET = "787903d0-bb7f-4d84-b598-c07ac71180ef"
KUCOIN_PASSPHRASE = "YtuyE5uM6hE8HC6"

MEXC_KEY = "mx0vglqkp7DNxtrVO6"
MEXC_SECRET = "880bf82a7761449fa24cc508c6e577fa"

MEXC_MIN_USDT = 1.0
KUCOIN_MIN_MPC = 10

def log(msg):
    ts = datetime.now().strftime('%H:%M:%S')
    line = f"[{ts}] {msg}"
    print(line)
    with open(LOG_FILE, 'a') as f:
        f.write(line + '\n')

def kucoin_sig(secret, ts, method, path, body=''):
    message = f'{ts}{method}{path}{body}'
    mac = hmac.new(secret.encode(), message.encode(), hashlib.sha256)
    return base64.b64encode(mac.digest()).decode()

def get_prices():
    try:
        resp_k = requests.get('https://api.kucoin.com/api/v1/market/orderbook/level1?symbol=MPC-USDT', timeout=5)
        k_data = resp_k.json()['data']
        
        resp_m = requests.get('https://api.mexc.com/api/v3/ticker/24hr?symbol=MPCUSDT', timeout=5)
        m_data = resp_m.json()
        
        return {
            'kucoin': {'bid': float(k_data['bestBid']), 'ask': float(k_data['bestAsk'])},
            'mexc': {'bid': float(m_data['bidPrice']), 'ask': float(m_data['askPrice'])}
        }
    except Exception as e:
        log(f"Error getting prices: {e}")
        return None

def execute_market_buy_kucoin(qty):
    """Buy MPC on KuCoin at market price"""
    ts = str(int(time.time() * 1000))
    body = json_lib.dumps({"clientOid": ts, "symbol": "MPC-USDT", "side": "buy", "type": "market", "size": str(qty)})
    sig = kucoin_sig(KUCOIN_SECRET, ts, 'POST', '/api/v1/orders', body)
    
    headers = {
        'KC-API-KEY': KUCOIN_KEY,
        'KC-API-SIGN': sig,
        'KC-API-TIMESTAMP': ts,
        'KC-API-PASSPHRASE': KUCOIN_PASSPHRASE,
        'Content-Type': 'application/json'
    }
    
    resp = requests.post('https://api.kucoin.com/api/v1/orders', headers=headers, data=body, timeout=10)
    return resp.json()

def execute_limit_sell_kucoin(qty, price):
    """Sell MPC on KuCoin at limit price"""
    ts = str(int(time.time() * 1000))
    body = json_lib.dumps({"clientOid": f"{ts}_sell", "symbol": "MPC-USDT", "side": "sell", "type": "limit", "size": str(qty), "price": f"{price:.6f}"})
    sig = kucoin_sig(KUCOIN_SECRET, ts, 'POST', '/api/v1/orders', body)
    
    headers = {
        'KC-API-KEY': KUCOIN_KEY,
        'KC-API-SIGN': sig,
        'KC-API-TIMESTAMP': ts,
        'KC-API-PASSPHRASE': KUCOIN_PASSPHRASE,
        'Content-Type': 'application/json'
    }
    
    resp = requests.post('https://api.kucoin.com/api/v1/orders', headers=headers, data=body, timeout=10)
    return resp.json()

def execute_market_buy_mexc(qty):
    """Buy MPC on MEXC at market price"""
    ts = str(int(time.time() * 1000))
    params = f'symbol=MPCUSDT&side=BUY&type=MARKET&quantity={qty}&timestamp={ts}'
    sig = hmac.new(MEXC_SECRET.encode('utf-8'), params.encode('utf-8'), hashlib.sha256).hexdigest()
    
    url = f'https://api.mexc.com/api/v3/order?{params}&signature={sig}'
    headers = {'X-MEXC-APIKEY': MEXC_KEY}
    
    resp = requests.post(url, headers=headers, timeout=10)
    return resp.json()

def execute_limit_sell_mexc(qty, price):
    """Sell MPC on MEXC at limit price"""
    ts = str(int(time.time() * 1000))
    params = f'symbol=MPCUSDT&side=SELL&type=LIMIT&quantity={qty}&price={price:.6f}&timestamp={ts}'
    sig = hmac.new(MEXC_SECRET.encode('utf-8'), params.encode('utf-8'), hashlib.sha256).hexdigest()
    
    url = f'https://api.mexc.com/api/v3/order?{params}&signature={sig}'
    headers = {'X-MEXC-APIKEY': MEXC_KEY}
    
    resp = requests.post(url, headers=headers, timeout=10)
    return resp.json()

def check_kucoin_order_status(order_id):
    """Check KuCoin order fill status"""
    ts = str(int(time.time() * 1000))
    method = 'GET'
    path = f'/api/v1/orders/{order_id}'
    
    sig = kucoin_sig(KUCOIN_SECRET, ts, method, path)
    
    headers = {
        'KC-API-KEY': KUCOIN_KEY,
        'KC-API-SIGN': sig,
        'KC-API-TIMESTAMP': ts,
        'KC-API-PASSPHRASE': KUCOIN_PASSPHRASE
    }
    
    resp = requests.get(f'https://api.kucoin.com{path}', headers=headers, timeout=10)
    data = resp.json()
    
    if data.get('code') == '200000':
        o = data['data']
        filled_qty = float(o.get('dealSize', 0))
        total_qty = float(o.get('size', 0))
        is_done = o.get('isActive', True) == False
        return {
            'filled_qty': filled_qty,
            'total_qty': total_qty,
            'is_done': is_done,
            'is_active': o.get('isActive', True),
            'status': o.get('status', 'unknown')
        }
    return None

def check_mexc_order_status(order_id):
    """Check MEXC order fill status"""
    ts = str(int(time.time() * 1000))
    params = f'orderId={order_id}&timestamp={ts}'
    sig = hmac.new(MEXC_SECRET.encode('utf-8'), params.encode('utf-8'), hashlib.sha256).hexdigest()
    
    url = f'https://api.mexc.com/api/v3/order?{params}&signature={sig}'
    headers = {'X-MEXC-APIKEY': MEXC_KEY}
    
    resp = requests.get(url, headers=headers, timeout=10)
    data = resp.json()
    
    if 'orderId' in data:
        filled_qty = float(data.get('executedQty', 0))
        total_qty = float(data.get('origQty', 0))
        status = data.get('status', '')
        return {
            'filled_qty': filled_qty,
            'total_qty': total_qty,
            'is_done': status in ['FILLED', 'CANCELED'],
            'is_active': status == 'NEW',
            'status': status
        }
    return None

def wait_for_limit_fill(exchange, order_id, timeout=60):
    """Wait for limit order to be filled, logging partial fills"""
    start_time = time.time()
    last_logged_fill = 0
    total_qty = 0  # Initialize to avoid UnboundLocalError
    
    while time.time() - start_time < timeout:
        if exchange == 'KuCoin':
            status = check_kucoin_order_status(order_id)
        else:
            status = check_mexc_order_status(order_id)
        
        if status:
            filled = status['filled_qty']
            total_qty = status['total_qty']
            pct = (filled / total_qty * 100) if total_qty > 0 else 0
            
            # Log partial fills
            if filled > last_logged_fill and filled < total_qty:
                log(f"⚠️ PARTIAL FILL: {filled}/{total_qty} MPC ({pct:.1f}%)")
                last_logged_fill = filled
            
            if status['is_done']:
                if filled == total_qty:
                    log(f"✅ LIMIT ORDER FILLED: {filled}/{total_qty} MPC")
                else:
                    log(f"⚠️ LIMIT ORDER PARTIALLY FILLED: {filled}/{total_qty} MPC ({pct:.1f}%)")
                return filled, total_qty, True
        
        time.sleep(2)  # Check every 2 seconds
    
    log(f"⏱️ LIMIT ORDER TIMEOUT: {last_logged_fill}/{total_qty} MPC after {timeout}s")
    return last_logged_fill, total_qty, False

def execute_trade_M_to_K(qty, buy_price, sell_price, strategy='coin'):
    """M -> K: Buy MEXC (market), Sell KuCoin (limit)
    
    COIN-GEWINN STRATEGY (Jonas' correct approach):
    - Buy X MPC on MEXC
    - Calculate: how much USDT we got from selling X MPC at profit
    - The BONUS MPC we can sell = net_profit_usdt / sell_price
    - Sell X + bonus MPC on KuCoin (ALL IN ONE ORDER)
    - Net result: more MPC than we started with!
    """
    log(f"=== EXECUTING M->K TRADE (Coin-Gewinn) ===")
    log(f"Buy MEXC: {qty} MPC @ ${buy_price:.6f}")
    
    # Step 1: Market Buy on MEXC
    log("Step 1: MEXC Market BUY...")
    result1 = execute_market_buy_mexc(qty)
    if result1.get('code') is None or 'orderId' in result1:
        order_id1 = result1.get('orderId', 'unknown')
        log(f"✅ MEXC Order placed: {order_id1}")
    else:
        log(f"❌ MEXC Error: {result1}")
        return False
    
    # Calculate potential profit BEFORE selling
    # We sell the same qty, calculate what we'd make
    gross_profit_estimate = (sell_price - buy_price) * qty
    fee_estimate = (buy_price * qty + sell_price * qty) * 0.001
    net_profit_estimate = gross_profit_estimate - fee_estimate
    
    # Calculate bonus MPC we can afford to sell (the profit adds to sell qty)
    bonus_mpc = 0
    if strategy == 'coin' and net_profit_estimate > 0:
        # Bonus = net_profit / sell_price (how many extra MPC we can sell at profit)
        bonus_mpc = net_profit_estimate / sell_price
        # Cap bonus to reasonable size (e.g., 10% of qty or 100 MPC max)
        bonus_mpc = min(bonus_mpc, qty * 0.1, 100)
        log(f"Coin-Gewinn: Can sell {qty} + {bonus_mpc:.2f} bonus MPC = {qty + bonus_mpc:.2f} total")
    
    # Round to whole numbers for KuCoin compatibility (baseIncrement = 1)
    bonus_mpc = round(bonus_mpc)
    if bonus_mpc < 1:
        bonus_mpc = 0
    total_sell_qty = qty + bonus_mpc
    
    # Step 2: Limit Sell on KuCoin (with bonus included!)
    log(f"Step 2: KuCoin Limit SELL {total_sell_qty} MPC @ ${sell_price:.6f}...")
    result2 = execute_limit_sell_kucoin(total_sell_qty, sell_price)
    if result2.get('code') == '200000':
        order_id2 = result2['data'].get('orderId', 'unknown')
        log(f"✅ KuCoin Order placed: {order_id2}")
        # Track the order
        track_order(order_id2, 'KuCoin', 'sell', total_sell_qty, sell_price, 'M->K', 'MEXC', 'KuCoin')
    else:
        log(f"❌ KuCoin Error: {result2}")
        return False
    
    # Step 3: Wait for Limit Sell to be filled
    log("Step 3: Waiting for KuCoin Limit SELL to fill...")
    filled, total, completed = wait_for_limit_fill('KuCoin', order_id2, timeout=120)
    
    # Calculate actual profit based on filled amount
    # We BOUGHT qty MPC, but SOLD total MPC (including bonus)
    bought_qty = qty
    sold_qty = filled
    mpc_net = sold_qty - bought_qty  # Positive = we gained MPC!
    
    revenue = sold_qty * sell_price
    cost = bought_qty * buy_price
    gross_profit = revenue - cost
    fee_taker = cost * 0.001
    fee_maker = revenue * 0.001
    net_profit_usdt = gross_profit - fee_taker - fee_maker
    
    if completed and filled == total:
        log(f"=== TRADE COMPLETED ===")
    elif filled > 0:
        log(f"=== TRADE PARTIALLY COMPLETED: {filled}/{total} MPC ===")
    else:
        log(f"⚠️ LIMIT SELL FAILED/TIMEOUT: 0 MPC sold!")
        log(f"⚠️ WE BOUGHT {bought_qty} MPC BUT COULDN'T SELL THEM!")
    
    log(f"Bought: {bought_qty} MPC | Sold: {sold_qty:.2f} MPC")
    log(f"MPC Net Change: {mpc_net:+.2f} MPC {'(COIN-GEWINN!)' if mpc_net > 0 else ''}")
    log(f"Revenue: ${revenue:.4f} | Cost: ${cost:.4f}")
    log(f"Gross Profit: ${gross_profit:.4f} | Fees: ${fee_taker + fee_maker:.4f}")
    log(f"Net USDT Profit: ${net_profit_usdt:.4f}")
    
    # CRITICAL: If we bought but couldn't sell, this is a FAILED trade!
    # Return False so main loop doesn't start next trade
    if filled == 0 and bought_qty > 0:
        log(f"❌ TRADE FAILED: Cannot proceed without selling!")
        return False
    
    return completed

def execute_trade_K_to_M(qty, buy_price, sell_price, strategy='coin'):
    """K -> M: Buy KuCoin (market), Sell MEXC (limit)
    
    COIN-GEWINN STRATEGY (Jonas' correct approach):
    - Buy X MPC on KuCoin
    - Calculate: how much USDT we got from selling X MPC at profit
    - The BONUS MPC we can sell = net_profit_usdt / sell_price
    - Sell X + bonus MPC on MEXC (ALL IN ONE ORDER)
    - Net result: more MPC than we started with!
    """
    log(f"=== EXECUTING K->M TRADE (Coin-Gewinn) ===")
    log(f"Buy KuCoin: {qty} MPC @ ${buy_price:.6f}")
    
    # Step 1: Market Buy on KuCoin
    log("Step 1: KuCoin Market BUY...")
    result1 = execute_market_buy_kucoin(qty)
    if result1.get('code') == '200000':
        order_id1 = result1['data'].get('orderId', 'unknown')
        log(f"✅ KuCoin Order placed: {order_id1}")
    else:
        log(f"❌ KuCoin Error: {result1}")
        return False
    
    # Calculate potential profit BEFORE selling
    gross_profit_estimate = (sell_price - buy_price) * qty
    fee_estimate = (buy_price * qty + sell_price * qty) * 0.001
    net_profit_estimate = gross_profit_estimate - fee_estimate
    
    # Calculate bonus MPC we can afford to sell (the profit adds to sell qty)
    bonus_mpc = 0
    if strategy == 'coin' and net_profit_estimate > 0:
        # Bonus = net_profit / sell_price (how many extra MPC we can sell at profit)
        bonus_mpc = net_profit_estimate / sell_price
        # Cap bonus to reasonable size (e.g., 10% of qty or 100 MPC max)
        bonus_mpc = min(bonus_mpc, qty * 0.1, 100)
        # Round to 2 decimal places for MEXC compatibility
        bonus_mpc = round(bonus_mpc, 2)
        if bonus_mpc < 0.01:
            bonus_mpc = 0
        log(f"Coin-Gewinn: Can sell {qty} + {bonus_mpc:.2f} bonus MPC = {qty + bonus_mpc:.2f} total")
    
    total_sell_qty = qty + bonus_mpc
    
    # Step 2: Limit Sell on MEXC (with bonus included!)
    log(f"Step 2: MEXC Limit SELL {total_sell_qty:.2f} MPC @ ${sell_price:.6f}...")
    result2 = execute_limit_sell_mexc(total_sell_qty, sell_price)
    if result2.get('code') is None or 'orderId' in result2:
        order_id2 = result2.get('orderId', 'unknown')
        log(f"✅ MEXC Order placed: {order_id2}")
        # Track the order
        track_order(order_id2, 'MEXC', 'sell', total_sell_qty, sell_price, 'K->M', 'KuCoin', 'MEXC')
    else:
        log(f"❌ MEXC Error: {result2}")
        return False
    
    # Step 3: Wait for Limit Sell on MEXC to be filled
    log("Step 3: Waiting for MEXC Limit SELL to fill...")
    filled, total, completed = wait_for_limit_fill('MEXC', order_id2, timeout=120)
    
    # Calculate actual profit based on filled amount
    # We BOUGHT qty MPC, but SOLD total MPC (including bonus)
    bought_qty = qty
    sold_qty = filled
    mpc_net = sold_qty - bought_qty  # Positive = we gained MPC!
    
    revenue = sold_qty * sell_price
    cost = bought_qty * buy_price
    gross_profit = revenue - cost
    fee_taker = cost * 0.001
    fee_maker = revenue * 0.001
    net_profit_usdt = gross_profit - fee_taker - fee_maker
    
    if completed and filled == total:
        log(f"=== TRADE COMPLETED ===")
    elif filled > 0:
        log(f"=== TRADE PARTIALLY COMPLETED: {filled}/{total} MPC ===")
    else:
        log(f"⚠️ LIMIT SELL FAILED/TIMEOUT: 0 MPC sold!")
        log(f"⚠️ WE BOUGHT {bought_qty} MPC BUT COULDN'T SELL THEM!")
    
    log(f"Bought: {bought_qty} MPC | Sold: {sold_qty:.2f} MPC")
    log(f"MPC Net Change: {mpc_net:+.2f} MPC {'(COIN-GEWINN!)' if mpc_net > 0 else ''}")
    log(f"Revenue: ${revenue:.4f} | Cost: ${cost:.4f}")
    log(f"Gross Profit: ${gross_profit:.4f} | Fees: ${fee_taker + fee_maker:.4f}")
    log(f"Net USDT Profit: ${net_profit_usdt:.4f}")
    
    # CRITICAL: If we bought but couldn't sell, this is a FAILED trade!
    if filled == 0 and bought_qty > 0:
        log(f"❌ TRADE FAILED: Cannot proceed without selling!")
        return False
    
    return completed

def load_order_tracker():
    """Load order tracker from file"""
    try:
        with open(ORDER_TRACKER_FILE, 'r') as f:
            return json.load(f)
    except:
        return {}

def save_order_tracker(tracker):
    """Save order tracker to file"""
    with open(ORDER_TRACKER_FILE, 'w') as f:
        json.dump(tracker, f, indent=2)

def track_order(order_id, exchange, side, qty, price, direction, buy_exchange, sell_exchange):
    """Track a new order"""
    tracker = load_order_tracker()
    tracker[order_id] = {
        'order_id': order_id,
        'exchange': exchange,
        'side': side,
        'qty': qty,
        'price': price,
        'filled': 0,
        'direction': direction,  # 'M->K' or 'K->M'
        'buy_exchange': buy_exchange,
        'sell_exchange': sell_exchange,
        'status': 'PENDING',  # PENDING, FILLED, PARTIAL, CANCELLED, FAILED
        'placed_at': time.strftime('%Y-%m-%d %H:%M:%S'),
        'updated_at': time.strftime('%Y-%m-%d %H:%M:%S')
    }
    save_order_tracker(tracker)
    log(f"📝 Order tracked: {order_id} ({exchange})")

def update_order_status(order_id, filled, total, status):
    """Update order status"""
    tracker = load_order_tracker()
    if order_id in tracker:
        tracker[order_id]['filled'] = filled
        tracker[order_id]['total'] = total
        tracker[order_id]['status'] = status
        tracker[order_id]['updated_at'] = time.strftime('%Y-%m-%d %H:%M:%S')
        save_order_tracker(tracker)
        log(f"📝 Order updated: {order_id} -> {status} ({filled}/{total})")

def get_pending_orders():
    """Get all pending orders"""
    tracker = load_order_tracker()
    pending = [o for o in tracker.values() if o['status'] == 'PENDING']
    return pending

def check_pending_orders():
    """Check status of all pending orders and update if filled"""
    pending = get_pending_orders()
    if not pending:
        return
    
    log(f"🔍 Checking {len(pending)} pending orders...")
    
    for order in pending:
        order_id = order['order_id']
        exchange = order['exchange']
        
        # Check KuCoin orders
        if exchange == 'KuCoin':
            ts = str(int(time.time() * 1000))
            method = 'GET'
            path = f'/api/v1/orders/{order_id}'
            
            message = f'{ts}{method}{path}'
            mac = hmac.new(KUCOIN_SECRET.encode(), message.encode(), hashlib.sha256)
            signature = base64.b64encode(mac.digest()).decode()
            
            headers = {
                'KC-API-KEY': KUCOIN_KEY,
                'KC-API-SIGN': signature,
                'KC-API-TIMESTAMP': ts,
                'KC-API-PASSPHRASE': KUCOIN_PASSPHRASE
            }
            
            resp = requests.get(f'https://api.kucoin.com{path}', headers=headers, timeout=10)
            data = resp.json()
            
            if data.get('code') == '200000':
                o = data['data']
                filled = float(o.get('dealSize', 0))
                total = float(o.get('size', 0))
                is_active = o.get('isActive', True)
                
                if not is_active:
                    if filled == total:
                        update_order_status(order_id, filled, total, 'FILLED')
                    elif filled > 0:
                        update_order_status(order_id, filled, total, 'PARTIAL')
                    else:
                        update_order_status(order_id, filled, total, 'CANCELLED')
        
        # Check MEXC orders
        elif exchange == 'MEXC':
            ts = str(int(time.time() * 1000))
            params = f'orderId={order_id}&timestamp={ts}'
            sig = hmac.new(MEXC_SECRET.encode('utf-8'), params.encode('utf-8'), hashlib.sha256).hexdigest()
            
            url = f'https://api.mexc.com/api/v3/order?{params}&signature={sig}'
            headers = {'X-MEXC-APIKEY': MEXC_KEY}
            
            resp = requests.get(url, headers=headers, timeout=10)
            data = resp.json()
            
            if 'orderId' in data:
                filled = float(data.get('executedQty', 0))
                total = float(data.get('origQty', 0))
                status = data.get('status', '')
                
                if status == 'FILLED':
                    update_order_status(order_id, filled, total, 'FILLED')
                elif status in ['CANCELED', 'EXPIRED']:
                    update_order_status(order_id, filled, total, 'CANCELLED')
                elif filled > 0:
                    update_order_status(order_id, filled, total, 'PARTIAL')
