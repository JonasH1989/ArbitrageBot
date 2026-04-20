#!/usr/bin/env python3
"""
Arbitrage Bot Dashboard - Single Chart Design
KuCoin (green) vs MEXC (blue) | Spread Zone | Delta Column
"""

import streamlit as st
import streamlit.components.v1 as components
import requests
import yaml
from pathlib import Path
from datetime import datetime
import pandas as pd

st.set_page_config(
    page_title="Arbitrage Bot",
    page_icon="📊",
    layout="wide"
)

# ============================================================================
# Configuration
# ============================================================================

CONFIG_FILE = 'config/config.yaml'

def load_config():
    config_path = Path(__file__).parent / CONFIG_FILE
    if config_path.exists():
        with open(config_path, 'r') as f:
            return yaml.safe_load(f) or {}
    return {
        'kucoin': {},
        'mexc': {},
        'trading': {
            'thresholds': {'start': 0.2, 'stop': 0.1},
            'pairs': ['MPC-USDT'],
            'strategy': 'usdt'
        }
    }

def save_config(config):
    config_path = Path(__file__).parent / CONFIG_FILE
    config_path.parent.mkdir(parents=True, exist_ok=True)
    with open(config_path, 'w') as f:
        yaml.dump(config, f, default_flow_style=False)

# ============================================================================
# Exchange APIs
# ============================================================================

def get_kucoin_orderbook(pair: str):
    try:
        resp = requests.get(
            "https://api.kucoin.com/api/v1/market/orderbook/level1",
            params={"symbol": pair},
            timeout=5
        )
        if resp.status_code == 200:
            data = resp.json()
            if data.get('code') == '200000':
                d = data.get('data') or {}
                return {
                    'bid': float(d.get('bestBid', 0) or 0),
                    'bid_size': float(d.get('bestBidSize', 0) or 0),
                    'ask': float(d.get('bestAsk', 0) or 0),
                    'ask_size': float(d.get('bestAskSize', 0) or 0),
                    'ok': True
                }
    except:
        pass
    return {'ok': False}

def get_mexc_orderbook(pair: str):
    try:
        symbol = pair.replace('-', '')
        resp = requests.get(
            "https://api.mexc.com/api/v3/ticker/bookTicker",
            params={"symbol": symbol},
            timeout=5
        )
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
    except:
        pass
    return {'ok': False}

# ============================================================================
# Session State
# ============================================================================

if 'price_history' not in st.session_state:
    st.session_state.price_history = []

if 'max_points' not in st.session_state:
    st.session_state.max_points = 60

# ============================================================================
# Header
# ============================================================================

st.title("📊 Arbitrage Bot")

