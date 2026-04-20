"""
MPC Arbitrage Bot
Main bot that monitors orderbooks and detects arbitrage opportunities
"""

import asyncio
import signal
import sys
import os
from pathlib import Path

# Add parent directory to path so we can import config and bot
sys.path.insert(0, str(Path(__file__).parent.parent))

from datetime import datetime
from typing import Optional
from loguru import logger
from config.kucoin_connector import KuCoinConnector, get_kucoin_connector
from config.mexc_connector import MexcConnector, get_mexc_connector
from config.config_manager import get_config
from bot.spread_analyzer import SpreadAnalyzer, SpreadSnapshot


class ArbitrageBot:
    """
    Main arbitrage bot that monitors KuCoin and MEXC orderbooks
    """
    
    def __init__(self, pair: str = "MPC-USDT", update_interval: float = 1.0):
        self.pair = pair
        self.update_interval = update_interval
        self.config = get_config()
        
        # Exchange connectors
        self.kucoin: Optional[KuCoinConnector] = None
        self.mexc: Optional[MexcConnector] = None
        
        # Analyzer
        self.analyzer = SpreadAnalyzer(pair)
        
        # Control flags
        self._running = False
        self._paused = False
        self._task: Optional[asyncio.Task] = None
        
        # Register signal handlers
        signal.signal(signal.SIGINT, self._signal_handler)
        signal.signal(signal.SIGTERM, self._signal_handler)
    
    def _signal_handler(self, signum, frame):
        """Handle shutdown signals"""
        logger.info(f"Received signal {signum}, shutting down...")
        asyncio.create_task(self.stop())
    
    async def start(self):
        """Start the arbitrage bot"""
        logger.info(f"🚀 Starting MPC Arbitrage Bot for {self.pair}")
        
        # Initialize connectors
        logger.info("[1/3] Connecting to KuCoin...")
        self.kucoin = await get_kucoin_connector(self.pair)
        
        logger.info("[2/3] Connecting to MEXC...")
        self.mexc = await get_mexc_connector(self.pair)
        
        logger.info("[3/3] Initializing spread analyzer...")
        
        # Get thresholds
        thresholds = self.config.get_thresholds()
        logger.info(f"   Thresholds: start={thresholds['start']}%, stop={thresholds['stop']}%")
        
        self._running = True
        logger.info(f"✅ Bot started! Monitoring {self.pair} every {self.update_interval}s")
        
        # Start monitoring loop
        self._task = asyncio.create_task(self._monitor_loop())
    
    async def stop(self):
        """Stop the arbitrage bot"""
        logger.info("🛑 Stopping Arbitrage Bot...")
        self._running = False
        
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
        
        # Disconnect from exchanges
        if self.kucoin:
            await self.kucoin.disconnect()
        if self.mexc:
            await self.mexc.disconnect()
        
        logger.info("✅ Bot stopped gracefully")
    
    async def pause(self):
        """Pause monitoring"""
        self._paused = True
        logger.info("⏸️ Bot paused")
    
    async def resume(self):
        """Resume monitoring"""
        self._paused = False
        logger.info("▶️ Bot resumed")
    
    async def _monitor_loop(self):
        """Main monitoring loop"""
        consecutive_errors = 0
        max_errors = 5
        
        while self._running:
            try:
                if not self._paused:
                    await self._fetch_and_analyze()
                    consecutive_errors = 0
                
                await asyncio.sleep(self.update_interval)
                
            except asyncio.CancelledError:
                break
            except Exception as e:
                consecutive_errors += 1
                logger.error(f"Error in monitor loop ({consecutive_errors}/{max_errors}): {e}")
                
                if consecutive_errors >= max_errors:
                    logger.error("Too many consecutive errors, pausing bot...")
                    await self.pause()
                
                await asyncio.sleep(5)  # Wait before retry
    
    async def _fetch_and_analyze(self):
        """Fetch orderbooks from both exchanges and analyze"""
        # Fetch orderbooks concurrently
        kucoin_task = self.kucoin.get_orderbook()
        mexc_task = self.mexc.get_orderbook()
        
        kucoin_ob, mexc_ob = await asyncio.gather(kucoin_task, mexc_task)
        
        if kucoin_ob is None:
            logger.warning("⚠️ Failed to fetch KuCoin orderbook")
            return
        
        if mexc_ob is None:
            logger.warning("⚠️ Failed to fetch MEXC orderbook")
            return
        
        # Log prices
        logger.debug(
            f"[{datetime.now().strftime('%H:%M:%S')}] "
            f"KuCoin: {kucoin_ob.best_bid:.6f} / {kucoin_ob.best_ask:.6f} | "
            f"MEXC: {mexc_ob.best_bid:.6f} / {mexc_ob.best_ask:.6f}"
        )
        
        # Analyze
        snapshot = self.analyzer.analyze_orderbooks(kucoin_ob, mexc_ob)
        
        # Check for opportunities
        if self.analyzer.is_opportunity_active:
            opp = list(self.analyzer.opportunities)[-1]
            logger.info(f"🚀 OPPORTUNITY: {opp}")
    
    def get_status(self) -> dict:
        """Get current bot status"""
        return {
            'running': self._running,
            'paused': self._paused,
            'pair': self.pair,
            'update_interval': self.update_interval,
            'connected': {
                'kucoin': self.kucoin.is_connected if self.kucoin else False,
                'mexc': self.mexc.is_connected if self.mexc else False
            },
            'analyzer': self.analyzer.get_summary()
        }


# Global bot instance
_bot: Optional[ArbitrageBot] = None

def get_bot() -> ArbitrageBot:
    """Get or create global bot instance"""
    global _bot
    if _bot is None:
        _bot = ArbitrageBot()
    return _bot

async def start_bot():
    """Start the global bot"""
    bot = get_bot()
    await bot.start()
    return bot

async def stop_bot():
    """Stop the global bot"""
    global _bot
    if _bot:
        await _bot.stop()
        _bot = None
