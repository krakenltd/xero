import os, requests, time
from decimal import Decimal, InvalidOperation

# ---------- 1.  Get a 30-min Xero access-token ----------
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

# ---------- 2.  Tenant ID ----------
tenant_id = os.getenv("XERO_TENANT_ID") or requests.get(
    "https://api.xero.com/connections",
    headers={"Authorization": f"Bearer {access_token}"},
).json()[0]["tenantId"]

# ---------- 3.  Total stock value = Σ(cost_price × qty_all_warehouses) ----------
hdrs = {
    "x-api-key": os.environ["VEEQO_API_KEY"],
    "accept":    "application/json",
}

def safe_decimal(v):
    try:
        return Decimal(str(v))
    except (InvalidOperation, TypeError, ValueError):
        return Decimal("0")

total = Decimal("0")
url = "https://api.veeqo.com/products?per_page=200&page=1"

while url:
    resp = requests.get(url, headers=hdrs)
    resp.raise_for_status()
    print(f"[DEBUG] headers for {url} →", dict(resp.headers))
    page = resp.json()

    # ---- DEBUG: show how many products parsed on this page
    print(f"[DEBUG] fetched {len(page)} products from → {url}")

    for product in page:
        for variant in product.get("sellables", []):
            cost = safe_decimal(variant.get("cost_price") or 0)
            qty  = safe_decimal(
                variant.get("inventory", {}).get(
                    "physical_stock_level_at_all_warehouses", 0
                )
            )
            if cost > 0 and qty > 0:
                total += cost * qty
    url = resp.links.get("next", {}).get("url")
    time.sleep(0.3)

print(f"Total inventory across all warehouses = £{total}")

if total == 0:
    print("Inventory total is £0 – aborting run.")
    raise SystemExit(0)

# ---------- 4.  Post the Manual Journal to Xero ----------
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
