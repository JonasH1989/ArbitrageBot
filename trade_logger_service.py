"""
Trade Logger Service - Background Thread for Trade Logging

Architecture:
- Bot calls log_trade() (sync via trade_logger.py) - minimal, just records trade
- Logger service runs in background, polls exchanges for:
  - Limit order status updates (WATCHING → FILLED/PARTIAL)
  - Missing fees from myTrades/fills API
  - Multi-fill detection and row insertion
  - KuCoin timestamp fetching
- CSV is updated in-place with new rows and cell updates

Usage:
    from trade_logger_service import start
    start()  # Call once at bot startup
"""

import csv
import hmac
import hashlib
import json
import time
import threading
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional, Tuple

from trade_logger import to_float, UNIFIED_COLUMNS

LOG_DIR = Path("/app/logs")
CONFIG_PATH = Path("/app/config/config.yaml")

# Column indices (0-based) for efficient access
COL = {name: i for i, name in enumerate(UNIFIED_COLUMNS)}


class TradeLoggerService:
    """
    Background service for comprehensive trade data management.
    
    Responsibilities:
    - Poll limit orders for status updates (WATCHING → FILLED/PARTIAL)
    - Fetch missing fees from exchange APIs (myTrades/fills)
    - Detect multi-fills and insert additional rows
    - Fetch KuCoin timestamps via polling
    - Recalculate summary rows when all data is available
    """
    
    _instance = None
    _lock = threading.Lock()
    
    def __init__(self):
        self.running = False
        self.filler_thread = None
        self._csv_lock = threading.Lock()
        self._kucoin_keys = None
        self._mexc_keys = None
        
        # Load exchange credentials
        self._load_credentials()
    
    def _load_credentials(self):
        """Load API credentials from config"""
        if CONFIG_PATH.exists():
            import yaml
            with open(CONFIG_PATH, 'r') as f:
                config = yaml.safe_load(f)
            
            # KuCoin
            kucoin = config.get('kucoin', {})
            self._kucoin_keys = {
                'key': kucoin.get('api_key', ''),
                'secret': kucoin.get('api_secret', ''),
                'passphrase': kucoin.get('api_passphrase', '')
            }
            
            # MEXC
            mexc = config.get('mexc', {})
            self._mexc_keys = {
                'api_key': mexc.get('api_key', ''),
                'api_secret': mexc.get('api_secret', '')
            }
    
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
        
        self.filler_thread = threading.Thread(target=self._background_loop, daemon=True)
        self.filler_thread.start()
        
        print(f"[TradeLogger] Started - LOG_DIR={LOG_DIR}")
        print(f"[TradeLogger] Credentials loaded: KuCoin={'YES' if self._kucoin_keys else 'NO'}, MEXC={'YES' if self._mexc_keys else 'NO'}")
    
    def stop(self):
        """Stop the background thread"""
        self.running = False
        if self.filler_thread:
            self.filler_thread.join(timeout=5)
        print("[TradeLogger] Stopped")
    
    def _background_loop(self):
        """Main background loop - runs every 30 seconds"""
        while self.running:
            try:
                # Process each trading pair CSV
                for csv_file in LOG_DIR.glob("*_trades.csv"):
                    self._process_csv(csv_file)
                    
            except Exception as e:
                print(f"[TradeLogger] Main loop error: {e}")
            
            # Sleep 30 seconds between iterations
            time.sleep(30)
    
    def _process_csv(self, csv_path: Path):
        """Process a single CSV file - update pending trades"""
        with self._csv_lock:
            try:
                with open(csv_path, 'r', newline='') as f:
                    reader = csv.DictReader(f, delimiter=';')
                    rows = list(reader)
                
                if not rows:
                    return
                
                modified = False
                
                # Group rows by trade (main trade + its fill rows)
                trade_blocks = self._group_trade_blocks(rows)
                
                for block in trade_blocks:
                    main_row = block['main']
                    fill_rows = block['ex1_fills']
                    ex2sum_row = block['ex2sum']
                    limit_fill_rows = block['ex2_fills']
                    
                    trade_id = main_row['trade_id']
                    
                    # 1. Check limit order status (if WATCHING)
                    if ex2sum_row and ex2sum_row.get('limit_watch_status') == 'WATCHING':
                        result = self._check_limit_order(main_row, ex2sum_row, limit_fill_rows)
                        if result:
                            self._apply_limit_update(rows, block, result)
                            modified = True
                    
                    # 2. Check for multi-fills on ex1 (if qty_ordered != qty_filled)
                    ex1_ordered = to_float(main_row.get('ex1_qty_ordered', 0) or 0)
                    ex1_filled = to_float(main_row.get('ex1_qty_filled', 0) or 0)
                    if ex1_ordered > 0 and abs(ex1_ordered - ex1_filled) > 1:
                        # Possible multi-fill - check API
                        fills = self._fetch_all_fills_for_ex1(main_row)
                        if fills and len(fills) > len(fill_rows):
                            self._insert_ex1_fills(rows, block, fills)
                            modified = True
                    
                    # 3. Fetch missing fees
                    if self._update_missing_fees(main_row, fill_rows, ex2sum_row, limit_fill_rows):
                        modified = True
                
                if modified:
                    self._write_csv(csv_path, rows)
                    print(f"[TradeLogger] Updated {csv_path.name}")
                    
            except Exception as e:
                print(f"[TradeLogger] Error processing {csv_path}: {e}")
    
    def _group_trade_blocks(self, rows: List[Dict]) -> List[Dict]:
        """
        Group CSV rows into trade blocks.
        Each block contains: main row, ex1 fill rows, ex2sum row, ex2 fill rows
        """
        blocks = []
        current_block = None
        current_main_id = None
        
        for row in rows:
            trade_id = row.get('trade_id', '')
            
            # Main trade row (no suffix)
            if not any(suffix in trade_id for suffix in ['_ex1p', '_ex2p', '_ex2sum']):
                if current_block:
                    blocks.append(current_block)
                current_block = {
                    'main': row,
                    'ex1_fills': [],
                    'ex2sum': None,
                    'ex2_fills': []
                }
                current_main_id = trade_id
            
            elif '_ex1p' in trade_id and current_block:
                current_block['ex1_fills'].append(row)
            elif '_ex2sum' in trade_id and current_block:
                current_block['ex2sum'] = row
            elif '_ex2p' in trade_id and current_block:
                current_block['ex2_fills'].append(row)
        
        if current_block:
            blocks.append(current_block)
        
        return blocks
    
    def _check_limit_order(self, main_row: Dict, ex2sum_row: Dict, limit_fill_rows: List[Dict]) -> Optional[Dict]:
        """
        Check status of a limit order on exchange.
        Returns update dict if status changed, None otherwise.
        """
        ex2_exchange = ex2sum_row.get('ex2', '')
        ex2_order_id = ex2sum_row.get('ex2_order_id', '')
        
        if not ex2_order_id or ex2_order_id in ['FAILED', 'NOT_PLACED', '']:
            return None
        
        # Get pair for API calls
        pair = main_row.get('pair', 'MPC-USDT')
        
        try:
            if ex2_exchange.upper() == 'KCN':
                return self._check_kucoin_limit_order(ex2_order_id, pair)
            elif ex2_exchange.upper() == 'MXC':
                return self._check_mexc_limit_order(ex2_order_id, pair)
        except Exception as e:
            print(f"[TradeLogger] Error checking limit order {ex2_order_id}: {e}")
        
        return None
    
    def _check_kucoin_limit_order(self, order_id: str, pair: str) -> Optional[Dict]:
        """Check KuCoin limit order status"""
        if not self._kucoin_keys:
            return None
        
        try:
            import requests
            
            ts = str(int(time.time() * 1000))
            path = f'/api/v1/orders/{order_id}'
            sig = self._kucoin_sign(ts, 'GET', path)
            
            headers = {
                'KC-API-KEY': self._kucoin_keys['key'],
                'KC-API-SIGN': sig,
                'KC-API-TIMESTAMP': ts,
                'KC-API-PASSPHRASE': self._kucoin_keys['passphrase'],
                'KC-API-KEY-VERSION': '2'
            }
            
            resp = requests.get(f'https://api.kucoin.com{path}', headers=headers, timeout=10)
            data = resp.json()
            
            if data.get('code') != '200000':
                return None
            
            order_data = data.get('data', {})
            is_active = order_data.get('isActive', True)
            status = order_data.get('status', '')
            
            # Get fills for accurate qty/fees
            fills = self._fetch_kucoin_fills(order_id)
            
            total_qty = float(order_data.get('dealSize', 0) or 0)
            total_fees = 0.0
            if fills:
                for f in fills:
                    total_qty = sum(float(f.get('size', 0) or 0) for f in fills)
                    total_fees = sum(float(f.get('fee', 0) or 0) for f in fills)
            else:
                total_fees = float(order_data.get('fee', 0) or 0)
            
            # Order is done if: status='Done' OR (isActive=False AND dealSize > 0)
            if status == 'Done' or (not is_active and total_qty > 0):
                return {
                    'status': 'FILLED',
                    'qty_filled': total_qty,
                    'fees': total_fees,
                    'fills': fills
                }
            elif total_qty > 0 and is_active:
                return {
                    'status': 'PARTIAL',
                    'qty_filled': total_qty,
                    'fees': total_fees,
                    'fills': fills
                }
            
            return None
            
        except Exception as e:
            print(f"[TradeLogger] KuCoin order check error: {e}")
            return None
    
    def _check_mexc_limit_order(self, order_id: str, pair: str) -> Optional[Dict]:
        """Check MEXC limit order status"""
        if not self._mexc_keys:
            return None
        
        try:
            import requests
            
            symbol = pair.replace('-', '')
            ts = str(int(time.time() * 1000))
            params = f'symbol={symbol}&orderId={order_id}&timestamp={ts}'
            sig = hmac.new(
                self._mexc_keys['api_secret'].encode('utf-8'),
                params.encode('utf-8'),
                hashlib.sha256
            ).hexdigest()
            
            url = f'https://api.mexc.com/api/v3/order?{params}&signature=***'
            headers = {'X-MEXC-APIKEY': self._mexc_keys['api_key']}
            
            resp = requests.get(url, headers=headers, timeout=10)
            if resp.status_code != 200:
                return None
            
            order_data = resp.json()
            status = order_data.get('status', '')
            qty_filled = float(order_data.get('executedQty', 0) or 0)
            
            # Get fills for accurate fees
            fills = self._fetch_mexc_fills(order_id, symbol)
            total_fees = sum(float(f.get('commission', 0) or 0) for f in fills)
            
            if status == 'FILLED' and qty_filled > 0:
                return {
                    'status': 'FILLED',
                    'qty_filled': qty_filled,
                    'fees': total_fees,
                    'fills': fills
                }
            elif status == 'PARTIALLY_FILLED' and qty_filled > 0:
                return {
                    'status': 'PARTIAL',
                    'qty_filled': qty_filled,
                    'fees': total_fees,
                    'fills': fills
                }
            
            return None
            
        except Exception as e:
            print(f"[TradeLogger] MEXC order check error: {e}")
            return None
    
    def _fetch_kucoin_fills(self, order_id: str) -> List[Dict]:
        """Fetch all fills for a KuCoin order"""
        if not self._kucoin_keys:
            return []
        
        try:
            import requests
            
            ts = str(int(time.time() * 1000))
            path = f'/api/v1/fills?orderId={order_id}'
            sig = self._kucoin_sign(ts, 'GET', path)
            
            headers = {
                'KC-API-KEY': self._kucoin_keys['key'],
                'KC-API-SIGN': sig,
                'KC-API-TIMESTAMP': ts,
                'KC-API-PASSPHRASE': self._kucoin_keys['passphrase'],
                'KC-API-KEY-VERSION': '2'
            }
            
            resp = requests.get(f'https://api.kucoin.com{path}', headers=headers, timeout=10)
            data = resp.json()
            
            if data.get('code') != '200000':
                return []
            
            data_field = data.get('data', {})
            if isinstance(data_field, dict):
                items = data_field.get('items', [])
            else:
                items = data_field if isinstance(data_field, list) else []
            
            return items
            
        except Exception as e:
            print(f"[TradeLogger] KuCoin fills fetch error: {e}")
            return []
    
    def _fetch_mexc_fills(self, order_id: str, symbol: str) -> List[Dict]:
        """Fetch all fills (myTrades) for a MEXC order"""
        if not self._mexc_keys:
            return []
        
        try:
            import requests
            
            ts = str(int(time.time() * 1000))
            params = f'symbol={symbol}&timestamp={ts}'
            sig = hmac.new(
                self._mexc_keys['api_secret'].encode('utf-8'),
                params.encode('utf-8'),
                hashlib.sha256
            ).hexdigest()
            
            url = f'https://api.mexc.com/api/v3/myTrades?{params}&signature=***'
            headers = {'X-MEXC-APIKEY': self._mexc_keys['api_key']}
            
            resp = requests.get(url, headers=headers, timeout=10)
            if resp.status_code != 200:
                return []
            
            all_trades = resp.json()
            if not isinstance(all_trades, list):
                return []
            
            # Filter to our order
            our_trades = [t for t in all_trades if str(t.get('orderId', '')) == str(order_id)]
            return our_trades
            
        except Exception as e:
            print(f"[TradeLogger] MEXC fills fetch error: {e}")
            return []
    
    def _fetch_all_fills_for_ex1(self, main_row: Dict) -> List[Dict]:
        """Fetch all fills for ex1 (market order) to detect multi-fill"""
        ex1_exchange = main_row.get('ex1', '')
        ex1_order_id = main_row.get('ex1_order_id', '')
        pair = main_row.get('pair', 'MPC-USDT')
        
        if not ex1_order_id or ex1_order_id in ['FAILED', 'NOT_PLACED', '']:
            return []
        
        try:
            if ex1_exchange.upper() == 'KCN':
                return self._fetch_kucoin_fills(ex1_order_id)
            elif ex1_exchange.upper() == 'MXC':
                symbol = pair.replace('-', '')
                return self._fetch_mexc_fills(ex1_order_id, symbol)
        except Exception as e:
            print(f"[TradeLogger] Error fetching ex1 fills: {e}")
        
        return []
    
    def _apply_limit_update(self, rows: List[Dict], block: Dict, result: Dict):
        """Apply limit order update to rows"""
        ex2sum_row = block['ex2sum']
        main_row = block['main']
        
        new_status = result['status']
        qty_filled = result.get('qty_filled', 0)
        fees = result.get('fees', 0)
        fills = result.get('fills', [])
        
        # Update ex2sum row
        ex2sum_row['ex2_status'] = new_status
        ex2sum_row['limit_watch_status'] = new_status
        ex2sum_row['limit_last_check'] = datetime.now().isoformat()
        
        if qty_filled > 0:
            ex2sum_row['ex2_qty_filled'] = qty_filled
        if fees > 0:
            ex2sum_row['ex2_fees'] = fees
        
        # Recalculate actual profit
        ex1_value = to_float(main_row.get('ex1_value_usdt', 0) or 0)
        ex1_fees = to_float(main_row.get('ex1_fees', 0) or 0)
        ex2_value = qty_filled * to_float(ex2sum_row.get('ex2_price_actual', 0) or 0)
        
        profit_usdt_actual = ex2_value - ex1_value - ex1_fees - fees
        ex2sum_row['profit_usdt_actual'] = profit_usdt_actual
        
        # Calculate profit_mpc_actual
        ex1_qty_filled = to_float(main_row.get('ex1_qty_filled', 0) or 0)
        ex2sum_row['profit_mpc_actual'] = ex1_qty_filled - qty_filled
        
        # Insert fill rows if we have fills
        if fills and new_status == 'FILLED':
            self._insert_ex2_fills(rows, block, fills)
    
    def _insert_ex1_fills(self, rows: List[Dict], block: Dict, fills: List[Dict]):
        """Insert additional ex1 fill rows if missing"""
        main_row = block['main']
        existing_fills = block['ex1_fills']
        main_idx = rows.index(main_row)
        
        trade_id_base = main_row['trade_id']
        
        # Count existing fills
        existing_count = len(existing_fills)
        
        for i, fill in enumerate(fills):
            fill_idx = existing_count + i + 1  # ex1p1, ex1p2, ...
            fill_id = f"{trade_id_base}_ex1p{fill_idx}"
            
            # Check if this fill already exists
            if any(r.get('trade_id') == fill_id for r in existing_fills):
                continue
            
            # Create fill row
            fill_row = self._create_empty_row(fill_id)
            
            # Fill in data
            fill_row['ex1_qty_filled'] = float(fill.get('size', 0) or fill.get('qty', 0) or 0)
            fill_row['ex1_price_actual'] = float(fill.get('price', 0) or 0)
            fill_row['ex1_value_usdt'] = float(fill.get('funds', 0) or fill.get('quoteQty', 0) or 0)
            fill_row['ex1_fees'] = float(fill.get('fee', 0) or fill.get('commission', 0) or 0)
            fill_row['ex1_status'] = 'FILLED'
            
            # Insert after main row + existing fills
            insert_pos = main_idx + 1 + existing_count + i
            rows.insert(insert_pos, fill_row)
    
    def _insert_ex2_fills(self, rows: List[Dict], block: Dict, fills: List[Dict]):
        """Insert ex2 fill rows from fills data"""
        ex2sum_row = block['ex2sum']
        ex2_fills = block['ex2_fills']
        main_row = block['main']
        
        if not ex2sum_row or not fills:
            return
        
        trade_id_base = main_row['trade_id']
        
        # Find insertion point (after ex2sum)
        if ex2sum_row in rows:
            ex2sum_idx = rows.index(ex2sum_row)
        else:
            return
        
        # Count existing limit fills
        existing_count = len(ex2_fills)
        
        for i, fill in enumerate(fills):
            fill_idx = existing_count + i + 1  # ex2p1, ex2p2, ...
            fill_id = f"{trade_id_base}_ex2p{fill_idx}"
            
            # Check if this fill already exists
            if any(r.get('trade_id') == fill_id for r in ex2_fills):
                continue
            
            # Create fill row
            fill_row = self._create_empty_row(fill_id)
            
            # Fill in data
            fill_row['ex2_qty_filled'] = float(fill.get('size', 0) or fill.get('qty', 0) or 0)
            fill_row['ex2_price_actual'] = float(fill.get('price', 0) or 0)
            fill_row['ex2_value_usdt'] = float(fill.get('funds', 0) or fill.get('quoteQty', 0) or 0)
            fill_row['ex2_fees'] = float(fill.get('fee', 0) or fill.get('commission', 0) or 0)
            fill_row['ex2_status'] = 'FILLED'
            fill_row['limit_watch_status'] = 'FILLED'
            
            # Insert after ex2sum + existing fills
            insert_pos = ex2sum_idx + 1 + existing_count + i
            rows.insert(insert_pos, fill_row)
    
    def _update_missing_fees(self, main_row: Dict, ex1_fills: List[Dict], 
                              ex2sum_row: Optional[Dict], ex2_fills: List[Dict]) -> bool:
        """Fetch and update missing fees"""
        modified = False
        
        # Check ex1 fees
        ex1_fees = to_float(main_row.get('ex1_fees', 0) or 0)
        if ex1_fees == 0:
            order_id = main_row.get('ex1_order_id', '')
            exchange = main_row.get('ex1', '')
            pair = main_row.get('pair', 'MPC-USDT')
            
            fee = self._fetch_fees(exchange, order_id, pair)
            if fee and fee > 0:
                main_row['ex1_fees'] = fee
                modified = True
        
        # Check ex2 fees in ex2sum
        if ex2sum_row:
            ex2_fees = to_float(ex2sum_row.get('ex2_fees', 0) or 0)
            if ex2_fees == 0:
                order_id = ex2sum_row.get('ex2_order_id', '')
                exchange = ex2sum_row.get('ex2', '')
                pair = main_row.get('pair', 'MPC-USDT')
                
                fee = self._fetch_fees(exchange, order_id, pair)
                if fee and fee > 0:
                    ex2sum_row['ex2_fees'] = fee
                    modified = True
        
        return modified
    
    def _fetch_fees(self, exchange: str, order_id: str, pair: str) -> Optional[float]:
        """Fetch fees for an order from exchange"""
        if not order_id or order_id in ['FAILED', 'NOT_PLACED', '']:
            return None
        
        symbol = pair.replace('-', '')
        
        try:
            if exchange.upper() == 'KCN':
                fills = self._fetch_kucoin_fills(order_id)
                if fills:
                    return sum(float(f.get('fee', 0) or 0) for f in fills)
            elif exchange.upper() == 'MXC':
                fills = self._fetch_mexc_fills(order_id, symbol)
                if fills:
                    return sum(float(f.get('commission', 0) or 0) for f in fills)
        except Exception as e:
            print(f"[TradeLogger] Fee fetch error: {e}")
        
        return None
    
    def _kucoin_sign(self, timestamp: str, method: str, path: str) -> str:
        """Generate KuCoin API signature"""
        if not self._kucoin_keys:
            return ''
        
        message = f"{timestamp}{method}{path}"
        signature = hmac.new(
            self._kucoin_keys['secret'].encode('utf-8'),
            message.encode('utf-8'),
            hashlib.sha256
        ).hexdigest()
        return signature
    
    def _create_empty_row(self, trade_id: str) -> Dict:
        """Create an empty row with just trade_id"""
        return {col: '' for col in UNIFIED_COLUMNS}
    
    def _get_csv_path(self, pair: str) -> Path:
        """Get CSV path for a trading pair"""
        normalized = pair.replace('-', '').replace('/', '')
        return LOG_DIR / f"{normalized}_trades.csv"
    
    def get_trades(self, pair: str, limit: int = 50) -> List[Dict]:
        """Get trades from CSV - for dashboard"""
        csv_path = self._get_csv_path(pair)
        
        if not csv_path.exists():
            return []
        
        with self._csv_lock:
            with open(csv_path, 'r', newline='') as f:
                reader = csv.DictReader(f, delimiter=';')
                rows = list(reader)
        
        return list(reversed(rows))[:limit]
    
    def get_trade_summary(self, pair: str) -> Dict:
        """Get summary statistics"""
        trades = self.get_trades(pair, limit=1000)
        
        if not trades:
            return {
                'total_trades': 0,
                'completed_trades': 0,
                'pending_limit_orders': 0,
                'total_profit_usdt': 0,
                'total_profit_mpc': 0,
                'win_rate': '0%'
            }
        
        # Count main trades only (no suffixes)
        main_trades = [t for t in trades if not any(s in t.get('trade_id', '') for s in ['_ex1p', '_ex2p', '_ex2sum'])]
        total_trades = len(main_trades)
        completed_trades = len([t for t in main_trades if t.get('limit_watch_status') == 'FILLED'])
        pending_limit = len([t for t in main_trades if t.get('limit_watch_status') == 'WATCHING'])
        
        total_profit_usdt = sum(to_float(t.get('profit_usdt_actual', 0) or 0) for t in main_trades)
        total_profit_mpc = sum(to_float(t.get('profit_mpc_actual', 0) or 0) for t in main_trades)
        
        winning = len([t for t in main_trades if to_float(t.get('profit_usdt_actual', 0) or 0) > 0])
        win_rate = f"{(winning / total_trades * 100):.1f}%" if total_trades > 0 else "0%"
        
        return {
            'total_trades': total_trades,
            'completed_trades': completed_trades,
            'pending_limit_orders': pending_limit,
            'total_profit_usdt': total_profit_usdt,
            'total_profit_mpc': total_profit_mpc,
            'win_rate': win_rate,
        }
    
    def _fmt_value(self, val) -> str:
        """Format numeric value with comma as decimal separator."""
        if val is None or val == "":
            return ""
        if isinstance(val, str):
            return val
        if isinstance(val, (int, float)) and not isinstance(val, bool):
            return str(val).replace('.', ',')
        return str(val)
    
    def _prepare_row(self, row: Dict) -> Dict:
        """Prepare row for CSV writing - convert numeric values to comma format."""
        prepared = {}
        for col, val in row.items():
            if isinstance(val, (int, float)) and not isinstance(val, bool):
                prepared[col] = self._fmt_value(val)
            else:
                prepared[col] = val
        return prepared
    
    def _write_csv(self, csv_path: Path, rows: List[Dict]):
        """Write rows back to CSV"""
        with open(csv_path, 'w', newline='') as f:
            writer = csv.DictWriter(f, fieldnames=UNIFIED_COLUMNS, delimiter=';')
            writer.writeheader()
            # Prepare rows with comma decimals
            prepared_rows = [self._prepare_row(row) for row in rows]
            writer.writerows(prepared_rows)


# ========================================================================
# Module-level functions
# ========================================================================

_instance = None

def get_instance() -> TradeLoggerService:
    global _instance
    if _instance is None:
        _instance = TradeLoggerService.get_instance()
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