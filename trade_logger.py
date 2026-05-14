"""
Trade Logger - Harmonized Multi-Exchange Trade Capture
One CSV per trading pair, all trades appended sequentially.

Harmonization: Exchange-specific API responses are normalized into
a unified schema so data is comparable across exchanges.
"""
import csv
import os
import json
from datetime import datetime
from pathlib import Path
from typing import Dict, Optional, List, Tuple

LOG_DIR = Path("/app/logs")


# Exchange configuration cache
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
    """Get short_id for an exchange (e.g. 'KUCOIN' -> 'KCN')"""
    config = get_exchange_config()
    exchange_lower = exchange_name.lower()
    if exchange_lower in config:
        return config[exchange_lower].get('short_id', exchange_name[:3].upper())
    # Fallback: first 3 chars uppercase
    return exchange_name[:3].upper()

def get_exchange_color(exchange_name: str) -> str:
    """Get color for an exchange"""
    config = get_exchange_config()
    exchange_lower = exchange_name.lower()
    if exchange_lower in config:
        return config[exchange_lower].get('color', '#888888')
    return '#888888'

# Unified CSV columns for ALL trades (harmonized format)
# Exchange-Agnostic: Works with any exchanges (KuCoin, MEXC, Binance, etc.)
#
# Schema: Market-Side (Exchange 1) + Limit-Side (Exchange 2)
# - Market-Side: Always a MARKET order (first leg of arbitrage)
# - Limit-Side: Always a LIMIT order (second leg, may be pending/filled/cancelled)
UNIFIED_COLUMNS = [
    # Trade Identity
    "trade_id",              # Unique ID: YYYYMMDD_HHMMSS_MMMMMM (no prefix)
    "internal_ts",            # When BOT initiated the trade (ISO format)
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
    "ex1_price_expected",    # Expected price when trade was initiated (pK or pM)
    "ex1_price_actual",      # Actual execution price
    "ex1_price_avg",       # Average fill price (for multi-level fills)
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
    "ex2_price_actual",      #
    "ex2_price_avg",       # Actual fill price (0 if not filled)
    "ex2_value_usdt",        # Total value in USDT (0 if not filled)
    "ex2_fees",              # Fees paid in USDT
    "ex2_create_ts",         # Exchange timestamp (ms)
    "ex2_status",            # Exchange status: PENDING, FILLED, PARTIAL, CANCELLED
    
    # Profit Calculation
    "profit_usdt_expected",  # Expected USDT profit (calculated pre-trade)
    "profit_mpc_expected",   # Expected MPC profit (calculated pre-trade)
    "profit_usdt_actual",    # Actual USDT profit (filled limit order)
    "profit_mpc_actual",     # Actual MPC profit (filled limit order)
    
    # Limit Order Watch State
    "limit_watch_status",    # "WATCHING", "FILLED", "PARTIAL", "CANCELLED", "EXPIRED", "ERROR"
    "limit_last_check",      # Last timestamp we checked fill status
    
    # Error Handling
    "error_code",            # Error code: "QTY_ZERO", "PRICE_SLIPPAGE", "API_ERROR", etc.
    "error_message",         # Human-readable error description
    
    # Metadata
    "raw_ex1_response",      # Full JSON response from Exchange 1
    "raw_ex2_response",      # Full JSON response from Exchange 2
    "updated_at",            # Last update timestamp (ISO format)
]

# =============================================================================
# MULTI-LEVEL FILL DOCUMENTATION (2026-05-12)
# =============================================================================
#
# When a market order fills across multiple price levels (e.g., 100 MPC bought at 3 different prices),
# the fills are tracked in raw_ex1_response as individual fill events.
#
# CSV Fields for Multi-Level Support:
# - ex1_qty_filled:     Total quantity filled (sum of all fills)
# - ex1_price_actual:   Last fill price (single fill)
# - ex1_price_avg:     Volume-weighted average price (calculated from all fills)
# - raw_ex1_response: JSON array of individual fill events from exchange API
#
# Display Logic (dashboard.py):
# - Single fill (1 line):  "85.0 @ $0.01630"
# - Multi-level (3 lines):  "Σ 100.0 @ $0.01652"  ← Summe + Durchschnittspreis
#                         "40.0 @ $0.01630"    ← Teilorder 1
#                         "25.0 @ $0.01680"    ← Teilorder 2
#
# To enable multi-level detection:
# 1. exchange API must return individual fills in response (check MEXC/KuCoin API docs)
# 2. raw_ex1_response must be stored as JSON string in CSV
# 3. ex1_price_avg must be calculated from: Σ(qty * price) / Σ(qty)
#
# =============================================================================




