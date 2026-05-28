#!/usr/bin/env python3
"""
Trade Log Validator - Query exchanges for missing data
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
# QUERY REPLACEMENT ORDERS FROM KUCOIN
# ============================================================
print("=" * 80)
print("KUCOIN REPLACEMENT ORDERS QUERY")
print("=" * 80)

for trade_id, order_id in REPLACEMENT_ORDERS.items():
    print(f"\n--- Trade {trade_id} | Replacement Order {order_id} ---")
    
    # Get order details
    path = f'/api/v1/orders/{order_id}?symbol=MPC-USDT'
    result = kucoin_request('GET', path)
    
    if result.get('code') == '200000':
        data = result['data']
        print(f"  Status: {data.get('status')}")
        print(f"  Side: {data.get('side')}")
        print(f"  Type: {data.get('type')}")
        print(f"  Size (ordered): {data.get('size')}")
        print(f"  DealSize (filled): {data.get('dealSize')}")
        print(f"  DealFunds: {data.get('dealFunds')}")
        print(f"  Fee: {data.get('fee')}")
        created_at = data.get('createdAt')
        if created_at:
            ts = datetime.fromtimestamp(int(created_at)/1000)
            print(f"  CreatedAt: {created_at} ({ts})")
        
        # Get fills for this order
        fills_path = f'/api/v1/fills?symbol=MPC-USDT&orderId={order_id}'
        fills_result = kucoin_request('GET', fills_path)
        
        if fills_result.get('code') == '200000':
            fills = fills_result['data']['items']
            print(f"  Fills count: {len(fills)}")
            for i, fill in enumerate(fills):
                print(f"    Fill {i+1}:")
                print(f"      tradeId: {fill.get('tradeId')}")
                print(f"      size: {fill.get('size')}")
                print(f"      price: {fill.get('price')}")
                print(f"      funds: {fill.get('funds')}")
                print(f"      fee: {fill.get('fee')}")
                print(f"      feeRate: {fill.get('feeRate')}")
                print(f"      liquidity: {fill.get('liquidity')}")
                fill_created = fill.get('createdAt')
                if fill_created:
                    ts = datetime.fromtimestamp(int(fill_created)/1000)
                    print(f"      createdAt: {fill_created} ({ts})")
        else:
            print(f"  Fills error: {fills_result}")
    else:
        print(f"  Order query error: {result}")

print("\n" + "=" * 80)
print("QUERY COMPLETE")
print("=" * 80)