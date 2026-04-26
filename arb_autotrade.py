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
from datetime import datetime
import os

# Import settings_sync for config access
sys.path.insert(0, '/app')
try:
    from settings_sync import get_setting, set_setting, get_pair_settings, load_config
except ImportError:
    get_setting = None
    get_pair_settings = None
    load_config = None

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
KUCOIN_MIN_MPC = 85  # Minimum ~85 MPC per order (≈1 USDT at ~$0.012)

# Exchange precision (decimal places)
MEXC_PRICE_PRECISION = 5  # MEXC uses 5 decimal places for MPC
KUCOIN_PRICE_PRECISION = 6  # KuCoin uses 6 decimal places for MPC

TRADING_PAIR = "MPC-USDT"

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
    """Enhanced logging with optional level"""
    ts = datetime.now().strftime('%H:%M:%S.%f')[:-3]
    line = f"[{ts}] [{level}] {msg}"
    print(line)
    with open(LOG_FILE, 'a') as f:
        f.write(line + '\n')

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
        resp_m = requests.get('https://api.mexc.com/api/v3/depth?symbol=MPCUSDT&limit=10', timeout=5)
        m_depth = resp_m.json()
        
        # KuCoin Level2 API - get top 20
        resp_k = requests.get('https://api.kucoin.com/api/v1/market/orderbook/level2_20?symbol=MPC-USDT', timeout=5)
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
        resp_k = requests.get('https://api.kucoin.com/api/v1/market/orderbook/level1?symbol=MPC-USDT', timeout=5)
        k_data = resp_k.json()['data']
        
        # MEXC Level1 from depth (not ticker!)
        resp_m = requests.get('https://api.mexc.com/api/v3/depth?symbol=MPCUSDT&limit=1', timeout=5)
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
    """Buy MPC on KuCoin at market price"""
    ts = str(int(time.time() * 1000))
    body = json_lib.dumps({"clientOid": ts, "symbol": "MPC-USDT", "side": "buy", "type": "market", "size": str(qty)})
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
    """Sell MPC on KuCoin at limit price"""
    ts = str(int(time.time() * 1000))
    body = json_lib.dumps({"clientOid": f"{ts}_sell", "symbol": "MPC-USDT", "side": "sell", "type": "limit", "size": str(qty), "price": f"{price:.6f}"})
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
    """Buy MPC on MEXC at market price"""
    ts = str(int(time.time() * 1000))
    params = f'symbol=MPCUSDT&side=BUY&type=MARKET&quantity={qty}&timestamp={ts}'
    sig = hmac.new(MEXC_SECRET.encode('utf-8'), params.encode('utf-8'), hashlib.sha256).hexdigest()
    
    url = f'https://api.mexc.com/api/v3/order?{params}&signature={sig}'
    headers = {'X-MEXC-APIKEY': MEXC_KEY}
    
    resp = requests.post(url, headers=headers, timeout=10)
    return resp.json()

def execute_limit_sell_mexc(qty, price):
    """Sell MPC on MEXC at limit price"""
    ts = str(int(time.time() * 1000))
    params = f'symbol=MPCUSDT&side=SELL&type=LIMIT&quantity={qty}&price={price:.6f}&timestamp={ts}'
    sig = hmac.new(MEXC_SECRET.encode('utf-8'), params.encode('utf-8'), hashlib.sha256).hexdigest()
    
    url = f'https://api.mexc.com/api/v3/order?{params}&signature={sig}'
    headers = {'X-MEXC-APIKEY': MEXC_KEY}
    
    resp = requests.post(url, headers=headers, timeout=10)
    return resp.json()

