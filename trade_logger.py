"""
Trade Logger - Harmonized Multi-Exchange Trade Capture
New Format (2026-05-16): One CSV per trading pair, multiple rows per trade.

Structure per trade:
- Row 1: Main trade (summaries) - trade_id without suffix
- Row 2+: ex1p1, ex1p2... - Market (ex1) partial fills
- ex2sum row: Limit order summary
- ex2p1, ex2p2... - Limit (ex2) partial fills

Harmonization: Exchange-specific API responses are normalized into
a unified schema so data is comparable across exchanges.
"""
import csv
import os
import json
import sys
import time
from datetime import datetime
from pathlib import Path
from typing import Dict, Optional, List, Tuple

LOG_DIR = Path("/app/logs")

# Helper for locale-independent float parsing
def to_float(val):
    """Parse float from string, handling comma decimal separator."""
    if isinstance(val, str):
        val = val.replace(',', '.')
    return float(val or 0)

# =============================================================================
# DEBUG LOGGING
# =============================================================================
DEBUG_LOG_FILE = LOG_DIR / "trade_logger_debug.log"
LOG_FILE = LOG_DIR / "arb_autotrade.log"  # Shared with arb_autotrade.py

def debug_log(message: str, level: str = "INFO"):
    """Log debug messages to both stderr, debug file AND the main bot log"""
    ts = datetime.now().strftime('%Y-%m-%d %H:%M:%S.%f')[:-3]
    log_line = f"[{ts}] [{level}] {message}"
    print(log_line, file=sys.stderr)
    
    # Also write to main bot log file (same as log() function)
    try:
        LOG_DIR.mkdir(parents=True, exist_ok=True)
        with open(LOG_FILE, 'a') as f:
            f.write(log_line + "\n")
    except Exception as e:
        print(f"DEBUG: Could not write to log file: {e}", file=sys.stderr)
    
    # Also write to debug file
    try:
        with open(DEBUG_LOG_FILE, 'a') as f:
            f.write(log_line + "\n")
    except Exception as e:
        print(f"DEBUG: Could not write to debug log: {e}", file=sys.stderr)

def debug_trade_write(trade_id: str, row_num: int, columns: Dict):
    """Log details about a row being written"""
    debug_log(f"TRADE_WRITE: {trade_id} | Row {row_num}")
    for k, v in columns.items():
        if v:
            debug_log(f"  {k}: {v}")

# =============================================================================
# EXCHANGE CONFIG
# =============================================================================
_EXCHANGE_CONFIG = None

def get_exchange_config() -> Dict:
    """Load exchange config from config.yaml"""
    global _EXCHANGE_CONFIG
    if _EXCHANGE_CONFIG is None:
        config_path = Path('/app/config/config.yaml')
        if config_path.exists():
            import yaml
            with open(config_path, 'r') as f:
                config = yaml.safe_load(f)
                _EXCHANGE_CONFIG = config.get('exchanges', {})
        else:
            _EXCHANGE_CONFIG = {}
    return _EXCHANGE_CONFIG

def get_exchange_short_id(exchange_name: str) -> str:
    """Get short_id for an exchange (e.g. 'KUCOIN' -> 'KCN')
    
    Falls back to hardcoded values if not in config:
    - KUCOIN -> KCN
    - MEXC -> MXC
    """
    config = get_exchange_config()
    exchange_lower = exchange_name.lower()
    
    # Check config first
    if exchange_lower in config:
        short = config[exchange_lower].get('short_id')
        if short:
            return short
    
    # Hardcoded fallback - these should match TRADE_LOG_STRUCTURE.md
    fallback_map = {
        'kucoin': 'KCN',
        'mexc': 'MXC',
        'binance': 'BNC',
    }
    
    if exchange_lower in fallback_map:
        return fallback_map[exchange_lower]
    
    return exchange_name[:3].upper()

