"""
Trade Logger Service - Background Thread for Trade Logging

Architecture (Option 1: Sync Bot + Background Filler):
- Bot calls log_trade() (sync via trade_logger.py) - unchanged
- This service provides only the background filler for missing exchange data
- get_trades() and get_trade_summary() for dashboard reads
- Bot ownership of CSV is NOT transferred

Usage:
    from trade_logger_service import start, get_trades, get_trade_summary
    start()  # Call once at bot startup
"""

import csv
import threading
import time
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional

LOG_DIR = Path("/app/logs")
CONFIG_PATH = Path("/app/config/config.yaml")


# Exchange configuration
_EXCHANGE_CONFIG = None

def get_exchange_config() -> Dict:
    global _EXCHANGE_CONFIG
    if _EXCHANGE_CONFIG is None:
        if CONFIG_PATH.exists():
            import yaml
            with open(CONFIG_PATH, 'r') as f:
                config = yaml.safe_load(f)
                _EXCHANGE_CONFIG = config.get('exchanges', {})
        else:
            _EXCHANGE_CONFIG = {}
    return _EXCHANGE_CONFIG

def get_mexc_credentials() -> Optional[Dict]:
    """Get MEXC API credentials from config"""
    if CONFIG_PATH.exists():
        import yaml
        with open(CONFIG_PATH, 'r') as f:
            config = yaml.safe_load(f)
            mexc = config.get('mexc', {})
            if mexc.get('api_key') and mexc.get('api_secret'):
                return {
                    'api_key': mexc['api_key'],
                    'api_secret': mexc['api_secret']
                }
    return None

def get_exchange_short_id(exchange_name: str) -> str:
    config = get_exchange_config()
    exchange_lower = exchange_name.lower()
    if exchange_lower in config:
        return config[exchange_lower].get('short_id', exchange_name[:3].upper())
    return exchange_name[:3].upper()


# Unified CSV columns (same as trade_logger.py)
UNIFIED_COLUMNS = [
    "trade_id", "internal_ts", "direction", "pair", "strategy", "spread_pct",
    "ex1", "ex1_order_id", "ex1_type", "ex1_side", "ex1_qty_ordered", "ex1_qty_filled",
    "ex1_price_expected", "ex1_price_actual", "ex1_price_avg", "ex1_value_usdt",
    "ex1_fees", "ex1_create_ts", "ex1_status",
    "ex2", "ex2_order_id", "ex2_type", "ex2_side", "ex2_qty_ordered", "ex2_qty_filled",
    "ex2_price_expected", "ex2_price_actual", "ex2_price_avg", "ex2_value_usdt",
    "ex2_fees", "ex2_create_ts", "ex2_status",
    "profit_usdt_expected", "profit_mpc_expected", "profit_usdt_actual", "profit_mpc_actual",
    "limit_watch_status", "limit_last_check",
    "error_code", "error_message",
    "raw_ex1_response", "raw_ex2_response", "updated_at"
]


