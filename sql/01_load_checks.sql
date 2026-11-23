-- 01_load_checks.sql
-- Purpose: check that the daily booking exports arrived properly
-- before trusting them. Reads playful_minds.raw_daily_loads, which
-- holds every daily export file stacked together.
-- Each export row carries export_id (which file) and export_date (which day).


-- name: rows_per_day
-- How many files and rows arrived for each day.
SELECT
  export_date,
  COUNT(DISTINCT export_id) AS files_received,
  COUNT(*) AS rows_received
FROM playful_minds.raw_daily_loads
GROUP BY export_date
ORDER BY export_date;


-- name: missing_days
-- Build a full calendar from the first to the last export day,
-- then keep the days that have no export at all.
WITH calendar AS (
  SELECT calendar_day
  FROM UNNEST(GENERATE_DATE_ARRAY(
    (SELECT MIN(export_date) FROM playful_minds.raw_daily_loads),
    (SELECT MAX(export_date) FROM playful_minds.raw_daily_loads)
  )) AS calendar_day
)
SELECT
  'Missing daily load' AS issue,
  c.calendar_day AS export_date
FROM calendar AS c
LEFT JOIN (SELECT DISTINCT export_date FROM playful_minds.raw_daily_loads) AS d
  ON c.calendar_day = d.export_date
WHERE d.export_date IS NULL
ORDER BY export_date;


-- name: days_loaded_twice
-- A day should arrive as exactly one export file.
SELECT
  'Day loaded more than once' AS issue,
  export_date,
  COUNT(DISTINCT export_id) AS files_received,
  COUNT(*) AS rows_received
FROM playful_minds.raw_daily_loads
GROUP BY export_date
HAVING COUNT(DISTINCT export_id) > 1
ORDER BY export_date;
