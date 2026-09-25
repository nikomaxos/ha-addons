import urllib.request

env_path = '.env'
env_vars = {}
with open(env_path) as f:
    for line in f:
        if '=' in line:
            key, val = line.strip().split('=', 1)
            env_vars[key] = val.strip('"')

url = f'{env_vars["HA_URL"]}/api/services/lovelace/reload'
headers = {
    'Authorization': f'Bearer {env_vars["HA_TOKEN"]}',
    'Content-Type': 'application/json'
}
try:
    req = urllib.request.Request(url, data=b"{}", headers=headers)
    with urllib.request.urlopen(req) as response:
        print(f"Reloading Lovelace: {response.status}")
except Exception as e:
    print(f"Error reloading Lovelace: {e}")