def ensure_log_dir():
    """Ensure log directory exists"""
    LOG_DIR.mkdir(parents=True, exist_ok=True)


def get_trade_csv_path(pair: str) -> Path:
    """Get CSV file path for a trading pair"""
    # Normalize pair format: MPCUSDT OR MPC-USDT -> MPCUSDT (consistent)
    normalized_pair = pair.replace("-", "").upper()
    if not normalized_pair.endswith("USDT"):
        normalized_pair += "USDT"
    return LOG_DIR / f"{normalized_pair}_trades.csv"


def init_pair_csv(pair: str) -> Path:
    """Initialize CSV file for a trading pair if it doesn't exist"""
    ensure_log_dir()
    csv_path = get_trade_csv_path(pair)
    
    if not csv_path.exists():
        with open(csv_path, 'w', newline='') as f:
            writer = csv.writer(f, delimiter=';')
            writer.writerow(UNIFIED_COLUMNS)
    
    return csv_path


def generate_trade_id() -> str:
    """
    Generate unique trade ID in format: DDHHMMSSms (hex)
    
    Example: 0c1500372b (10 chars)
    
    This format is:
    - Unique (millisecond precision)
    - Chronologically sortable
    - Compact (10 chars vs 20+)
    - Hex-encoded for brevity
    
    Contains: DD (day) + HH (hour) + MM (minute) + SS (second) + ms (milliseconds)
    """
    now = datetime.now()
    dd = now.strftime("%d")
    hh = now.strftime("%H")
    mm = now.strftime("%M")
    ss = now.strftime("%S")
    ms = now.strftime("%f")[:2]
    
    return f"{int(dd):02x}{int(hh):x}{int(mm):x}{int(ss):x}{int(ms):02x}"
    return ts


# =============================================================================
# HARMONIZATION FUNCTIONS
# Convert exchange-specific responses to unified format
# =============================================================================

def harmonize_kucoin_order(response: dict, side: str, order_type: str, pair: str) -> Dict:
    """
    Harmonize KuCoin order response to unified format.
    
    KuCoin Market Order Response fields:
    - orderId: order ID
    - symbol: pair symbol
    - type: "market" 
    - side: "buy" or "sell"
    - size: quantity ordered
    - dealSize: quantity filled
    - dealFunds: total value
    - fee: fee amount
    - feeCurrency: currency of fee
    - createTime: timestamp in ms
    - status: "Done", "Active"
    
    Returns:
        Dict with unified field names:
        - price_expected: Expected price (passed separately when calling)
        - price_actual: Actual execution price (calculated from dealFunds/dealSize)
    """
    # Calculate actual price from filled amount
    deal_size = float(response.get('dealSize', 0) or 0)
    deal_funds = float(response.get('dealFunds', 0) or 0)
    price_actual = deal_funds / deal_size if deal_size > 0 else 0
    
    # Determine status
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
        "raw_response": response,  # Keep full response for debugging
    }


def harmonize_mexc_order(response: dict, side: str, order_type: str, pair: str) -> Dict:
    """
    Harmonize MEXC order response to unified format.
    
    MEXC Market Order Response fields:
    - orderId: order ID
    - symbol: pair symbol (e.g. "MPCUSDT")
    - side: "BUY" or "SELL"
    - type: "MARKET"
    - orderQuantity: quantity ordered
    - orderAmount: amount ordered (for market buys in USDT)
    - quantity: quantity filled
    - amount: amount filled (in USDT value)
    - fees: fee amount
    - createTime: timestamp in ms
    - status: "Filled", "New"
    
    MEXC Limit Order Response:
    - orderId: order ID
    - symbol: pair symbol
    - side: "BUY" or "SELL"
    - type: "LIMIT"
    - price: limit price
    - quantity: quantity ordered
    - orderQuantity: same as quantity
    - amount: total value
    - dealQuantity: quantity filled
    - dealAmount: value filled
    - fees: fee amount
    - createTime: timestamp in ms
    - status: "Filled", "PartiallyFilled", "New", "Cancelled"
    
    Returns:
        Dict with unified field names:
        - price_expected: Expected price (passed separately when calling)
        - price_actual: Actual execution price
    """
    # Handle market vs limit order differences
    if order_type == "market":
        qty_filled = float(response.get('quantity', 0) or 0)
        value_usdt = float(response.get('amount', 0) or 0)
        qty_ordered = float(response.get('orderQuantity', 0) or 0)
        price_actual = value_usdt / qty_filled if qty_filled > 0 else 0
    else:  # limit
        qty_filled = float(response.get('dealQuantity', 0) or 0)
        value_usdt = float(response.get('dealAmount', 0) or 0)
        qty_ordered = float(response.get('quantity', 0) or 0)
        price_actual = float(response.get('price', 0) or 0)  # Limit price is the price
    
    # Determine status
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
        "price_expected": 0.0,  # Set by caller
        "price_actual": price_actual,
        "value_usdt": value_usdt,
        "fees": float(response.get('fees', 0) or 0),
        "create_ts": int(response.get('createTime', 0) or 0),
        "status": unified_status,
        "raw_response": response,  # Keep full response for debugging
    }


