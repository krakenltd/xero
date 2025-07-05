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

# ---------- 3. Add up inventory value from Veeqo ----------
hdrs = {"x-api-key": os.environ["VEEQO_API_KEY"], "accept": "application/json"}
total = decimal.Decimal("0")
url = "https://api.veeqo.com/products?per_page=200&page=1"

def safe_decimal(val):
    """Return Decimal(val) or 0 if val is None/empty/invalid."""
    try:
        return decimal.Decimal(str(val))
    except (decimal.InvalidOperation, TypeError, ValueError):
        return decimal.Decimal("0")

while url:
    r = requests.get(url, headers=hdrs)
    data = r.json()
    total += sum(safe_decimal(p.get("on_hand_value")) for p in data)
    url = r.links.get("next", {}).get("url")
    time.sleep(0.3)  # stay under Veeqo’s rate limit

# ---------- 4. Post the Manual Journal to Xero ----------
today = time.strftime("%Y-%m-%d")
journal = {
    "Narration": "Daily Veeqo stock revaluation",
    "Date": today,
    "Status": "POSTED",
    "JournalLines": [
        {"AccountCode": "320", "LineAmount": float(total)},   # debit Stock-on-Hand
        {"AccountCode": "999", "LineAmount": float(-total)},  # credit Adjustment
    ],
}
req_hdrs = {
    "Authorization": f"Bearer {access_token}",
    "xero-tenant-id": tenant_id,
    "Accept": "application/json",
}
requests.post(
    "https://api.xero.com/api.xro/2.0/ManualJournals",
    headers=req_hdrs,
    json=journal,
).raise_for_status()

print(f"Posted £{total} to Xero")
