mysql -h core-mariadb -u homeassistant -pRene1122 homeassistant -e "
SELECT id, DATE(FROM_UNIXTIME(start_ts)) as day, start_ts, state, sum, min, max, mean
FROM statistics
WHERE metadata_id = 556
  AND DATE(FROM_UNIXTIME(start_ts)) = '2026-09-23'
ORDER BY start_ts ASC;
"
