"""Count historical short opens from exchange since last deposit."""

import json
from exchange import Exchange
from datetime import datetime, timezone

config = json.load(open("config.json"))
ex = Exchange(config)
ex.load_markets()

bills = ex.exchange.privateMixGetV2MixAccountBill({
    "productType": "USDT-FUTURES",
    "limit": "100",
})
bill_list = bills.get("data", {}).get("bills", [])
bill_list.sort(key=lambda b: int(b.get("cTime", 0)))

# Find last deposit
deposit_time = None
for b in bill_list:
    if b.get("businessType") == "trans_from_exchange":
        deposit_time = int(b.get("cTime", 0))

if deposit_time:
    dt = datetime.fromtimestamp(deposit_time / 1000, tz=timezone.utc)
    print(f"Last deposit: {dt.strftime('%Y-%m-%d %H:%M UTC')}")
else:
    print("No deposit found")
    exit(1)

# Count unique open_short orders after deposit (by symbol + minute)
opens = [b for b in bill_list if b.get("businessType") == "open_short" and int(b.get("cTime", 0)) >= deposit_time]
unique_orders = set()
for b in opens:
    sym = b.get("symbol")
    ts = int(b.get("cTime", 0))
    minute = ts // 60000
    unique_orders.add((minute, sym))

print(f"open_short bills: {len(opens)}")
print(f"Unique orders: {len(unique_orders)}")
