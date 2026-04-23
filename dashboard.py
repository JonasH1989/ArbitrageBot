#!/usr/bin/env python3
"""
Arbitrage Bot Dashboard - Multi-Pair + Original Detail View
"""

import streamlit as st
import streamlit.components.v1 as components
import requests
import yaml
from pathlib import Path
from datetime import datetime
import os
import pandas as pd
from trade_logger import *
import sys
sys.path.insert(0, str(Path(__file__).parent / "config"))
from settings_sync import get_setting, set_setting, get_pair_settings, set_pair_settings, get_alert_settings, set_alert_settings, get_api_keys, set_api_keys, get_all_pairs, add_pair, remove_pair


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
    
    # Alert
    st.markdown("### 🔔 Alert")
    # Load current settings via settings_sync
    alert_settings = get_alert_settings()
    
    alert_enabled = st.checkbox("Akustischer Alert", value=alert_settings.get('enabled', True), key="alert_enabled_checkbox")
    
    # Volume - save on change
    volume = st.slider("🔊 Lautstaerke", 0.0, 1.0, alert_settings.get('volume', 0.3), 0.1, key="volume_slider", on_change=lambda: set_alert_settings(
        enabled=st.session_state.alert_enabled_checkbox,
        volume=st.session_state.volume_slider
    ))
    
    # Sound playback
    vol = volume
    
    if st.button("▶️ Test Sound"):
        import time
        # Unique timestamp to force re-render of components.html
        ts = int(time.time() * 1000000)
        sound_html = f"""
        <script>
            try {{
                const ctx = new (window.AudioContext || window.webkitAudioContext)();
                for (let i = 0; i < 3; i++) {{
                    setTimeout(() => {{
                        const o = ctx.createOscillator(), g = ctx.createGain();
                        o.connect(g); g.connect(ctx.destination);
                        o.frequency.value = 880; o.type = 'sine'; g.gain.value = {vol};
                        o.start(); o.stop(ctx.currentTime + 0.1);
                    }}, i * 200);
                }}
            }} catch(e) {{}}
        </script>
        <!-- {ts} -->
        """
        components.html(sound_html, height=0, width=0)
    
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

# ============================================================================
# TILE OVERVIEW
# ============================================================================

if st.session_state.selected_pair is None:
    st.subheader("📋 Paare")
    
    if not pairs_config:
        st.info("Fuege oben ein Paar hinzu!")
    else:
        cols = st.columns(3)
        
        for i, (pair_name, pair_data) in enumerate(pairs_config.items()):
            with cols[i % 3]:
                # Fetch data
                kucoin = get_kucoin_orderbook(pair_name)
                mexc = get_mexc_orderbook(pair_name)
                
                # Calculate
                is_profitable = False
                if kucoin.get('ok') and mexc.get('ok'):
                    profit_km = mexc['bid'] - kucoin['ask']
                    profit_mk = kucoin['bid'] - mexc['ask']
                    best = max(profit_km, profit_mk)
                    is_profitable = best > 0
                
                enabled = pair_data.get('enabled', True)
                tile_emoji = "🟢" if enabled else "🔴"
                
                st.subheader(f"{tile_emoji} {pair_name}")
                
                # Prices preview
                if kucoin.get('ok') and mexc.get('ok'):
                    c1, c2 = st.columns(2)
                    with c1:
                        st.caption(f"K: ${kucoin['bid']:.6f}")
                    with c2:
                        st.caption(f"M: ${mexc['bid']:.6f}")
                
                # View button
                if st.button("📊 Anzeigen", key=f"view_{pair_name}"):
                    st.session_state.selected_pair = pair_name
                    st.rerun()

# ============================================================================
# DETAIL VIEW - ORIGINAL DASHBOARD
# ============================================================================

