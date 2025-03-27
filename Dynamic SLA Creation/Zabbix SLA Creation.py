import requests
import json
import time
import urllib3

# Disable SSL warnings (for testing only; remove in production)
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

# --- Configuration ---
ZABBIX_URL = "https://your.zabbix.server/zabbix/api_jsonrpc.php"  # Replace with your Zabbix URL
API_TOKEN = "YOUR_API_TOKEN"  # Replace with your API token
HEADERS = {
    "Content-Type": "application/json",
    "Authorization": f"Bearer {API_TOKEN}"
}

def call_api(method, params, req_id=1):
    """
    Calls the Zabbix API using GET with token-based authentication.
    """
    payload = {
        "jsonrpc": "2.0",
        "method": method,
        "params": params,
        "id": req_id
    }
    response = requests.request("GET", ZABBIX_URL, headers=HEADERS, data=json.dumps(payload), verify=False)
    try:
        result = response.json()
    except Exception as e:
        print("Failed to parse SLA creation response:", e)
        result = {}
    if "error" in result:
        print(f"Error calling {method}: {result['error']}")
    return result

def get_client_services():
    """
    Retrieves all business services and returns those that have a problem tag "sla" equal to "true".
    We use "selectTags" and "selectProblemTags" to retrieve extended tag data.
    """
    params = {
        "output": ["serviceid", "name"],
        "selectTags": "extend",
        "selectProblemTags": "extend",
        "selectParents": "extend"
    }
    result = call_api("service.get", params, req_id=10)
    services = result.get("result", [])
    client_services = []
    for svc in services:
        p_tags = svc.get("problem_tags", [])
        for tag in p_tags:
            if tag.get("tag") == "sla" and tag.get("value") == "true":
                client_services.append(svc)
                break
    return client_services

def get_service_identifiers(svc):
    """
    From a client-level service, extract the environment and client values from its service tags.
    We assume that when the service was created, its service tags included:
       - {"tag": "environment", "value": <env>}
       - {"tag": "client", "value": <client>}
    """
    env = client = None
    tags = svc.get("tags", [])
    for tag in tags:
        if tag.get("tag") == "environment":
            env = tag.get("value")
        elif tag.get("tag") == "client":
            client = tag.get("value")
    return env, client

def create_sla_for_service(serviceid, env, client):

    sla_name = f"{client} - {env}"
    effective_date = int(time.time())
    sla_params = [
        {
            "name": sla_name,
            "slo": "99",
            "period": "0",
            "timezone": "Europe/Amsterdam",
            "description": "Uptime of client services",
            "effective_date": effective_date,
            "status": 1,
            "schedule": [
                {
                    "period_from": 0,
                    "period_to": 604800
                }
            ],
            "service_tags": [
                {
                    "tag": "client",
                    "operator": "0",
                    "value": client
                },
                {
                    "tag": "environment",
                    "operator": "0",
                    "value": env
                }
            ],
            "excluded_downtimes": []
        }
    ]
    params_payload = {
        "jsonrpc": "2.0",
        "method": "sla.create",
        "params": sla_params,
        "id": 1
    }
    result = call_api("sla.create", sla_params, req_id=1)
    if "result" in result:
        print(f"Created SLA for service {serviceid} with SLA name '{sla_name}'")
    else:
        print(f"Failed to create SLA for service {serviceid}: {result.get('error')}")

def main():
    client_services = get_client_services()
    if not client_services:
        print("No client services found for SLA creation.")
        return
    print("Found the following client services for SLA creation:")
    print(json.dumps(client_services, indent=2))
    for svc in client_services:
        serviceid = svc["serviceid"]
        env, client = get_service_identifiers(svc)
        if not env or not client:
            print(f"Skipping service {serviceid} due to missing environment or client tag.")
            continue
        create_sla_for_service(serviceid, env, client)

if __name__ == "__main__":
    main()
