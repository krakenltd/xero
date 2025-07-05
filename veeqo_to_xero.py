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

# ---------- 3. Get total stock value from Veeqo's report ----------
report = requests.get(
    "https://api.veeqo.com/reports/inventory_value",   # no location_id = all locations
    headers={"x-api-key": os.environ["VEEQO_API_KEY"], "accept": "application/json"},
).json()

total = decimal.Decimal(str(report["total_stock_value"]))

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
