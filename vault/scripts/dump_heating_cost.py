import json

path = '/config/.storage/core.config_entries'
with open(path, 'r', encoding='utf-8') as f:
    data = json.load(f)

for entry in data['data']['entries']:
    if 'sensor.daily_heating_cost' in str(entry.get('options', '')):
        print(f"Title: {entry.get('title')}")
        print(f"Domain: {entry.get('domain')}")
        print(f"Options: {entry.get('options')}")
        print("---")
