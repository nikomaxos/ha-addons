import urllib.request
import json
import time

env_path = '.env'
env_vars = {}
with open(env_path) as f:
    for line in f:
        if '=' in line:
            key, val = line.strip().split('=', 1)
            env_vars[key] = val.strip('"')

def calibrate(entity_id, value):
    url = f'{env_vars["HA_URL"]}/api/services/utility_meter/calibrate'
    headers = {
        'Authorization': f'Bearer {env_vars["HA_TOKEN"]}',
        'Content-Type': 'application/json'
    }
    payload = json.dumps({"entity_id": entity_id, "value": str(value)}).encode('utf-8')
    try:
        req = urllib.request.Request(url, data=payload, headers=headers)
        with urllib.request.urlopen(req) as response:
            print(f"Calibrated {entity_id} to {value}: {response.status}")
    except Exception as e:
        print(f"Error calibrating {entity_id}: {e}")

calibrate('sensor.kuga_energy_weekly', 6.338)
calibrate('sensor.kuga_energy_monthly', 6.338)
calibrate('sensor.kuga_energy_yearly', 364.688)

def restart_ha():
    url = f'{env_vars["HA_URL"]}/api/services/homeassistant/restart'
    headers = {
        'Authorization': f'Bearer {env_vars["HA_TOKEN"]}',
        'Content-Type': 'application/json'
    }
    try:
        req = urllib.request.Request(url, data=b"{}", headers=headers)
        with urllib.request.urlopen(req) as response:
            print(f"Restarting HA: {response.status}")
    except Exception as e:
        print(f"Error restarting HA: {e}")

# Save the states gracefully
restart_ha()
