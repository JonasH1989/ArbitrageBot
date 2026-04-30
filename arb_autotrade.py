#!/usr/bin/env python3
"""
Arbitrage Auto-Trade Bot
Executes trades automatically when opportunities arise
Uses harmonized trade_logger for unified multi-exchange logging
"""
import sys
sys.path.insert(0, '/home/openclaw/.openclaw/workspace/trading/arbitrage-bot')

import requests
import yaml
import time
import json
import hashlib
import hmac
import base64
import json as json_lib
import math
from datetime import datetime
import os
import threading

# Flask for HTTP logging server (optional)
try:
    from flask import Flask, jsonify, request
    FLASK_AVAILABLE = True
except ImportError:
    FLASK_AVAILABLE = False

# Import settings_sync for config access
sys.path.insert(0, '/app')
try:
    from settings_sync import get_setting, set_setting, get_pair_settings, load_config, is_debug_enabled, get_log_level
except ImportError:
    get_setting = None
    set_setting = None
    get_pair_settings = None
    load_config = None
    is_debug_enabled = lambda: False

# Import the harmonized trade logger
from trade_logger import (
    harmonize_kucoin_order,
    harmonize_mexc_order,
    log_trade,
    update_limit_watch,
    get_pending_limit_orders,
    get_trade_summary,
    get_trades,
)

from pathlib import Path

LOG_DIR = Path('/app/logs') if Path('/app/logs').exists() else Path('/home/openclaw/.openclaw/logs')
LOG_DIR.mkdir(parents=True, exist_ok=True)  # Ensure log directory exists
LOG_FILE = LOG_DIR / 'arb_autotrade.log'
CONFIG_FILE = '/home/openclaw/.openclaw/workspace/trading/arbitrage-bot/config/config.yaml'
ACTIVE_FLAG_FILE = LOG_DIR / 'arb_active.flag'

# Exchange API credentials
# Load API keys from config.yaml - use same path as settings_sync (dashboard)
from pathlib import Path
_config_dir = Path('/app/config') if Path('/app/config').exists() else Path(__file__).parent / 'config'
_config_path = _config_dir / 'config.yaml'
with open(_config_path, 'r') as _f:
    _cfg = yaml.safe_load(_f)
KUCOIN_KEY = _cfg.get('kucoin', {}).get('api_key', '')
KUCOIN_SECRET = _cfg.get('kucoin', {}).get('api_secret', '')
KUCOIN_PASSPHRASE = _cfg.get('kucoin', {}).get('api_passphrase', '')
MEXC_KEY = _cfg.get('mexc', {}).get('api_key', '')
MEXC_SECRET = _cfg.get('mexc', {}).get('api_secret', '')

MEXC_MIN_USDT = 1.0

# ==============================================================================
# Trading Pair Configuration - Change COIN for different coins!
# ==============================================================================
COIN_SYMBOL = "MPC-USDT"      # KuCoin format (e.g., BTC-USDT, ETH-USDT)
COIN_SYMBOL_MEXC = "MPCUSDT"  # MEXC format (e.g., BTCUSDT, ETHUSDT)
KUCOIN_MIN_QTY = 85           # Minimum quantity per order (will be adjusted per coin)

# Exchange precision (decimal places) - adjust per coin as needed
MEXC_PRICE_PRECISION = 5
KUCOIN_PRICE_PRECISION = 6

TRADING_PAIR = COIN_SYMBOL

# ==============================================================================
# HTTP Logging Server (for real-time monitoring)
# ==============================================================================
HTTP_LOGS = []  # In-memory log storage
HTTP_LOGS_MAX = 10000  # Keep last 10000 logs
_http_server = None

def http_log(message: str, level: str = "INFO"):
    """Add a log entry to the HTTP log buffer."""
    global HTTP_LOGS
    timestamp = datetime.now().strftime('%Y-%m-%d %H:%M:%S.%f')[:-3]
    entry = {
        'timestamp': timestamp,
        'level': level,
        'message': str(message),
        'received_at': time.time()
    }
    HTTP_LOGS.append(entry)
    # Keep only last N logs
    if len(HTTP_LOGS) > HTTP_LOGS_MAX:
        HTTP_LOGS = HTTP_LOGS[-HTTP_LOGS_MAX:]
    return entry

def start_http_log_server(port: int = 8503):
    """Start the Flask HTTP logging server in a background thread."""
    global _http_server

    if not FLASK_AVAILABLE:
        print("Flask not available, HTTP logging disabled")
        return None

    app = Flask(__name__)

    @app.route('/log', methods=['POST'])
    def add_log():
        data = request.get_json() or {}
        message = data.get('message', '')
        level = data.get('level', 'INFO')
        http_log(message, level)
        return jsonify({'status': 'ok', 'logs_count': len(HTTP_LOGS)})

    @app.route('/logs', methods=['GET'])
    def get_logs():
        last_n = request.args.get('last', 100, type=int)
        return jsonify(HTTP_LOGS[-last_n:])

    @app.route('/logs/today', methods=['GET'])
    def get_today_logs():
        today = datetime.now().date().isoformat()
        today_logs = [l for l in HTTP_LOGS if today in l['timestamp'][:10]]
        return jsonify(today_logs)

    @app.route('/logs/level/<level>', methods=['GET'])
    def get_logs_by_level(level):
        level_logs = [l for l in HTTP_LOGS if l['level'].upper() == level.upper()]
        return jsonify(level_logs[-100:])

    @app.route('/status', methods=['GET'])
    def get_status():
        return jsonify({
            'status': 'running',
            'logs_count': len(HTTP_LOGS),
            'uptime_seconds': time.time() - getattr(_http_server, 'start_time', time.time())
        })

    @app.route('/clear', methods=['POST'])
    def clear_logs():
        global HTTP_LOGS
        HTTP_LOGS = []
        return jsonify({'status': 'cleared'})

    def run_server():
        app.run(host='0.0.0.0', port=port, debug=False, use_reloader=False)

    thread = threading.Thread(target=run_server, daemon=True)
    thread.start()
    _http_server = thread
    print(f"HTTP Logging server started on port {port}")
    return thread

# Balance check functions
def get_mexc_balances() -> dict:
    """Get MEXC account balances (USDT and COIN)"""
    try:
        ts = str(int(time.time() * 1000))
        params = f'timestamp={ts}'
        sig = hmac.new(MEXC_SECRET.encode('utf-8'), params.encode('utf-8'), hashlib.sha256).hexdigest()
        url = f'https://api.mexc.com/api/v3/account?{params}&signature={sig}'
        headers = {'X-MEXC-APIKEY': MEXC_KEY}
        resp = requests.get(url, headers=headers, timeout=10)
        data = resp.json()

        balances = {'USDT': 0.0, COIN_SYMBOL.split('-')[0]: 0.0}
        if 'balances' in data:
            for b in data['balances']:
                if b['asset'] == 'USDT':
                    balances['USDT'] = float(b.get('free', 0))
                elif b['asset'] == COIN_SYMBOL.split('-')[0]:
                    balances[COIN_SYMBOL.split('-')[0]] = float(b.get('free', 0))
        return balances
    except Exception as e:
        log(f"❌ Error getting MEXC balances: {e}")
        return {'USDT': 0.0, COIN_SYMBOL.split('-')[0]: 0.0}

