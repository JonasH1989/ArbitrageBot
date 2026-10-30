#!/usr/bin/env python3
"""
Holt Bot-Logs von einem Host und legt sie in der lokalen Historie ab.

Wird per Cron alle 15 Minuten aufgerufen.

WICHTIG - die Datei waechst nur noch, sie wird nicht mehr komplett kopiert:
Frueher wurde `arb_autotrade.log` bei jedem Lauf vollstaendig gelesen und
als neuer Snapshot abgelegt. Bei einer 1-GB-Quelldatei ergab das 4 GB
Zusatzspeicher pro Stunde und ueber 90 GB pro Tag (quadratisches
Wachstum). Die VM war dadurch zu 99 % voll.

Jetzt gilt:
  1. Nur die neuen Zeilen seit dem letzten Lauf werden geholt (Offset-Modus
     ueber `tail -c +N` auf der Gegenseite, Byte-Offset wird gemerkt).
  2. Der fortlaufende Log wird rotiert: sobald er MAX_LOG_BYTES ueberschreitet,
     wird er nach `arb_autotrade-<timestamp>.log.1` verschoben (ein Generationen-
     backup, .1 bis .3).
  3. Alte Archiv-Logs werden begrenzt (MAX_ARCHIVE_FILES / MAX_ARCHIVE_AGE_DAYS).

Erwartet:
  ARB_LOG_SSH_HOST   z.B. root@192.168.13.57
  ARB_LOG_SSH_KEY    Pfad zum SSH-Key
  ARB_LOG_REMOTE_DIR  Default: /data/coolify/applications/<app-uuid>/logs
  ARB_LOG_DEST       lokales Zielverzeichnis

Alle Pfade haben Defaults, die der aktuellen Umgebung entsprechen.
"""
from __future__ import annotations

import os
import subprocess
import sys
from datetime import datetime, timedelta
from pathlib import Path

SSH_HOST = os.environ.get('ARB_LOG_SSH_HOST', 'root@192.168.13.57')
SSH_KEY = os.environ.get('ARB_LOG_SSH_KEY', str(Path.home() / '.ssh/id_coolifydev'))
REMOTE_DIR = os.environ.get(
    'ARB_LOG_REMOTE_DIR',
    '/data/coolify/applications/6vqgknob3trgvpxiulcqtymu/logs')
DEST = Path(os.environ.get(
    'ARB_LOG_DEST',
    '/home/openclaw/.openclaw/workspace/trading/arbitrage-bot-history/logs'))

# Dateien, die abgezogen werden. Trade-CSVs sind ausgeschlossen
# (groessere Mengen, eigene Historie).
LOG_FILES = ['arb_autotrade.log']

# Groesse, ab der der lokale fortlaufende Log rotiert wird.
MAX_LOG_BYTES = int(os.environ.get('ARB_LOG_MAX_BYTES', 64 * 1024 * 1024))
# Anzahl rotierter Generationen, die aufbewahrt werden (arb_autotrade.log.1 ... .3)
MAX_ARCHIVE_FILES = int(os.environ.get('ARB_LOG_MAX_ARCHIVES', 3))
# Aufbewahrungsdauer der rotierten Dateien in Tagen.
MAX_ARCHIVE_AGE_DAYS = int(os.environ.get('ARB_LOG_MAX_ARCHIVE_AGE_DAYS', 14))
# Zustandsdatei: merkt sich den Byte-Offset des letzten Laufs.
STATE_FILE = DEST / '_fetch_state.json'


def _ssh(*args: str) -> tuple[int, str, str]:
    cmd = ['ssh', '-i', SSH_KEY, '-o', 'BatchMode=yes', '-o', 'ConnectTimeout=10',
           SSH_HOST, *args]
    try:
        p = subprocess.run(cmd, capture_output=True, text=True, timeout=90)
    except subprocess.TimeoutExpired:
        return 1, '', 'timeout'
    return p.returncode, p.stdout, p.stderr


def _load_state() -> dict:
    try:
        import json
        return json.loads(STATE_FILE.read_text(encoding='utf-8'))
    except Exception:
        return {}


def _save_state(state: dict) -> None:
    try:
        import json
        STATE_FILE.write_text(json.dumps(state, indent=2), encoding='utf-8')
    except Exception:
        pass


