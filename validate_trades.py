#!/usr/bin/env python3
"""
Trade Log Validator - Process trades and query API for missing data
Uses KuCoin read-only API to verify and fill missing data
"""
import hmac
import hashlib
import base64
import time
import json
import csv
from datetime import datetime

# ============================================================
# KUCOIN CREDENTIALS (from config.yaml)
# ============================================================
KUCOIN_KEY = "69e542868294a100018f076f"
KUCOIN_SECRET = "899189f7-e6fa-4ea4-ad0c-dfd43506ef30"
KUCOIN_PASSPHRASE = "6GEWzwgmfDyjgDk"

# ============================================================
# KUCOIN HELPER FUNCTIONS
# ============================================================
def kucoin_passphrase_enc(secret, passphrase):
    mac = hmac.new(secret.encode(), passphrase.encode(), hashlib.sha256)
    return base64.b64encode(mac.digest()).decode()

def kucoin_sig(secret, timestamp, method, path, body=''):
    message = f'{timestamp}{method}{path}{body}'
    return base64.b64encode(hmac.new(secret.encode(), message.encode(), hashlib.sha256).digest()).decode()

def kucoin_request(method, path, body=''):
    timestamp = str(int(time.time() * 1000))
    sig = kucoin_sig(KUCOIN_SECRET, timestamp, method, path, body)
    passphrase_enc = kucoin_passphrase_enc(KUCOIN_SECRET, KUCOIN_PASSPHRASE)
    headers = {
        'KC-API-KEY': KUCOIN_KEY,
        'KC-API-SIGN': sig,
        'KC-API-TIMESTAMP': timestamp,
        'KC-API-PASSPHRASE': passphrase_enc,
        'KC-API-KEY-VERSION': '2'
    }
    url = f'https://api.kucoin.com{path}'
    import requests
    resp = requests.request(method, url, headers=headers, timeout=10)
    return resp.json()

# ============================================================
# REPLACEMENT ORDERS (from previous analysis)
# ============================================================
REPLACEMENT_ORDERS = {
    '1b16113062': '6a1751979c8d050007ecf50d',
    '1b16113647': '6a1751910970a10007e9173d',
    '1b16122f50': '6a1751c530aa00000711dc0d',
    '1b16181516': '6a17578642a70a00075963c5',
    '1b161c1e42': '6a1753eeeaee1500079a122c',
}