def get_kucoin_balances() -> dict:
    """Get KuCoin account balances (USDT and COIN)"""
    try:
        ts = str(int(time.time() * 1000))
        path = '/api/v1/accounts'
        method = 'GET'
        sig = kucoin_sig(KUCOIN_SECRET, ts, method, path)

        headers = {
            'KC-API-KEY': KUCOIN_KEY,
            'KC-API-SIGN': sig,
            'KC-API-TIMESTAMP': ts,
            'KC-API-PASSPHRASE': kucoin_passphrase_enc(KUCOIN_SECRET, KUCOIN_PASSPHRASE),
            'KC-API-KEY-VERSION': '2'
        }
        resp = requests.get(f'https://api.kucoin.com{path}', headers=headers, timeout=10)
        data = resp.json()

        log(f"DEBUG KuCoin accounts response: code={data.get('code')}, data count={len(data.get('data', []))}")

        coin_symbol = COIN_SYMBOL.split('-')[0]
        balances = {'USDT': 0.0, coin_symbol: 0.0}

        if data.get('code') == '200000' and 'data' in data:
            for acc in data['data']:
                currency = acc.get('currency', '')
                acc_type = acc.get('type', '')
                available = float(acc.get('available', 0))
                total = float(acc.get('balance', 0))

                # Debug logging for each account
                if currency in ['USDT', coin_symbol]:
                    log(f"DEBUG KuCoin account: {currency} | available={available} | total={total} | type={acc_type}")

                # ONLY use TRADE accounts for balance check (ignore main, margin, etc.)
                if acc_type == 'trade':
                    if currency == 'USDT':
                        balances['USDT'] = available  # Use TRADE account balance directly
                    elif currency == coin_symbol:
                        balances[coin_symbol] = available  # Use TRADE account balance directly
        else:
            log(f"❌ KuCoin API error: {data}")

        log(f"DEBUG Final balances: {balances}")
        return balances
    except Exception as e:
        log(f"❌ Error getting KuCoin balances: {e}")
        return {'USDT': 0.0, COIN_SYMBOL.split('-')[0]: 0.0}

def check_balances_for_trade(direction: str, qty: float, buy_price: float, sell_price: float) -> tuple:
    """Check if we have sufficient balances for a trade.

    Returns: (can_trade: bool, error_msg: str)
    """
    coin = COIN_SYMBOL.split('-')[0]

    if direction in ['M->K', 'M→K']:
        # Buying on MEXC, selling on KuCoin
        usdt_needed = qty * buy_price * 1.002  # +0.2% for fees
        coin_available_kucoin = get_kucoin_balances().get(coin, 0)

        if usdt_needed > 0.01:  # Need some USDT on MEXC
            mexc_bal = get_mexc_balances()
            if mexc_bal.get('USDT', 0) < usdt_needed:
                return False, f"Insufficient USDT on MEXC: need ${usdt_needed:.2f}, have ${mexc_bal.get('USDT', 0):.2f}"

        if coin_available_kucoin < qty:
            return False, f"Insufficient {coin} on KuCoin: need {qty:.2f}, have {coin_available_kucoin:.2f}"

    elif direction in ['K->M', 'K→M']:
        # Buying on KuCoin, selling on MEXC
        usdt_needed = qty * buy_price * 1.002  # +0.2% for fees
        coin_available_mexc = get_mexc_balances().get(coin, 0)

        if usdt_needed > 0.01:
            kucoin_bal = get_kucoin_balances()
            if kucoin_bal.get('USDT', 0) < usdt_needed:
                return False, f"Insufficient USDT on KuCoin: need ${usdt_needed:.2f}, have ${kucoin_bal.get('USDT', 0):.2f}"

        if coin_available_mexc < qty:
            return False, f"Insufficient {coin} on MEXC: need {qty:.2f}, have {coin_available_mexc:.2f}"

    return True, ""

def is_active():
    """Check if bot is marked as active"""
    return os.path.exists(ACTIVE_FLAG_FILE)

def set_active(flag):
    """Enable or disable trading"""
    if flag:
        open(ACTIVE_FLAG_FILE, 'w').write(str(datetime.now()))
    else:
        try:
            os.remove(ACTIVE_FLAG_FILE)
        except:
            pass

def log(msg, level="INFO"):
    """Enhanced logging with optional level - logs to file and HTTP server"""
    ts = datetime.now().strftime('%H:%M:%S.%f')[:-3]
    line = f"[{ts}] [{level}] {msg}"
    print(line)

    # Check log level - DEBUG messages only logged if debug enabled
    if level == "DEBUG" and not is_debug_enabled():
        return  # Skip DEBUG messages if not in debug mode

    try:
        LOG_DIR.mkdir(parents=True, exist_ok=True)
        with open(LOG_FILE, 'a') as f:
            f.write(line + '\n')
    except Exception:
        pass  # Silently fail if log file can't be written
    # Also send to HTTP log server
    http_log(msg, level)

def log_decision(title, **kwargs):
    """Log a decision point with all conditions"""
    log(f"═══ {title} ═══", "DECISION")
    for key, value in kwargs.items():
        log(f"  {key}: {value}", "DECISION")
    log("─" * 50, "DECISION")

def log_condition(name, result, expected=None, details=""):
    """Log a boolean condition check"""
    symbol = "✅" if result else "❌"
    msg = f"{symbol} {name}: {result}"
    if expected:
        msg += f" (expected: {expected})"
    if details:
        msg += f" | {details}"
    log(msg, "CONDITION")

def kucoin_sig(secret, ts, method, path, body=''):
    message = f'{ts}{method}{path}{body}'
    mac = hmac.new(secret.encode(), message.encode(), hashlib.sha256)
    return base64.b64encode(mac.digest()).decode()

def kucoin_passphrase_enc(secret, passphrase):
    """Encrypt passphrase for KuCoin API v2"""
    mac = hmac.new(secret.encode(), passphrase.encode(), hashlib.sha256)
    return base64.b64encode(mac.digest()).decode()

def get_orderbook_levels():
    """Get detailed orderbook levels from both exchanges for multi-level spread check"""
    try:
        # MEXC depth API - get top 10 levels
        resp_m = requests.get(f'https://api.mexc.com/api/v3/depth?symbol={COIN_SYMBOL_MEXC}&limit=10', timeout=5)
        m_depth = resp_m.json()

        # KuCoin Level2 API - get top 20
        resp_k = requests.get(f'https://api.kucoin.com/api/v1/market/orderbook/level2_20?symbol={COIN_SYMBOL}', timeout=5)
        k_depth = resp_k.json().get('data', {})

        # Parse MEXC asks (sorted low to high - we need to buy)
        mexc_asks = []
        if 'asks' in m_depth:
            for price, qty in m_depth['asks'][:10]:
                mexc_asks.append({'price': float(price), 'qty': float(qty)})

        # Parse KuCoin bids (sorted high to low - we need to sell)
        kucoin_bids = []
        if 'bids' in k_depth:
            for price, qty in k_depth.get('bids', [])[:10]:
                kucoin_bids.append({'price': float(price), 'qty': float(qty)})

        # For K->M direction we also need KuCoin asks and MEXC bids
        # KuCoin asks (sorted low to high)
        kucoin_asks = []
        for price, qty in k_depth.get('asks', [])[:5]:
            kucoin_asks.append({'price': float(price), 'qty': float(qty)})

        # MEXC bids (sorted high to low) - need to parse from m_depth
        mexc_bids = []
        if 'bids' in m_depth:
            for price, qty in m_depth['bids'][:5]:
                mexc_bids.append({'price': float(price), 'qty': float(qty)})

        return {
            'mexc_asks': mexc_asks,
            'kucoin_bids': kucoin_bids,
            'kucoin_asks': kucoin_asks,
            'mexc_bids': mexc_bids
        }
    except Exception as e:
        log(f"Error getting orderbook levels: {e}")
        return None

def get_prices():
    """Get Level 1 prices from real orderbook (not ticker!)"""
    try:
        # KuCoin Level1 orderbook
        resp_k = requests.get(f'https://api.kucoin.com/api/v1/market/orderbook/level1?symbol={COIN_SYMBOL}', timeout=5)
        k_data = resp_k.json()['data']

        # MEXC Level1 from depth (not ticker!)
        resp_m = requests.get(f'https://api.mexc.com/api/v3/depth?symbol={COIN_SYMBOL_MEXC}&limit=1', timeout=5)
        m_depth = resp_m.json()

        # Extract Level 1 prices
        k_bid = float(k_data['bestBid'])
        k_ask = float(k_data['bestAsk'])

        # MEXC: asks[0] = best ask (we buy here), bids[0] = best bid (we sell here)
        m_ask = float(m_depth['asks'][0][0]) if m_depth.get('asks') else 0
        m_bid = float(m_depth['bids'][0][0]) if m_depth.get('bids') else 0

        return {
            'kucoin': {'bid': k_bid, 'ask': k_ask},
            'mexc': {'bid': m_bid, 'ask': m_ask}
        }
    except Exception as e:
        log(f"Error getting prices: {e}")
        return None

