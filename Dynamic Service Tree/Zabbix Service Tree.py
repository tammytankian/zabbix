import requests
import json
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

print("Using Headers for API calls:")
print(json.dumps(HEADERS, indent=2))


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
        print("Failed to parse response:", e)
        result = {}
    if "error" in result:
        print(f"Error calling {method}: {result['error']}")
    return result


def get_dynamic_records():
    """
    Retrieves hosts with their tags and extracts unique combinations for 
    (environment, version, client). Only hosts with all three tags are included.
    """
    params = {
        "output": ["hostid", "name"],
        "selectTags": "extend"
    }
    result = call_api("host.get", params, req_id=1)
    hosts = result.get("result", [])
    combinations = set()
    
    for host in hosts:
        tags = host.get("tags", [])
        env = ver = client = None
        for tag in tags:
            if tag.get("tag") == "environment":
                env = tag.get("value")
            elif tag.get("tag") == "version":
                ver = tag.get("value")
            elif tag.get("tag") == "client":
                client = tag.get("value")
        if env and ver and client:
            combinations.add((env, ver, client))
    
    records = [{"environment": e, "version": v, "client": c} for (e, v, c) in combinations]
    print("Dynamic records extracted from host tags:")
    print(json.dumps(records, indent=2))
    return records


def get_service(name, parentid=None):
    """
    Retrieves a service by its name.
    If parentid is provided, returns only the service whose 'parents' list includes that parent's serviceid.
    """
    params = {
        "output": ["serviceid", "name"],
        "selectParents": "extend",
        "filter": {"name": name}
    }
    result = call_api("service.get", params, req_id=2)
    services = result.get("result", [])
    if parentid is not None:
        # Filter services by checking their 'parents' list.
        for svc in services:
            parents = svc.get("parents", [])
            for p in parents:
                if str(p.get("serviceid")) == str(parentid):
                    return svc
        return None
    else:
        return services[0] if services else None


def get_or_create_service(name, parentid, tag_key, tag_value):
    """
    Retrieves or creates an environment- or version-level service.
    For these services, we add a single tag (either "environment" or "version").
    """
    service = get_service(name, parentid)
    if service:
        print(f"Service '{name}' already exists (serviceid: {service['serviceid']})")
        return service["serviceid"]

    params = {
        "name": name,
        "algorithm": 0,       # Simple weighted SLA calculation
        "sortorder": 0,       # Required parameter for ordering
        "tags": [{"tag": tag_key, "value": tag_value}]
    }
    if parentid is not None:
        params["parents"] = [{"serviceid": str(parentid)}]
    result = call_api("service.create", params, req_id=3)
    serviceids = result.get("result", {}).get("serviceids", [])
    if serviceids:
        new_id = serviceids[0]
        print(f"Created service '{name}' (serviceid: {new_id})")
        return new_id
    else:
        print(f"Failed to create service '{name}'")
        return None


def get_or_create_client_service(name, parentid, env, ver, client):
    """
    Retrieves or creates a client-level service.
    For client services, we now supply both:
      - Service tags: used for SLA definitions (here: environment and client)
      - Problem tags: used to match trigger events for SLA calculation (here: environment, version, client, sla:true)
    """
    service = get_service(name, parentid)
    if service:
        print(f"Client service '{name}' already exists (serviceid: {service['serviceid']})")
        return service["serviceid"]
    
    service_tags = [
        {"tag": "environment", "value": env},
        {"tag": "client", "value": client}
    ]
    problem_tags = [
        {"tag": "environment", "value": env},
        {"tag": "version", "value": ver},
        {"tag": "client", "value": client},
        {"tag": "sla", "value": "true"}
    ]
    params = {
        "name": name,
        "algorithm": 0,
        "sortorder": 0,
        "parents": [{"serviceid": str(parentid)}],
        "tags": service_tags,
        "problem_tags": problem_tags
    }
    result = call_api("service.create", params, req_id=4)
    serviceids = result.get("result", {}).get("serviceids", [])
    if serviceids:
        new_id = serviceids[0]
        print(f"Created client service '{name}' (serviceid: {new_id}) with service tags {service_tags} and problem_tags {problem_tags}")
        return new_id
    else:
        print(f"Failed to create client service '{name}'")
        return None


def update_service_tree(records):
    """
    Builds (or updates) the hierarchical service tree based on the tag records.
    Expected hierarchy:
      Environment (no parents)
        └── Version (child of Environment)
              └── Client (child of Version) with:
                  - Service tags: environment, client
                  - Problem tags: environment, version, client, sla:true
    Returns a nested dictionary with service IDs.
    """
    tree_ids = {}
    for rec in records:
        env = rec["environment"]
        ver = rec["version"]
        client = rec["client"]

        # Environment-level service (no parents)
        if env not in tree_ids:
            env_id = get_or_create_service(env, None, "environment", env)
            tree_ids[env] = {"serviceid": env_id, "versions": {}}
        else:
            env_id = tree_ids[env]["serviceid"]

        # Version-level service (child of environment)
        if ver not in tree_ids[env]["versions"]:
            ver_id = get_or_create_service(ver, env_id, "version", ver)
            tree_ids[env]["versions"][ver] = {"serviceid": ver_id, "clients": {}}
        else:
            ver_id = tree_ids[env]["versions"][ver]["serviceid"]

        # Client-level service (child of version) with both service and problem tags.
        if client not in tree_ids[env]["versions"][ver]["clients"]:
            client_id = get_or_create_client_service(client, ver_id, env, ver, client)
            tree_ids[env]["versions"][ver]["clients"][client] = client_id
        else:
            client_id = tree_ids[env]["versions"][ver]["clients"][client]

    return tree_ids


if __name__ == "__main__":
    records = get_dynamic_records()
    if records:
        tree = update_service_tree(records)
        print("Updated Service Tree (service IDs):")
        print(json.dumps(tree, indent=2))
    else:
        print("No valid host tag combinations found. Ensure hosts include 'environment', 'version', and 'client' tags.")
