"""
Tests for Dashboard Trade-Counter (Multi-Row-Pattern).

Verifies the fix for the bug where:
- Dashboard counted CSV rows instead of unique trade_ids (4-7x too many)
- Profit sums included ex2_value_usdt from ex2p* rows (massive over-counting)
- get_trades(limit=1000) capped visible trades at ~166
- Open trades' negative initial profit was counted as realized loss

The fix introduces:
- count_main_trades() in trade_logger.py: iterates ALL rows, dedupes by trade_id
- total_profit_usdt() in trade_logger.py: sums profit_usdt_actual from _ex2sum rows
- completed_profit_usdt() in trade_logger.py: only FILLED trades (Jonas 2026-10-19)
- open_trade_count() in trade_logger.py: count of OPEN trades (Jonas 2026-10-19)
- is_main_trade_row() / is_ex2sum_row() in dashboard.py: suffix filters for detail view
"""

import csv
import sys
from pathlib import Path

# Add project root to path so 'import trade_logger' works
sys.path.insert(0, str(Path(__file__).parent.parent))

from trade_logger import (
    TRADE_ROW_SUFFIXES,
    count_main_trades,
    total_profit_usdt,
    completed_profit_usdt,
    open_trade_count,
    UNIFIED_COLUMNS,
)


# Mirror of dashboard.py helper logic — kept in sync with is_main_trade_row.
# If you change the helper in dashboard.py, update here too (and vice versa).
def is_main_trade_row(row: dict) -> bool:
    """Mirror of dashboard.is_main_trade_row for unit testing."""
    tid = (row.get("trade_id") or "").strip()
    return bool(tid) and not any(tid.endswith(s) for s in TRADE_ROW_SUFFIXES)


def is_ex2sum_row(row: dict) -> bool:
    """Mirror of dashboard.is_ex2sum_row for unit testing."""
    return (row.get("trade_id") or "").endswith("_ex2sum")