def fmt_price(price, exchange):
    """Format price with exchange-specific precision"""
    if exchange == 'mexc':
        return f"{price:.{MEXC_PRICE_PRECISION}f}"
    return f"{price:.{KUCOIN_PRICE_PRECISION}f}"

def get_trading_strategy(pair):
    """Get trading strategy for pair (usdt or mpc)"""
    return get_setting(f'trading.pairs.{pair}.strategy', 'usdt')

def execute_market_buy_kucoin(qty):
    """Buy COIN on KuCoin at market price"""
    ts = str(int(time.time() * 1000))
    body = json_lib.dumps({"clientOid": ts, "symbol": COIN_SYMBOL, "side": "buy", "type": "market", "size": str(qty)})
    log(f"📤 KUCOIN Market BUY Request: {body}", "DEBUG")
    sig = kucoin_sig(KUCOIN_SECRET, ts, 'POST', '/api/v1/orders', body)

    headers = {
        'KC-API-KEY': KUCOIN_KEY,
        'KC-API-SIGN': sig,
        'KC-API-TIMESTAMP': ts,
        'KC-API-PASSPHRASE': kucoin_passphrase_enc(KUCOIN_SECRET, KUCOIN_PASSPHRASE),
        'KC-API-KEY-VERSION': '2',
        'Content-Type': 'application/json'
    }

    resp = requests.post('https://api.kucoin.com/api/v1/orders', headers=headers, data=body, timeout=10)
    return resp.json()

def execute_limit_sell_kucoin(qty, price):
    """"Sell COIN on KuCoin at limit price"""
    ts = str(int(time.time() * 1000))
    body = json_lib.dumps({"clientOid": f"{ts}_sell", "symbol": COIN_SYMBOL, "side": "sell", "type": "limit", "size": str(qty), "price": f"{price:.6f}"})
    log(f"📤 KUCOIN Limit SELL Request: {body}", "DEBUG")
    sig = kucoin_sig(KUCOIN_SECRET, ts, 'POST', '/api/v1/orders', body)

    headers = {
        'KC-API-KEY': KUCOIN_KEY,
        'KC-API-SIGN': sig,
        'KC-API-TIMESTAMP': ts,
        'KC-API-PASSPHRASE': kucoin_passphrase_enc(KUCOIN_SECRET, KUCOIN_PASSPHRASE),
        'KC-API-KEY-VERSION': '2',
        'Content-Type': 'application/json'
    }

    resp = requests.post('https://api.kucoin.com/api/v1/orders', headers=headers, data=body, timeout=10)
    return resp.json()

def execute_limit_buy_kucoin(qty, price):
    """Buy COIN on KuCoin at limit price"""
    ts = str(int(time.time() * 1000))
    body = json_lib.dumps({"clientOid": f"{ts}_buy", "symbol": COIN_SYMBOL, "side": "buy", "type": "limit", "size": str(qty), "price": f"{price:.6f}"})
    log(f"📤 KUCOIN Limit BUY Request: {body}", "DEBUG")
    sig = kucoin_sig(KUCOIN_SECRET, ts, 'POST', '/api/v1/orders', body)

    headers = {
        'KC-API-KEY': KUCOIN_KEY,
        'KC-API-SIGN': sig,
        'KC-API-TIMESTAMP': ts,
        'KC-API-PASSPHRASE': kucoin_passphrase_enc(KUCOIN_SECRET, KUCOIN_PASSPHRASE),
        'KC-API-KEY-VERSION': '2',
        'Content-Type': 'application/json'
    }

    resp = requests.post('https://api.kucoin.com/api/v1/orders', headers=headers, data=body, timeout=10)
    return resp.json()

def execute_market_sell_kucoin(qty):
    """Sell COIN on KuCoin at market price"""
    ts = str(int(time.time() * 1000))
    body = json_lib.dumps({"clientOid": ts, "symbol": COIN_SYMBOL, "side": "sell", "type": "market", "size": str(qty)})
    log(f"📤 KUCOIN Market SELL Request: {body}", "DEBUG")
    sig = kucoin_sig(KUCOIN_SECRET, ts, 'POST', '/api/v1/orders', body)

    headers = {
        'KC-API-KEY': KUCOIN_KEY,
        'KC-API-SIGN': sig,
        'KC-API-TIMESTAMP': ts,
        'KC-API-PASSPHRASE': kucoin_passphrase_enc(KUCOIN_SECRET, KUCOIN_PASSPHRASE),
        'KC-API-KEY-VERSION': '2',
        'Content-Type': 'application/json'
    }

    resp = requests.post('https://api.kucoin.com/api/v1/orders', headers=headers, data=body, timeout=10)
    return resp.json()

def execute_market_buy_mexc(qty):
    """Buy COIN on MEXC at market price"""
    log(f"📤 MEXC Market BUY Request: quantity={qty}", "DEBUG")
    ts = str(int(time.time() * 1000))
    params = f'symbol={COIN_SYMBOL_MEXC}&side=BUY&type=MARKET&quantity={qty}&timestamp={ts}'
    sig = hmac.new(MEXC_SECRET.encode('utf-8'), params.encode('utf-8'), hashlib.sha256).hexdigest()

    url = f'https://api.mexc.com/api/v3/order?{params}&signature={sig}'
    headers = {'X-MEXC-APIKEY': MEXC_KEY}

    resp = requests.post(url, headers=headers, timeout=10)
    return resp.json()

def execute_limit_sell_mexc(qty, price):
    """Sell COIN on MEXC at limit price"""
    log(f"📤 MEXC Limit SELL Request: quantity={qty}, price={price}", "DEBUG")
    ts = str(int(time.time() * 1000))
    params = f'symbol={COIN_SYMBOL_MEXC}&side=SELL&type=LIMIT&quantity={qty}&price={price:.5f}&timestamp={ts}'
    sig = hmac.new(MEXC_SECRET.encode('utf-8'), params.encode('utf-8'), hashlib.sha256).hexdigest()

    url = f'https://api.mexc.com/api/v3/order?{params}&signature={sig}'
    headers = {'X-MEXC-APIKEY': MEXC_KEY}

    resp = requests.post(url, headers=headers, timeout=10)
    return resp.json()

def execute_limit_buy_mexc(qty, price):
    """Buy COIN on MEXC at limit price"""
    log(f"📤 MEXC Limit BUY Request: quantity={qty}, price={price}", "DEBUG")
    ts = str(int(time.time() * 1000))
    params = f'symbol={COIN_SYMBOL_MEXC}&side=BUY&type=LIMIT&quantity={qty}&price={price:.5f}&timestamp={ts}'
    sig = hmac.new(MEXC_SECRET.encode('utf-8'), params.encode('utf-8'), hashlib.sha256).hexdigest()

    url = f'https://api.mexc.com/api/v3/order?{params}&signature={sig}'
    headers = {'X-MEXC-APIKEY': MEXC_KEY}

    resp = requests.post(url, headers=headers, timeout=10)
    return resp.json()

def execute_market_sell_mexc(qty):
    """Sell COIN on MEXC at market price"""
    log(f"📤 MEXC Market SELL Request: quantity={qty}", "DEBUG")
    ts = str(int(time.time() * 1000))
    params = f'symbol={COIN_SYMBOL_MEXC}&side=SELL&type=MARKET&quantity={qty}&timestamp={ts}'
    sig = hmac.new(MEXC_SECRET.encode('utf-8'), params.encode('utf-8'), hashlib.sha256).hexdigest()

    url = f'https://api.mexc.com/api/v3/order?{params}&signature={sig}'
    headers = {'X-MEXC-APIKEY': MEXC_KEY}

    resp = requests.post(url, headers=headers, timeout=10)
    return resp.json()

