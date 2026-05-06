#!/usr/bin/env python3
"""
Arbitrage Bot Dashboard - Multi-Pair + Original Detail View
"""

import streamlit as st
import streamlit.components.v1 as components
import requests
import yaml
from datetime import datetime
from pathlib import Path
import os
import pandas as pd
import io
from trade_logger import *
import sys
from settings_sync import get_setting, set_setting, get_pair_settings, set_pair_settings, get_alert_settings, set_alert_settings, get_api_keys, set_api_keys, get_all_pairs, add_pair, remove_pair, get_log_level, set_log_level

import base64

# Sound files
SOUND_FILES = {
    'bis3': '/app/static/bis3prozent.mp3',
    'bis10': '/app/static/bis10prozent.mp3',
    'ab10': '/app/static/ab10prozent.mp3',
    'kaching': '/app/static/kaching.mp3'
}

def play_sound(sound_key, volume=0.5):
    """Play a sound file with given volume (0-1)"""
    sound_file = SOUND_FILES.get(sound_key)
    if not sound_file:
        return
    try:
        with open(sound_file, 'rb') as f:
            audio_bytes = f.read()
        b64 = base64.b64encode(audio_bytes).decode()
        vol_int = int(volume * 100)
        audio_html = '<audio id="alert_sound" autoplay="autoplay"><source src="data:audio/mp3;base64,' + b64 + '" type="audio/mpeg"></audio><script>document.getElementById("alert_sound").volume=' + str(vol_int) + '/100;</script>'
        st.iframe(audio_html, height=1)
    except Exception as e:
        pass

# Exchange price precision
MEXC_PRICE_PRECISION = 5
KUCOIN_PRICE_PRECISION = 6

# Dashboard logging to same file as bot



def fmt_price(price, exchange):
    """Format price with exchange-specific precision"""
    if exchange == 'mexc':
        return f"{price:.{MEXC_PRICE_PRECISION}f}"
    return f"{price:.{KUCOIN_PRICE_PRECISION}f}"
# Logo paths


KUCoin_LOGO = "/app/static/kucoin.jpg"
MEXC_LOGO = "/app/static/mexc.jpg"
st.set_page_config(page_title="Arbitrage Bot", page_icon="📊", layout="wide")

CONFIG_FILE = 'config/config.yaml'

def load_config():
    """Load config using settings_sync for real-time sync"""
    config = {
        'kucoin': get_api_keys('kucoin'),
        'mexc': get_api_keys('mexc'),
        'alert': get_alert_settings(),
        'trading': {'pairs': {}, 'thresholds': {'start': 0.2, 'stop': 0.1}}
    }
    for pair in get_all_pairs():
        config['trading']['pairs'][pair] = get_pair_settings(pair)
    return config

def save_config(config):
    """Save config - now a no-op since we save immediately via settings_sync"""
    pass  # All saves now happen immediately via set_setting calls

# ============================================================================
# API Functions
# ============================================================================

def get_kucoin_orderbook(pair: str):
    try:
        resp = requests.get(f"https://api.kucoin.com/api/v1/market/orderbook/level1?symbol={pair}", timeout=5)
        if resp.status_code == 200:
            data = resp.json()
            if data.get('code') == '200000':
                d = data.get('data', {})
                return {
                    'bid': float(d.get('bestBid', 0) or 0),
                    'bid_size': float(d.get('bestBidSize', 0) or 0),
                    'ask': float(d.get('bestAsk', 0) or 0),
                    'ask_size': float(d.get('bestAskSize', 0) or 0),
                    'ok': True
                }
    except: pass
    return {'ok': False}

def get_mexc_orderbook(pair: str):
    try:
        symbol = pair.replace('-', '')
        resp = requests.get(f"https://api.mexc.com/api/v3/ticker/bookTicker?symbol={symbol}", timeout=5)
        if resp.status_code == 200:
            data = resp.json()
            bid = float(data.get('bidPrice', 0) or 0)
            ask = float(data.get('askPrice', 0) or 0)
            return {
                'bid': bid,
                'bid_size': float(data.get('bidQty', 0) or 0),
                'ask': ask,
                'ask_size': float(data.get('askQty', 0) or 0),
                'ok': True
            }
    except: pass
    return {'ok': False}

def get_kucoin_balances(api_key: str, api_secret: str, passphrase: str):
    """Get KuCoin account balances"""
    try:
        import hashlib
        import hmac
        import base64
        import time
        
        now = int(time.time() * 1000)
        method = 'GET'
        path = '/api/v1/accounts'
        body = ''
        
        # Signature
        message = f'{now}{method}{path}{body}'
        mac = hmac.new(api_secret.encode(), message.encode(), hashlib.sha256)
        signature = base64.b64encode(mac.digest()).decode()
        
        headers = {
            'KC-API-KEY': api_key,
            'KC-API-SIGN': signature,
            'KC-API-TIMESTAMP': str(now),
            'KC-API-PASSPHRASE': passphrase,  # Version 1: plain passphrase
            'KC-API-KEY-VERSION': '1'
        }
        
        resp = requests.get(f'https://api.kucoin.com{path}', headers=headers, timeout=10)
        if resp.status_code == 200:
            data = resp.json()
            if data.get('code') == '200000':
                balances = {}
                for acc in data.get('data', []):
                    currency = acc.get('currency', '')
                    available = float(acc.get('available', 0) or 0)
                    total = float(acc.get('balance', 0) or 0)
                    if currency and total > 0:
                        if currency not in balances:
                            balances[currency] = {'available': available, 'total': total}
                        else:
                            # Sum across multiple accounts (e.g., trade + main + margin)
                            balances[currency]['available'] += available
                            balances[currency]['total'] += total
                return {'ok': True, 'balances': balances}
            else:
                return {'ok': False, 'balances': {}, 'error': data.get('msg', 'Unknown error')}
        else:
            return {'ok': False, 'balances': {}, 'error': f'HTTP {resp.status_code}'}
    except Exception as e:
        return {'ok': False, 'balances': {}, 'error': str(e)}

def get_kucoin_trades(api_key: str, api_secret: str, passphrase: str, symbol: str = 'MPC-USDT', limit: int = 10):
    """Get KuCoin trade/fill history"""
    try:
        import hashlib
        import hmac
        import base64
        import time
        
        now = int(time.time() * 1000)
        method = 'GET'
        path = f'/api/v1/fills?symbol={symbol}&limit={limit}'
        body = ''
        
        # Signature (same as balances)
        message = f'{now}{method}{path}{body}'
        mac = hmac.new(api_secret.encode(), message.encode(), hashlib.sha256)
        signature = base64.b64encode(mac.digest()).decode()
        
        headers = {
            'KC-API-KEY': api_key,
            'KC-API-SIGN': signature,
            'KC-API-TIMESTAMP': str(now),
            'KC-API-PASSPHRASE': passphrase,
            'KC-API-KEY-VERSION': '1'
        }
        
        resp = requests.get(f'https://api.kucoin.com{path}', headers=headers, timeout=10)
        if resp.status_code == 200:
            data = resp.json()
            if data.get('code') == '200000':
                items = data.get('data', {}).get('items', [])
                trades = []
                for item in items:
                    trades.append({
                        'symbol': item.get('symbol'),
                        'side': item.get('side'),
                        'price': float(item.get('price', 0)),
                        'size': float(item.get('size', 0)),
                        'funds': float(item.get('funds', 0)),
                        'fee': float(item.get('fee', 0)),
                        'fee_currency': item.get('feeCurrency'),
                        'created_at': item.get('createdAt'),  # timestamp in ms
                        'trade_id': item.get('tradeId')
                    })
                return {'ok': True, 'trades': trades}
            else:
                return {'ok': False, 'trades': [], 'error': data.get('msg', 'Unknown error')}
        else:
            return {'ok': False, 'trades': [], 'error': f'HTTP {resp.status_code}'}
    except Exception as e:
        return {'ok': False, 'trades': [], 'error': str(e)}

def get_mexc_balances(api_key: str, api_secret: str):
    """Get MEXC account balances"""
    try:
        import hashlib
        import hmac
        import time
        
        ts = int(time.time() * 1000)
        path = '/api/v3/account'
        
        # MEXC signature: HMAC_SHA256(secretKey, "timestamp=<ts>")
        signature = hmac.new(api_secret.encode(), f'timestamp={ts}'.encode(), hashlib.sha256).hexdigest()
        
        headers = {
            'ApiKey': api_key
        }
        
        resp = requests.get(f'https://api.mexc.com{path}?timestamp={ts}&signature={signature}', headers=headers, timeout=10)
        if resp.status_code == 200:
            data = resp.json()
            balances = {}
            for bal in data.get('balances', []):
                sym = bal.get('asset', '')
                free = float(bal.get('free', 0) or 0)
                locked = float(bal.get('locked', 0) or 0)
                total = free + locked
                if total > 0:
                    balances[sym] = {'available': free, 'total': total}
            return {'ok': True, 'balances': balances}
        else:
            return {'ok': False, 'balances': {}, 'error': f'HTTP {resp.status_code}'}
    except Exception as e:
        return {'ok': False, 'balances': {}, 'error': str(e)}

