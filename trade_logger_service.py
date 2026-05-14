"""
Trade Logger Service - Background Thread for Trade Logging
Runs inside the bot container, handles all CSV operations and background filler.
"""
import csv
import os
import json
import time
import threading
import queue
from datetime import datetime
from pathlib import Path
from typing import Dict, Optional, List, Tuple

LOG_DIR = Path("/app/logs")
CONFIG_PATH = Path("/app/config/config.yaml")


# Exchange configuration cache
_EXCHANGE_CONFIG = None

def get_exchange_config() -> Dict:
    """Load exchange config from config.yaml"""
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

def get_exchange_short_id(exchange_name: str) -> str:
    """Get short_id for an exchange (e.g. 'KUCOIN' -> 'KCN')"""
    config = get_exchange_config()
    exchange_lower = exchange_name.lower()
    if exchange_lower in config:
        return config[exchange_lower].get('short_id', exchange_name[:3].upper())
    return exchange_name[:3].upper()

def get_exchange_color(exchange_name: str) -> str:
    """Get color for an exchange"""
    config = get_exchange_config()
    exchange_lower = exchange_name.lower()
    if exchange_lower in config:
        return config[exchange_lower].get('color', '#888888')
    return '#888888'


# Unified CSV columns for ALL trades
UNIFIED_COLUMNS = [
    "trade_id",              # Unique ID
    "internal_ts",           # When BOT initiated the trade (ISO format)
    "direction",              # "KCN->MXC" or "MXC->KCN"
    "pair",                  # Trading pair e.g. "MPC-USDT"
    "strategy",               # "USDT" or "COINS"
    "spread_pct",             # Spread in % when trade was triggered
    
    # Exchange 1 (Market Order - first leg, always MARKET)
    "ex1",                   # Exchange short_id: "KCN", "MXC", "BNC"
    "ex1_order_id",          # Exchange-specific order ID
    "ex1_type",              # "market" (always for ex1)
    "ex1_side",              # "buy" or "sell"
    "ex1_qty_ordered",       # Quantity ordered
    "ex1_qty_filled",        # Quantity filled
    "ex1_price_expected",    # Expected price when trade was initiated
    "ex1_price_actual",      # Actual execution price
    "ex1_price_avg",         # Average fill price (for multi-level fills)
    "ex1_value_usdt",        # Total value in USDT
    "ex1_fees",              # Fees paid in USDT
    "ex1_create_ts",         # Exchange timestamp (ms)
    "ex1_status",            # Exchange status: FILLED, PARTIAL, REJECTED, PENDING
    
    # Exchange 2 (Limit Order - second leg, always LIMIT)
    "ex2",                   # Exchange short_id: "KCN", "MXC", "BNC"
    "ex2_order_id",          # Exchange-specific order ID
    "ex2_type",              # "limit" (always for ex2)
    "ex2_side",              # "buy" or "sell"
    "ex2_qty_ordered",       # Quantity ordered
    "ex2_qty_filled",        # Quantity filled (0 = pending)
    "ex2_price_expected",    # Expected price when trade was initiated
    "ex2_price_actual",      # Actual execution price
    "ex2_price_avg",         # Actual fill price (0 if not filled)
    "ex2_value_usdt",        # Total value in USDT (0 if not filled)
    "ex2_fees",              # Fees paid in USDT
    "ex2_create_ts",         # Exchange timestamp (ms)
    "ex2_status",            # Exchange status: PENDING, FILLED, PARTIAL, CANCELLED
    
    # Profit Calculation
    "profit_usdt_expected",  # Expected USDT profit
    "profit_mpc_expected",   # Expected MPC profit
    "profit_usdt_actual",    # Actual USDT profit
    "profit_mpc_actual",     # Actual MPC profit
    
    # Limit Order Watch State
    "limit_watch_status",    # "WATCHING", "FILLED", "PARTIAL", "CANCELLED", "EXPIRED", "ERROR"
    "limit_last_check",      # Last timestamp we checked fill status
    
    # Error Handling
    "error_code",            # Error code if any
    "error_message",         # Human-readable error description
    
    # Metadata
    "raw_ex1_response",      # Full JSON response from Exchange 1
    "raw_ex2_response",      # Full JSON response from Exchange 2
    "updated_at",            # Last update timestamp (ISO format)
]