def get_mexc_order_status(order_id: str) -> dict:
    """Get MEXC order fill status by order ID (for polling market orders)"""
    ts = str(int(time.time() * 1000))
    params = f'symbol={COIN_SYMBOL_MEXC}&orderId={order_id}&timestamp={ts}'
    sig = hmac.new(MEXC_SECRET.encode('utf-8'), params.encode('utf-8'), hashlib.sha256).hexdigest()

    url = f'https://api.mexc.com/api/v3/order?{params}&signature={sig}'
    headers = {'X-MEXC-APIKEY': MEXC_KEY}

    resp = requests.get(url, headers=headers, timeout=10)
    return resp.json()

def poll_mexc_market_order(order_id: str, orig_qty: float, transact_time: int, max_wait_ms: int = 2000, fallback_price: float = 0.011) -> dict:
    """Get MEXC market order fill data.

    Strategy:
    1. Try private my_trades API (with API key auth)
    2. If empty or fails, try private order status API
    3. ONLY if both fail completely, use public trades API as last resort fallback

    Args:
        order_id: The MEXC order ID from the initial response
        orig_qty: Original quantity ordered (for estimating if no trade found)
        transact_time: Transaction timestamp from initial response (ms)
        max_wait_ms: How long to wait
        fallback_price: Price to use if all methods fail

    Returns:
        dict with fill data: quantity, amount, fees, status
    """
    start_time = time.time() * 1000
    poll_interval = 200  # ms
    time_window = 2000  # 2 second window to match trade

    # ========================================================================
    # METHOD 1: Try private my_trades API (PRIMARY)
    # ========================================================================
    private_api_tried = False

    while (time.time() * 1000 - start_time) < max_wait_ms:
        try:
            # Try private my_trades API
            ts = str(int(time.time() * 1000))
            params = f'symbol={COIN_SYMBOL_MEXC}&timestamp={ts}'
            sig = hmac.new(MEXC_SECRET.encode('utf-8'), params.encode('utf-8'), hashlib.sha256).hexdigest()
            url = f'https://api.mexc.com/api/v3/my_trades?{params}&signature={sig}'
            headers = {'X-MEXC-APIKEY': MEXC_KEY}

            resp = requests.get(url, headers=headers, timeout=10)

            if resp.status_code == 200 and resp.text and len(resp.text) > 0:
                private_api_tried = True
                trades = resp.json()

                if isinstance(trades, list) and trades:
                    # Find trade matching our order by timestamp
                    for trade in trades:
                        trade_time = int(trade.get('time', 0))
                        if abs(trade_time - transact_time) <= time_window:
                            qty = float(trade.get('qty', 0))
                            price = float(trade.get('price', 0))
                            quote_qty = float(trade.get('quoteQty', 0))

                            if qty > 0:
                                log(f"   Found MEXC trade (private API): qty={qty}, price={price}, value=${quote_qty:.4f}")
                                return {
                                    'status': 'Filled',
                                    'quantity': str(qty),
                                    'amount': str(quote_qty),
                                    'fees': str(quote_qty * 0.001),
                                    'price': str(price),
                                    'executedQty': str(qty),
                                    'cummulativeQuoteQty': str(quote_qty)
                                }
        except Exception as e:
            pass  # Silently continue to next method

        time.sleep(poll_interval / 1000)

    # ========================================================================
    # METHOD 2: Try private order status API (SECONDARY)
    # ========================================================================
    log(f"   Private API returned no trades, trying order status...")

    try:
        ts = str(int(time.time() * 1000))
        params = f'symbol={COIN_SYMBOL_MEXC}&orderId={order_id}&timestamp={ts}'
        sig = hmac.new(MEXC_SECRET.encode('utf-8'), params.encode('utf-8'), hashlib.sha256).hexdigest()
        url = f'https://api.mexc.com/api/v3/order?{params}&signature={sig}'
        headers = {'X-MEXC-APIKEY': MEXC_KEY}

        resp = requests.get(url, headers=headers, timeout=10)

        if resp.status_code == 200 and resp.text:
            order_data = resp.json()
            if order_data.get('executedQty') and float(order_data.get('executedQty', 0)) > 0:
                qty = float(order_data.get('executedQty', 0))
                quote = float(order_data.get('cummulativeQuoteQty', 0))
                price = float(order_data.get('price', 0)) or fallback_price
                log(f"   Found MEXC order (order status API): qty={qty}, value=${quote:.4f}")
                return {
                    'status': 'Filled',
                    'quantity': str(qty),
                    'amount': str(quote),
                    'fees': str(quote * 0.001),
                    'price': str(price),
                    'executedQty': str(qty),
                    'cummulativeQuoteQty': str(quote)
                }
    except Exception as e:
        pass  # Silently continue to fallback

    # ========================================================================
    # METHOD 3: Public trades API (LAST RESORT FALLBACK ONLY!)
    # ========================================================================
    log(f"   WARNING: Both private APIs failed - using PUBLIC API fallback!")

    try:
        trades_url = f'https://api.mexc.com/api/v3/trades?symbol={COIN_SYMBOL_MEXC}&limit=5'
        resp = requests.get(trades_url, timeout=10)
        trades = resp.json()

        if trades and isinstance(trades, list):
            for trade in trades:
                trade_time = int(trade.get('time', 0))
                if abs(trade_time - transact_time) <= time_window:
                    qty = float(trade.get('qty', 0))
                    price = float(trade.get('price', 0))
                    quote_qty = float(trade.get('quoteQty', 0))

                    if qty > 0:
                        log(f"   PUBLIC API fallback used: qty={qty}, price={price}")
                        return {
                            'status': 'Filled',
                            'quantity': str(qty),
                            'amount': str(quote_qty),
                            'fees': str(quote_qty * 0.001),
                            'price': str(price),
                            'executedQty': str(qty),
                            'cummulativeQuoteQty': str(quote_qty)
                        }
    except:
        pass

    # ========================================================================
    # FINAL FALLBACK: Use estimated data
    # ========================================================================
    log(f"   All APIs failed - using estimated data")
    return {
        'status': 'Filled',
        'quantity': str(orig_qty),
        'amount': str(orig_qty * fallback_price),
        'fees': str(orig_qty * fallback_price * 0.001),
        'price': str(fallback_price),
        'executedQty': str(orig_qty),
        'cummulativeQuoteQty': str(orig_qty * fallback_price)
    }