def get_mexc_trades(api_key: str, api_secret: str, symbol: str = 'MPCUSDT', limit: int = 10):
    """Get MEXC trade/fill history using myTrades endpoint"""
    try:
        import hashlib
        import hmac
        import time
        
        ts = int(time.time() * 1000)
        path = '/api/v3/myTrades'
        query = f'symbol={symbol}&limit={limit}&timestamp={ts}'
        
        signature = hmac.new(api_secret.encode(), query.encode(), hashlib.sha256).hexdigest()
        
        headers = {'X-MEXC-APIKEY': api_key}
        
        resp = requests.get(f'https://api.mexc.com{path}?{query}&signature={signature}', headers=headers, timeout=10)
        if resp.status_code == 200:
            trades = resp.json()
            result = []
            for t in trades:
                result.append({
                    'symbol': t.get('symbol'),
                    'side': 'buy' if t.get('isBuyer') else 'sell',
                    'price': float(t.get('price', 0)),
                    'qty': float(t.get('qty', 0)),
                    'quote': float(t.get('quoteQty', 0)),
                    'fee': float(t.get('commission', 0)),
                    'fee_asset': t.get('commissionAsset'),
                    'time': t.get('time'),
                    'trade_id': t.get('id'),
                    'order_id': t.get('orderId')
                })
            return {'ok': True, 'trades': result}
        else:
            return {'ok': False, 'trades': [], 'error': f'HTTP {resp.status_code}: {resp.text}'}
    except Exception as e:
        return {'ok': False, 'trades': [], 'error': str(e)}

def get_kucoin_fees(api_key: str, api_secret: str, passphrase: str, symbol: str = 'MPC-USDT'):
    """Get KuCoin actual fee rates for a symbol"""
    try:
        import hashlib
        import hmac
        import base64
        import time
        
        now = int(time.time() * 1000)
        method = 'GET'
        path = f'/api/v1/base-fee?symbol={symbol}'
        body = ''
        
        message = f'{now}{method}{path}{body}'
        mac = hmac.new(api_secret.encode(), message.encode(), hashlib.sha256)
        signature = base64.b64encode(mac.digest()).decode()
        
        headers = {
            'KC-API-KEY': api_key,
            'KC-API-SIGN': signature,
            'KC-API-TIMESTAMP': str(now),
            'KC-API-PASSPHRASE': passphrase,
            'KC-API-KEY-VERSION': '1'
        }
        
        resp = requests.get(f'https://api.kucoin.com{path}', headers=headers, timeout=10)
        if resp.status_code == 200:
            data = resp.json()
            if data.get('code') == '200000':
                d = data.get('data', {})
                return {
                    'ok': True,
                    'maker_fee_rate': float(d.get('makerFeeRate', 0)),
                    'taker_fee_rate': float(d.get('takerFeeRate', 0))
                }
        return {'ok': False, 'maker_fee_rate': 0.001, 'taker_fee_rate': 0.001}
    except:
        return {'ok': False, 'maker_fee_rate': 0.001, 'taker_fee_rate': 0.001}

def get_kucoin_token_fees(api_key: str, api_secret: str, passphrase: str):
    """Get KuCoin actual token fees (maker/taker for all symbols)"""
    try:
        import hashlib
        import hmac
        import base64
        import time
        
        now = int(time.time() * 1000)
        method = 'GET'
        path = '/api/v1/trade-fees'
        body = ''
        
        message = f'{now}{method}{path}{body}'
        mac = hmac.new(api_secret.encode(), message.encode(), hashlib.sha256)
        signature = base64.b64encode(mac.digest()).decode()
        
        headers = {
            'KC-API-KEY': api_key,
            'KC-API-SIGN': signature,
            'KC-API-TIMESTAMP': str(now),
            'KC-API-PASSPHRASE': passphrase,
            'KC-API-KEY-VERSION': '1'
        }
        
        resp = requests.get(f'https://api.kucoin.com{path}', headers=headers, timeout=10)
        if resp.status_code == 200:
            data = resp.json()
            if data.get('code') == '200000':
                fees = {}
                for item in data.get('data', []):
                    sym = item.get('symbol', '')
                    fees[sym] = {
                        'maker_fee_rate': float(item.get('makerFeeRate', 0)),
                        'taker_fee_rate': float(item.get('takerFeeRate', 0))
                    }
                return {'ok': True, 'fees': fees}
        return {'ok': False, 'fees': {}}
    except:
        return {'ok': False, 'fees': {}}

def get_mexc_fees(api_key: str, api_secret: str, symbol: str = 'MPCUSDT'):
    """Get MEXC actual fee rates via API"""
    try:
        import hashlib
        import hmac
        import time
        
        ts = int(time.time() * 1000)
        path = f'/api/v3/tradeFee'
        query = f'symbol={symbol}&timestamp={ts}'
        
        signature = hmac.new(api_secret.encode(), query.encode(), hashlib.sha256).hexdigest()
        
        headers = {'X-MEXC-APIKEY': api_key}
        
        resp = requests.get(f'https://api.mexc.com{path}?{query}&signature={signature}', headers=headers, timeout=10)
        if resp.status_code == 200:
            data = resp.json()
            if data.get('code') == 0:
                d = data.get('data', {})
                return {
                    'ok': True,
                    'maker_fee_rate': float(d.get('makerCommission', 0.002)),
                    'taker_fee_rate': float(d.get('takerCommission', 0.002))
                }
        return {'ok': False, 'maker_fee_rate': 0.002, 'taker_fee_rate': 0.002}
    except:
        return {'ok': False, 'maker_fee_rate': 0.002, 'taker_fee_rate': 0.002}

# ============================================================================
# Session State
# ============================================================================

if 'selected_pair' not in st.session_state:
    st.session_state.selected_pair = None

if 'price_history' not in st.session_state:
    st.session_state.price_history = {}

if 'max_points' not in st.session_state:
    st.session_state.max_points = 60


# ============================================================================
# Main App
# ============================================================================

st.title("📊 Arbitrage Bot")

config = load_config()
pairs_config = config.get('trading', {}).get('pairs', {})
# Handle both list and dict format for backwards compatibility
if isinstance(pairs_config, list):
    # Convert list to dict format
    pairs_config = {p: {'enabled': True, 'strategy': 'usdt', 'threshold_start': 1.0, 'threshold_stop': 0.5, 'alert_enabled': True} for p in pairs_config}

# ENFORCE INAKTIV on redeploy - check flag, set config to match
if os.path.exists('/home/openclaw/.openclaw/logs/arb_active.flag'):
    config['trading']['pairs'] = pairs_config
else:
    # Ensure config is INAKTIV on redeploy
    for p in pairs_config:
        pairs_config[p]['enabled'] = False
    config['trading']['pairs'] = pairs_config
    save_config(config)

thresholds = config['trading'].get('thresholds', {'start': 0.2, 'stop': 0.1})

# ============================================================================
# SIDEBAR
# ============================================================================

