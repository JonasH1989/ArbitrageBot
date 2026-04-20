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
import pandas as pd

st.set_page_config(page_title="Arbitrage Bot", page_icon="📊", layout="wide")

CONFIG_FILE = 'config/config.yaml'

def load_config():
    config_path = Path(__file__).parent / CONFIG_FILE
    if config_path.exists():
        with open(config_path, 'r') as f:
            return yaml.safe_load(f) or {}
    return {'trading': {'pairs': {}, 'thresholds': {'start': 0.2, 'stop': 0.1}}}

def save_config(config):
    config_path = Path(__file__).parent / CONFIG_FILE
    config_path.parent.mkdir(parents=True, exist_ok=True)
    with open(config_path, 'w') as f:
        yaml.dump(config, f, default_flow_style=False)

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
    pairs_config = {p: {'enabled': True, 'strategy': 'usdt', 'threshold_start': 0.2, 'threshold_stop': 0.1, 'alert_enabled': True} for p in pairs_config}
thresholds = config['trading'].get('thresholds', {'start': 0.2, 'stop': 0.1})

# ============================================================================
# SIDEBAR
# ============================================================================

with st.sidebar:
    st.header("⚙️ Einstellungen")
    
    # Exchange Settings FIRST
    st.markdown("### 🔗 Exchanges")
    
    with st.expander("🥇 KuCoin", expanded=True):
        kucoin_key = st.text_input("API Key", value=config.get('kucoin', {}).get('api_key', ''), key="kucoin_key")
        kucoin_secret = st.text_input("API Secret", value=config.get('kucoin', {}).get('api_secret', ''), type="password", key="kucoin_secret")
        kucoin_pass = st.text_input("Passphrase", value=config.get('kucoin', {}).get('api_passphrase', ''), type="password", key="kucoin_pass")
        if st.button("💾 KuCoin"):
            config['kucoin'] = {'api_key': kucoin_key, 'api_secret': kucoin_secret, 'api_passphrase': kucoin_pass}
            save_config(config)
            st.success("Gespeichert!")
    
    with st.expander("🥈 MEXC", expanded=True):
        mexc_key = st.text_input("API Key", value=config.get('mexc', {}).get('api_key', ''), key="mexc_key")
        mexc_secret = st.text_input("API Secret", value=config.get('mexc', {}).get('api_secret', ''), type="password", key="mexc_secret")
        if st.button("💾 MEXC"):
            config['mexc'] = {'api_key': mexc_key, 'api_secret': mexc_secret}
            save_config(config)
            st.success("Gespeichert!")
    
    st.divider()
    
    # Alert
    st.markdown("### 🔔 Alert")
    alert_enabled = st.checkbox("Akustischer Alert", value=config.get('alert', {}).get('enabled', True))
    
    # Volume - explicit save button
    volume = st.slider("🔊 Lautstaerke", 0.0, 1.0, config.get('alert', {}).get('volume', 0.3), 0.1, key="volume_slider")
    
    if st.button("💾 Vol"):
        config.setdefault('alert', {})['volume'] = volume
        save_config(config)
        st.rerun()
    
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
            pairs_config[new_pair] = {
                'enabled': True,
                'strategy': 'usdt',
                'threshold_start': thresholds['start'],
                'threshold_stop': thresholds['stop'],
                'alert_enabled': True
            }
            config['trading']['pairs'] = pairs_config
            save_config(config)
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
                # Box with border using container
                box = st.container()
                
                with box:
                    st.markdown('<div style="border: 2px solid #888; border-radius: 10px; padding: 10px; background: #fafafa;">', unsafe_allow_html=True)
                    
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
                tile_emoji = "🟢" if is_profitable and enabled else "⬜"
                
                st.subheader(f"{tile_emoji} {pair_name}")
                
                # Prices preview
                if kucoin.get('ok') and mexc.get('ok'):
                    c1, c2 = st.columns(2)
                    with c1:
                        st.caption(f"K: ${kucoin['bid']:.6f}")
                    with c2:
                        st.caption(f"M: ${mexc['bid']:.6f}")
                
                # Buttons
                c1, c2, c3 = st.columns(3)
                with c1:
                    if st.button("📊", key=f"view_{pair_name}"):
                        st.session_state.selected_pair = pair_name
                        st.rerun()
                with c2:
                    new_state = not enabled
                    if st.button("🔄" if enabled else "▶️", key=f"tgl_{pair_name}"):
                        pairs_config[pair_name]['enabled'] = new_state
                        config['trading']['pairs'] = pairs_config
                        save_config(config)
                        st.rerun()
                with c3:
                    # Delete confirmation
                    confirm_key = f"confirm_del_{pair_name}"
                    if st.session_state.get(confirm_key, False):
                        st.warning(f"{pair_name} loeschen?")
                        c_yes, c_no = st.columns(2)
                        with c_yes:
                            if st.button("Ja", key=f"yes_{pair_name}"):
                                del pairs_config[pair_name]
                                config['trading']['pairs'] = pairs_config
                                save_config(config)
                                st.session_state[confirm_key] = False
                                st.rerun()
                        with c_no:
                            if st.button("Nein", key=f"no_{pair_name}"):
                                st.session_state[confirm_key] = False
                                st.rerun()
                    else:
                        if st.button("🗑️", key=f"del_{pair_name}"):
                            st.session_state[confirm_key] = True
                            st.rerun()
                    
                    st.markdown('</div>', unsafe_allow_html=True)

