import sqlite3
db_path = '/config/home-assistant_v2.db'
conn = sqlite3.connect(db_path)
conn.row_factory = sqlite3.Row
cursor = conn.cursor()

cursor.execute("SELECT id, statistic_id FROM statistics_meta WHERE statistic_id LIKE '%kuga%'")
for row in cursor.fetchall():
    print(f"{row['id']}: {row['statistic_id']}")
conn.close()
