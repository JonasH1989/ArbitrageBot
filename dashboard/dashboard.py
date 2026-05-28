"""
MPC Arbitrage Dashboard
Streamlit-based dashboard for monitoring and controlling the arbitrage bot
"""

import streamlit as st
import asyncio
import time
from datetime import datetime
from typing import Dict, Any

# Import bot components
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from config.config_manager import get_config
from bot.spread_analyzer import SpreadAnalyzer
from bot.main_bot import get_bot, start_bot, stop_bot
from bot.trade_logger import get_trades, get_trade_summary, get_pending_limit_orders


# Page config
st.set_page_config(
    page_title="MPC Arbitrage Bot",
    page_icon="📊",
    layout="wide",
    initial_sidebar_state="expanded"
)


# Custom CSS
st.markdown("""
<style>
    .status-ok { color: #2ecc71; font-weight: bold; }
    .status-error { color: #e74c3c; font-weight: bold; }
    .status-warning { color: #f39c12; font-weight: bold; }
    .metric-card {
        background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
        padding: 20px;
        border-radius: 10px;
        color: white;
        text-align: center;
    }
    .opportunity-alert {
        background: linear-gradient(135deg, #11998e 0%, #38ef7d 100%);
        padding: 15px;
        border-radius: 10px;
        color: white;
        font-weight: bold;
    }
    .stActionButton > button {
        background-color: #4CAF50;
        color: white;
    }
</style>
""", unsafe_allow_html=True)


# Session state management
def init_session_state():
    """Initialize session state variables"""
    if 'authenticated' not in st.session_state:
        st.session_state.authenticated = False
    if 'show_2fa' not in st.session_state:
        st.session_state.show_2fa = False
    if 'username' not in st.session_state:
        st.session_state.username = ""
    if 'password' not in st.session_state:
        st.session_state.password = ""
    if 'totp_token' not in st.session_state:
        st.session_state.totp_token = ""


def login_page():
    """Render login / registration page"""
    st.title("🔐 MPC Arbitrage Bot - Login")
    
    config = get_config()
    
    if not config.is_registered:
        # Registration page
        st.info("👋 First time setup! Please create your admin account.")
        
        with st.form("registration_form"):
            st.subheader("Create Admin Account")
            
            username = st.text_input("Username", value="admin")
            password = st.text_input("Password", type="password")
            password_confirm = st.text_input("Confirm Password", type="password")
            
            submitted = st.form_submit_button("Register", use_container_width=True)
            
            if submitted:
                if password != password_confirm:
                    st.error("❌ Passwords do not match!")
                elif len(password) < 8:
                    st.error("❌ Password must be at least 8 characters!")
                else:
                    # Show 2FA setup
                    result = config.register_admin(username, password)
                    
                    if result['success']:
                        st.success("✅ Admin registered successfully!")
                        
                        st.info("📱 **Setup 2FA (TOTP)**")
                        st.markdown(f"""
                        **Step 1:** Install an authenticator app (Google Authenticator, Authy, etc.)
                        
                        **Step 2:** Scan this QR code or enter the secret manually:
                        
                        **Secret Key:** `{result['totp_secret']}`
                        
                        **Backup Codes (save these!):**
                        ```
                        """
                        + "\n".join(result['backup_codes']) +
                        """
                        ```
                        
                        [Download Authenticator App](https://play.google.com/store/apps/details?id=com.google.android.apps.authenticator2)
                        """)
                        
                        st.session_state.show_2fa_setup = True
                        st.session_state.totp_secret = result['totp_secret']
                    else:
                        st.error(f"❌ {result['message']}")
    else:
        # Login page
        with st.form("login_form"):
            st.subheader("🔑 Admin Login")
            
            username = st.text_input("Username", value=st.session_state.get('username', ''))
            password = st.text_input("Password", type="password")
            
            # 2FA input (show after password)
            token = st.text_input("2FA Code (from Authenticator)", type="password", max_chars=6)
            
            submitted = st.form_submit_button("Login", use_container_width=True)
            
            if submitted:
                if not username or not password:
                    st.error("Please enter username and password")
                elif not token:
                    st.error("Please enter 2FA code")
                else:
                    result = config.authenticate(username, password, token)
                    
                    if result['success']:
                        st.session_state.authenticated = True
                        st.session_state.username = username
                        st.rerun()
                    else:
                        st.error(f"❌ {result['message']}")


