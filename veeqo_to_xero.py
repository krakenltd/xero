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

# ---------- 3.  Total stock value across ALL Veeqo locations ----------
def safe_decimal(v):
    try:
        return Decimal(str(v))
    except (InvalidOperation, TypeError, ValueError):
        return Decimal("0")

total = Decimal("0")
location_ids = os.environ["VEEQO_LOCATION_IDS"].split(",")  # e.g. "328835,124495"

hdrs = {
    "x-api-key": os.environ["VEEQO_API_KEY"],
    "accept": "application/json",
}

for loc_id in location_ids:
    url = f"https://api.veeqo.com/reports/inventory_value?location_id={loc_id}"
    r = requests.get(url, headers=hdrs)
    if r.status_code == 404:
        raise RuntimeError(f"Inventory report not enabled for location {loc_id}")
    data = r.json()  # format may vary by account

    if "stock_value" in data:
        total += safe_decimal(data["stock_value"])
    elif "total_stock_value" in data:
        total += safe_decimal(data["total_stock_value"])
    else:
        raise RuntimeError(f"Unexpected structure for location {loc_id}: {data}")

print(f"Total inventory across all locations = £{total}")

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
