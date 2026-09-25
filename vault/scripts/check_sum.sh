mysql -h core-mariadb -u homeassistant -pRene1122 homeassistant -e "
-- Check a few rows of 556 to see if sum is NULL
SELECT id, start_ts, state, sum FROM statistics WHERE metadata_id = 556 ORDER BY start_ts DESC LIMIT 5;
"
