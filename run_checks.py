"""Run the whole pipeline locally with DuckDB (no internet or BigQuery needed).

Steps:
  1. Load the CSVs into DuckDB tables named like the BigQuery ones.
  2. Run sql/01 to sql/04 in order.
  3. Print a plain-English data-quality summary.
  4. Write output/data_quality_report.xlsx and output/report_for_sheets.csv.

Usage:  python run_checks.py
"""

import re
from pathlib import Path

import duckdb
import pandas as pd

ROOT = Path(__file__).parent
DATA_DIR = ROOT / "data"
SQL_DIR = ROOT / "sql"
OUTPUT_DIR = ROOT / "output"

BOOKING_COLUMNS = {
    "booking_id": "VARCHAR", "booking_date": "DATE", "visit_date": "DATE",
    "time_slot": "VARCHAR", "ticket_type": "VARCHAR", "adults": "INTEGER",
    "children": "INTEGER", "amount_aed": "DOUBLE", "channel": "VARCHAR",
    "customer_id": "VARCHAR",
}
TABLES = {
    "raw_bookings": ("bookings.csv", BOOKING_COLUMNS),
    "raw_waivers": ("waivers.csv", {
        "waiver_id": "VARCHAR", "booking_id": "VARCHAR",
        "signed_at": "TIMESTAMP", "signed": "VARCHAR"}),
    "raw_feedback": ("feedback.csv", {
        "feedback_id": "VARCHAR", "booking_id": "VARCHAR",
        "submitted_at": "TIMESTAMP", "rating": "INTEGER", "category": "VARCHAR"}),
    "raw_daily_loads": ("daily_loads/*.csv", {
        "export_id": "VARCHAR", "export_date": "DATE", **BOOKING_COLUMNS}),
}

# Plain-English sentence for each quality check (n = rows returned)
CHECK_SENTENCES = {
    "duplicate_bookings": "{n} bookings appeared more than once (duplicate rows)",
    "bookings_without_signed_waiver": "{n} bookings had no signed waiver",
    "visit_before_booking": "{n} bookings had a visit date before the booking date",
    "non_positive_amounts": "{n} bookings had a zero or negative amount",
    "child_ticket_without_children": "{n} child tickets had 0 children",
    "feedback_for_unknown_booking": "{n} feedback responses were for bookings that don't exist",
    "rating_out_of_range": "{n} feedback ratings were outside 1-5",
}


def connect(data_dir=DATA_DIR):
    """Create an in-memory DuckDB database with the raw tables loaded."""
    con = duckdb.connect()
    con.execute("CREATE SCHEMA playful_minds")
    # BigQuery has GENERATE_DATE_ARRAY built in; DuckDB needs it defined
    con.execute("""
        CREATE MACRO GENERATE_DATE_ARRAY(start_day, end_day) AS
        list_transform(generate_series(start_day, end_day, INTERVAL 1 DAY), d -> CAST(d AS DATE))
    """)
    for table, (file_name, columns) in TABLES.items():
        path = (Path(data_dir) / file_name).as_posix()
        con.execute(
            f"CREATE TABLE playful_minds.{table} AS "
            f"SELECT * FROM read_csv(?, header = true, columns = {columns})",
            [path],
        )
    return con


def adapt_for_duckdb(sql):
    """The only dialect difference: DuckDB names an UNNEST column as t(column)."""
    return re.sub(r"(UNNEST\(GENERATE_DATE_ARRAY\(.*?\)\)) AS (\w+)", r"\1 AS t(\2)",
                  sql, flags=re.DOTALL)


def read_queries(sql_file):
    """Split a .sql file into (name, sql) pairs using the '-- name:' markers."""
    queries = []
    for chunk in Path(sql_file).read_text(encoding="utf-8").split(";"):
        name = re.search(r"--\s*name:\s*(\w+)", chunk)
        code = "\n".join(line for line in chunk.splitlines()
                         if not line.strip().startswith("--")).strip()
        if name and code:
            queries.append((name.group(1), code))
    return queries


def run_sql_file(con, sql_file, replace=None):
    """Run every query in a file. Returns {name: DataFrame} for SELECT queries.

    replace: optional {old_text: new_text} applied first (used by tests to
    point the checks at the clean tables).
    """
    results = {}
    for name, sql in read_queries(sql_file):
        for old, new in (replace or {}).items():
            sql = sql.replace(old, new)
        sql = adapt_for_duckdb(sql)
        if sql.upper().startswith(("SELECT", "WITH")):
            results[name] = con.sql(sql).df()
        else:
            con.execute(sql)
    return results


def tidy(df):
    """Show whole-number columns as 21 instead of 21.0."""
    for column in df.select_dtypes("float").columns:
        values = df[column].dropna()
        if (values == values.round()).all():
            df[column] = df[column].astype("Int64")
    return df