def _rotate(path: Path) -> None:
    """Rotiert den fortlaufenden Log: .1 -> .2 -> .3, neue Datei nach .1."""
    for i in range(MAX_ARCHIVE_FILES, 0, -1):
        src = path.with_suffix(path.suffix + f'.{i}')
        dst = path.with_suffix(path.suffix + f'.{i + 1}')
        if i == MAX_ARCHIVE_FILES:
            # Alteste Generation entfaellt.
            if src.exists():
                src.unlink()
        elif src.exists():
            src.rename(dst)
    if path.exists():
        path.rename(path.with_suffix(path.suffix + '.1'))


def _prune_archives(path: Path) -> None:
    """Entfernt zu alte rotierte Dateien."""
    cutoff = datetime.now() - timedelta(days=MAX_ARCHIVE_AGE_DAYS)
    for f in path.parent.glob(path.name + '.*'):
        if not f.is_file():
            continue
        try:
            mtime = datetime.fromtimestamp(f.stat().st_mtime)
        except OSError:
            continue
        if mtime < cutoff:
            try:
                f.unlink()
            except OSError:
                pass


def main() -> int:
    DEST.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime('%Y%m%d-%H%M%S')
    fetched, failed = [], []
    state = _load_state()

    for fname in LOG_FILES:
        remote_path = f'{REMOTE_DIR}/{fname}'
        local_path = DEST / fname

        # Offset seit dem letzten Lauf. Ohne Offset (erster Lauf) wird die
        # komplette Datei geholt - das ist einmalig und liegt bei 1 GB.
        offset = int(state.get(fname, {}).get('offset', 0) or 0)

        # Nur die Bytes ab dem gemerkten Offset holen. `tail -c +N` liest
        # ab Byte N (1-basiert) - ohne den Umweg ueber die ganze Datei.
        if offset > 0:
            rc, out, err = _ssh('tail', '-c', f'+{offset + 1}', remote_path)
        else:
            rc, out, err = _ssh('cat', remote_path)
        if rc != 0:
            failed.append(f'{fname}: {err.strip()[:120]}')
            continue

        # Gesamtgroesse der Gegenseite bestimmen, um den Offset zu validieren.
        rc2, sout, _ = _ssh('stat', '-c', '%s', remote_path)
        remote_size = int(sout.strip()) if rc2 == 0 and sout.strip().isdigit() else 0

        new_text = out
        rotated_remote = False
        if offset and remote_size and remote_size < offset:
            # Die Gegenseite hat rotiert: die Datei wurde nach .1 verschoben
            # und neu angelegt. Statt die ganze Datei erneut in die lokale
            # Datei zu haengen (Duplikate, ungebremstes Wachstum), wird die
            # lokale Datei selbst rotiert und neu begonnen. Die alte
            # Generation bleibt als .1 erhalten.
            _rotate(local_path)
            rotated_remote = True
            offset = 0
            new_text = out

        if new_text:
            with open(local_path, 'a', encoding='utf-8') as f:
                f.write(new_text)
            added = len(new_text)
        else:
            added = 0

        # Rotation, wenn die lokale Datei zu gross geworden ist.
        rotated = False
        if local_path.exists() and local_path.stat().st_size > MAX_LOG_BYTES:
            _rotate(local_path)
            rotated = True

        _prune_archives(local_path)

        # Neuer Offset: Position im aktuellen Remote-Inhalt.
        state[fname] = {
            'offset': remote_size if remote_size else offset + len(out),
            'last_fetch': datetime.now().isoformat(),
        }
        fetched.append(f'{fname}: +{added} Bytes (neu), lokal {local_path.stat().st_size if local_path.exists() else 0} Bytes'
                       + (', rotiert' if rotated else '')
                       + (', remote rotiert - lokal neu begonnen' if rotated_remote else ''))

    _save_state(state)

    # Status-Datei mit Metadaten (ohne Secrets)
    meta = DEST / f'_fetch_status_{stamp}.txt'
    meta.write_text(
        f'fetched_at: {datetime.now().isoformat()}\n'
        f'host: {SSH_HOST}\n'
        f'remote_dir: {REMOTE_DIR}\n'
        f'max_log_bytes: {MAX_LOG_BYTES}\n'
        + ''.join(f'OK   {f}\n' for f in fetched)
        + ''.join(f'FAIL {f}\n' for f in failed),
        encoding='utf-8')

    # Alte Statusdateien begrenzen (die letzten 20 behalten).
    statuses = sorted(DEST.glob('_fetch_status_*.txt'))
    for old in statuses[:-20]:
        try:
            old.unlink()
        except OSError:
            pass

    for f in fetched:
        print(f'[logfetch] OK   {f}')
    for f in failed:
        print(f'[logfetch] FAIL {f}', file=sys.stderr)
    return 1 if failed and not fetched else 0


if __name__ == '__main__':
    sys.exit(main())