# Sidebar
with st.sidebar:
    st.header("⚙️ Konfiguration")
    config = load_config()
    
    pair = st.selectbox(
        "Aktives Pair",
        ['MPC-USDT', 'BTC-USDT', 'ETH-USDT', 'BNB-USDT', 'SOL-USDT', 
         'XRP-USDT', 'ADA-USDT', 'DOGE-USDT', 'AVAX-USDT', 'DOT-USDT'],
        index=0,
        key="pair_select"
    )
    
    if st.button("💾 Pair", key="save_pair"):
        config['trading']['pairs'] = [pair]
        save_config(config)
        st.session_state.price_history = []
        st.rerun()
    
    st.divider()
    
    thresholds = config['trading'].get('thresholds', {'start': 0.2, 'stop': 0.1})
    
    # Initialize session state
    if 'threshold_start' not in st.session_state:
        st.session_state.threshold_start = thresholds['start']
    if 'threshold_stop' not in st.session_state:
        st.session_state.threshold_stop = thresholds['stop']
    
    st.number_input(
        "Start Threshold %", 0.0, 50.0, thresholds['start'], 0.05,
        key="threshold_start"
    )
    
    # Stop is limited by start value
    max_stop = max(0.1, st.session_state.threshold_start)
    st.number_input(
        "Stop Threshold %", 0.0, max_stop, st.session_state.threshold_stop, 0.05,
        key="threshold_stop"
    )
    
    start_t = st.session_state.threshold_start
    stop_t = st.session_state.threshold_stop
    
    if st.button("💾 Thresholds"):
        config['trading']['thresholds'] = {'start': start_t, 'stop': stop_t}
        save_config(config)
        st.rerun()
    
    st.divider()
    
    # Strategy Mode - read from config to set correct default
    saved_strategy = config.get('trading', {}).get('strategy', 'usdt')
    strategy_index = 0 if saved_strategy == 'usdt' else 1
    
    st.markdown("### Strategie")
    strategy = st.radio(
        "Was willst du erreichen?",
        ["💰 USDT Gewinn", "🪙 Coin vermehren"],
        index=strategy_index,
        horizontal=True
    )
    
    if strategy == "💰 USDT Gewinn":
        config['trading']['strategy'] = 'usdt'
    else:
        config['trading']['strategy'] = 'coins'
    
    if st.button("💾 Strategie"):
        save_config(config)
        st.rerun()
    
    st.divider()
    
    # Alert Settings
    st.markdown("### 🔔 Alert")
    
    # Test button using Web Audio API - 3 beeps
    if st.button("▶️ Test Sound"):
        volume = st.session_state.get('alert_volume', 0.3)
        components.html(f"""
        <script>
            try {{
                var audioCtx = new (window.AudioContext || window.webkitAudioContext)();
                function playBeep() {{
                    var osc = audioCtx.createOscillator();
                    var gain = audioCtx.createGain();
                    osc.connect(gain);
                    gain.connect(audioCtx.destination);
                    osc.frequency.value = 880;
                    osc.type = 'sine';
                    gain.gain.value = {volume};
                    osc.start();
                    osc.stop(audioCtx.currentTime + 0.15);
                }}
                playBeep();
                setTimeout(playBeep, 200);
                setTimeout(playBeep, 400);
            }} catch(e) {{
                console.log('Audio error:', e);
            }}
        </script>
        """, height=0, width=0)
    
    st.caption("Hinweis: Browser muss Sound erlauben!")
    alert_enabled = st.checkbox("Akustischer Alert bei Profit", value=True)
    
    # Volume slider
    volume = st.slider("🔊 Lautstaerke", 0.0, 1.0, 0.3, 0.1)
    st.session_state.alert_volume = volume
    
    st.divider()
    
    st.metric("📊 Datenpunkte", len(st.session_state.price_history))
    
    if st.button("🗑️ Clear", key="clear_btn"):
        st.session_state.price_history = []
        st.rerun()

# ============================================================================
# Main Content
# ============================================================================

st.header(f"📈 {pair}")

# Fetch data
kucoin = get_kucoin_orderbook(pair)
mexc = get_mexc_orderbook(pair)

# Collect data point
ts = datetime.now()
data_point = {
    'time': ts,
    'kucoin_bid': kucoin.get('bid') if kucoin.get('ok') else None,
    'kucoin_ask': kucoin.get('ask') if kucoin.get('ok') else None,
    'kucoin_bid_size': kucoin.get('bid_size') if kucoin.get('ok') else None,
    'kucoin_ask_size': kucoin.get('ask_size') if kucoin.get('ok') else None,
    'mexc_bid': mexc.get('bid') if mexc.get('ok') else None,
    'mexc_ask': mexc.get('ask') if mexc.get('ok') else None,
    'mexc_bid_size': mexc.get('bid_size') if mexc.get('ok') else None,
    'mexc_ask_size': mexc.get('ask_size') if mexc.get('ok') else None,
}

# Calculate spreads (always positive = absolute value)
if kucoin.get('ok') and mexc.get('ok') and kucoin['ask'] > 0 and mexc['bid'] > 0:
    spread_km_raw = ((mexc['bid'] - kucoin['ask']) / kucoin['ask']) * 100
    data_point['spread_kucoin_mexc'] = abs(spread_km_raw)
    data_point['volume_kucoin_mexc'] = min(kucoin['ask_size'], mexc['bid_size'])