def main_dashboard():
    """Main dashboard page"""
    
    # Header
    st.title("📊 MPC Arbitrage Bot Dashboard")
    
    # Sidebar controls
    with st.sidebar:
        st.header("⚙️ Configuration")
        
        config = get_config()
        thresholds = config.get_thresholds()
        
        # Thresholds (only in test mode)
        st.subheader("🎚️ Threshold Settings")
        
        start_threshold = st.slider(
            "Start Threshold (%)",
            min_value=0.0,
            max_value=50.0,
            value=thresholds['start'],
            step=0.1,
            help="Spread must exceed this to start arbitrage"
        )
        
        stop_threshold = st.slider(
            "Stop Threshold (%)",
            min_value=0.0,
            max_value=50.0,
            value=thresholds['stop'],
            step=0.1,
            help="Spread must fall below this to stop arbitrage"
        )
        
        if start_threshold < stop_threshold:
            st.error("⚠️ Start threshold must be >= stop threshold")
        elif st.button("💾 Save Thresholds", use_container_width=True):
            result = config.set_thresholds(start_threshold, stop_threshold)
            if result['success']:
                st.success("✅ Thresholds updated")
            else:
                st.error(f"❌ {result['message']}")
        
        st.divider()
        
        # Bot controls
        st.subheader("🤖 Bot Controls")
        
        col1, col2 = st.columns(2)
        
        with col1:
            if st.button("▶️ Start", use_container_width=True, type="primary"):
                asyncio.create_task(start_bot())
                time.sleep(0.5)
                st.rerun()
        
        with col2:
            if st.button("⏹️ Stop", use_container_width=True):
                asyncio.create_task(stop_bot())
                time.sleep(0.5)
                st.rerun()
        
        # API Keys section
        st.divider()
        st.subheader("🔑 API Status")
        
        api_keys_set = {
            'KuCoin': bool(config.get('kucoin.api_key')),
            'MEXC': bool(config.get('mexc.api_key'))
        }
        
        for exchange, is_set in api_keys_set.items():
            status = "✅ Set" if is_set else "❌ Not set"
            st.text(f"{exchange}: {status}")
        
        # Logout
        st.divider()
        if st.button("🚪 Logout", use_container_width=True):
            st.session_state.authenticated = False
            st.rerun()
    
    # Main content
    col1, col2, col3, col4 = st.columns(4)
    
    # Get bot status
    bot = get_bot()
    status = bot.get_status() if bot else None
    
    # Status cards
    with col1:
        bot_status = "🟢 Running" if status and status['running'] else "🔴 Stopped"
        if status and status['paused']:
            bot_status = "🟡 Paused"
        st.metric("Bot Status", bot_status)
    
    with col2:
        opp_status = "🚀 Active" if bot and bot.analyzer.is_opportunity_active else "⏸️ None"
        st.metric("Opportunity", opp_status)
    
    with col3:
        current_spread = 0.0
        if bot and bot.analyzer.current_snapshot:
            snapshot = bot.analyzer.current_snapshot
            current_spread = max(
                snapshot.kucoin_buy_mexc_sell if snapshot.kucoin_buy_mexc_sell > 0 else 0,
                getattr(snapshot, 'mexc_buy_kucoin_sell', 0)
            )
        st.metric("Current Spread", f"{current_spread:.3f}%")
    
    # Trade stats replace "Total Checks" tile
    all_trades = get_trades('MPC-USDT', limit=10000)
    
    # Count unique trade IDs (exclude sub-rows like _ex2sum, _ex1p1, _ex2p1 etc.)
    trade_ids = set()
    for t in all_trades:
        tid = t.get('trade_id', '')
        # Only count main trade rows (no _ex2sum, _ex1pN, _ex2pN suffixes)
        if tid and not any(suffix in tid for suffix in ['_ex2sum', '_ex1p', '_ex2p', '_ex1sum']):
            trade_ids.add(tid)
    
    total_trades = len(trade_ids)
    
    # Count pending trades
    pending_trades = get_pending_limit_orders('MPC-USDT')
    pending_count = len(pending_trades)
    
    # Calculate profits from summary
    summary = get_trade_summary('MPC-USDT')
    total_profit_usdt = summary.get('total_profit_usdt', 0)
    total_profit_mpc = summary.get('total_profit_mpc', 0)
    
    st.metric("Trades", f"{total_trades} ({pending_count} pending)")
    st.metric("Gewinn USDT", f"{total_profit_usdt:.4f}")
    st.caption(f"MPC: {total_profit_mpc:.4f}")
    
    # Price comparison
    st.subheader("💰 Price Comparison")
    
    if bot and bot.analyzer.current_snapshot:
        snapshot = bot.analyzer.current_snapshot
        
        price_col1, price_col2, price_col3, price_col4 = st.columns(4)
        
        with price_col1:
            st.metric("KuCoin Bid", f"${snapshot.kucoin_bid:.6f}")
        with price_col2:
            st.metric("KuCoin Ask", f"${snapshot.kucoin_ask:.6f}")
        with price_col3:
            st.metric("MEXC Bid", f"${snapshot.mexc_bid:.6f}")
        with price_col4:
            st.metric("MEXC Ask", f"${snapshot.mexc_ask:.6f}")
    else:
        st.info("📡 Waiting for orderbook data... Start the bot to see live prices.")
    
    # Charts
    st.subheader("📈 Spread Analysis")
    
    chart_col1, chart_col2 = st.columns(2)
    
    with chart_col1:
        st.write("**Spread Over Time**")
        if bot and len(bot.analyzer.snapshots) > 1:
            chart_data = bot.analyzer.get_chart_data(last_n=100)
            
            import pandas as pd
            df = pd.DataFrame({
                'Time': pd.to_datetime(chart_data['timestamps']),
                'KuCoin→MEXC': chart_data['kucoin_buy_mexc_sell'],
                'MEXC→KuCoin': chart_data['mexc_buy_kucoin_sell']
            })
            
            st.line_chart(df.set_index('Time'))
        else:
            st.info("Not enough data for chart yet")
    
    with chart_col2:
        st.write("**Orderbook Volumes**")
        if bot and bot.analyzer.current_snapshot:
            snapshot = bot.analyzer.current_snapshot
            
            vol_data = pd.DataFrame({
                'Exchange': ['KuCoin Bid', 'KuCoin Ask', 'MEXC Bid', 'MEXC Ask'],
                'Volume (MPC)': [
                    snapshot.kucoin_bid_vol,
                    snapshot.kucoin_ask_vol,
                    snapshot.mexc_bid_vol,
                    snapshot.mexc_ask_vol
                ]
            })
            
            st.bar_chart(vol_data.set_index('Exchange'))
    
    # Statistics
    st.subheader("📊 Statistics")
    
    if bot:
        stats = bot.analyzer.stats
        
        stat_col1, stat_col2, stat_col3, stat_col4 = st.columns(4)
        
        with stat_col1:
            st.metric("Opportunities Found", stats['opportunities_found'])
        with stat_col2:
            st.metric("Max Spread Observed", f"{stats['max_spread_observed']:.3f}%")
        with stat_col3:
            st.metric("Min Spread Observed", f"{stats['min_spread_observed']:.3f}%")
        with stat_col4:
            st.metric("Avg Spread", f"{stats['avg_spread_kucoin_mexc']:.3f}%")
    
    # Recent Opportunities
    st.subheader("🔔 Recent Opportunities")
    
    if bot and len(bot.analyzer.opportunities) > 0:
        opportunities = list(bot.analyzer.opportunities)[-10:]
        
        opp_data = []
        for opp in opportunities:
            opp_data.append({
                'Time': opp.timestamp.strftime('%H:%M:%S'),
                'Buy Exchange': opp.buy_exchange.upper(),
                'Sell Exchange': opp.sell_exchange.upper(),
                'Buy Price': f"${opp.buy_price:.6f}",
                'Sell Price': f"${opp.sell_price:.6f}",
                'Spread (%)': f"{opp.spread_pct:.3f}%",
                'Volume': f"{opp.max_volume:.0f}"
            })
        
        st.dataframe(pd.DataFrame(opp_data), use_container_width=True)
    else:
        st.info("No opportunities detected yet")


def main():
    """Main entry point"""
    init_session_state()
    
    if not st.session_state.authenticated:
        login_page()
    else:
        main_dashboard()


if __name__ == "__main__":
    main()
