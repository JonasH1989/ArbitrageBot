#!/usr/bin/env python3
"""
Arbitrage Bot Dashboard - Multi-Pair + Original Detail View
"""
import streamlit as st
import streamlit.components.v1 as components
import requests
import yaml
import re
from datetime import datetime
from pathlib import Path
import os
import pandas as pd
import io
import io
from trade_logger import *
import sys
from settings_sync import get_setting, set_setting, get_pair_settings, set_pair_settings, get_alert_settings, set_alert_settings, get_api_keys, set_api_keys, get_all_pairs, add_pair, remove_pair, get_log_level, set_log_level
import base64
# =============================================================================
# TRADE-LOG ROW HELPERS (added 2026-10-19 — dashboard counter fix)
# =============================================================================
# TRADE_ROW_SUFFIXES wird via 'from trade_logger import *' importiert.
#
# Counter und Summen MÜSSEN nach Suffix filtern, sonst wird jeder Fill als
# eigener Trade gezählt und ex2_value_usdt mehrfach summiert.
# =============================================================================
def is_main_trade_row(row: dict) -> bool:
    """Return True if this row is a Main trade row (no fill/sum suffix)."""
    tid = (row.get('trade_id') or '').strip()
    if not tid:
        return False
    # Use regex to match ANY number of fills (_ex1p1, _ex1p2, ..., _ex1p99)
    # and the summary row (_ex2sum). The old fixed tuple only went to _ex1p5.
    return not bool(TRADE_ROW_SUFFIX_RE.search(tid))
def is_ex2sum_row(row: dict) -> bool:
    """Return True if this row is an _ex2sum row (contains profit values)."""
    return (row.get('trade_id') or '').endswith('_ex2sum')
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
# Bot cache base URL — sichtbar in Sidebar für Diagnose
BOT_CACHE_URL = 'http://arbitrage-bot:8505'
st.sidebar.info(f"🔗 Bot-Cache: {BOT_CACHE_URL}")
# ============================================================================
# Debug-Helper: st.rerun() mit Sidebar-Toggle (für Full-Reload-Eingrenzung)
# ============================================================================
def _safe_rerun(key: str):
    """st.rerun() wrapped — wird durch Sidebar-Checkbox dbg_rerun_<key> deaktiviert.
    Default True → verhält sich wie st.rerun() wenn keine Checkbox aktiv ist."""
    if st.session_state.get(f'dbg_rerun_{key}', True):
        st.rerun()
# ============================================================================
# Helper: Fetch Level 2 orderbook from MEXC + KuCoin (public APIs, no auth)
# Used by orderbook/spread render. Extracted for fragment-wrapping.
# ============================================================================
def fetch_l2_orderbook(symbol_mexc="MPCUSDT", symbol_kucoin="MPC-USDT"):
    """Fetch L2 orderbook from MEXC depth (limit=20) and KuCoin level2_20.
    Returns (mexc_bids, mexc_asks, kucoin_bids, kucoin_asks) — lists of (price, qty) tuples.
    Empty lists on any failure (timeout, bad JSON, non-200)."""
    try:
        mexc_ob_resp = requests.get(f"https://api.mexc.com/api/v3/depth?symbol={symbol_mexc}&limit=20", timeout=5)
        mexc_ob = mexc_ob_resp.json() if mexc_ob_resp.status_code == 200 else {'bids': [], 'asks': []}
        mexc_bids_l2 = [(float(p), float(v)) for p, v in mexc_ob.get('bids', [])[:20]]
        mexc_asks_l2 = [(float(p), float(v)) for p, v in mexc_ob.get('asks', [])[:20]]
    except:
        mexc_bids_l2, mexc_asks_l2 = [], []
    try:
        kucoin_ob_resp = requests.get(f"https://api.kucoin.com/api/v1/market/orderbook/level2_20?symbol={symbol_kucoin}", timeout=5)
        kucoin_ob = kucoin_ob_resp.json() if kucoin_ob_resp.status_code == 200 else {}
        kucoin_bids_l2 = [(float(p), float(v)) for p, v in kucoin_ob.get('data', {}).get('bids', [])[:20]]
        kucoin_asks_l2 = [(float(p), float(v)) for p, v in kucoin_ob.get('data', {}).get('asks', [])[:20]]
    except:
        kucoin_bids_l2, kucoin_asks_l2 = [], []
    return mexc_bids_l2, mexc_asks_l2, kucoin_bids_l2, kucoin_asks_l2
