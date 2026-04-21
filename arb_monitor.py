#!/usr/bin/env python3
"""
Arbitrage Monitor - Check for trading opportunities
Runs as a cron job and alerts when opportunities arise
"""

import sys
sys.path.insert(0, '/home/openclaw/.openclaw/workspace/trading/arbitrage-bot')

import requests
import yaml
import time
from datetime import datetime

# Load config
with open('/home/openclaw/.openclaw/workspace/trading/arbitrage-bot/config/config.yaml', 'r') as f:
    config = yaml.safe_load(f)

# Exchange minimums (USDT value)
MEXC_MIN_USDT = 1.0
KUCOIN_MIN_MPC = 10

def get_prices():
    """Get current bid/ask from both exchanges"""
    try:
        # KuCoin
        resp_k = requests.get('https://api.kucoin.com/api/v1/market/orderbook/level1?symbol=MPC-USDT', timeout=5)
        k_data = resp_k.json()['data']
        k_bid = float(k_data['bestBid'])
        k_ask = float(k_data['bestAsk'])
        
        # MEXC
        resp_m = requests.get('https://api.mexc.com/api/v3/ticker/24hr?symbol=MPCUSDT', timeout=5)
        m_data = resp_m.json()
        m_bid = float(m_data['bidPrice'])
        m_ask = float(m_data['askPrice'])
        
        return {
            'kucoin': {'bid': k_bid, 'ask': k_ask},
            'mexc': {'bid': m_bid, 'ask': m_ask}
        }
    except Exception as e:
        print(f"Error getting prices: {e}")
        return None

def check_opportunities(prices, threshold_pct=0.5):
    """Check for arbitrage opportunities"""
    k_bid, k_ask = prices['kucoin']['bid'], prices['kucoin']['ask']
    m_bid, m_ask = prices['mexc']['bid'], prices['mexc']['ask']
    
    opportunities = []
    
    # Direction 1: K -> M (Buy KuCoin, Sell MEXC)
    # Buy on KuCoin Ask, Sell on MEXC Bid
    spread_km = m_bid - k_ask
    spread_pct_km = (spread_km / k_ask) * 100 if k_ask > 0 else 0
    
    # Calculate volumes
    vol_km = KUCOIN_MIN_MPC  # KuCoin minimum
    mexc_vol_for_min = MEXC_MIN_USDT / m_bid if m_bid > 0 else 0
    
    if spread_km > 0 and spread_pct_km >= threshold_pct:
        opportunities.append({
            'direction': 'K->M',
            'buy_ex': 'KuCoin',
            'sell_ex': 'MEXC',
            'buy_price': k_ask,
            'sell_price': m_bid,
            'spread': spread_km,
            'spread_pct': spread_pct_km,
            'volume': vol_km,
            'profit_usdt': spread_km * vol_km,
            'profit_mpc': (spread_km * vol_km) / k_ask
        })
    
    # Direction 2: M -> K (Buy MEXC, Sell KuCoin)
    # Buy on MEXC Ask, Sell on KuCoin Bid
    spread_mk = k_bid - m_ask
    spread_pct_mk = (spread_mk / m_ask) * 100 if m_ask > 0 else 0
    
    vol_mk = max(KUCOIN_MIN_MPC, mexc_vol_for_min)
    
    if spread_mk > 0 and spread_pct_mk >= threshold_pct:
        opportunities.append({
            'direction': 'M->K',
            'buy_ex': 'MEXC',
            'sell_ex': 'KuCoin',
            'buy_price': m_ask,
            'sell_price': k_bid,
            'spread': spread_mk,
            'spread_pct': spread_pct_mk,
            'volume': vol_mk,
            'profit_usdt': spread_mk * vol_mk,
            'profit_mpc': (spread_mk * vol_mk) / m_ask
        })
    
    return opportunities

def main():
    timestamp = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    print(f"\n[{timestamp}] Checking Arbitrage Opportunities...")
    
    prices = get_prices()
    if not prices:
        print("Failed to get prices")
        return
    
    k = prices['kucoin']
    m = prices['mexc']
    
    print(f"  KuCoin: Bid=${k['bid']:.6f} | Ask=${k['ask']:.6f}")
    print(f"  MEXC:   Bid=${m['bid']:.6f} | Ask=${m['ask']:.6f}")
    
    # Get threshold from config
    threshold = config.get('trading', {}).get('thresholds', {}).get('start', 0.5)
    
    opportunities = check_opportunities(prices, threshold)
    
    if opportunities:
        print(f"\n  🚨 FOUND {len(opportunities)} OPPORTUNITY(IES)!")
        for opp in opportunities:
            print(f"\n  Direction: {opp['direction']}")
            print(f"  Buy:  {opp['buy_ex']} @ ${opp['buy_price']:.6f}")
            print(f"  Sell: {opp['sell_ex']} @ ${opp['sell_price']:.6f}")
            print(f"  Spread: {opp['spread_pct']:.2f}%")
            print(f"  Volume: {opp['volume']:.0f} MPC")
            print(f"  Profit: ${opp['profit_usdt']:.4f} | {opp['profit_mpc']:.4f} MPC")
            
            # Save opportunity for alerting
            with open('/tmp/arb_opportunity.json', 'w') as f:
                import json
                json.dump({
                    'timestamp': timestamp,
                    'opportunity': opp,
                    'prices': prices
                }, f)
    else:
        print(f"\n  No opportunities (threshold: {threshold}%)")
        # Clear any old opportunity
        try:
            import os
            os.remove('/tmp/arb_opportunity.json')
        except:
            pass

if __name__ == '__main__':
    main()
