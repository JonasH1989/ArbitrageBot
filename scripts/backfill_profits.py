#!/usr/bin/env python3
"""
One-Shot Backfill Script: re-fetch all stale FILLED trade profits from exchanges.

Reads /app/logs/MPCUSDT_trades.csv, finds all FILLED orders with profit_usdt_actual=0,
fetches the actual fills from the exchange (MEXC or KuCoin) with date-range parameters,
and updates profit_usdt_actual, ex2_value_usdt, ex2_qty_filled, ex2_fees.

Usage (in container):
    python3 scripts/backfill_profits.py

Jonas 2026-10-19 12:18
"""
import sys
import csv
import hmac
import hashlib
import json
import time
from pathlib import Path
from datetime import datetime
from typing import Dict, List, Optional, Tuple

try:
    import requests
except ImportError:
    print("ERROR: 'requests' module not installed. Run: pip install requests")
    sys.exit(1)

try:
    import yaml
except ImportError:
    print("ERROR: 'pyyaml' module not installed. Run: pip install pyyaml")
    sys.exit(1)

# ============================================================
# CONFIG
# ============================================================
CSV_PATH = Path('/app/logs/MPCUSDT_trades.csv')
CONFIG_PATH = Path('/app/config/config.yaml')
SYMBOL_MEXC = 'MPCUSDT'
SYMBOL_KUCOIN = 'MPC-USDT'
DATE_WINDOW_HOURS = 48  # ±48h around ex2_create_ts


def load_config() -> Dict:
    """Load exchange credentials from config.yaml."""
    if not CONFIG_PATH.exists():
        print(f"ERROR: Config not found: {CONFIG_PATH}")
        sys.exit(1)
    with open(CONFIG_PATH) as f:
        return yaml.safe_load(f)


def iso_to_ms(iso_str: str) -> int:
    """Convert '2026-09-09 22:48:49.770' to Unix ms. 0 on failure."""
    if not iso_str:
        return 0
    try:
        dt = datetime.strptime(iso_str[:19], '%Y-%m-%d %H:%M:%S')
        return int(dt.timestamp() * 1000)
    except (ValueError, TypeError):
        return 0


def to_float(val, default: float = 0.0) -> float:
    """Parse float, handling comma decimal separator."""
    if val is None or val == '':
        return default
    try:
        return float(str(val).replace(',', '.'))
    except (ValueError, TypeError):
        return default


# ============================================================
# EXCHANGE API CALLS
# ============================================================
def fetch_mexc_fills(order_id: str, symbol: str, start_time_ms: int, mexc_cfg: Dict) -> List[Dict]:
    """Fetch all fills for a MEXC order using GET /api/v3/myTrades with date range."""
    ts = str(int(time.time() * 1000))
    end_ms = start_time_ms + DATE_WINDOW_HOURS * 3600 * 1000
    params = f"symbol={symbol}&orderId={order_id}&startTime={start_time_ms}&endTime={end_ms}&timestamp={ts}"
    sig = hmac.new(
        mexc_cfg['api_secret'].encode('utf-8'),
        params.encode('utf-8'),
        hashlib.sha256
    ).hexdigest()
    url = f"https://api.mexc.com/api/v3/myTrades?{params}&signature={sig}"
    headers = {'X-MEXC-APIKEY': mexc_cfg['api_key']}
    try:
        resp = requests.get(url, headers=headers, timeout=15)
        if resp.status_code != 200:
            print(f"  [MEXC] HTTP {resp.status_code} for {order_id}: {resp.text[:200]}")
            return []
        trades = resp.json()
        if not isinstance(trades, list):
            return []
        # Filter to our order (API might return other orders in the range)
        return [t for t in trades if str(t.get('orderId', '')) == str(order_id)]
    except Exception as e:
        print(f"  [MEXC] Error for {order_id}: {e}")
        return []