# ============================================================
# TRADE DATA (from CSV analysis)
# ============================================================
TRADES = [
    # Trade 1: 1b1611d4e - COMPLETE (FILLED)
    {'trade_id': '1b1611d4e', 'ex1_order': 'C02__688414456513777664119', 'ex2_order': '6a17514967c9710007139cef',
     'ex1_filled': 57.72, 'ex2_filled': 58.0, 'ex2_fees': 0.003160362},
    # Trade 2: 1b16111d31 - COMPLETE (FILLED)
    {'trade_id': '1b16111d31', 'ex1_order': 'C02__688414521529683969119', 'ex2_order': '6a17515967c971000713d108',
     'ex1_filled': 78.07, 'ex2_filled': 78.0, 'ex2_fees': 0.004249908},
    # Trade 3: 1b1611211e - COMPLETE (FILLED)
    {'trade_id': '1b1611211e', 'ex1_order': 'C02__688414538755608579119', 'ex2_order': '6a17515d1296f100074afb9f',
     'ex1_filled': 83.15, 'ex2_filled': 83.0, 'ex2_fees': 0.004522338},
    # Trade 4: 1b16113062 - CANCELLED (replacement needed)
    {'trade_id': '1b16113062', 'ex1_order': 'C02__688414602798489601119', 'ex2_order': '6a17516caf78b5000775da5a',
     'ex1_filled': 32.97, 'ex2_filled': 0, 'ex2_fees': 0, 'original_cancelled': True},
    # Trade 5: 1b16113647 - CANCELLED (replacement needed)
    {'trade_id': '1b16113647', 'ex1_order': 'C02__688414627339358208119', 'ex2_order': '6a175172571a870007c90fa9',
     'ex1_filled': 67.73, 'ex2_filled': 0, 'ex2_fees': 0, 'original_cancelled': True},
    # Trade 6: 1b16121b13 - COMPLETE (FILLED)
    {'trade_id': '1b16121b13', 'ex1_order': 'C02__688414764631461888119', 'ex2_order': '6a1751931296f100074bae96',
     'ex1_filled': 183.0, 'ex2_filled': 183.0, 'ex2_fees': 0.009963252},
    # Trade 7: 1b1612202e - COMPLETE (FILLED)
    {'trade_id': '1b1612202e', 'ex1_order': 'C02__688414786253148160119', 'ex2_order': '6a175198f7247100073a7423',
     'ex1_filled': 144.0, 'ex2_filled': 144.0, 'ex2_fees': 0.007839936},
    # Trade 8: 1b16122f50 - CANCELLED (replacement needed)
    {'trade_id': '1b16122f50', 'ex1_order': 'C02__688414850790903809119', 'ex2_order': '6a1751a76950e40007d52a0a',
     'ex1_filled': 30.95, 'ex2_filled': 0, 'ex2_fees': 0, 'original_cancelled': True},
    # Trade 9: 1b16181516 - CANCELLED (replacement needed)
    {'trade_id': '1b16181516', 'ex1_order': 'C02__688416249486381056119', 'ex2_order': '6a1752f5a7f17f000770d374',
     'ex1_filled': 36.52, 'ex2_filled': 0, 'ex2_fees': 0, 'original_cancelled': True},
    # Trade 10: 1b161c1a45 - COMPLETE (FILLED)
    {'trade_id': '1b161c1a45', 'ex1_order': 'C02__688417278021996544119', 'ex2_order': '6a1753ea8d7f740007fc976b',
     'ex1_filled': 250.0, 'ex2_filled': 250.0, 'ex2_fees': 0.0135345},
    # Trade 11: 1b161c1e42 - CANCELLED (replacement needed)
    {'trade_id': '1b161c1e42', 'ex1_order': 'C02__688417295872958465119', 'ex2_order': '6a1753eeeaee1500079a122c',
     'ex1_filled': 210.0, 'ex2_filled': 0, 'ex2_fees': 0, 'original_cancelled': True},
    # Trade 12: 1b161c2c27 - COMPLETE (FILLED)
    {'trade_id': '1b161c2c27', 'ex1_order': 'C02__688417353221672960119', 'ex2_order': '6a1753fc30aa00000718e8bf',
     'ex1_filled': 75.93, 'ex2_filled': 76.0, 'ex2_fees': 0.00411084},
    # Trade 13: 1b161e2f2a - COMPLETE (FILLED)
    {'trade_id': '1b161e2f2a', 'ex1_order': 'C02__688417869540503552119', 'ex2_order': '6a1754774e1cb600073c7de2',
     'ex1_filled': 86.0, 'ex2_filled': 86.0, 'ex2_fees': 0.004646838},
    # Trade 14: 1c8252130 - COMPLETE (FILLED)
    {'trade_id': '1c8252130', 'ex1_order': 'C02__688570566356905984119', 'ex2_order': '6a17e2adf103be00072e301c',
     'ex1_filled': 80.45, 'ex2_filled': 80.0, 'ex2_fees': 0.00424728},
    # Trade 15: 1c8252549 - COMPLETE (FILLED)
    {'trade_id': '1c8252549', 'ex1_order': 'C02__688570583591292928119', 'ex2_order': '6a17e2b167c971000744051f',
     'ex1_filled': 276.57, 'ex2_filled': 277.0, 'ex2_fees': 0.014707038},
    # Trade 16: 1c825365e - COMPLETE (FILLED)
    {'trade_id': '1c825365e', 'ex1_order': 'C02__688570656337301504119', 'ex2_order': '6a17e2c2f828df000769e0a7',
     'ex1_filled': 79.15, 'ex2_filled': 79.0, 'ex2_fees': 0.004191582},
    # Trade 17: 1cb36f01 - COMPLETE (FILLED)
    {'trade_id': '1cb36f01', 'ex1_order': 'C02__688620065544654849119', 'ex2_order': '6a1810c6eaee1500076691ce',
     'ex1_filled': 80.44, 'ex2_filled': 80.0, 'ex2_fees': 0.00415128},
    # Trade 18: 1cb361254 - COMPLETE (FILLED)
    {'trade_id': '1cb361254', 'ex1_order': 'C02__688620082586062848119', 'ex2_order': '6a1810cae1d8f800075b948e',
     'ex1_filled': 496.76, 'ex2_filled': 497.0, 'ex2_fees': 0.0},
    # Trade 19: 1cb36224e - COMPLETE (FILLED)
    {'trade_id': '1cb36224e', 'ex1_order': 'C02__688620148457660416119', 'ex2_order': '6a1810da4afdd0000792a8d7',
     'ex1_filled': 117.0, 'ex2_filled': 117.0, 'ex2_fees': 0.006074055},
    # Trade 20: 1cb362818 - COMPLETE (FILLED)
    {'trade_id': '1cb362818', 'ex1_order': 'C02__688620171375337472119', 'ex2_order': '6a1810e0f103be0007d34ea6',
     'ex1_filled': 117.0, 'ex2_filled': 117.0, 'ex2_fees': 0.006074757},
    # Trade 21: 1cb37048 - COMPLETE (FILLED)
    {'trade_id': '1cb37048', 'ex1_order': 'C02__688620258105106433119', 'ex2_order': '6a1810f442a70a00071b70c5',
     'ex1_filled': 117.0, 'ex2_filled': 117.0, 'ex2_fees': 0.006062121},
]

