mysql -h core-mariadb -u homeassistant -pRene1122 homeassistant -e "
SELECT DATE(FROM_UNIXTIME(start_ts)) as day, MAX(state) as max_state
FROM statistics
WHERE metadata_id = 730
  AND start_ts >= UNIX_TIMESTAMP('2026-04-01 00:00:00')
  AND start_ts < UNIX_TIMESTAMP('2026-06-01 00:00:00')
GROUP BY day
ORDER BY day ASC;
"
