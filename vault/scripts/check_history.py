import urllib.request
import json
import datetime

env_path = '.env'
env_vars = {}
with open(env_path) as f:
    for line in f:
        if '=' in line:
            key, val = line.strip().split('=', 1)
            env_vars[key] = val.strip('"')

# Fetch start of today
now = datetime.datetime.now()
start_of_today = now.replace(hour=0, minute=0, second=0, microsecond=0).isoformat()
url = f'{env_vars["HA_URL"]}/api/history/period/{start_of_today}?filter_entity_id=sensor.kuga_kwh_calculation_left_filtered'
headers = {
    'Authorization': f'Bearer {env_vars["HA_TOKEN"]}',
    'Content-Type': 'application/json'
}

try:
    req = urllib.request.Request(url, headers=headers)
    with urllib.request.urlopen(req) as response:
        data = json.loads(response.read().decode())
        if data and len(data) > 0 and len(data[0]) > 0:
            first_val = float(data[0][0]['state'])
            last_val = float(data[0][-1]['state'])
            print(f"Start of today: {first_val}")
            print(f"Current: {last_val}")
            print(f"Consumed today: {last_val - first_val}")
        else:
            print("No history found")
except Exception as e:
    print(f"Error: {e}")