# =============================================================================
# UNIFIED COLUMNS (43 columns - Col 2-44 in XLSX)
# Col 1 = COMMENT (Hilfsfeld, nicht in CSV)
# Col 2-44 = 43 DB-Spalten
# =============================================================================
UNIFIED_COLUMNS = [
    # Col 1: trade_id - Unique ID (DDHHMMSSms hex)
    "trade_id",
    # Col 2: internal_ts - When BOT initiated the trade (ISO format)
    "internal_ts",
    # Col 3: direction - "KCN->MXC" or "MXC->KCN"
    "direction",
    # Col 4: pair - Trading pair e.g. "MPC-USDT"
    "pair",
    # Col 5: strategy - "USDT" or "COINS"
    "strategy",
    # Col 6: spread_pct - Spread in % when trade was triggered
    "spread_pct",
    
    # Col 7-19: ex1 (Market order)
    # Col 7: ex1 - Exchange short_id
    "ex1",
    # Col 8: ex1_order_id
    "ex1_order_id",
    # Col 9: ex1_type - "market" (hardcoded)
    "ex1_type",
    # Col 10: ex1_side - "buy" or "sell"
    "ex1_side",
    # Col 11: ex1_qty_ordered
    "ex1_qty_ordered",
    # Col 12: ex1_qty_filled - Sum of all partial fills
    "ex1_qty_filled",
    # Col 13: ex1_price_expected
    "ex1_price_expected",
    # Col 14: ex1_price_actual - Weighted avg of all fills
    "ex1_price_actual",
    # Col 15: ex1_value_usdt - Sum of all fill values
    "ex1_value_usdt",
    # Col 16: ex1_fees - Sum of all fees
    "ex1_fees",
    # Col 17: ex1_create_ts - When order was created on exchange
    "ex1_create_ts",
    # Col 18: ex1_fill_ts - When fill(s) actually happened (NEW!)
    "ex1_fill_ts",
    # Col 19: ex1_status
    "ex1_status",
    
    # Col 20-32: ex2 (Limit order)
    # Col 20: ex2 - Exchange short_id
    "ex2",
    # Col 21: ex2_order_id
    "ex2_order_id",
    # Col 22: ex2_type - "limit" (hardcoded)
    "ex2_type",
    # Col 23: ex2_side - "buy" or "sell"
    "ex2_side",
    # Col 24: ex2_qty_ordered
    "ex2_qty_ordered",
    # Col 25: ex2_qty_filled - Sum of partial fills
    "ex2_qty_filled",
    # Col 26: ex2_price_expected
    "ex2_price_expected",
    # Col 27: ex2_price_actual - Weighted avg
    "ex2_price_actual",
    # Col 28: ex2_value_usdt
    "ex2_value_usdt",
    # Col 29: ex2_fees
    "ex2_fees",
    # Col 30: ex2_create_ts - When order was created on exchange
    "ex2_create_ts",
    # Col 31: ex2_fill_ts - When fill(s) actually happened (NEW!)
    "ex2_fill_ts",
    # Col 32: ex2_status
    # ex2_status: "FILLED" when all fills complete
    "ex2_status",
    # Col 38: error_code
    "error_code",
    # Col 39: error_message
    "error_message",
    
    # Col 40-43: Raw responses (Col 41-44 in XLSX, aber Col 1 ist COMMENT)
    # Col 40: raw_ex1_response
    "raw_ex1_response",
    # Col 41: raw_ex1_response_ts
    "raw_ex1_response_ts",
    # Col 42: raw_ex2_response
    "raw_ex2_response",
    # Col 43: raw_ex2_response_ts
    "raw_ex2_response_ts",
]


def ensure_log_dir():
    """Ensure log directory exists"""
    LOG_DIR.mkdir(parents=True, exist_ok=True)


def get_trade_csv_path(pair: str) -> Path:
    """Get CSV file path for a trading pair"""
    # Normalize pair format: MPCUSDT OR MPC-USDT -> MPCUSDT
    normalized_pair = pair.replace("-", "").upper()
    if not normalized_pair.endswith("USDT"):
        normalized_pair += "USDT"
    return LOG_DIR / f"{normalized_pair}_trades.csv"


def init_pair_csv(pair: str) -> Path:
    """Initialize CSV file for a trading pair if it doesn't exist"""
    ensure_log_dir()
    csv_path = get_trade_csv_path(pair)
    
    print(f"DEBUG init_pair_csv: pair={pair}, csv_path={csv_path}, exists={csv_path.exists()}")
    
    if not csv_path.exists():
        with open(csv_path, 'w', newline='') as f:
            writer = csv.writer(f, delimiter=';')
            writer.writerow(UNIFIED_COLUMNS)
        debug_log(f"CSV initialized: {csv_path}")
        print(f"DEBUG init_pair_csv: CSV file created at {csv_path}")
    else:
        print(f"DEBUG init_pair_csv: CSV already exists at {csv_path}")
    
    return csv_path


def generate_trade_id() -> str:
    """
    Generate unique trade ID in format: DDHHMMSSms (hex)
    
    Example: 0c1500372b (10 chars)
    
    Contains: DD (day) + HH (hour) + MM (minute) + SS (second) + ms (milliseconds)
    """
    now = datetime.now()
    dd = now.strftime("%d")
    hh = now.strftime("%H")
    mm = now.strftime("%M")
    ss = now.strftime("%S")
    ms = now.strftime("%f")[:2]
    
    return f"{int(dd):02x}{int(hh):x}{int(mm):x}{int(ss):x}{int(ms):02x}"


# =============================================================================
# HARMONIZATION FUNCTIONS
# =============================================================================

def harmonize_kucoin_order(response: dict, side: str, order_type: str, pair: str) -> Dict:
    """
    Harmonize KuCoin order response to unified format.
    """
    deal_size = float(response.get('dealSize', 0) or 0)
    deal_funds = float(response.get('dealFunds', 0) or 0)
    price_actual = deal_funds / deal_size if deal_size > 0 else 0
    
    status_map = {
        "Done": "FILLED",
        "Active": "OPEN",
        "cancelled": "CANCELLED",
    }
    raw_status = response.get('status', '')
    unified_status = status_map.get(raw_status, raw_status)
    
    return {
        "exchange": "KUCOIN",
        "order_id": response.get('orderId', ''),
        "type": order_type,
        "side": side.lower(),
        "qty_ordered": float(response.get('size', 0) or 0),
        "qty_filled": deal_size,
        "price_expected": 0.0,  # Set by caller
        "price_actual": price_actual,
        "value_usdt": deal_funds,
        "fees": float(response.get('fee', 0) or 0),
        "create_ts": int(response.get('createTime', 0) or 0),
        "status": unified_status,
        "raw_response": response,
    }


