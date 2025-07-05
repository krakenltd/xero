import os, requests, time
from decimal import Decimal, InvalidOperation

# ---------- 1. Get a 30-min Xero access token ----------
token = requests.post(
    "https://identity.xero.com/connect/token",
    headers={"Content-Type": "application/x-www-form-urlencoded"},
    data={
        "grant_type": "client_credentials",
        "scope": "accounting.transactions accounting.journals.read",
        "client_id": os.environ["XERO_CLIENT_ID"],
        "client_secret": os.environ["XERO_CLIENT_SECRET"],
    },
).json()
access_token = token["access_token"]

# ---------- 2. Get tenant ID (once) ----------
tenant_id = os.getenv("XERO_TENANT_ID") or requests.get(
    "https://api.xero.com/connections",
    headers={"Authorization": f"Bearer {access_token}"},
).json()[0]["tenantId"]

# ---------- 3. Calculate total stock value (uses stock_entries endpoint) ----------
hdrs = {
    "x-api-key": os.environ["VEEQO_API_KEY"],
    "accept":    "application/json",
}

def safe_decimal(v):
    try:
        return Decimal(str(v))
    except (InvalidOperation, TypeError, ValueError):
        return Decimal("0")

def value_for_location(loc_id: str) -> Decimal:
    total_loc = Decimal("0")
    url = f"https://api.veeqo.com/stock_entries?warehouse_id={loc_id}&per_page=200&page=1"
    while url:
        resp = requests.get(url, headers=hdrs)
        resp.raise_for_status()
        for entry in resp.json():
            val = entry.get("sellable_on_hand_value")
            if val not in (None, "", 0, "0", "0.0"):
                total_loc += safe_decimal(val)
        url = resp.links.get("next", {}).get("url")
    return total_loc

total = sum(
    value_for_location(loc.strip())
    for loc in os.environ["VEEQO_LOCATION_IDS"].split(",")
)

print(f"Total inventory across all locations = £{total}")

if total == 0:
    print("Inventory total is £0 – no journal posted.")
    raise SystemExit(0)

# ---------- 4. Post the Manual Journal to Xero ----------
today = time.strftime("%Y-%m-%d")
journal = {
    "Narration": "Daily Veeqo stock revaluation",
    "Date": today,
    "Status": "POSTED",
    "JournalLines": [
        {"AccountCode": "320", "LineAmount": float(total)},   # Stock on Hand
        {"AccountCode": "630", "LineAmount": float(-total)},  # Adjustment
    ],
}

resp = requests.post(
    "https://api.xero.com/api.xro/2.0/ManualJournals",
    headers={
        "Authorization": f"Bearer {access_token}",
        "xero-tenant-id": tenant_id,
        "Accept": "application/json",
    },
    json=journal,
)
print("Xero reply:", resp.status_code, resp.text)
resp.raise_for_status()
print(f"Posted £{total} to Xero ✔️")