else:
    pair = st.session_state.selected_pair
    
    if st.button("← Zurueck zu Paaren"):
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
    
    if kucoin.get('ok') and mexc.get('ok'):
        k_ask, k_bid = kucoin['ask'], kucoin['bid']
        m_ask, m_bid = mexc['ask'], mexc['bid']
        
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
        
        fee_taker = 0.001
        min_profit_buffer = 0.0002
        if k_ask > 0 and m_ask > 0:
            fee_pct_km = fee_taker * (k_ask + m_bid) / k_ask * 100
            recommended_min_km = fee_pct_km + min_profit_buffer * 100
            fee_pct_mk = fee_taker * (m_ask + k_bid) / m_ask * 100
            recommended_min_mk = fee_pct_mk + min_profit_buffer * 100
        else:
            fee_pct_km = fee_pct_mk = 0.2
            recommended_min_km = recommended_min_mk = 0.3
        
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
            
            if mexc_bids and mexc_asks and kucoin_bids and kucoin_asks:
                st.markdown("**Legende:** 🟢 Threshold erfüllt | 🟡 Positiv aber < Threshold | 🔴 Negativ")
                st.markdown("---")
                col_km, col_mk = st.columns(2)
                
                with col_km:
                    st.markdown("**KuCoin → MEXC**")
                    st.markdown('🥇 **KUCOIN BUY**')
                    for i in range(19, -1, -1):
                        k_ask_p = kucoin_asks[i][0] if i < len(kucoin_asks) else 0
                        k_ask_v = kucoin_asks[i][1] if i < len(kucoin_asks) else 0
                        m_bid_p = mexc_bids[0][0] if mexc_bids else 0
                        profit = m_bid_p - k_ask_p
                        pct = (profit / k_ask_p * 100) if k_ask_p > 0 else 0
                        bg = "rgba(0,255,0,0.15)" if pct >= threshold_start else ("rgba(255,235,59,0.15)" if pct >= 0 else "rgba(244,67,54,0.1)")
                        color = "#00c853" if pct >= threshold_start else ("#ffc107" if pct >= 0 else "#f44336")
                        st.markdown(f"<div style='background-color: {bg}; padding: 2px 8px; border-radius: 4px; margin: 1px 0;'><span style='color: {color}; font-weight: bold;'>${k_ask_p:.5f}</span> <span style='color: #888;'>|</span> <span style='color: #fff;'>{k_ask_v:.0f} MPC</span> <span style='color: #888; margin-left: 10px;'>{pct:+.3f}%</span></div>", unsafe_allow_html=True)
                    
                    km_spread_bg = "rgba(0,255,0,0.2)" if spread_pct_km >= threshold_start else ("rgba(255,235,59,0.2)" if spread_pct_km > 0 else "rgba(244,67,54,0.2)")
                    km_spread_color = "#00c853" if spread_pct_km >= threshold_start else ("#ffc107" if spread_pct_km > 0 else "#f44336")
                    st.markdown("---")
                    st.markdown(f"<div style='background-color: {km_spread_bg}; padding: 8px; border-radius: 8px; text-align: center; font-size: 24px; font-weight: bold; color: {km_spread_color};'>Spread: {spread_pct_km:+.3f}%</div>", unsafe_allow_html=True)
                    st.markdown("---")
                    
                    st.markdown('🥈 **MEXC SELL**')
                    for i in range(20):
                        m_bid_p = mexc_bids[i][0] if i < len(mexc_bids) else 0
                        m_bid_v = mexc_bids[i][1] if i < len(mexc_bids) else 0
                        k_ask_p = kucoin_asks[0][0] if kucoin_asks else k_ask
                        profit = m_bid_p - k_ask_p
                        pct = (profit / k_ask_p * 100) if k_ask_p > 0 else 0
                        bg = "rgba(0,255,0,0.15)" if pct >= threshold_start else ("rgba(255,235,59,0.15)" if pct >= 0 else "rgba(244,67,54,0.1)")
                        color = "#00c853" if pct >= threshold_start else ("#ffc107" if pct >= 0 else "#f44336")
                        st.markdown(f"<div style='background-color: {bg}; padding: 2px 8px; border-radius: 4px; margin: 1px 0;'><span style='color: {color}; font-weight: bold;'>${m_bid_p:.5f}</span> <span style='color: #888;'>|</span> <span style='color: #fff;'>{m_bid_v:.0f} MPC</span> <span style='color: #888; margin-left: 10px;'>{pct:+.3f}%</span></div>", unsafe_allow_html=True)
                
                with col_mk:
                    st.markdown("**MEXC → KuCoin**")
                    st.markdown('🥈 **MEXC BUY**')
                    for i in range(19, -1, -1):
                        m_ask_p = mexc_asks[i][0] if i < len(mexc_asks) else 0
                        m_ask_v = mexc_asks[i][1] if i < len(mexc_asks) else 0
                        k_bid_p = kucoin_bids[0][0] if kucoin_bids else 0
                        profit = k_bid_p - m_ask_p
                        pct = (profit / m_ask_p * 100) if m_ask_p > 0 else 0
                        bg = "rgba(0,255,0,0.15)" if pct >= threshold_start else ("rgba(255,235,59,0.15)" if pct >= 0 else "rgba(244,67,54,0.1)")
                        color = "#00c853" if pct >= threshold_start else ("#ffc107" if pct >= 0 else "#f44336")
                        st.markdown(f"<div style='background-color: {bg}; padding: 2px 8px; border-radius: 4px; margin: 1px 0;'><span style='color: {color}; font-weight: bold;'>${m_ask_p:.5f}</span> <span style='color: #888;'>|</span> <span style='color: #fff;'>{m_ask_v:.0f} MPC</span> <span style='color: #888; margin-left: 10px;'>{pct:+.3f}%</span></div>", unsafe_allow_html=True)
                    
                    mk_spread_bg = "rgba(0,255,0,0.2)" if spread_pct_mk >= threshold_start else ("rgba(255,235,59,0.2)" if spread_pct_mk > 0 else "rgba(244,67,54,0.2)")
                    mk_spread_color = "#00c853" if spread_pct_mk >= threshold_start else ("#ffc107" if spread_pct_mk > 0 else "#f44336")
                    st.markdown("---")
                    st.markdown(f"<div style='background-color: {mk_spread_bg}; padding: 8px; border-radius: 8px; text-align: center; font-size: 24px; font-weight: bold; color: {mk_spread_color};'>Spread: {spread_pct_mk:+.3f}%</div>", unsafe_allow_html=True)
                    st.markdown("---")
                    
                    st.markdown('🥇 **KUCOIN SELL**')
                    for i in range(20):
                        k_bid_p = kucoin_bids[i][0] if i < len(kucoin_bids) else 0
                        k_bid_v = kucoin_bids[i][1] if i < len(kucoin_bids) else 0
                        m_ask_p = mexc_asks[0][0] if mexc_asks else m_ask
                        profit = k_bid_p - m_ask_p
                        pct = (profit / m_ask_p * 100) if m_ask_p > 0 else 0
                        bg = "rgba(0,255,0,0.15)" if pct >= threshold_start else ("rgba(255,235,59,0.15)" if pct >= 0 else "rgba(244,67,54,0.1)")
                        color = "#00c853" if pct >= threshold_start else ("#ffc107" if pct >= 0 else "#f44336")
                        st.markdown(f"<div style='background-color: {bg}; padding: 2px 8px; border-radius: 4px; margin: 1px 0;'><span style='color: {color}; font-weight: bold;'>${k_bid_p:.5f}</span> <span style='color: #888;'>|</span> <span style='color: #fff;'>{k_bid_v:.0f} MPC</span> <span style='color: #888; margin-left: 10px;'>{pct:+.3f}%</span></div>", unsafe_allow_html=True)
                
            else:
                st.info("Orderbook Daten nicht vollständig verfügbar")
        
        # Einstellungen
        with st.expander("⚙️ Einstellungen", expanded=False):
            s1, s2, s3, s4 = st.columns([1, 1, 1, 1])
            
            with s1:
                ts = pair_data.get('threshold_start', 1.0)
                ts_new = st.number_input("Start %", 0.0, 50.0, ts, 0.05, key=f"pts_{pair}")
                if ts_new != ts:
                    set_pair_settings(pair, threshold_start=ts_new)
            
            with s2:
                tss = pair_data.get('threshold_stop', 0.5)
                tss_new = st.number_input("Stop %", 0.0, max(0.1, ts_new), tss, 0.05, key=f"ptss_{pair}")
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
                new_strat = st.radio("Strategie", ["💰 USDT", "🪙 Coins"], index=strat_idx, key=f"pstr_{pair}")
                new_strat_val = 'usdt' if new_strat == "💰 USDT" else 'coins'
                if new_strat_val != strat:
                    set_pair_settings(pair, strategy=new_strat_val)
        
        # Fee Empfehlung
        with st.expander("⚠️ Fee Empfehlung", expanded=False):
            fee_col1, fee_col2 = st.columns(2)
            with fee_col1:
                st.write(f"**K→M:** Fees ≈ {fee_pct_km:.3f}%")
                st.write(f"**M→K:** Fees ≈ {fee_pct_mk:.3f}%")
            with fee_col2:
                st.write(f"**Min. Threshold:** ≥{max(recommended_min_km, recommended_min_mk):.2f}%")
                st.write(f"**Aktueller Threshold:** {threshold_start}%")
            if threshold_start < max(recommended_min_km, recommended_min_mk):
                st.error(f"⚠️ **WARNUNG:** Threshold {threshold_start}% ist unter dem empfohlenen Minimum!")
            else:
                st.success(f"✅ Threshold {threshold_start}% ist ausreichend.")
        
        # Wallet
        with st.expander("💰 Wallet", expanded=False):
            w1, w2 = st.columns(2)
            with w1:
                st.markdown("### KuCoin")
                st.metric("USDT", f"${k_usdt:.2f}")
                st.metric(base_coin, f"{k_mpc:.2f}")
            with w2:
                st.markdown("### MEXC")
                st.metric("USDT", f"${m_usdt:.2f}")
                st.metric(base_coin, f"{m_mpc:.2f}")
        
        # Log
        with st.expander("📜 Log", expanded=False):
            st.info("Trade-Log wird hier angezeigt.")
        
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
            st.warning("⚠️ Markt effizient - kein profitabler Spread")
        
        # Show both directions for reference
        # Alert - only if threshold is met
        pair_alert = pair_data.get('alert_enabled', True)
        if pair_alert and alert_enabled and (trade_possible_km or trade_possible_mk):
            st.warning("🚨 Profitabel!")
            st.warning("🚨 Profitabel!")
    
    else:
        st.error("Daten nicht verfuegbar")
    
    st.divider()
    if st.button("🔄 Aktualisieren"):
        st.rerun()
    
    # =========================================================================
    # WALLET - KuCoin + MEXC side by side (wrapped in container to prevent duplicates)
    # =========================================================================
    
    with st.expander("💰 Wallets", expanded=True):
        st.subheader("💰 Wallets")
        
        col1, col2 = st.columns(2)
    
    # Extract base and quote from pair
    pair_parts = pair.split('-')
    base_coin = pair_parts[0] if len(pair_parts) > 0 else ''
    quote_coin = pair_parts[1] if len(pair_parts) > 1 else ''
    
    kucoin_key = config.get('kucoin', {}).get('api_key', '')
    kucoin_secret = config.get('kucoin', {}).get('api_secret', '')
    kucoin_pass = config.get('kucoin', {}).get('api_passphrase', '')
    mexc_key = config.get('mexc', {}).get('api_key', '')
    mexc_secret = config.get('mexc', {}).get('api_secret', '')
    
    # Fetch wallet data BEFORE displaying (so it's available for portfolio logging)
    kucoin_wallet = {'ok': False, 'balances': {}}
    mexc_wallet = {'ok': False, 'balances': {}}
    
    if kucoin_key and kucoin_secret and kucoin_pass:
        kucoin_wallet = get_kucoin_balances(kucoin_key, kucoin_secret, kucoin_pass)
    
    if mexc_key and mexc_secret:
        mexc_wallet = get_mexc_balances(mexc_key, mexc_secret)
    
    # KuCoin Wallet
    with col1:
        st.image("/app/static/kucoin_icon.png", width=40); st.text("KuCoin")
        if kucoin_wallet.get('ok'):
            bals = kucoin_wallet['balances']
            for sym in [base_coin, quote_coin]:
                if sym:
                    if sym in bals:
                        bal = bals[sym]
                        st.metric(sym, f"{bal['available']:.2f}", f"Total: {bal['total']:.2f}")
                    else:
                        st.metric(sym, "0.00", "Total: 0.00")
        else:
            st.caption("KuCoin API Keys nicht konfiguriert")
    
    # MEXC Wallet
    with col2:
        st.image("/app/static/mexc_icon.png", width=40); st.text("MEXC")
        if mexc_wallet.get('ok'):
            bals = mexc_wallet['balances']
            # Deduplicate by summing totals per coin
            unique_balances = {}
            for sym, bal in bals.items():
                if bal['total'] > 0:
                    if sym not in unique_balances:
                        unique_balances[sym] = bal
                    else:
                        # Sum available and total
                        unique_balances[sym] = {
                            'available': unique_balances[sym]['available'] + bal['available'],
                            'total': unique_balances[sym]['total'] + bal['total']
                        }
            # Show both coins for the pair (even if 0)
            for sym in [base_coin, quote_coin]:
                if sym:
                    if sym in unique_balances:
                        bal = unique_balances[sym]
                        st.metric(sym, f"{bal['available']:.2f}", f"Total: {bal['total']:.2f}")
                    else:
                        st.metric(sym, "0.00", "Total: 0.00")
        else:
            st.caption("MEXC API Keys nicht konfiguriert")

    # Portfolio logging not yet implemented
    # try:
    #     k_bal = {'MPC': 0, 'USDT': 0}
    #     m_bal = {'MPC': 0, 'USDT': 0}
    #     if kucoin_wallet.get('ok'):
    #         for sym, bal in kucoin_wallet.get('balances', {}).items():
    #             if sym in ['MPC', 'USDT']:
    #                 k_bal[sym] = bal.get('total', 0)
    #     if mexc_wallet.get('ok'):
    #         for sym, bal in mexc_wallet.get('balances', {}).items():
    #             if sym in ['MPC', 'USDT']:
    #                 m_bal[sym] = bal.get('total', 0)
    #     
    #     changed = check_and_log_portfolio(k_bal, m_bal, strategy=current_strategy, threshold=threshold_start)
    #     if changed:
    #         st.info(f"📝 Portfolio-Änderung erkannt und geloggt!")
    # except Exception as e:
    #     st.warning(f"⚠️ Portfolio-Log Fehler: {e}")

    # Auto-detect new trades from exchange APIs
    try:
        if kucoin_key and kucoin_secret and kucoin_pass:
            k_trades = get_kucoin_trades(kucoin_key, kucoin_secret, kucoin_pass, pair.replace('-', '-'), limit=5)
            if not k_trades.get('ok'):
                k_trades = {'trades': []}
        else:
            k_trades = {'trades': []}
        
        if mexc_key and mexc_secret:
            m_trades = get_mexc_trades(mexc_key, mexc_secret, pair.replace('-', ''), limit=5)
            if not m_trades.get('ok'):
                m_trades = {'trades': []}
        else:
            m_trades = {'trades': []}
        # detect_and_log_trades not yet implemented
        pass
    except Exception as e:
        st.warning(f"⚠️ Trade-Detection Fehler: {e}")