def harmonize_mexc_order(response: dict, side: str, order_type: str, pair: str) -> Dict:
    """
    Harmonize MEXC order response to unified format.
    """
    if order_type == "market":
        qty_filled = float(response.get('quantity', 0) or 0)
        value_usdt = float(response.get('amount', 0) or 0)
        qty_ordered = float(response.get('orderQuantity', 0) or 0)
        price_actual = value_usdt / qty_filled if qty_filled > 0 else 0
    else:  # limit
        qty_filled = float(response.get('dealQuantity', 0) or 0)
        value_usdt = float(response.get('dealAmount', 0) or 0)
        qty_ordered = float(response.get('quantity', 0) or 0)
        price_actual = float(response.get('price', 0) or 0)
    
    status_map = {
        "Filled": "FILLED",
        "PartiallyFilled": "PARTIAL",
        "New": "OPEN",
        "Cancelled": "CANCELLED",
    }
    raw_status = response.get('status', '')
    unified_status = status_map.get(raw_status, raw_status)
    
    return {
        "exchange": "MEXC",
        "order_id": response.get('orderId', ''),
        "type": order_type,
        "side": side.lower(),
        "qty_ordered": qty_ordered,
        "qty_filled": qty_filled,
        "price_expected": 0.0,
        "price_actual": price_actual,
        "value_usdt": value_usdt,
        "fees": float(response.get('fees', 0) or 0),
        "create_ts": int(response.get('createTime', 0) or 0),
        "status": unified_status,
        "raw_response": response,
    }


def harmonize_order(response: dict, exchange: str, side: str, order_type: str, pair: str) -> Dict:
    """Route to correct harmonizer based on exchange"""
    if exchange.upper() == "KUCOIN":
        return harmonize_kucoin_order(response, side, order_type, pair)
    elif exchange.upper() == "MEXC":
        return harmonize_mexc_order(response, side, order_type, pair)
    else:
        raise ValueError(f"Unknown exchange: {exchange}")


# =============================================================================
# HELPER: Create empty row for a trade
# =============================================================================


def fmt(value, decimals=None) -> str:
    """Format a numeric value with comma as decimal separator.
    
    Args:
        value: The numeric value to format
        decimals: Number of decimal places (None = use default formatting)
    """
    if value is None or value == "":
        return ""
    if isinstance(value, str):
        return value
    # It's a number
    if decimals is not None:
        formatted = f"{float(value):.{decimals}f}"
    else:
        formatted = str(float(value))
    return formatted.replace('.', ',')


def create_empty_row(trade_id: str) -> dict:
    """Create a row dict with all columns initialized to empty/zero"""
    row = {col: "" for col in UNIFIED_COLUMNS}
    row["trade_id"] = trade_id
    return row



def row_to_list(row: dict) -> list:
    """Convert row dict to list in column order, with comma decimals.
    
    MPC qty columns use 2 decimal places (exchange precision).
    Price columns use 6 decimals.
    USDT values use 4 decimals.
    """
    # Define column-specific decimal precision
    MPC_QTY_COLS = {'ex1_qty_ordered', 'ex1_qty_filled', 'ex2_qty_ordered', 'ex2_qty_filled',
                    'profit_mpc_expected', 'profit_mpc_actual'}
    PRICE_COLS = {'ex1_price_expected', 'ex1_price_actual', 'ex2_price_expected', 'ex2_price_actual'}
    USDT_COLS = {'ex1_value_usdt', 'ex1_fees', 'ex2_value_usdt', 'ex2_fees', 
                 'profit_usdt_expected', 'profit_usdt_actual'}
    
    result = []
    for col in UNIFIED_COLUMNS:
        val = row.get(col, "")
        # Only convert numeric values (int/float) to comma format
        if isinstance(val, (int, float)) and not isinstance(val, bool):
            if col in MPC_QTY_COLS:
                val = fmt(val, decimals=2)
            elif col in PRICE_COLS:
                val = fmt(val, decimals=6)
            elif col in USDT_COLS:
                val = fmt(val, decimals=4)
            else:
                val = fmt(val)
        result.append(str(val) if val is not None else "")
    return result


# =============================================================================
# MAIN LOG FUNCTION
# =============================================================================

