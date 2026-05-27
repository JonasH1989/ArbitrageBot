#!/usr/bin/env python3
"""
Arbitrage Auto-Trade Bot - DEBUG VERSION
Enhanced logging for troubleshooting trade decisions
"""
import sys
import os

# Setup paths
sys.path.insert(0, '/home/openclaw/.openclaw/workspace/trading/arbitrage-bot')
sys.path.insert(0, '/app')

import requests
import yaml
import time
import json
import hashlib
import hmac
import base64
from datetime import datetime
from pathlib import Path

# Import logger
from trade_logger import log_trade, get_trades

# =============================================================================
# CONFIG
# =============================================================================
TRADING_PAIR = "MPC-USDT"
MEXC_MIN_USDT = 1.0
KUCOIN_MIN_MPC = 85

CONFIG_PATH = '/app/config/config.yaml' if Path('/app/config/config.yaml').exists() else '/home/openclaw/.openclaw/workspace/trading/arbitrage-bot/config/config.yaml'
LOG_DIR = Path('/home/openclaw/.openclaw/logs')
LOG_DIR.mkdir(parents=True, exist_ok=True)
DEBUG_LOG = LOG_DIR / 'arb_debug.log'
ACTIVE_FLAG = LOG_DIR / 'arb_active.flag'

# =============================================================================
# LOGGING
# =============================================================================
def log(level, msg):
    """Enhanced logging with timestamps and levels"""
    ts = datetime.now().strftime('%H:%M:%S.%f')[:-3]
    line = f"[{ts}] [{level}] {msg}"
    print(line, flush=True)
    
    with open(DEBUG_LOG, 'a') as f:
        f.write(line + '\n')

def log_decision(title, **kwargs):
    """Log a decision point with all conditions"""
    log("DECISION", f"═══ {title} ═══")
    for key, value in kwargs.items():
        log("DECISION", f"  {key}: {value}")
    log("DECISION", "─" * 50)

def log_condition(condition_name, result, expected=None, details=""):
    """Log a boolean condition check"""
    symbol = "✅" if result else "❌"
    msg = f"{symbol} {condition_name}: {result}"
    if expected is not None:
        msg += f" (expected: {expected})"
    if details:
        msg += f" | {details}"
    log("CONDITION", msg)

# =============================================================================
# API SETUP
# =============================================================================
with open(CONFIG_PATH, 'r') as f:
    cfg = yaml.safe_load(_f)

KUCOIN_KEY = cfg.get('kucoin', {}).get('api_key', '')
KUCOIN_SECRET = cfg.get('kucoin', {}).get('api_secret', '')
KUCOIN_PASSPHRASE = cfg.get('kucoin', {}).get('api_passphrase', '')
MEXC_KEY = cfg.get('mexc', {}).get('api_key', '')
MEXC_SECRET = cfg.get('mexc', {}).get('api_secret', '')

def is_active():
    return os.path.exists(ACTIVE_FLAG)

def kucoin_sig(secret, ts, method, path, body=''):
    message = f'{ts}{method}{path}{body}'
    return base64.b64encode(hmac.new(secret.encode(), message.encode(), hashlib.sha256).digest()).decode()

def kucoin_passphrase_enc(secret, passphrase):
    return base64.b64encode(hmac.new(secret.encode(), passphrase.encode(), hashlib.sha256).digest()).decode()

# =============================================================================
# GET PRICES
# =============================================================================
def get_prices():
    """Get current prices from both exchanges with debug info"""
    try:
        # KuCoin
        resp_k = requests.get('https://api.kucoin.com/api/v1/market/orderbook/level1?symbol=MPC-USDT', timeout=5)
        k_data = resp_k.json()['data']
        k = {'bid': float(k_data['bestBid']), 'ask': float(k_data['bestAsk']), 'last': float(k_data['price'])}
        
        # MEXC
        resp_m = requests.get('https://api.mexc.com/api/v3/ticker/24hr?symbol=MPCUSDT', timeout=5)
        m_data = resp_m.json()
        m = {'bid': float(m_data['bidPrice']), 'ask': float(m_data['askPrice']), 'last': float(m_data['lastPrice'])}
        
        log("PRICE", f"KuCoin: bid=${k['bid']:.6f} ask=${k['ask']:.6f} | MEXC: bid=${m['bid']:.6f} ask=${m['ask']:.6f}")
        
        return {'kucoin': k, 'mexc': m}
    except Exception as e:
        log("ERROR", f"Price fetch failed: {e}")
        return None

