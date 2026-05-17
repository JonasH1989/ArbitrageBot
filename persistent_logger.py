#!/usr/bin/env python3
"""
Persistent Logger - appends timestamped log entries to a text file
Survives bot restarts - lives on persistent volume
"""
import os
from datetime import datetime

LOG_DIR = "/app/logs"
LOG_FILE = os.path.join(LOG_DIR, "persistent_trades.log")

def ensure_dir():
    os.makedirs(LOG_DIR, exist_ok=True)

def log(message: str, level: str = "INFO"):
    """Append a timestamped log entry to the file"""
    ensure_dir()
    ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S.%f")[:-3]
    entry = f"[{ts}] [{level}] {message}\n"
    with open(LOG_FILE, "a") as f:
        f.write(entry)

def log_trade(direction: str, ex1: str, ex1_qty: float, ex1_price: float,
              ex2: str, ex2_qty: float, ex2_price: float, spread: float):
    """Log a trade in structured format"""
    ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S.%f")[:-3]
    entry = (
        f"[{ts}] [TRADE] "
        f"Direction={direction} | "
        f"{ex1}: {ex1_qty} MPC @ {ex1_price:.5f} | "
        f"{ex2}: {ex2_qty} MPC @ {ex2_price:.5f} | "
        f"Spread={spread:.2f}%\n"
    )
    ensure_dir()
    with open(LOG_FILE, "a") as f:
        f.write(entry)

def get_logs(limit: int = 100):
    """Read last N log entries"""
    if not os.path.exists(LOG_FILE):
        return []
    with open(LOG_FILE, "r") as f:
        lines = f.readlines()
    return [l.strip() for l in lines[-limit:]]

if __name__ == "__main__":
    log("Persistent logger test")
    print(f"Log file: {LOG_FILE}")
    print(f"Exists: {os.path.exists(LOG_FILE)}")
    if os.path.exists(LOG_FILE):
        with open(LOG_FILE, "r") as f:
            print(f"Content:\n{f.read()}")
