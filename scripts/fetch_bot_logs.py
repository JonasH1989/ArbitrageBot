#!/usr/bin/env python3
"""
Holt Bot-Logs von einem Host und legt sie in der lokalen Historie ab.

Wird per Cron alle 15 Minuten aufgerufen. Haelt die Log-Historie als
lueckenlose Kette: jeder Lauf schreibt ein eigenes Snapshot-File mit
Groesse/MTime-Angabe, damit Lauecken (Log wurde dazwischen rotiert)
erkennbar sind.

Erwartet:
  ARB_LOG_SSH_HOST   z.B. root@192.168.13.57
  ARB_LOG_SSH_KEY    Pfad zum SSH-Key
  ARB_LOG_REMOTE_DIR  z.B. /opt/arb/ArbitrageBot/logs
  ARB_LOG_DEST       lokales Zielverzeichnis

Alle Pfade haben Defaults, die der aktuellen Umgebung entsprechen.
"""
from __future__ import annotations

import os
import subprocess
import sys
from datetime import datetime
from pathlib import Path

SSH_HOST = os.environ.get('ARB_LOG_SSH_HOST', 'root@192.168.13.57')
SSH_KEY = os.environ.get('ARB_LOG_SSH_KEY', str(Path.home() / '.ssh/id_coolifydev'))
REMOTE_DIR = os.environ.get('ARB_LOG_REMOTE_DIR', '/opt/arb/ArbitrageBot/logs')
DEST = Path(os.environ.get(
    'ARB_LOG_DEST',
    '/home/openclaw/.openclaw/workspace/trading/arbitrage-bot-history/logs'))

# Dateien, die abgezogen werden. Trade-CSVs sind ausgeschlossen
# (groessere Mengen, eigene Historie).
LOG_FILES = ['arb_autotrade.log']


def _ssh(*args: str) -> tuple[int, str, str]:
    cmd = ['ssh', '-i', SSH_KEY, '-o', 'BatchMode=yes', '-o', 'ConnectTimeout=10',
           SSH_HOST, *args]
    try:
        p = subprocess.run(cmd, capture_output=True, text=True, timeout=90)
    except subprocess.TimeoutExpired:
        return 1, '', 'timeout'
    return p.returncode, p.stdout, p.stderr


def main() -> int:
    DEST.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime('%Y%m%d-%H%M%S')
    fetched, failed = [], []

    for fname in LOG_FILES:
        rc, out, err = _ssh('cat', f'{REMOTE_DIR}/{fname}')
        if rc != 0:
            failed.append(f'{fname}: {err.strip()[:120]}')
            continue
        if not out:
            failed.append(f'{fname}: leer')
            continue
        target = DEST / f'{fname.replace(".log", "")}_{stamp}.log'
        target.write_text(out, encoding='utf-8')
        fetched.append(f'{fname} -> {target.name} ({len(out)} bytes)')

    # Status-Datei mit Metadaten (ohne Secrets)
    meta = DEST / f'_fetch_status_{stamp}.txt'
    meta.write_text(
        f'fetched_at: {datetime.now().isoformat()}\n'
        f'host: {SSH_HOST}\n'
        f'remote_dir: {REMOTE_DIR}\n'
        + ''.join(f'OK   {f}\n' for f in fetched)
        + ''.join(f'FAIL {f}\n' for f in failed),
        encoding='utf-8')

    for f in fetched:
        print(f'[logfetch] OK   {f}')
    for f in failed:
        print(f'[logfetch] FAIL {f}', file=sys.stderr)
    return 1 if failed and not fetched else 0


if __name__ == '__main__':
    sys.exit(main())
