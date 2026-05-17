# WALLET TRANSFER TRACKING

## Übersicht

Der Bot überwacht Wallet-Bewegungen zwischen Börsen und erkennt Transfers automatisch:
- Balance-Änderung auf Exchange A (X MPC fehlen, nicht durch Trade erklärbar)
- Nach Verzögerung: Balance-Änderung auf Exchange B (X MPC angekommen, minus Transfer-Fee)

## Transfer Erkennung

### Erkennungslogik
```
1. Poll Wallet-Balance beide Exchanges (z.B. alle 60s)
2. Berechne: expected_balance = previous_balance ± trades_since_last_check
3. Wenn actual_balance != expected_balance UND diff > threshold:
   → Möglicher Transfer erkannt!
```

### Beispiel KCN -> MXC Transfer
| Zeit | KCN MPC | MXC MPC | Änderung |
|------|---------|---------|----------|
| T0 | 1000 | 500 | - |
| T1 | 800 | 500 | KCN: -200 MPC (nicht durch Trade erklärt) |
| T2 | 800 | 695 | MXC: +195 MPC angekommen (5 MPC Fee) |

## Trade Log Struktur für Transfers

### Row 2 (Main Transfer)
```
trade_id:              <id>_transfer
internal_ts:           Wann wir die Änderung zuerst erkannt haben
direction:             KCN->MXC oder MXC->KCN
pair:                  MPC-USDT
ex1_qty_ordered:      Gesendeter Betrag (vor Fee)
ex1_value_usdt:        Gesendeter Betrag in USDT
ex1_fees:              Transfer Fee (z.B. 0.50 USDT für Near)
ex1_create_ts:         Timestamp SENT erkannt
ex1_status:            SENT
ex2_qty_ordered:       Erhaltener Betrag (nach Fee)
ex2_value_usdt:        Erhaltener Betrag in USDT
ex2_create_ts:         Timestamp RECEIVED erkannt  
ex2_status:            RECEIVED oder PENDING
limit_watch_status:    PENDING | RECEIVED | SENT
```

### Transfer Status
| Status | Bedeutung |
|--------|----------|
| `PENDING` | Transfer erkannt, wartet auf Empfang |
| `SENT` | Von sendender Börse abgegangen |
| `RECEIVED` | Auf empfangender Börse angekommen |
| `LOST` | Nach Timeout nicht angekommen |

## Fees Berechnung
```
transfer_fee = ex1_value_usdt - ex2_value_usdt
```

## Service Architektur

```
┌─────────────────────────────────────────────────────┐
│            WalletTransferService                      │
│                                                      │
│  ┌─────────────┐    ┌──────────────┐    ┌─────────┐ │
│  │BalancePoller│───>│DiffDetector │───>│Transfer │ │
│  │ (60s loop)  │    │             │    │ Logger  │ │
│  └─────────────┘    └──────────────┘    └─────────┘ │
│         │                                       │      │
│         v                                       v      │
│  ┌─────────────┐                       ┌──────────┐ │
│  │TradeMatcher │                       │TradeCSV  │ │
│  │(Filter out  │                       │          │ │
│  │ known trades)│                       │_transfer │ │
│  └─────────────┘                       │ Einträge │ │
│                                        └──────────┘ │
└─────────────────────────────────────────────────────┘
```

## Implementierungsschritte

1. [ ] Balance Polling implementieren (KuCoin + MEXC APIs)
2. [ ] Trade-Matcher:已知 Trades von Balance-Änderung abziehen
3. [ ] Diff-Detektor: Flagge wenn unerklärte Änderung
4. [ ] Transfer-Logger in CSV
5. [ ] Timeout-Handler für hängende Transfers
6. [ ] Dashboard Integration

## CSV Struktur für Transfer Trades

| trade_id | internal_ts | direction | ex1 | ex1_value_usdt | ex1_fees | ex1_create_ts | ex1_status | ex2 | ex2_value_usdt | ex2_create_ts | ex2_status |
|----------|-------------|-----------|-----|-----------------|----------|---------------|------------|-----|----------------|---------------|-------------|
| 0c15192d61_transfer | 2026-05-12T16:47:05 | KCN->MXC | KCN | 1000 | 0.50 | 2026-05-12T16:47:05 | SENT | MXC | 999.50 | 2026-05-12T16:52:05 | RECEIVED |

---

*Stand: 2026-05-14*