def fetch_kucoin_fills(order_id: str, start_time_ms: int, kucoin_cfg: Dict) -> List[Dict]:
    """Fetch all fills for a KuCoin order using GET /api/v1/fills with date range."""
    ts = str(int(time.time() * 1000))
    end_ms = start_time_ms + DATE_WINDOW_HOURS * 3600 * 1000
    path = f"/api/v1/fills?orderId={order_id}&startAt={start_time_ms}&endAt={end_ms}"

    # KuCoin v2 signing
    message = f"{ts}GET{path}"
    sig = base64.b64encode(
        hmac.new(
            kucoin_cfg['api_secret'].encode('utf-8'),
            message.encode('utf-8'),
            hashlib.sha256
        ).digest()
    ).decode()

    headers = {
        'KC-API-KEY': kucoin_cfg['api_key'],
        'KC-API-SIGN': sig,
        'KC-API-TIMESTAMP': ts,
        'KC-API-PASSPHRASE': kucoin_cfg['api_passphrase'],
        'KC-API-KEY-VERSION': '2'
    }
    try:
        resp = requests.get(f"https://api.kucoin.com{path}", headers=headers, timeout=15)
        data = resp.json()
        if data.get('code') != '200000':
            print(f"  [KuCoin] API {data.get('code')} for {order_id}: {data.get('msg', '')[:200]}")
            return []
        data_field = data.get('data', {})
        if isinstance(data_field, dict):
            return data_field.get('items', [])
        if isinstance(data_field, list):
            return data_field
        return []
    except Exception as e:
        print(f"  [KuCoin] Error for {order_id}: {e}")
        return []


# ============================================================
# PROFIT CALCULATION
# ============================================================
def calc_profit_from_fills(fills: List[Dict], exchange: str) -> Tuple[float, float]:
    """Returns (ex2_value_usdt, ex2_fees) from a list of fills."""
    value_usdt = 0.0
    fees = 0.0
    for f in fills:
        if exchange == 'MXC':
            # MEXC: quoteQty = USDT value, commission = fee in MPC
            # Note: MEXC fees are in the asset received (e.g., MPC for sells), not USDT
            value_usdt += to_float(f.get('quoteQty', 0))
            fees += to_float(f.get('commission', 0)) * to_float(f.get('price', 0))
        elif exchange == 'KCN':
            # KuCoin: funds = USDT value, fee = fee in the asset
            value_usdt += to_float(f.get('funds', 0))
            fees += to_float(f.get('fee', 0)) * to_float(f.get('price', 0))
    return value_usdt, fees