def make_test_csv(path: Path, rows: list) -> None:
    """Write a test CSV with the given rows. Missing columns default to ''."""
    with open(path, "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=UNIFIED_COLUMNS, delimiter=";")
        writer.writeheader()
        for row in rows:
            writer.writerow({col: row.get(col, "") for col in UNIFIED_COLUMNS})


# =============================================================================
# TRADE_ROW_SUFFIXES — sanity check
# =============================================================================

def test_trade_row_suffixes_complete():
    """TRADE_ROW_SUFFIXES should cover all known suffix types (1-5 each)."""
    assert "_ex1p1" in TRADE_ROW_SUFFIXES
    assert "_ex2p1" in TRADE_ROW_SUFFIXES
    assert "_ex2sum" in TRADE_ROW_SUFFIXES
    for n in range(1, 6):
        assert f"_ex1p{n}" in TRADE_ROW_SUFFIXES, f"missing _ex1p{n}"
        assert f"_ex2p{n}" in TRADE_ROW_SUFFIXES, f"missing _ex2p{n}"


# =============================================================================
# is_main_trade_row / is_ex2sum_row — unit tests (mirror of dashboard.py)
# =============================================================================

def test_is_main_trade_row_true_for_main():
    assert is_main_trade_row({"trade_id": "0c102f0747"}) is True
    assert is_main_trade_row({"trade_id": "abc123"}) is True
    assert is_main_trade_row({"trade_id": "  0c102f0747  "}) is True  # whitespace stripped


def test_is_main_trade_row_false_for_suffixes():
    assert is_main_trade_row({"trade_id": "0c102f0747_ex1p1"}) is False
    assert is_main_trade_row({"trade_id": "0c102f0747_ex1p2"}) is False
    assert is_main_trade_row({"trade_id": "0c102f0747_ex2p1"}) is False
    assert is_main_trade_row({"trade_id": "0c102f0747_ex2sum"}) is False


def test_is_main_trade_row_false_for_empty():
    assert is_main_trade_row({"trade_id": ""}) is False
    assert is_main_trade_row({}) is False
    assert is_main_trade_row({"trade_id": None}) is False


def test_is_ex2sum_row():
    assert is_ex2sum_row({"trade_id": "0c102f0747_ex2sum"}) is True
    assert is_ex2sum_row({"trade_id": "0c102f0747"}) is False
    assert is_ex2sum_row({"trade_id": "0c102f0747_ex2p1"}) is False
    assert is_ex2sum_row({"trade_id": "0c102f0747_ex1p1"}) is False
    assert is_ex2sum_row({"trade_id": ""}) is False


# =============================================================================
# count_main_trades — integration tests (uses tmp_path + monkeypatch)
# =============================================================================

def test_count_main_trades_no_csv():
    """Returns 0 if CSV does not exist."""
    assert count_main_trades("NONEXISTENT-PAIR-FAKE") == 0


def test_count_main_trades_single_trade(tmp_path, monkeypatch):
    """Returns 1 for a single trade with 5-row multi-row pattern."""
    monkeypatch.setattr("trade_logger.LOG_DIR", tmp_path)
    rows = [
        {"trade_id": "0c102f0747", "ex1": "MXC", "ex1_value_usdt": "3.21"},
        {"trade_id": "0c102f0747_ex1p1", "ex1_qty_filled": "90.0"},
        {"trade_id": "0c102f0747_ex1p2", "ex1_qty_filled": "93.0"},
        {"trade_id": "0c102f0747_ex2sum", "ex2_value_usdt": "3.32"},
        {"trade_id": "0c102f0747_ex2p1", "ex2_qty_filled": "183.0"},
    ]
    make_test_csv(tmp_path / "TESTUSDT_trades.csv", rows)
    assert count_main_trades("TEST-USDT") == 1


def test_count_main_trades_multiple_trades(tmp_path, monkeypatch):
    """Counts unique trade_ids, not rows. 10 trades × 4 rows = 40 rows → 10."""
    monkeypatch.setattr("trade_logger.LOG_DIR", tmp_path)
    rows = []
    for i in range(10):
        tid = f"0c102f{i:04x}"
        rows.append({"trade_id": tid})
        rows.append({"trade_id": f"{tid}_ex1p1"})
        rows.append({"trade_id": f"{tid}_ex2sum"})
        rows.append({"trade_id": f"{tid}_ex2p1"})
    make_test_csv(tmp_path / "TESTUSDT_trades.csv", rows)
    assert count_main_trades("TEST-USDT") == 10


def test_count_main_trades_no_1000_limit(tmp_path, monkeypatch):
    """Iterates over ALL rows (no 1000-limit). 500 trades × 3 rows = 1500 rows."""
    monkeypatch.setattr("trade_logger.LOG_DIR", tmp_path)
    rows = []
    for i in range(500):
        tid = f"0c102{i:04x}"
        rows.append({"trade_id": tid})
        rows.append({"trade_id": f"{tid}_ex1p1"})
        rows.append({"trade_id": f"{tid}_ex2sum"})
    make_test_csv(tmp_path / "TESTUSDT_trades.csv", rows)
    # 500 trades, NOT ~166 (which would be the case with 1000-row limit)
    assert count_main_trades("TEST-USDT") == 500


# =============================================================================
# total_profit_usdt — integration tests
# =============================================================================

def test_total_profit_usdt_no_csv():
    """Returns 0.0 if CSV does not exist."""
    assert total_profit_usdt("NONEXISTENT-PAIR-FAKE") == 0.0


def test_total_profit_usdt_sums_ex2sum_only(tmp_path, monkeypatch):
    """Sums profit_usdt_actual from _ex2sum rows ONLY (avoids double-counting)."""
    monkeypatch.setattr("trade_logger.LOG_DIR", tmp_path)
    rows = [
        # Trade 1: profit 0.10
        {"trade_id": "t1"},
        {"trade_id": "t1_ex1p1"},
        {"trade_id": "t1_ex2sum", "profit_usdt_actual": "0.10"},
        # ex2p1 has ex2_value_usdt=3.2 — would inflate if summed naively
        {"trade_id": "t1_ex2p1", "ex2_value_usdt": "3.2"},
        # Trade 2: profit 0.20
        {"trade_id": "t2"},
        {"trade_id": "t2_ex2sum", "profit_usdt_actual": "0.20"},
        {"trade_id": "t2_ex2p1", "ex2_value_usdt": "5.3"},
    ]
    make_test_csv(tmp_path / "TESTUSDT_trades.csv", rows)
    # Should be 0.10 + 0.20 = 0.30
    # NOT 0.10 + 0.20 + 3.2 + 5.3 = 8.80 (naive sum over all rows)
    assert abs(total_profit_usdt("TEST-USDT") - 0.30) < 1e-9


def test_total_profit_usdt_handles_comma_decimal(tmp_path, monkeypatch):
    """Handles comma decimal separator (German locale in CSV)."""
    monkeypatch.setattr("trade_logger.LOG_DIR", tmp_path)
    rows = [
        {"trade_id": "t1_ex2sum", "profit_usdt_actual": "0,15"},
        {"trade_id": "t2_ex2sum", "profit_usdt_actual": "0,25"},
    ]
    make_test_csv(tmp_path / "TESTUSDT_trades.csv", rows)
    assert abs(total_profit_usdt("TEST-USDT") - 0.40) < 1e-9


def test_total_profit_usdt_handles_invalid_values(tmp_path, monkeypatch):
    """Skips rows with invalid/empty profit values (does not crash)."""
    monkeypatch.setattr("trade_logger.LOG_DIR", tmp_path)
    rows = [
        {"trade_id": "t1_ex2sum", "profit_usdt_actual": "0.10"},
        {"trade_id": "t2_ex2sum", "profit_usdt_actual": "invalid"},
        {"trade_id": "t3_ex2sum", "profit_usdt_actual": ""},
        {"trade_id": "t4_ex2sum", "profit_usdt_actual": "0.30"},
    ]
    make_test_csv(tmp_path / "TESTUSDT_trades.csv", rows)
    assert abs(total_profit_usdt("TEST-USDT") - 0.40) < 1e-9


def test_total_profit_usdt_no_1000_limit(tmp_path, monkeypatch):
    """Iterates over ALL rows (no 1000-limit)."""
    monkeypatch.setattr("trade_logger.LOG_DIR", tmp_path)
    rows = []
    for i in range(2000):  # 2000 ex2sum rows
        rows.append({"trade_id": f"t{i}_ex2sum", "profit_usdt_actual": "0.01"})
    make_test_csv(tmp_path / "TESTUSDT_trades.csv", rows)
    # 2000 × 0.01 = 20.0 (would be capped at ~10.0 with 1000-row limit)
    assert abs(total_profit_usdt("TEST-USDT") - 20.0) < 1e-6


# =============================================================================
# completed_profit_usdt — integration tests (Jonas 2026-10-19)
# =============================================================================

def test_completed_profit_usdt_no_csv():
    """Returns 0.0 if CSV does not exist."""
    assert completed_profit_usdt("NONEXISTENT-PAIR-FAKE") == 0.0


def test_completed_profit_usdt_filters_open_trades(tmp_path, monkeypatch):
    """Sums profit only from _ex2sum rows with ex2_status='FILLED'.
    Open trades (initial negative profit) must NOT be counted."""
    monkeypatch.setattr("trade_logger.LOG_DIR", tmp_path)
    rows = [
        # Trade 1: FILLED, profit 0.10
        {"trade_id": "t1_ex2sum", "ex2_status": "FILLED", "profit_usdt_actual": "0.10"},
        # Trade 2: OPEN, profit -3.21 (initial, before limit fill)
        {"trade_id": "t2_ex2sum", "ex2_status": "OPEN", "profit_usdt_actual": "-3.21"},
        # Trade 3: FILLED, profit 0.20
        {"trade_id": "t3_ex2sum", "ex2_status": "FILLED", "profit_usdt_actual": "0.20"},
        # Trade 4: PARTIAL (in progress) — also not counted
        {"trade_id": "t4_ex2sum", "ex2_status": "PARTIAL", "profit_usdt_actual": "-1.50"},
    ]
    make_test_csv(tmp_path / "TESTUSDT_trades.csv", rows)
    # Should be 0.10 + 0.20 = 0.30 (FILLED only)
    # NOT 0.10 - 3.21 + 0.20 - 1.50 = -4.41 (all rows including OPEN)
    assert abs(completed_profit_usdt("TEST-USDT") - 0.30) < 1e-9


def test_completed_profit_usdt_no_open_trades(tmp_path, monkeypatch):
    """When all trades are FILLED, sum equals total_profit_usdt for FILLED rows."""
    monkeypatch.setattr("trade_logger.LOG_DIR", tmp_path)
    rows = [
        {"trade_id": "t1_ex2sum", "ex2_status": "FILLED", "profit_usdt_actual": "0.10"},
        {"trade_id": "t2_ex2sum", "ex2_status": "FILLED", "profit_usdt_actual": "0.25"},
    ]
    make_test_csv(tmp_path / "TESTUSDT_trades.csv", rows)
    assert abs(completed_profit_usdt("TEST-USDT") - 0.35) < 1e-9


def test_completed_profit_usdt_handles_lowercase_status(tmp_path, monkeypatch):
    """ex2_status is compared case-insensitive (some rows may have 'filled' lowercase)."""
    monkeypatch.setattr("trade_logger.LOG_DIR", tmp_path)
    rows = [
        {"trade_id": "t1_ex2sum", "ex2_status": "filled", "profit_usdt_actual": "0.10"},
        {"trade_id": "t2_ex2sum", "ex2_status": "open", "profit_usdt_actual": "-3.0"},
    ]
    make_test_csv(tmp_path / "TESTUSDT_trades.csv", rows)
    assert abs(completed_profit_usdt("TEST-USDT") - 0.10) < 1e-9


# =============================================================================
# open_trade_count — integration tests (Jonas 2026-10-19)
# =============================================================================

def test_open_trade_count_no_csv():
    """Returns 0 if CSV does not exist."""
    assert open_trade_count("NONEXISTENT-PAIR-FAKE") == 0


def test_open_trade_count_only_ex2sum(tmp_path, monkeypatch):
    """Only counts _ex2sum rows with ex2_status='OPEN'.
    OPEN status in ex2p* rows must NOT be counted (those are fills, not pending limits)."""
    monkeypatch.setattr("trade_logger.LOG_DIR", tmp_path)
    rows = [
        # 2 OPEN trades
        {"trade_id": "t1_ex2sum", "ex2_status": "OPEN"},
        {"trade_id": "t2_ex2sum", "ex2_status": "OPEN"},
        # 1 FILLED
        {"trade_id": "t3_ex2sum", "ex2_status": "FILLED"},
        # ex2p* row with OPEN — must NOT count
        {"trade_id": "t1_ex2p1", "ex2_status": "OPEN"},
        # Main row with OPEN status — must NOT count
        {"trade_id": "t1", "ex2_status": "OPEN"},
    ]
    make_test_csv(tmp_path / "TESTUSDT_trades.csv", rows)
    assert open_trade_count("TEST-USDT") == 2


def test_open_trade_count_no_open(tmp_path, monkeypatch):
    """Returns 0 when no trades are open."""
    monkeypatch.setattr("trade_logger.LOG_DIR", tmp_path)
    rows = [
        {"trade_id": "t1_ex2sum", "ex2_status": "FILLED"},
        {"trade_id": "t2_ex2sum", "ex2_status": "CANCELLED"},
    ]
    make_test_csv(tmp_path / "TESTUSDT_trades.csv", rows)
    assert open_trade_count("TEST-USDT") == 0
