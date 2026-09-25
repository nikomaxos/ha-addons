mysql -h core-mariadb -u homeassistant -pRene1122 homeassistant -e "
SELECT id, DATE(FROM_UNIXTIME(start_ts)) as day, start_ts, state, sum
FROM statistics
WHERE metadata_id = 552
  AND start_ts >= 1790197200
ORDER BY start_ts ASC LIMIT 5;
"