def execute_trade_market_buy_limit_sell(exchange_market, exchange_limit, qty, buy_price, sell_price, strategy='usdt', spread_pct=0.0):
    """Execute arbitrage trade: Market Buy on one exchange, Limit Sell on another.

    GENERIC FUNCTION - Works with ANY two exchanges!
    Examples:
        - KuCoin + MEXC: execute_trade_market_buy_limit_sell("KUCOIN", "MEXC", ...)
        - Binance + KuCoin: execute_trade_market_buy_limit_sell("BINANCE", "KUCOIN", ...)
        - MEXC + Binance: execute_trade_market_buy_limit_sell("MEXC", "BINANCE", ...)

    Args:
        exchange_market: Exchange for market order (BUY) - e.g. "KUCOIN", "MEXC", "BINANCE"
        exchange_limit: Exchange for limit order (SELL) - e.g. "MEXC", "KUCOIN", "BINANCE"
        qty: Quantity to buy on market exchange
        buy_price: Expected price on market exchange
        sell_price: Expected price on limit exchange
        strategy: 'usdt' or 'coins'
        spread_pct: Spread % when trade was triggered

    Returns:
        (success, trade_id)
    """
    # Determine direction string for logging
    dir_str = f"{exchange_market[:1]}->{exchange_limit[:1]}"  # e.g. "K->M" or "M->K"

    log(f"=== EXECUTING TRADE {dir_str} (strategy={strategy}) ===")
    coin = COIN_SYMBOL.split('-')[0]
    log(f"Market BUY on {exchange_market}: {qty} {coin} @ ${buy_price:.6f}")
    log(f"Limit SELL on {exchange_limit}: @ ${sell_price:.6f}")

    # Store expected prices for logging
    market_price_expected = buy_price
    limit_price_expected = sell_price

    # Capture internal timestamp
    internal_ts = datetime.now().isoformat()

    # Track error state
    error_code = None
    error_message = None
    ex1_data = None
    ex2_data = None

    # ========================================================================
    # PRE-TRADE BALANCE CHECK
    # ========================================================================
    log(f"Checking balances for {dir_str} trade...")
    can_trade, balance_error = check_balances_for_trade(dir_str, qty, buy_price, sell_price)
    if not can_trade:
        log(f"❌ BALANCE CHECK FAILED: {balance_error}")
        return False, None
    log(f"✅ Balance check passed")

    # ========================================================================
    # STEP 1: Market BUY on exchange_market
    # ========================================================================
    log(f"Step 1: {exchange_market} Market BUY...")

    # Route to correct API based on exchange
    if exchange_market.upper() == "KUCOIN":
        result1 = execute_market_buy_kucoin(qty)
        ex1_harmonize = harmonize_kucoin_order
        api_success_check = lambda r: r.get('code') == '200000'
    elif exchange_market.upper() == "MEXC":
        result1 = execute_market_buy_mexc(qty)
        ex1_harmonize = harmonize_mexc_order
        api_success_check = lambda r: r.get('code') is None or 'orderId' not in r
    else:
        error_code = "UNKNOWN_EXCHANGE"
        error_message = f"Unknown market exchange: {exchange_market}"
        log(f"❌ {error_message}")
        return False, None

    log(f"DEBUG {exchange_market} Response: {result1}")

    # Check for API errors
    if not api_success_check(result1):
        error_code = "API_ERROR"
        error_message = f"{exchange_market} market order failed: {result1}"
        log(f"❌ {error_message}")

        # Create failed ex1_data for logging
        ex1_data = {"exchange": exchange_market.upper(), "order_id": "FAILED", "type": "market",
                    "side": "buy", "qty_ordered": qty, "qty_filled": 0,
                    "price_expected": market_price_expected, "price_actual": 0,
                    "value_usdt": 0, "fees": 0, "create_ts": 0, "status": "REJECTED",
                    "raw_response": result1}
        ex2_data = {"exchange": exchange_limit.upper(), "order_id": "FAILED", "type": "limit",
                    "side": "sell", "qty_ordered": 0, "qty_filled": 0,
                    "price_expected": limit_price_expected, "price_actual": 0,
                    "value_usdt": 0, "fees": 0, "create_ts": 0, "status": "NOT_PLACED",
                    "raw_response": {}}

        trade_id = log_trade(
            pair=TRADING_PAIR,
            internal_ts=internal_ts,
            direction=dir_str,
            ex1_data=ex1_data,
            ex2_data=ex2_data,
            limit_watch_status="ERROR",
            strategy=strategy.upper(),
            spread_pct=spread_pct,
            market_price_expected=market_price_expected,
            limit_price_expected=limit_price_expected,
            error_code=error_code,
            error_message=error_message
        )
        log(f"📝 Trade logged with error: {trade_id}")
        return False, trade_id

    # Harmonize successful response
    order_id1 = result1.get('orderId', 'unknown') or result1.get('orderId', 'unknown')
    orig_qty1 = float(result1.get('origQty', 0) or 0)
    transact_time1 = int(result1.get('transactTime', 0) or 0)
    log(f"✅ {exchange_market} Order placed: {order_id1} (qty={orig_qty1}, time={transact_time1})")

    # MEXC market orders are async - get actual fill from trades API
    if exchange_market.upper() == "MEXC":
        log(f"   Polling MEXC trades API for fill...")
        filled_response = poll_mexc_market_order(order_id1, orig_qty1, transact_time1, max_wait_ms=2000, fallback_price=market_price_expected)
        result1 = filled_response  # Use the filled response
        log(f"   After polling: status={filled_response.get('status')}, quantity={filled_response.get('quantity')}, amount={filled_response.get('amount')}")

    # Get the response data for harmonization (KuCoin nests in 'data', MEXC doesn't)
    response_data1 = result1.get('data', result1) if exchange_market.upper() == "KUCOIN" else result1
    ex1_data = ex1_harmonize(response_data1, "buy", "market", TRADING_PAIR)
    ex1_data['price_expected'] = market_price_expected
    log(f"   Harmonized: qty_filled={ex1_data['qty_filled']}, value_usdt={ex1_data['value_usdt']:.4f}, fees={ex1_data['fees']:.4f}")

    # CRITICAL CHECK: qty_filled must not be 0
    if ex1_data['qty_filled'] == 0:
        error_code = "QTY_ZERO"
        error_message = f"{exchange_market} market order returned qty_filled=0! Counter-order ABORTED."
        log(f"❌ {error_message}")

        # Log trade with error but NO limit order placed
        ex2_data = {"exchange": exchange_limit.upper(), "order_id": "NOT_PLACED", "type": "limit",
                    "side": "sell", "qty_ordered": 0, "qty_filled": 0,
                    "price_expected": limit_price_expected, "price_actual": 0,
                    "value_usdt": 0, "fees": 0, "create_ts": 0, "status": "NOT_PLACED",
                    "raw_response": {}}

        trade_id = log_trade(
            pair=TRADING_PAIR,
            internal_ts=internal_ts,
            direction=dir_str,
            ex1_data=ex1_data,
            ex2_data=ex2_data,
            limit_watch_status="ERROR",
            strategy=strategy.upper(),
            spread_pct=spread_pct,
            market_price_expected=market_price_expected,
            limit_price_expected=limit_price_expected,
            error_code=error_code,
            error_message=error_message
        )
        log(f"📝 Trade logged with error: {trade_id}")
        return False, trade_id

    # ========================================================================
    # STEP 2: Determine sell quantity based on strategy
    # ========================================================================
    if strategy == 'coins':
        # Coins strategy: sell less MPC to keep the spread as MPC profit
        # USDT spent (minus fees) / sell price = MPC to sell
        usdt_to_sell = ex1_data['value_usdt'] - ex1_data['fees']
        sell_qty = usdt_to_sell / sell_price if sell_price > 0 else qty
        coin = COIN_SYMBOL.split('-')[0]
        log(f"Strategy=COINS: USDT spent={usdt_to_sell:.4f}, calculating {coin} to sell @ ${sell_price:.6f}")
    else:
        # USDT strategy: sell same quantity as bought
        sell_qty = ex1_data['qty_filled']

    # Round to integer for KuCoin (KuCoin requires whole numbers, increment=1)
    # Also ensure minimum of 10 MPC for KuCoin
    sell_qty = max(10, round(sell_qty))

    coin = COIN_SYMBOL.split('-')[0]
    log(f"Step 2: {exchange_limit} Limit SELL: {sell_qty:.4f} {coin} @ ${sell_price:.6f}")

    # Small delay before placing limit order
    time.sleep(0.5)

    # ========================================================================
    # STEP 3: Limit SELL on exchange_limit
    # ========================================================================
    log(f"Step 2: {exchange_limit} Limit SELL...")

    # Route to correct API based on exchange
    if exchange_limit.upper() == "KUCOIN":
        result2 = execute_limit_sell_kucoin(sell_qty, sell_price)
        ex2_harmonize = harmonize_kucoin_order
        limit_success_check = lambda r: r.get('code') == '200000'
    elif exchange_limit.upper() == "MEXC":
        result2 = execute_limit_sell_mexc(sell_qty, sell_price)
        ex2_harmonize = harmonize_mexc_order
        limit_success_check = lambda r: r.get('code') is None or 'orderId' in r
    else:
        error_code = "UNKNOWN_EXCHANGE"
        error_message = f"Unknown limit exchange: {exchange_limit}"
        log(f"❌ {error_message}")
        result2 = {"error": error_message}

    if limit_success_check(result2):
        order_id2 = result2.get('data', {}).get('orderId') or result2.get('orderId', 'unknown')
        log(f"✅ {exchange_limit} Order placed: {order_id2}")

        # Get the response data for harmonization
        response_data2 = result2.get('data', result2) if exchange_limit.upper() == "KUCOIN" else result2
        ex2_data = ex2_harmonize(response_data2, "sell", "limit", TRADING_PAIR)
        ex2_data['price_expected'] = limit_price_expected
        log(f"   Harmonized: qty_ordered={ex2_data['qty_ordered']}, qty_filled={ex2_data['qty_filled']}, price_actual={ex2_data['price_actual']:.6f}")
    else:
        log(f"❌ {exchange_limit} Error: {result2}")
        error_code = "LIMIT_ORDER_FAILED"
        error_message = f"{exchange_limit} limit order failed: {result2}"

        # Log trade even with limit order failure
        ex2_data = {"exchange": exchange_limit.upper(), "order_id": "FAILED", "type": "limit",
                    "side": "sell", "qty_ordered": sell_qty, "qty_filled": 0,
                    "price_expected": limit_price_expected, "price_actual": 0,
                    "value_usdt": 0, "fees": 0, "create_ts": 0, "status": "FAILED",
                    "raw_response": result2 if isinstance(result2, dict) else {}}

    # ========================================================================
    # STEP 4: Calculate expected profit and log trade
    # ========================================================================
    cost = ex1_data['value_usdt']
    revenue = ex2_data['value_usdt']
    gross_profit = revenue - cost
    fee_taker = ex1_data['fees']
    fee_maker = ex2_data.get('fees', 0)
    net_profit = gross_profit - fee_taker - fee_maker
    mpc_gain = net_profit / sell_price if sell_price > 0 else 0

    # Log trade with harmonized data
    trade_id = log_trade(
        pair=TRADING_PAIR,
        internal_ts=internal_ts,
        direction=dir_str,
        ex1_data=ex1_data,
        ex2_data=ex2_data,
        limit_watch_status="WATCHING",
        strategy=strategy.upper(),
        spread_pct=spread_pct,
        market_price_expected=market_price_expected,
        limit_price_expected=limit_price_expected,
        profit_usdt_expected=net_profit,
        profit_mpc_expected=mpc_gain,
        error_code=error_code,
        error_message=error_message
    )
    log(f"📝 Trade logged: {trade_id}")

    log(f"=== TRADE LOGGED (pending limit fill) ===")
    log(f"Cost: ${cost:.4f} | Revenue: ${revenue:.4f}")
    log(f"Gross Profit: ${gross_profit:.4f} | Fees: ${fee_taker + fee_maker:.4f}")
    coin = COIN_SYMBOL.split('-')[0]
    log(f"Expected Net Profit: ${net_profit:.4f} | {coin} Gain: {mpc_gain:.4f}")

    return True, trade_id


