#!/usr/bin/env python3
"""
Lädt die Exchange-API-Keys aus config.yaml in die ENV des Kindprozesses.

WARUM DIESES SKRIPT EXISTIERT
----------------------------
config.yaml enthält echte API-Keys und darf von niemandem außer dem
Container selbst gelesen werden — insbesondere nicht von einem
KI-Assistenten, dessen Kontext protokolliert/ausgegeben werden kann.

Deshalb ist der Lesevorgang ein Skript *innerhalb* des Containers:
  1. Dieses Skript liest config.yaml (einziger Ort, an dem das passiert).
  2. Es schreibt die Werte in os.environ des Kindprozesses.
  3. Es ruft den echten Bot per exec() auf - der Kindprozess erbt die ENV.
  4. Die Werte werden NIE ausgegeben, geloggt oder in eine Datei geschrieben.

Was der Operator (Mensch/Assistent) zu sehen bekommt, ist ausschließlich
eine maskierte Zusammenfassung: welcher Key ist gesetzt, wie lang ist er.
Kein Klartext, keine Previews, kein Base64.

Nutzung (im Container):
    python3 scripts/load_keys_to_env.py python3 arb_autotrade.py
    python3 scripts/load_keys_to_env.py streamlit run dashboard.py --server.port=8501

Alternativ ohne args: es wird der Befehl aus ARB_ENTRYPOINT_CMD gelesen.
"""
from __future__ import annotations

import os
import shlex
import sys
from pathlib import Path

# Pfad im Container (Config ist als Volume gemountet)
CONFIG_PATH = Path(os.environ.get('ARB_CONFIG_PATH', '/app/config/config.yaml'))

# Ziel-Variablennamen. Reihenfolge = Ausgabe-Reihenfolge.
ENV_MAP = {
    'KUCOIN_KEY': ('kucoin', 'api_key'),
    'KUCOIN_SECRET': ('kucoin', 'api_secret'),
    'KUCOIN_PASSPHRASE': ('kucoin', 'api_passphrase'),
    'MEXC_KEY': ('mexc', 'api_key'),
    'MEXC_SECRET': ('mexc', 'api_secret'),
}


def _mask(value: str) -> str:
    """Maske: nur Laenge + erste/rueckwaerts-Typ, kein Klartext.

    Bewusst KEIN Prefix/Suffix: bei 30-Zeichen-Secrets wuerde das
    2/3 des Secrets preisgeben. Nur die Laenge ist informativ genug.
    """
    if not value:
        return '(leer)'
    return f'gesetzt, {len(value)} Zeichen'


def load_keys_from_config(path: Path) -> dict:
    """Liest die Keys aus config.yaml. Gibt NIE etwas aus ausser dem Returnwert."""
    try:
        import yaml
    except ImportError:
        print('[load_keys] WARNUNG: pyyaml fehlt, Keys koennen nicht geladen werden',
              file=sys.stderr)
        return {}

    try:
        with open(path, 'r', encoding='utf-8') as f:
            cfg = yaml.safe_load(f) or {}
    except FileNotFoundError:
        print(f'[load_keys] config.yaml nicht gefunden: {path}', file=sys.stderr)
        return {}
    except Exception as exc:
        # Nur der Exception-Typ, nie der Inhalt (koennte Keys enthalten).
        print(f'[load_keys] config.yaml nicht lesbar: {type(exc).__name__}',
              file=sys.stderr)
        return {}

    if not isinstance(cfg, dict):
        return {}

    result = {}
    for env_name, (section, field) in ENV_MAP.items():
        block = cfg.get(section) or {}
        if not isinstance(block, dict):
            continue
        val = block.get(field) or ''
        result[env_name] = str(val).strip()
    return result


def main() -> int:
    # Kommando bestimmen
    if len(sys.argv) > 1:
        cmd = sys.argv[1:]
    else:
        raw = os.environ.get('ARB_ENTRYPOINT_CMD', '').strip()
        if not raw:
            print('[load_keys] Kein Zielbefehl angegeben.', file=sys.stderr)
            return 2
        cmd = shlex.split(raw)

    if not cmd:
        print('[load_keys] Leerer Zielbefehl.', file=sys.stderr)
        return 2

    file_keys = load_keys_from_config(CONFIG_PATH)

    # Praezedenz: bereits gesetzte ENV gewinnt (z.B. docker-compose env_file),
    # ENV aus config.yaml nur als Auffuellung fuer leere Werte.
    applied, kept = [], []
    for env_name in ENV_MAP:
        current = (os.environ.get(env_name) or '').strip()
        if current:
            kept.append(env_name)
            continue
        value = file_keys.get(env_name, '')
        if value:
            os.environ[env_name] = value
            applied.append(env_name)

    # Maskierte Zusammenfassung - KEINE Werte, nur Status.
    print('[load_keys] Key-Status (maskiert):')
    for env_name in ENV_MAP:
        val = (os.environ.get(env_name) or '').strip()
        quelle = 'ENV' if env_name in kept else ('config.yaml' if env_name in applied else '-')
        print(f'[load_keys]   {env_name:20s} {_mask(val):22s} Quelle: {quelle}')

    if not any((os.environ.get(n) or '').strip() for n in ENV_MAP):
        print('[load_keys] WARNUNG: keine API-Keys vorhanden '
              '(Bot bleibt in WAITING, keine Trades moeglich).', file=sys.stderr)

    # exec: Kindprozess erbt die gesetzte ENV.
    # sys.argv[0] wird zum Skriptnamen -> passt die Nutzung
    # "python3 scripts/load_keys_to_env.py <cmd...>" an.
    os.execvp(cmd[0], cmd)
    return 0  # wird nicht erreicht


if __name__ == '__main__':
    sys.exit(main())
