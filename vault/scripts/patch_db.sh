mysql -h core-mariadb -u homeassistant -pRene1122 homeassistant -e "
-- 1. Fix SUM for all energy utility meters (lifetime accumulator)
UPDATE statistics SET sum = sum - 1247.463 WHERE metadata_id IN (552, 553, 554, 555) AND start_ts >= 1790179200;
UPDATE statistics_short_term SET sum = sum - 1247.463 WHERE metadata_id IN (552, 553, 554, 555) AND start_ts >= 1790179200;

-- 2. Fix STATE for Daily Energy (resets at 1790197200)
UPDATE statistics SET state = state - 1247.463, min = min - 1247.463, max = max - 1247.463, mean = mean - 1247.463 
WHERE metadata_id = 552 AND start_ts >= 1790179200 AND start_ts < 1790197200;
UPDATE statistics_short_term SET state = state - 1247.463, min = min - 1247.463, max = max - 1247.463, mean = mean - 1247.463 
WHERE metadata_id = 552 AND start_ts >= 1790179200 AND start_ts < 1790197200;

-- 3. Fix STATE for Weekly, Monthly, Yearly Energy (haven't reset yet)
UPDATE statistics SET state = state - 1247.463, min = min - 1247.463, max = max - 1247.463, mean = mean - 1247.463 
WHERE metadata_id IN (553, 554, 555) AND start_ts >= 1790179200;
UPDATE statistics_short_term SET state = state - 1247.463, min = min - 1247.463, max = max - 1247.463, mean = mean - 1247.463 
WHERE metadata_id IN (553, 554, 555) AND start_ts >= 1790179200;

-- 4. Fix STATE for Daily Cost (resets at 1790197200)
UPDATE statistics SET state = state - 242.0078, min = min - 242.0078, max = max - 242.0078, mean = mean - 242.0078 
WHERE metadata_id = 556 AND start_ts >= 1790179200 AND start_ts < 1790197200;
UPDATE statistics_short_term SET state = state - 242.0078, min = min - 242.0078, max = max - 242.0078, mean = mean - 242.0078 
WHERE metadata_id = 556 AND start_ts >= 1790179200 AND start_ts < 1790197200;

-- 5. Fix STATE for Weekly, Monthly, Yearly Cost (haven't reset yet)
UPDATE statistics SET state = state - 242.0078, min = min - 242.0078, max = max - 242.0078, mean = mean - 242.0078 
WHERE metadata_id IN (557, 558, 559) AND start_ts >= 1790179200;
UPDATE statistics_short_term SET state = state - 242.0078, min = min - 242.0078, max = max - 242.0078, mean = mean - 242.0078 
WHERE metadata_id IN (557, 558, 559) AND start_ts >= 1790179200;
"