with st.sidebar:
    st.header("⚙️ Einstellungen")
    
    # Exchange Settings FIRST
    st.markdown("### 🔗 Exchanges")
    
    with st.expander("KuCoin", expanded=True):
        st.image("/app/static/kucoin_icon.png", width=32)
        kucoin_key_val = config.get('kucoin', {}).get('api_key', '')
        kucoin_secret_val = config.get('kucoin', {}).get('api_secret', '')
        kucoin_pass_val = config.get('kucoin', {}).get('api_passphrase', '')
        kucoin_key = st.text_input("API Key", value=kucoin_key_val, type="password", key="kucoin_key_field")
        kucoin_secret = st.text_input("API Secret", value=kucoin_secret_val, type="password", key="kucoin_secret_field")
        kucoin_pass = st.text_input("Passphrase", value=kucoin_pass_val, type="password", key="kucoin_pass_field")
        if st.button("💾 KuCoin"):
            set_api_keys('kucoin', api_key=kucoin_key, api_secret=kucoin_secret, api_passphrase=kucoin_pass)
            st.success("Gespeichert!")
            st.rerun()
    
    with st.expander("MEXC", expanded=True):
        st.image("/app/static/mexc_icon.png", width=32)
        mexc_key_val = config.get('mexc', {}).get('api_key', '')
        mexc_secret_val = config.get('mexc', {}).get('api_secret', '')
        mexc_key = st.text_input("API Key", value=mexc_key_val, type="password", key="mexc_key_field")
        mexc_secret = st.text_input("API Secret", value=mexc_secret_val, type="password", key="mexc_secret_field")
        if st.button("💾 MEXC"):
            set_api_keys('mexc', api_key=mexc_key, api_secret=mexc_secret)
            st.success("Gespeichert!")
            st.rerun()
    
    st.divider()
    
    # Log Level
    st.markdown("### 🔍 Log Level")
    current_log_level = get_log_level()
    log_level_options = {1: "Level 1 - Basic", 2: "Level 2 - Debug"}
    log_level_labels = list(log_level_options.values())
    selected_label = st.selectbox("Log Level", log_level_labels, index=current_log_level - 1, key="log_level_select")
    new_log_level = 1 if selected_label == log_level_labels[0] else 2
    if new_log_level != current_log_level:
        set_log_level(new_log_level)
        # Log immediately to arb_live_log.txt (no 30s delay)
        try:
            from pathlib import Path
            from datetime import datetime
            log_dir = Path('/app/logs') if Path('/app/logs').exists() else Path('/home/openclaw/.openclaw/logs')
            log_file = log_dir / 'arb_live_log.txt'
            ts = datetime.now().strftime('%H:%M:%S')
            level_str = "Level 1 - Basic" if new_log_level == 1 else "Level 2 - Debug"
            entry = f"[{ts}] [INFO    ] ⚙️ CONFIG: Log Level geaendert auf {level_str}\n"
            with open(log_file, 'a') as f:
                f.write(entry)
        except:
            pass
    
    st.caption("Level 2 erzeugt deutlich mehr Logs (API-Details, Orderbook, etc.)")
    
    st.divider()
    
    # Alert
    st.markdown("### 🔔 Alert")
    # Load current settings via settings_sync
    alert_settings = get_alert_settings()
    
    alert_enabled = st.checkbox("Akustischer Alert", value=alert_settings.get('enabled', True), key="alert_enabled_checkbox")
    
    # Volume - always save on slider change
    current_volume = alert_settings.get('volume', 0.3)
    
    # Use unique key for slider that changes on interaction
    new_volume = st.slider("🔊 Lautstaerke", 0.0, 1.0, current_volume, 0.1, key="volume_slider")
    
    # Force save on every interaction - check if different from file value
    if new_volume != current_volume:
        set_alert_settings(enabled=alert_enabled, volume=new_volume)
        # Don't rerun - let streamlit handle the state
        st.success(f"Lautstärke gespeichert: {int(new_volume*100)}%")
    
    # Sound playback
    vol = alert_settings.get('volume', 0.3)
    
    # Sound selector
    sound_options = {
        "💰 Bis 3%": "bis3",
        "🎯 3-10%": "bis10",
        "🚨 Ab 10%": "ab10",
        "💵 Kaching (Trade)": "kaching"
    }
    selected_sound = st.selectbox("🔊 Sound auswaehlen", 
                                   options=list(sound_options.keys()),
                                   index=0, key="sound_select")
    
    # Sound test - use fixed key but handle rerun properly
    sound_key = sound_options[selected_sound]
    
    # Improved sound test with direct st.audio
    if 'sound_test_clicked' not in st.session_state:
        st.session_state.sound_test_clicked = False
    
    col1, col2, col3 = st.columns([1, 1, 2])
    with col1:
        if st.button("▶️ Sound testen", key="sound_test_btn"):
            st.session_state.sound_test_clicked = True
    
    # Test ALL sounds button
    with col2:
        if st.button("🔊 Alle testen", key="sound_test_all_btn"):
            st.session_state.sound_test_all = True
    
    # Handle single sound test
    if st.session_state.sound_test_clicked:
        sound_file = SOUND_FILES.get(sound_key)
        if sound_file:
            try:
                with open(sound_file, 'rb') as f:
                    audio_bytes = f.read()
                st.audio(audio_bytes, format='audio/mp3')
            except Exception as e:
                st.error(f"Sound fehler: {e}")
        st.session_state.sound_test_clicked = False
    
    # Handle test all sounds
    if st.session_state.get('sound_test_all', False):
        for name, key in sound_options.items():
            sf = SOUND_FILES.get(key)
            if sf:
                try:
                    with open(sf, 'rb') as f:
                        st.audio(f.read(), format='audio/mp3')
                except:
                    pass
        st.session_state.sound_test_all = False
    
    st.divider()
    
    # Add pair
    st.markdown("### ➕ Paar hinzufuegen")
    available = ['MPC-USDT', 'BTC-USDT', 'ETH-USDT', 'BNB-USDT', 'SOL-USDT', 
                 'XRP-USDT', 'ADA-USDT', 'DOGE-USDT', 'AVAX-USDT', 'DOT-USDT']
    existing = list(pairs_config.keys())
    remaining = [p for p in available if p not in existing]
    
    if remaining:
        new_pair = st.selectbox("Paar", remaining, key="new_pair_select")
        if st.button("➕ Hinzufuegen"):
            add_pair(new_pair)
            st.rerun()
    else:
        st.info("Alle vorhanden!")
    
    # Delete pair
    st.markdown("### ➖ Paar entfernen")
    if pairs_config:
        pair_to_delete = st.selectbox("Paar", list(pairs_config.keys()), key="delete_pair_select")
        if st.button("🗑️ Entfernen", key="delete_pair_btn"):
            remove_pair(pair_to_delete)
            st.rerun()
    else:
        st.info("Keine Paare vorhanden!")

# ============================================================================
# TILE OVERVIEW
# ============================================================================

if st.session_state.selected_pair is None:
    st.subheader("📋 Home")
    
    if not pairs_config:
        st.info("Fuege oben ein Paar hinzu!")
    else:
        # CSS for tile borders

        cols = st.columns(3)
        
        # Use columns with styled containers
        for i, pair_name in enumerate(pairs_config.keys()):
            with cols[i % 3]:
                # Get fresh pair_data directly from settings
                pair_data = get_pair_settings(pair_name)
                enabled = pair_data.get('enabled', True)
                status_color = "🟢" if enabled else "🔴"
                
                trades = get_trades(pair_name, limit=1000)
                total_trades = len(trades)
                total_profit = sum(
                    (float(t.get('ex2_value_usdt', 0) or 0) - float(t.get('ex1_value_usdt', 0) or 0) - 
                     float(t.get('ex1_fees', 0) or 0) - float(t.get('ex2_fees', 0) or 0))
                    for t in trades
                )
                
                # Build complete tile as HTML
                st.markdown(f"""
                <div style="background: #262626; border: 1px solid #404040; border-radius: 8px; padding: 16px; margin: 4px 0;">
                    <div style="display: flex; align-items: center; gap: 8px; margin-bottom: 12px;">
                        <span style="font-size: 24px;">{status_color}</span>
                        <span style="font-size: 20px; font-weight: bold; color: white;">{pair_name}</span>
                    </div>
                    <div style="display: flex; justify-content: space-between; margin-bottom: 12px; color: #aaa;">
                        <span>Trades: {total_trades}</span>
                        <span>Gewinn: ${total_profit:.4f}</span>
                    </div>
                </div>
                """, unsafe_allow_html=True)
                
                if st.button("📊 Anzeigen", key=f"view_{pair_name}"):
                    st.session_state.selected_pair = pair_name
                    st.rerun()
            
# ============================================================================
# DETAIL VIEW - ORIGINAL DASHBOARD
# ============================================================================

