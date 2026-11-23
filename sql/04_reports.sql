-- 04_reports.sql
-- Purpose: report views for Google Sheets and Looker Studio.
-- Views always show the latest clean data, so nothing needs
-- to be copied when the clean tables are rebuilt.
-- All reports read from the clean tables only.


-- name: rpt_visitors_per_day
CREATE OR REPLACE VIEW playful_minds.rpt_visitors_per_day AS
SELECT
  visit_date,
  COUNT(*) AS bookings,
  SUM(adults) AS adults,
  SUM(children) AS children,
  SUM(total_visitors) AS total_visitors,
  SUM(amount_aed) AS revenue_aed
FROM playful_minds.clean_bookings
GROUP BY visit_date;


-- name: rpt_busiest_time_slots
CREATE OR REPLACE VIEW playful_minds.rpt_busiest_time_slots AS
SELECT
  time_slot,
  COUNT(*) AS bookings,
  SUM(total_visitors) AS total_visitors,
  ROUND(SUM(total_visitors) / COUNT(DISTINCT visit_date), 1) AS avg_visitors_per_day
FROM playful_minds.clean_bookings
GROUP BY time_slot;


-- name: rpt_revenue_by_ticket_and_channel
CREATE OR REPLACE VIEW playful_minds.rpt_revenue_by_ticket_and_channel AS
SELECT
  ticket_type,
  channel,
  COUNT(*) AS bookings,
  SUM(amount_aed) AS revenue_aed,
  ROUND(AVG(amount_aed), 2) AS avg_booking_value_aed
FROM playful_minds.clean_bookings
GROUP BY ticket_type, channel;


-- name: rpt_waiver_completion
-- Share of bookings with a signed waiver, per channel and overall.
CREATE OR REPLACE VIEW playful_minds.rpt_waiver_completion AS
WITH booking_waivers AS (
  SELECT
    b.channel,
    CASE WHEN w.signed = 'yes' THEN 1 ELSE 0 END AS is_signed
  FROM playful_minds.clean_bookings AS b
  LEFT JOIN playful_minds.clean_waivers AS w
    ON b.booking_id = w.booking_id
)
SELECT
  channel,
  COUNT(*) AS bookings,
  SUM(is_signed) AS signed_waivers,
  ROUND(100 * SUM(is_signed) / COUNT(*), 1) AS completion_rate_pct
FROM booking_waivers
GROUP BY channel
UNION ALL
SELECT
  'ALL CHANNELS' AS channel,
  COUNT(*),
  SUM(is_signed),
  ROUND(100 * SUM(is_signed) / COUNT(*), 1)
FROM booking_waivers;


-- name: rpt_rating_by_category
CREATE OR REPLACE VIEW playful_minds.rpt_rating_by_category AS
SELECT
  category,
  COUNT(*) AS responses,
  ROUND(AVG(rating), 2) AS avg_rating,
  SUM(CASE WHEN rating <= 2 THEN 1 ELSE 0 END) AS low_ratings
FROM playful_minds.clean_feedback
GROUP BY category;


-- name: rpt_daily_summary
-- One row per visit day: the table exported to Google Sheets.
CREATE OR REPLACE VIEW playful_minds.rpt_daily_summary AS
WITH daily_bookings AS (
  SELECT
    b.visit_date,
    COUNT(*) AS bookings,
    SUM(b.total_visitors) AS total_visitors,
    SUM(b.amount_aed) AS revenue_aed,
    SUM(CASE WHEN w.signed = 'yes' THEN 1 ELSE 0 END) AS signed_waivers
  FROM playful_minds.clean_bookings AS b
  LEFT JOIN playful_minds.clean_waivers AS w
    ON b.booking_id = w.booking_id
  GROUP BY b.visit_date
),
daily_feedback AS (
  SELECT
    b.visit_date,
    COUNT(*) AS feedback_responses,
    ROUND(AVG(f.rating), 2) AS avg_rating
  FROM playful_minds.clean_feedback AS f
  JOIN playful_minds.clean_bookings AS b
    ON f.booking_id = b.booking_id
  GROUP BY b.visit_date
)
SELECT
  d.visit_date,
  d.bookings,
  d.total_visitors,
  d.revenue_aed,
  ROUND(100 * d.signed_waivers / d.bookings, 1) AS waiver_completion_pct,
  COALESCE(f.feedback_responses, 0) AS feedback_responses,
  f.avg_rating
FROM daily_bookings AS d
LEFT JOIN daily_feedback AS f
  ON d.visit_date = f.visit_date;
