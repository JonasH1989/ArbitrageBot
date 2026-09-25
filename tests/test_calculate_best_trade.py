#!/usr/bin/env python3
"""Test-Skript: calculate_best_trade Logik simulieren"""
import sys
sys.path.insert(0, '.')

# Mock-Daten für M→K: KuCoin bid (sell) > MEXC ask (buy)
orderbook_mk = {
    'kucoin_bids': [{'price': 0.015462, 'qty': 1000}],  # KuCoin sell (we buy here)
    'mexc_asks': [{'price': 0.015000, 'qty': 500}],     # MEXC buy (we sell here)
    'kucoin_asks': [{'price': 0.015500, 'qty': 1000}],
    'mexc_bids': [{'price': 0.014500, 'qty': 500}],
}

print("="*60)
print("Test 1: M→K profitable (1.55% spread)")
print("="*60)
print(f"KuCoin best bid: {orderbook_mk['kucoin_bids'][0]['price']}")
print(f"MEXC best ask: {orderbook_mk['mexc_asks'][0]['price']}")
spread = (orderbook_mk['kucoin_bids'][0]['price'] - orderbook_mk['mexc_asks'][0]['price']) / orderbook_mk['mexc_asks'][0]['price'] * 100
print(f"Spread M→K: {spread:.3f}%")
print(f"Threshold_start: 1.9%, Threshold_stop: 0.7%")
print(f"Erwartung: spread >= 1.9%? {spread >= 1.9} — True wenn spread >= 1.9%, False wenn < 1.9%")
print(f"Multi-Level Volumen check: L1 KuCoin={orderbook_mk['kucoin_bids'][0]['qty']} MPC, L1 MEXC={orderbook_mk['mexc_asks'][0]['qty']} MPC")
trade_vol = min(orderbook_mk['kucoin_bids'][0]['qty'], orderbook_mk['mexc_asks'][0]['qty'])
print(f"Trade volume (MIN): {trade_vol} MPC")
print()

print("="*60)
print("Test 2: Threshold-Wahl for_follow_up_trade")
print("="*60)
for fut in [True, False]:
    threshold = 0.7 if fut else 1.9
    print(f"for_follow_up_trade={fut} → threshold={threshold}%")