def execute_trade_M_to_K(qty, buy_price, sell_price):
    """M -> K: Buy MEXC (market), Sell KuCoin (limit)"""
    log(f"=== EXECUTING M->K TRADE ===")
    log(f"Buy MEXC: {qty} MPC @ ${buy_price:.6f}")
    log(f"Sell KuCoin: {qty} MPC @ ${sell_price:.6f}")
    
    # Capture internal timestamp
    internal_ts = datetime.now().isoformat()
    
    # Step 1: Market Buy on MEXC
    log("Step 1: MEXC Market BUY...")
    result1 = execute_market_buy_mexc(qty)
    
    ex1_data = None
    if result1.get('code') is None or 'orderId' in result1:
        order_id1 = result1.get('orderId', 'unknown')
        log(f"✅ MEXC Order placed: {order_id1}")
        
        # Harmonize MEXC response
        ex1_data = harmonize_mexc_order(result1, "buy", "market", TRADING_PAIR)
        log(f"   Harmonized: qty_ordered={ex1_data['qty_ordered']}, qty_filled={ex1_data['qty_filled']}, price_avg={ex1_data['price_avg']:.6f}")
    else:
        log(f"❌ MEXC Error: {result1}")
        return False, None
    
    # Small delay
    time.sleep(0.5)
    
    # Step 2: Limit Sell on KuCoin
    log("Step 2: KuCoin Limit SELL...")
    result2 = execute_limit_sell_kucoin(qty, sell_price)
    
    ex2_data = None
    if result2.get('code') == '200000':
        order_id2 = result2['data'].get('orderId', 'unknown')
        log(f"✅ KuCoin Order placed: {order_id2}")
        
        # Harmonize KuCoin response
        ex2_data = harmonize_kucoin_order(result2.get('data', {}), "sell", "limit", TRADING_PAIR)
        log(f"   Harmonized: qty_ordered={ex2_data['qty_ordered']}, qty_filled={ex2_data['qty_filled']}, price_avg={ex2_data['price_avg']:.6f}")
    else:
        log(f"❌ KuCoin Error: {result2}")
        # Log trade even with partial failure
        ex2_data = {"exchange": "KUCOIN", "order_id": "FAILED", "type": "limit", "side": "sell",
                    "qty_ordered": qty, "qty_filled": 0, "price_avg": 0, "value_usdt": 0,
                    "fees": 0, "create_ts": 0, "status": "FAILED", "raw_response": result2}
    
    # Log trade with harmonized data
    trade_id = log_trade(
        pair=TRADING_PAIR,
        internal_ts=internal_ts,
        direction="M->K",
        ex1_data=ex1_data,
        ex2_data=ex2_data,
        limit_watch_status="WATCHING"
    )
    log(f"📝 Trade logged: {trade_id}")
    
    # Calculate expected profit
    cost = qty * buy_price
    revenue = qty * sell_price
    gross_profit = revenue - cost
    fee_taker = cost * 0.001
    fee_maker = revenue * 0.001
    net_profit = gross_profit - fee_taker - fee_maker
    mpc_gain = net_profit / sell_price if sell_price > 0 else 0
    
    log(f"=== TRADE LOGGED (pending limit fill) ===")
    log(f"Cost: ${cost:.4f} | Revenue: ${revenue:.4f}")
    log(f"Gross Profit: ${gross_profit:.4f} | Fees: ${fee_taker + fee_maker:.4f}")
    log(f"Expected Net Profit: ${net_profit:.4f} | MPC Gain: {mpc_gain:.4f}")
    
    return True, trade_id

