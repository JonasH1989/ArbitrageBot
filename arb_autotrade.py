#!/usr/bin/env python3
"""Arbitrage Bot v3"""
import requests, time, json, hashlib, hmac, base64, os
from datetime import datetime

LOG = '/home/openclaw/.openclaw/logs/arb_autotrade.log'
TRADES = '/home/openclaw/.openclaw/logs/arb_trades.json'
TRACKER = '/home/openclaw/.openclaw/workspace/trading/arbitrage-bot/order_tracker.json'
SNAPSHOT = '/home/openclaw/.openclaw/logs/snapshot.json'

KC_KEY = "69e6445dd56900000160af01"
KC_SEC = "787903d0-bb7f-4d84-b598-c07ac71180ef"
KC_PASS = "YtuyE5uM6hE8HC6"
MX_KEY = "mx0vglqkp7DNxtrVO6"
MX_SEC = "880bf82a7761449fa24cc508c6e577fa"
MIN_USDT = 1.0
MIN_KC = 10
THRESH = 0.5

def lg(m):
    t = datetime.now().strftime('%H:%M:%S')
    print(f"[{t}] {m}")
    open(LOG, 'a').write(f"[{t}] {m}\n")

def ksig(ts, method, path, body=''):
    m = hmac.new(KC_SEC.encode(), f'{ts}{method}{path}{body}'.encode(), hashlib.sha256)
    return base64.b64encode(m.digest()).decode()

def get_p():
    try:
        r = requests.get('https://api.kucoin.com/api/v1/market/orderbook/level1?symbol=MPC-USDT', timeout=5).json()['data']
        m = requests.get('https://api.mexc.com/api/v3/ticker/24hr?symbol=MPCUSDT', timeout=5).json()
        return {'k': {'b': float(r['bestBid']), 'a': float(r['bestAsk']), 'bq': float(r.get('bestBidSize', 0)), 'aq': float(r.get('bestAskSize', 0))}, 'm': {'b': float(m['bidPrice']), 'a': float(m['askPrice']), 'bq': float(m.get('bidQty', 0)), 'aq': float(m.get('askQty', 0))}}
    except:
        return None

def load_tk():
    try:
        return json.load(open(TRACKER))
    except:
        return {}

def save_tk(t):
    json.dump(t, open(TRACKER, 'w'), indent=2)

def chk_k(oid):
    ts = str(int(time.time()*1000))
    h = {'KC-API-KEY': KC_KEY, 'KC-API-SIGN': ksig(ts, 'GET', f'/api/v1/orders/{oid}'), 'KC-API-TIMESTAMP': ts, 'KC-API-PASSPHRASE': KC_PASS}
    r = requests.get(f'https://api.kucoin.com/api/v1/orders/{oid}', headers=h).json()
    if r.get('code') == '200000':
        o = r['data']
        return {'f': float(o.get('dealSize', 0)), 'd': not o.get('isActive', True)}
    return None

def chk_m(oid):
    ts = str(int(time.time()*1000))
    p = f'orderId={oid}&timestamp={ts}'
    s = hmac.new(MX_SEC.encode(), p.encode(), hashlib.sha256).hexdigest()
    r = requests.get(f'https://api.mexc.com/api/v3/order?{p}&signature={s}', headers={'X-MEXC-APIKEY': MX_KEY}).json()
    if 'orderId' in r:
        return {'f': float(r.get('executedQty', 0)), 'd': r.get('status') in ['FILLED', 'CANCELED']}
    return None

def exec_k_buy(qty):
    ts, body = str(int(time.time()*1000)), json.dumps({"clientOid": ts, "symbol": "MPC-USDT", "side": "buy", "type": "market", "size": str(int(qty))})
    h = {'KC-API-KEY': KC_KEY, 'KC-API-SIGN': ksig(ts, 'POST', '/api/v1/orders', body), 'KC-API-TIMESTAMP': ts, 'KC-API-PASSPHRASE': KC_PASS, 'Content-Type': 'application/json'}
    return requests.post('https://api.kucoin.com/api/v1/orders', headers=h, data=body).json()

def exec_k_sell(qty, pr):
    ts, body = str(int(time.time()*1000)), json.dumps({"clientOid": f"{ts}_s", "symbol": "MPC-USDT", "side": "sell", "type": "limit", "size": str(int(qty)), "price": f"{pr:.6f}"})
    h = {'KC-API-KEY': KC_KEY, 'KC-API-SIGN': ksig(ts, 'POST', '/api/v1/orders', body), 'KC-API-TIMESTAMP': ts, 'KC-API-PASSPHRASE': KC_PASS, 'Content-Type': 'application/json'}
    return requests.post('https://api.kucoin.com/api/v1/orders', headers=h, data=body).json()

def exec_m_buy(qty):
    ts = str(int(time.time()*1000))
    p = f'symbol=MPCUSDT&side=BUY&type=MARKET&quantity={qty:.2f}&timestamp={ts}'
    s = hmac.new(MX_SEC.encode(), p.encode(), hashlib.sha256).hexdigest()
    return requests.post(f'https://api.mexc.com/api/v3/order?{p}&signature={s}', headers={'X-MEXC-APIKEY': MX_KEY}).json()

