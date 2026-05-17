#!/usr/bin/env python3
"""
Persistent Logger - Durable logging for Arbitrage Bot
Two separate files:
1. arb_autotrade.log - All general logs (already exists, continues)
2. persistent_trades.log - Trade-specific entries only (NEW)
Both survive bot restarts via Docker named volume
"""
import os
from datetime import datetime

LOG_DIR = "/app/logs"
LOG_FILE = os.path.join(LOG_DIR, "arb_autotrade.log")      # General logs (existing)
TRADE_LOG_FILE = os.path.join(LOG_DIR, "persistent_trades.log")  # Trade entries only

def ensure_dir():
    os.makedirs(LOG_DIR, exist_ok=True)

def log(message: str, level: str = "INFO"):
    """General logging - appends to arb_autotrade.log with full timestamp"""
    ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S.%f")[:-3]
    entry = f"[{ts}] [{level}] {message}\n"
    try:
        with open(LOG_FILE, "a") as f:
            f.write(entry)
    except Exception:
        pass

def log_trade(trade_id: str, direction: str, ex1_exchange: str, ex1_side: str, 
              ex1_qty: float, ex1_price: float, ex1_value: float,
              ex2_exchange: str, ex2_side: str,
              ex2_qty: float, ex2_price: float, ex2_value: float,
              spread: float, status: str = "FILLED"):
    """Log a trade to the persistent trade log"""
    ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S.%f")[:-3]
    # Format: [TIMESTAMP] [TRADE] id|direction|ex1|side|qty|price|value|ex2|side|qty|price|value|spread|status
    entry = (
        f"[{ts}] [TRADE] "
        f"{trade_id}|{direction}|"
        f"{ex1_exchange}|{ex1_side}|{ex1_qty:.4f}|{ex1_price:.5f}|{ex1_value:.4f}|"
        f"{ex2_exchange}|{ex2_side}|{ex2_qty:.4f}|{ex2_price:.5f}|{ex2_value:.4f}|"
        f"{spread:.2f}|{status}\n"
    )
    try:
        with open(TRADE_LOG_FILE, "a") as f:
            f.write(entry)
    except Exception:
        pass

def log_trade_reconstructed(trade_id: str, timestamp: str, direction: str,
                           kucoin_side: str, kucoin_qty: float, kucoin_price: float,
                           mexc_side: str, mexc_qty: float, mexc_price: float,
                           spread: float, status: str = "RECONSTRUCTED"):
    """Log a reconstructed trade (from API data) to the persistent trade log"""
    entry = (
        f"[{timestamp}] [TRADE] "
        f"{trade_id}|{direction}|"
        f"KUCOIN|{kucoin_side}|{kucoin_qty:.4f}|{kucoin_price:.5f}|{kucoin_qty*kucoin_price:.4f}|"
        f"MEXC|{mexc_side}|{mexc_qty:.4f}|{mexc_price:.5f}|{mexc_qty*mexc_price:.4f}|"
        f"{spread:.2f}|{status}\n"
    )
    try:
        with open(TRADE_LOG_FILE, "a") as f:
            f.write(entry)
    except Exception:
        pass

def get_trades(limit: int = 100):
    """Read last N trade entries from persistent trade log"""
    if not os.path.exists(TRADE_LOG_FILE):
        return []
    try:
        with open(TRADE_LOG_FILE, "r") as f:
            lines = f.readlines()
        return [l.strip() for l in lines[-limit:]]
    except Exception:
        return []

def get_all_trades():
    """Read all trade entries"""
    return get_trades(limit=999999)

if __name__ == "__main__":
    log("Persistent logger initialized")
    print(f"Log file: {LOG_FILE}")
    print(f"Trade log file: {TRADE_LOG_FILE}")
    print(f"Trade log exists: {os.path.exists(TRADE_LOG_FILE)}")