# ============================================================
# MAIN
# ============================================================
def main():
    if not CSV_PATH.exists():
        print(f"ERROR: CSV not found: {CSV_PATH}")
        sys.exit(1)

    config = load_config()
    mexc_cfg = config.get('mexc', {})
    kucoin_cfg = config.get('kucoin', {})
    if not mexc_cfg.get('api_key') or not kucoin_cfg.get('api_key'):
        print("ERROR: Missing MEXC or KuCoin credentials in config.yaml")
        sys.exit(1)

    print(f"Reading CSV: {CSV_PATH}")
    with open(CSV_PATH, 'r', newline='') as f:
        reader = csv.DictReader(f, delimiter=';')
        rows = list(reader)
    print(f"Loaded {len(rows)} rows")

    # Group rows by trade_id
    trade_blocks: Dict[str, Dict] = {}
    for row in rows:
        tid = row.get('trade_id', '').strip()
        if not tid:
            continue
        if tid not in trade_blocks:
            trade_blocks[tid] = {'main': None, 'ex2sum': None, 'ex1_fills': [], 'ex2_fills': []}
        if tid.endswith('_ex2sum'):
            trade_blocks[tid]['ex2sum'] = row
        elif tid.endswith('_ex1p'):
            trade_blocks[tid]['ex1_fills'].append(row)
        elif tid.endswith('_ex2p'):
            trade_blocks[tid]['ex2_fills'].append(row)
        else:
            trade_blocks[tid]['main'] = row

    # Find stale FILLED trades (profit=0)
    stale: List[Tuple[str, Dict, Dict]] = []  # (trade_id, main_row, ex2sum_row)
    for tid, block in trade_blocks.items():
        main = block.get('main')
        ex2sum = block.get('ex2sum')
        if not main or not ex2sum:
            continue
        if ex2sum.get('ex2_status', '').strip().upper() != 'FILLED':
            continue
        profit = to_float(ex2sum.get('profit_usdt_actual', 0))
        if profit != 0:
            continue
        ex2_order_id = ex2sum.get('ex2_order_id', '').strip()
        ex2_exchange = ex2sum.get('ex2', '').strip().upper()
        ex2_create_ts = ex2sum.get('ex2_create_ts', '').strip()
        if not ex2_order_id or ex2_order_id in ('FAILED', 'NOT_PLACED', ''):
            continue
        if not ex2_exchange:
            continue
        stale.append((tid, main, ex2sum, ex2_order_id, ex2_exchange, ex2_create_ts))

    print(f"Found {len(stale)} stale FILLED trades (profit=0, FILLED, valid order_id)")

    if not stale:
        print("Nothing to backfill.")
        return

    # Fetch and update
    updated = 0
    failed = 0
    for tid, main, ex2sum, ex2_order_id, ex2_exchange, ex2_create_ts in stale:
        start_time_ms = iso_to_ms(ex2_create_ts)
        if start_time_ms == 0:
            # Fallback: no create_ts → use a wide range from Sep 1
            start_time_ms = int(datetime(2026, 9, 1).timestamp() * 1000)

        print(f"\n[{tid}] exchange={ex2_exchange} order_id={ex2_order_id} create_ts={ex2_create_ts}")

        if ex2_exchange == 'MXC':
            fills = fetch_mexc_fills(ex2_order_id, SYMBOL_MEXC, start_time_ms, mexc_cfg)
        elif ex2_exchange == 'KCN':
            fills = fetch_kucoin_fills(ex2_order_id, start_time_ms, kucoin_cfg)
        else:
            print(f"  Unknown exchange: {ex2_exchange}, skipping")
            failed += 1
            continue

        if not fills:
            print(f"  No fills returned for {ex2_order_id}")
            failed += 1
            continue

        ex2_value_usdt, ex2_fees = calc_profit_from_fills(fills, ex2_exchange)
        ex1_value_usdt = to_float(main.get('ex1_value_usdt', 0))
        ex1_fees = to_float(main.get('ex1_fees', 0))
        new_profit = ex2_value_usdt - ex1_value_usdt - ex1_fees - ex2_fees
        new_qty_filled = sum(to_float(f.get('size', f.get('qty', 0))) for f in fills)

        print(f"  fills={len(fills)} ex2_value={ex2_value_usdt:.4f} ex2_fees={ex2_fees:.4f}")
        print(f"  ex1_value={ex1_value_usdt:.4f} ex1_fees={ex1_fees:.4f}")
        print(f"  NEW profit_usdt_actual = {new_profit:.4f}")
        print(f"  NEW ex2_qty_filled = {new_qty_filled:.4f}")

        ex2sum['profit_usdt_actual'] = f"{new_profit:.4f}".replace('.', ',')
        ex2sum['ex2_value_usdt'] = f"{ex2_value_usdt:.4f}".replace('.', ',')
        ex2sum['ex2_fees'] = f"{ex2_fees:.4f}".replace('.', ',')
        ex2sum['ex2_qty_filled'] = f"{new_qty_filled:.4f}".replace('.', ',')
        updated += 1
        time.sleep(0.2)  # Rate limit: 5 req/s

    print(f"\n=== Summary ===")
    print(f"Updated: {updated}")
    print(f"Failed (no fills): {failed}")
    if updated == 0:
        print("Nothing changed. NOT writing CSV.")
        return

    # Write back
    print(f"\nWriting CSV: {CSV_PATH}")
    # Re-collect all rows in original order, but with updated ex2sum entries
    with open(CSV_PATH, 'w', newline='') as f:
        writer = csv.DictWriter(f, fieldnames=rows[0].keys(), delimiter=';')
        writer.writeheader()
        for row in rows:
            writer.writerow(row)
    print("Done.")


if __name__ == '__main__':
    main()
