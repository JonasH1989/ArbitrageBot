#!/usr/bin/env python3
"""Quick scanner to find best arbitrage opportunities"""
import requests
import time

PAIRS = ['BTC-USDT', 'ETH-USDT', 'BNB-USDT', 'SOL-USDT', 'XRP-USDT', 
         'ADA-USDT', 'DOGE-USDT', 'AVAX-USDT', 'DOT-USDT', 'MATIC-USDT',
         'LINK-USDT', 'UNI-USDT', 'ATOM-USDT', 'LTC-USDT', 'ETC-USDT']

def get_prices():
    results = []
    for pair in PAIRS:
        base = pair.split('-')[0]
        
        # MEXC
        try:
            r = requests.get(f"https://api.mexc.com/api/v3/ticker/price?symbol={base}USDT", timeout=5)
            if r.status_code == 200:
                mexc_price = float(r.json()['price'])
            else:
                mexc_price = None
        except:
            mexc_price = None
        
        # Binance
        try:
            r = requests.get(f"https://api.binance.com/api/v3/ticker/bookTicker?symbol={base}USDT", timeout=5)
            if r.status_code == 200:
                d = r.json()
                binance_price = (float(d['bidPrice']) + float(d['askPrice'])) / 2
            else:
                binance_price = None
        except:
            binance_price = None
        
        if mexc_price and binance_price:
            spread = abs(mexc_price - binance_price) / max(mexc_price, binance_price) * 100
            results.append({
                'pair': pair,
                'mexc': mexc_price,
                'binance': binance_price,
                'spread': spread
            })
    
    return sorted(results, key=lambda x: x['spread'], reverse=True)

print("Scanning for arbitrage opportunities...")
print("=" * 60)
for i in range(5):
    results = get_prices()
    print(f"\nScan {i+1}:")
    for r in results[:5]:
        print(f"  {r['pair']}: MEXC ${r['mexc']:.6f} | Binance ${r['binance']:.6f} | Spread: {r['spread']:.4f}%")
    if i < 4:
        time.sleep(3)
