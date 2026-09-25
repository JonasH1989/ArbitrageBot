# Arbitrage Bot — System Status

**Stand:** 2026-09-25 09:10 MESZ
**Quellcode:** `/home/openclaw/.openclaw/workspace/trading/arbitrage-bot/`

---

## ⚠️ ARCHITEKTUR-FRAGE OFFEN (ehrliche Korrektur)

**Mein vorheriger STATUS.md (07:30) behauptete "Single-Container-Setup". Das war eine Annahme, kein Beweis.** Ich kann die Architektur vom OpenClaw-Host aus nicht verifizieren (kein Docker-Zugang zum Coolify-Host, kein SSH-Zugang, Coolify-MCP gestern down).

**Was ich weiß:**
- `docker-compose.yaml` definiert ZWEI separate Services (`bot` + `dashboard`)
- `Dockerfile.bot` startet nur `arb_autotrade.py`
- `Dockerfile.dashboard` startet nur Streamlit, kopiert aber `arb_autotrade.py` mit (= Verdacht: in Coolify wird Entrypoint überschrieben, sodass beides im Dashboard-Container startet)
- Vom Host aus sind BEIDE Ports exposed: Bot `18888`, Dashboard `8501` und `8502`

**Was ich nicht weiß:**
- Ob Coolify sie wirklich zu einem Container konsolidiert hat (meine Annahme von gestern)
- Ob die Container im Bridge-Netz des Hosts liegen und einander per IP/DNS erreichen
- Welche konkrete URL aus dem Dashboard-Container heraus den Bot erreicht

**Folge:** Falls meine "Single-Container"-Annahme falsch war, funktioniert `localhost:8505` aus dem Dashboard-Container NICHT — dann ist der Daten-Fehler erklärt.

---

## 🟢 FUNKTIONIERENDER ZUSTAND (vom OpenClaw-Host aus verifiziert)

| URL | Status |
|---|---|
| `http://192.168.113.14:18888/debug/internal-state` | ✅ `cache_update_count` steigt, `last_step=after_cache_update`, keine Errors |
| `http://192.168.113.14:18888/latest/spreads` | ✅ Echte Spread-Daten (Kucoin/MEXC) |
| `http://192.168.113.14:18888/latest/orderbook` | ✅ Echte Orderbook-Daten |
| `http://192.168.113.14:8501/` | ✅ Streamlit 200 OK (Healthcheck) |
| `http://192.168.113.14:8502/` | ✅ Streamlit 200 OK (Healthcheck) |

**Bot-Cache läuft. Vom OpenClaw-Host aus sind die Daten erreichbar.**

---

## 🔧 NEUER FIX (09:10, Commit steht aus)

**Was ich geändert habe:**

```diff
- CACHE_BASE_URL = os.environ.get('CACHE_BASE_URL', 'http://localhost:8505')
+ CACHE_BASE_URL = os.environ.get('CACHE_BASE_URL', 'http://192.168.113.14:18888')
```

**Plus Error-Logging im except-Block** (Z. 855):
```python
except Exception as e:
    st.error(f"❌ Cache-Call fehlgeschlagen: {CACHE_BASE_URL}/latest/spreads → {type(e).__name__}: {str(e)[:120]}")
```

**Begründung:**
- `localhost:8505` (alter Default) ist nur erreichbar wenn BEIDE im SELBEN Container laufen — Annahme unbewiesen
- `192.168.113.14:18888` ist die Host-IP, die aus jedem Container im Bridge-Netz erreichbar sein sollte (Standard-Verhalten bei Coolify/Docker)
- Falls die ENV nicht gesetzt ist (Jonas bestätigt: nichts gesetzt), greift jetzt der neue Default
- Falls es doch nicht klappt, zeigt der Dashboard jetzt den GENAUEN Fehler im UI — kein Rätselraten mehr

**ENV-Variable in Coolify:**
- Leer lassen → neuer Default greift
- Falls du explizit setzen willst: `CACHE_BASE_URL=http://192.168.113.14:18888`
- ❌ NICHT `arbitrage-bot:8505` setzen — das war gestern mein falscher Vorschlag

---

## 🔴 OFFENE PROBLEME

### 1. Dashboard zeigt "Daten nicht verfuegbar" für MPC-USDT

**Vermutung:** Cache-Call schlägt fehl, weil `localhost:8505` aus Dashboard-Container nicht erreichbar.

**Mit neuem Fix:** Dashboard zeigt entweder Daten (gelöst) ODER den konkreten Fehler im UI (Diagnose-Grundlage für nächsten Schritt).

### 2. Pre-existierende Endpoint-Bugs (nicht von meinen Edits verursacht)

| Endpoint | Problem |
|---|---|
| `/debug/log/files` | `'NoneType' object has no attribute 'log_dir'` |
| `/debug/log/last/arb_autotrade` | 500 Internal Server Error |
| `/status` | 500 Internal Server Error |

Diese brauchen separate Diagnose + Fix.

### 3. Pattern-Crashes (Server "wieder abgestürzt")

**Symptom:** Container restartet, `cache_update_count` springt zurück auf 0.
**Vermutung:** OOM (Out of Memory) weil kein Memory-Limit im Container.
**TODO:** Memory-Limit + Restart-Policy in Coolify-UI setzen (Jonas).

---

## 📋 BACKUP-REFERENZEN

- `docker-compose.yaml` (alt, Mai 2026): ZWEI Services — verlass dich nicht drauf, dass Coolify es genauso deployt
- `Dockerfile.bot`: Startet nur `arb_autotrade.py`
- `Dockerfile.dashboard`: Startet nur Streamlit, kopiert aber `arb_autotrade.py` mit
- `start.sh` / `start_bot.sh`: Manueller Start (nicht im Container)
