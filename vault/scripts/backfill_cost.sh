mysql -h core-mariadb -u homeassistant -pRene1122 homeassistant -e "
-- Daily
UPDATE statistics s1 JOIN statistics s2 ON s1.start_ts = s2.start_ts 
SET s1.sum = s2.sum * 0.194, s1.state = s2.state * 0.194 
WHERE s1.metadata_id = 556 AND s2.metadata_id = 552;

UPDATE statistics_short_term s1 JOIN statistics_short_term s2 ON s1.start_ts = s2.start_ts 
SET s1.sum = s2.sum * 0.194, s1.state = s2.state * 0.194 
WHERE s1.metadata_id = 556 AND s2.metadata_id = 552;

-- Weekly
UPDATE statistics s1 JOIN statistics s2 ON s1.start_ts = s2.start_ts 
SET s1.sum = s2.sum * 0.194, s1.state = s2.state * 0.194 
WHERE s1.metadata_id = 557 AND s2.metadata_id = 553;

UPDATE statistics_short_term s1 JOIN statistics_short_term s2 ON s1.start_ts = s2.start_ts 
SET s1.sum = s2.sum * 0.194, s1.state = s2.state * 0.194 
WHERE s1.metadata_id = 557 AND s2.metadata_id = 553;

-- Monthly
UPDATE statistics s1 JOIN statistics s2 ON s1.start_ts = s2.start_ts 
SET s1.sum = s2.sum * 0.194, s1.state = s2.state * 0.194 
WHERE s1.metadata_id = 558 AND s2.metadata_id = 554;

UPDATE statistics_short_term s1 JOIN statistics_short_term s2 ON s1.start_ts = s2.start_ts 
SET s1.sum = s2.sum * 0.194, s1.state = s2.state * 0.194 
WHERE s1.metadata_id = 558 AND s2.metadata_id = 554;

-- Yearly
UPDATE statistics s1 JOIN statistics s2 ON s1.start_ts = s2.start_ts 
SET s1.sum = s2.sum * 0.194, s1.state = s2.state * 0.194 
WHERE s1.metadata_id = 559 AND s2.metadata_id = 555;

UPDATE statistics_short_term s1 JOIN statistics_short_term s2 ON s1.start_ts = s2.start_ts 
SET s1.sum = s2.sum * 0.194, s1.state = s2.state * 0.194 
WHERE s1.metadata_id = 559 AND s2.metadata_id = 555;
"
