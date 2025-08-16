
# Wallet + Referral + Mining Demo (Flask)

Demo-only implementation of:
- Mobile recharge (demo credit)
- Diamond top-up (spend)
- Referral link & first-claim bonus
- Daily claim bonus (24 hours)
- Dollar buy/sell (demo)
- Balance & transactions
- Profile (referral link)
- Support & About pages
- Mining via product purchase with pretty URLs: `/p/<slug>`
- Simple "unlimited users" via database, not artificially restricted

## Quick Start

```bash
python -m venv .venv
source .venv/bin/activate  # Windows: .venv\Scripts\activate
pip install -r requirements.txt
python app.py
```

Open: http://127.0.0.1:5000

Use "Mobile Recharge" to add demo balance, then buy a product and watch mining accrue.