# ============================================================================
# DETAIL VIEW - ORIGINAL DASHBOARD
# ============================================================================

else:
    pair = st.session_state.selected_pair
    pair_data = pairs_config.get(pair, {})
    
    if st.button("← Zurueck zu Paaren"):
        st.session_state.selected_pair = None
        st.rerun()
    
    st.header(f"📈 {pair}")
    
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
        base_coin = pair.split('-')[0]  # e.g., "MPC"
        quote_coin = pair.split('-')[1]  # e.g., "USDT"
        
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
                # Dedupe MEXC
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
        
        # Three column layout
        c1, c2, c3 = st.columns(3)
        
        with c1:
            st.success("🥇 KuCoin")
            st.metric("Bid", f"${k_bid:.6f}", f"Vol: {kucoin['bid_size']:.0f}")
            st.metric("Ask", f"${k_ask:.6f}", f"Vol: {kucoin['ask_size']:.0f}")
        
        with c2:
            st.markdown("### ⚖️ Spread")
            
            if profit_km > 0:
                st.markdown("🟢 **KUCOIN → MEXC**")
            else:
                st.markdown("🔴 **KUCOIN → MEXC**")
            st.metric("Profit/Coin", f"${profit_km:.6f}")
            
            st.markdown("---")
            
            if profit_mk > 0:
                st.markdown("🟢 **MEXC → KUCOIN**")
            else:
                st.markdown("🔴 **MEXC → KUCOIN**")
            st.metric("Profit/Coin", f"${profit_mk:.6f}")
            
            st.divider()
            
            if profit_km > 0:
                st.metric("K→M Total", f"${profit_km * vol_km:.4f}")
            if profit_mk > 0:
                st.metric("M→K Total", f"${profit_mk * vol_mk:.4f}")
        
        with c3:
            st.success("🥈 MEXC")
            st.metric("Bid", f"${m_bid:.6f}", f"Vol: {mexc['bid_size']:.0f}")
            st.metric("Ask", f"${m_ask:.6f}", f"Vol: {mexc['ask_size']:.0f}")
        
        # =========================================================================
        # OPPORTUNITY SUMMARY - CLEAR TABLE VIEW
        # =========================================================================
        
        st.divider()
        st.subheader("🎯 Zusammenfassung")
        
        current_strategy = pair_data.get('strategy', 'usdt')
        threshold_start = pair_data.get('threshold_start', thresholds['start'])
        threshold_stop = pair_data.get('threshold_stop', thresholds['stop'])
        
        # Spread calculation (overkreuz):
        # K→M: Buy on KuCoin (Ask), Sell on MEXC (Bid) → Spread = MEXC_Bid - KuCoin_Ask
        # M→K: Buy on MEXC (Ask), Sell on KuCoin (Bid) → Spread = KuCoin_Bid - MEXC_Ask
        # 
        # Logic: Only positive spreads can be traded. Threshold filters out small spreads.
        # Threshold is in PERCENT (%), so calculate spread as percentage.
        
        # Calculate spread in % (profit relative to buy/ask price)
        spread_pct_km = (profit_km / k_ask * 100) if k_ask > 0 else 0
        spread_pct_mk = (profit_mk / m_ask * 100) if m_ask > 0 else 0
        
        # Check if spread is positive (profitable)
        km_profitable = profit_km > 0  # K→M direction
        mk_profitable = profit_mk > 0  # M→K direction
        
        # Only check threshold for positive spreads (threshold is in %)
        km_meets_threshold = km_profitable and (spread_pct_km >= threshold_start)
        mk_meets_threshold = mk_profitable and (spread_pct_mk >= threshold_start)
        
        # Trade possible only if profitable AND threshold met
        trade_possible_km = km_meets_threshold
        trade_possible_mk = mk_meets_threshold
        
        # Calculate coin profit for coins strategy
        # Profit per coin in MPC = spread_USDT / ask_price
        # coins_km = vol_km * (m_bid - k_ask) / k_ask = vol_km * profit_km / k_ask
        # coins_mk = vol_mk * (k_bid - m_ask) / m_ask = vol_mk * profit_mk / m_ask
        coins_km = (vol_km * profit_km / k_ask) if k_ask > 0 else 0
        coins_mk = (vol_mk * profit_mk / m_ask) if m_ask > 0 else 0
        
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
                    st.metric("Exchange", "🥇 KuCoin")
                    st.metric("Preis (Ask)", f"${k_ask:.6f}")
                    st.metric("Verfügbar USDT", f"${available_usdt:.2f}")
                    st.metric("Kaufbar (max)", f"{max_coins:.0f} MPC")
                else:
                    # M→K: Buy on MEXC (we have m_usdt USDT there)
                    available_usdt = m_usdt  # From wallet
                    max_coins_by_usdt = available_usdt / m_ask if m_ask > 0 else 0
                    max_coins = min(max_coins_by_usdt, vol_mk)
                    if available_usdt > 0:
                        st.metric("Exchange", "🥈 MEXC")
                        st.metric("Preis (Ask)", f"${m_ask:.6f}")
                        st.metric("Verfügbar USDT", f"${available_usdt:.2f}")
                        st.metric("Kaufbar (max)", f"{max_coins:.0f} MPC")
                    else:
                        st.metric("⚠️ Exchange", "🥈 MEXC")
                        st.metric("Preis (Ask)", f"${m_ask:.6f}")
                        st.metric("Verfügbar USDT", f"${available_usdt:.2f}")
                        st.error("KEINE USDT!")
            
            with col_sell:
                st.markdown("### 📤 VERKAUFEN")
                if show_direction == "K→M":
                    st.metric("Exchange", "🥈 MEXC")
                    st.metric("Preis (Bid)", f"${m_bid:.6f}")
                    st.metric("Max verkaufbar", f"{max_coins:.0f} MPC")
                    st.metric("Ertrag (USD)", f"${m_bid * max_coins:.4f}")
                else:
                    st.metric("Exchange", "🥇 KuCoin")
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
        with st.expander("📊 Alle Richtungen (Details)"):
            d1, d2 = st.columns(2)
            with d1:
                st.markdown("#### KUCOIN → MEXC")
                st.write(f"🥇 KuCoin **Ask:** `${k_ask:.6f}`  |  🥈 MEXC **Bid:** `${m_bid:.6f}`")
                spread_km_color = "🔴" if profit_km <= 0 else ("🟡" if spread_pct_km < threshold_start else "🟢")
                st.write(f"{spread_km_color} Spread: {spread_pct_km:+.3f}% (${profit_km:+.6f})")
                st.write(f"   Threshold: {threshold_start}%")
                if km_profitable and spread_pct_km >= threshold_start:
                    st.success(f"✅ Trade möglich!")
                elif km_profitable:
                    st.warning(f"⚠️ Positiv aber < Threshold")
                else:
                    st.error(f"❌ Negativer Spread")
                st.write(f"Volume: {vol_km:.0f} MPC")
                if current_strategy == 'usdt':
                    st.write(f"Total: ${profit_km * vol_km:+.4f}")
                else:
                    # Only show positive MPC gain for this direction
                    mpc_gain_km = coins_km if km_profitable and spread_pct_km >= threshold_start else 0
                    st.write(f"MPC-Gewinn: {mpc_gain_km:+.4f} MPC")
            with d2:
                st.markdown("#### MEXC → KUCOIN")
                st.write(f"🥈 MEXC **Ask:** `${m_ask:.6f}`  |  🥇 KuCoin **Bid:** `${k_bid:.6f}`")
                spread_mk_color = "🔴" if profit_mk <= 0 else ("🟡" if spread_pct_mk < threshold_start else "🟢")
                st.write(f"{spread_mk_color} Spread: {spread_pct_mk:+.3f}% (${profit_mk:+.6f})")
                st.write(f"   Threshold: {threshold_start}%")
                if mk_profitable and spread_pct_mk >= threshold_start:
                    st.success(f"✅ Trade möglich!")
                elif mk_profitable:
                    st.warning(f"⚠️ Positiv aber < Threshold")
                else:
                    st.error(f"❌ Negativer Spread")
                st.write(f"Volume: {vol_mk:.0f} MPC")
                if current_strategy == 'usdt':
                    st.write(f"Total: ${profit_mk * vol_mk:+.4f}")
                else:
                    # Only show positive MPC gain for this direction
                    mpc_gain_mk = coins_mk if mk_profitable and spread_pct_mk >= threshold_start else 0
                    st.write(f"MPC-Gewinn: {mpc_gain_mk:+.4f} MPC")
        
        # =========================================================================
        # PAIR SETTINGS (compact at bottom)
        # =========================================================================
        
        st.divider()
        st.subheader("⚙️ Paar-Einstellungen")
        
        s1, s2, s3, s4, s5 = st.columns([1, 1, 1, 1, 1])
        
        with s1:
            ts = pair_data.get('threshold_start', thresholds['start'])
            ts_new = st.number_input("Start %", 0.0, 50.0, ts, 0.05, key=f"pts_{pair}")
            if ts_new != ts:
                pairs_config[pair]['threshold_start'] = ts_new
                config['trading']['pairs'] = pairs_config
                save_config(config)
        
        with s2:
            tss = pair_data.get('threshold_stop', thresholds['stop'])
            tss_new = st.number_input("Stop %", 0.0, max(0.1, ts_new), tss, 0.05, key=f"ptss_{pair}")
            if tss_new != tss:
                pairs_config[pair]['threshold_stop'] = tss_new
                config['trading']['pairs'] = pairs_config
                save_config(config)
        
        with s3:
            ae = pair_data.get('alert_enabled', True)
            ae_new = st.checkbox("🔔 Alert", value=ae, key=f"pae_{pair}")
            if ae_new != ae:
                pairs_config[pair]['alert_enabled'] = ae_new
                config['trading']['pairs'] = pairs_config
                save_config(config)
        
        with s4:
            strat = pair_data.get('strategy', 'usdt')
            strat_idx = 0 if strat == 'usdt' else 1
            new_strat = st.radio("Strategie", ["💰 USDT", "🪙 Coins"], index=strat_idx, key=f"pstr_{pair}")
            new_strat_val = 'usdt' if new_strat == "💰 USDT" else 'coins'
            if new_strat_val != strat:
                pairs_config[pair]['strategy'] = new_strat_val
                config['trading']['pairs'] = pairs_config
                save_config(config)
        
        with s5:
            enabled = pair_data.get('enabled', True)
            en_new = st.checkbox("🟢 Aktiv", value=enabled, key=f"pen_{pair}")
            if en_new != enabled:
                pairs_config[pair]['enabled'] = en_new
                config['trading']['pairs'] = pairs_config
                save_config(config)
        
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
    # WALLET - KuCoin + MEXC side by side
    # =========================================================================
    
    st.divider()
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
    
    # KuCoin Wallet
    with col1:
        st.markdown("#### 🥇 KuCoin")
        if kucoin_key and kucoin_secret and kucoin_pass:
            kucoin_wallet = get_kucoin_balances(kucoin_key, kucoin_secret, kucoin_pass)
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
                err = kucoin_wallet.get('error', 'Unbekannt')
                st.error(f"KuCoin: {err}")
        else:
            st.caption("KuCoin API Keys nicht konfiguriert")
    
    # MEXC Wallet
    with col2:
        st.markdown("#### 🥈 MEXC")
        if mexc_key and mexc_secret:
            mexc_wallet = get_mexc_balances(mexc_key, mexc_secret)
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
                err = mexc_wallet.get('error', 'Unbekannt')
                st.error(f"MEXC: {err}")
        else:
            st.caption("MEXC API Keys nicht konfiguriert")

# Auto refresh
if st.session_state.selected_pair:
    import time
    time.sleep(2)
    st.rerun()
