"""Prove the checks catch every error that was injected, and nothing else,
and that the clean tables are free of the problems they should remove.

Fresh data is created in a temporary folder, so these tests never
depend on (or change) the files in data/.
"""

import pytest

import generate_data
import monitor_loads
import run_checks

# Injected error type -> the SQL check in 02_data_quality_checks.sql that must find it
ROW_CHECKS = {
    "duplicate_booking": "duplicate_bookings",
    "no_signed_waiver": "bookings_without_signed_waiver",
    "visit_before_booking": "visit_before_booking",
    "non_positive_amount": "non_positive_amounts",
    "child_ticket_no_children": "child_ticket_without_children",
    "feedback_unknown_booking": "feedback_for_unknown_booking",
    "rating_out_of_range": "rating_out_of_range",
}
LOAD_ERRORS = {"missing_daily_load", "duplicate_daily_load", "partial_daily_load"}


@pytest.fixture(scope="session")
def run(tmp_path_factory):
    data_dir = tmp_path_factory.mktemp("data")
    errors = generate_data.generate(data_dir)
    con = run_checks.connect(data_dir)
    load, quality, reports = run_checks.run_pipeline(con)
    return {"data_dir": data_dir, "errors": errors, "con": con,
            "load": load, "quality": quality, "reports": reports}


def injected(run, error_type):
    errors = run["errors"]
    return set(errors.loc[errors["error_type"] == error_type, "record_id"])


def test_every_injected_error_type_is_tested(run):
    assert set(run["errors"]["error_type"]) == set(ROW_CHECKS) | LOAD_ERRORS


@pytest.mark.parametrize("error_type, check", ROW_CHECKS.items())
def test_check_finds_exactly_the_injected_rows(run, error_type, check):
    flagged = set(run["quality"][check]["record_id"])
    expected = injected(run, error_type)
    assert expected, f"no {error_type} errors were injected"
    assert flagged == expected  # nothing missed, no false alarms


def test_sql_finds_missing_day(run):
    found = {str(d.date()) for d in run["load"]["missing_days"]["export_date"]}
    assert found == injected(run, "missing_daily_load")


def test_sql_finds_day_loaded_twice(run):
    found = {str(d.date()) for d in run["load"]["days_loaded_twice"]["export_date"]}
    assert found == injected(run, "duplicate_daily_load")


def test_monitor_finds_all_load_problems(run):
    result = monitor_loads.check_folder(run["data_dir"] / "daily_loads")
    assert {str(d) for d in result["missing"]} == injected(run, "missing_daily_load")
    assert {str(d) for d in result["duplicates"]} == injected(run, "duplicate_daily_load")
    assert {str(d) for d in result["low"]} == injected(run, "partial_daily_load")
    assert result["high"] == {}


def test_clean_tables_pass_the_same_checks(run):
    # Re-run every quality check, pointed at the clean tables instead of raw
    on_clean = run_checks.run_sql_file(
        run["con"], run_checks.SQL_DIR / "02_data_quality_checks.sql",
        replace={"raw_": "clean_"})
    for check, rows in on_clean.items():
        if check == "bookings_without_signed_waiver":
            continue  # kept on purpose, tested below
        assert rows.empty, f"{check} still finds {len(rows)} rows in the clean tables"


def test_clean_bookings_have_no_flagged_ids(run):
    con = run["con"]
    ids = con.sql("SELECT booking_id FROM playful_minds.clean_bookings").df()["booking_id"]
    assert ids.is_unique
    for error_type in ["visit_before_booking", "non_positive_amount", "child_ticket_no_children"]:
        assert not injected(run, error_type) & set(ids)
    # Duplicates are fixed, not dropped: one copy of each remains
    assert injected(run, "duplicate_booking") <= set(ids)


def test_clean_feedback_has_no_flagged_ids(run):
    ids = set(run["con"].sql("SELECT feedback_id FROM playful_minds.clean_feedback").df()["feedback_id"])
    assert not injected(run, "feedback_unknown_booking") & ids
    assert not injected(run, "rating_out_of_range") & ids


def test_missing_waivers_are_kept_and_reported(run):
    con = run["con"]
    clean_ids = set(con.sql("SELECT booking_id FROM playful_minds.clean_bookings").df()["booking_id"])
    assert injected(run, "no_signed_waiver") <= clean_ids
    overall = run["reports"]["rpt_waiver_completion"].set_index("channel").loc["ALL CHANNELS"]
    assert overall["bookings"] - overall["signed_waivers"] == len(injected(run, "no_signed_waiver"))


def test_report_totals_match_clean_bookings(run):
    total = run["con"].sql("SELECT SUM(amount_aed) FROM playful_minds.clean_bookings").fetchone()[0]
    assert run["reports"]["rpt_daily_summary"]["revenue_aed"].sum() == pytest.approx(total)
    assert run["reports"]["rpt_revenue_by_ticket_and_channel"]["revenue_aed"].sum() == pytest.approx(total)
