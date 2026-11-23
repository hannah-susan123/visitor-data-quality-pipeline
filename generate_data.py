"""Create SYNTHETIC booking, waiver and feedback data for the fictional
Playful Minds Museum (Dubai), with known errors mixed in on purpose.

Every error added is written to data/injected_errors.csv so the checks
can be tested against a known answer.

Usage:  python generate_data.py
"""

import random
from datetime import date, datetime, time, timedelta
from pathlib import Path

import pandas as pd

SEED = 42
START_DATE = date(2026, 9, 1)
NUM_DAYS = 60

# Daily-load problems (one of each)
MISSING_LOAD_DAY = date(2026, 9, 17)   # export never arrived
DOUBLE_LOAD_DAY = date(2026, 10, 8)    # export arrived twice
PARTIAL_LOAD_DAY = date(2026, 10, 21)  # export cut off part-way

# How many of each row-level error to add
ERROR_COUNTS = {
    "duplicate_booking": 15,
    "waiver_not_signed": 30,
    "waiver_missing": 12,
    "visit_before_booking": 10,
    "non_positive_amount": 12,
    "child_ticket_no_children": 9,
    "feedback_unknown_booking": 14,
    "rating_out_of_range": 11,
}

TIME_SLOTS = ["09:00", "10:30", "12:00", "13:30", "15:00", "16:30"]
SLOT_WEIGHTS = [10, 25, 20, 15, 20, 10]
CHANNELS = ["website", "walk-in", "partner"]
CHANNEL_WEIGHTS = [60, 25, 15]
TICKET_TYPES = ["child", "adult", "family pack", "annual pass"]
TICKET_WEIGHTS = [45, 10, 35, 10]
CHILD_PRICE, ADULT_PRICE = 95, 60
FAMILY_PACK_PRICE, ANNUAL_PASS_PRICE = 299, 1200

FEEDBACK_CATEGORIES = ["exhibits", "staff", "cleanliness", "cafe", "price"]
# Each category leans towards different scores so the report has a story
RATING_WEIGHTS = {
    "exhibits":    [1, 2, 8, 35, 54],
    "staff":       [1, 2, 6, 30, 61],
    "cleanliness": [2, 4, 14, 40, 40],
    "cafe":        [6, 12, 30, 32, 20],
    "price":       [10, 18, 32, 26, 14],
}


def make_party(ticket_type):
    """Return (adults, children, amount_aed) for a ticket type."""
    if ticket_type == "child":
        children, adults = random.randint(1, 3), random.randint(1, 2)
        return adults, children, children * CHILD_PRICE + adults * ADULT_PRICE
    if ticket_type == "adult":
        adults = random.randint(1, 2)
        return adults, 0, adults * ADULT_PRICE
    if ticket_type == "family pack":
        return 2, random.randint(2, 3), FAMILY_PACK_PRICE
    return random.randint(1, 2), random.randint(1, 3), ANNUAL_PASS_PRICE