# =========================================================================
# TRADE LOG SECTION - ONLY IN DETAIL VIEW (FULL WIDTH)
# =========================================================================
        if st.session_state.selected_pair:
            # Use full width container
            with st.container():
                st.divider()
                st.subheader("📜 Trade Log")
                
                log_pair = st.session_state.selected_pair
                
                # Summary stats - full width, 8 metrics
                summary = get_trade_summary_extended(log_pair)
                
                # Summary stats as HTML table for full width control
                s = summary
                st.markdown(f"""
                <div style="display: grid; grid-template-columns: repeat(8, 1fr); gap: 0; width: 100%; font-family: sans-serif;">
                    <div style="text-align: center; padding: 12px 8px; border: 1px solid #ddd; background: #0a0a0a;">
                        <div style="color: #aaa; font-size: 11px;">SUMME TRADES</div>
                        <div style="color: white; font-size: 18px; font-weight: bold;">{s.get('total_trades', 0)}</div>
                    </div>
                    <div style="text-align: center; padding: 12px 8px; border: 1px solid #ddd; background: #0a0a0a;">
                        <div style="color: #aaa; font-size: 11px;">COMPLETED</div>
                        <div style="color: white; font-size: 18px; font-weight: bold;">{s.get('completed_trades', 0)}</div>
                    </div>
                    <div style="text-align: center; padding: 12px 8px; border: 1px solid #ddd; background: #0a0a0a;">
                        <div style="color: #aaa; font-size: 11px;">OPEN TRADES</div>
                        <div style="color: white; font-size: 18px; font-weight: bold;">{s.get('open_trades', 0)}</div>
                    </div>
                    <div style="text-align: center; padding: 12px 8px; border: 1px solid #ddd; background: #0a0a0a;">
                        <div style="color: #aaa; font-size: 11px;">TOTAL PROFIT</div>
                        <div style="color: #00ff00; font-size: 18px; font-weight: bold;">${s.get('total_profit_usdt', 0):.4f}</div>
                    </div>
                    <div style="text-align: center; padding: 12px 8px; border: 1px solid #ddd; background: #0a0a0a;">
                        <div style="color: #aaa; font-size: 11px;">TOTAL MPC</div>
                        <div style="color: #00ff00; font-size: 18px; font-weight: bold;">{s.get('total_profit_mpc', 0):.2f}</div>
                    </div>
                    <div style="text-align: center; padding: 12px 8px; border: 1px solid #ddd; background: #0a0a0a;">
                        <div style="color: #aaa; font-size: 11px;">BEST TRADE</div>
                        <div style="color: white; font-size: 18px; font-weight: bold;">${s.get('best_trade_usdt', 0):.4f}</div>
                    </div>
                    <div style="text-align: center; padding: 12px 8px; border: 1px solid #ddd; background: #0a0a0a;">
                        <div style="color: #aaa; font-size: 11px;">AVG PROFIT</div>
                        <div style="color: white; font-size: 18px; font-weight: bold;">${s.get('avg_profit_usdt', 0):.4f}</div>
                    </div>
                    <div style="text-align: center; padding: 12px 8px; border: 1px solid #ddd; background: #0a0a0a;">
                        <div style="color: #aaa; font-size: 11px;">AVG SPREAD</div>
                        <div style="color: white; font-size: 18px; font-weight: bold;">{s.get('avg_spread_pct', 0):.3f}%</div>
                    </div>
                </div>
                """, unsafe_allow_html=True)

                # Export button
                if st.button("📥 Export CSV"):
                    path = export_trades_csv(log_pair)
                    if path:
                        st.success(f"Exported!")
                    else:
                        st.info("No trades")
                
                # Trade history table
                trades = get_trades(log_pair, limit=100)
                
                if trades:
                    df = pd.DataFrame(trades)
                    df = df.iloc[::-1]  # Newest first
                    
                    # Calculate derived fields
                    def calc_profit(row):
                        try:
                            ex1 = float(row.get('ex1_value_usdt', 0) or 0)
                            ex2 = float(row.get('ex2_value_usdt', 0) or 0)
                            fees = float(row.get('ex1_fees', 0) or 0) + float(row.get('ex2_fees', 0) or 0)
                            direction = row.get('direction', '')
                            if 'K->M' in direction:
                                return (ex2 - ex1) - fees
                            else:
                                return (ex2 - ex1) - fees
                        except:
                            return 0
                    
                    def calc_gross(row):
                        try:
                            ex1 = float(row.get('ex1_value_usdt', 0) or 0)
                            ex2 = float(row.get('ex2_value_usdt', 0) or 0)
                            direction = row.get('direction', '')
                            if 'K->M' in direction:
                                return ex2 - ex1
                            else:
                                return ex2 - ex1
                        except:
                            return 0
                    
                    def calc_fees(row):
                        try:
                            return float(row.get('ex1_fees', 0) or 0) + float(row.get('ex2_fees', 0) or 0)
                        except:
                            return 0
                    
                    def short_time(ts):
                        try:
                            return datetime.fromisoformat(ts).strftime('%H:%M:%S')
                        except:
                            return ts
                    
                    def direction_icon(d):
                        return 'K→M' if 'K->M' in str(d) else 'M→K'
                    
                    def status_icon(s):
                        icons = {'FILLED': '✅', 'PARTIAL': '⚠️', 'WATCHING': '⏳', 'CANCELLED': '❌', 'FAILED': '🔴'}
                        return icons.get(s, '❓')

                    df['time'] = df['internal_ts'].apply(short_time)
                    df['id'] = df['trade_id'].str[-10:]
                    df['dir'] = df['direction'].apply(direction_icon)
                    df['qty'] = df.apply(lambda r: float(r.get('ex1_qty_filled', 0) or 0), axis=1)
                    df['buy_ex'] = df['ex1_exchange'].str[:1]
                    df['buy_price'] = df['ex1_price_avg'].apply(lambda x: f"${float(x or 0):.4f}")
                    df['sell_price'] = df['ex2_price_avg'].apply(lambda x: f"${float(x or 0):.4f}")
                    df['gross'] = df.apply(calc_gross, axis=1).apply(lambda x: f"${x:.4f}")
                    df['fees'] = df.apply(calc_fees, axis=1).apply(lambda x: f"${x:.4f}")
                    df['net'] = df.apply(calc_profit, axis=1).apply(lambda x: f"${x:.4f}")
                    df['status'] = df['limit_watch_status'].apply(status_icon) + ' ' + df['limit_watch_status'].astype(str)
                    
                    # Build display dataframe
                    display_df = df[['time', 'id', 'dir', 'qty', 'buy_ex', 'buy_price', 'sell_price', 'gross', 'fees', 'net', 'status']].copy()
                    display_df.columns = ['Time', 'ID', 'Dir', 'Qty', 'Buy', 'Buy $', 'Sell $', 'Gross', 'Fees', 'Net', 'Status']
                    
                    # Color Net column
                    def net_color(val):
                        try:
                            v = float(str(val).replace('$', ''))
                            if v > 0: return '🟢'
                            elif v < 0: return '🔴'
                            return '➖'
                        except:
                            return '➖'
                    
                    display_df['P/L'] = df.apply(calc_profit, axis=1).apply(net_color)
                    display_df = display_df[['Time', 'ID', 'Dir', 'Qty', 'Buy', 'Buy $', 'Sell $', 'Gross', 'Fees', 'Net', 'P/L', 'Status']]
                    
                    st.dataframe(display_df, use_container_width=True, hide_index=True)
                else:
                    st.info("⏳ No trades yet")
            
            st.divider()

# Auto refresh
if st.session_state.selected_pair:
    import time
    time.sleep(2)
    st.rerun()
