import os
import logging
import requests
from illumio import PolicyComputeEngine, IPList, IPRange


# ----------------------------
# Config (via environment vars)
# ----------------------------
MEDIGATE_API_URL = os.getenv("MEDIGATE_API_URL", "https://api.medigate.io")
MEDIGATE_API_TOKEN = os.getenv("MEDIGATE_API_TOKEN")
MEDIGATE_PAGE_SIZE = int(os.getenv("MEDIGATE_PAGE_SIZE", "500"))

PCE_HOST = os.getenv("PCE_HOST")
PCE_PORT = os.getenv("PCE_PORT", "8443")
PCE_ORG_ID = os.getenv("PCE_ORG_ID", "1")
PCE_API_KEY = os.getenv("PCE_API_KEY")
PCE_API_SECRET = os.getenv("PCE_API_SECRET")

# Name of the IP List in Illumio you want to manage
TARGET_IPLIST_NAME = os.getenv(
    "TARGET_IPLIST_NAME",
    "MEDIGATE-Medical-Critical"
)

# Auto-provision toggle
AUTO_PROVISION = os.getenv("AUTO_PROVISION", "true").lower() == "true"

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("medigate_illumio_sync")


# ---------------
# Medigate client
# ---------------
def medigate_headers():
    return {
        "Authorization": f"Bearer {MEDIGATE_API_TOKEN}",
        "Accept": "application/json",
        "Content-Type": "application/json",
    }


def fetch_medigate_devices():
    """
    Pull devices matching:
      - device_category = Medical
      - risk_score = Critical
      - retired = false
    Paginate over all results.
    """
    url = f"{MEDIGATE_API_URL.rstrip('/')}/api/v1/devices/"
    devices = []
    offset = 0

    while True:
        body = {
            "filter_by": {
                "operation": "and",
                "operands": [
                    {
                        "field": "device_category",
                        "operation": "in",
                        "value": ["Medical"],
                    },
                    {
                        "field": "risk_score",
                        "operation": "in",
                        "value": ["Critical"],
                    },
                    {
                        "field": "retired",
                        "operation": "in",
                        "value": [False],
                    },
                ],
            },
            "offset": offset,
            "limit": MEDIGATE_PAGE_SIZE,
            "fields": ["ip_list", "device_type", "device_category", "uid"],
            "include_count": False,
        }

        logger.info("Requesting Medigate devices offset=%d limit=%d", offset, MEDIGATE_PAGE_SIZE)
        resp = requests.post(url, headers=medigate_headers(), json=body, timeout=60)
        resp.raise_for_status()
        data = resp.json()

        batch = data.get("devices", [])
        if not batch:
            break

        devices.extend(batch)
        logger.info("Fetched %d devices so far (batch size %d)", len(devices), len(batch))

        if len(batch) < MEDIGATE_PAGE_SIZE:
            break
        offset += MEDIGATE_PAGE_SIZE

    logger.info("Finished Medigate fetch: total devices %d", len(devices))
    return devices


def clean_ip(ip_str: str) -> str:
    """
    Strip annotation like ' (Last known IP)' from IP strings,
    keeping only the IP portion.
    """
    if not ip_str:
        return ""
    return ip_str.split()[0].strip()


def extract_ips(devices):
    """
    Build a set of cleaned IPs from devices[].ip_list.
    """
    ips = set()
    for d in devices:
        ip_list = d.get("ip_list") or []
        for raw_ip in ip_list:
            ip = clean_ip(raw_ip)
            if ip:
                ips.add(ip)
    return ips


# -------------
# Illumio client
# -------------
def illumio_client():
    pce = PolicyComputeEngine(PCE_HOST, port=PCE_PORT, org_id=PCE_ORG_ID)
    pce.set_credentials(PCE_API_KEY, PCE_API_SECRET)
    return pce


def get_iplist_by_name(pce, name):
    ip_lists = pce.ip_lists.get(params={"name": name})
    return ip_lists[0] if ip_lists else None


def ensure_iplist(pce, name, ip_set):
    """
    Create or replace an IP List with the given set of IPs.
    """
    ip_ranges = [IPRange(from_ip=ip) for ip in sorted(ip_set)]

    existing = get_iplist_by_name(pce, name)
    if existing:
        logger.info(
            "Updating IP List '%s' (%s) with %d IPs",
            name,
            existing.href,
            len(ip_set),
        )
        update_body = {
            "ip_ranges": [{"from_ip": ip} for ip in sorted(ip_set)]
        }
        pce.ip_lists.update(existing.href, update_body)
    else:
        logger.info("Creating IP List '%s' with %d IPs", name, len(ip_set))
        new_list = IPList(name=name, ip_ranges=ip_ranges)
        pce.ip_lists.create(new_list)


def auto_provision(pce):
    """
    Automatically provision draft changes in Illumio.
    """
    logger.info("Requesting Illumio policy provision")

    payload = {
        "update_description": f"Automated Medigate sync for IP List '{TARGET_IPLIST_NAME}'"
    }

    # illumio-py does not expose every workflow cleanly across versions,
    # so use the underlying API call directly.
    response = pce.post("/sec_policy", json=payload)

    logger.info("Provision request submitted: %s", response)


# ------------
# Main workflow
# ------------
def sync_medigate_to_illumio():
    if not MEDIGATE_API_TOKEN:
        raise RuntimeError("MEDIGATE_API_TOKEN is not set")
    if not all([PCE_HOST, PCE_API_KEY, PCE_API_SECRET]):
        raise RuntimeError("Illumio PCE env vars are not fully set")

    logger.info("Starting Medigate → Illumio sync for IP List '%s'", TARGET_IPLIST_NAME)

    devices = fetch_medigate_devices()
    ip_set = extract_ips(devices)

    logger.info("Extracted %d unique IPs from Medigate", len(ip_set))

    if not ip_set:
        raise RuntimeError("No IPs were extracted from Medigate; refusing to update Illumio with an empty set")

    pce = illumio_client()
    ensure_iplist(pce, TARGET_IPLIST_NAME, ip_set)

    if AUTO_PROVISION:
        auto_provision(pce)
    else:
        logger.info("AUTO_PROVISION is disabled; skipping Illumio provision step")

    logger.info("Sync complete for IP List '%s'", TARGET_IPLIST_NAME)


if __name__ == "__main__":
    sync_medigate_to_illumio()