def harmonize_order(response: dict, exchange: str, side: str, order_type: str, pair: str) -> Dict:
    """Route to correct harmonizer based on exchange"""
    if exchange.upper() == "KUCOIN":
        return harmonize_kucoin_order(response, side, order_type, pair)
    elif exchange.upper() == "MEXC":
        return harmonize_mexc_order(response, side, order_type, pair)
    else:
        raise ValueError(f"Unknown exchange: {exchange}")


def log_trade(
    pair: str,
    internal_ts: str,
    direction: str,
    ex1_data: Dict,   # Harmonized data from market exchange
    ex2_data: Dict,   # Harmonized data from limit exchange (may be partial)
    limit_watch_status: str = "WATCHING",
    strategy: str = "USDT",               # "USDT" or "COINS"
    spread_pct: float = 0.0,              # Spread in % when trade was triggered
    market_price_expected: float = 0.0,   # Expected price (pK or pM) at trade initiation
    limit_price_expected: float = 0.0,    # Expected price at trade initiation
    profit_usdt_expected: float = 0.0,    # Expected USDT profit
    profit_mpc_expected: float = 0.0,     # Expected MPC profit
    error_code: str = None,              # Error code if any
    error_message: str = None             # Error message if any
) -> str:
    """
    Log a complete trade to the pair-specific CSV.
    
    Exchange-Agnostic: Works with any exchange as ex1 (market) and ex2 (limit).
    
    Args:
        pair: Trading pair e.g. "MPC-USDT"
        internal_ts: Our internal timestamp when trade was initiated
        direction: "K->M" or "M->K"
        ex1_data: Harmonized data from market exchange (always MARKET order)
        ex2_data: Harmonized data from limit exchange (always LIMIT order)
        limit_watch_status: Initial status of limit order
        strategy: "USDT" or "COINS" strategy used
        spread_pct: Spread in % when trade was triggered
        market_price_expected: Expected price at initiation (pK or pM)
        limit_price_expected: Expected price at initiation
        profit_usdt_expected: Expected USDT profit
        profit_mpc_expected: Expected MPC profit
        error_code: Error code if trade had errors
        error_message: Error message if trade had errors
    
    Returns:
        trade_id: Generated trade ID (format: YYYYMMDD_HHMMSS_MMMMMM)
    """
    trade_id = generate_trade_id()
    updated_at = datetime.now().isoformat()
    
    # Normalize pair for filename
    csv_path = init_pair_csv(pair)
    
    # Set price_expected fields in harmonized data (if not already set by caller)
    # These are set here as fallback - caller should set these explicitly
    if ex1_data.get('price_expected', 0) == 0 and market_price_expected > 0:
        ex1_data['price_expected'] = market_price_expected
    if ex2_data.get('price_expected', 0) == 0 and limit_price_expected > 0:
        ex2_data['price_expected'] = limit_price_expected
    
    # Build row in unified format
    row = [
        # Trade Identity
        trade_id,
        internal_ts,
        direction,  # Now formatted as "KCN->MXC" or "MXC->KCN" from caller
        pair,
        strategy,
        spread_pct,
        
        # Exchange 1 (market order - first leg)
        get_exchange_short_id(ex1_data.get("exchange", "")),
        ex1_data.get("order_id", ""),
        ex1_data.get("type", ""),
        ex1_data.get("side", ""),
        ex1_data.get("qty_ordered", 0),
        ex1_data.get("qty_filled", 0),
        ex1_data.get("price_expected", 0),
        ex1_data.get("price_actual", 0),
        ex1_data.get("price_avg", 0),  # Average price for multi-level fills
        ex1_data.get("value_usdt", 0),
        ex1_data.get("fees", 0),
        ex1_data.get("create_ts", 0),
        ex1_data.get("status", ""),
        
        # Exchange 2 (limit order - second leg)
        get_exchange_short_id(ex2_data.get("exchange", "")),
        ex2_data.get("order_id", ""),
        ex2_data.get("type", ""),
        ex2_data.get("side", ""),
        ex2_data.get("qty_ordered", 0),
        ex2_data.get("qty_filled", 0),
        ex2_data.get("price_expected", 0),
        ex2_data.get("price_actual", 0),
        ex2_data.get("price_avg", 0),  # Average price for multi-level fills
        ex2_data.get("value_usdt", 0),
        ex2_data.get("fees", 0),
        ex2_data.get("create_ts", 0),
        ex2_data.get("status", ""),
        
        # Profit Calculation
        profit_usdt_expected,
        profit_mpc_expected,
        0.0,  # profit_usdt_actual (filled later)
        0.0,  # profit_mpc_actual (filled later)
        
        # Limit watch state
        limit_watch_status,
        "",  # limit_last_check
        
        # Error Handling
        error_code or "",
        error_message or "",
        
        # Raw responses
        json.dumps(ex1_data.get("raw_response", {})),
        json.dumps(ex2_data.get("raw_response", {})),
        updated_at,
    ]
    
    # Append to CSV
    # DEBUG: Log the full path where we're writing
    import sys
    sys.stderr.write(f"DEBUG: Writing trade to CSV: {csv_path}\n")
    sys.stderr.write(f"DEBUG: CSV exists: {csv_path.exists()}\n")
    
    with open(csv_path, 'a', newline='') as f:
        writer = csv.writer(f, delimiter=';')
        writer.writerow(row)
    
    return trade_id