# ============================================================================
# Fragment: Orderbook + Spread render (syncron, eigene Update-Cycle)
# Fetches fresh L2 data every 2s, computes spreads from the SAME snapshot,
# renders the orderbook tables. This guarantees Orderbook and Spread
# values always come from the same HTTP response (no skew).
# ============================================================================
@st.fragment(run_every=1)
def render_orderbook_spread_view(threshold_start=1.0):
    mexc_bids_l2, mexc_asks_l2, kucoin_bids_l2, kucoin_asks_l2 = fetch_l2_orderbook()
    with st.expander("📋 Orderbook", expanded=False):
        if not (mexc_bids_l2 and mexc_asks_l2 and kucoin_bids_l2 and kucoin_asks_l2):
            st.info("Orderbook Daten nicht vollständig verfügbar")
            return
        # Syncron: spread calc uses same L2 snapshot as the table below
        k_ask = kucoin_asks_l2[0][0]
        k_bid = kucoin_bids_l2[0][0]
        m_ask = mexc_asks_l2[0][0]
        m_bid = mexc_bids_l2[0][0]
        spread_pct_km = (m_bid - k_ask) / k_ask * 100 if k_ask > 0 else 0
        spread_pct_mk = (k_bid - m_ask) / m_ask * 100 if m_ask > 0 else 0
        mexc_bids = mexc_bids_l2
        mexc_asks = mexc_asks_l2
        kucoin_bids = kucoin_bids_l2
        kucoin_asks = kucoin_asks_l2
        # Bot State aus Cache (live via Fragment run_every=2)
        try:
            _bs = requests.get(f"{BOT_CACHE_URL}/state", timeout=2).json()
        except:
            _bs = {}
        _se = {'WAITING': '🟡', 'RUNNING': '🟢'}.get(_bs.get('state', '?'), '⚪')
        _he = '🟢' if _bs.get('hysteresis_armed') else '⚪'
        _pe = '🟢' if _bs.get('pair_enabled') else '🔴'
        st.markdown(f"**Legende:** 🟢 Threshold erfüllt | 🟡 Positiv aber < Threshold | 🔴 Negativ  |  **State:** {_se} {_bs.get('state', '?')}  |  Hyst: {_he}  |  Pair: {_pe}")
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
                st.markdown(f"<div style='background-color: {bg}; padding: 2px 8px; border-radius: 4px; margin: 1px 0;'><span style='color: #00c853; font-weight: bold;'>${k_bid_p:.6f}</span> <span style='color: #00c853;'>|</span> <span style='color: #00c853;'>{k_bid_v:.0f} MPC</span> <span style='color: #888; margin-left: 10px;'>{pct:+.3f}%</span></div>", unsafe_allow_html=True)
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
# Fragment: BESTE RICHTUNG — updates alle 2s nach Trade
# Selbst-enthaltend: holt Orderbook + Balances frisch vom Bot-Cache.
# Ersetzt den main-flow Block damit die Anzeige nach Trades updated.
# ============================================================================
@st.fragment(run_every=1)
def render_best_direction():
    try:
        # Fresh orderbook
        mexc_bids, mexc_asks, kucoin_bids, kucoin_asks = fetch_l2_orderbook()
        if not (mexc_bids and mexc_asks and kucoin_bids and kucoin_asks):
            return
        # Fresh balances from bot cache
        try:
            bal = requests.get(f"{BOT_CACHE_URL}/balances", timeout=2).json()
            k_usdt = float(bal.get('kucoin', {}).get('USDT', {}).get('free', 0))
            m_usdt = float(bal.get('mexc', {}).get('USDT', {}).get('free', 0))
        except Exception:
            k_usdt = m_usdt = 0
        # Config from session_state (written by main flow)
        cfg = st.session_state.get('bot_pair_config', {})
        current_strategy = cfg.get('strategy', 'coins')
        threshold_start = cfg.get('threshold_start', 1.9)
        # Calculate
        k_ask, k_bid = kucoin_asks[0][0], kucoin_bids[0][0]
        m_ask, m_bid = mexc_asks[0][0], mexc_bids[0][0]
        profit_km = m_bid - k_ask
        profit_mk = k_bid - m_ask
        spread_pct_km = (profit_km / k_ask * 100) if k_ask > 0 else 0
        spread_pct_mk = (profit_mk / m_ask * 100) if m_ask > 0 else 0
        # Multi-level volume (L1+L2+L3)
        kucoin_vol = sum(q for _, q in kucoin_asks[:3])
        mexc_vol = sum(q for _, q in mexc_asks[:3])
        vol_km = min(kucoin_vol, mexc_vol)
        vol_mk = min(mexc_vol, kucoin_vol)
        # Trade possible?
        km_ok = profit_km > 0 and spread_pct_km >= threshold_start
        mk_ok = profit_mk > 0 and spread_pct_mk >= threshold_start
        # Coins
        coins_km = (vol_km * profit_km / k_ask) if k_ask > 0 else 0
        coins_mk = (vol_mk * profit_mk / m_ask) if m_ask > 0 else 0
        if (km_ok or mk_ok) and max(spread_pct_km, spread_pct_mk) >= threshold_start:
            if current_strategy == 'usdt':
                pkm_total = profit_km * vol_km
                pmk_total = profit_mk * vol_mk
                show_direction = "K→M" if pkm_total >= pmk_total else "M→K"
                show_volume = vol_km if show_direction == "K→M" else vol_mk
                show_profit_txt = f"${abs(profit_km if show_direction == 'K→M' else profit_mk):.6f}"
            else:
                show_direction = "K→M" if coins_km >= coins_mk else "M→K"
                show_volume = vol_km if show_direction == "K→M" else vol_mk
                show_profit_txt = f"{abs(coins_km if show_direction == 'K→M' else coins_mk):.2f} MPC"
            st.success(f"🟢 **BESTE RICHTUNG: {show_direction}** | Gewinn: {show_profit_txt} | Vol: {show_volume:.0f} Coins")
            col_buy, col_sell, col_profit = st.columns(3)
            with col_buy:
                st.markdown("### 📥 KAUFEN")
                if show_direction == "K→M":
                    avail = k_usdt
                    max_by_usdt = avail / k_ask if k_ask > 0 else 0
                    max_coins = min(max_by_usdt, vol_km)
                    st.metric("Exchange", "KuCoin")
                    st.metric("Preis (Ask)", f"${k_ask:.6f}")
                    st.metric("Verfügbar USDT", f"${avail:.2f}")
                    st.metric("Kaufbar (max)", f"{max_coins:.0f} MPC")
                else:
                    avail = m_usdt
                    max_by_usdt = avail / m_ask if m_ask > 0 else 0
                    max_coins = min(max_by_usdt, vol_mk)
                    if avail > 0:
                        st.metric("Exchange", "MEXC")
                        st.metric("Preis (Ask)", f"${m_ask:.6f}")
                        st.metric("Verfügbar USDT", f"${avail:.2f}")
                        st.metric("Kaufbar (max)", f"{max_coins:.0f} MPC")
                    else:
                        st.metric("Exchange", "⚠️ MEXC")
                        st.metric("Preis (Ask)", f"${m_ask:.6f}")
                        st.metric("Verfügbar USDT", f"${avail:.2f}")
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
    except Exception as e:
        st.error(f"Fragment-Fehler: {e}")
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
def get_kucoin_balances(api_key: str, api_secret: str, passphrase: str, wallet_type: str = None):
    """Get KuCoin account balances filtered by wallet type.
    
    Args:
        wallet_type: Specific wallet type ('trade', 'main', 'margin', 'otc', 'pool').
                     If None, uses 'kucoin.trading_wallet' setting or 'trade' by default.
    """
    try:
        import hashlib
        import hmac
        import base64
        import time
        
        # Resolve wallet type
        if wallet_type is None:
            wallet_type = get_setting('kucoin.trading_wallet', 'trade')
        
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
                    acc_type = acc.get('type', '')
                    # Filter by wallet type
                    if acc_type != wallet_type:
                        continue
                    currency = acc.get('currency', '')
                    available = float(acc.get('available', 0) or 0)
                    total = float(acc.get('balance', 0) or 0)
                    if currency and total > 0:
                        if currency not in balances:
                            balances[currency] = {'available': available, 'total': total}
                        else:
                            balances[currency]['available'] += available
                            balances[currency]['total'] += total
                return {'ok': True, 'balances': balances, 'wallet_type': wallet_type}
            else:
                return {'ok': False, 'balances': {}, 'error': data.get('msg', 'Unknown error')}
        else:
            return {'ok': False, 'balances': {}, 'error': f'HTTP {resp.status_code}'}
    except Exception as e:
        return {'ok': False, 'balances': {}, 'error': str(e)}
