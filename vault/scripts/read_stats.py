import sqlite3
import datetime
import time

db_path = '/config/home-assistant_v2.db'
conn = sqlite3.connect(db_path)
conn.row_factory = sqlite3.Row
cursor = conn.cursor()

# Get metadata IDs
cursor.execute("SELECT id, statistic_id FROM statistics_meta WHERE statistic_id IN ('sensor.kuga_kwh_calculation_left_filtered', 'sensor.kuga_energy_cost_daily', 'sensor.kuga_energy_daily')")
meta = {row['statistic_id']: row['id'] for row in cursor.fetchall()}
print("Meta IDs:", meta)

# We want stats for the last 4 days
now = datetime.datetime.now()
days_to_check = 4

for i in range(days_to_check, -1, -1):
    day_start = (now - datetime.timedelta(days=i)).replace(hour=0, minute=0, second=0, microsecond=0)
    day_end = day_start + datetime.timedelta(days=1)
    
    ts_start = day_start.timestamp()
    ts_end = day_end.timestamp()
    
    print(f"\n--- {day_start.strftime('%Y-%m-%d')} ---")
    
    for stat_id, m_id in meta.items():
        # Get the max value in the statistics table for this day
        cursor.execute("SELECT MAX(max) as max_val, MAX(state) as max_state, MAX(sum) as max_sum FROM statistics WHERE metadata_id = ? AND start_ts >= ? AND start_ts < ?", (m_id, ts_start, ts_end))
        row = cursor.fetchone()
        print(f"{stat_id}: max={row['max_val']}, state={row['max_state']}, sum={row['max_sum']}")

conn.close()
