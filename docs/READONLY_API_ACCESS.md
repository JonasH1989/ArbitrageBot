# Read-Only API Access - Arbitrage Bot

## Übersicht

Dieses Dokument beschreibt, wie man mit den API-Credentials des Bots (read-only oder full-access) **authentifiziert** auf beide Börsen zugreift.

---

## KuCoin API

### Credentials
```
KUCOIN_KEY = "69e542868294a100018f076f"
KUCOIN_SECRET = "899189f7-e6fa-4ea4-ad0c-dfd43506ef30"
KUCOIN_PASSPHRASE = "6GEWzwgmfDyjgDk"
```

### Signatur-Funktionen (aus arb_autotrade.py)

```python
import hmac, hashlib, base64

def kucoin_passphrase_enc(secret, passphrase):
    """Verschlüsselt passphrase für KuCoin API v2"""
    mac = hmac.new(secret.encode(), passphrase.encode(), hashlib.sha256)
    return base64.b64encode(mac.digest()).decode()

def kucoin_sig(secret, timestamp, method, path, body=''):
    """Erstellt KuCoin Signatur für Request"""
    message = f'{timestamp}{method}{path}{body}'
    mac = hmac.new(secret.encode(), message.encode(), hashlib.sha256)
    return base64.b64encode(mac.digest()).decode()
```

### Standard Headers für alle Requests

```python
passphrase_enc = kucoin_passphrase_enc(KUCOIN_SECRET, KUCOIN_PASSPHRASE)

headers = {
    'KC-API-KEY': KUCOIN_KEY,
    'KC-API-SIGN': kucoin_sig(KUCOIN_SECRET, timestamp, method, path, body),
    'KC-API-TIMESTAMP': timestamp,
    'KC-API-PASSPHRASE': passphrase_enc,
    'KC-API-KEY-VERSION': '2'
}
```

### Verfügbare Endpoints

| Endpoint | Methode | Beschreibung |
|----------|---------|-------------|
| `/api/v1/accounts` | GET | Alle Balances |
| `/api/v1/accounts?currency=MPC` | GET | Balance für eine Währung |
| `/api/v1/orders?symbol=MPC-USDT&status=ACTIVE` | GET | Offene Orders |
| `/api/v1/orders?symbol=MPC-USDT&status=DONE` | GET | Abgeschlossene Orders |
| `/api/v1/fills?symbol=MPC-USDT&limit=100` | GET | Alle Fills (Trades) |
| `/api/v1/fills?orderId=XXX` | GET | Fills für eine Order |

---

## KuCoin: Account Balances abrufen

```python
import requests, time

timestamp = str(int(time.time() * 1000))
path = '/api/v1/accounts'
sig = kucoin_sig(KUCOIN_SECRET, timestamp, 'GET', path)
passphrase_enc = kucoin_passphrase_enc(KUCOIN_SECRET, KUCOIN_PASSPHRASE)

headers = {
    'KC-API-KEY': KUCOIN_KEY,
    'KC-API-SIGN': sig,
    'KC-API-TIMESTAMP': timestamp,
    'KC-API-PASSPHRASE': passphrase_enc,
    'KC-API-KEY-VERSION': '2'
}

resp = requests.get(f'https://api.kucoin.com{path}', headers=headers, timeout=10)
data = resp.json()

if data.get('code') == '200000':
    for acc in data['data']:
        currency = acc['currency']
        avail = float(acc['available'])
        total = float(acc['balance'])
        acc_type = acc['type']
        if total > 0:
            print(f"  {currency}: avail={avail}, total={total} ({acc_type})")
```

---

## KuCoin: Fills (abgeschlossene Trades) abrufen

```python
import requests, time
from datetime import datetime

timestamp = str(int(time.time() * 1000))
path = '/api/v1/fills?symbol=MPC-USDT&limit=100'
sig = kucoin_sig(KUCOIN_SECRET, timestamp, 'GET', path)
passphrase_enc = kucoin_passphrase_enc(KUCOIN_SECRET, KUCOIN_PASSPHRASE)

headers = {
    'KC-API-KEY': KUCOIN_KEY,
    'KC-API-SIGN': sig,
    'KC-API-TIMESTAMP': timestamp,
    'KC-API-PASSPHRASE': passphrase_enc,
    'KC-API-KEY-VERSION': '2'
}

resp = requests.get(f'https://api.kucoin.com{path}', headers=headers, timeout=10)
data = resp.json()

if data.get('code') == '200000':
    total_pages = data['data']['totalPage']
    for page in range(1, total_pages + 1):
        path_page = f'/api/v1/fills?symbol=MPC-USDT&limit=100&page={page}'
        sig_page = kucoin_sig(KUCOIN_SECRET, timestamp, 'GET', path_page)
        headers_page = {**headers, 'KC-API-SIGN': sig_page}
        resp_page = requests.get(f'https://api.kucoin.com{path_page}', headers=headers_page, timeout=10)
        page_data = resp_page.json()
        
        for fill in page_data['data']['items']:
            ts = datetime.fromtimestamp(int(fill['createdAt'])/1000)
            side = fill['side']  # 'buy' oder 'sell'
            qty = float(fill['size'])
            price = float(fill['price'])
            funds = float(fill['funds'])
            liquidity = fill['liquidity']  # 'taker' oder 'maker'
            order_id = fill['orderId']
            print(f"  {ts} | {side:4} | qty={qty:>10.2f} | price={price:.6f} | ${funds:.4f} | {liquidity}")
```

