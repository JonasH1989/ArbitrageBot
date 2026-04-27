#!/usr/bin/env python3
"""
Coin Scanner v3 - Mit CoinGecko Verifizierung
"""

import requests
import json
import time
from datetime import datetime

MEXC_API = "https://api.mexc.com"
KUCOIN_API = "https://api.kucoin.com"
CG_API = "https://api.coingecko.com/api/v3"

def get_cg_price(coin_id):
    """Get price from CoinGecko"""
    try:
        url = f"{CG_API}/simple/price?ids={coin_id}&vs_currencies=usd"
        resp = requests.get(url, timeout=5)
        if resp.status_code == 200:
            data = resp.json()
            if coin_id in data:
                return data[coin_id].get('usd')
    except:
        pass
    return None

def search_cg(symbol):
    """Search CoinGecko for symbol"""
    try:
        url = f"{CG_API}/search?query={symbol}"
        resp = requests.get(url, timeout=5)
        if resp.status_code == 200:
            return resp.json().get('coins', [])
    except:
        pass
    return []

def main():
    print("🚀 Coin Scanner v3 - Mit CoinGecko Verifizierung")
    print("=" * 60)
    
    # Load our scan data
    with open('coin_scanner_usdt.json', 'r') as f:
        data = json.load(f)
    
    candidates = data['pairs'][:30]  # Top 30 by volume
    
    print(f"\n📊 Analyse von {len(candidates)} Low-Volume Kandidaten...")
    
    results = []
    for i, c in enumerate(candidates):
        coin = c['coin']
        m_price = c['m_price']
        k_price = c['k_price']
        spread = c['spread_pct']
        avg_vol = c['avg_usdt_vol']
        
        print(f"\n{i+1}. {coin}")
        print(f"   Preise: M=${m_price:.6f}, K=${k_price:.6f}, Spread={spread:.2f}%")
        print(f"   Vol: ${avg_vol:.0f}")
        
        # CoinGecko search
        cg_results = search_cg(coin)
        
        if cg_results:
            top = cg_results[0]
            cg_symbol = top.get('symbol', '').upper()
            cg_name = top.get('name', '')
            cg_id = top.get('id', '')
            cg_price = get_cg_price(cg_id)
            
            print(f"   CG: {cg_name} ({cg_symbol}) - ${cg_price if cg_price else 'N/A'}")
            
            # Price plausibility check
            if cg_price and cg_price > 0:
                m_diff = abs(m_price - cg_price) / cg_price * 100
                k_diff = abs(k_price - cg_price) / cg_price * 100
                print(f"   Plausibility: MEXC={m_diff:.1f}% vs CG, KuCoin={k_diff:.1f}% vs CG")
                
                # Check if prices match (within 10%)
                if m_diff < 10 and k_diff < 10:
                    status = "✅ GLEICH"
                elif m_diff < 50 or k_diff < 50:
                    status = "⚠️ DIFFERENT?"
                else:
                    status = "❌ ANDERER COIN"
                
                print(f"   → {status}")
                
                results.append({
                    'coin': coin,
                    'cg_name': cg_name,
                    'cg_price': cg_price,
                    'm_price': m_price,
                    'k_price': k_price,
                    'm_diff': m_diff,
                    'k_diff': k_diff,
                    'spread': spread,
                    'avg_vol': avg_vol,
                    'status': status
                })
            else:
                print(f"   → Kein CG Preis")
                results.append({
                    'coin': coin,
                    'cg_name': cg_name,
                    'cg_price': None,
                    'm_price': m_price,
                    'k_price': k_price,
                    'spread': spread,
                    'avg_vol': avg_vol,
                    'status': "❓ KEIN CG PREIS"
                })
        else:
            print(f"   → NICHT GEFUNDEN auf CoinGecko")
            results.append({
                'coin': coin,
                'status': "❌ NICHT AUF CG",
                'm_price': m_price,
                'k_price': k_price,
                'spread': spread,
                'avg_vol': avg_vol
            })
        
        time.sleep(0.3)  # Rate limit
    
    # Summary
    print("\n" + "=" * 60)
    print("📊 ERGEBNIS:")
    print("-" * 60)
    
    verified = [r for r in results if 'GLEICH' in r.get('status', '')]
    different = [r for r in results if 'DIFFERENT' in r.get('status', '')]
    unknown = [r for r in results if r.get('status', '').startswith(('❓', '❌'))]
    
    print(f"✅ Verifiziert (Preis plausibel): {len(verified)}")
    print(f"⚠️ Möglicherweise andere Coins: {len(different)}")
    print(f"❓ Nicht verifizierbar: {len(unknown)}")
    
    if verified:
        print("\n📋 VERIFIZIERTE COINS:")
        for r in verified:
            print(f"   {r['coin']}: ${r['avg_vol']:.0f} Vol, {r['spread']:.2f}% Spread")
    
    # Save
    with open('coin_scanner_verified.json', 'w') as f:
        json.dump({
            'timestamp': datetime.now().isoformat(),
            'results': results,
            'verified': verified,
            'suspicious': different,
            'unknown': unknown
        }, f, indent=2)
    
    print("\n✅ Gespeichert: coin_scanner_verified.json")

if __name__ == "__main__":
    main()
