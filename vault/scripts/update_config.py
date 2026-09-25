import json

path = '/config/.storage/core.config_entries'
with open(path, 'r', encoding='utf-8') as f:
    data = json.load(f)

changed = False
for entry in data['data']['entries']:
    if entry['domain'] == 'utility_meter' and ('Kuga energy ' in entry.get('title', '') or 'Ford Kuga Energy Daily' in entry.get('title', '')):
        if entry.get('options', {}).get('source') == 'sensor.ford_kuga_kwh_per_session':
            entry['options']['source'] = 'sensor.kuga_kwh_calculation_left_filtered'
            changed = True
            print(f"Updated {entry['title']}")

if changed:
    with open(path, 'w', encoding='utf-8') as f:
        # Home Assistant .storage files typically don't have indent=2, they are minimized or use specific indent, but indent=2 is safe and readable.
        json.dump(data, f, ensure_ascii=False)
    print('Changes saved successfully.')
else:
    print('No changes needed.')
