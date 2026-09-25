import json

path = '/config/.storage/core.config_entries'
with open(path, 'r', encoding='utf-8') as f:
    data = json.load(f)

for entry in data['data']['entries']:
    if 'Heating Hours' in str(entry.get('title', '')):
        print(f"Title: {entry.get('title')}")
        print(f"Options: {entry.get('options')}")
        print("---")
