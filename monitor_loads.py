"""Check the daily export folder before the data is used.

Reports, in plain English:
  - days with no export file
  - days with more than one export file
  - days whose row count is unusually low or high
    (less than half, or more than double, the typical day)

Exit code is 1 if any problem is found, so a scheduler can raise an alert.

Usage:  python monitor_loads.py [folder]
"""

import re
import sys
from datetime import date, timedelta
from pathlib import Path
from statistics import median

LOW_RATIO = 0.5   # below half a typical day
HIGH_RATIO = 2.0  # above double a typical day
FILE_PATTERN = re.compile(r"bookings_(\d{4}-\d{2}-\d{2})")


def count_rows(path):
    with open(path, encoding="utf-8") as f:
        return sum(1 for _ in f) - 1  # minus the header


def check_folder(folder="data/daily_loads"):
    """Return a dict describing every load problem found in the folder."""
    files_by_day = {}
    for path in sorted(Path(folder).glob("*.csv")):
        match = FILE_PATTERN.match(path.name)
        if match:
            day = date.fromisoformat(match.group(1))
            files_by_day.setdefault(day, []).append(path)

    if not files_by_day:
        return {"days_found": 0, "missing": [], "duplicates": {}, "low": {}, "high": {}, "typical": 0}

    first, last = min(files_by_day), max(files_by_day)
    all_days = [first + timedelta(days=i) for i in range((last - first).days + 1)]

    # Use the first file per day so a duplicate doesn't skew the counts
    rows_by_day = {day: count_rows(paths[0]) for day, paths in files_by_day.items()}
    typical = median(rows_by_day.values())

    return {
        "days_found": len(files_by_day),
        "first_day": first,
        "last_day": last,
        "typical": typical,
        "missing": [d for d in all_days if d not in files_by_day],
        "duplicates": {d: [p.name for p in paths] for d, paths in files_by_day.items() if len(paths) > 1},
        "low": {d: n for d, n in rows_by_day.items() if n < typical * LOW_RATIO},
        "high": {d: n for d, n in rows_by_day.items() if n > typical * HIGH_RATIO},
    }


def describe(result):
    """Plain-English lines for a check_folder result."""
    if result["days_found"] == 0:
        return ["No export files found."]
    lines = [f"Checked {result['days_found']} days of exports "
             f"({result['first_day']} to {result['last_day']}). "
             f"A typical day has {result['typical']:.0f} bookings."]
    for day in result["missing"]:
        lines.append(f"MISSING: no export file for {day}.")
    for day, names in result["duplicates"].items():
        lines.append(f"DUPLICATE: {day} has {len(names)} files ({', '.join(names)}). Keep only one.")
    for day, n in result["low"].items():
        lines.append(f"LOW: {day} has only {n} rows (typical is {result['typical']:.0f}). The export may be incomplete.")
    for day, n in result["high"].items():
        lines.append(f"HIGH: {day} has {n} rows (typical is {result['typical']:.0f}). Check for repeated rows.")
    if len(lines) == 1:
        lines.append("All daily loads look normal.")
    return lines


def main():
    folder = sys.argv[1] if len(sys.argv) > 1 else "data/daily_loads"
    result = check_folder(folder)
    print("\n".join(describe(result)))
    problems = result["missing"] or result["duplicates"] or result["low"] or result["high"]
    sys.exit(1 if problems else 0)


if __name__ == "__main__":
    main()