def log_trade(
    pair: str,
    internal_ts: str,
    direction: str,
    ex1_data: Dict,         # Harmonized data from market exchange
    ex2_data: Dict,         # Harmonized data from limit exchange (may be partial)
    ex1_partial_fills: List[Dict] = None,  # List of individual fill data
    ex2_partial_fills: List[Dict] = None,  # List of individual limit fill data
    strategy: str = "USDT",
    spread_pct: float = 0.0,
    market_price_expected: float = 0.0,
    limit_price_expected: float = 0.0,
    profit_usdt_expected: float = 0.0,
    profit_mpc_expected: float = 0.0,
    error_code: str = None,
    error_message: str = None,
) -> str:
    """
    Log a complete trade to the pair-specific CSV.
    
    Writes MULTIPLE rows per trade:
    - Row 1: Main trade (summaries)
    - Row 2+: ex1p1, ex1p2... (Market partial fills)
    - ex2sum row: Limit order summary
    - ex2p1, ex2p2... (Limit partial fills)
    
    Args:
        pair: Trading pair e.g. "MPC-USDT"
        internal_ts: Internal timestamp after successful balance check
        direction: "KCN->MXC" or "MXC->KCN"
        ex1_data: Harmonized data from market exchange
        ex2_data: Harmonized data from limit exchange
        ex1_partial_fills: List of individual fill dicts from polling
        ex2_partial_fills: List of individual limit fill dicts
        strategy: "USDT" or "COINS"
        spread_pct: Spread in % (3 decimals)
        market_price_expected: Expected price at initiation
        limit_price_expected: Expected price at initiation
        profit_usdt_expected: Expected USDT profit
        profit_mpc_expected: Expected MPC profit
        error_code: Error code if trade had errors
        error_message: Error message if trade had errors
    
    Returns:
        trade_id: Generated trade ID
    """
    trade_id = generate_trade_id()
    debug_log(f"LOG_TRADE: Starting for trade_id={trade_id}")
    
    print(f"DEBUG log_trade ENTRY: trade_id={trade_id}, pair={pair}")
    
    # Initialize defaults
    if ex1_partial_fills is None:
        ex1_partial_fills = []
    if ex2_partial_fills is None:
        ex2_partial_fills = []
    
    # Normalize pair for filename
    csv_path = init_pair_csv(pair)
    debug_log(f"LOG_TRADE: CSV path={csv_path}")
    print(f"DEBUG log_trade: After init_pair_csv, csv_path={csv_path}")
    
    # Prepare ex1 data
    ex1_exchange = get_exchange_short_id(ex1_data.get("exchange", ""))
    ex1_order_id = ex1_data.get("order_id", "")
    ex1_qty_ordered = ex1_data.get("qty_ordered", 0)
    
    # Convert Unix ms timestamp to readable format
    ex1_ts_raw = ex1_data.get("create_ts", 0)
    if ex1_ts_raw and int(ex1_ts_raw) > 0:
        ex1_create_ts = datetime.fromtimestamp(int(ex1_ts_raw) / 1000).strftime("%Y-%m-%d %H:%M:%S.%f")[:-3]
    else:
        ex1_create_ts = ""
    
    raw_ex1_response = json.dumps(ex1_data.get("raw_response", {}))
    
    # Calculate ex1 summaries from partial fills
    ex1_qty_filled = sum(f.get('qty_filled', 0) for f in ex1_partial_fills) if ex1_partial_fills else ex1_data.get('qty_filled', 0)
    ex1_value_usdt = sum(f.get('value_usdt', 0) for f in ex1_partial_fills) if ex1_partial_fills else ex1_data.get('value_usdt', 0)
    ex1_fees = sum(f.get('fees', 0) for f in ex1_partial_fills) if ex1_partial_fills else ex1_data.get('fees', 0)
    
    # Calculate weighted average price
    if ex1_qty_filled > 0:
        ex1_price_actual = ex1_value_usdt / ex1_qty_filled
    else:
        ex1_price_actual = 0
    
    # Set price_expected from caller
    ex1_price_expected = market_price_expected if market_price_expected > 0 else ex1_data.get('price_expected', 0)
    
    # Determine ex1_status
    ex1_status = "FILLED" if ex1_qty_filled >= ex1_qty_ordered else "PARTIAL"
    
    debug_log(f"LOG_TRADE: ex1 qty_ordered={ex1_qty_ordered}, qty_filled={ex1_qty_filled}, status={ex1_status}")
    
    # Prepare ex2 data
    ex2_exchange = get_exchange_short_id(ex2_data.get("exchange", ""))
    ex2_order_id = ex2_data.get("order_id", "")
    ex2_qty_ordered = ex2_data.get("qty_ordered", 0)
    
    # Convert Unix ms timestamp to readable format
    ex2_ts_raw = ex2_data.get("create_ts", 0)
    if ex2_ts_raw and int(ex2_ts_raw) > 0:
        ex2_create_ts = datetime.fromtimestamp(int(ex2_ts_raw) / 1000).strftime("%Y-%m-%d %H:%M:%S.%f")[:-3]
    else:
        ex2_create_ts = ""
    
    raw_ex2_response = json.dumps(ex2_data.get("raw_response", {}))
    raw_ex2_response_ts = datetime.now().isoformat() if ex2_data.get("raw_response") else ""
    
    # Calculate ex2 summaries from partial fills
    ex2_qty_filled = sum(f.get('qty_filled', 0) for f in ex2_partial_fills) if ex2_partial_fills else ex2_data.get('qty_filled', 0)
    ex2_value_usdt = sum(f.get('value_usdt', 0) for f in ex2_partial_fills) if ex2_partial_fills else ex2_data.get('value_usdt', 0)
    ex2_fees = sum(f.get('fees', 0) for f in ex2_partial_fills) if ex2_partial_fills else ex2_data.get('fees', 0)
    
    if ex2_qty_filled > 0:
        ex2_price_actual = ex2_value_usdt / ex2_qty_filled
    else:
        ex2_price_actual = 0
    
    ex2_price_expected = limit_price_expected if limit_price_expected > 0 else ex2_data.get('price_expected', 0)
    
    debug_log(f"LOG_TRADE: ex2 qty_ordered={ex2_qty_ordered}, qty_filled={ex2_qty_filled}")
    
    # Note: profit_mpc_actual and profit_usdt_actual are calculated in update_limit_watch()
    # when the limit order is actually FILLED. At this point ex2 is not yet filled.
    # Initial values are 0 - will be updated later.
    
    # ==========================================================================
    # BUILD ROWS
    # ==========================================================================
    rows_to_write = []
    
    # --------------------------------------------------------------------------
    # ROW 1: Main trade (summaries)
    # --------------------------------------------------------------------------
    row1 = create_empty_row(trade_id)
    row1["internal_ts"] = internal_ts
    row1["direction"] = direction
    row1["pair"] = pair
    row1["strategy"] = strategy
    row1["spread_pct"] = spread_pct  # Float - will be formatted with comma by row_to_list()
    row1["ex1"] = ex1_exchange
    row1["ex1_order_id"] = ex1_order_id
    row1["ex1_type"] = "market"
    row1["ex1_side"] = ex1_data.get("side", "")
    row1["ex1_qty_ordered"] = ex1_qty_ordered
    row1["ex1_qty_filled"] = ex1_qty_filled
    row1["ex1_price_expected"] = ex1_price_expected
    row1["ex1_price_actual"] = ex1_price_actual
    row1["ex1_value_usdt"] = ex1_value_usdt
    row1["ex1_fees"] = ex1_fees
    row1["ex1_create_ts"] = ex1_create_ts
    row1["ex1_status"] = ex1_status
    row1["error_code"] = error_code or ""
    row1["error_message"] = error_message or ""
    row1["raw_ex1_response"] = raw_ex1_response
    
    rows_to_write.append(row1)
    debug_trade_write(trade_id, 1, row1)
    
    # --------------------------------------------------------------------------
    # ROWS 2+: ex1 partial fills (ex1p1, ex1p2...)
    # --------------------------------------------------------------------------
    for i, fill in enumerate(ex1_partial_fills):
        row_n = create_empty_row(f"{trade_id}_ex1p{i+1}")
        row_n["ex1_qty_filled"] = fill.get('qty_filled', 0)
        row_n["ex1_price_actual"] = fill.get('price_actual', 0)
        row_n["ex1_value_usdt"] = fill.get('value_usdt', 0)
        row_n["ex1_fees"] = fill.get('fees', 0)
        row_n["ex1_create_ts"] = fill.get('create_ts', ex1_create_ts)  # Fallback
        row_n["ex1_fill_ts"] = fill.get('fill_ts', ex1_create_ts)  # When fill happened
        # Convert Unix ms to readable format for partial fills too
        if row_n["ex1_create_ts"]:
            try:
                ts_val = int(row_n["ex1_create_ts"])
                if ts_val > 0:
                    row_n["ex1_create_ts"] = datetime.fromtimestamp(ts_val / 1000).strftime("%Y-%m-%d %H:%M:%S.%f")[:-3]
            except:
                pass  # Keep as-is if conversion fails
        # Also convert fill_ts
        if row_n["ex1_fill_ts"]:
            try:
                ts_val = int(row_n["ex1_fill_ts"])
                if ts_val > 0:
                    row_n["ex1_fill_ts"] = datetime.fromtimestamp(ts_val / 1000).strftime("%Y-%m-%d %H:%M:%S.%f")[:-3]
            except:
                pass  # Keep as-is if conversion fails
        row_n["ex1_status"] = "FILLED"
        rows_to_write.append(row_n)
        debug_trade_write(trade_id, f"ex1p{i+1}", row_n)
    
    # --------------------------------------------------------------------------
    # ex2sum row: Limit order summary
    # --------------------------------------------------------------------------
    ex2sum_row = create_empty_row(f"{trade_id}_ex2sum")
    ex2sum_row["ex2"] = ex2_exchange
    ex2sum_row["ex2_order_id"] = ex2_order_id
    ex2sum_row["ex2_type"] = "limit"
    ex2sum_row["ex2_side"] = ex2_data.get("side", "")
    ex2sum_row["ex2_qty_ordered"] = ex2_qty_ordered
    ex2sum_row["ex2_qty_filled"] = ex2_qty_filled
    ex2sum_row["ex2_price_expected"] = ex2_price_expected
    ex2sum_row["ex2_price_actual"] = ex2_price_actual
    ex2sum_row["ex2_value_usdt"] = ex2_value_usdt
    ex2sum_row["ex2_fees"] = ex2_fees
    ex2sum_row["ex2_create_ts"] = ex2_create_ts
    ex2sum_row["ex2_status"] = "FILLED" if ex2_qty_filled >= ex2_qty_ordered else "OPEN"
    ex2sum_row["profit_usdt_expected"] = profit_usdt_expected
    ex2sum_row["profit_mpc_expected"] = profit_mpc_expected
    ex2sum_row["profit_mpc_actual"] = profit_mpc_actual
    ex2sum_row["limit_last_check"] = datetime.now().isoformat()
    ex2sum_row["raw_ex2_response"] = raw_ex2_response
    ex2sum_row["raw_ex2_response_ts"] = raw_ex2_response_ts
    
    rows_to_write.append(ex2sum_row)
    debug_trade_write(trade_id, "ex2sum", ex2sum_row)
    
    # --------------------------------------------------------------------------
    # ex2p1, ex2p2... rows: Individual limit fills
    # --------------------------------------------------------------------------
    for i, fill in enumerate(ex2_partial_fills):
        row_n = create_empty_row(f"{trade_id}_ex2p{i+1}")
        row_n["ex2_qty_ordered"] = fill.get('qty_ordered', 0)
        row_n["ex2_qty_filled"] = fill.get('qty_filled', 0)
        row_n["ex2_price_actual"] = fill.get('price_actual', 0)
        row_n["ex2_value_usdt"] = fill.get('value_usdt', 0)
        row_n["ex2_fees"] = fill.get('fees', 0)
        row_n["ex2_create_ts"] = fill.get('create_ts', ex2_create_ts)
        row_n["ex2_fill_ts"] = fill.get('fill_ts', ex2_create_ts)  # When fill happened
        # Convert Unix ms to readable format for partial fills too
        if row_n["ex2_create_ts"]:
            try:
                ts_val = int(row_n["ex2_create_ts"])
                if ts_val > 0:
                    row_n["ex2_create_ts"] = datetime.fromtimestamp(ts_val / 1000).strftime("%Y-%m-%d %H:%M:%S.%f")[:-3]
            except:
                pass  # Keep as-is if conversion fails
        # Also convert fill_ts
        if row_n["ex2_fill_ts"]:
            try:
                ts_val = int(row_n["ex2_fill_ts"])
                if ts_val > 0:
                    row_n["ex2_fill_ts"] = datetime.fromtimestamp(ts_val / 1000).strftime("%Y-%m-%d %H:%M:%S.%f")[:-3]
            except:
                pass  # Keep as-is if conversion fails
        row_n["ex2_status"] = "FILLED"
        rows_to_write.append(row_n)
        debug_trade_write(trade_id, f"ex2p{i+1}", row_n)
    
    # ==========================================================================
    # WRITE ALL ROWS TO CSV
    # ==========================================================================
    debug_log(f"LOG_TRADE: Writing {len(rows_to_write)} rows for {trade_id}")
    
    try:
        with open(csv_path, 'a', newline='') as f:
            writer = csv.writer(f, delimiter=';')
            for row in rows_to_write:
                writer.writerow(row_to_list(row))
        debug_log(f"LOG_TRADE: Successfully wrote {len(rows_to_write)} rows")
    except Exception as e:
        debug_log(f"LOG_TRADE: ERROR writing to CSV: {e}", "ERROR")
        raise
    
    return trade_id


