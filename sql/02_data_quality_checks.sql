-- 02_data_quality_checks.sql
-- Purpose: find bad rows before they reach any report.
-- One query per problem. Every query returns:
--   issue      plain-English label for the problem
--   record_id  the booking_id or feedback_id to look at
-- plus a few columns that help someone fix it.
-- An empty result means no problem of that type.


-- name: duplicate_bookings
-- The same booking_id should appear only once.
SELECT
  'Duplicate booking' AS issue,
  booking_id AS record_id,
  COUNT(*) AS times_found
FROM playful_minds.raw_bookings
GROUP BY booking_id
HAVING COUNT(*) > 1
ORDER BY record_id;


-- name: bookings_without_signed_waiver
-- Every booking needs a waiver marked 'yes'.
-- DISTINCT stops duplicate bookings being counted twice.
SELECT
  CASE WHEN w.booking_id IS NULL THEN 'No waiver on file'
       ELSE 'Waiver not signed' END AS issue,
  b.booking_id AS record_id,
  b.visit_date,
  b.channel
FROM (SELECT DISTINCT booking_id, visit_date, channel
      FROM playful_minds.raw_bookings) AS b
LEFT JOIN playful_minds.raw_waivers AS w
  ON b.booking_id = w.booking_id
WHERE w.booking_id IS NULL
   OR w.signed != 'yes'
ORDER BY record_id;


-- name: visit_before_booking
-- Nobody can visit before they booked.
SELECT
  'Visit date is before booking date' AS issue,
  booking_id AS record_id,
  booking_date,
  visit_date
FROM playful_minds.raw_bookings
WHERE visit_date < booking_date
ORDER BY record_id;


-- name: non_positive_amounts
-- Every booking should have been paid for.
SELECT
  'Amount is zero or negative' AS issue,
  booking_id AS record_id,
  ticket_type,
  amount_aed
FROM playful_minds.raw_bookings
WHERE amount_aed <= 0
ORDER BY record_id;


-- name: child_ticket_without_children
-- A child ticket must include at least one child.
SELECT
  'Child ticket with 0 children' AS issue,
  booking_id AS record_id,
  adults,
  children
FROM playful_minds.raw_bookings
WHERE ticket_type = 'child'
  AND children = 0
ORDER BY record_id;


-- name: feedback_for_unknown_booking
-- Feedback must belong to a booking we know about.
SELECT
  'Feedback for a booking that does not exist' AS issue,
  f.feedback_id AS record_id,
  f.booking_id,
  f.submitted_at
FROM playful_minds.raw_feedback AS f
LEFT JOIN (SELECT DISTINCT booking_id FROM playful_minds.raw_bookings) AS b
  ON f.booking_id = b.booking_id
WHERE b.booking_id IS NULL
ORDER BY record_id;


-- name: rating_out_of_range
-- Ratings must be whole numbers from 1 to 5.
SELECT
  'Rating outside 1-5' AS issue,
  feedback_id AS record_id,
  rating,
  category
FROM playful_minds.raw_feedback
WHERE rating NOT BETWEEN 1 AND 5
   OR rating IS NULL
ORDER BY record_id;
