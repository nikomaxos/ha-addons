mysql -h core-mariadb -u homeassistant -pRene1122 homeassistant -e "
-- Fix negative mins for daily cost (556)
UPDATE statistics SET min = 0.399 WHERE metadata_id = 556 AND start_ts = 1790179200 AND min < 0;
UPDATE statistics_short_term SET min = 0.399 WHERE metadata_id = 556 AND start_ts = 1790179200 AND min < 0;

-- Fix max for 1790197200 (Sep 24 00:00) which belongs to Sep 23
UPDATE statistics SET max = 0.912 WHERE metadata_id = 556 AND start_ts = 1790197200 AND max > 200;
UPDATE statistics_short_term SET max = 0.912 WHERE metadata_id = 556 AND start_ts = 1790197200 AND max > 200;

-- Fix negative mins for weekly, monthly, yearly cost (557, 558, 559)
UPDATE statistics SET min = 0.716 WHERE metadata_id IN (557, 558, 559) AND start_ts = 1790179200 AND min < 0;
UPDATE statistics_short_term SET min = 0.716 WHERE metadata_id IN (557, 558, 559) AND start_ts = 1790179200 AND min < 0;

"
