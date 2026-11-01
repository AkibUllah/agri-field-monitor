"""Weekly report as downloadable files (CSV / XLSX) for programme reporting."""

from __future__ import annotations

import csv
import io
from collections.abc import Sequence
from datetime import date

from apps.alerts.reports import REPORT_COLUMNS, ReportRow

# Spreadsheet apps execute cells that start with these characters as formulas. Farmer and field
# names are user input, so text cells are prefixed with an apostrophe (OWASP "CSV injection").
_FORMULA_PREFIXES = ("=", "+", "-", "@", "\t", "\r")


def safe_text(value: str) -> str:
    return "'" + value if value.startswith(_FORMULA_PREFIXES) else value


def _cell(row: ReportRow, name: str):
    value = getattr(row, name)
    if name == "field_ids":
        return ",".join(str(i) for i in value)
    return value


def export_filename(week_start: date, group_by: str, extension: str) -> str:
    return f"awd-weekly-report-{week_start.isoformat()}-by-{group_by}.{extension}"


def to_csv(rows: Sequence[ReportRow]) -> bytes:
    """UTF-8 CSV with a BOM, so Excel shows Bangla names correctly when the file is double-clicked."""
    buffer = io.StringIO()
    writer = csv.writer(buffer, lineterminator="\r\n")
    writer.writerow([header for _, header in REPORT_COLUMNS])
    for row in rows:
        values = []
        for name, _ in REPORT_COLUMNS:
            value = _cell(row, name)
            if value is None:
                values.append("")
            elif isinstance(value, str):
                values.append(safe_text(value))
            elif isinstance(value, date):
                values.append(value.isoformat())
            else:
                values.append(value)
        writer.writerow(values)
    return buffer.getvalue().encode("utf-8-sig")