def run_pipeline(con):
    """Run all four SQL files and collect what's needed for the summary."""
    load = run_sql_file(con, SQL_DIR / "01_load_checks.sql")
    quality = run_sql_file(con, SQL_DIR / "02_data_quality_checks.sql")
    run_sql_file(con, SQL_DIR / "03_clean_tables.sql")
    run_sql_file(con, SQL_DIR / "04_reports.sql")
    reports = {
        name: tidy(con.sql(f"SELECT * FROM playful_minds.{name} ORDER BY 1").df())
        for name in ["rpt_daily_summary", "rpt_visitors_per_day", "rpt_busiest_time_slots",
                     "rpt_revenue_by_ticket_and_channel", "rpt_waiver_completion",
                     "rpt_rating_by_category"]
    }
    return load, quality, reports


def table_counts(con):
    rows = []
    for name in ["bookings", "waivers", "feedback"]:
        raw = con.sql(f"SELECT COUNT(*) FROM playful_minds.raw_{name}").fetchone()[0]
        clean = con.sql(f"SELECT COUNT(*) FROM playful_minds.clean_{name}").fetchone()[0]
        rows.append({"table": name, "raw_rows": raw, "clean_rows": clean, "rows_removed": raw - clean})
    return pd.DataFrame(rows)


def build_summary(load, quality, counts, reports):
    """Turn the query results into short plain-English sentences."""
    lines = ["LOAD CHECKS"]
    days = load["rows_per_day"]
    lines.append(f"Received exports for {len(days)} days ({days['rows_received'].sum()} rows in total)")
    for day in load["missing_days"]["export_date"]:
        lines.append(f"No export arrived for {day:%Y-%m-%d}")
    for row in load["days_loaded_twice"].itertuples():
        lines.append(f"{row.export_date:%Y-%m-%d} was loaded {row.files_received} times "
                     f"({row.rows_received} rows instead of {row.rows_received // row.files_received})")

    lines.append("")
    lines.append("DATA QUALITY CHECKS")
    for name, template in CHECK_SENTENCES.items():
        lines.append(template.format(n=len(quality[name])))
        if name == "bookings_without_signed_waiver":
            kinds = quality[name]["issue"].value_counts()
            lines.append(f"   ({kinds.get('No waiver on file', 0)} had no waiver on file, "
                         f"{kinds.get('Waiver not signed', 0)} had a waiver marked not signed)")

    lines.append("")
    lines.append("CLEAN TABLES")
    for row in counts.itertuples():
        lines.append(f"{row.table}: {row.raw_rows} raw rows -> {row.clean_rows} clean rows "
                     f"({row.rows_removed} removed)")

    lines.append("")
    lines.append("HEADLINES (from clean data only)")
    daily = reports["rpt_daily_summary"]
    lines.append(f"Total visitors: {int(daily['total_visitors'].sum()):,} | "
                 f"Revenue: AED {daily['revenue_aed'].sum():,.0f}")
    overall = reports["rpt_waiver_completion"].set_index("channel").loc["ALL CHANNELS"]
    lines.append(f"Waiver completion rate: {overall['completion_rate_pct']}%")
    slots = reports["rpt_busiest_time_slots"].sort_values("total_visitors", ascending=False)
    lines.append(f"Busiest time slot: {slots.iloc[0]['time_slot']}")
    ratings = reports["rpt_rating_by_category"].sort_values("avg_rating")
    lines.append(f"Lowest-rated area: {ratings.iloc[0]['category']} ({ratings.iloc[0]['avg_rating']} / 5); "
                 f"highest: {ratings.iloc[-1]['category']} ({ratings.iloc[-1]['avg_rating']} / 5)")
    return lines


def write_outputs(summary, load, quality, counts, reports, output_dir=OUTPUT_DIR):
    output_dir.mkdir(exist_ok=True)
    xlsx_path = output_dir / "data_quality_report.xlsx"
    with pd.ExcelWriter(xlsx_path, engine="openpyxl") as writer:
        pd.DataFrame({"Data quality summary (SYNTHETIC data)": summary}).to_excel(
            writer, sheet_name="Summary", index=False)
        counts.to_excel(writer, sheet_name="Clean table counts", index=False)
        for name, df in {**load, **quality}.items():
            df.to_excel(writer, sheet_name=name[:31], index=False)
        reports["rpt_daily_summary"].to_excel(writer, sheet_name="Daily summary", index=False)
        for sheet in writer.sheets.values():
            for column in sheet.columns:
                width = max(len(str(cell.value or "")) for cell in column)
                sheet.column_dimensions[column[0].column_letter].width = min(width + 2, 80)

    csv_path = output_dir / "report_for_sheets.csv"
    reports["rpt_daily_summary"].to_csv(csv_path, index=False)
    return xlsx_path, csv_path


def main():
    con = connect()
    load, quality, reports = run_pipeline(con)
    counts = table_counts(con)
    summary = build_summary(load, quality, counts, reports)

    print("=" * 64)
    print("Playful Minds Museum - data quality summary (SYNTHETIC data)")
    print("=" * 64)
    print("\n".join(summary))

    xlsx_path, csv_path = write_outputs(summary, load, quality, counts, reports)
    print()
    print(f"Wrote {xlsx_path.relative_to(ROOT)}")
    print(f"Wrote {csv_path.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