### Wichtige Felder in Fills

| Feld | Beschreibung |
|------|-------------|
| `side` | `buy` oder `sell` - unsere Seite |
| `liquidity` | `taker` = wir haben die Order吃掉, `maker` = wir haben als Limit-Order dagestellt |
| `size` | Menge in MPC |
| `price` | Ausführungspreis |
| `funds` | USDT Wert |
| `fee` | Gebühr |
| `feeRate` | Fee-Satz (0.003 = 0.3%) |
| `orderId` | Unsere Order ID |
| `counterOrderId` | Gegenorder ID (andere Partei) |
| `createdAt` | Timestamp in Millisekunden |

---

## KuCoin: Offene Orders abrufen

```python
timestamp = str(int(time.time() * 1000))
path = '/api/v1/orders?symbol=MPC-USDT&status=ACTIVE'
sig = kucoin_sig(KUCOIN_SECRET, timestamp, 'GET', path)
passphrase_enc = kucoin_passphrase_enc(KUCOIN_SECRET, KUCOIN_PASSPHRASE)

headers = {
    'KC-API-KEY': KUCOIN_KEY,
    'KC-API-SIGN': sig,
    'KC-API-TIMESTAMP': timestamp,
    'KC-API-PASSPHRASE': passphrase_enc,
    'KC-API-KEY-VERSION': '2'
}

resp = requests.get(f'https://api.kucoin.com{path}', headers=headers, timeout=10)
data = resp.json()

if data.get('code') == '200000':
    for order in data['data']:
        print(f"  {order['side']} | qty={order['size']} | price={order['price']} | status={order['status']}")
```

---

## MEXC API

### Credentials
```
MEXC_KEY = "mx0vglEZT6rtvympvJ"
MEXC_SECRET = "a1a045b12c66414c935dd2eff63e2eb0"
```

### Signatur

```python
import hmac, hashlib, time

timestamp = str(int(time.time() * 1000))
params = f'timestamp={timestamp}'  # oder mit symbol, orderId etc.
sig = hmac.new(MEXC_SECRET.encode('utf-8'), params.encode('utf-8'), hashlib.sha256).hexdigest()

headers = {'X-MEXC-APIKEY': MEXC_KEY}
```

### Verfügbare Endpoints

| Endpoint | Beschreibung |
|----------|-------------|
| `GET /api/v3/account` | Account Balances |
| `GET /api/v3/order?symbol=MPCUSDT&orderId=XXX` | Order Status |
| `GET /api/v3/myTrades?symbol=MPCUSDT` | Eigene Trades (PERMISSION REQUIRED!) |

---

## MEXC: Account Balances abrufen

```python
import requests, hmac, hashlib, time

timestamp = str(int(time.time() * 1000))
params = f'timestamp={timestamp}'
sig = hmac.new(MEXC_SECRET.encode('utf-8'), params.encode('utf-8'), hashlib.sha256).hexdigest()

url = f'https://api.mexc.com/api/v3/account?{params}&signature={sig}'
headers = {'X-MEXC-APIKEY': MEXC_KEY}

resp = requests.get(url, headers=headers, timeout=10)
data = resp.json()

for bal in data.get('balances', []):
    free = float(bal.get('free', 0))
    locked = float(bal.get('locked', 0))
    total = free + locked
    if total > 0:
        print(f"  {bal['asset']}: free={free}, locked={locked}, total={total}")
```

---

## MEXC: Offene Orders abrufen

```python
import requests, hmac, hashlib, time

timestamp = str(int(time.time() * 1000))
params = f'symbol=MPCUSDT&timestamp={timestamp}'
sig = hmac.new(MEXC_SECRET.encode('utf-8'), params.encode('utf-8'), hashlib.sha256).hexdigest()

url = f'https://api.mexc.com/api/v3/openOrders?{params}&signature={sig}'
headers = {'X-MEXC-APIKEY': MEXC_KEY}

resp = requests.get(url, headers=headers, timeout=10)
print(resp.json())
```

---

## ⚠️ Bekannte Probleme

### MEXC myTrades
- **Problem**: `{'code': 700007, 'msg': 'No permission to access the endpoint.'}`
- **Lösung**: API Key hat keine Permission für Trade-History. Nur Balances + Open Orders möglich.