# Legacy alias for backward compatibility (will be removed)
def execute_trade_M_to_K(qty, buy_price, sell_price, strategy='usdt', spread_pct=0.0):
    """Legacy: Use execute_trade_market_buy_limit_sell('MEXC', 'KUCOIN', ...) instead"""
    return execute_trade_market_buy_limit_sell('MEXC', 'KUCOIN', qty, buy_price, sell_price, strategy, spread_pct)


def execute_trade_K_to_M(qty, buy_price, sell_price, strategy='usdt', spread_pct=0.0):
    """Legacy: Use execute_trade_market_buy_limit_sell('KUCOIN', 'MEXC', ...) instead"""
    return execute_trade_market_buy_limit_sell('KUCOIN', 'MEXC', qty, buy_price, sell_price, strategy, spread_pct)




def check_limit_order_fills():
    """
    Background task: Check pending limit orders and update status.
    This polls the exchanges for fill status.
    """
    pending = get_pending_limit_orders(TRADING_PAIR)

    if not pending:
        return

    log(f"🔍 Checking {len(pending)} pending limit orders...")

    for trade in pending:
        direction = trade.get('direction', '')
        ex2_exchange = trade.get('ex2_exchange', '')
        ex2_order_id = trade.get('ex2_order_id', '')
        trade_id = trade.get('trade_id', '')

        if not ex2_order_id or ex2_order_id == 'FAILED':
            continue

        # Poll exchange for order status
        try:
            if ex2_exchange == 'KUCOIN':
                # Check KuCoin order status
                ts = str(int(time.time() * 1000))
                path = f'/api/v1/orders/{ex2_order_id}'
                sig = kucoin_sig(KUCOIN_SECRET, ts, 'GET', path)

                headers = {
                    'KC-API-KEY': KUCOIN_KEY,
                    'KC-API-SIGN': sig,
                    'KC-API-TIMESTAMP': ts,
                    'KC-API-PASSPHRASE': kucoin_passphrase_enc(KUCOIN_SECRET, KUCOIN_PASSPHRASE),
                }

                resp = requests.get(f'https://api.kucoin.com{path}', headers=headers, timeout=10)
                data = resp.json().get('data', {})

                status = data.get('status', '')
                deal_size = float(data.get('dealSize', 0) or 0)
                deal_funds = float(data.get('dealFunds', 0) or 0)

                if status == 'Done':
                    update_limit_watch(trade_id, TRADING_PAIR, 'FILLED',
                                     qty_filled=deal_size,
                                     price_avg=deal_funds/deal_size if deal_size > 0 else 0,
                                     fees=float(data.get('fee', 0) or 0))
                    log(f"✅ Limit filled: {trade_id}")
                elif status == 'Active' and deal_size > 0:
                    update_limit_watch(trade_id, TRADING_PAIR, 'PARTIAL', qty_filled=deal_size)

            elif ex2_exchange == 'MEXC':
                # Check MEXC order status
                ts = str(int(time.time() * 1000))
                params = f'symbol={COIN_SYMBOL_MEXC}&orderId={ex2_order_id}&timestamp={ts}'
                sig = hmac.new(MEXC_SECRET.encode('utf-8'), params.encode('utf-8'), hashlib.sha256).hexdigest()

                url = f'https://api.mexc.com/api/v3/order?{params}&signature={sig}'
                headers = {'X-MEXC-APIKEY': MEXC_KEY}

                resp = requests.get(url, headers=headers, timeout=10)
                data = resp.json()

                status = data.get('status', '')
                qty_filled = float(data.get('quantity', 0) or 0)
                amount_filled = float(data.get('amount', 0) or 0)

                if status == 'Filled':
                    update_limit_watch(trade_id, TRADING_PAIR, 'FILLED',
                                     qty_filled=qty_filled,
                                     price_avg=amount_filled/qty_filled if qty_filled > 0 else 0,
                                     fees=float(data.get('fees', 0) or 0))
                    log(f"✅ Limit filled: {trade_id}")
                elif status == 'PartiallyFilled' and qty_filled > 0:
                    update_limit_watch(trade_id, TRADING_PAIR, 'PARTIAL', qty_filled=qty_filled)

        except Exception as e:
            log(f"⚠️ Error checking order {ex2_order_id}: {e}")


