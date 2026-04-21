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

def execute_trade_M_to_K(qty, buy_price, sell_price):
    """M -> K: Buy MEXC (market), Sell KuCoin (limit)"""
    log(f"=== EXECUTING M->K TRADE ===")
    log(f"Buy MEXC: {qty} MPC @ ${buy_price:.6f}")
    log(f"Sell KuCoin: {qty} MPC @ ${sell_price:.6f}")
    
    # Step 1: Market Buy on MEXC
    log("Step 1: MEXC Market BUY...")
    result1 = execute_market_buy_mexc(qty)
    if result1.get('code') is None or 'orderId' in result1:
        order_id1 = result1.get('orderId', 'unknown')
        log(f"✅ MEXC Order placed: {order_id1}")
    else:
        log(f"❌ MEXC Error: {result1}")
        return False
    
    # Small delay
    time.sleep(0.5)
    
    # Step 2: Limit Sell on KuCoin
    log("Step 2: KuCoin Limit SELL...")
    result2 = execute_limit_sell_kucoin(qty, sell_price)
    if result2.get('code') == '200000':
        order_id2 = result2['data'].get('orderId', 'unknown')
        log(f"✅ KuCoin Order placed: {order_id2}")
    else:
        log(f"❌ KuCoin Error: {result2}")
        return False
    
    # Calculate profit
    cost = qty * buy_price
    revenue = qty * sell_price
    gross_profit = revenue - cost
    fee_taker = cost * 0.001
    fee_maker = revenue * 0.001
    net_profit = gross_profit - fee_taker - fee_maker
    mpc_gain = net_profit / sell_price
    
    log(f"=== TRADE COMPLETED ===")
    log(f"Cost: ${cost:.4f} | Revenue: ${revenue:.4f}")
    log(f"Gross Profit: ${gross_profit:.4f} | Fees: ${fee_taker + fee_maker:.4f}")
    log(f"Net Profit: ${net_profit:.4f} | MPC Gain: {mpc_gain:.4f}")
    
    return True

def execute_trade_K_to_M(qty, buy_price, sell_price):
    """K -> M: Buy KuCoin (market), Sell MEXC (limit)"""
    log(f"=== EXECUTING K->M TRADE ===")
    log(f"Buy KuCoin: {qty} MPC @ ${buy_price:.6f}")
    log(f"Sell MEXC: {qty} MPC @ ${sell_price:.6f}")
    
    # Step 1: Market Buy on KuCoin
    log("Step 1: KuCoin Market BUY...")
    result1 = execute_market_buy_kucoin(qty)
    if result1.get('code') == '200000':
        order_id1 = result1['data'].get('orderId', 'unknown')
        log(f"✅ KuCoin Order placed: {order_id1}")
    else:
        log(f"❌ KuCoin Error: {result1}")
        return False
    
    # Small delay
    time.sleep(0.5)
    
    # Step 2: Limit Sell on MEXC
    log("Step 2: MEXC Limit SELL...")
    result2 = execute_limit_sell_mexc(qty, sell_price)
    if result2.get('code') is None or 'orderId' in result2:
        order_id2 = result2.get('orderId', 'unknown')
        log(f"✅ MEXC Order placed: {order_id2}")
    else:
        log(f"❌ MEXC Error: {result2}")
        return False
    
    # Calculate profit
    cost = qty * buy_price
    revenue = qty * sell_price
    gross_profit = revenue - cost
    fee_taker = cost * 0.001
    fee_maker = revenue * 0.001
    net_profit = gross_profit - fee_taker - fee_maker
    mpc_gain = net_profit / sell_price
    
    log(f"=== TRADE COMPLETED ===")
    log(f"Cost: ${cost:.4f} | Revenue: ${revenue:.4f}")
    log(f"Gross Profit: ${gross_profit:.4f} | Fees: ${fee_taker + fee_maker:.4f}")
    log(f"Net Profit: ${net_profit:.4f} | MPC Gain: {mpc_gain:.4f}")
    
    return True
    
    return True

def main():
    log("=== AUTO-TRADE BOT STARTED ===")
    log("Strategy: Coin-Gewinn (MPC akkumulieren)")
    log("Principle: ONE TRADE AT A TIME")
    
    # Ensure logs directory exists
    os.makedirs('/home/openclaw/.openclaw/logs', exist_ok=True)
    
    threshold = 0.5  # minimum spread %
    trade_in_progress = False
    last_trade_time = 0
    
    while True:
        prices = get_prices()
        if not prices:
            time.sleep(1)
            continue
        
        k = prices['kucoin']
        m = prices['mexc']
        
        # Check M->K (Buy MEXC, Sell KuCoin)
        spread_mk = k['bid'] - m['ask']
        spread_pct_mk = (spread_mk / m['ask']) * 100 if m['ask'] > 0 else 0
        
        # Check K->M (Buy KuCoin, Sell MEXC)
        spread_km = m['bid'] - k['ask']
        spread_pct_km = (spread_km / k['ask']) * 100 if k['ask'] > 0 else 0
        
        # Determine volume (minimum for both exchanges)
        # MEXC requires at least 1 USDT, so calculate MPC qty from that
        vol_for_mexc = int((MEXC_MIN_USDT + 1) / m['ask']) if m['ask'] > 0 else 86  # +1 buffer
        vol_for_kucoin = max(KUCOIN_MIN_MPC, vol_for_mexc)  # Use same or larger for KuCoin
        
        # Log every 30 seconds
        if int(time.time()) % 30 == 0:
            log(f"Prices: K=${k['bid']:.4f}/${k['ask']:.4f} | M=${m['bid']:.4f}/${m['ask']:.4f}")
            log(f"  M->K spread: {spread_pct_mk:.2f}% | K->M spread: {spread_pct_km:.2f}%")
        
        # Trade BOTH directions when profitable!
        # K->M: Buy MEXC (cheaper), Sell KuCoin (more expensive)
        # M->K: Buy KuCoin (cheaper), Sell MEXC (more expensive)
        # Either way, we profit!
        
        if spread_km >= threshold and not trade_in_progress:
            log(f"🚨 K->M OPPORTUNITY: {spread_km:.2f}%")
            trade_in_progress = True
            success = execute_trade_K_to_M(vol_for_kucoin, k['ask'], m['bid'])
            last_trade_time = time.time()
            trade_in_progress = False
        elif spread_mk >= threshold and not trade_in_progress:
            log(f"🚨 M->K OPPORTUNITY: {spread_mk:.2f}%")
            trade_in_progress = True
            success = execute_trade_M_to_K(vol_for_mexc, m['ask'], k['bid'])
            last_trade_time = time.time()
            trade_in_progress = False
        
        time.sleep(1)  # Check every second

if __name__ == '__main__':
    main()
