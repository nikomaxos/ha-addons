mysql -h core-mariadb -u homeassistant -pRene1122 homeassistant -e "
SELECT id, start_ts, state, sum, min, max, mean
FROM statistics
WHERE metadata_id = 556
  AND start_ts >= UNIX_TIMESTAMP('2026-09-22 00:00:00')
  AND start_ts < UNIX_TIMESTAMP('2026-09-23 00:00:00')
ORDER BY start_ts ASC;
"
