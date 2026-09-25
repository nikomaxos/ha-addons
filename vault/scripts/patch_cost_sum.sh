mysql -h core-mariadb -u homeassistant -pRene1122 homeassistant -e "
-- Add 0.222 to sum and state for cost sensors from Sep 22 10:00 onwards
UPDATE statistics SET sum = sum + 0.222, state = state + 0.222 WHERE metadata_id IN (556, 557, 558, 559) AND start_ts >= 1790060400;
UPDATE statistics_short_term SET sum = sum + 0.222, state = state + 0.222 WHERE metadata_id IN (556, 557, 558, 559) AND start_ts >= 1790060400;
"