def get_kucoin_all_wallets_detailed(api_key: str, api_secret: str, passphrase: str):
    """Get KuCoin wallets with type breakdown for wallet selection UI."""
    try:
        import hashlib
        import hmac
        import base64
        import time
        
        now = int(time.time() * 1000)
        method = 'GET'
        path = '/api/v1/accounts'
        body = ''
        
        # Signature v1 (same as dashboard uses)
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
                wallets = {}  # {currency: {wallet_type: {available, total}}}
                for acc in data.get('data', []):
                    currency = acc.get('currency', '')
                    acc_type = acc.get('type', '')
                    available = float(acc.get('available', 0) or 0)
                    total = float(acc.get('balance', 0) or 0)
                    if currency:
                        if currency not in wallets:
                            wallets[currency] = {}
                        wallets[currency][acc_type] = {'available': available, 'total': total}
                return {'ok': True, 'wallets': wallets}
            else:
                return {'ok': False, 'wallets': {}, 'error': data.get('msg', 'Unknown error')}
        else:
            return {'ok': False, 'wallets': {}, 'error': f'HTTP {resp.status_code}'}
    except Exception as e:
        return {'ok': False, 'wallets': {}, 'error': str(e)}
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
# ENFORCE INAKTIV on redeploy - ALWAYS start disabled for safety!
# The active flag is NOT used to enable the bot - user must enable manually in dashboard
# This prevents the bot from auto-starting after a crash/restart
if os.path.exists('/app/logs/arb_active.flag'):
    # Flag exists but DON'T use it to enable - just log it
    # The flag was set when user last enabled via dashboard, but bot should still start disabled
    pass  # Do nothing with the flag - bot always starts disabled