def update_limit_watch(
    trade_id: str,
    pair: str,
    new_status: str,
    qty_filled: float = None,
    price_actual: float = None,
    fees: float = None,
    profit_usdt_actual: float = None,
    profit_mpc_actual: float = None
):
    """
    Update limit order watch state for a trade.
    
    Args:
        trade_id: Trade ID to update
        pair: Trading pair
        new_status: New limit_watch_status
        qty_filled: Filled quantity (from limit order fill)
        price_actual: Actual fill price (ex2_price_actual)
        fees: Fees paid on limit order
        profit_usdt_actual: Actual USDT profit after limit fill
        profit_mpc_actual: Actual MPC profit after limit fill
    
    Returns:
        True if updated, False if not found
    """
    csv_path = get_trade_csv_path(pair)
    
    if not csv_path.exists():
        return False
    
    # Read all rows
    rows = []
    with open(csv_path, 'r', newline='') as f:
        reader = csv.DictReader(f)
        fieldnames = reader.fieldnames
        rows = list(reader)
    
    # Find and update trade
    updated = False
    for row in rows:
        if row.get("trade_id") == trade_id:
            row["limit_watch_status"] = new_status
            row["limit_last_check"] = datetime.now().isoformat()
            
            # Update fill data if provided
            if qty_filled is not None:
                row["ex2_qty_filled"] = qty_filled
            if price_actual is not None:
                row["ex2_price_actual"] = price_actual
            if fees is not None:
                row["ex2_fees"] = fees
            if profit_usdt_actual is not None:
                row["profit_usdt_actual"] = profit_usdt_actual
            if profit_mpc_actual is not None:
                row["profit_mpc_actual"] = profit_mpc_actual
            
            row["updated_at"] = datetime.now().isoformat()
            updated = True
            break
    
    # Write back
    if updated:
        with open(csv_path, 'w', newline='') as f:
            writer = csv.DictWriter(f, fieldnames=fieldnames)
            writer.writeheader()
            writer.writerows(rows)
    
    return updated


def get_trades(pair: str, limit: int = 100) -> List[Dict]:
    """Get all trades for a trading pair"""
    csv_path = get_trade_csv_path(pair)
    
    if not csv_path.exists():
        return []
    
    trades = []
    with open(csv_path, 'r', newline='') as f:
        reader = csv.DictReader(f)
        rows = list(reader)
    
    # Reverse to get newest first
    rows = rows[::-1]
    
    for i, row in enumerate(rows):
        if i >= limit:
            break
        trades.append(row)
    
    return trades


