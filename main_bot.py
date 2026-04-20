#!/usr/bin/env python3
"""
MPC Arbitrage Bot - Main Entry Point
"""
import asyncio
import sys
import os

# Add parent directory to path so we can import config and bot
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from bot.main_bot import start_bot, stop_bot

if __name__ == "__main__":
    print("🚀 Starting MPC Arbitrage Bot...")
    try:
        asyncio.run(start_bot())
    except KeyboardInterrupt:
        print("\n🛑 Shutting down...")
        asyncio.run(stop_bot())