else:
    data_point['spread_kucoin_mexc'] = None
    data_point['volume_kucoin_mexc'] = None

if kucoin.get('ok') and mexc.get('ok') and mexc['ask'] > 0 and kucoin['bid'] > 0:
    spread_mk_raw = ((kucoin['bid'] - mexc['ask']) / mexc['ask']) * 100
    data_point['spread_mexc_kucoin'] = abs(spread_mk_raw)
    data_point['volume_mexc_kucoin'] = min(mexc['ask_size'], kucoin['bid_size'])
else:
    data_point['spread_mexc_kucoin'] = None
    data_point['volume_mexc_kucoin'] = None

st.session_state.price_history.append(data_point)

if len(st.session_state.price_history) > st.session_state.max_points:
    st.session_state.price_history.pop(0)

# Convert to DataFrame
df = pd.DataFrame(st.session_state.price_history)

if len(df) >= 2:
    df = df.set_index('time')
    
    # =========================================================================
    # SINGLE CHART: KuCoin vs MEXC with Spread Zone
    # =========================================================================
    
    st.subheader("💰 Preisverlauf & Spread Zone")
    
    # Prepare chart data
    chart_data = pd.DataFrame(index=df.index)
    chart_data['KuCoin Bid'] = df['kucoin_bid']
    chart_data['KuCoin Ask'] = df['kucoin_ask']
    chart_data['MEXC Bid'] = df['mexc_bid']
    chart_data['MEXC Ask'] = df['mexc_ask']
    
    # Display chart
    st.line_chart(chart_data[['KuCoin Bid', 'KuCoin Ask', 'MEXC Bid', 'MEXC Ask']].dropna(), height=300)
    
    # =========================================================================
    # THREE COLUMN LAYOUT: KuCoin | Delta | MEXC
    # =========================================================================
    
    st.subheader("📋 Orderbook Vergleich")
    
    col1, col2, col3 = st.columns([1, 1, 1])
    
    # KUCOIN (LEFT)
    with col1:
        if kucoin.get('ok'):
            st.success("🥇 KuCoin")
            st.metric("Bid", f"${kucoin['bid']:.6f}", f"Vol: {kucoin['bid_size']:.0f}")
            st.metric("Ask", f"${kucoin['ask']:.6f}", f"Vol: {kucoin['ask_size']:.0f}")
            
            # Spread within KuCoin
            kucoin_spread = ((kucoin['ask'] - kucoin['bid']) / kucoin['bid']) * 100 if kucoin['bid'] > 0 else 0
            st.caption(f"Innerer Spread: {kucoin_spread:.4f}%")
        else:
            st.error("❌ KuCoin nicht verfügbar")
    
    # DELTA (MIDDLE)
    with col2:
        st.markdown("**⚖️ Profit pro Trade**")
        
        if kucoin.get('ok') and mexc.get('ok'):
            # Prices
            k_ask = kucoin['ask']
            k_bid = kucoin['bid']
            m_ask = mexc['ask']
            m_bid = mexc['bid']
            
            # Profit calculations
            profit_km = m_bid - k_ask if k_ask > 0 and m_bid > 0 else 0
            profit_km_pct = (profit_km / k_ask) * 100 if k_ask > 0 else 0
            profit_mk = k_bid - m_ask if m_ask > 0 and k_bid > 0 else 0
            profit_mk_pct = (profit_mk / m_ask) * 100 if m_ask > 0 else 0
            
            # KuCoin -> MEXC
            if profit_km > 0:
                st.markdown("🟢 **KUCOIN → MEXC**")
            else:
                st.markdown("🔴 **KUCOIN → MEXC**")
            st.metric("Profit/Coin", f"${profit_km:.6f}")
            
            st.markdown("---")
            
            # MEXC -> KuCoin
            if profit_mk > 0:
                st.markdown("🟢 **MEXC → KUCOIN**")
            else:
                st.markdown("🔴 **MEXC → KUCOIN**")
            st.metric("Profit/Coin", f"${profit_mk:.6f}")
            
            st.divider()
            
            # Available Volume
            vol_km = data_point.get('volume_kucoin_mexc', 0) or 0
            vol_mk = data_point.get('volume_mexc_kucoin', 0) or 0
            
            if profit_km > 0:
                total_km = profit_km * vol_km
                st.markdown(f"📦 Vol: {vol_km:.0f} | **Total: ${total_km:.2f}**")
            if profit_mk > 0:
                total_mk = profit_mk * vol_mk
                st.markdown(f"📦 Vol: {vol_mk:.0f} | **Total: ${total_mk:.2f}**")
        else:
            st.warning("⏳ Warte auf Daten...")
    
    # MEXC (RIGHT)
    with col3:
        if mexc.get('ok'):
            st.success("🥈 MEXC")
            st.metric("Bid", f"${mexc['bid']:.6f}", f"Vol: {mexc['bid_size']:.0f}")
            st.metric("Ask", f"${mexc['ask']:.6f}", f"Vol: {mexc['ask_size']:.0f}")
            
            # Spread within MEXC
            mexc_spread = ((mexc['ask'] - mexc['bid']) / mexc['bid']) * 100 if mexc['bid'] > 0 else 0
            st.caption(f"Innerer Spread: {mexc_spread:.4f}%")
        else:
            st.error("❌ MEXC nicht verfügbar")
    
    # =========================================================================
    # OPPORTUNITY SUMMARY with Strategy
    # =========================================================================
    
    st.subheader("🎯 Zusammenfassung")
    
    current_strategy = config.get('trading', {}).get('strategy', 'usdt')
    
    if kucoin.get('ok') and mexc.get('ok'):
        # Prices
        k_ask = kucoin['ask']
        k_bid = kucoin['bid']
        m_ask = mexc['ask']
        m_bid = mexc['bid']
        
        vol_km = data_point.get('volume_kucoin_mexc', 0) or 0
        vol_mk = data_point.get('volume_mexc_kucoin', 0) or 0
        
        col_left, col_right = st.columns(2)
        
        if current_strategy == 'usdt':
            # USDT Gewinn: Kaufe X Coins guenstig, verkaufe X Coins teurer
            profit_km = m_bid - k_ask if k_ask > 0 and m_bid > 0 else 0
            profit_mk = k_bid - m_ask if m_ask > 0 and k_bid > 0 else 0
            total_km = profit_km * vol_km
            total_mk = profit_mk * vol_mk
            
            with col_left:
                st.markdown("### KUCOIN → MEXC")
                if profit_km > 0:
                    st.metric("Status", "✅ PROFITABLE", f"${total_km:.4f}")
                else:
                    st.metric("Status", "❌ Verlust", f"${total_km:.4f}")
                st.metric("Kauf (K-Ask)", f"${k_ask:.6f}")
                st.metric("Verkauf (M-Bid)", f"${m_bid:.6f}")
                st.metric("Vol / Gewinn", f"{vol_km:.0f} / ${total_km:.4f}")
            
            with col_right:
                st.markdown("### MEXC → KUCOIN")
                if profit_mk > 0:
                    st.metric("Status", "✅ PROFITABLE", f"${total_mk:.4f}")
                else:
                    st.metric("Status", "❌ Verlust", f"${total_mk:.4f}")
                st.metric("Kauf (M-Ask)", f"${m_ask:.6f}")
                st.metric("Verkauf (K-Bid)", f"${k_bid:.6f}")
                st.metric("Vol / Gewinn", f"{vol_mk:.0f} / ${total_mk:.4f}")
        
        else:
            # Coin vermehren: Verkaufe X Coins, kaufe mit Erloes mehr Coins
            coins_from_km = (vol_km * k_bid) / m_ask if m_ask > 0 and k_bid > 0 else 0
            coins_net_km = coins_from_km - vol_km
            coins_from_mk = (vol_mk * m_bid) / k_ask if k_ask > 0 and m_bid > 0 else 0
            coins_net_mk = coins_from_mk - vol_mk
            
            with col_left:
                st.markdown("### KUCOIN → MEXC")
                if coins_net_km > 0:
                    st.metric("Status", "✅ Coins+", f"{coins_net_km:.0f}")
                else:
                    st.metric("Status", "❌ Coins-", f"{coins_net_km:.0f}")
                st.metric("Verkauf (K-Bid)", f"${k_bid:.6f}")
                st.metric("Kauf (M-Ask)", f"${m_ask:.6f}")
                st.metric("Coin-Gewinn", f"{coins_net_km:+.0f}")
            
            with col_right:
                st.markdown("### MEXC → KUCOIN")
                if coins_net_mk > 0:
                    st.metric("Status", "✅ Coins+", f"{coins_net_mk:.0f}")
                else:
                    st.metric("Status", "❌ Coins-", f"{coins_net_mk:.0f}")
                st.metric("Verkauf (M-Bid)", f"${m_bid:.6f}")
                st.metric("Kauf (K-Ask)", f"${k_ask:.6f}")
                st.metric("Coin-Gewinn", f"{coins_net_mk:+.0f}")
        
        # Status message
        if current_strategy == 'usdt':
            if profit_km <= 0 and profit_mk <= 0:
                st.warning("⚠️ Markt effizient - kein profitabler Spread")
        else:
            if coins_net_km <= 0 and coins_net_mk <= 0:
                st.warning("⚠️ Kein Coin-Gewinn moeglich")