def get_pending_limit_orders(pair: str = None) -> List[Dict]:
    """
    Get all trades with pending limit orders.
    Used by the limit order watcher to poll for fills.
    
    Args:
        pair: Optional pair filter. If None, checks all pair CSVs.
    
    Returns:
        List of trades with WATCHING status
    """
    pending = []
    
    if pair:
        # Check specific pair
        trades = get_trades(pair, limit=1000)
        for trade in trades:
            if trade.get("limit_watch_status") == "WATCHING":
                pending.append(trade)
    else:
        # Check all pair CSVs
        for csv_file in LOG_DIR.glob("*_trades.csv"):
            pair_name = csv_file.stem.replace("_trades", "")
            trades = get_trades(pair_name, limit=1000)
            for trade in trades:
                if trade.get("limit_watch_status") == "WATCHING":
                    pending.append(trade)
    
    return pending


def get_trade_summary(pair: str) -> Dict:
    """Get summary statistics for a trading pair"""
    trades = get_trades(pair, limit=10000)
    
    if not trades:
        return {
            "pair": pair,
            "total_trades": 0,
            "win_rate": "0%",
            "total_profit_usdt": 0,
            "total_profit_mpc": 0,
            "best_trade_usdt": 0,
            "avg_profit_usdt": 0,
            "pending_limit_orders": 0,
        }
    
    wins = 0
    losses = 0
    total_profit_usdt = 0
    total_profit_mpc = 0
    best_trade_usdt = 0
    pending = 0
    
    for trade in trades:
        status = trade.get("limit_watch_status", "")
        
        # Only count completed trades for stats
        if status == "FILLED":
            # Calculate profit from the trade
            ex1_value = float(trade.get("ex1_value_usdt", 0) or 0)
            ex2_value = float(trade.get("ex2_value_usdt", 0) or 0)
            ex1_fees = float(trade.get("ex1_fees", 0) or 0)
            ex2_fees = float(trade.get("ex2_fees", 0) or 0)
            
            # For K->M: Buy on KuCoin (ex1), Sell on MEXC (ex2)
            # Direction tells us which is buy/sell
            direction = trade.get("direction", "")
            
            # Calculate profit based on direction
            if "K->M" in direction:
                cost = ex1_value  # Bought on KuCoin
                revenue = ex2_value  # Sold on MEXC
            else:  # M->K
                cost = ex1_value  # Bought on MEXC
                revenue = ex2_value  # Sold on KuCoin
            
            net_profit = revenue - cost - ex1_fees - ex2_fees
            total_profit_usdt += net_profit
            
            # Calculate MPC gain (reinvested coins)
            ex2_price = float(trade.get("ex2_price_avg", 0) or 0)
            if ex2_price > 0:
                mpc_gain = net_profit / ex2_price
                total_profit_mpc += mpc_gain
            
            if net_profit > 0:
                wins += 1
            else:
                losses += 1
            
            if net_profit > best_trade_usdt:
                best_trade_usdt = net_profit
                
        elif status == "WATCHING":
            pending += 1
    
    total_completed = wins + losses
    win_rate = f"{(wins/total_completed*100):.1f}%" if total_completed > 0 else "0%"
    avg_profit = total_profit_usdt / total_completed if total_completed > 0 else 0
    
    return {
        "pair": pair,
        "total_trades": len(trades),
        "completed_trades": total_completed,
        "win_rate": win_rate,
        "total_profit_usdt": round(total_profit_usdt, 4),
        "total_profit_mpc": round(total_profit_mpc, 4),
        "best_trade_usdt": round(best_trade_usdt, 4),
        "avg_profit_usdt": round(avg_profit, 4),
        "pending_limit_orders": pending,
    }


def export_trades_csv(pair: str) -> Optional[str]:
    """Export all trades for a pair to a standalone CSV"""
    trades = get_trades(pair, limit=100000)
    
    if not trades:
        return None
    
    export_dir = LOG_DIR / "exports"
    export_dir.mkdir(parents=True, exist_ok=True)
    
    filename = f"{pair}_trades_export_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv"
    filepath = export_dir / filename
    
    with open(filepath, 'w', newline='') as f:
        if trades:
            writer = csv.DictWriter(f, fieldnames=trades[0].keys())
            writer.writeheader()
            writer.writerows(trades)
    
    return str(filepath)


