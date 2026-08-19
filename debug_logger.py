#!/usr/bin/env python3
"""
Debug-Logger für Arbitrage-Bot
==============================

Persistent-File-basierter Logger für den Trigger-Pfad.
JSON-Lines Format, ein File pro Tag, fsync auf kritischen Pfaden.

Pfade (in Reihenfolge der Prüfung):
  1. DEBUG_LOG_DIR (env, falls gesetzt)
  2. /app/logs/debug              (Container)
  3. ./logs/debug                 (lokal)

Levels:
  0 = OFF       — nichts wird geloggt
  1 = SUMMARY   — state_change + error + idle (async, 100ms flush)
  2 = FULL      — alles: trigger + api_call mit fsync (sync)

Verwendung:
    from debug_logger import dbg
    dbg.set_level(2)
    dbg.trigger('spread_check', spread_mk=0.0087, threshold=0.006)
    dbg.state_change('WAITING', 'RUNNING', reason='spread_ok')
    dbg.api_call('mexc', 'POST', '/orders', req, resp, elapsed_ms=123)
    dbg.error('place_order failed', exc=e, ctx={'qty': 100})
    dbg.idle('WAITING', last_spread=0.002)
    dbg.flush()  # vor Shutdown

Architektur (Stand 2026-08-19, Jonas-Freigabe):
    — Trigger-Pfad (seltene Events): sync + fsync auf Level 2
    — Idle-Pfad (häufige Heartbeats): async mit 100ms-Buffer-Flush
    — Errors: immer sync, fsync auf Level 2
    — Thread-safe via Lock pro Datei
    — Bei Crash bleiben alle Level-2-Daten erhalten (fsync vor write)
"""

import json
import os
import sys
import threading
import time
import traceback
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional


DEFAULT_LOG_DIRS = [
    Path('/app/logs/debug'),          # Container (via Volume-Mount)
    Path('./logs/debug'),             # Lokal (relativ zum CWD)
]


def _resolve_log_dir() -> Path:
    """Sucht das erste beschreibbare Log-Verzeichnis.

    Reihenfolge:
      1. DEBUG_LOG_DIR (env)
      2. /app/logs/debug (Container)
      3. ./logs/debug (lokal)
    """
    override = os.environ.get('DEBUG_LOG_DIR')
    if override:
        p = Path(override)
        p.mkdir(parents=True, exist_ok=True)
        return p

    for p in DEFAULT_LOG_DIRS:
        try:
            p.mkdir(parents=True, exist_ok=True)
            # Test-Write, um Read-Only-FS zu erkennen
            test = p / '.write_test'
            test.write_text('ok')
            test.unlink()
            return p
        except (PermissionError, OSError):
            continue

    # Last resort (sollte nie passieren, aber besser als Crash)
    fallback = Path('./logs/debug')
    fallback.mkdir(parents=True, exist_ok=True)
    return fallback