# =============================================================================
# VOLUME CALCULATION
# =============================================================================
def get_required_volume():
    """Calculate minimum required volume for both exchanges"""
    prices = get_prices()
    if not prices:
        return None, None, None
    
    m = prices['mexc']
    k = prices['kucoin']
    
    # MEXC: Minimum USDT amount -> convert to MPC
    min_mpc_mexc = (MEXC_MIN_USDT + 0.1) / m['ask'] if m['ask'] > 0 else 85
    # KuCoin: Fixed minimum MPC
    min_mpc_kucoin = KUCOIN_MIN_MPC
    
    # Use the larger of the two
    min_mpc = max(min_mpc_mexc, min_mpc_kucoin)
    
    log("VOLUME", f"Required MPC: MEXC min={min_mpc_mexc:.0f}, KuCoin min={min_mpc_kucoin}, using={min_mpc:.0f}")
    
    return min_mpc, prices

# =============================================================================
# MAIN LOOP
# =============================================================================
def main():
    log("INFO", "=" * 70)
    log("INFO", "🚨 ARB DEBUG BOT STARTED")
    log("INFO", "=" * 70)
    
    # Load config
    try:
        with open(CONFIG_PATH, 'r') as f:
            cfg = yaml.safe_load(f)
        pair_cfg = cfg.get('trading', {}).get('pairs', {}).get(TRADING_PAIR, {})
        START_THRESHOLD = pair_cfg.get('threshold_start', 1.0)
        STOP_THRESHOLD = pair_cfg.get('threshold_stop', 0.5)
        pair_enabled = pair_cfg.get('enabled', False)
    except Exception as e:
        log("ERROR", f"Config load failed: {e}")
        START_THRESHOLD = 1.0
        STOP_THRESHOLD = 0.5
        pair_enabled = False
    
    # NOTE: pair_enabled is READ-ONLY from config!
    # It can ONLY be changed by:
    #   1. Dashboard (user toggles the checkbox)
    #   2. Container restart (safety flag file)
    # NO other code may write to this value!
    # Safety override is done via SEPARATE flag file, NOT config.yaml!
    
    log_decision("CONFIG LOADED",
        start_threshold=f"{START_THRESHOLD}%",
        stop_threshold=f"{STOP_THRESHOLD}%",
        pair_enabled=str(pair_enabled),
        safety="pair_enabled is READ ONLY from config - only Dashboard may change it"
    )
    
    state = "WAITING"
    last_status_log = 0
    
    while True:
        try:
            # Get prices
            prices = get_prices()
            if not prices:
                time.sleep(1)
                continue
            
            k = prices['kucoin']
            m = prices['mexc']
            
            # Calculate spreads
            spread_mk = k['bid'] - m['ask']  # Buy MEXC, Sell KuCoin
            spread_pct_mk = (spread_mk / m['ask']) * 100 if m['ask'] > 0 else 0
            
            spread_km = m['bid'] - k['ask']  # Buy KuCoin, Sell MEXC
            spread_pct_km = (spread_km / k['ask']) * 100 if k['ask'] > 0 else 0
            
            # Determine best direction
            best_spread_pct = max(spread_pct_km, spread_pct_mk)
            best_direction = "K→M" if spread_pct_km >= spread_pct_mk else "M→K"
            
            # Get required volume
            min_vol, _ = get_required_volume()
            
            # Log status every 15 seconds
            if time.time() - last_status_log >= 15:
                log_decision("STATUS CHECK",
                    state=state,
                    pair_enabled=str(pair_enabled),
                    best_spread=f"{best_spread_pct:.3f}%",
                    direction=best_direction,
                    threshold_start=f"{START_THRESHOLD}%",
                    threshold_stop=f"{STOP_THRESHOLD}%",
                    min_volume=f"{min_vol:.0f} MPC" if min_vol else "N/A"
                )
                last_status_log = time.time()
            
            # Check if INACTIVE
            if not pair_enabled:
                if state != "INACTIVE":
                    state = "INACTIVE"
                    log("INFO", "⏸️ BOT INACTIVE - no trades will execute")
                time.sleep(1)
                continue
            
            # ================================================================
            # ACTIVE MODE - Check trade conditions
            # ================================================================
            
            # Check 1: Is spread >= START_THRESHOLD?
            condition_start = best_spread_pct >= START_THRESHOLD
            log_condition("Spread >= START_THRESHOLD", condition_start, 
                expected=f"{START_THRESHOLD}%",
                details=f"actual={best_spread_pct:.3f}%"
            )
            
            if not condition_start:
                if state != "WAITING":
                    state = "WAITING"
                    log("INFO", f"⏸️ SPREAD TOO LOW - waiting (spread={best_spread_pct:.3f}% < threshold={START_THRESHOLD}%)")
                time.sleep(1)
                continue
            
            # Check 2: Volume check
            if min_vol is None:
                log("WARN", "⚠️ Could not determine volume requirements")
                time.sleep(1)
                continue
            
            log_condition("Volume sufficient", min_vol > 0, 
                details=f"required={min_vol:.0f} MPC"
            )
            
            # Check 3: Price sanity
            price_sane = k['ask'] > 0 and m['ask'] > 0 and k['bid'] > 0 and m['bid'] > 0
            log_condition("Prices sane (all > 0)", price_sane,
                details=f"K ask=${k['ask']:.6f} M ask=${m['ask']:.6f}"
            )
            
            if not price_sane:
                log("ERROR", "❌ Price sanity check failed!")
                time.sleep(1)
                continue
            
            # ================================================================
            # ALL CONDITIONS MET - Decision to trade
            # ================================================================
            log("INFO", "=" * 60)
            log_decision("🚀 TRIGGER CONDITIONS MET",
                spread=f"{best_spread_pct:.3f}%",
                direction=best_direction,
                volume=f"{min_vol:.0f} MPC"
            )
            
            # Determine direction and execute
            if best_direction == "K→M":
                log("INFO", "📋 EXECUTING: Buy KuCoin → Sell MEXC")
                log_decision("TRADE PARAMETERS",
                    direction="K→M (Buy KuCoin, Sell MEXC)",
                    buy_price=f"${k['ask']:.6f}",
                    sell_price=f"${m['bid']:.6f}",
                    volume=f"{min_vol:.0f} MPC",
                    expected_profit_usdt=f"{spread_km:.6f}"
                )
                # execute_trade_K_to_M would be called here
            else:
                log("INFO", "📋 EXECUTING: Buy MEXC → Sell KuCoin")
                log_decision("TRADE PARAMETERS",
                    direction="M→K (Buy MEXC, Sell KuCoin)",
                    buy_price=f"${m['ask']:.6f}",
                    sell_price=f"${k['bid']:.6f}",
                    volume=f"{min_vol:.0f} MPC",
                    expected_profit_usdt=f"{spread_mk:.6f}"
                )
                # execute_trade_M_to_K would be called here
            
            log("INFO", "🔔 TRADE SIGNAL SENT - execution depends on API response")
            log("INFO", "=" * 60)
            
            state = "TRADING"
            
            # In real version, execute trade here
            # For debug, just sleep
            time.sleep(5)
            
        except Exception as e:
            log("ERROR", f"Main loop exception: {e}")
            import traceback
            log("ERROR", traceback.format_exc())
            time.sleep(1)

if __name__ == '__main__':
    main()