# =============================================================================
# LIMIT ORDER ROW FUNCTIONS
# Handle ex2pN rows (individual limit orders)
# =============================================================================

def get_ex2p_rows(trade_id: str, pair: str) -> List[Dict]:
    """Get all ex2pN rows for a trade."""
    csv_path = get_trade_csv_path(pair)
    if not csv_path.exists():
        return []
    
    rows = []
    with open(csv_path, 'r', newline='') as f:
        reader = csv.DictReader(f, delimiter=';')
        for row in reader:
            tid = row.get('trade_id', '')
            if tid.startswith(f"{trade_id}_ex2p"):
                rows.append(row)
    return rows

def find_ex2p_by_order_id(trade_id: str, pair: str, order_id: str) -> Optional[Dict]:
    """Find ex2p row by trade_id and order_id."""
    rows = get_ex2p_rows(trade_id, pair)
    for row in rows:
        if row.get('ex2_order_id') == order_id:
            return row
    return None

def get_highest_ex2p_suffix(trade_id: str, pair: str) -> int:
    """Get the highest ex2pN suffix number for a trade."""
    rows = get_ex2p_rows(trade_id, pair)
    max_num = 0
    for row in rows:
        tid = row.get('trade_id', '')
        if tid.startswith(f"{trade_id}_ex2p"):
            try:
                num = int(tid.split('_ex2p')[1])
                if num > max_num:
                    max_num = num
            except:
                pass
    return max_num

