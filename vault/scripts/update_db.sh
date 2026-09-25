mysql -h core-mariadb -u homeassistant -pRene1122 homeassistant -e "
-- Fix daily cost max
UPDATE statistics SET max = 0.317, min = 0.317, mean = 0.317 WHERE metadata_id = 556 AND DATE(FROM_UNIXTIME(start_ts)) = '2026-09-22' AND max > 0;
-- Fix daily energy state/sum/max
UPDATE statistics SET max = 1.634, state = 1.634, sum = 1.634 WHERE metadata_id = 552 AND DATE(FROM_UNIXTIME(start_ts)) = '2026-09-22' AND max > 0;

-- Fix short term stats just in case
UPDATE statistics_short_term SET max = 0.317, min = 0.317, mean = 0.317 WHERE metadata_id = 556 AND DATE(FROM_UNIXTIME(start_ts)) = '2026-09-22' AND max > 0;
UPDATE statistics_short_term SET max = 1.634, state = 1.634, sum = 1.634 WHERE metadata_id = 552 AND DATE(FROM_UNIXTIME(start_ts)) = '2026-09-22' AND max > 0;
"
