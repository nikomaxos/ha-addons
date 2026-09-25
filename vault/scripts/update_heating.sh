mysql -h core-mariadb -u homeassistant -pRene1122 homeassistant -e "
-- Add 29.46 to all stats from March 14 onwards for Annual Heating Cost Total
UPDATE statistics SET state = state + 29.46, sum = sum + 29.46, min = min + 29.46, max = max + 29.46, mean = mean + 29.46 WHERE metadata_id = 730 AND start_ts >= UNIX_TIMESTAMP('2026-03-14 00:00:00');
UPDATE statistics_short_term SET state = state + 29.46, sum = sum + 29.46, min = min + 29.46, max = max + 29.46, mean = mean + 29.46 WHERE metadata_id = 730 AND start_ts >= UNIX_TIMESTAMP('2026-03-14 00:00:00');
"