class TradeLogger:
    """
    Background service for trade data management.
    
    Provides:
    - Background filler for missing exchange data (ex2_create_ts, ex2_status)
    - Thread-safe CSV reading for dashboard
    
    NOTE: Bot keeps using log_trade() from trade_logger.py (sync)
          This service only handles background filling, NOT trade logging
    """
    
    _instance = None
    _lock = threading.Lock()
    
    def __init__(self):
        self.running = False
        self.filler_thread = None
        self._csv_lock = threading.Lock()
    
    @classmethod
    def get_instance(cls):
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    cls._instance = cls()
        return cls._instance
    
    def start(self):
        """Start the background filler thread"""
        if self.running:
            return
        
        self.running = True
        LOG_DIR.mkdir(parents=True, exist_ok=True)
        
        self.filler_thread = threading.Thread(target=self._background_filler, daemon=True)
        self.filler_thread.start()
        
        print(f"[TradeLogger] Started - LOG_DIR={LOG_DIR}")
    
    def stop(self):
        """Stop the background thread"""
        self.running = False
        if self.filler_thread:
            self.filler_thread.join(timeout=5)
        print("[TradeLogger] Stopped")
    
    def _background_filler(self):
        """Background filler - polls exchanges for missing trade data"""
        while self.running:
            try:
                time.sleep(60)  # Check every minute
                
                for csv_file in LOG_DIR.glob("*_trades.csv"):
                    self._fill_missing_in_csv(csv_file)
                    
            except Exception as e:
                print(f"[TradeLogger] Filler error: {e}")
    
    def _fill_missing_in_csv(self, csv_path: Path):
        """Check CSV for missing data and fill via API calls"""
        with self._csv_lock:
            try:
                with open(csv_path, 'r', newline='') as f:
                    reader = csv.DictReader(f)
                    rows = list(reader)
                
                if not rows:
                    return
                
                modified = False
                
                for i, row in enumerate(rows):
                    # ex2_create_ts missing?
                    if not row.get('ex2_create_ts') or row.get('ex2_create_ts') == '0':
                        order_id = row.get('ex2_order_id', '')
                        if order_id and order_id not in ['FAILED', 'NOT_PLACED', '']:
                            exchange = row.get('ex2', '')
                            ts = self._fetch_order_timestamp(exchange, order_id)
                            if ts:
                                rows[i]['ex2_create_ts'] = ts
                                modified = True
                    
                    # ex2_status missing?
                    if not row.get('ex2_status') or row.get('ex2_status') == '':
                        order_id = row.get('ex2_order_id', '')
                        if order_id and order_id not in ['FAILED', 'NOT_PLACED', '']:
                            exchange = row.get('ex2', '')
                            status = self._fetch_order_status(exchange, order_id)
                            if status:
                                rows[i]['ex2_status'] = status
                                modified = True
                    
                    # ex1_fees missing or 0?
                    ex1_fees = float(row.get('ex1_fees', 0) or 0)
                    if ex1_fees == 0:
                        order_id = row.get('ex1_order_id', '')
                        exchange = row.get('ex1', '')
                        if order_id and exchange and order_id not in ['FAILED', 'NOT_PLACED', '']:
                            pair = row.get('pair', '')
                            ts = int(row.get('ex1_create_ts', 0) or 0)
                            fee = self._fetch_fees_for_order(exchange, order_id, pair, ts)
                            if fee and fee > 0:
                                rows[i]['ex1_fees'] = fee
                                modified = True
                    
                    # ex2_fees missing or 0?
                    ex2_fees = float(row.get('ex2_fees', 0) or 0)
                    if ex2_fees == 0:
                        order_id = row.get('ex2_order_id', '')
                        exchange = row.get('ex2', '')
                        if order_id and exchange and order_id not in ['FAILED', 'NOT_PLACED', '']:
                            pair = row.get('pair', '')
                            ts = int(row.get('ex2_create_ts', 0) or 0)
                            fee = self._fetch_fees_for_order(exchange, order_id, pair, ts)
                            if fee and fee > 0:
                                rows[i]['ex2_fees'] = fee
                                modified = True
                
                if modified:
                    with open(csv_path, 'w', newline='') as f:
                        writer = csv.DictWriter(f, fieldnames=UNIFIED_COLUMNS)
                        writer.writeheader()
                        writer.writerows(rows)
                    print(f"[TradeLogger] Filled missing data in {csv_path.name}")
                    
            except Exception as e:
                print(f"[TradeLogger] Error filling {csv_path}: {e}")
    
    def _fetch_order_timestamp(self, exchange: str, order_id: str) -> Optional[int]:
        """Fetch order timestamp from exchange API"""
        # TODO: Implement API call to get order createTime
        # Needs exchange credentials from config
        return None
    
    def _fetch_order_status(self, exchange: str, order_id: str) -> Optional[str]:
        """Fetch order status from exchange API"""
        # TODO: Implement API call to get order status
        return None
    
    def _fetch_fees_for_order(self, exchange: str, order_id: str, pair: str, timestamp_ms: int) -> Optional[float]:
        """
        Fetch actual fees paid for an order from exchange API.
        Returns fee in USDT or None if not found.
        """
        # Normalize pair for MEXC: MPC-USDT -> MPCUSDT
        symbol = pair.replace('-', '').replace('/', '')
        
        if exchange.upper() == 'MXC':
            return self._fetch_mexc_fees(order_id, symbol, timestamp_ms)
        elif exchange.upper() == 'KCN':
            return self._fetch_kucoin_fees(order_id, symbol, timestamp_ms)
        return None
    
    def _fetch_mexc_fees(self, order_id: str, symbol: str, timestamp_ms: int) -> Optional[float]:
        """Fetch fees from MEXC myTrades API"""
        try:
            import hmac
            import hashlib
            import requests
            
            mexc_config = self._get_mexc_config()
            if not mexc_config:
                return None
            
            ts = str(int(time.time() * 1000))
            params = f'symbol={symbol}&timestamp={ts}'
            sig = hmac.new(
                mexc_config['api_secret'].encode('utf-8'),
                params.encode('utf-8'),
                hashlib.sha256
            ).hexdigest()
            
            url = f'https://api.mexc.com/api/v3/myTrades?{params}&signature={sig}'
            headers = {'X-MEXC-APIKEY': mexc_config['api_key']}
            
            resp = requests.get(url, headers=headers, timeout=10)
            if resp.status_code != 200:
                return None
            
            trades = resp.json()
            if not isinstance(trades, list):
                return None
            
            # Find trades matching this order
            total_fee = 0.0
            for trade in trades:
                if str(trade.get('orderId', '')) == str(order_id):
                    total_fee += float(trade.get('fee', 0) or 0)
            
            return total_fee if total_fee > 0 else None
            
        except Exception as e:
            print(f"[TradeLogger] MEXC fee fetch error: {e}")
            return None
    
    def _fetch_kucoin_fees(self, order_id: str, symbol: str, timestamp_ms: int) -> Optional[float]:
        """Fetch fees from KuCoin dealer API"""
        # KuCoin has different fee tracking - typically included in fill response
        # This is more complex and can be added later if needed
        return None
    
    def _get_mexc_config(self) -> Optional[Dict]:
        """Get MEXC API credentials from config"""
        return get_mexc_credentials()
    
    def get_trades(self, pair: str, limit: int = 50) -> List[Dict]:
        """Get trades from CSV - for dashboard"""
        csv_path = self._get_csv_path(pair)
        
        if not csv_path.exists():
            return []
        
        with self._csv_lock:
            with open(csv_path, 'r', newline='') as f:
                reader = csv.DictReader(f)
                rows = list(reader)
        
        return list(reversed(rows))[:limit]
    
    def get_trade_summary(self, pair: str) -> Dict:
        """Get summary statistics"""
        trades = self.get_trades(pair, limit=1000)
        
        total_trades = len(trades)
        completed_trades = len([t for t in trades if t.get('limit_watch_status') == 'FILLED'])
        pending_limit = len([t for t in trades if t.get('limit_watch_status') == 'WATCHING'])
        
        total_profit_usdt = sum(float(t.get('profit_usdt_actual', 0) or 0) for t in trades)
        total_profit_mpc = sum(float(t.get('profit_mpc_actual', 0) or 0) for t in trades)
        
        winning = len([t for t in trades if float(t.get('profit_usdt_actual', 0) or 0) > 0])
        win_rate = f"{(winning / total_trades * 100):.1f}%" if total_trades > 0 else "0%"
        
        return {
            'total_trades': total_trades,
            'completed_trades': completed_trades,
            'pending_limit_orders': pending_limit,
            'total_profit_usdt': total_profit_usdt,
            'total_profit_mpc': total_profit_mpc,
            'win_rate': win_rate,
        }
    
    def _get_csv_path(self, pair: str) -> Path:
        normalized = pair.replace('-', '').replace('/', '')
        return LOG_DIR / f"{normalized}_trades.csv"


# ========================================================================
# Module-level functions
# ========================================================================

_instance = None

def get_instance() -> TradeLogger:
    global _instance
    if _instance is None:
        _instance = TradeLogger.get_instance()
    return _instance

def start():
    """Start the TradeLogger background service"""
    get_instance().start()

def stop():
    """Stop the TradeLogger background service"""
    get_instance().stop()

def get_trades(pair: str, limit: int = 50) -> List[Dict]:
    """Get trades from CSV - for dashboard"""
    return get_instance().get_trades(pair, limit)

def get_trade_summary(pair: str) -> Dict:
    """Get trade summary - for dashboard"""
    return get_instance().get_trade_summary(pair)