This script syncs medical devices from Medigate (a security platform) to Illumio (a network segmentation platform). Here's the flow:

## **Configuration & Setup**
- Loads API credentials and settings from environment variables (Medigate API token, Illumio PCE host/credentials, etc.)
- Sets up logging

## **Step 1: Fetch Medigate Devices**
`fetch_medigate_devices()` - Calls the Medigate API to pull all devices matching:
- **device_category** = "Medical"
- **risk_score** = "Critical"
- **retired** = false (only active devices)
- Handles pagination to get all results

## **Step 2: Extract & Clean IPs**
- `extract_ips()` - Pulls IP addresses from each device's `ip_list` field
- `clean_ip()` - Removes annotations (like " (Last known IP)") from raw IP strings, keeping only the actual IP address
- Returns a deduplicated set of unique IPs

## **Step 3: Sync to Illumio**
`ensure_iplist()` - Creates or updates an IP List in Illumio:
- Checks if an IP List with the target name already exists
- If it exists, updates it with the new IPs
- If not, creates a new IP List
- Converts each IP into an `IPRange` object for Illumio's API

## **Main Workflow**
`sync_medigate_to_illumio()` - Orchestrates everything:
- Validates that all required environment variables are set
- Fetches devices from Medigate
- Extracts IP addresses
- Updates the Illumio IP List with those addresses

Essentially, it's **synchronizing critical medical devices from Medigate into Illumio for network security policies**.
