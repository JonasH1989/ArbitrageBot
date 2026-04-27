#!/usr/bin/env python3
"""
Coin Researcher - Automatische Recherche für Arbitrage-Kandidaten
"""

import requests
import json
import time
from datetime import datetime
import re

CG_API = "https://api.coingecko.com/api/v3"

def search_and_research(coin):
    """Recherchiert einen Coin automatisch"""
    results = {
        'coin': coin,
        'found': False,
        'is_meme': False,
        'has_whitepaper': False,
        'description': '',
        'category': '',
        'links': {},
        'risk_level': 'UNKNOWN'
    }
    
    try:
        # 1. CoinGecko Search
        search_resp = requests.get(f"{CG_API}/search?query={coin}", timeout=10)
        if search_resp.status_code == 200:
            data = search_resp.json()
            coins = data.get('coins', [])
            
            if coins:
                top = coins[0]
                results['found'] = True
                results['cg_name'] = top.get('name', '')
                results['cg_symbol'] = top.get('symbol', '').upper()
                results['cg_id'] = top.get('id', '')
                results['cg_thumb'] = top.get('thumb', '')
                
                # 2. Get detailed info if we have ID
                if results['cg_id']:
                    detail_resp = requests.get(
                        f"{CG_API}/coins/{results['cg_id']}?localization=false&tickers=false&market_data=true&community_data=false&developer_data=false",
                        timeout=10
                    )
                    if detail_resp.status_code == 200:
                        detail = detail_resp.json()
                        
                        # Description (truncated)
                        desc = detail.get('description', {}).get('en', '')
                        results['description'] = desc[:300] + '...' if len(desc) > 300 else desc
                        
                        # Category
                        results['category'] = detail.get('categories', ['Unknown'])[0] if detail.get('categories') else 'Unknown'
                        
                        # Links
                        results['links'] = {
                            'website': detail.get('links', {}).get('homepage', [''])[0] if detail.get('links', {}).get('homepage') else '',
                            'whitepaper': detail.get('links', {}).get('whitepaper', '') if detail.get('links') else '',
                            'github': detail.get('links', {}).get('repos_url', {}).get('github', [''])[0] if detail.get('links', {}).get('repos_url') else ''
                        }
                        
                        # Market cap rank
                        results['market_cap_rank'] = detail.get('market_cap_rank')
                        
                        # Check if it's a meme coin
                        meme_keywords = ['meme', 'doge', 'shib', 'pepe', 'floki', 'baby', 'elon', 'inu', 'cat', 'girl', 'boy', 'pup', 'kitty']
                        desc_lower = desc.lower()
                        name_lower = results['cg_name'].lower()
                        
                        if any(k in name_lower for k in meme_keywords) or any(k in desc_lower for k in meme_keywords):
                            results['is_meme'] = True
                        
                        if results['is_meme']:
                            results['risk_level'] = 'HIGH_MEME'
                        elif not results['links']['website'] and not results['links']['whitepaper']:
                            results['risk_level'] = 'MEDIUM_NO_INFO'
                        else:
                            results['risk_level'] = 'LOW'
        
        # Also check for known scam patterns
        scam_patterns = ['free', 'giveaway', 'airdrop', 'claim', 'hodl', 'to the moon', 'diamond hands']
        if any(p in results['description'].lower() for p in scam_patterns):
            results['risk_level'] = 'HIGH_SCAM_RISK'
            
    except Exception as e:
        results['error'] = str(e)
    
    return results

def main():
    print("🚀 Coin Researcher - Automatische Recherche")
    print("=" * 60)
    
    # Load our candidates (sorted by low volume)
    with open('coin_scanner_usdt.json', 'r') as f:
        data = json.load(f)
    
    # Top 15 low-volume coins
    candidates = data['pairs'][:15]
    
    all_results = []
    
    for i, c in enumerate(candidates):
        coin = c['coin']
        print(f"\n🔍 [{i+1}/{len(candidates)}] Researching: {coin}")
        
        result = search_and_research(coin)
        
        # Add scan data
        result['volume_usdt'] = c['avg_usdt_vol']
        result['spread_pct'] = c['spread_pct']
        result['m_price'] = c['m_price']
        result['k_price'] = c['k_price']
        
        # Display
        print(f"   Name: {result.get('cg_name', 'N/A')}")
        print(f"   Risk: {result.get('risk_level', 'UNKNOWN')}")
        print(f"   Meme: {'Yes ❗' if result.get('is_meme') else 'No'}")
        print(f"   Category: {result.get('category', 'N/A')}")
        
        all_results.append(result)
        
        time.sleep(0.5)  # Rate limit
    
    # Save results
    with open('coin_research_results.json', 'w') as f:
        json.dump({
            'timestamp': datetime.now().isoformat(),
            'results': all_results
        }, f, indent=2, ensure_ascii=False)
    
    # Summary
    print("\n" + "=" * 60)
    print("📊 RESEARCH ZUSAMMENFASSUNG")
    print("-" * 60)
    
    low_risk = [r for r in all_results if r.get('risk_level') == 'LOW']
    medium_risk = [r for r in all_results if 'MEDIUM' in r.get('risk_level', '')]
    high_risk = [r for r in all_results if 'HIGH' in r.get('risk_level', '')]
    unknown = [r for r in all_results if r.get('risk_level') == 'UNKNOWN']
    
    print(f"🟢 Low Risk (good for arb): {len(low_risk)}")
    print(f"🟡 Medium Risk: {len(medium_risk)}")
    print(f"🔴 High Risk (shitcoins/scams): {len(high_risk)}")
    print(f"❓ Unknown/Not on CG: {len(unknown)}")
    
    if low_risk:
        print("\n📋 LOW RISK COINS:")
        for r in low_risk:
            print(f"   {r['coin']}: ${r['volume_usdt']:.0f} Vol, {r['spread_pct']:.2f}% Spread")
            print(f"      → {r['cg_name']} ({r.get('category', 'N/A')})")
    
    if high_risk:
        print("\n⚠️ HIGH RISK (avoid):")
        for r in high_risk:
            print(f"   {r['coin']}: {r.get('risk_level')} - {r.get('cg_name', 'N/A')}")
    
    print("\n✅ Gespeichert: coin_research_results.json")

if __name__ == "__main__":
    main()
