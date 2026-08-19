#!/usr/bin/env python3
"""
Tests für debug_logger.

Ausführung:
    cd /home/openclaw/.openclaw/workspace/trading/arbitrage-bot
    python -m unittest tests/test_debug_logger.py -v
"""

import json
import os
import sys
import tempfile
import threading
import time
import unittest
from pathlib import Path

# Temp-Verzeichnis für isolierte Log-Files
TEST_LOG_DIR = tempfile.mkdtemp(prefix='debug_logger_test_')
os.environ['DEBUG_LOG_DIR'] = TEST_LOG_DIR
os.environ['DEBUG_LEVEL'] = '2'

# Singleton muss neu initialisiert werden mit den neuen Env-Vars
if 'debug_logger' in sys.modules:
    del sys.modules['debug_logger']

from debug_logger import dbg, DebugLogger  # noqa: E402


class TestDebugLogger(unittest.TestCase):
    """Tests für das Singleton Debug-Logger Modul."""

    def setUp(self):
        # Reset für jeden Test
        dbg.set_level(2)
        dbg._last_idle_emit = 0
        with dbg._async_buffer_lock:
            dbg._async_buffer = []
        # Cleanup alte Test-Files
        for f in Path(TEST_LOG_DIR).glob('*.jsonl'):
            f.unlink()

    def tearDown(self):
        for f in Path(TEST_LOG_DIR).glob('*.jsonl'):
            f.unlink()

    def _read_jsonl(self, kind: str) -> list:
        """Liest alle Einträge einer Log-Datei als JSON-Liste."""
        today = datetime_now_utc_day()
        path = Path(TEST_LOG_DIR) / f'{kind}_{today}.jsonl'
        if not path.exists():
            return []
        with open(path) as f:
            return [json.loads(line) for line in f if line.strip()]

    # ============================================================
    # Level-Filterung
    # ============================================================

    def test_level_0_logs_nothing(self):
        """Bei Level 0 wird nichts geschrieben."""
        dbg.set_level(0)
        dbg.trigger('test_event', value=42)
        dbg.state_change('WAITING', 'RUNNING')
        dbg.error('test_error', exc=ValueError('x'))
        dbg.flush()
        time.sleep(0.15)
        self.assertEqual(len(self._read_jsonl('trigger')), 0)
        self.assertEqual(len(self._read_jsonl('state')), 0)
        self.assertEqual(len(self._read_jsonl('error')), 0)

    def test_level_1_logs_state_and_error_only(self):
        """Bei Level 1 nur state_change + error (kein trigger)."""
        dbg.set_level(1)
        dbg.trigger('test_event', value=42)            # soll ignoriert werden
        dbg.state_change('WAITING', 'RUNNING', reason='test')
        dbg.error('test_error', exc=ValueError('x'))
        self.assertEqual(len(self._read_jsonl('trigger')), 0)
        self.assertEqual(len(self._read_jsonl('state')), 1)
        self.assertEqual(len(self._read_jsonl('error')), 1)

    def test_level_2_logs_everything(self):
        """Bei Level 2 wird alles geschrieben (trigger, state, error)."""
        dbg.set_level(2)
        dbg.trigger('spread_check', spread_mk=0.0087)
        dbg.state_change('WAITING', 'RUNNING', reason='spread_ok')
        try:
            raise RuntimeError('simulated')
        except RuntimeError as e:
            dbg.error('something failed', exc=e)
        self.assertEqual(len(self._read_jsonl('trigger')), 1)
        self.assertEqual(len(self._read_jsonl('state')), 1)
        self.assertEqual(len(self._read_jsonl('error')), 1)

    # ============================================================
    # JSON-Format
    # ============================================================

    def test_json_format_valid(self):
        """Jede Zeile ist valides JSON mit ts, pid, kind, event."""
        dbg.set_level(2)
        dbg.trigger('test', value='hello', num=42, lst=[1, 2, 3])
        records = self._read_jsonl('trigger')
        self.assertEqual(len(records), 1)
        r = records[0]
        for key in ('ts', 'pid', 'kind', 'event'):
            self.assertIn(key, r)
        self.assertEqual(r['event'], 'test')
        self.assertEqual(r['value'], 'hello')
        self.assertEqual(r['num'], 42)
        self.assertEqual(r['lst'], [1, 2, 3])

    def test_state_change_records_transition(self):
        """state_change loggt from, to, reason."""
        dbg.set_level(2)
        dbg.state_change('WAITING', 'RUNNING', reason='spread_above_threshold')
        records = self._read_jsonl('state')
        self.assertEqual(len(records), 1)
        self.assertEqual(records[0]['from'], 'WAITING')
        self.assertEqual(records[0]['to'], 'RUNNING')
        self.assertEqual(records[0]['reason'], 'spread_above_threshold')

    def test_error_records_traceback(self):
        """error loggt exc_type, exc_msg, traceback."""
        dbg.set_level(2)
        try:
            raise ValueError('boom')
        except ValueError as e:
            dbg.error('place_order failed', exc=e, ctx={'qty': 100})
        records = self._read_jsonl('error')
        self.assertEqual(len(records), 1)
        self.assertEqual(records[0]['exc_type'], 'ValueError')
        self.assertEqual(records[0]['exc_msg'], 'boom')
        self.assertIn('traceback', records[0])
        self.assertIsNotNone(records[0]['traceback'])
        self.assertEqual(records[0]['ctx'], {'qty': 100})

    # ============================================================
    # API-Call Truncation
    # ============================================================

    def test_api_call_truncation(self):
        """Große Response-Bodies werden trunkiert."""
        dbg.set_level(2)
        long_response = {'data': 'x' * 10000}
        dbg.api_call('mexc', 'POST', '/orders', {'side': 'buy'}, long_response, 123)
        records = self._read_jsonl('api')
        self.assertEqual(len(records), 1)
        self.assertEqual(records[0]['response'], '<truncated>')
        self.assertEqual(records[0]['exchange'], 'mexc')
        self.assertEqual(records[0]['elapsed_ms'], 123)

    def test_api_call_short_response_kept(self):
        """Kurze Responses bleiben unverändert."""
        dbg.set_level(2)
        response = {'orderId': '123', 'status': 'filled'}
        dbg.api_call('kucoin', 'GET', '/orders/123', None, response, 50)
        records = self._read_jsonl('api')
        self.assertEqual(records[0]['response'], response)

    # ============================================================
    # Idle-Throttling
    # ============================================================

    def test_idle_throttled_to_60s(self):
        """idle() wird auf 60s throttled."""
        dbg.set_level(2)
        dbg.idle('WAITING', last_spread=0.001)
        dbg.flush()
        time.sleep(0.15)
        first_count = len(self._read_jsonl('idle'))
        # Zweiter Aufruf sofort danach — soll ignoriert werden
        dbg.idle('WAITING', last_spread=0.002)
        dbg.flush()
        time.sleep(0.15)
        second_count = len(self._read_jsonl('idle'))
        self.assertEqual(first_count, 1)
        self.assertEqual(second_count, 1)  # Throttle hat gewirkt

    def test_idle_silent_at_level_0(self):
        """idle() wird bei Level 0 ignoriert."""
        dbg.set_level(0)
        dbg.idle('WAITING', last_spread=0.001)
        dbg.flush()
        time.sleep(0.15)
        self.assertEqual(len(self._read_jsonl('idle')), 0)

    # ============================================================
    # Thread-Safety
    # ============================================================

    def test_concurrent_writes(self):
        """4 Threads × 50 Events = 200 Records, alle vollständig."""
        dbg.set_level(2)
        errors = []

        def worker(thread_id):
            try:
                for j in range(50):
                    dbg.trigger(f'w{thread_id}_e{j}', value=thread_id * 100 + j)
            except Exception as e:
                errors.append(e)

        threads = [threading.Thread(target=worker, args=(i,)) for i in range(4)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        self.assertEqual(len(errors), 0, f"Thread errors: {errors}")
        records = self._read_jsonl('trigger')
        self.assertEqual(len(records), 200)

    def test_concurrent_mixed_kinds(self):
        """Verschiedene Event-Typen aus verschiedenen Threads."""
        dbg.set_level(2)

        def writer_trigger():
            for i in range(20):
                dbg.trigger('test', n=i)

        def writer_state():
            for i in range(20):
                dbg.state_change('S1', 'S2', reason=f'r{i}')

        threads = [
            threading.Thread(target=writer_trigger),
            threading.Thread(target=writer_state),
        ]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        self.assertEqual(len(self._read_jsonl('trigger')), 20)
        self.assertEqual(len(self._read_jsonl('state')), 20)

    # ============================================================
    # Singleton-Verhalten
    # ============================================================

    def test_singleton_same_instance(self):
        """dbg ist immer dieselbe Instanz."""
        dbg2 = DebugLogger()
        self.assertIs(dbg, dbg2)
        # set_level auf einer Instanz wirkt auf beide
        dbg.set_level(1)
        self.assertEqual(dbg2.level, 1)

    def test_level_clamped_to_0_2(self):
        """Level wird auf [0, 2] geklemmt."""
        dbg.set_level(5)
        self.assertEqual(dbg.level, 2)
        dbg.set_level(-1)
        self.assertEqual(dbg.level, 0)

    # ============================================================
    # Log-Directory Resolution
    # ============================================================

    def test_log_dir_exists(self):
        """Log-Verzeichnis existiert nach Singleton-Init."""
        self.assertTrue(dbg.log_dir.exists())
        self.assertTrue(dbg.log_dir.is_dir())

    def test_files_created_in_log_dir(self):
        """Log-Files werden im log_dir erstellt."""
        dbg.set_level(2)
        dbg.trigger('test')
        files = list(Path(TEST_LOG_DIR).glob('trigger_*.jsonl'))
        self.assertEqual(len(files), 1)


def datetime_now_utc_day() -> str:
    """Hilfsfunktion: heutiges Datum als YYYY-MM-DD in UTC."""
    from datetime import datetime, timezone
    return datetime.now(timezone.utc).strftime('%Y-%m-%d')


if __name__ == '__main__':
    unittest.main(verbosity=2)
