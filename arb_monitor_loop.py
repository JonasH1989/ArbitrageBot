#!/usr/bin/env python3
"""
Arbitrage Monitor Loop - Runs continuously and alerts on opportunities
"""
import sys
sys.path.insert(0, '/home/openclaw/.openclaw/workspace/trading/arbitrage-bot')

import requests
import yaml
import time
import os
import json
from datetime import datetime

LOG_FILE = '/home/openclaw/.openclaw/logs/arb_monitor.log'
OPP_FILE = '/tmp/arb_opportunity.json'
LAST_ALERT_FILE = '/tmp/arb_last_alert.txt'

def log(msg):
    timestamp = datetime.now().strftime('%H:%M:%S')
    line = f"[{timestamp}] {msg}"
    print(line)
    with open(LOG_FILE, 'a') as f:
        f.write(line + '\n')

def get_prices():
    try:
        resp_k = requests.get('https://api.kucoin.com/api/v1/market/orderbook/level1?symbol=MPC-USDT', timeout=5)
        k_data = resp_k.json()['data']
        k_bid = float(k_data['bestBid'])
        k_ask = float(k_data['bestAsk'])
        
        resp_m = requests.get('https://api.mexc.com/api/v3/ticker/24hr?symbol=MPCUSDT', timeout=5)
        m_data = resp_m.json()
        m_bid = float(m_data['bidPrice'])
        m_ask = float(m_data['askPrice'])
        
        return {'kucoin': {'bid': k_bid, 'ask': k_ask}, 'mexc': {'bid': m_bid, 'ask': m_ask}}
    except:
        return None

def check_and_alert(prices, threshold=0.5):
    if not prices:
        return False
    
    k_bid, k_ask = prices['kucoin']['bid'], prices['kucoin']['ask']
    m_bid, m_ask = prices['mexc']['bid'], prices['mexc']['ask']
    
    # Check M->K (Buy MEXC, Sell KuCoin)
    spread_mk = k_bid - m_ask
    spread_pct_mk = (spread_mk / m_ask) * 100 if m_ask > 0 else 0
    
    # Check K->M (Buy KuCoin, Sell MEXC)  
    spread_km = m_bid - k_ask
    spread_pct_km = (spread_km / k_ask) * 100 if k_ask > 0 else 0
    
    opportunity = None
    direction = None
    
    if spread_mk > 0 and spread_pct_mk >= threshold:
        opportunity = {
            'direction': 'M->K',
            'buy_ex': 'MEXC',
            'sell_ex': 'KuCoin',
            'buy_price': m_ask,
            'sell_price': k_bid,
            'spread': spread_mk,
            'spread_pct': spread_pct_mk,
            'volume': 86,
            'profit_usdt': spread_mk * 86,
            'profit_mpc': (spread_mk * 86) / m_ask
        }
        direction = 'M->K'
    elif spread_km > 0 and spread_pct_km >= threshold:
        opportunity = {
            'direction': 'K->M',
            'buy_ex': 'KuCoin',
            'sell_ex': 'MEXC',
            'buy_price': k_ask,
            'sell_price': m_bid,
            'spread': spread_km,
            'spread_pct': spread_pct_km,
            'volume': 86,
            'profit_usdt': spread_km * 86,
            'profit_mpc': (spread_km * 86) / k_ask
        }
        direction = 'K->M'
    
    if opportunity:
        # Check if we already alerted recently
        should_alert = True
        if os.path.exists(LAST_ALERT_FILE):
            with open(LAST_ALERT_FILE, 'r') as f:
                last = f.read().strip()
                if last == direction:
                    should_alert = False
        
        if should_alert:
            log(f"🚨 OPPORTUNITY FOUND: {direction}!")
            log(f"   Spread: {opportunity['spread_pct']:.2f}% | Profit: ${opportunity['profit_usdt']:.4f}")
            
            # Save opportunity
            with open(OPP_FILE, 'w') as f:
                json.dump({
                    'timestamp': datetime.now().isoformat(),
                    'opportunity': opportunity,
                    'prices': prices
                }, f)
            
            # Remember we alerted
            with open(LAST_ALERT_FILE, 'w') as f:
                f.write(direction)
            
            return True
    
    return False

def main():
    log("=== Arbitrage Monitor Started ===")
    log("Strategy: Coin-Gewinn (MPC akkumulieren)")
    
    check_count = 0
    last_opportunity_time = None
    
    while True:
        check_count += 1
        prices = get_prices()
        
        if prices:
            k = prices['kucoin']
            m = prices['mexc']
            
            # Log every 60 checks (once per minute)
            if check_count % 60 == 0:
                log(f"Prices: K=${k['bid']:.4f}/${k['ask']:.4f} | M=${m['bid']:.4f}/${m['ask']:.4f}")
            
            found = check_and_alert(prices)
            if found:
                last_opportunity_time = datetime.now()
        else:
            if check_count % 60 == 0:
                log("Warning: Could not fetch prices")
        
        time.sleep(1)  # Check every second

if __name__ == '__main__':
    main()
