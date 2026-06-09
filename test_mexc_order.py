import requests, hmac, hashlib, time, json

with open('/home/openclaw/.openclaw/workspace/trading/arbitrage-bot/config/config.yaml') as f:
    import yaml
    cfg = yaml.safe_load(f)

mexc_list = [v for k, v in cfg.items() if 'mexc' in k.lower()]
mexc_cfg = mexc_list[1] if len(mexc_list) > 1 else mexc_list[0]

MEXC_KEY = mexc_cfg['api_key']
MEXC_SECRET = mexc_cfg['api_secret']

ts = str(int(time.time() * 1000))
params = f'symbol=MPCUSDT&orderId=C02__688414521529683969119&timestamp={ts}'
sig = hmac.new(MEXC_SECRET.encode('utf-8'), params.encode('utf-8'), hashlib.sha256).hexdigest()
url = f'https://api.mexc.com/api/v3/order?{params}&signature={sig}'
resp = requests.get(url, headers={'X-MEXC-APIKEY': MEXC_KEY}, timeout=10)
print(json.dumps(resp.json(), indent=2))
