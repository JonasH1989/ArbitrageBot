# Exchange Specific Notes

## KuCoin

### API Authentication
- **Passphrase Encryption Required**: API v2 requires the passphrase to be encrypted with HMAC-SHA256 (using API secret) and then base64 encoded.
- **Header**: Must include `KC-API-KEY-VERSION: 2`

```python
def kucoin_passphrase_enc(secret, passphrase):
    mac = hmac.new(secret.encode(), passphrase.encode(), hashlib.sha256)
    return base64.b64encode(mac.digest()).decode()
```

### Minimum Order
- Minimum order quantity: **~84 MPC** (at ~$0.012 price = 1 USDT minimum)
- This varies by price - calculate as: `min_qty = ceil(1.0 / price)`
- MEXC also has 1 USDT minimum, same calculation

### Symbols
- Symbol format: `MPC-USDT` (hyphen, not a slash)

## MEXC

### API Authentication
- Signature: HMAC-SHA256 of `timestamp + method + requestPath + body`
- Header: `X-MEXC-APIKEY`

### Minimum Order
- Minimum order: **1 USDT** per order
- At $0.012 MPC price ≈ 84 MPC minimum
- If quantity is below minimum, order fails with: `{"msg":"The minimum transaction volume cannot be less than：1USDT","code":30002}`

### Symbols
- Symbol format: `MPCUSDT` (no hyphen)

## General

### Minimum Order Quantities (as of 2026-04-23)
| Exchange | Min USDT | Min MPC (~$0.012) |
|----------|----------|------------------|
| KuCoin   | ~1 USDT  | ~84 MPC          |
| MEXC     | 1 USDT   | ~84 MPC          |

**Important**: When calculating trade quantities, always ensure:
1. Above minimum for both exchanges
2. Account for fees
3. Check spread AFTER fees (net profit, not gross)

### Spread Calculation
- Spread must be >= START_THRESHOLD **after fees** to be profitable
- Always calculate: `gross_spread - (fee_ex1 + fee_ex2) >= threshold`

---

*Last updated: 2026-04-23*