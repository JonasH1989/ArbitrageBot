#!/usr/bin/env python3
"""
Coin Scanner for Arbitrage
- Fetches all trading pairs from MEXC and KuCoin
- Finds common pairs
"""

import requests
import json
import time
from datetime import datetime

MEXC_API = "https://api.mexc.com"
KUCOIN_API = "https://api.kucoin.com"

def get_mexc_symbols():
    """Fetch all USDT trading pairs from MEXC"""
    try:
        resp = requests.get(f"{MEXC_API}/api/v3/exchangeInfo", timeout=10)
        data = resp.json()
        symbols = data.get('symbols', [])
        # Status '1' = Normal trading
        return {s['baseAsset']: s['symbol'] for s in symbols if s['quoteAsset'] == 'USDT' and s['status'] == '1'}
    except Exception as e:
        print(f"MEXC API Error: {e}")
        return {}

def get_kucoin_symbols():
    """Fetch all USDT trading pairs from KuCoin"""
    try:
        resp = requests.get(f"{KUCOIN_API}/api/v1/symbols", timeout=10)
        data = resp.json()
        if data.get('code') == '200000':
            symbols = data.get('data', [])
            return {s['baseCurrency']: s['symbol'] for s in symbols if s['quoteCurrency'] == 'USDT' and s['enableTrading']}
        return {}
    except Exception as e:
        print(f"KuCoin API Error: {e}")
        return {}

def get_mexc_ticker(symbol):
    """Get 24h ticker for a symbol"""
    try:
        resp = requests.get(f"{MEXC_API}/api/v3/ticker/24hr?symbol={symbol}", timeout=5)
        data = resp.json()
        return {
            'volume': float(data.get('volume', 0)),
            'quote_volume': float(data.get('quoteAssetVolume', 0)),
            'price': float(data.get('lastPrice', 0))
        }
    except:
        return None

def get_kucoin_ticker(symbol):
    """Get 24h ticker for a symbol"""
    try:
        kucoin_sym = symbol.replace('USDT', '-USDT')
        resp = requests.get(f"{KUCOIN_API}/api/v1/market/stats?symbol={kucoin_sym}", timeout=5)
        data = resp.json()
        if data.get('code') == '200000':
            t = data.get('data', {})
            return {
                'volume': float(t.get('vol', 0)),
                'quote_volume': float(t.get('volQuote', 0)),
                'price': float(t.get('last', 0))
            }
        return None
    except:
        return None

def main():
    print("🚀 Coin Scanner gestartet...")
    print("=" * 60)
    
    print("\n📡 Lade MEXC Symbols...")
    mexc_symbols = get_mexc_symbols()
    print(f"   MEXC: {len(mexc_symbols)} USDT Paare")
    
    print("\n📡 Lade KuCoin Symbols...")
    kucoin_symbols = get_kucoin_symbols()
    print(f"   KuCoin: {len(kucoin_symbols)} USDT Paare")
    
    # Find common pairs
    common = set(mexc_symbols.keys()) & set(kucoin_symbols.keys())
    print(f"\n✅ Gemeinsame Paare: {len(common)}")
    
    # Save results
    results = {
        'timestamp': datetime.now().isoformat(),
        'mexc_total': len(mexc_symbols),
        'kucoin_total': len(kucoin_symbols),
        'common_count': len(common),
        'common_pairs': sorted(list(common))
    }
    
    with open('coin_scanner_results.json', 'w') as f:
        json.dump(results, f, indent=2)
    
    print(f"\n💾 Resultate: coin_scanner_results.json")
    print(f"\n📊 Erste 30 gemeinsame Paare:")
    for i, pair in enumerate(sorted(common)[:30]):
        print(f"   {i+1:3d}. {pair}")

if __name__ == "__main__":
    main()