class DebugLogger:
    """Singleton Debug-Logger für den Trigger-Pfad.

    Thread-safe via:
      — self._file_locks (ein Lock pro Log-Datei)
      — self._async_buffer_lock (Buffer für async-Events)

    Crash-Safety:
      — sync-Writes (trigger, api_call, error) nutzen os.fsync()
      — async-Writes (idle) haben 100ms-Buffer, dürfen bei Crash
        verloren gehen — Idle ist nicht crash-relevant
    """

    _instance: Optional['DebugLogger'] = None
    _singleton_lock = threading.Lock()

    def __new__(cls):
        if cls._instance is None:
            with cls._singleton_lock:
                if cls._instance is None:
                    inst = super().__new__(cls)
                    inst._init()
                    cls._instance = inst
        return cls._instance

    def _init(self):
        self._level = int(os.environ.get('DEBUG_LEVEL', '0'))
        self._log_dir = _resolve_log_dir()
        self._file_locks: dict = {}
        self._file_locks_lock = threading.Lock()
        self._async_buffer: list = []
        self._async_buffer_lock = threading.Lock()
        self._async_flush_thread: Optional[threading.Thread] = None
        self._async_flush_stop = threading.Event()
        self._last_idle_emit = 0.0

    # ============================================================
    # Public API
    # ============================================================

    @property
    def level(self) -> int:
        return self._level

    @property
    def log_dir(self) -> Path:
        return self._log_dir

    def set_level(self, level: int):
        """Setzt Debug-Level (0, 1, 2). Thread-safe."""
        with self._file_locks_lock:
            self._level = max(0, min(2, int(level)))

    def trigger(self, event: str, **kwargs):
        """Trigger-Pfad Event. Sync mit fsync bei Level 2."""
        if self._level < 2:
            return
        self._write_sync('trigger', event, kwargs, fsync=True)

    def state_change(self, from_state: str, to_state: str, reason: str = '', **kwargs):
        """State-Machine Transition. Sync, fsync bei Level 2."""
        if self._level < 1:
            return
        data = {'from': from_state, 'to': to_state, 'reason': reason, **kwargs}
        self._write_sync('state', 'transition', data, fsync=(self._level >= 2))

    def api_call(self, exchange: str, method: str, url: str,
                 request: Any, response: Any, elapsed_ms: float = 0, **kwargs):
        """Exchange API Call. Sync mit fsync bei Level 2.

        Response wird bei >5000 Zeichen trunkiert, damit Logs
        nicht explodieren (große Orderbook-Responses etc.).
        """
        if self._level < 2:
            return
        # Truncate large response bodies
        if isinstance(response, str) and len(response) > 5000:
            response = response[:5000] + '...[truncated]'
        elif isinstance(response, (dict, list)):
            try:
                response_str = json.dumps(response, default=str)
                if len(response_str) > 5000:
                    response = '<truncated>'
            except (TypeError, ValueError):
                response = '<unserializable>'
        data = {
            'exchange': exchange,
            'method': method,
            'url': url,
            'request': request,
            'response': response,
            'elapsed_ms': elapsed_ms,
            **kwargs,
        }
        self._write_sync('api', 'call', data, fsync=True)

    def error(self, msg: str, exc: Optional[BaseException] = None,
              ctx: Optional[dict] = None, **kwargs):
        """Error mit optionalem Exception-Trail. Sync, fsync bei Level 2."""
        if self._level < 1:
            return
        data = {
            'msg': msg,
            'exc_type': type(exc).__name__ if exc else None,
            'exc_msg': str(exc) if exc else None,
            'traceback': traceback.format_exc() if exc else None,
            'ctx': ctx or {},
            **kwargs,
        }
        self._write_sync('error', 'exception', data, fsync=(self._level >= 2))

    def idle(self, state: str, **kwargs):
        """Idle-Heartbeat. Async (100ms flush), kein fsync.

        Throttled auf 60s — der Bot pollt mehrmals pro Sekunde,
        aber Idle-Events sollen nur alle 60s ins Log.
        """
        if self._level < 1:
            return
        now = time.time()
        if (now - self._last_idle_emit) < 60:
            return
        self._last_idle_emit = now
        data = {'state': state, **kwargs}
        self._write_async('idle', 'heartbeat', data)

    def flush(self):
        """Manueller Flush aller Buffer. Vor Shutdown aufrufen."""
        self._flush_async_buffer()

    # ============================================================
    # Internals
    # ============================================================

    def _file_for(self, kind: str) -> Path:
        day = datetime.now(timezone.utc).strftime('%Y-%m-%d')
        return self._log_dir / f'{kind}_{day}.jsonl'

    def _get_lock_for(self, path: Path) -> threading.Lock:
        key = str(path)
        with self._file_locks_lock:
            if key not in self._file_locks:
                self._file_locks[key] = threading.Lock()
            return self._file_locks[key]

    def _write_sync(self, kind: str, event: str, data: dict, fsync: bool):
        """Synchrone Schreiboperation mit optionalem fsync."""
        record = {
            'ts': datetime.now(timezone.utc).isoformat(),
            'pid': os.getpid(),
            'kind': kind,
            'event': event,
            **data,
        }
        path = self._file_for(kind)
        line = json.dumps(record, default=str, ensure_ascii=False) + '\n'
        lock = self._get_lock_for(path)
        try:
            with lock:
                path.parent.mkdir(parents=True, exist_ok=True)
                with open(path, 'a', buffering=1) as f:
                    f.write(line)
                    if fsync:
                        f.flush()
                        os.fsync(f.fileno())
        except Exception as e:
            print(f"[debug_logger] write failed: {e}", file=sys.stderr)

    def _write_async(self, kind: str, event: str, data: dict):
        """Async Schreiboperation (100ms Buffer-Flush)."""
        record = {
            'ts': datetime.now(timezone.utc).isoformat(),
            'pid': os.getpid(),
            'kind': kind,
            'event': event,
            **data,
        }
        with self._async_buffer_lock:
            self._async_buffer.append((kind, record))
        self._ensure_async_thread()

    def _ensure_async_thread(self):
        """Startet Async-Flush-Thread, falls noch nicht aktiv."""
        if self._async_flush_thread is None or not self._async_flush_thread.is_alive():
            self._async_flush_stop.clear()
            self._async_flush_thread = threading.Thread(
                target=self._async_flush_loop,
                daemon=True,
                name='debug-logger-flush',
            )
            self._async_flush_thread.start()

    def _async_flush_loop(self):
        """Loop: alle 100ms Buffer flushen."""
        while not self._async_flush_stop.wait(0.1):
            self._flush_async_buffer()

    def _flush_async_buffer(self):
        """Schreibt den Async-Buffer in die entsprechenden Dateien."""
        with self._async_buffer_lock:
            buf = self._async_buffer
            self._async_buffer = []
        if not buf:
            return
        # Group by kind für weniger File-Opens
        by_kind: dict = {}
        for kind, rec in buf:
            by_kind.setdefault(kind, []).append(rec)
        for kind, records in by_kind.items():
            path = self._file_for(kind)
            lock = self._get_lock_for(path)
            try:
                with lock:
                    path.parent.mkdir(parents=True, exist_ok=True)
                    with open(path, 'a', buffering=1) as f:
                        for rec in records:
                            f.write(json.dumps(rec, default=str, ensure_ascii=False) + '\n')
                        f.flush()
                        os.fsync(f.fileno())  # beide INNERHALB des with-Blocks
            except Exception as e:
                print(f"[debug_logger] async flush failed: {e}", file=sys.stderr)


# Singleton-Instanz
dbg = DebugLogger()