# Ensure config is INAKTIV on redeploy (SAFETY FIRST)
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
            _safe_rerun('kucoin_save')
        
        # Wallet type selector - only show if API keys are set
        if kucoin_key and kucoin_secret and kucoin_pass:
            try:
                wallets_data = get_kucoin_all_wallets_detailed(kucoin_key, kucoin_secret, kucoin_pass)
                if wallets_data.get('ok'):
                    all_wallets = wallets_data.get('wallets', {})
                    mpc_wallets = all_wallets.get('MPC', {})
                    
                    if mpc_wallets:
                        st.markdown("**Trading Wallet:**")
                        
                        # Build options with current balance info
                        wallet_options = []
                        wallet_labels = []
                        
                        for wt in ['trade', 'main', 'margin', 'otc', 'pool']:
                            if wt in mpc_wallets:
                                data = mpc_wallets[wt]
                                wallet_options.append(wt)
                        labels = {'trade': 'Trade Wallet', 'main': 'Main Wallet', 
                                'margin': 'Margin Wallet', 'otc': 'OTC Wallet', 'pool': 'Pool Wallet'}
                        
                        if wallet_options:
                            current_wallet = get_setting('kucoin.trading_wallet', 'trade')
                            
                            current_idx = 0
                            if current_wallet in wallet_options:
                                current_idx = wallet_options.index(current_wallet)
                            
                            selected = st.selectbox(
                                "Wallet:",
                                options=wallet_options,
                                index=current_idx,
                                format_func=lambda x: labels.get(x, x),
                                key="kucoin_wallet_select"
                            )
                            
                            if selected != current_wallet:
                                set_setting('kucoin.trading_wallet', selected)
                                st.success(f"Wallet gesetzt: {selected}")
                                _safe_rerun('kucoin_wallet')
                        else:
                            pass  # All wallets shown
                    else:
                        st.caption("Keine MPC Wallets gefunden")
            except Exception as e:
                st.caption(f"Wallet-Fehler: {e}")
    
    with st.expander("MEXC", expanded=True):
        st.image("/app/static/mexc_icon.png", width=32)
        mexc_key_val = config.get('mexc', {}).get('api_key', '')
        mexc_secret_val = config.get('mexc', {}).get('api_secret', '')
        mexc_key = st.text_input("API Key", value=mexc_key_val, type="password", key="mexc_key_field")
        mexc_secret = st.text_input("API Secret", value=mexc_secret_val, type="password", key="mexc_secret_field")
        if st.button("💾 MEXC"):
            set_api_keys('mexc', api_key=mexc_key, api_secret=mexc_secret)
            st.success("Gespeichert!")
            _safe_rerun('mexc_save')
        
        # MEXC Wallet selector (MEXC uses funding/trade wallets via API)
        if mexc_key and mexc_secret:
            try:
                # MEXC has different wallet types - check via API
                st.markdown("**Trading Wallet:**")
                
                # Get current setting
                current_wallet = get_setting('mexc.trading_wallet', 'funding')
                
                # MEXC wallet options (via API they differentiate)
                wallet_options = ['funding', 'spot', 'margin']
                wallet_labels = ['Funding Wallet', 'Spot Wallet', 'Margin Wallet']
                
                current_idx = 0
                if current_wallet in wallet_options:
                    current_idx = wallet_options.index(current_wallet)
                
                selected = st.selectbox(
                    "Wallet:",
                    options=wallet_options,
                    index=current_idx,
                    format_func=lambda x: labels.get(x, x),
                    key="mexc_wallet_select"
                )
                
                if selected != current_wallet:
                    set_setting('mexc.trading_wallet', selected)
                    st.success(f"Wallet gesetzt: {selected}")
                    _safe_rerun('mexc_wallet')
            except Exception as e:
                st.caption(f"Wallet-Fehler: {e}")
    
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
            log_dir = Path('/app/logs')
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
            _safe_rerun('pair_add')
    else:
        st.info("Alle vorhanden!")
    
    # Delete pair
    st.markdown("### ➖ Paar entfernen")
    if pairs_config:
        pair_to_delete = st.selectbox("Paar", list(pairs_config.keys()), key="delete_pair_select")
        if st.button("🗑️ Entfernen", key="delete_pair_btn"):
            remove_pair(pair_to_delete)
            _safe_rerun('pair_remove')
    else:
        st.info("Keine Paare vorhanden!")
    # ========================================================================
    # 🐛 DEBUG: st.rerun() Trigger-Toggles (Full-Reload-Eingrenzung)
    # ========================================================================
    # ========================================================================
    # 🐛 DEBUG SIDEBOARD (rechts, einklappbar via Toggle-Button)
    # ========================================================================
    # CSS für rechten Sideboard (position: fixed, gleiche Optik wie st.sidebar links)
    st.markdown("""<style>
section.debug-sideboard {
    position: fixed;
    right: 0;
    top: 3.5rem;
    bottom: 2rem;
    width: 340px;
    background-color: #262626;
    border-left: 1px solid #404040;
    z-index: 999;
    overflow-y: auto;
    padding: 1rem;
    box-shadow: -2px 0 8px rgba(0,0,0,0.3);
}
div[data-testid="stButton"] button[kind="secondary"]:has(p:contains("🐛 Debug")) {
    position: fixed !important;
    top: 0.5rem !important;
    right: 0.5rem !important;
    z-index: 1001 !important;
}
</style>""", unsafe_allow_html=True)

    # Toggle-Button (immer sichtbar; per CSS oben rechts fixiert)
    if st.button("🐛 Debug", key="toggle_debug_sideboard", help="Debug Sideboard rechts ein-/ausklappen"):
        st.session_state.debug_sideboard_open = not st.session_state.get("debug_sideboard_open", False)

    # Rechter Sideboard: nur rendern wenn Toggle aktiv (Default: zugeklappt)
    if st.session_state.get("debug_sideboard_open", False):
        with st.container():
            st.markdown('<section class="debug-sideboard">', unsafe_allow_html=True)
            st.markdown("### 🔧 Maintenance & Debug")
            st.caption("Wartungs- und Debug-Tools. Sideboard rechts einklappbar.")

            # --- 🔬 Diagnose CSV (sauberes chr(10).join() Pattern) ---
            if st.button("🔬 Diagnose CSV", key="diag_csv_btn"):
                _diag_log = []
                try:
                    csv_path = "/app/logs/MPCUSDT_trades.csv"
                    rows = trade_logger._read_csv_data_rows(csv_path)
                    filled = [r for r in rows if r.get('ex2_status', '').strip().upper() == 'FILLED']
                    _diag_log.append(f"Total CSV rows: {len(rows)}")
                    _diag_log.append(f"FILLED rows: {len(filled)}")
                    for r in filled[:5]:
                        _diag_log.append(f"  {r.get('trade_id','')}: profit={r.get('profit_usdt_actual','')!r}")
                    profits = [float(r.get('profit_usdt_actual', 0) or 0) for r in filled if r.get('profit_usdt_actual')]
                    _diag_log.append(f"Sum profit_usdt_actual: {sum(profits):.4f} USDT")
                    open_count = sum(1 for r in rows if r.get('ex2_status', '').strip().upper() == 'OPEN')
                    _diag_log.append(f"OPEN count: {open_count}")
                except Exception as _e:
                    _diag_log.append(f"ERROR: {_e}")
                st.code(chr(10).join(_diag_log), language="text")

            st.markdown("---")

            # --- 🐛 st.rerun() Trigger-Toggles (aus altem Debug-Expander Z.991) ---
            st.markdown("**🐛 st.rerun() Trigger-Toggles**")
            st.caption("Schalte einzelne st.rerun() ab um zu sehen welcher Trigger die Full-Reloads verursacht. Default: alle AN.")
            st.checkbox("💾 KuCoin Save", value=True, key="dbg_rerun_kucoin_save")
            st.checkbox("KuCoin Wallet-Select", value=True, key="dbg_rerun_kucoin_wallet")
            st.checkbox("💾 MEXC Save", value=True, key="dbg_rerun_mexc_save")
            st.checkbox("MEXC Wallet-Select", value=True, key="dbg_rerun_mexc_wallet")
            st.checkbox("➕ Paar hinzufügen", value=True, key="dbg_rerun_pair_add")
            st.checkbox("🗑️ Paar entfernen", value=True, key="dbg_rerun_pair_remove")
            st.checkbox("📊 Anzeigen Pair", value=True, key="dbg_rerun_pair_view")
            st.checkbox("← Home", value=True, key="dbg_rerun_home")
            st.checkbox("Bot AKTIV Toggle", value=True, key="dbg_rerun_bot_toggle")

            st.markdown('</section>', unsafe_allow_html=True)

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
                # Counter + Profit iterieren über ALLE CSV-Zeilen (kein 1000-Limit).
                # Realisierter Gewinn = nur FILLED Trades; offene nur als Anzahl
                # (Jonas 2026-10-19 09:59). Siehe docs/TRADE_LOG_CALCULATIONS.md.
                total_trades = count_main_trades(pair_name)
                total_profit = completed_profit_usdt(pair_name)
                open_trades = open_trade_count(pair_name)
                
                # Build complete tile as HTML
                st.markdown(f"""
                <div style="background: #262626; border: 1px solid #404040; border-radius: 8px; padding: 16px; margin: 4px 0;">
                    <div style="display: flex; align-items: center; gap: 8px; margin-bottom: 12px;">
                        <span style="font-size: 24px;">{status_color}</span>
                        <span style="font-size: 20px; font-weight: bold; color: white;">{pair_name}</span>
                    </div>
                """)