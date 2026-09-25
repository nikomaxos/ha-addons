mysql -h core-mariadb -u homeassistant -pRene1122 homeassistant -e "
SELECT DATE(FROM_UNIXTIME(start_ts)) as day, MAX(sum) - MIN(sum) as change_sum
FROM statistics
WHERE metadata_id = 552
  AND start_ts >= UNIX_TIMESTAMP('2026-09-20 00:00:00')
GROUP BY day
ORDER BY day ASC;
"
