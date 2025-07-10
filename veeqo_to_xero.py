import os, requests, time
from decimal import Decimal, InvalidOperation

# ---------- 1.  Xero access token (client-credentials flow) ----------
token = requests.post(
    "https://identity.xero.com/connect/token",
    headers={"Content-Type": "application/x-www-form-urlencoded"},
    data={
        "grant_type":    "client_credentials",
        "scope":         "accounting.transactions accounting.journals.read",
        "client_id":     os.environ["XERO_CLIENT_ID"],
        "client_secret": os.environ["XERO_CLIENT_SECRET"],
    },
).json()
access_token = token["access_token"]

# ---------- 2.  Tenant ID ----------
tenant_id = os.getenv("XERO_TENANT_ID") or requests.get(
    "https://api.xero.com/connections",
    headers={"Authorization": f"Bearer {access_token}"},
).json()[0]["tenantId"]

# ---------- 3.  Pull every product & sum cost × qty ----------
hdrs = {
    "x-api-key": os.environ["VEEQO_API_KEY"],
    "accept":    "application/json",
}

def d(val):                 # safe Decimal
    try:
        return Decimal(str(val))
    except (InvalidOperation, TypeError, ValueError):
        return Decimal("0")

total = Decimal("0")
page  = 1
while True:
    url = f"https://api.veeqo.com/products?per_page=200&page={page}"
    resp = requests.get(url, headers=hdrs)
    resp.raise_for_status()

    tot_pages = int(resp.headers.get("X-Total-Pages-Count", 1))
    for product in resp.json():
        for v in product.get("sellables", []):
            cost = d(v.get("cost_price"))
            qty  = d(v.get("inventory", {}).get(
                     "physical_stock_level_at_all_warehouses", 0))
            if cost > 0 and qty > 0:
                total += cost * qty

    if page >= tot_pages:
        break
    page += 1
    time.sleep(0.3)  # stay below rate limit

if total == 0:
    print("Inventory total is £0 – no journal posted.")
    raise SystemExit(0)

print(f"Total inventory across all warehouses = £{total}")

# ---------- 4a. Void the latest revaluation journal (if any) ----------
search = requests.get(
    "https://api.xero.com/api.xro/2.0/ManualJournals",
    headers={
        "Authorization": f"Bearer {access_token}",
        "xero-tenant-id": tenant_id,
        "Accept": "application/json",
    },
    params={
        "where": 'Narration=="Daily Veeqo stock revaluation" && Status=="POSTED"',
        "order": "UpdatedDateUTC DESC",  # newest first
        "page": 1,
    },
).json()

if search.get("ManualJournals"):
    last_id = search["ManualJournals"][0]["ManualJournalID"]
    print(f"[INFO] Voiding previous journal {last_id}")
    requests.post(
        f"https://api.xero.com/api.xro/2.0/ManualJournals/{last_id}",
        headers={
            "Authorization": f"Bearer {access_token}",
            "xero-tenant-id": tenant_id,
            "Accept": "application/json",
        },
        json={"Status": "VOIDED"},
    )
else:
    print("[INFO] No prior revaluation journal found")

# ---------- 4.  Ensure only ONE journal for today ----------
today = time.strftime("%Y-%m-%d")

old = requests.get(
    "https://api.xero.com/api.xro/2.0/ManualJournals",
    headers={
        "Authorization": f"Bearer {access_token}",
        "xero-tenant-id": tenant_id,
        "Accept": "application/json",
    },
    params={
        "where": (
            f'Date==DateTime({today}) '
            f'&& Narration=="Daily Veeqo stock revaluation"'
        )
    },
).json()

for mj in old.get("ManualJournals", []):
    jid = mj["ManualJournalID"]
    requests.post(
        f"https://api.xero.com/api.xro/2.0/ManualJournals/{jid}",
        headers={
            "Authorization": f"Bearer {access_token}",
            "xero-tenant-id": tenant_id,
            "Accept": "application/json",
        },
        json={"Status": "VOIDED"},
    )

# ---------- 5.  Post today’s journal ----------
journal = {
    "Narration": "Daily Veeqo stock revaluation",
    "Date":      today,
    "Status":    "POSTED",
    "JournalLines": [
        {"AccountCode": "630", "LineAmount":  float(total)},   # debit Inventory
        {"AccountCode": "999", "LineAmount": -float(total)},   # credit Adjustment
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
