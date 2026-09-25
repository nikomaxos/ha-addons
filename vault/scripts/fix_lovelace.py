import json

path = '/config/.storage/lovelace.lovelace'
with open(path, 'r', encoding='utf-8') as f:
    data = json.load(f)

changed = False
if 'data' in data and 'config' in data['data'] and 'views' in data['data']['config']:
    for view in data['data']['config']['views']:
        for card in view.get('cards', []):
            if card.get('type') == 'statistics-graph' and 'sensor.kuga_energy_cost_daily' in card.get('entities', []):
                if 'mean' in card.get('stat_types', []):
                    card['stat_types'] = ['max']
                    changed = True
                    print("Updated card!")

if changed:
    with open(path, 'w', encoding='utf-8') as f:
        json.dump(data, f, ensure_ascii=False)
    print("Saved lovelace configuration.")
else:
    print("No changes made.")
