import os, requests, time
from decimal import Decimal, InvalidOperation

# ---------- 1.  Get a 30-min Xero access-token (client-credentials flow) ----------
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

# ---------- 2.  Tenant ID (read secret or fetch once) ----------
tenant_id = os.getenv("XERO_TENANT_ID")
if not tenant_id:
    tenant_id = requests.get(
        "https://api.xero.com/connections",
        headers={"Authorization": f"Bearer {access_token}"},
    ).json()[0]["tenantId"]

# ---------- 3.  Total stock value using stock_entries ----------
hdrs = {                              #  ←  keep this near the top of the block
    "x-api-key": os.environ["VEEQO_API_KEY"],
    "accept":    "application/json",
}

from decimal import Decimal, InvalidOperation

def safe_decimal(v):
    try:
        return Decimal(str(v))
    except (InvalidOperation, TypeError, ValueError):
        return Decimal("0")

def value_for_location(location_id):
    total_loc = Decimal("0")
    url = "https://api.veeqo.com/products?per_page=200&page=1&include[]=stock_entries"
    while url:
        resp = requests.get(url, headers=hdrs)
        resp.raise_for_status()
        for p in resp.json():
            for entry in p.get("stock_entries", []):
                if str(entry.get("warehouse_id")) == str(location_id):
                    val = entry.get("sellable_on_hand_value")
                    if val not in (None, "", 0, "0", "0.0"):
                        total_loc += safe_decimal(val)
        url = resp.links.get("next", {}).get("url")
        time.sleep(0.3)
    return total_loc

total = Decimal("0")
for loc_id in os.environ["VEEQO_LOCATION_IDS"].split(","):
    total += value_for_location(loc_id)

print(f"Total inventory across all locations = £{total}")
if total == 0:
    print("Inventory total is £0 – aborting run.")
    raise SystemExit(0)


# ---------- 4.  Abort if value is zero (prevents empty journal) ----------
if total == Decimal("0"):
    print("Inventory total is £0 – no journal posted.")
    raise SystemExit(0)

# ---------- 5.  Post the Manual Journal to Xero ----------
today = time.strftime("%Y-%m-%d")
journal = {
    "Narration": "Daily Veeqo stock revaluation",
    "Date": today,
    "Status": "POSTED",
    "JournalLines": [
        {"AccountCode": "320", "LineAmount": float(total)},    # debit Stock-on-Hand
        {"AccountCode": "630", "LineAmount": float(-total)},   # credit Adjustment
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