def random_time(day, start_hour=8, end_hour=21):
    minutes = random.randint(start_hour * 60, end_hour * 60 - 1)
    return datetime.combine(day, time(minutes // 60, minutes % 60))


def make_bookings():
    rows = []
    for offset in range(NUM_DAYS):
        day = START_DATE + timedelta(days=offset)
        is_weekend = day.weekday() >= 5  # Sat/Sun in the UAE
        for _ in range(random.randint(36, 46) if is_weekend else random.randint(22, 30)):
            channel = random.choices(CHANNELS, CHANNEL_WEIGHTS)[0]
            ticket = random.choices(TICKET_TYPES, TICKET_WEIGHTS)[0]
            adults, children, amount = make_party(ticket)
            lead_days = 0 if channel == "walk-in" else random.randint(0, 7)
            rows.append({
                "booking_date": day,
                "visit_date": day + timedelta(days=lead_days),
                "time_slot": random.choices(TIME_SLOTS, SLOT_WEIGHTS)[0],
                "ticket_type": ticket,
                "adults": adults,
                "children": children,
                "amount_aed": amount,
                "channel": channel,
                "customer_id": f"CUST-{random.randint(1, 1400):05d}",
            })
    for i, row in enumerate(rows, start=1):
        row["booking_id"] = f"BK-{i:06d}"
    columns = ["booking_id", "booking_date", "visit_date", "time_slot", "ticket_type",
               "adults", "children", "amount_aed", "channel", "customer_id"]
    return pd.DataFrame(rows)[columns]


def make_waivers(bookings):
    rows = []
    for i, b in enumerate(bookings.itertuples(), start=1):
        # Signed some time between booking and the start of the visit day
        span = max((b.visit_date - b.booking_date).days, 0)
        sign_day = b.booking_date + timedelta(days=random.randint(0, span))
        signed_at = random_time(sign_day, 7, 9) if sign_day == b.visit_date else random_time(sign_day)
        rows.append({"waiver_id": f"WV-{i:06d}", "booking_id": b.booking_id,
                     "signed_at": signed_at, "signed": "yes"})
    return pd.DataFrame(rows)


def make_feedback(bookings):
    rows = []
    for b in bookings.sample(frac=0.35, random_state=SEED).itertuples():
        category = random.choice(FEEDBACK_CATEGORIES)
        rows.append({
            "booking_id": b.booking_id,
            "submitted_at": random_time(b.visit_date + timedelta(days=random.randint(0, 2))),
            "rating": random.choices([1, 2, 3, 4, 5], RATING_WEIGHTS[category])[0],
            "category": category,
        })
    feedback = pd.DataFrame(rows).sort_values("submitted_at").reset_index(drop=True)
    feedback.insert(0, "feedback_id", [f"FB-{i:06d}" for i in range(1, len(feedback) + 1)])
    return feedback


def inject_errors(bookings, waivers, feedback):
    """Add known errors and return the changed tables plus a log of what was done."""
    log = []

    def note(error_type, table, record_id, detail):
        log.append({"error_type": error_type, "table": table,
                    "record_id": record_id, "detail": detail})

    # Keep load-problem days free of row errors so each problem stays separate
    load_days = {MISSING_LOAD_DAY, DOUBLE_LOAD_DAY, PARTIAL_LOAD_DAY}
    candidates = bookings[~bookings["booking_date"].isin(load_days)]
    # Each error gets its own bookings so no row has two problems
    needed = sum(ERROR_COUNTS[k] for k in ERROR_COUNTS if k not in
                 ("child_ticket_no_children", "feedback_unknown_booking", "rating_out_of_range"))
    pool = candidates[candidates["ticket_type"] != "child"].sample(n=needed, random_state=1)
    pool_ids = list(pool["booking_id"])
    child_ids = list(candidates[candidates["ticket_type"] == "child"]
                     .sample(n=ERROR_COUNTS["child_ticket_no_children"], random_state=2)["booking_id"])

    def take(n):
        picked = pool_ids[:n]
        del pool_ids[:n]
        return picked

    # 1. Duplicate bookings: the same row exported twice
    dup_ids = take(ERROR_COUNTS["duplicate_booking"])
    for booking_id in dup_ids:
        note("duplicate_booking", "bookings", booking_id, "row appears twice")
    bookings = pd.concat([bookings, bookings[bookings["booking_id"].isin(dup_ids)]])

    # 2. No signed waiver: either marked 'no' or missing altogether
    for booking_id in take(ERROR_COUNTS["waiver_not_signed"]):
        mask = waivers["booking_id"] == booking_id
        waivers.loc[mask, "signed"] = "no"
        waivers.loc[mask, "signed_at"] = pd.NaT
        note("no_signed_waiver", "waivers", booking_id, "waiver marked signed = no")
    missing_ids = take(ERROR_COUNTS["waiver_missing"])
    waivers = waivers[~waivers["booking_id"].isin(missing_ids)]
    for booking_id in missing_ids:
        note("no_signed_waiver", "waivers", booking_id, "no waiver row at all")

    # 3. Visit date before booking date
    for booking_id in take(ERROR_COUNTS["visit_before_booking"]):
        mask = bookings["booking_id"] == booking_id
        days_back = random.randint(1, 5)
        bookings.loc[mask, "visit_date"] = bookings.loc[mask, "booking_date"] - timedelta(days=days_back)
        note("visit_before_booking", "bookings", booking_id, f"visit_date moved {days_back} day(s) before booking_date")

    # 4. Zero or negative amounts
    for booking_id in take(ERROR_COUNTS["non_positive_amount"]):
        mask = bookings["booking_id"] == booking_id
        new_amount = random.choice([0, -bookings.loc[mask, "amount_aed"].iloc[0]])
        bookings.loc[mask, "amount_aed"] = new_amount
        note("non_positive_amount", "bookings", booking_id, f"amount_aed set to {new_amount}")

    # 5. Child ticket with zero children
    for booking_id in child_ids:
        bookings.loc[bookings["booking_id"] == booking_id, "children"] = 0
        note("child_ticket_no_children", "bookings", booking_id, "children set to 0 on a child ticket")

    # 6. Feedback pointing at bookings that don't exist
    next_id = len(feedback) + 1
    fake_rows = []
    for i in range(ERROR_COUNTS["feedback_unknown_booking"]):
        feedback_id = f"FB-{next_id + i:06d}"
        fake_booking = f"BK-{900000 + random.randint(1, 99999):06d}"
        day = START_DATE + timedelta(days=random.randint(0, NUM_DAYS - 1))
        fake_rows.append({"feedback_id": feedback_id, "booking_id": fake_booking,
                          "submitted_at": random_time(day), "rating": random.randint(1, 5),
                          "category": random.choice(FEEDBACK_CATEGORIES)})
        note("feedback_unknown_booking", "feedback", feedback_id, f"booking_id {fake_booking} does not exist")
    feedback = pd.concat([feedback, pd.DataFrame(fake_rows)], ignore_index=True)

    # 7. Ratings outside 1-5 (only on feedback with a real booking)
    real = feedback[~feedback["feedback_id"].isin([r["feedback_id"] for r in fake_rows])]
    for feedback_id in real.sample(n=ERROR_COUNTS["rating_out_of_range"], random_state=3)["feedback_id"]:
        bad_rating = random.choice([0, 6, 7, 10, -1])
        feedback.loc[feedback["feedback_id"] == feedback_id, "rating"] = bad_rating
        note("rating_out_of_range", "feedback", feedback_id, f"rating set to {bad_rating}")

    bookings = bookings.sort_values(["booking_date", "booking_id"]).reset_index(drop=True)
    return bookings, waivers.reset_index(drop=True), feedback, log


def write_daily_loads(bookings, folder, log):
    """Split bookings into one export file per booking day, with load problems added."""
    folder.mkdir(parents=True, exist_ok=True)
    for old_file in folder.glob("*.csv"):
        old_file.unlink()

    for day, day_rows in bookings.groupby("booking_date"):
        if day == MISSING_LOAD_DAY:
            continue
        if day == PARTIAL_LOAD_DAY:
            day_rows = day_rows.head(len(day_rows) * 3 // 10)
        copies = 2 if day == DOUBLE_LOAD_DAY else 1
        for copy in range(1, copies + 1):
            export = day_rows.copy()
            export.insert(0, "export_date", day)
            export.insert(0, "export_id", f"EXP-{day:%Y%m%d}-{copy}")
            suffix = "" if copy == 1 else "_rerun"
            export.to_csv(folder / f"bookings_{day}{suffix}.csv", index=False)

    log.append({"error_type": "missing_daily_load", "table": "daily_loads",
                "record_id": str(MISSING_LOAD_DAY), "detail": "no export file for this day"})
    log.append({"error_type": "duplicate_daily_load", "table": "daily_loads",
                "record_id": str(DOUBLE_LOAD_DAY), "detail": "export file loaded twice (second copy named _rerun)"})
    log.append({"error_type": "partial_daily_load", "table": "daily_loads",
                "record_id": str(PARTIAL_LOAD_DAY), "detail": "export cut off at 30% of the day's rows"})


def generate(data_dir="data", seed=SEED):
    """Build all CSVs in data_dir. Returns the injected-errors log as a DataFrame."""
    random.seed(seed)
    data_dir = Path(data_dir)
    data_dir.mkdir(parents=True, exist_ok=True)

    bookings = make_bookings()
    waivers = make_waivers(bookings)
    feedback = make_feedback(bookings)
    bookings, waivers, feedback, log = inject_errors(bookings, waivers, feedback)

    bookings.to_csv(data_dir / "bookings.csv", index=False)
    waivers.to_csv(data_dir / "waivers.csv", index=False, date_format="%Y-%m-%d %H:%M:%S")
    feedback.to_csv(data_dir / "feedback.csv", index=False, date_format="%Y-%m-%d %H:%M:%S")
    write_daily_loads(bookings, data_dir / "daily_loads", log)

    errors = pd.DataFrame(log)
    errors.to_csv(data_dir / "injected_errors.csv", index=False)
    return errors


if __name__ == "__main__":
    errors = generate()
    print("SYNTHETIC data written to data/ (fictional Playful Minds Museum)")
    print("Errors injected on purpose:")
    print(errors["error_type"].value_counts().to_string())