st.caption(f"Stand: {datetime.now().strftime('%H:%M:%S')}")

# Check for profitable opportunity and play alert
if kucoin.get('ok') and mexc.get('ok') and alert_enabled:
    current_strategy = config.get('trading', {}).get('strategy', 'usdt')
    
    # Calculate profits for alert check
    k_ask = kucoin.get('ask', 0)
    k_bid = kucoin.get('bid', 0)
    m_ask = mexc.get('ask', 0)
    m_bid = mexc.get('bid', 0)
    vol_km = data_point.get('volume_kucoin_mexc', 0) or 0
    vol_mk = data_point.get('volume_mexc_kucoin', 0) or 0
    
    profit_km = m_bid - k_ask if k_ask > 0 and m_bid > 0 else 0
    profit_mk = k_bid - m_ask if m_ask > 0 and k_bid > 0 else 0
    coins_from_km = (vol_km * k_bid) / m_ask if m_ask > 0 and k_bid > 0 else 0
    coins_net_km = coins_from_km - vol_km
    coins_from_mk = (vol_mk * m_bid) / k_ask if k_ask > 0 and m_bid > 0 else 0
    coins_net_mk = coins_from_mk - vol_mk
    
    is_profitable = False
    
    if current_strategy == 'usdt':
        if profit_km > 0 or profit_mk > 0:
            is_profitable = True
    else:
        if coins_net_km > 0 or coins_net_mk > 0:
            is_profitable = True
    
    if is_profitable:
        # Play alert sound using Web Audio API - 3 beeps
        volume = st.session_state.get('alert_volume', 0.3)
        beep_script = f"""
        <script>
            try {{
                var audioCtx = new (window.AudioContext || window.webkitAudioContext)();
                function playBeep() {{
                    var osc = audioCtx.createOscillator();
                    var gain = audioCtx.createGain();
                    osc.connect(gain);
                    gain.connect(audioCtx.destination);
                    osc.frequency.value = 880;
                    osc.type = 'sine';
                    gain.gain.value = {volume};
                    osc.start();
                    osc.stop(audioCtx.currentTime + 0.15);
                }}
                // Play 3 beeps
                playBeep();
                setTimeout(playBeep, 200);
                setTimeout(playBeep, 400);
            }} catch(e) {{
                console.log('Alert audio error:', e);
            }}
        </script>
        """
        components.html(beep_script, height=0, width=0)

# Auto refresh
import time
time.sleep(1)
st.rerun()
