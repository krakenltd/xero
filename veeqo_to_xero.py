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
from decimal import Decimal, InvalidOperation

hdrs = {                                # ← Add these three lines
    "x-api-key": os.environ["VEEQO_API_KEY"],
    "accept":    "application/json",
}

def safe_decimal(v):
    try:
        return Decimal(str(v))
    except (InvalidOperation, TypeError, ValueError):
        return Decimal("0")

def diy_location_value(location_id):
    """Sum warehouse value for one location, skipping zero / missing entries."""
    total_loc = Decimal("0")
    url = "https://api.veeqo.com/products?per_page=200&page=1&include[]=stock"
    while url:
        resp = requests.get(url, headers=hdrs)
        resp.raise_for_status()
        for p in resp.json():
            cost = safe_decimal(p.get("cost_price") or 0)
            loc = p.get("stock", {}).get(str(location_id)) or p.get("stock", {}).get(location_id)
            if not loc:
                continue

            # 1. Prefer explicit warehouse stock value
            if loc.get("stock_value") not in (None, "", 0, "0", "0.0"):
                total_loc += safe_decimal(loc["stock_value"])
                continue
            if loc.get("on_hand_value") not in (None, "", 0, "0", "0.0"):
                total_loc += safe_decimal(loc["on_hand_value"])
                continue

            # 2. Fallback: cost_price × physical_stock_level (only if cost>0)
            qty = safe_decimal(loc.get("physical_stock_level") or 0)
            if cost > 0 and qty > 0:
                total_loc += cost * qty
        url = resp.links.get("next", {}).get("url")
        time.sleep(0.3)
    return total_loc

total = Decimal("0")
location_ids = os.environ["VEEQO_LOCATION_IDS"].split(",")  # "328835,124495"

for loc_id in location_ids:
    url = f"https://api.veeqo.com/reports/inventory_value?location_id={loc_id}"
    r = requests.get(url, headers=hdrs)

    if r.status_code == 200:
        data = r.json()

        # ----- three ways Veeqo may wrap the number -----
        if "stock_value" in data:
            total += safe_decimal(data["stock_value"])

        elif "total_stock_value" in data:
            total += safe_decimal(data["total_stock_value"])

        elif "data" in data and isinstance(data["data"], list) and data["data"]:
            block = data["data"][0]             # first (only) row
            if "stock_value" in block:
                total += safe_decimal(block["stock_value"])
            elif "total_stock_value" in block:
                total += safe_decimal(block["total_stock_value"])
            else:
                print(f"Unrecognised keys in report for {loc_id}, using fallback.")
                total += diy_location_value(loc_id)

        else:
            print(f"Unrecognised structure for {loc_id}, using fallback.")
            total += diy_location_value(loc_id)

    elif r.status_code == 404:
        print(f"Report unavailable for {loc_id}, using fallback.")
        total += diy_location_value(loc_id)

    else:
        r.raise_for_status()

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