def execute_trade_K_to_M(qty, buy_price, sell_price):
    """K -> M: Buy KuCoin (market), Sell MEXC (limit)"""
    log(f"=== EXECUTING K->M TRADE ===")
    log(f"Buy KuCoin: {qty} MPC @ ${buy_price:.6f}")
    log(f"Sell MEXC: {qty} MPC @ ${sell_price:.6f}")
    
    # Capture internal timestamp
    internal_ts = datetime.now().isoformat()
    
    # Step 1: Market Buy on KuCoin
    log("Step 1: KuCoin Market BUY...")
    result1 = execute_market_buy_kucoin(qty)
    
    ex1_data = None
    if result1.get('code') == '200000':
        order_id1 = result1['data'].get('orderId', 'unknown')
        log(f"✅ KuCoin Order placed: {order_id1}")
        
        # Harmonize KuCoin response
        ex1_data = harmonize_kucoin_order(result1['data'], "buy", "market", TRADING_PAIR)
        log(f"   Harmonized: qty_ordered={ex1_data['qty_ordered']}, qty_filled={ex1_data['qty_filled']}, price_avg={ex1_data['price_avg']:.6f}")
    else:
        log(f"❌ KuCoin Error: {result1}")
        return False, None
    
    # Small delay
    time.sleep(0.5)
    
    # Step 2: Limit Sell on MEXC
    log("Step 2: MEXC Limit SELL...")
    result2 = execute_limit_sell_mexc(qty, sell_price)
    
    ex2_data = None
    if result2.get('code') is None or 'orderId' in result2:
        order_id2 = result2.get('orderId', 'unknown')
        log(f"✅ MEXC Order placed: {order_id2}")
        
        # Harmonize MEXC response
        ex2_data = harmonize_mexc_order(result2, "sell", "limit", TRADING_PAIR)
        log(f"   Harmonized: qty_ordered={ex2_data['qty_ordered']}, qty_filled={ex2_data['qty_filled']}, price_avg={ex2_data['price_avg']:.6f}")
    else:
        log(f"❌ MEXC Error: {result2}")
        # Log trade even with partial failure
        ex2_data = {"exchange": "MEXC", "order_id": "FAILED", "type": "limit", "side": "sell",
                    "qty_ordered": qty, "qty_filled": 0, "price_avg": 0, "value_usdt": 0,
                    "fees": 0, "create_ts": 0, "status": "FAILED", "raw_response": result2}
    
    # Log trade with harmonized data
    trade_id = log_trade(
        pair=TRADING_PAIR,
        internal_ts=internal_ts,
        direction="K->M",
        ex1_data=ex1_data,
        ex2_data=ex2_data,
        limit_watch_status="WATCHING"
    )
    log(f"📝 Trade logged: {trade_id}")
    
    # Calculate expected profit
    cost = qty * buy_price
    revenue = qty * sell_price
    gross_profit = revenue - cost
    fee_taker = cost * 0.001
    fee_maker = revenue * 0.001
    net_profit = gross_profit - fee_taker - fee_maker
    mpc_gain = net_profit / sell_price if sell_price > 0 else 0
    
    log(f"=== TRADE LOGGED (pending limit fill) ===")
    log(f"Cost: ${cost:.4f} | Revenue: ${revenue:.4f}")
    log(f"Gross Profit: ${gross_profit:.4f} | Fees: ${fee_taker + fee_maker:.4f}")
    log(f"Expected Net Profit: ${net_profit:.4f} | MPC Gain: {mpc_gain:.4f}")
    
    return True, trade_id


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
                params = f'symbol=MPCUSDT&orderId={ex2_order_id}&timestamp={ts}'
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
    log("Strategy: Coin-Gewinn (MPC akkumulieren)")
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
        kucoin_min_qty = KUCOIN_MIN_MPC
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
                        if best_trade is None or spread_pct > best_trade['pct']:
                            best_trade = {
                                'dir': 'M→K',
                                'buy': m_ask['price'],
                                'sell': k_bid['price'],
                                'pct': spread_pct,
                                'vol': min(cum_vol_mexc, k_bid['qty'])
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
        if int(time.time()) % 30 == 0:
            if ob_data:
                total_mexc = sum(x['qty'] for x in ob_data['mexc_asks'][:5])
                total_kucoin = sum(x['qty'] for x in ob_data['kucoin_bids'][:5])
                strategy = get_trading_strategy(TRADING_PAIR)
                log(f"Sweep: {strategy.upper()} strategy | MEXC top5={total_mexc:.0f} MPC, KuCoin top5={total_kucoin:.0f} MPC, min={min_trade_qty}")
                if best_trade:
                    log(f"  Best: {best_trade['dir']} @ {best_trade['pct']:.3f}% | Vol={best_trade['vol']:.0f} MPC | profit_usdt=${best_trade['profit_usdt']:.4f} | profit_mpc={best_trade['profit_mpc']:.4f}")
                else:
                    log(f"  No tradeable spread found (spread below thresholds or insufficient volume)")
        
        # Log volume check every 15s
        if int(time.time()) % 15 == 0 and ob_data:
            total_mexc_vol = sum(x['qty'] for x in ob_data['mexc_asks'][:5])
            total_kucoin_vol = sum(x['qty'] for x in ob_data['kucoin_bids'][:5])
            log(f"Orderbook: MEXC top5={total_mexc_vol:.0f} MPC, KuCoin top5={total_kucoin_vol:.0f} MPC, min_needed={min_trade_qty}")
            log(f"Best trade: {best_trade['dir']} @ {best_trade['pct']:.3f}% | Vol={best_trade['vol']:.0f} MPC" if best_trade else "No tradeable spread")
        
        if not ob_data:
            # Fallback when orderbook fetch fails
            vol_for_mexc = round((MEXC_MIN_USDT + 1) / m['ask']) if m['ask'] > 0 else 86
            vol_for_kucoin = max(KUCOIN_MIN_MPC, vol_for_mexc)

        
        # Log every 30 seconds
        if int(time.time()) % 30 == 0:
            log(f"Prices: K={fmt_price(k['bid'],'kucoin')}/{fmt_price(k['ask'],'kucoin')} | M={fmt_price(m['bid'],'mexc')}/{fmt_price(m['ask'],'mexc')}")
            log(f"  M->K spread: {spread_pct_mk:.2f}% | K->M spread: {spread_pct_km:.2f}%")
        
        # Check limit order fills every 10 seconds
        if time.time() - last_limit_check > 10:
            check_limit_order_fills()
            last_limit_check = time.time()
        
        # Determine which spread direction is profitable
        profitable_spread = max(spread_pct_km, spread_pct_mk)
        direction = "K→M" if spread_pct_km >= spread_pct_mk else "M→K"
        
        # Log decision every 15 seconds
        if int(time.time()) % 15 == 0:
            # Settings already read at loop start
            log_decision("STATUS_CHECK",
                state=state,
                pair_enabled=str(pair_enabled),
                strategy=current_strategy,
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
            if int(time.time()) % 30 == 0:
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
                    vol_for_mexc = best_trade['vol']
                    vol_for_kucoin = best_trade['vol']
                    log(f"🚀 Executing: {best_trade['dir']} @ {best_trade['pct']:.3f}% | Vol={best_trade['vol']:.0f} MPC")
                    if best_trade['dir'] == 'K→M':
                        success, trade_id = execute_trade_K_to_M(best_trade['vol'], best_trade['buy'], best_trade['sell'])
                    else:
                        success, trade_id = execute_trade_M_to_K(best_trade['vol'], best_trade['buy'], best_trade['sell'])
                elif spread_pct_km >= spread_pct_mk:
                    success, trade_id = execute_trade_K_to_M(vol_for_kucoin, k['ask'], m['bid'])
                else:
                    success, trade_id = execute_trade_M_to_K(vol_for_mexc, m['ask'], k['bid'])
                
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
                    vol_for_mexc = best_trade['vol']
                    vol_for_kucoin = best_trade['vol']
                    log(f"🚀 Executing: {best_trade['dir']} @ {best_trade['pct']:.3f}% | Vol={best_trade['vol']:.0f} MPC")
                    if best_trade['dir'] == 'K→M':
                        success, trade_id = execute_trade_K_to_M(best_trade['vol'], best_trade['buy'], best_trade['sell'])
                    else:
                        success, trade_id = execute_trade_M_to_K(best_trade['vol'], best_trade['buy'], best_trade['sell'])
                elif spread_pct_km >= spread_pct_mk:
                    success, trade_id = execute_trade_K_to_M(vol_for_kucoin, k['ask'], m['bid'])
                else:
                    success, trade_id = execute_trade_M_to_K(vol_for_mexc, m['ask'], k['bid'])
                
                last_trade_time = time.time()
                trade_in_progress = False
        
        time.sleep(1)  # Check every second

if __name__ == '__main__':
    main()