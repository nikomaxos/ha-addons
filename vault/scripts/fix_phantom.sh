mysql -h core-mariadb -u homeassistant -pRene1122 homeassistant -e "
UPDATE statistics SET max = 0 WHERE metadata_id = 556 AND start_ts = 1790197200;
UPDATE statistics_short_term SET max = 0 WHERE metadata_id = 556 AND start_ts = 1790197200;
"