# ============================================================
# MAIN ANALYSIS
# ============================================================
print("=" * 80)
print("TRADE LOG VALIDATION REPORT")
print("=" * 80)

# Query replacement orders
print("\n--- REPLACEMENT ORDER STATUS (from KuCoin API) ---\n")

replacement_data = {}
for trade_id, order_id in REPLACEMENT_ORDERS.items():
    path = f'/api/v1/orders/{order_id}?symbol=MPC-USDT'
    result = kucoin_request('GET', path)
    
    if result.get('code') == '200000':
        data = result['data']
        deal_size = float(data.get('dealSize', 0) or 0)
        fee = float(data.get('fee', 0) or 0)
        
        replacement_data[trade_id] = {
            'order_id': order_id,
            'status': data.get('status'),
            'deal_size': deal_size,
            'fee': fee,
            'deal_funds': float(data.get('dealFunds', 0) or 0),
            'created_at': data.get('createdAt')
        }
        
        status_icon = "✅" if deal_size > 0 else "❌"
        print(f"{status_icon} Trade {trade_id}: Order {order_id}")
        print(f"    DealSize: {deal_size} MPC")
        print(f"    Fee: {fee} USDT")
        print(f"    Status: {data.get('status')}")
        print()
    else:
        print(f"❌ Trade {trade_id}: API Error - {result}")
        replacement_data[trade_id] = {'error': result}

print("\n" + "=" * 80)
print("SUMMARY")
print("=" * 80)

print("\nOriginal cancelled orders (5):")
cancelled_trades = ['1b16113062', '1b16113647', '1b16122f50', '1b16181516', '1b161c1e42']
for t in cancelled_trades:
    if t in replacement_data:
        rd = replacement_data[t]
        if 'error' not in rd:
            print(f"  {t}: {rd['deal_size']} MPC filled")
        else:
            print(f"  {t}: ERROR")
    else:
        print(f"  {t}: Not queried")

print("\nReplacement status:")
filled_count = sum(1 for t in cancelled_trades if t in replacement_data and replacement_data[t].get('deal_size', 0) > 0)
print(f"  Filled: {filled_count}/5")
print(f"  NOT Filled: {5 - filled_count}/5")

# Note the problem with 1b161c1e42
print("\n⚠️  PROBLEM IDENTIFIED:")
print("  Trade 1b161c1e42 replacement order 6a1753eeeaee1500079a122c has 0 MPC filled!")
print("  This trade may need manual intervention or has an edge case.")

print("\n" + "=" * 80)
print("API QUERY COMPLETE")
print("=" * 80)