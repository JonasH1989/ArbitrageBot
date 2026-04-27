#!/usr/bin/env python3
"""
Coin Scanner v2 - Volume & Price Data Collection
"""

import requests
import json
import time
from datetime import datetime

MEXC_API = "https://api.mexc.com"
KUCOIN_API = "https://api.kucoin.com"

def get_mexc_symbols():
    resp = requests.get(f"{MEXC_API}/api/v3/exchangeInfo", timeout=10)
    data = resp.json()
    return {s['baseAsset']: s['symbol'] for s in data.get('symbols', []) if s['quoteAsset'] == 'USDT' and s['status'] == '1'}

def get_kucoin_symbols():
    resp = requests.get(f"{KUCOIN_API}/api/v1/symbols", timeout=10)
    data = resp.json()
    if data.get('code') == '200000':
        return {s['baseCurrency']: s['symbol'] for s in data.get('data', []) if s['quoteCurrency'] == 'USDT' and s['enableTrading']}
    return {}

def get_tickers(coin, mexc_sym, kucoin_sym):
    mexc_data = None
    kucoin_data = None
    
    # MEXC ticker
    if mexc_sym:
        try:
            resp = requests.get(f"{MEXC_API}/api/v3/ticker/24hr?symbol={mexc_sym}", timeout=5)
            if resp.status_code == 200:
                d = resp.json()
                mexc_data = {
                    'volume': float(d.get('volume', 0)),
                    'quote_volume': float(d.get('quoteAssetVolume', 0)),
                    'price': float(d.get('lastPrice', 0))
                }
        except:
            pass
    
    # KuCoin ticker
    if kucoin_sym:
        try:
            resp = requests.get(f"{KUCOIN_API}/api/v1/market/stats?symbol={kucoin_sym}", timeout=5)
            if resp.status_code == 200:
                d = resp.json()
                if d.get('code') == '200000':
                    t = d.get('data', {})
                    kucoin_data = {
                        'volume': float(t.get('vol', 0)),
                        'quote_volume': float(t.get('volQuote', 0)),
                        'price': float(t.get('last', 0))
                    }
        except:
            pass
    
    return mexc_data, kucoin_data

def main():
    print("🚀 Coin Scanner v2 - Volume Data Collection")
    print("=" * 60)
    
    # Load symbols
    print("\n📡 Lade Symbol-Mappings...")
    mexc_map = get_mexc_symbols()
    kucoin_map = get_kucoin_symbols()
    
    common = sorted(set(mexc_map.keys()) & set(kucoin_map.keys()))
    print(f"   Gemeinsame Paare: {len(common)}")
    
    # Load cached results
    with open('coin_scanner_results.json', 'r') as f:
        cached = json.load(f)
    
    results = []
    start_time = time.time()
    
    print(f"\n⏳ Starte Volume-Abfrage...")
    for i, coin in enumerate(common):
        mexc_sym = mexc_map.get(coin)
        kucoin_sym = kucoin_map.get(coin)
        
        mexc_t, kucoin_t = get_tickers(coin, mexc_sym, kucoin_sym)
        
        if mexc_t or kucoin_t:
            results.append({
                'coin': coin,
                'mexc': mexc_t,
                'kucoin': kucoin_t
            })
        
        # Progress every 50
        if (i + 1) % 50 == 0:
            elapsed = time.time() - start_time
            eta = (elapsed / (i + 1)) * (len(common) - i - 1)
            print(f"   {i+1}/{len(common)} | ETA: {eta/60:.1f} min")
        
        time.sleep(0.05)  # Be nice to APIs
    
    # Save detailed results
    output = {
        'timestamp': datetime.now().isoformat(),
        'total_pairs': len(common),
        'with_data': len(results),
        'data': results
    }
    
    with open('coin_scanner_full.json', 'w') as f:
        json.dump(output, f)
    
    # Summary by volume
    print("\n📊 Top 20 nach kleinstem Volumen (für Arbitrage interessant):")
    
    # Calculate avg volume
    summary = []
    for r in results:
        m_vol = r['mexc']['quote_volume'] if r['mexc'] else 0
        k_vol = r['kucoin']['quote_volume'] if r['kucoin'] else 0
        avg_vol = (m_vol + k_vol) / 2 if (m_vol and k_vol) else (m_vol or k_vol)
        if avg_vol > 0:
            summary.append({
                'coin': r['coin'],
                'mexc_vol': m_vol,
                'kucoin_vol': k_vol,
                'avg_vol': avg_vol
            })
    
    summary.sort(key=lambda x: x['avg_vol'])
    
    for i, s in enumerate(summary[:20]):
        print(f"   {i+1:2d}. {s['coin']:10s} | Avg Vol: ${s['avg_vol']:,.0f}")
    
    print(f"\n✅ Daten gespeichert: coin_scanner_full.json")
    print(f"   {len(results)} Paare mit Daten")

if __name__ == "__main__":
    main()
