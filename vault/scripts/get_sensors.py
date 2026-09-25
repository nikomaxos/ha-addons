import urllib.request
import json
import os

env_path = '.env'
env_vars = {}
with open(env_path) as f:
    for line in f:
        if '=' in line:
            key, val = line.strip().split('=', 1)
            env_vars[key] = val.strip('"')

url = f'{env_vars["HA_URL"]}/api/states'
headers = {
    'Authorization': f'Bearer {env_vars["HA_TOKEN"]}',
    'Content-Type': 'application/json'
}

req = urllib.request.Request(url, headers=headers)
try:
    with urllib.request.urlopen(req) as response:
        data = json.loads(response.read().decode())
        print(f'Total entities: {len(data)}')
        
        print('\n--- Relevant Entities ---')
        keywords = ['kuga', 'price', 'cost', 'charge', 'kwh', 'energy', 'heating', 'gas', 'boiler', 'time']
        for entity in data:
            ent_id = entity['entity_id'].lower()
            friendly_name = entity.get('attributes', {}).get('friendly_name', '').lower()
            
            if any(k in ent_id or k in friendly_name for k in keywords):
                print(f"{entity['entity_id']} = {entity['state']}")
                print(f"  Attributes: {json.dumps(entity.get('attributes', {}), ensure_ascii=False)}")
                
except Exception as e:
    print(f'API Error: {e}')