def get_all_pairs_with_trades() -> List[str]:
    """Get list of all trading pairs that have CSV files"""
    pairs = []
    for csv_file in LOG_DIR.glob("*_trades.csv"):
        pair = csv_file.stem.replace("_trades", "")
        pairs.append(pair)
    return pairs

def get_trade_summary_extended(pair: str) -> Dict:
    """Get extended summary statistics including average spread"""
    trades = get_trades(pair, limit=10000)
    
    if not trades:
        return {
            "pair": pair,
            "total_trades": 0,
            "completed_trades": 0,
            "open_trades": 0,
            "total_profit_usdt": 0,
            "total_profit_mpc": 0,
            "best_trade_usdt": 0,
            "avg_profit_usdt": 0,
            "avg_spread_pct": 0,
            "pending_limit_orders": 0,
        }
    
    completed = 0
    open_trades = 0
    total_profit_usdt = 0
    total_profit_mpc = 0
    best_trade_usdt = 0
    total_spread = 0
    
    for trade in trades:
        status = trade.get("limit_watch_status", "")
        
        if status == "FILLED":
            completed += 1
            
            ex1_value = float(trade.get("ex1_value_usdt", 0) or 0)
            ex2_value = float(trade.get("ex2_value_usdt", 0) or 0)
            ex1_fees = float(trade.get("ex1_fees", 0) or 0)
            ex2_fees = float(trade.get("ex2_fees", 0) or 0)
            ex1_price = float(trade.get("ex1_price_avg", 0) or 0)
            
            direction = trade.get("direction", "")
            
            if "K->M" in direction:
                cost = ex1_value
                revenue = ex2_value
            else:
                cost = ex1_value
                revenue = ex2_value
            
            net_profit = revenue - cost - ex1_fees - ex2_fees
            total_profit_usdt += net_profit
            
            # Calculate spread for this trade
            if ex1_price > 0 and ex2_value > 0:
                spread_pct = ((revenue - cost) / cost) * 100 if cost > 0 else 0
                total_spread += spread_pct
            
            # MPC gain
            ex2_price = float(trade.get("ex2_price_avg", 0) or 0)
            if ex2_price > 0:
                mpc_gain = net_profit / ex2_price
                total_profit_mpc += mpc_gain
            
            if net_profit > best_trade_usdt:
                best_trade_usdt = net_profit
                
        elif status == "WATCHING" or status == "PARTIAL":
            open_trades += 1
    
    avg_profit = total_profit_usdt / completed if completed > 0 else 0
    avg_spread = total_spread / completed if completed > 0 else 0
    
    return {
        "pair": pair,
        "total_trades": len(trades),
        "completed_trades": completed,
        "open_trades": open_trades,
        "total_profit_usdt": round(total_profit_usdt, 4),
        "total_profit_mpc": round(total_profit_mpc, 4),
        "best_trade_usdt": round(best_trade_usdt, 4),
        "avg_profit_usdt": round(avg_profit, 4),
        "avg_spread_pct": round(avg_spread, 3),
        "pending_limit_orders": open_trades,
    }

def format_trade_table(trade_data):
    """Format completed trade as ASCII table"""
    return f"""
╔════════════════════════════════════════════════════════════════╗
║  Trade Summary                                           ║
╠════════════════════════════════════════════════════════════════╣
║  Trade ID:     {trade_data.get('trade_id', 'N/A'):<35} ║
║  Direction:   {trade_data.get('direction', 'N/A'):<35} ║
║  ───────────────────────────────────────────────────────  ║
║  Step 1:     {trade_data.get('step1_ex', 'N/A'):<8} {trade_data.get('step1_type', 'N/A'):<10} {trade_data.get('step1_qty', 0):>8.2f} MPC ║
║  Step 2:     {trade_data.get('step2_ex', 'N/A'):<8} {trade_data.get('step2_type', 'N/A'):<10} @ {trade_data.get('step2_price', 0):>8.5f}    ║
╠════════════════════════════════════════════════════════════════╣
║  Profit:     ${trade_data.get('profit_usdt', 0):>8.4f} USDT   │ MPC Gain:  {trade_data.get('profit_mpc', 0):>8.2f} MPC ║
╚════════════════════════════════════════════════════════════════╝"""