### KuCoin Invalid KC-API-SIGN
- **Ursache**: Falsche Signatur-Berechnung
- **Lösung**: Signature muss NUR timestamp + method + path + body enthalten (ohne Host, ohne Query-String im Path)
- **Wichtig**: Query-Parameter gehören NICHT zum Signatur-Path!

---

## Vollständiges Beispiel: Gap-Analyse 10:00-12:00

```python
import requests, hmac, hashlib, base64, time
from datetime import datetime

# ============================================================
# CREDENTIALS (aus config.yaml)
# ============================================================
KUCOIN_KEY = "69e542868294a100018f076f"
KUCOIN_SECRET = "899189f7-e6fa-4ea4-ad0c-dfd43506ef30"
KUCOIN_PASSPHRASE = "6GEWzwgmfDyjgDk"
MEXC_KEY = "mx0vglEZT6rtvympvJ"
MEXC_SECRET = "a1a045b12c66414c935dd2eff63e2eb0"

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
    resp = requests.request(method, url, headers=headers, timeout=10)
    return resp.json()

# ============================================================
# MEXC HELPER FUNCTION
# ============================================================
def mexc_request(params_dict):
    timestamp = str(int(time.time() * 1000))
    params_dict['timestamp'] = timestamp
    params = '&'.join(f'{k}={v}' for k, v in params_dict.items())
    sig = hmac.new(MEXC_SECRET.encode('utf-8'), params.encode('utf-8'), hashlib.sha256).hexdigest()
    headers = {'X-MEXC-APIKEY': MEXC_KEY}
    url = f"https://api.mexc.com/api/v3/{params_dict.get('method', 'account').replace('GET ', '')}?{params}&signature={sig}"
    return requests.get(url, headers=headers, timeout=10).json()

# ============================================================
# 1. KUCOIN FILLS (Alle Seiten)
# ============================================================
all_fills = []
page = 1
while True:
    data = kucoin_request('GET', f'/api/v1/fills?symbol=MPC-USDT&limit=100&page={page}')
    if data.get('code') != '200000':
        break
    all_fills.extend(data['data']['items'])
    if page >= data['data']['totalPage']:
        break
    page += 1

# Deduplizieren nach tradeId
seen = set()
unique_fills = []
for f in all_fills:
    if f['tradeId'] not in seen:
        seen.add(f['tradeId'])
        unique_fills.append(f)

# Filter: Heute 10:00-12:00
window_start = datetime(2026, 5, 7, 10, 0, 0).timestamp() * 1000
window_end = datetime(2026, 5, 7, 12, 0, 0).timestamp() * 1000
window_fills = [f for f in unique_fills if window_start <= int(f['createdAt']) <= window_end]

# Bot's TAKER sells = unsere abgeschlossenen M->K Trades
bot_sells = [f for f in window_fills if f['side'] == 'sell' and f['liquidity'] == 'taker']
other_sells = [f for f in window_fills if f['side'] == 'sell' and f['liquidity'] == 'maker']

print(f"Bot TAKER sells: {sum(float(f['size']) for f in bot_sells):,.2f} MPC ({len(bot_sells)} fills)")
print(f"Other MAKER sells: {sum(float(f['size']) for f in other_sells):,.2f} MPC ({len(other_sells)} fills)")

# ============================================================
# 2. KUCOIN BALANCES
# ============================================================
bal_data = kucoin_request('GET', '/api/v1/accounts')
if bal_data.get('code') == '200000':
    for acc in bal_data['data']:
        if float(acc['balance']) > 0:
            print(f"  KuCoin {acc['currency']}: {acc['balance']} ({acc['type']})")

# ============================================================
# 3. MEXC BALANCES
# ============================================================
mexc_bal = mexc_request({'method': 'account', 'timestamp': ''})  # dummy
print(f"MEXC Response: {mexc_bal}")
```

---

*Letztes Update: 2026-05-07*

---

## ⚠️ KRITISCH: ZWEI MEXC KEYS!

### Read-Only Key (API Read)
```
Name: ArbitrageBotREADONLY
Access Key: mx0vglEZT6rtvympvJ
Secret Key: a1a045b12c66414c935dd2eff63e2eb0
```
- Nur Balances + Open Orders
- KEINE Trade History (`myTrades` = No permission)

### Trading Key (Volle Rechte!)
```
Name: ArbitrageBotTRADEv2
Access Key: mx0vglBgOfyggoJe3I
Secret Key: 4d15399a840d494b9a308534f9cf7907
```
- **VOLLE RECHTE**: Trading + Trade History lesen!
- Für `myTrades` und alle anderen Private Endpoints!

### WICHTIG: Immer den RICHTIGEN Key nutzen!
- Trade History lesen → Trading Key (TRADEv2)
- Nur Balances prüfen → Read-only Key reicht

*Gespeichert: 2026-05-17*