def exec_m_sell(qty, pr):
    ts = str(int(time.time()*1000))
    p = f'symbol=MPCUSDT&side=SELL&type=LIMIT&quantity={qty:.2f}&price={pr:.6f}&timestamp={ts}'
    s = hmac.new(MX_SEC.encode(), p.encode(), hashlib.sha256).hexdigest()
    return requests.post(f'https://api.mexc.com/api/v3/order?{p}&signature={s}', headers={'X-MEXC-APIKEY': MX_KEY}).json()

def track(oid, ex, q):
    t = load_tk()
    t[oid] = {'id': oid, 'ex': ex, 'qty': q, 'f': 0, 'st': 'P'}
    save_tk(t)

def ptot():
    return sum(o.get('qty', 0) - o.get('f', o.get('filled', 0)) for o in load_tk().values() if o.get('st', o.get('status', 'P')) in ['P', 'PENDING'])

def chk_all():
    t = load_tk()
    for i, o in list(t.items()):
        st = o.get('st', o.get('status', 'P'))
        if st != 'P' and st != 'PENDING':
            continue
        r = chk_k(i) if o.get('ex', o.get('exchange', '')) == 'KuCoin' else chk_m(i)
        if r and r['d']:
            o['f'] = r['f']
            o['st'] = 'F'
            o['status'] = 'FILLED'
            lg(f"FILLED: {i}")
    save_tk(t)

def snap(k, m, p):
    try:
        json.dump({'t': datetime.now().isoformat(), 'kb': k['b'], 'ka': k['a'], 'kbq': k['bq'], 'kaq': k['aq'], 'mb': m['b'], 'ma': m['a'], 'mbq': m['bq'], 'maq': m['aq'], 'p': p}, open(SNAPSHOT, 'w'))
    except:
        pass

trds = []
try:
    trds = json.load(open(TRADES))
except:
    pass

def trade_KM(q, bp, sp):
    tid = f"KT{int(time.time())}"
    lg(f"=== {tid} ===")
    r1 = exec_k_buy(q)
    if r1.get('code') == '200000':
        bo = r1['data']['orderId']
        lg(f"Buy: {bo}")
        while not chk_k(bo)['d']:
            time.sleep(1)
    else:
        return False
    r2 = exec_m_sell(q, sp)
    so = r2.get('orderId', 'u')
    lg(f"Sell: {so}")
    track(so, 'MEXC', q)
    net = q * (sp - bp) * 0.998
    lg(f"Net: ${net:.4f}")
    trds.append({'id': tid, 'q': q, 'n': net, 'ts': datetime.now().isoformat()})
    json.dump(trds, open(TRADES, 'w'))
    return True

def trade_MK(q, bp, sp):
    tid = f"MT{int(time.time())}"
    lg(f"=== {tid} ===")
    r1 = exec_m_buy(q)
    if r1.get('code') is None or 'orderId' in r1:
        bo = r1['orderId']
        lg(f"Buy: {bo}")
        while not chk_m(bo)['d']:
            time.sleep(1)
    else:
        return False
    r2 = exec_k_sell(q, sp)
    so = r2['data'].get('orderId', 'u')
    lg(f"Sell: {so}")
    track(so, 'KuCoin', q)
    net = q * (sp - bp) * 0.998
    lg(f"Net: ${net:.4f}")
    trds.append({'id': tid, 'q': q, 'n': net, 'ts': datetime.now().isoformat()})
    json.dump(trds, open(TRADES, 'w'))
    return True

def main():
    lg("=== BOT v3 START ===")
    os.makedirs('/home/openclaw/.openclaw/logs', exist_ok=True)
    lc = 0
    while True:
        p = get_p()
        if not p:
            time.sleep(1)
            continue
        k, m = p['k'], p['m']
        smk = (k['b'] - m['a']) / m['a'] * 100
        skm = (m['b'] - k['a']) / k['a'] * 100
        vm = int((MIN_USDT + 1) / m['a']) if m['a'] > 0 else 86
        vk = max(MIN_KC, vm)
        if int(time.time()) - lc >= 30:
            lc = int(time.time())
            chk_all()
            pt = ptot()
            lg(f"P: K={k['b']:.4f}/{k['a']:.4f} M={m['b']:.4f}/{m['a']:.4f}")
            lg(f"Q: Kb={k['bq']:.0f} Ka={k['aq']:.0f} Mb={m['bq']:.0f} Ma={m['aq']:.0f}")
            lg(f"S: Mk={smk:.2f}% Km={skm:.2f}% P={pt}")
            snap(k, m, pt)
        if skm >= THRESH:
            trade_KM(vk, k['a'], m['b'])
        elif smk >= THRESH:
            trade_MK(vm, m['a'], k['b'])
        time.sleep(1)

if __name__ == '__main__':
    main()