def append_limit_row(
    pair: str,
    trade_id: str,
    exchange: str,
    order_id: str,
    side: str,
    qty_ordered: float,
    qty_filled: float = 0,
    price_actual: float = 0,
    value_usdt: float = 0,
    fees: float = 0,
    create_ts: str = "",
    fill_ts: str = "",
    ex2_status: str = "OPEN",
) -> bool:
    """Append a new ex2pN row to the CSV."""
    csv_path = get_trade_csv_path(pair)
    if not csv_path.exists():
        debug_log(f"APPEND_LIMIT_ROW: CSV not found for {pair}", "WARNING")
        return False
    
    # Determine next suffix
    suffix_num = get_highest_ex2p_suffix(trade_id, pair) + 1
    new_row_id = f"{trade_id}_ex2p{suffix_num}"
    
    row = create_empty_row(new_row_id)
    row["ex2"] = get_exchange_short_id(exchange)
    row["ex2_order_id"] = order_id
    row["ex2_type"] = "limit"
    row["ex2_side"] = side
    row["ex2_qty_ordered"] = qty_ordered
    row["ex2_qty_filled"] = qty_filled
    row["ex2_price_actual"] = price_actual
    row["ex2_value_usdt"] = value_usdt
    row["ex2_fees"] = fees
    row["ex2_create_ts"] = create_ts
    row["ex2_fill_ts"] = fill_ts
    row["ex2_status"] = ex2_status
    row["limit_last_check"] = datetime.now().isoformat()
    
    try:
        with open(csv_path, 'a', newline='') as f:
            writer = csv.writer(f, delimiter=';')
            writer.writerow(row_to_list(row))
        debug_log(f"APPEND_LIMIT_ROW: Created {new_row_id} order_id={order_id}")
        return True
    except Exception as e:
        debug_log(f"APPEND_LIMIT_ROW: ERROR: {e}", "ERROR")
        return False


