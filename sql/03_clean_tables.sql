-- 03_clean_tables.sql
-- Purpose: build the clean tables that reports read from.
-- Raw tables are never changed; clean copies are rebuilt each run.
--
-- What happens to each problem from 02_data_quality_checks.sql:
--   duplicate booking              -> FIXED: keep one copy
--   visit before booking           -> REMOVED: true date unknown
--   zero or negative amount        -> REMOVED: true amount unknown
--   child ticket with 0 children   -> REMOVED: true party size unknown
--   feedback for unknown booking   -> REMOVED
--   rating outside 1-5             -> REMOVED
--   no signed waiver               -> KEPT: the booking itself is real;
--                                     it is reported as a safety follow-up


-- name: clean_bookings
CREATE OR REPLACE TABLE playful_minds.clean_bookings AS
WITH numbered AS (
  -- Number each copy of a booking_id: 1, 2, ...
  SELECT
    *,
    ROW_NUMBER() OVER (PARTITION BY booking_id ORDER BY booking_date) AS copy_number
  FROM playful_minds.raw_bookings
)
SELECT
  booking_id,
  booking_date,
  visit_date,
  time_slot,
  ticket_type,
  adults,
  children,
  adults + children AS total_visitors,
  amount_aed,
  channel,
  customer_id
FROM numbered
WHERE copy_number = 1
  AND visit_date >= booking_date
  AND amount_aed > 0
  AND NOT (ticket_type = 'child' AND children = 0);


-- name: clean_waivers
-- One waiver per clean booking. Unsigned waivers stay so the
-- completion rate is honest.
CREATE OR REPLACE TABLE playful_minds.clean_waivers AS
SELECT
  w.waiver_id,
  w.booking_id,
  w.signed_at,
  w.signed
FROM playful_minds.raw_waivers AS w
JOIN playful_minds.clean_bookings AS b
  ON w.booking_id = b.booking_id;


-- name: clean_feedback
-- Only feedback that links to a clean booking and has a valid rating.
CREATE OR REPLACE TABLE playful_minds.clean_feedback AS
SELECT
  f.feedback_id,
  f.booking_id,
  f.submitted_at,
  f.rating,
  f.category
FROM playful_minds.raw_feedback AS f
JOIN playful_minds.clean_bookings AS b
  ON f.booking_id = b.booking_id
WHERE f.rating BETWEEN 1 AND 5;
