#!/usr/bin/env python3
"""
Log Viewer Page - Dedicated page for viewing bot logs
Run this as a separate Streamlit app: streamlit run log_viewer.py --server.port 8502
"""
import streamlit as st
import streamlit.components.v1 as components
from pathlib import Path
from datetime import datetime
import time

st.set_page_config(page_title="Bot Log Viewer", page_icon="📊")

st.title("📊 Bot Log Viewer")
st.caption("Live monitoring of arbitrage bot decisions")

# Auto-refresh checkbox
auto_refresh = st.sidebar.checkbox("Auto-Refresh (5s)", value=True)

# Refresh button
if st.sidebar.button("🔄 Refresh Now"):
    st.rerun()

# Log file path
LOG_FILE = Path('/home/openclaw/.openclaw/logs/arb_debug.log')

def get_logs(limit=200):
    if not LOG_FILE.exists():
        return ["❌ Log file not found. Start arb_autotrade_debug.py first."]
    try:
        lines = LOG_FILE.read_text().strip().split('\n')
        return lines[-limit:] if lines else ["Log is empty"]
    except Exception as e:
        return [f"Error reading log: {e}"]

# Display logs
logs = get_logs(200)

if logs:
    st.subheader(f"Recent Logs ({len(logs)} entries)")
    
    # Color mapping
    def get_color(line):
        if '[DECISION]' in line:
            return '#00bfff'  # cyan
        elif '[CONDITION]' in line:
            if '✅' in line:
                return '#00ff00'  # green
            elif '❌' in line:
                return '#ff4444'  # red
            return '#ffff00'  # yellow
        elif '[ERROR]' in line:
            return '#ff0000'  # red
        elif '[WARN]' in line:
            return '#ffaa00'  # orange
        elif '[PRICE]' in line:
            return '#00ffcc'  # teal
        elif '[VOLUME]' in line:
            return '#ff00ff'  # magenta
        elif '[INFO]' in line:
            return '#ffffff'  # white
        return '#aaaaaa'  # gray
    
    # Build HTML
    log_html = """
    <div style='font-family: monospace; font-size: 12px; background: #0d1117; padding: 15px; border-radius: 8px; max-height: 70vh; overflow-y: auto;'>
    """
    
    for line in logs:
        color = get_color(line)
        line_escaped = line.replace('<', '&lt;').replace('>', '&gt;')
        log_html += f"<div style='color: {color}; margin: 3px 0; border-bottom: 1px solid #222;'>{line_escaped}</div>"
    
    log_html += "</div>"
    
    components.html(log_html, height=700, scrolling=True)
else:
    st.warning("No logs available")

# Stats
st.sidebar.divider()
st.sidebar.subheader("📈 Stats")
if LOG_FILE.exists():
    stats = LOG_FILE.stat()
    st.sidebar.caption(f"Log size: {stats.st_size / 1024:.1f} KB")
    st.sidebar.caption(f"Modified: {datetime.fromtimestamp(stats.st_mtime)}")
else:
    st.sidebar.caption("Log file not found")

# Auto-refresh
if auto_refresh:
    time.sleep(5)
    st.rerun()