def update_limit_row(
    pair: str,
    trade_id: str,
    order_id: str = None,
    suffix: int = None,  # Or specify suffix directly
    qty_filled: float = None,
    price_actual: float = None,
    value_usdt: float = None,
    fees: float = None,
    ex2_status: str = None,
    new_order_id: str = None,  # For edit case - update order_id
    new_price: float = None
) -> bool:
    """Update an existing ex2pN row.
    
    Args:
        pair: Trading pair
        trade_id: Trade ID
        order_id: Order ID to find the row
        suffix: Or specify suffix number directly (ex2p1, ex2p2...)
        qty_filled: New filled quantity
        price_actual: New actual price
        fees: New fees
        ex2_status: New status (OPEN, FILLED, CANCELLED)
        new_order_id: For edit - new order_id
        new_price: For edit - new price
    """
    csv_path = get_trade_csv_path(pair)
    if not csv_path.exists():
        debug_log(f"UPDATE_LIMIT_ROW: CSV not found for {pair}", "WARNING")
        return False
    
    rows = []
    with open(csv_path, 'r', newline='') as f:
        reader = csv.DictReader(f, delimiter=';')
        fieldnames = reader.fieldnames
        rows = list(reader)
    
    updated = False
    for row in rows:
        tid = row.get('trade_id', '')
        # Match by suffix number or by order_id
        match = False
        if suffix:
            match = tid == f"{trade_id}_ex2p{suffix}"
        elif order_id:
            match = tid.startswith(f"{trade_id}_ex2p") and row.get('ex2_order_id') == order_id
        
        if match:
            if qty_filled is not None:
                row["ex2_qty_filled"] = qty_filled
            if price_actual is not None:
                row["ex2_price_actual"] = price_actual
            if value_usdt is not None:
                row["ex2_value_usdt"] = value_usdt
            if fees is not None:
                row["ex2_fees"] = fees
            if ex2_status is not None:
                row["ex2_status"] = ex2_status
            if new_order_id is not None:
                row["ex2_order_id"] = new_order_id
            if new_price is not None:
                row["ex2_price_actual"] = new_price
            row["limit_last_check"] = datetime.now().isoformat()
            updated = True
            debug_log(f"UPDATE_LIMIT_ROW: Updated {tid}")
            break
    
    if updated:
        with open(csv_path, 'w', newline='') as f:
            writer = csv.DictWriter(f, fieldnames=fieldnames, delimiter=';')
            writer.writeheader()
            writer.writerows(rows)
        debug_log(f"UPDATE_LIMIT_ROW: Wrote back to CSV")
    else:
        debug_log(f"UPDATE_LIMIT_ROW: No matching row found for {trade_id}", "WARNING")
    
    return updated


def update_limit_watch(
    trade_id: str,
    pair: str,
    new_status: str,
    qty_filled: float = None,
    price_actual: float = None,
    fees: float = None,
    profit_mpc_actual: float = None,
    create_ts: str = None  # Exchange order creation timestamp
):
    """
    Update limit order watch state for a trade (ex2sum row).
    
    When new_status is CANCELLED:
    - Sets ex2_status to CANCELLED on the ex2pN row
    - Does NOT cancel _ex2sum - it stays OPEN
    """
    csv_path = get_trade_csv_path(pair)
    
    if not csv_path.exists():
        debug_log(f"UPDATE_LIMIT_WATCH: CSV not found for {pair}", "WARNING")
        return False
    
    # Read all rows
    rows = []
    with open(csv_path, 'r', newline='') as f:
        reader = csv.DictReader(f, delimiter=';')
        fieldnames = reader.fieldnames
        rows = list(reader)
    
    # Find and update trade (look for _ex2sum row AND main trade row)
    updated = False
    main_row = None  # Row 1 (main trade) for ex1 values
    ex2sum_row = None  # Reference to ex2sum row
    ex2sum_idx = None  # Index of ex2sum row in rows list
    
    for i, row in enumerate(rows):
        tid = row.get("trade_id", "")
        if tid == trade_id:
            main_row = row  # Row 1 (main trade)
        elif tid == f"{trade_id}_ex2sum":
            ex2sum_row = row
            ex2sum_idx = i
    
    if ex2sum_row is not None:
        ex2sum_row["limit_last_check"] = datetime.now().isoformat()
        
        # When new_status is CANCELLED, also handle the ex2pN row
        if new_status == 'CANCELLED':
            # Find the pending ex2pN row to cancel
            # IMPORTANT: If order has partial fills (qty_filled > 0 from exchange), keep that value!
            # Only set to 0 if no fills happened before cancellation
            for row in rows:
                tid = row.get("trade_id", "")
                if tid.startswith(f"{trade_id}_ex2p") and row.get("ex2_status") == "OPEN":
                    row["ex2_status"] = "CANCELLED"
                    # Only set qty_filled=0 if no partial fill was recorded
                    # If exchange reported partial fills (via qty_filled param), keep it
                    if qty_filled is not None and qty_filled > 0:
                        row["ex2_qty_filled"] = qty_filled
                    row["ex2_status"] = "CANCELLED"
                    row["limit_last_check"] = datetime.now().isoformat()
                    debug_log(f"UPDATE_LIMIT_WATCH: Cancelled {tid}, partial_fill={qty_filled}")
                    break
            # Do NOT update ex2sum - stays OPEN until replacement order fills
            # Write back and return early
            with open(csv_path, 'w', newline='') as f:
                writer = csv.DictWriter(f, fieldnames=fieldnames, delimiter=';')
                writer.writeheader()
                writer.writerows(rows)
            return True
        
        # For FILLED and other statuses, update ex2sum row
        if new_status == 'FILLED':
            ex2sum_row["ex2_status"] = 'FILLED'
            # Calculate actual profits
        
        if qty_filled is not None:
            ex2sum_row["ex2_qty_filled"] = qty_filled
        if price_actual is not None:
            ex2sum_row["ex2_price_actual"] = price_actual
        if fees is not None:
            ex2sum_row["ex2_fees"] = fees
        if profit_mpc_actual is not None:
            ex2sum_row["profit_mpc_actual"] = profit_mpc_actual
        if create_ts is not None:
            ex2sum_row["ex2_create_ts"] = create_ts
        elif not ex2sum_row.get("ex2_create_ts"):
            # Fallback: try to get create_ts from existing ex2p1 row
            for row in rows:
                if row.get("trade_id") == f"{trade_id}_ex2p1":
                    ts = row.get("ex2_create_ts", "")
                    if ts:
                        ex2sum_row["ex2_create_ts"] = ts
                        debug_log(f"UPDATE_LIMIT_WATCH: fallback create_ts from ex2p1: {ts}")
                    break
        
        # When new_status is FILLED, also set ex2_status and calculate profits
        if new_status == 'FILLED':
            ex2sum_row["ex2_status"] = 'FILLED'
            
            # Calculate actual profits
            if main_row is not None:
                # profit_usdt_actual = ex2_value - ex1_value - ex1_fees - ex2_fees
                ex1_value_usdt = to_float(main_row.get('ex1_value_usdt', 0) or 0)
                ex1_fees = to_float(main_row.get('ex1_fees', 0) or 0)
                ex2_value_usdt = to_float(ex2sum_row.get('ex2_value_usdt', 0) or 0)
                ex2_fees = to_float(ex2sum_row.get('ex2_fees', 0) or 0)
                profit_usdt_actual = ex2_value_usdt - ex1_value_usdt - ex1_fees - ex2_fees
                ex2sum_row["profit_usdt_actual"] = profit_usdt_actual
                
                # profit_mpc_actual = ex1_qty_filled - ex2_qty_filled
                ex1_qty_filled = to_float(main_row.get('ex1_qty_filled', 0) or 0)
                ex2_qty_filled = to_float(ex2sum_row.get('ex2_qty_filled', 0) or 0)
                profit_mpc_actual = ex1_qty_filled - ex2_qty_filled
                ex2sum_row["profit_mpc_actual"] = profit_mpc_actual
                
                debug_log(f"UPDATE_LIMIT_WATCH: FILLED - profit_usdt={profit_usdt_actual:.4f}, profit_mpc={profit_mpc_actual:.2f}")
        
        rows[ex2sum_idx] = ex2sum_row
        updated = True
        debug_log(f"UPDATE_LIMIT_WATCH: Updated {trade_id}_ex2sum status={new_status}")
    
    # Write back
    if updated:
        with open(csv_path, 'w', newline='') as f:
            writer = csv.DictWriter(f, fieldnames=fieldnames, delimiter=';')
            writer.writeheader()
            writer.writerows(rows)
        debug_log(f"UPDATE_LIMIT_WATCH: Wrote back to CSV")
    else:
        debug_log(f"UPDATE_LIMIT_WATCH: {trade_id}_ex2sum not found", "WARNING")
    
    return updated


