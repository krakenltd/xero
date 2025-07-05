import os, requests, decimal, time

# ---------- 1. Get a 30-min access token from Xero ----------
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

# ---------- 2. Find tenant ID (unless you stored it) ----------
tenant_id = os.getenv("XERO_TENANT_ID")
if not tenant_id:
    tenant_id = requests.get(
        "https://api.xero.com/connections",
        headers={"Authorization": f"Bearer {access_token}"},
    ).json()[0]["tenantId"]

# ---------- 3. Compute total stock value across ALL locations ----------
from decimal import Decimal, InvalidOperation

def safe_decimal(v):
    try:
        return Decimal(str(v))
    except (InvalidOperation, TypeError, ValueError):
        return Decimal("0")

total = Decimal("0")
url = "https://api.veeqo.com/products?per_page=200&page=1"
headers = {
    "x-api-key": os.environ["VEEQO_API_KEY"],
    "accept": "application/json",
}

while url:
    resp = requests.get(url, headers=headers)
    data = resp.json()

    for p in data:
        cost = safe_decimal(p.get("cost_price") or 0)

        # p["stock"] is a dict: {location_id: {...}, ...}
        for loc in p.get("stock", {}).values():
            # Most accounts expose one of these keys:
            if "on_hand_value" in loc and loc["on_hand_value"] is not None:
                total += safe_decimal(loc["on_hand_value"])
            elif "stock_value" in loc and loc["stock_value"] is not None:
                total += safe_decimal(loc["stock_value"])
            else:
                qty = safe_decimal(loc.get("physical_stock_level") or 0)
                total += cost * qty

    # follow the “next” link if pagination header is present
    url = resp.links.get("next", {}).get("url")
    time.sleep(0.3)            # stay well inside Veeqo’s 5-req/sec limit


# ---------- 4. Post the Manual Journal to Xero ----------
today = time.strftime("%Y-%m-%d")
journal = {
    "Narration": "Daily Veeqo stock revaluation",
    "Date": today,
    "Status": "POSTED",
    "JournalLines": [
        {"AccountCode": "320", "LineAmount": float(total)},   # debit Stock-on-Hand
        {"AccountCode": "630", "LineAmount": float(-total)},  # credit Adjustment
    ],
}
req_hdrs = {
    "Authorization": f"Bearer {access_token}",
    "xero-tenant-id": tenant_id,
    "Accept": "application/json",
}
resp = requests.post(
    "https://api.xero.com/api.xro/2.0/ManualJournals",
    headers=req_hdrs,
    json=journal,
)
print("Xero reply:", resp.status_code, resp.text)   # <-- add this
resp.raise_for_status()                             # keep this

print(f"Posted £{total} to Xero")