def main():
    log("=== AUTO-TRADE BOT STARTED ===")
    log("Strategy: Coin-Gewinn (COIN akkumulieren)")
    log("Principle: ONE TRADE AT A TIME")
    log(f"Logging: Harmonized CSV per pair -> {TRADING_PAIR}_trades.csv")

    # Ensure logs directory exists
    os.makedirs('/home/openclaw/.openclaw/logs', exist_ok=True)

    # Thresholds - load from config directly (avoiding settings_sync import issues)
    try:
        config_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'config', 'config.yaml')
        with open(config_path, 'r') as f:
            cfg = yaml.safe_load(f)
        pair_cfg = cfg.get('trading', {}).get('pairs', {}).get(TRADING_PAIR, {})
        START_THRESHOLD = pair_cfg.get('threshold_start', 1.0)
        STOP_THRESHOLD = pair_cfg.get('threshold_stop', 0.5)
        log(f"Thresholds geladen: start={START_THRESHOLD}%, stop={STOP_THRESHOLD}%")
    except Exception as e:
        log(f"Konnte thresholds nicht aus config laden: {e}, verwende defaults")
        START_THRESHOLD = 1.0
        STOP_THRESHOLD = 0.5

    # State machine
    STATE_WAITING = 'WAITING'
    STATE_RUNNING = 'RUNNING'
    state = STATE_WAITING
    trade_in_progress = False
    last_spread_ok = None  # Track spread condition changes
    last_pair_enabled = None  # Track pair enabled changes

    # Start HTTP logging server for real-time monitoring
    start_http_log_server(port=8505)
    http_log("Bot gestartet", "INFO")
    last_config_hash = None  # Track config changes for immediate logging
    last_trade_time = 0
    last_limit_check = 0

    # Read enabled status from config
    config = load_config()
    pair_enabled = get_setting(f'trading.pairs.{TRADING_PAIR}.enabled', False)
    current_strategy = get_setting(f'trading.pairs.{TRADING_PAIR}.strategy', 'usdt')
    log(f"Pair {TRADING_PAIR} enabled in config: {pair_enabled}")

    # ALWAYS start inactive for safety - user must enable via dashboard
    log("=== BOT STARTET IM INAKTIV STATUS (Safety First) ===")
    pair_enabled = False
    set_setting(f'trading.pairs.{TRADING_PAIR}.enabled', False)

    while True:
        # Re-read all settings from config each cycle
        pair_enabled = get_setting(f'trading.pairs.{TRADING_PAIR}.enabled', False)
        current_strategy = get_setting(f'trading.pairs.{TRADING_PAIR}.strategy', 'usdt')
        threshold_start = get_setting(f'trading.pairs.{TRADING_PAIR}.threshold_start', 1.0)
        threshold_stop = get_setting(f'trading.pairs.{TRADING_PAIR}.threshold_stop', 0.5)
        current_log_level = get_log_level()

        # Check if any setting changed - log immediately if so
        import hashlib
        config_hash = f"{pair_enabled}|{current_strategy}|{threshold_start}|{threshold_stop}|{current_log_level}"
        if config_hash != last_config_hash:
            log_decision("CONFIG_CHANGED",
                pair_enabled=str(pair_enabled),
                strategy=current_strategy,
                log_level=f"Level {current_log_level}",
                threshold=f"{threshold_start:.2f}%",
                threshold_stop=f"{threshold_stop:.2f}%"
            )
            last_config_hash = config_hash

        prices = get_prices()
        if not prices:
            time.sleep(1)
            continue

        k = prices['kucoin']
        m = prices['mexc']

        # Check M->K (Buy MEXC, Sell KuCoin)
        spread_mk = k['bid'] - m['ask']
        spread_pct_mk = (spread_mk / m['ask']) * 100 if m['ask'] > 0 else 0

        # Check K->M (Buy KuCoin, Sell MEXC)
        spread_km = m['bid'] - k['ask']
        spread_pct_km = (spread_km / k['ask']) * 100 if k['ask'] > 0 else 0

        # Get real orderbook levels
        ob_data = get_orderbook_levels()

        # Calculate minimum trade quantity
        mexc_min_qty = round((MEXC_MIN_USDT + 0.1) / m['ask']) if m['ask'] > 0 else 85
        kucoin_min_qty = KUCOIN_MIN_QTY
        min_trade_qty = max(mexc_min_qty, kucoin_min_qty)

        # Find best tradeable spread using sweep algorithm
        best_trade = None
        vol_for_mexc = min_trade_qty  # Default volume
        vol_for_kucoin = min_trade_qty

        if ob_data:
            # Direction M→K: Buy MEXC (sweep asks), Sell KuCoin (fix bids)
            # For each KuCoin bid level (best first), sweep through MEXC asks
            for k_bid in ob_data['kucoin_bids'][:5]:  # Top 5 bid levels
                cum_vol_mexc = 0  # Cumulative volume on MEXC (buy) side

                for m_ask in ob_data['mexc_asks'][:5]:  # Sweep through asks
                    spread = k_bid['price'] - m_ask['price']
                    spread_pct = (spread / m_ask['price']) * 100 if m_ask['price'] > 0 else 0
                    cum_vol_mexc += m_ask['qty']  # Add cumulative volume

                    # STOP_THRESHOLD check - spread too low, no deeper level will help
                    if spread_pct < STOP_THRESHOLD:
                        break

                    # START_THRESHOLD check - spread is interesting
                    if spread_pct >= threshold_start and cum_vol_mexc >= min_trade_qty and k_bid['qty'] >= min_trade_qty:
                        # Calculate expected profit for decision
                        strategy = get_trading_strategy(TRADING_PAIR)
                        expected_profit_usdt = (k_bid['price'] - m_ask['price']) * min(cum_vol_mexc, k_bid['qty'])
                        expected_profit_mpc = expected_profit_usdt / m_ask['price'] if m_ask['price'] > 0 else 0

                        profit_for_decision = expected_profit_mpc if strategy == 'coins' else expected_profit_usdt

                        if best_trade is None or profit_for_decision > (best_trade.get('profit_mpc' if strategy == 'coins' else 'profit_usdt', 0)):
                            best_trade = {
                                'dir': 'M→K',
                                'buy': m_ask['price'],
                                'sell': k_bid['price'],
                                'pct': spread_pct,
                                'vol': min(cum_vol_mexc, k_bid['qty']),
                                'profit_usdt': expected_profit_usdt,
                                'profit_mpc': expected_profit_mpc,
                                'strategy': strategy
                            }
                        break  # Found tradeable at this bid level, move to next bid

            # Direction K→M: Buy KuCoin (sweep asks), Sell MEXC (fix bids)
            for m_bid in ob_data['mexc_bids'][:5]:  # Top 5 bid levels on MEXC
                cum_vol_kucoin = 0  # Cumulative volume on KuCoin (buy) side

                for k_ask in ob_data.get('kucoin_asks', [])[:5]:  # Sweep through asks
                    spread = m_bid['price'] - k_ask['price']
                    spread_pct = (spread / k_ask['price']) * 100 if k_ask['price'] > 0 else 0
                    cum_vol_kucoin += k_ask['qty']  # Add cumulative volume

                    # STOP_THRESHOLD check
                    if spread_pct < STOP_THRESHOLD:
                        break

                    # START_THRESHOLD check
                    if spread_pct >= threshold_start and cum_vol_kucoin >= min_trade_qty and m_bid['qty'] >= min_trade_qty:
                        # Calculate expected profit for decision
                        strategy = get_trading_strategy(TRADING_PAIR)
                        expected_profit_usdt = (m_bid['price'] - k_ask['price']) * min(cum_vol_kucoin, m_bid['qty'])
                        expected_profit_mpc = expected_profit_usdt / k_ask['price'] if k_ask['price'] > 0 else 0

                        profit_for_decision = expected_profit_mpc if strategy == 'coins' else expected_profit_usdt

                        if best_trade is None or profit_for_decision > (best_trade.get('profit_mpc' if strategy == 'coins' else 'profit_usdt', 0)):
                            best_trade = {
                                'dir': 'K→M',
                                'buy': k_ask['price'],
                                'sell': m_bid['price'],
                                'pct': spread_pct,
                                'vol': min(cum_vol_kucoin, m_bid['qty']),
                                'profit_usdt': expected_profit_usdt,
                                'profit_mpc': expected_profit_mpc,
                                'strategy': strategy
                            }
                        break

        # Log sweep results every 30 seconds
        if int(time.time()) % 10 == 0:
            if ob_data:
                total_mexc = sum(x['qty'] for x in ob_data['mexc_asks'][:5])
                total_kucoin = sum(x['qty'] for x in ob_data['kucoin_bids'][:5])
                strategy = get_trading_strategy(TRADING_PAIR)
                coin = COIN_SYMBOL.split('-')[0]
                log(f"Sweep: {strategy.upper()} strategy | MEXC top5={total_mexc:.0f} {coin}, KuCoin top5={total_kucoin:.0f} {coin}, min={min_trade_qty}")
                if best_trade:
                    coin = COIN_SYMBOL.split('-')[0]
                    log(f"  Best: {best_trade['dir']} @ {best_trade['pct']:.3f}% | Vol={best_trade['vol']:.0f} {coin} | profit_usdt=${best_trade['profit_usdt']:.4f} | profit_{coin}={best_trade['profit_mpc']:.4f}")
                else:
                    log(f"  No tradeable spread found (spread below thresholds or insufficient volume)")

        # Log volume check every 15s
        if int(time.time()) % 15 == 0 and ob_data:
            total_mexc_vol = sum(x['qty'] for x in ob_data['mexc_asks'][:5])
            total_kucoin_vol = sum(x['qty'] for x in ob_data['kucoin_bids'][:5])
            coin = COIN_SYMBOL.split('-')[0]
            log(f"Orderbook: MEXC top5={total_mexc_vol:.0f} {coin}, KuCoin top5={total_kucoin_vol:.0f} {coin}, min_needed={min_trade_qty}")
            coin = COIN_SYMBOL.split('-')[0]
            log(f"Best trade: {best_trade['dir']} @ {best_trade['pct']:.3f}% | Vol={best_trade['vol']:.0f} {coin}" if best_trade else "No tradeable spread")

        if not ob_data:
            # Fallback when orderbook fetch fails
            vol_for_mexc = round((MEXC_MIN_USDT + 1) / m['ask']) if m['ask'] > 0 else 86
            vol_for_kucoin = max(KUCOIN_MIN_QTY, vol_for_mexc)


        # Log every 30 seconds
        if int(time.time()) % 10 == 0:
            log(f"Prices: K={fmt_price(k['bid'],'kucoin')}/{fmt_price(k['ask'],'kucoin')} | M={fmt_price(m['bid'],'mexc')}/{fmt_price(m['ask'],'mexc')}")
            log(f"  M->K spread: {spread_pct_mk:.2f}% | K->M spread: {spread_pct_km:.2f}%")

        # Check limit order fills every 10 seconds
        if time.time() - last_limit_check > 10:
            check_limit_order_fills()
            last_limit_check = time.time()

        # Determine which spread direction is profitable
        profitable_spread = max(spread_pct_km, spread_pct_mk)
        direction = "K→M" if spread_pct_km >= spread_pct_mk else "M→K"

        # Log periodic status every 30 seconds for monitoring
        if int(time.time()) % 10 == 0:
            log_decision("STATUS_CHECK",
                state=state,
                pair_enabled=str(pair_enabled),
                strategy=current_strategy,
                log_level=f"Level {get_log_level()}",
                spread_mk=f"{spread_pct_mk:.3f}%",
                spread_km=f"{spread_pct_km:.3f}%",
                best_spread=f"{profitable_spread:.3f}%",
                direction=direction,
                threshold=f"{threshold_start:.2f}%",
                threshold_stop=f"{threshold_stop:.2f}%",
                vol_mexc=f"{vol_for_mexc:.0f}",
                vol_kucoin=f"{vol_for_kucoin:.0f}"
            )

        # Trade BOTH directions when profitable!
        if not pair_enabled:
            state = STATE_WAITING
            if int(time.time()) % 10 == 0:
                log(f"INAKTIV - keine Trades")
            time.sleep(1)
            continue

        # Log condition check only when state CHANGES (reduce spam)
        current_spread_ok = profitable_spread >= threshold_start
        if current_spread_ok != last_spread_ok:
            log_condition("Spread >= START_THRESHOLD",
                current_spread_ok,
                expected=f"{threshold_start}%",
                details=f"actual={profitable_spread:.3f}%"
            )
            last_spread_ok = current_spread_ok

        # State machine logic
        if state == STATE_WAITING:
            if profitable_spread >= threshold_start and not trade_in_progress:
                log(f"🚀 TRIGGER: spread={profitable_spread:.2f}% >= threshold={threshold_start}%", "DECISION")
                state = STATE_RUNNING
                trade_in_progress = True

                # Execute best trade found by sweep
                if best_trade:
                    # KuCoin requires WHOLE NUMBER quantities (baseIncrement=1 for MPC-USDT)
                    # Fractional quantities like 119.34 cause 'Order size increment invalid' error
                    # IMPORTANT: For Market BUY orders (takes liquidity from orderbook)
                    # -> use math.floor() to NEVER exceed available volume
                    # For Limit SELL orders (creates new order on book) -> can use round()
                    vol_for_mexc = math.floor(best_trade['vol'])
                    vol_for_kucoin = math.floor(best_trade['vol'])
                    trade_strategy = best_trade.get('strategy', current_strategy)
                    coin = COIN_SYMBOL.split('-')[0]
                    log(f"🚀 Executing: {best_trade['dir']} @ {best_trade['pct']:.3f}% | Vol={best_trade['vol']:.0f} {coin} | strategy={trade_strategy}")
                    if best_trade['dir'] == 'K→M':
                        success, trade_id = execute_trade_market_buy_limit_sell('KUCOIN', 'MEXC', vol_for_kucoin, best_trade['buy'], best_trade['sell'], trade_strategy, best_trade['pct'])
                    else:
                        success, trade_id = execute_trade_market_buy_limit_sell('MEXC', 'KUCOIN', vol_for_mexc, best_trade['buy'], best_trade['sell'], trade_strategy, best_trade['pct'])
                elif spread_pct_km >= spread_pct_mk:
                    success, trade_id = execute_trade_market_buy_limit_sell('KUCOIN', 'MEXC', math.floor(vol_for_kucoin), k['ask'], m['bid'], current_strategy, spread_pct_km)
                else:
                    success, trade_id = execute_trade_market_buy_limit_sell('MEXC', 'KUCOIN', math.floor(vol_for_mexc), m['ask'], k['bid'], current_strategy, spread_pct_mk)
                
                last_trade_time = time.time()
                trade_in_progress = False
        
        elif state == STATE_RUNNING:
            if profitable_spread < STOP_THRESHOLD:
                log(f"⏹ STOPPING: spread={profitable_spread:.2f}% < STOP_THRESHOLD={STOP_THRESHOLD}%")
                state = STATE_WAITING
            elif not trade_in_progress:
                trade_in_progress = True
                # Execute best trade found by sweep
                if best_trade:
                    # KuCoin requires WHOLE NUMBER quantities (baseIncrement=1 for MPC-USDT)
                    # Fractional quantities like 119.34 cause 'Order size increment invalid' error
                    # IMPORTANT: For Market BUY orders (takes liquidity from orderbook)
                    # -> use math.floor() to NEVER exceed available volume
                    # For Limit SELL orders (creates new order on book) -> can use round()
                    vol_for_mexc = math.floor(best_trade['vol'])
                    vol_for_kucoin = math.floor(best_trade['vol'])
                    trade_strategy = best_trade.get('strategy', current_strategy)
                    coin = COIN_SYMBOL.split('-')[0]
                    log(f"🚀 Executing: {best_trade['dir']} @ {best_trade['pct']:.3f}% | Vol={best_trade['vol']:.0f} {coin} | strategy={trade_strategy}")
                    if best_trade['dir'] == 'K→M':
                        success, trade_id = execute_trade_market_buy_limit_sell('KUCOIN', 'MEXC', vol_for_kucoin, best_trade['buy'], best_trade['sell'], trade_strategy, best_trade['pct'])
                    else:
                        success, trade_id = execute_trade_market_buy_limit_sell('MEXC', 'KUCOIN', vol_for_mexc, best_trade['buy'], best_trade['sell'], trade_strategy, best_trade['pct'])
                elif spread_pct_km >= spread_pct_mk:
                    success, trade_id = execute_trade_market_buy_limit_sell('KUCOIN', 'MEXC', math.floor(vol_for_kucoin), k['ask'], m['bid'], current_strategy, spread_pct_km)
                else:
                    success, trade_id = execute_trade_market_buy_limit_sell('MEXC', 'KUCOIN', math.floor(vol_for_mexc), m['ask'], k['bid'], current_strategy, spread_pct_mk)

                last_trade_time = time.time()
                trade_in_progress = False

        time.sleep(1)  # Check every second

if __name__ == '__main__':
    main()