# =============================================================================
# READ FUNCTIONS
# =============================================================================

def get_trades(pair: str, limit: int = 100) -> List[Dict]:
    """Get all trades for a trading pair (newest first)"""
    csv_path = get_trade_csv_path(pair)
    
    if not csv_path.exists():
        return []
    
    trades = []
    with open(csv_path, 'r', newline='') as f:
        reader = csv.DictReader(f, delimiter=';')
        rows = list(reader)
    
    # Reverse to get newest first
    rows = rows[::-1]
    
    for i, row in enumerate(rows):
        if i >= limit:
            break
        trades.append(row)
    
    return trades


def get_pending_limit_orders(pair: str = None) -> List[Dict]:
    """Get all trades with pending limit orders."""
    pending = []
    
    if pair:
        trades = get_trades(pair, limit=1000)
        for trade in trades:
            if trade.get("ex2_status") == "OPEN":
                pending.append(trade)
    else:
        for csv_file in LOG_DIR.glob("*_trades.csv"):
            pair_name = csv_file.stem.replace("_trades", "")
            trades = get_trades(pair_name, limit=1000)
            for trade in trades:
                if trade.get("ex2_status") == "OPEN":
                    pending.append(trade)
    
    return pending


def get_trade_summary(pair: str) -> Dict:
    """Get summary statistics for a trading pair"""
    trades = get_trades(pair, limit=10000)
    
    if not trades:
        return {
            "pair": pair,
            "total_trades": 0,
            "total_profit_mpc": 0,
            "total_profit_usdt": 0,
            "win_rate": "0%",
        }
    
    # Filter to main trades only (trade_id without suffix)
    main_trades = [t for t in trades if not t.get("trade_id", "").endswith(("ex1p1", "ex1p2", "ex2p1", "ex2p2", "ex2sum"))]
    
    total_profit_mpc = sum(float(t.get("profit_mpc_actual", 0) or 0) for t in main_trades)
    total_profit_usdt = sum(float(t.get("profit_usdt_actual", 0) or 0) for t in main_trades)
    
    # Count FILLED limit orders
    filled_count = len([t for t in main_trades if t.get("ex2_status") == "FILLED"])
    win_rate = f"{filled_count / len(main_trades) * 100:.0f}%" if main_trades else "0%"
    
    return {
        "pair": pair,
        "total_trades": len(main_trades),
        "total_profit_mpc": total_profit_mpc,
        "total_profit_usdt": total_profit_usdt,
        "win_rate": win_rate,
    }


# =============================================================================
# UTILITY
# =============================================================================

def clear_debug_log():
    """Clear the debug log file"""
    try:
        if DEBUG_LOG_FILE.exists():
            DEBUG_LOG_FILE.unlink()
        debug_log("Debug log cleared")
    except Exception as e:
        print(f"Could not clear debug log: {e}", file=sys.stderr)