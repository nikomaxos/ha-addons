mysql -h core-mariadb -u homeassistant -pRene1122 homeassistant -e "
SELECT id, DATE(FROM_UNIXTIME(start_ts)) as day, start_ts, state, min, max, mean
FROM statistics
WHERE metadata_id = 556
  AND start_ts > 1790197200
ORDER BY start_ts ASC LIMIT 10;
"