class TradeLogger:
    """
    Trade Logger Service - Background Thread for Trade Logging
    
    Architecture:
    - Bot calls log_trade_async() to queue a trade
    - Background thread processes queue and writes to CSV
    - Background filler polls exchanges for missing data
    - All trade data owned by this class
    
    Usage:
        logger = TradeLogger.get_instance()
        logger.start()
        logger.log_trade_async(trade_data)
    """
    
    _instance = None
    _lock = threading.Lock()
    
    def __init__(self):
        self.queue = queue.Queue()
        self.running = False
        self.background_thread = None
        self.filler_thread = None
        self.last_cleanup = time.time()
    
    @classmethod
    def get_instance(cls):
        """Get singleton instance"""
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    cls._instance = cls()
        return cls._instance
    
    def start(self):
        """Start the background threads"""
        if self.running:
            return
        
        self.running = True
        LOG_DIR.mkdir(parents=True, exist_ok=True)
        
        # Main queue processor thread
        self.background_thread = threading.Thread(target=self._process_queue, daemon=True)
        self.background_thread.start()
        
        # Background filler thread (polls exchanges for missing data)
        self.filler_thread = threading.Thread(target=self._background_filler, daemon=True)
        self.filler_thread.start()
        
        print(f"[TradeLogger] Started - LOG_DIR={LOG_DIR}")
    
    def stop(self):
        """Stop the background threads"""
        self.running = False
        if self.background_thread:
            self.background_thread.join(timeout=5)
        if self.filler_thread:
            self.filler_thread.join(timeout=5)
        print("[TradeLogger] Stopped")
    
    def log_trade_async(self, **kwargs):
        """
        Add trade to queue for async processing.
        Call this from bot main thread - returns immediately.
        """
        trade_data = {
            'pair': kwargs.get('pair', 'UNKNOWN'),
            'internal_ts': kwargs.get('internal_ts', datetime.now().isoformat()),
            'direction': kwargs.get('direction', ''),
            'ex1_data': kwargs.get('ex1_data', {}),
            'ex2_data': kwargs.get('ex2_data', {}),
            'limit_watch_status': kwargs.get('limit_watch_status', 'WATCHING'),
            'strategy': kwargs.get('strategy', 'USDT'),
            'spread_pct': kwargs.get('spread_pct', 0.0),
            'market_price_expected': kwargs.get('market_price_expected', 0),
            'limit_price_expected': kwargs.get('limit_price_expected', 0),
            'error_code': kwargs.get('error_code'),
            'error_message': kwargs.get('error_message'),
        }
        self.queue.put(trade_data)
    
    def _process_queue(self):
        """Process trades from queue"""
        while self.running:
            try:
                # Block for up to 1 second waiting for item
                trade_data = self.queue.get(timeout=1)
                
                # Write trade to CSV
                self._write_trade(trade_data)
                
                self.queue.task_done()
            except queue.Empty:
                continue
            except Exception as e:
                print(f"[TradeLogger] Error processing queue: {e}")
    
    def _write_trade(self, trade_data: Dict):
        """Write a single trade to CSV"""
        pair = trade_data['pair']
        csv_path = self._get_csv_path(pair)
        
        # Initialize CSV if needed
        self._ensure_csv_exists(csv_path)
        
        # Generate trade_id
        trade_id = self._generate_trade_id()
        
        # Build row data
        ex1_data = trade_data.get('ex1_data', {})
        ex2_data = trade_data.get('ex2_data', {})
        
        row = [
            trade_id,
            trade_data.get('internal_ts', ''),
            trade_data.get('direction', ''),
            pair,
            trade_data.get('strategy', 'USDT'),
            trade_data.get('spread_pct', 0),
            
            # ex1
            get_exchange_short_id(ex1_data.get('exchange', '')),
            ex1_data.get('order_id', ''),
            ex1_data.get('type', ''),
            ex1_data.get('side', ''),
            ex1_data.get('qty_ordered', 0),
            ex1_data.get('qty_filled', 0),
            ex1_data.get('price_expected', 0),
            ex1_data.get('price_actual', 0),
            ex1_data.get('price_avg', 0),
            ex1_data.get('value_usdt', 0),
            ex1_data.get('fees', 0),
            ex1_data.get('create_ts', 0),
            ex1_data.get('status', ''),
            
            # ex2
            get_exchange_short_id(ex2_data.get('exchange', '')),
            ex2_data.get('order_id', ''),
            ex2_data.get('type', ''),
            ex2_data.get('side', ''),
            ex2_data.get('qty_ordered', 0),
            ex2_data.get('qty_filled', 0),
            ex2_data.get('price_expected', 0),
            ex2_data.get('price_actual', 0),
            ex2_data.get('price_avg', 0),
            ex2_data.get('value_usdt', 0),
            ex2_data.get('fees', 0),
            ex2_data.get('create_ts', 0),
            ex2_data.get('status', ''),
            
            # profit
            trade_data.get('profit_usdt_expected', 0),
            trade_data.get('profit_mpc_expected', 0),
            0,  # profit_usdt_actual
            0,  # profit_mpc_actual
            
            # limit watch
            trade_data.get('limit_watch_status', 'WATCHING'),
            '',  # limit_last_check
            
            # error
            trade_data.get('error_code', ''),
            trade_data.get('error_message', ''),
            
            # metadata
            json.dumps(ex1_data.get('raw_response', {})),
            json.dumps(ex2_data.get('raw_response', {})),
            datetime.now().isoformat(),
        ]
        
        # Write to CSV
        try:
            with open(csv_path, 'a', newline='') as f:
                writer = csv.writer(f)
                writer.writerow(row)
            print(f"[TradeLogger] Trade logged: {trade_id}")
        except Exception as e:
            print(f"[TradeLogger] Error writing trade: {e}")
    
    def _background_filler(self):
        """
        Background filler - polls exchanges for missing trade data.
        Runs every 60 seconds.
        """
        while self.running:
            try:
                time.sleep(60)  # Check every minute
                
                # Find all CSV files
                for csv_file in LOG_DIR.glob("*_trades.csv"):
                    self._fill_missing_in_csv(csv_file)
                    
            except Exception as e:
                print(f"[TradeLogger] Filler error: {e}")
    
    def _fill_missing_in_csv(self, csv_path: Path):
        """Check CSV for missing data and fill via API calls"""
        try:
            # Read all rows
            with open(csv_path, 'r', newline='') as f:
                reader = csv.DictReader(f)
                rows = list(reader)
            
            if not rows:
                return
            
            modified = False
            
            # Check for missing ex2_create_ts or ex2_status
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
            
            # Write back if modified
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
        # TODO: Implement API call to get order timestamp
        # This would call KuCoin or MEXC API to get createTime
        return None
    
    def _fetch_order_status(self, exchange: str, order_id: str) -> Optional[str]:
        """Fetch order status from exchange API"""
        # TODO: Implement API call to get order status
        return None
    
    def _get_csv_path(self, pair: str) -> Path:
        """Get CSV path for a trading pair"""
        normalized = pair.replace('-', '').replace('/', '')
        return LOG_DIR / f"{normalized}_trades.csv"
    
    def _ensure_csv_exists(self, csv_path: Path):
        """Ensure CSV file exists with header"""
        if not csv_path.exists():
            with open(csv_path, 'w', newline='') as f:
                writer = csv.writer(f)
                writer.writerow(UNIFIED_COLUMNS)
    
    def _generate_trade_id(self) -> str:
        """Generate unique trade ID: YYYYMMDD_HHMMSS_MMMMMM"""
        now = datetime.now()
        return now.strftime("%Y%m%d_%H%M%S") + f"_{now.microsecond:06d}"
    
    # ========================================================================
    # READ METHODS - For Dashboard and other consumers
    # ========================================================================
    
    def get_trades(self, pair: str, limit: int = 50) -> List[Dict]:
        """Get trades from CSV for a trading pair"""
        csv_path = self._get_csv_path(pair)
        
        if not csv_path.exists():
            return []
        
        with open(csv_path, 'r', newline='') as f:
            reader = csv.DictReader(f)
            rows = list(reader)
        
        # Return latest first
        return list(reversed(rows))[:limit]
    
    def get_trade_summary(self, pair: str) -> Dict:
        """Get summary statistics for a trading pair"""
        trades = self.get_trades(pair, limit=1000)
        
        total_trades = len(trades)
        completed_trades = len([t for t in trades if t.get('limit_watch_status') == 'FILLED'])
        pending_limit = len([t for t in trades if t.get('limit_watch_status') == 'WATCHING'])
        
        # Calculate profit
        total_profit_usdt = sum(float(t.get('profit_usdt_actual', 0) or 0) for t in trades)
        total_profit_mpc = sum(float(t.get('profit_mpc_actual', 0) or 0) for t in trades)
        
        # Win rate
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


# Singleton instance
_instance = None

def get_logger() -> TradeLogger:
    """Get the TradeLogger singleton instance"""
    return TradeLogger.get_instance()

def log_trade_async(**kwargs):
    """Convenience function - add trade to queue for async processing"""
    get_logger().log_trade_async(**kwargs)