else:
    pair = st.session_state.selected_pair
    
    if st.button("← Home"):
        st.session_state.selected_pair = None
        st.rerun()
    
    # Reload pair_data directly from config (NOT from cached pairs_config)
    pair_data = get_pair_settings(pair)
    pair_enabled = pair_data.get('enabled', False)
    status_emoji = "🟢" if pair_enabled else "🔴"
    
    col1, col2 = st.columns([4, 1])
    with col1:
        st.markdown(f"## {status_emoji} {pair}")
    with col2:
        new_enabled = st.checkbox("Bot AKTIV", value=pair_enabled, key="bot_enable_checkbox")
        if new_enabled != pair_enabled:
            set_pair_settings(pair, enabled=new_enabled)
            st.rerun()
    
    # Get data
    kucoin = get_kucoin_orderbook(pair)
    mexc = get_mexc_orderbook(pair)
    
    # Also fetch Level 2 orderbook for accurate spread calculation (same data as orderbook table)
    try:
        mexc_ob_resp = requests.get("https://api.mexc.com/api/v3/depth?symbol=MPCUSDT&limit=20", timeout=5)
        mexc_ob = mexc_ob_resp.json() if mexc_ob_resp.status_code == 200 else {'bids': [], 'asks': []}
        mexc_bids_l2 = [(float(p), float(v)) for p, v in mexc_ob.get('bids', [])[:20]]
        mexc_asks_l2 = [(float(p), float(v)) for p, v in mexc_ob.get('asks', [])[:20]]
    except:
        mexc_bids_l2, mexc_asks_l2 = [], []
    
    try:
        kucoin_ob_resp = requests.get("https://api.kucoin.com/api/v1/market/orderbook/level2_20?symbol=MPC-USDT", timeout=5)
        kucoin_ob = kucoin_ob_resp.json() if kucoin_ob_resp.status_code == 200 else {}
        kucoin_bids_l2 = [(float(p), float(v)) for p, v in kucoin_ob.get('data', {}).get('bids', [])[:20]]
        kucoin_asks_l2 = [(float(p), float(v)) for p, v in kucoin_ob.get('data', {}).get('asks', [])[:20]]
    except:
        kucoin_bids_l2, kucoin_asks_l2 = [], []
    
    if kucoin.get('ok') and mexc.get('ok'):
        # Use Level 2 best prices for spread (synchronized with orderbook table)
        k_ask = kucoin_asks_l2[0][0] if kucoin_asks_l2 else kucoin['ask']
        k_bid = kucoin_bids_l2[0][0] if kucoin_bids_l2 else kucoin['bid']
        m_ask = mexc_asks_l2[0][0] if mexc_asks_l2 else mexc['ask']
        m_bid = mexc_bids_l2[0][0] if mexc_bids_l2 else mexc['bid']
        
        # Calculate
        profit_km = m_bid - k_ask
        profit_mk = k_bid - m_ask
        vol_km = min(kucoin['ask_size'], mexc['bid_size'])
        vol_mk = min(mexc['ask_size'], kucoin['bid_size'])
        
        # Get wallet balances for the pair
        base_coin = pair.split('-')[0]
        quote_coin = pair.split('-')[1]
        
        # KuCoin balances
        kucoin_balances = {}
        if kucoin_key and kucoin_secret and kucoin_pass:
            kw = get_kucoin_balances(kucoin_key, kucoin_secret, kucoin_pass)
            if kw.get('ok'):
                kucoin_balances = kw.get('balances', {})
        
        # MEXC balances
        mexc_balances = {}
        if mexc_key and mexc_secret:
            mw = get_mexc_balances(mexc_key, mexc_secret)
            if mw.get('ok'):
                mexc_balances_raw = mw.get('balances', {})
                mexc_balances = {}
                for sym, bal in mexc_balances_raw.items():
                    if sym not in mexc_balances:
                        mexc_balances[sym] = bal
                    else:
                        mexc_balances[sym]['available'] += bal['available']
                        mexc_balances[sym]['total'] += bal['total']
        
        k_usdt = kucoin_balances.get('USDT', {}).get('available', 0)
        k_mpc = kucoin_balances.get(base_coin, {}).get('available', 0)
        m_usdt = mexc_balances.get('USDT', {}).get('available', 0)
        m_mpc = mexc_balances.get(base_coin, {}).get('available', 0)
        
        current_strategy = pair_data.get('strategy', 'usdt')
        threshold_start = pair_data.get('threshold_start', 1.0)
        threshold_stop = pair_data.get('threshold_stop', 0.5)
        
        spread_pct_km = (profit_km / k_ask * 100) if k_ask > 0 else 0
        spread_pct_mk = (profit_mk / m_ask * 100) if m_ask > 0 else 0
        
        km_profitable = profit_km > 0
        mk_profitable = profit_mk > 0
        km_meets_threshold = km_profitable and (spread_pct_km >= threshold_start)
        mk_meets_threshold = mk_profitable and (spread_pct_mk >= threshold_start)
        trade_possible_km = km_meets_threshold
        trade_possible_mk = mk_meets_threshold
        
        # Get real fees from APIs
        k_fee = get_kucoin_fees(kucoin_key, kucoin_secret, kucoin_pass, pair) if (kucoin_key and kucoin_secret and kucoin_pass) else {'ok': False, 'maker_fee_rate': 0.001, 'taker_fee_rate': 0.001}
        m_fee = get_mexc_fees(mexc_key, mexc_secret, pair.replace('-', ''))
        
        k_maker = k_fee.get('maker_fee_rate', 0.001)
        k_taker = k_fee.get('taker_fee_rate', 0.001)
        m_maker = m_fee.get('maker_fee_rate', 0.002)
        m_taker = m_fee.get('taker_fee_rate', 0.002)
        
        min_profit_buffer = 0.001  # 0.1%
        if k_ask > 0 and m_ask > 0:
            # Fee for K→M: Buy on KuCoin (Taker), Sell on MEXC (Maker)
            fee_pct_km = (k_taker + m_maker) * 100
            # Fee for M→K: Buy on MEXC (Taker), Sell on KuCoin (Maker)
            fee_pct_mk = (m_taker + k_maker) * 100
            recommended_min_km = fee_pct_km + min_profit_buffer * 100
            recommended_min_mk = fee_pct_mk + min_profit_buffer * 100
        else:
            fee_pct_km = fee_pct_mk = 0.3
            recommended_min_km = recommended_min_mk = 0.4
        
        coins_km = (vol_km * profit_km / k_ask) if k_ask > 0 else 0
        coins_mk = (vol_mk * profit_mk / m_ask) if m_ask > 0 else 0
        
        # =========================================================================
        # SECTIONS
        # =========================================================================
        
        # Übersicht - Expanded by default (for charts later)
        with st.expander("📊 Übersicht", expanded=True):
            st.info("Charts und Visualisierung kommen hier.")
        
        # Orderbook detailed view
        with st.expander("📋 Orderbook", expanded=False):
            try:
                mexc_ob_resp = requests.get("https://api.mexc.com/api/v3/depth?symbol=MPCUSDT&limit=20", timeout=5)
                mexc_ob = mexc_ob_resp.json() if mexc_ob_resp.status_code == 200 else {'bids': [], 'asks': []}
                mexc_bids = [(float(p), float(v)) for p, v in mexc_ob.get('bids', [])[:20]]
                mexc_asks = [(float(p), float(v)) for p, v in mexc_ob.get('asks', [])[:20]]
            except:
                mexc_bids, mexc_asks = [], []
            
            try:
                kucoin_ob_resp = requests.get("https://api.kucoin.com/api/v1/market/orderbook/level2_20?symbol=MPC-USDT", timeout=5)
                kucoin_ob = kucoin_ob_resp.json() if kucoin_ob_resp.status_code == 200 else {}
                kucoin_bids = [(float(p), float(v)) for p, v in kucoin_ob.get('data', {}).get('bids', [])[:20]]
                kucoin_asks = [(float(p), float(v)) for p, v in kucoin_ob.get('data', {}).get('asks', [])[:20]]
            except:
                kucoin_bids, kucoin_asks = [], []
            
            if mexc_bids_l2 and mexc_asks_l2 and kucoin_bids_l2 and kucoin_asks_l2:
                # Reuse already-fetched Level 2 data (no duplicate API calls)
                mexc_bids = mexc_bids_l2
                mexc_asks = mexc_asks_l2
                kucoin_bids = kucoin_bids_l2
                kucoin_asks = kucoin_asks_l2
                
                st.markdown("**Legende:** 🟢 Threshold erfüllt | 🟡 Positiv aber < Threshold | 🔴 Negativ")
                st.markdown("---")
                col_km, col_mk = st.columns(2)
                
                with col_km:
                    st.markdown("**KuCoin → MEXC**")
                    c1, c2 = st.columns([1, 8])
                    with c1:
                        st.image("/app/static/kucoin_icon.png", width=20)
                    with c2:
                        st.markdown('**KUCOIN BUY**')
                    for i in range(19, -1, -1):
                        k_ask_p = kucoin_asks[i][0] if i < len(kucoin_asks) else 0
                        k_ask_v = kucoin_asks[i][1] if i < len(kucoin_asks) else 0
                        m_bid_p = mexc_bids[0][0] if mexc_bids else 0
                        profit = m_bid_p - k_ask_p
                        pct = (profit / k_ask_p * 100) if k_ask_p > 0 else 0
                        bg = "rgba(0,255,0,0.15)" if pct >= threshold_start else ("rgba(255,235,59,0.15)" if pct >= 0 else "rgba(244,67,54,0.1)")
                        price_color = "#f44336"  # RED - what we pay on BUY side
                        st.markdown(f"<div style='background-color: {bg}; padding: 2px 8px; border-radius: 4px; margin: 1px 0;'><span style='color: #f44336; font-weight: bold;'>${k_ask_p:.6f}</span> <span style='color: #f44336;'>|</span> <span style='color: #f44336;'>{k_ask_v:.0f} MPC</span> <span style='color: #888; margin-left: 10px;'>{pct:+.3f}%</span></div>", unsafe_allow_html=True)
                    
                    km_spread_bg = "rgba(0,255,0,0.2)" if spread_pct_km >= threshold_start else ("rgba(255,235,59,0.2)" if spread_pct_km > 0 else "rgba(244,67,54,0.2)")
                    km_spread_color = "#00c853" if spread_pct_km >= threshold_start else ("#ffc107" if spread_pct_km > 0 else "#f44336")
                    st.markdown("---")
                    st.markdown(f"<div style='background-color: {km_spread_bg}; padding: 8px; border-radius: 8px; text-align: center; font-size: 24px; font-weight: bold; color: {km_spread_color};'>Spread: {spread_pct_km:+.3f}%</div>", unsafe_allow_html=True)
                    st.markdown("---")
                    
                    c1, c2 = st.columns([1, 8])
                    with c1:
                        st.image("/app/static/mexc_icon.png", width=20)
                    with c2:
                        st.markdown('**MEXC SELL**')
                    for i in range(20):
                        m_bid_p = mexc_bids[i][0] if i < len(mexc_bids) else 0
                        m_bid_v = mexc_bids[i][1] if i < len(mexc_bids) else 0
                        k_ask_p = kucoin_asks[0][0] if kucoin_asks else k_ask
                        profit = m_bid_p - k_ask_p
                        pct = (profit / k_ask_p * 100) if k_ask_p > 0 else 0
                        bg = "rgba(0,255,0,0.15)" if pct >= threshold_start else ("rgba(255,235,59,0.15)" if pct >= 0 else "rgba(244,67,54,0.1)")
                        price_color = "#00c853"  # GREEN - what we get on SELL side
                        st.markdown(f"<div style='background-color: {bg}; padding: 2px 8px; border-radius: 4px; margin: 1px 0;'><span style='color: #00c853; font-weight: bold;'>${m_bid_p:.5f}</span> <span style='color: #00c853;'>|</span> <span style='color: #00c853;'>{m_bid_v:.0f} MPC</span> <span style='color: #888; margin-left: 10px;'>{pct:+.3f}%</span></div>", unsafe_allow_html=True)
                
                with col_mk:
                    st.markdown("**MEXC → KuCoin**")
                    c1, c2 = st.columns([1, 8])
                    with c1:
                        st.image("/app/static/mexc_icon.png", width=20)
                    with c2:
                        st.markdown('**MEXC BUY**')
                    for i in range(19, -1, -1):
                        m_ask_p = mexc_asks[i][0] if i < len(mexc_asks) else 0
                        m_ask_v = mexc_asks[i][1] if i < len(mexc_asks) else 0
                        k_bid_p = kucoin_bids[0][0] if kucoin_bids else 0
                        profit = k_bid_p - m_ask_p
                        pct = (profit / m_ask_p * 100) if m_ask_p > 0 else 0
                        bg = "rgba(0,255,0,0.15)" if pct >= threshold_start else ("rgba(255,235,59,0.15)" if pct >= 0 else "rgba(244,67,54,0.1)")
                        price_color = "#f44336"  # RED - what we pay on BUY side
                        st.markdown(f"<div style='background-color: {bg}; padding: 2px 8px; border-radius: 4px; margin: 1px 0;'><span style='color: #f44336; font-weight: bold;'>${m_ask_p:.5f}</span> <span style='color: #f44336;'>|</span> <span style='color: #f44336;'>{m_ask_v:.0f} MPC</span> <span style='color: #888; margin-left: 10px;'>{pct:+.3f}%</span></div>", unsafe_allow_html=True)
                    
                    mk_spread_bg = "rgba(0,255,0,0.2)" if spread_pct_mk >= threshold_start else ("rgba(255,235,59,0.2)" if spread_pct_mk > 0 else "rgba(244,67,54,0.2)")
                    mk_spread_color = "#00c853" if spread_pct_mk >= threshold_start else ("#ffc107" if spread_pct_mk > 0 else "#f44336")
                    st.markdown("---")
                    st.markdown(f"<div style='background-color: {mk_spread_bg}; padding: 8px; border-radius: 8px; text-align: center; font-size: 24px; font-weight: bold; color: {mk_spread_color};'>Spread: {spread_pct_mk:+.3f}%</div>", unsafe_allow_html=True)
                    st.markdown("---")
                    
                    c1, c2 = st.columns([1, 8])
                    with c1:
                        st.image("/app/static/kucoin_icon.png", width=20)
                    with c2:
                        st.markdown('**KUCOIN SELL**')
                    for i in range(20):
                        k_bid_p = kucoin_bids[i][0] if i < len(kucoin_bids) else 0
                        k_bid_v = kucoin_bids[i][1] if i < len(kucoin_bids) else 0
                        m_ask_p = mexc_asks[0][0] if mexc_asks else m_ask
                        profit = k_bid_p - m_ask_p
                        pct = (profit / m_ask_p * 100) if m_ask_p > 0 else 0
                        bg = "rgba(0,255,0,0.15)" if pct >= threshold_start else ("rgba(255,235,59,0.15)" if pct >= 0 else "rgba(244,67,54,0.1)")
                        color = "#00c853" if pct >= threshold_start else ("#ffc107" if pct >= 0 else "#f44336")
                        st.markdown(f"<div style='background-color: {bg}; padding: 2px 8px; border-radius: 4px; margin: 1px 0;'><span style='color: #00c853; font-weight: bold;'>${k_bid_p:.6f}</span> <span style='color: #00c853;'>|</span> <span style='color: #00c853;'>{k_bid_v:.0f} MPC</span> <span style='color: #888; margin-left: 10px;'>{pct:+.3f}%</span></div>", unsafe_allow_html=True)
                
            else:
                st.info("Orderbook Daten nicht vollständig verfügbar")
        
        
        # Einstellungen
        with st.expander("⚙️ Einstellungen", expanded=False):
            s1, s2, s3, s4 = st.columns([1, 1, 1, 1])
            
            with s1:
                tss = pair_data.get('threshold_stop', 0.5)
                ts = pair_data.get('threshold_start', 1.0)
                ts_min = tss  # Start must be >= Stop
                ts_safe = max(ts, ts_min)
                ts_new = st.number_input("Start Threshold in %", ts_min, 50.0, ts_safe, 0.05, key=f"pts_{pair}")
                if ts_new != ts:
                    set_pair_settings(pair, threshold_start=ts_new)
            
            with s2:
                tss = pair_data.get('threshold_stop', 0.5)
                tss_max = ts_new  # Stop must be <= Start
                
                tss_safe = min(tss, tss_max)
                tss_new = st.number_input("Stop Threshold in %", 0.0, tss_max, tss_safe, 0.05, key=f"ptss_{pair}")
                if tss_new != tss:
                    set_pair_settings(pair, threshold_stop=tss_new)
            
            with s3:
                ae = pair_data.get('alert_enabled', True)
                ae_new = st.checkbox("🔔 Alert", value=ae, key=f"pae_{pair}")
                if ae_new != ae:
                    set_pair_settings(pair, alert_enabled=ae_new)
            
            with s4:
                strat = pair_data.get('strategy', 'usdt')
                strat_idx = 0 if strat == 'usdt' else 1
                new_strat = st.radio("Gewinn Strategie", ["USDT", "Coins"], index=strat_idx, key=f"pstr_{pair}")
                new_strat_val = 'usdt' if new_strat == "USDT" else 'coins'
                if new_strat_val != strat:
                    set_pair_settings(pair, strategy=new_strat_val)
            
            # Fee-Empfehlung
            st.markdown("---")
            fee_col1, fee_col2 = st.columns(2)
            with fee_col1:
                st.write(f"**MEXC:** Maker {(m_maker*100):.2f}% | Taker {(m_taker*100):.2f}%")
                st.write(f"**KuCoin:** Maker {(k_maker*100):.2f}% | Taker {(k_taker*100):.2f}%")
            with fee_col2:
                buffer_pct = min_profit_buffer * 100
                st.write(f"**Puffer:** {buffer_pct:.1f}%")
            
            st.write(f"**K→M:** {(k_taker*100):.2f}% + {(m_maker*100):.2f}% + Puffer {buffer_pct:.1f}% = **{(fee_pct_km + buffer_pct):.3f}%**")
            st.write(f"**M→K:** {(m_taker*100):.2f}% + {(k_maker*100):.2f}% + Puffer {buffer_pct:.1f}% = **{(fee_pct_mk + buffer_pct):.3f}%**")
            
            if threshold_start < max(recommended_min_km, recommended_min_mk):
                st.error(f"⚠️ **WARNUNG:** Threshold {threshold_start}% ist unter dem empfohlenen Minimum! "
                        f"Gebühren könnten den Gewinn auffressen.")
            else:
                st.success(f"✅ Threshold {threshold_start}% ist ausreichend.")
        
        # Wallets
        with st.expander("💰 Wallets", expanded=False):
            st.subheader("💰 Wallets")
            
            col1, col2, col3 = st.columns(3)
        
        # Extract base and quote from pair
        pair_parts = pair.split('-')
        base_coin_local = pair_parts[0] if len(pair_parts) > 0 else ''
        quote_coin_local = pair_parts[1] if len(pair_parts) > 1 else ''
        
        kucoin_key_local = config.get('kucoin', {}).get('api_key', '')
        kucoin_secret_local = config.get('kucoin', {}).get('api_secret', '')
        kucoin_pass_local = config.get('kucoin', {}).get('api_passphrase', '')
        mexc_key_local = config.get('mexc', {}).get('api_key', '')
        mexc_secret_local = config.get('mexc', {}).get('api_secret', '')
        
        # Fetch wallet data
        kucoin_wallet = {'ok': False, 'balances': {}}
        mexc_wallet = {'ok': False, 'balances': {}}
        
        if kucoin_key_local and kucoin_secret_local and kucoin_pass_local:
            kucoin_wallet = get_kucoin_balances(kucoin_key_local, kucoin_secret_local, kucoin_pass_local)
        
        if mexc_key_local and mexc_secret_local:
            mexc_wallet = get_mexc_balances(mexc_key_local, mexc_secret_local)
        
        # Collect balances for combined view
        k_balances = kucoin_wallet.get('balances', {})
        m_balances = mexc_wallet.get('balances', {})
        
        # KuCoin Wallet
        with col1:
            st.image("/app/static/kucoin_icon.png", width=40); st.text("KuCoin")
            if kucoin_wallet.get('ok'):
                bals = kucoin_wallet['balances']
                for sym in [base_coin_local, quote_coin_local]:
                    if sym:
                        if sym in bals:
                            bal = bals[sym]
                            st.metric(" ", f"{bal['available']:.2f} {sym}", f"Total: {bal['total']:.2f} {sym}")
                        else:
                            st.metric(" ", f"0.00 {sym}", f"Total: 0.00 {sym}")
            else:
                st.caption("KuCoin API Keys nicht konfiguriert")
        
        # MEXC Wallet  
        with col2:
            st.image("/app/static/mexc_icon.png", width=40); st.text("MEXC")
            if mexc_wallet.get('ok'):
                bals = mexc_wallet['balances']
                unique_balances = {}
                for sym, bal in bals.items():
                    if bal['total'] > 0:
                        if sym not in unique_balances:
                            unique_balances[sym] = bal
                        else:
                            unique_balances[sym] = {
                                'available': unique_balances[sym]['available'] + bal['available'],
                                'total': unique_balances[sym]['total'] + bal['total']
                            }
                for sym in [base_coin_local, quote_coin_local]:
                    if sym:
                        if sym in unique_balances:
                            bal = unique_balances[sym]
                            st.metric(" ", f"{bal['available']:.2f} {sym}", f"Total: {bal['total']:.2f} {sym}")
                        else:
                            st.metric(" ", f"0.00 {sym}", f"Total: 0.00 {sym}")
            else:
                st.caption("MEXC API Keys nicht konfiguriert")
        
        # Total Wallet (Combined)
        with col3:
            st.image("https://cdn-icons-png.flaticon.com/512/2333/2333570.png", width=40); st.text("GESAMT")
            for sym in [base_coin_local, quote_coin_local]:
                if sym:
                    k_avail = k_balances.get(sym, {}).get('available', 0) if k_balances else 0
                    k_total = k_balances.get(sym, {}).get('total', 0) if k_balances else 0
                    m_avail = m_balances.get(sym, {}).get('available', 0) if m_balances else 0
                    m_total = m_balances.get(sym, {}).get('total', 0) if m_balances else 0
                    total_avail = k_avail + m_avail
                    total_all = k_total + m_total
                    st.metric(" ", f"{total_avail:.2f} {sym}", f"Total: {total_all:.2f} {sym}")
        
        # Log - Trade history
        with st.expander("📜 Log", expanded=False):
            trades = get_trades('MPC-USDT', limit=100)
            
            if trades:
                # Prepare trade data
                rows = []
                for t in reversed(trades):
                    try:
                        ex1_val = float(t.get('ex1_value_usdt', 0) or 0)
                        ex2_val = float(t.get('ex2_value_usdt', 0) or 0)
                        fees = float(t.get('ex1_fees', 0) or 0) + float(t.get('ex2_fees', 0) or 0)
                        gross = ex2_val - ex1_val
                        net = gross - fees
                        direction = t.get('direction', '')
                        status = t.get('limit_watch_status', 'UNKNOWN')
                        
                        ts = t.get('internal_ts', '')
                        try:
                            dt = datetime.fromisoformat(ts)
                            date_str = dt.strftime('%d.%m')
                            time_str = dt.strftime('%H:%M:%S')
                        except:
                            date_str = ts[:10] if len(ts) > 10 else 'N/A'
                            time_str = ts[-8:] if len(ts) > 8 else ts
                        
                        rows.append({
                            'date': date_str,
                            'time': time_str,
                            'trade_id': t.get('trade_id', ''),
                            'trade_id_short': t.get('trade_id', '')[-6:],
                            'direction': 'K→M' if 'K->M' in direction else 'M→K',
                            'strategy': t.get('strategy', current_strategy),
                            'spread': float(t.get('spread_pct', 0) or 0),
                            'ex1_exchange': t.get('ex1_exchange', ''),
                            'ex1_order_id': t.get('ex1_order_id', ''),
                            'ex1_qty': float(t.get('ex1_qty_filled', 0) or 0),
                            'ex1_price': float(t.get('ex1_price_avg', t.get('ex1_price_actual', 0)) or 0),
                            'ex1_value': ex1_val,
                            'ex1_fees': float(t.get('ex1_fees', 0) or 0),
                            'ex2_exchange': t.get('ex2_exchange', ''),
                            'ex2_order_id': t.get('ex2_order_id', ''),
                            'ex2_qty': float(t.get('ex2_qty_filled', 0) or 0),
                            'ex2_price': float(t.get('ex2_price_avg', t.get('ex2_price_actual', 0)) or 0),
                            'ex2_value': ex2_val,
                            'ex2_fees': float(t.get('ex2_fees', 0) or 0),
                            'gross': gross,
                            'fees': fees,
                            'net': net,
                            'status': status,
                            'profit_mpc': float(t.get('profit_mpc_expected', 0) or 0),
                            'profit_usdt': float(t.get('profit_usdt_expected', 0) or 0),
                        })
                    except:
                        pass
                
                if rows:
                    # Summary stats
                    total_trades = len(rows)
                    filled_trades = len([r for r in rows if r['status'] == 'FILLED'])
                    winning_trades = len([r for r in rows if r['net'] > 0])
                    total_profit = sum(r['net'] for r in rows)
                    
                    st.markdown("#### 📊 Trade Übersicht")
                    col1, col2, col3, col4 = st.columns(4)
                    col1.metric("Trades", total_trades)
                    col2.metric("Gefüllt", filled_trades)
                    col3.metric("Gewinn", f"{winning_trades}/{total_trades-winning_trades}")
                    col4.metric("Netto", f"${total_profit:.4f}")
                    
                    # Clean table
                    st.markdown("""
                    <style>
                        .log-table{width:100%;border-collapse:collapse;font-size:12px;}
                        .log-table th{background:#262730;color:#aaa;text-align:left;padding:8px 10px;border-bottom:2px solid #444;}
                        .log-table td{padding:8px 10px;border-bottom:1px solid #222;color:#eee;}
                        .log-table tr:hover{background:#1e1e2a;}
                        .log-table .pos{color:#4ade80;}
                        .log-table .neg{color:#f87171;}
                    </style>
                    """, unsafe_allow_html=True)
                    
                    table_html = '<table class="log-table"><thead><tr>'
                    table_html += '<th>Datum</th><th>Zeit</th><th>ID</th><th>Dir</th><th>Spread</th>'
                    table_html += '<th>Ex1</th><th>Qty</th><th>→</th><th>Ex2</th><th>Qty</th>'
                    table_html += '<th style="text-align:right;">Brutto</th><th style="text-align:right;">Netto</th><th>Status</th>'
                    table_html += '</tr></thead><tbody>'
                    
                    for r in rows:
                        gc = 'pos' if r['gross'] > 0 else 'neg'
                        nc = 'pos' if r['net'] > 0 else 'neg'
                        se = {'FILLED': '✅', 'PARTIAL': '⚠️', 'WATCHING': '⏳', 'CANCELLED': '❌', 'FAILED': '🔴'}.get(r['status'], '❓')
                        
                        table_html += f"<tr>"
                        table_html += f"<td>{r['date']}</td>"
                        table_html += f"<td>{r['time']}</td>"
                        table_html += f"<td style='font-family:monospace;'>{r['trade_id_short']}</td>"
                        table_html += f"<td>{r['direction']}</td>"
                        table_html += f"<td>{r['spread']:.2f}%</td>"
                        table_html += f"<td>{r['ex1_exchange']}</td>"
                        table_html += f"<td>{r['ex1_qty']:.1f}</td>"
                        table_html += f"<td>→</td>"
                        table_html += f"<td>{r['ex2_exchange']}</td>"
                        table_html += f"<td>{r['ex2_qty']:.1f}</td>"
                        table_html += f"<td style='text-align:right;' class='{gc}'>${r['gross']:.4f}</td>"
                        table_html += f"<td style='text-align:right;font-weight:bold;' class='{nc}'>${r['net']:.4f}</td>"
                        table_html += f"<td>{se}</td>"
                        table_html += f"</tr>"
                    
                    table_html += '</tbody></table>'
                    st.markdown(table_html, unsafe_allow_html=True)
                    
                    # Detailed view button
                    st.markdown("---")
                    import json
                    import pandas as pd
                    
                    trades_json = json.dumps(rows)
                    
                    popup_html = f"""
                    <script>
                    function openDetailedView() {{
                        var data = {trades_json};
                        var html = `<!DOCTYPE html>
<html><head><title>Trade Details</title>
<style>
*{{margin:0;padding:0;box-sizing:border-box;}}
body{{font-family:system-ui,sans-serif;background:#0f0f14;color:#eee;padding:20px;}}
h1{{color:#fff;margin-bottom:20px;}}
.filters{{margin-bottom:20px;display:flex;gap:10px;flex-wrap:wrap;}}
.filters select,.filters input{{padding:8px;background:#1a1a24;border:1px solid #333;border-radius:6px;color:#fff;font-size:13px;}}
table{{width:100%;border-collapse:collapse;font-size:12px;background:#1a1a24;border-radius:8px;overflow:hidden;}}
th{{background:#262730;color:#aaa;text-align:left;padding:12px;border-bottom:2px solid #444;}}
td{{padding:10px;border-bottom:1px solid #222;}}
tr:hover{{background:#252535;}}
.pos{{color:#4ade80;}}
.neg{{color:#f87171;}}
.detail-grid{{display:grid;grid-template-columns:repeat(4,1fr);gap:12px;padding:10px 0;}}
.detail-item{{background:#222;padding:10px;border-radius:6px;}}
.detail-label{{color:#888;font-size:11px;margin-bottom:4px;}}
.detail-value{{color:#fff;}}
code{{background:#333;padding:2px 6px;border-radius:3px;}}
</style></head><body>
<h1>📊 Trade Details - MPC-USDT</h1>
<div class="filters">
<select id="statusFilter"><option value="">Alle Status</option><option value="FILLED">FILLED</option><option value="PARTIAL">PARTIAL</option><option value="WATCHING">WATCHING</option></select>
<select id="dirFilter"><option value="">Alle Richtungen</option><option value="M→K">M→K</option><option value="K→M">K→M</option></select>
<input type="text" id="searchInput" placeholder="Trade ID suchen...">
</div>
<div id="count" style="margin-bottom:15px;color:#888;"></div>
<table><thead><tr><th>Datum</th><th>Zeit</th><th>Trade ID</th><th>Dir</th><th>Spread</th><th>Ex1</th><th>Ex1 Qty</th><th>Ex2</th><th>Ex2 Qty</th><th style="text-align:right;">Brutto</th><th style="text-align:right;">Netto</th><th>Status</th></tr></thead>
<tbody id="tradeBody"></tbody></table>
<script>
var trades = {trades_json};
function filterTable(){{
var sf=document.getElementById('statusFilter').value;
var df=document.getElementById('dirFilter').value;
var search=document.getElementById('searchInput').value.toLowerCase();
var filtered=trades.filter(function(t){{
if(sf&&t.status!==sf)return false;
if(df&&t.direction!==df)return false;
if(search&&!t.trade_id.toLowerCase().includes(search))return false;
return true;
}});
document.getElementById('count').textContent=filtered.length+' von '+trades.length+' Trades';
var html='';
filtered.forEach(function(r){{
var gc=r.gross>0?'pos':'neg';
var nc=r.net>0?'pos':'neg';
html+='<tr onclick="toggleDetail(\''+r.trade_id+'\')" style="cursor:pointer;">';
html+='<td>'+r.date+'</td><td>'+r.time+'</td><td style="font-family:monospace;">'+r.trade_id+'</td>';
html+='<td>'+r.direction+'</td><td>'+r.spread.toFixed(2)+'%</td>';
html+='<td>'+r.ex1_exchange+'</td><td>'+r.ex1_qty.toFixed(2)+'</td>';
html+='<td>'+r.ex2_exchange+'</td><td>'+r.ex2_qty.toFixed(2)+'</td>';
html+='<td style="text-align:right;" class="'+gc+'">$'+r.gross.toFixed(4)+'</td>';
html+='<td style="text-align:right;font-weight:bold;" class="'+nc+'">$'+r.net.toFixed(4)+'</td>';
html+='<td>'+r.status+'</td></tr>';
html+='<tr id="d-'+r.trade_id+'" style="display:none;"><td colspan="12">';
html+='<div class=detail-grid>';
html+='<div class=detail-item><div class=detail-label>Ex1 Order ID</div><div class=detail-value><code>'+r.ex1_order_id+'</code></div></div>';
html+='<div class=detail-item><div class=detail-label>Ex1 Price</div><div class=detail-value>$'+r.ex1_price.toFixed(6)+'</div></div>';
html+='<div class=detail-item><div class=detail-label>Ex1 Value</div><div class=detail-value>$'+r.ex1_value.toFixed(4)+'</div></div>';
html+='<div class=detail-item><div class=detail-label>Ex1 Fees</div><div class=detail-value>$'+r.ex1_fees.toFixed(4)+'</div></div>';
html+='<div class=detail-item><div class=detail-label>Ex2 Order ID</div><div class=detail-value><code>'+r.ex2_order_id+'</code></div></div>';
html+='<div class=detail-item><div class=detail-label>Ex2 Price</div><div class=detail-value>$'+r.ex2_price.toFixed(6)+'</div></div>';
html+='<div class=detail-item><div class=detail-label>Ex2 Value</div><div class=detail-value>$'+r.ex2_value.toFixed(4)+'</div></div>';
html+='<div class=detail-item><div class=detail-label>Ex2 Fees</div><div class=detail-value>$'+r.ex2_fees.toFixed(4)+'</div></div>';
html+='<div class=detail-item><div class=detail-label>Profit MPC</div><div class=detail-value>'+r.profit_mpc.toFixed(4)+'</div></div>';
html+='<div class=detail-item><div class=detail-label>Profit USDT</div><div class=detail-value>$'+r.profit_usdt.toFixed(4)+'</div></div>';
html+='<div class=detail-item><div class=detail-label>Strategie</div><div class=detail-value>'+r.strategy+'</div></div>';
html+='</div></td></tr>';
}});
document.getElementById('tradeBody').innerHTML=html;
}}
function toggleDetail(id){{var el=document.getElementById('d-'+id);if(el)el.style.display=el.style.display==='none'?'table-row':'none';}}
document.getElementById('statusFilter').onchange=filterTable;
document.getElementById('dirFilter').onchange=filterTable;
document.getElementById('searchInput').onkeyup=filterTable;
filterTable();
<\/script>
</body></html>`;
                        var blob = new Blob([html], {type: 'text/html'});
                        var url = URL.createObjectURL(blob);
                        var w = window.open(url, '_blank', 'width=1400,height=800');
                        if (w) w.focus();
                        URL.revokeObjectURL(url);
                    }}
                    </script>
                    <button onclick="openDetailedView()" style="background:linear-gradient(135deg,#667eea,#764ba2);color:white;border:none;padding:12px 24px;border-radius:8px;cursor:pointer;font-size:14px;font-weight:500;">🔍 Detaillierte Ansicht öffnen</button>
                    """
                    st.markdown(popup_html, unsafe_allow_html=True)
                    
                    # CSV Export
                    df = pd.DataFrame(rows)
                    csv_cols = ['date', 'time', 'trade_id', 'direction', 'strategy', 'spread',
                               'ex1_exchange', 'ex1_order_id', 'ex1_qty', 'ex1_price', 'ex1_value', 'ex1_fees',
                               'ex2_exchange', 'ex2_order_id', 'ex2_qty', 'ex2_price', 'ex2_value', 'ex2_fees',
                               'gross', 'fees', 'net', 'profit_mpc', 'profit_usdt', 'status']
                    csv_bytes = df[csv_cols].to_csv(index=False).encode('utf-8')
                    st.download_button("📥 CSV Export", data=csv_bytes, file_name=f"MPC_trades_{datetime.now().strftime('%Y%m%d_%H%M')}.csv", mime="text/csv")
                else:
                    st.info("Keine Trades")
            else:
                st.info("Keine Trades")
        
        if trade_possible_km or trade_possible_mk:
            # Determine best direction based on strategy
            if current_strategy == 'usdt':
                # USDT strategy: compare total profit
                profit_km_total = profit_km * vol_km
                profit_mk_total = profit_mk * vol_mk
                show_direction = "K→M" if profit_km_total >= profit_mk_total else "M→K"
                show_volume = vol_km if show_direction == "K→M" else vol_mk
                show_profit_txt = f"${abs(profit_km if show_direction == 'K→M' else profit_mk):.6f}"
            else:
                # Coins strategy
                show_direction = "K→M" if coins_km >= coins_mk else "M→K"
                show_volume = vol_km if show_direction == "K→M" else vol_mk
                show_profit_txt = f"{abs(coins_km if show_direction == 'K→M' else coins_mk):.2f} MPC"
            
            # Direction header
            direction_color = "🟢"
            st.success(f"{direction_color} **BESTE RICHTUNG: {show_direction}** | Gewinn: {show_profit_txt} | Vol: {show_volume:.0f} Coins")
            
            # Create clear table
            col_buy, col_sell, col_profit = st.columns(3)
            
            with col_buy:
                st.markdown("### 📥 KAUFEN")
                if show_direction == "K→M":
                    # K→M: Buy on KuCoin (we have k_usdt USDT there)
                    available_usdt = k_usdt  # From wallet
                    max_coins_by_usdt = available_usdt / k_ask if k_ask > 0 else 0
                    max_coins = min(max_coins_by_usdt, vol_km)
                    st.metric("Exchange", "KuCoin")
                    st.metric("Preis (Ask)", f"${k_ask:.6f}")
                    st.metric("Verfügbar USDT", f"${available_usdt:.2f}")
                    st.metric("Kaufbar (max)", f"{max_coins:.0f} MPC")
                else:
                    # M→K: Buy on MEXC (we have m_usdt USDT there)
                    available_usdt = m_usdt  # From wallet
                    max_coins_by_usdt = available_usdt / m_ask if m_ask > 0 else 0
                    max_coins = min(max_coins_by_usdt, vol_mk)
                    if available_usdt > 0:
                        st.metric("Exchange", "MEXC")
                        st.metric("Preis (Ask)", f"${m_ask:.6f}")
                        st.metric("Verfügbar USDT", f"${available_usdt:.2f}")
                        st.metric("Kaufbar (max)", f"{max_coins:.0f} MPC")
                    else:
                        st.metric("Exchange", "⚠️ MEXC")
                        st.metric("Preis (Ask)", f"${m_ask:.6f}")
                        st.metric("Verfügbar USDT", f"${available_usdt:.2f}")
                        st.error("KEINE USDT!")
            
            with col_sell:
                st.markdown("### 📤 VERKAUFEN")
                if show_direction == "K→M":
                    st.metric("Exchange", "MEXC")
                    st.metric("Preis (Bid)", f"${m_bid:.6f}")
                    st.metric("Max verkaufbar", f"{max_coins:.0f} MPC")
                    st.metric("Ertrag (USD)", f"${m_bid * max_coins:.4f}")
                else:
                    st.metric("Exchange", "KuCoin")
                    st.metric("Preis (Bid)", f"${k_bid:.6f}")
                    st.metric("Max verkaufbar", f"{max_coins:.0f} MPC")
                    st.metric("Ertrag (USD)", f"${k_bid * max_coins:.4f}")
            
            with col_profit:
                st.markdown("### 💰 GEWINN")
                if show_direction == "K→M":
                    cost = k_ask * max_coins
                    revenue = m_bid * max_coins
                    profit = revenue - cost
                    if current_strategy == 'usdt':
                        st.metric("Kosten", f"${cost:.4f}")
                        st.metric("Erlös", f"${revenue:.4f}")
                        st.metric("💵 NETTO-GEWINN", f"${profit:.4f}", delta=f"+{profit:.4f}")
                    else:
                        st.metric("Kosten", f"{cost / k_ask:.2f} MPC")
                        st.metric("Erlös", f"{revenue / m_bid:.2f} MPC")
                        coins_profit = (revenue / m_bid) - (cost / k_ask)
                        st.metric("💵 NETTO-GEWINN", f"{coins_profit:.2f} MPC", delta=f"+{coins_profit:.2f}")
                else:
                    cost = m_ask * max_coins
                    revenue = k_bid * max_coins
                    profit = revenue - cost
                    if current_strategy == 'usdt':
                        st.metric("Kosten", f"${cost:.4f}")
                        st.metric("Erlös", f"${revenue:.4f}")
                        st.metric("💵 NETTO-GEWINN", f"${profit:.4f}", delta=f"+{profit:.4f}")
                    else:
                        st.metric("Kosten", f"{cost / m_ask:.2f} MPC")
                        st.metric("Erlös", f"{revenue / k_bid:.2f} MPC")
                        coins_profit = (revenue / k_bid) - (cost / m_ask)
                        st.metric("💵 NETTO-GEWINN", f"{coins_profit:.2f} MPC", delta=f"+{coins_profit:.2f}")
        else:
            pass  # No profitable spread
        
        # Show both directions for reference
        # Alert - only if threshold is met
        pair_alert = pair_data.get('alert_enabled', True)
        
        # Debug output for alert conditions
        alert_debug = st.session_state.get('alert_debug', False)
        if alert_debug:
            st.info(f"DEBUG Alert: pair_alert={pair_alert}, alert_enabled={alert_enabled}, trade_possible_km={trade_possible_km}, trade_possible_mk={trade_possible_mk}")
        
        # Toggle debug mode
        if st.button("🔍 Debug Alerts", key="alert_debug_toggle"):
            st.session_state.alert_debug = not st.session_state.get('alert_debug', False)
        
        # Track last trade for trade alerts
        if 'last_trade_count' not in st.session_state:
            st.session_state.last_trade_count = 0
        
        # Get current trade count
        try:
            trades_resp = requests.get(f'http://localhost:8505/trades/{selected_pair}', timeout=5)
            if trades_resp.status_code == 200:
                trades_data = trades_resp.json()
                current_trade_count = trades_data.get('count', 0)
                
                # If new trades detected, play trade alert
                if current_trade_count > st.session_state.last_trade_count:
                    st.session_state.last_trade_count = current_trade_count
                    # Play kaching sound for new trade
                    play_sound('kaching', vol)
                    st.success("🎉 NEUER TRADE ERKANNT!")
        except:
            pass  # Bot may not be running
        
        if pair_alert and alert_enabled and (trade_possible_km or trade_possible_mk):
            # Determine spread and play appropriate sound
            spread_pct = max(spread_pct_km, spread_pct_mk)
            if spread_pct >= 10:
                play_sound('ab10', vol)
                st.warning("🚨 Spread >= 10%!")
            elif spread_pct >= 3:
                play_sound('bis10', vol)
                st.warning("🚨 Spread 3-10%!")
            else:
                play_sound('bis3', vol)
                st.warning("🚨 Spread 1-3%!")
        elif pair_alert and alert_enabled and (spread_pct_km > 0 or spread_pct_mk > 0):
            # Positive spread but below threshold - still notify
            spread_pct = max(spread_pct_km, spread_pct_mk)
            st.info(f"📊 Spread positiv aber unter Threshold: {spread_pct:.2f}%")
        else:
            # Show current state
            spread_pct = max(spread_pct_km, spread_pct_mk)
            st.caption(f"Spreads: K→M {spread_pct_km:.2f}%, M→K {spread_pct_mk:.2f}% | Threshold: {threshold_start:.1f}%")
    
    else:
        st.error("Daten nicht verfuegbar")
    
# Auto refresh
if st.session_state.selected_pair:
    import time
    time.sleep(2)
    st.rerun()


# =============================================================================
# LIVE LOG VIEWER (SIDEBAR)


