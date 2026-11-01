"""Weekly report as downloadable files (CSV / XLSX) for programme reporting."""

from __future__ import annotations

import csv
import io
from collections.abc import Sequence
from datetime import date, datetime, timedelta

from django.utils import timezone

from apps.alerts.reports import CONTINUOUS_FLOODING_IRRIGATIONS_PER_WEEK, REPORT_COLUMNS, ReportRow

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


# Excel number formats per column; anything not listed keeps the "General" format.
_XLSX_FORMATS = {
    "week_start": "yyyy-mm-dd",
    "week_end": "yyyy-mm-dd",
    "area_ha": "0.000",
    "avg_level_cm": "0.0",
    "min_level_cm": "0.0",
    "irrigation_per_field": "0.00",
    "estimated_water_saving_pct": "0.0",
}


def to_xlsx(
    rows: Sequence[ReportRow],
    week_start: date,
    group_by: str,
    filters: dict[str, str] | None = None,
    generated_at: datetime | None = None,
) -> bytes:
    """Workbook with the report table (typed cells, frozen header, filter) and a notes sheet."""
    from openpyxl import Workbook
    from openpyxl.cell.cell import ILLEGAL_CHARACTERS_RE
    from openpyxl.styles import Font
    from openpyxl.utils import get_column_letter

    workbook = Workbook()
    sheet = workbook.active
    sheet.title = "Weekly report"
    sheet.append([header for _, header in REPORT_COLUMNS])
    for cell in sheet[1]:
        cell.font = Font(bold=True)

    for row in rows:
        values = [_cell(row, name) for name, _ in REPORT_COLUMNS]
        sheet.append([ILLEGAL_CHARACTERS_RE.sub("", v) if isinstance(v, str) else v for v in values])
        for (name, _), cell in zip(REPORT_COLUMNS, sheet[sheet.max_row], strict=True):
            if isinstance(cell.value, str):
                # openpyxl turns strings starting with "=" into formulas; keep user text as text.
                cell.data_type = "s"
            if name in _XLSX_FORMATS:
                cell.number_format = _XLSX_FORMATS[name]

    for index, (name, header) in enumerate(REPORT_COLUMNS, start=1):
        longest = max([len(header), *(len(str(getattr(r, name))) for r in rows)])
        sheet.column_dimensions[get_column_letter(index)].width = min(max(longest + 2, 10), 50)
    sheet.freeze_panes = "A2"
    sheet.auto_filter.ref = f"A1:{get_column_letter(len(REPORT_COLUMNS))}{max(sheet.max_row, 1)}"

    notes = workbook.create_sheet("Notes")
    generated_at = generated_at or timezone.now()
    for key, value in [
        ("Report", "AWD weekly progress"),
        ("Week", f"{week_start.isoformat()} to {(week_start + timedelta(days=6)).isoformat()}"),
        ("Grouped by", group_by),
        *((f"Filter: {k}", v) for k, v in (filters or {}).items() if v),
        ("Rows", len(rows)),
        ("Generated", timezone.localtime(generated_at).strftime("%Y-%m-%d %H:%M %Z")),
        (
            "Water saving estimate",
            "1 - irrigations per field / "
            f"{CONTINUOUS_FLOODING_IRRIGATIONS_PER_WEEK} (continuous flooding baseline per week)",
        ),
    ]:
        if isinstance(value, str):
            value = ILLEGAL_CHARACTERS_RE.sub("", value)
        notes.append([key, value])
        label, cell = notes[notes.max_row]
        label.font = Font(bold=True)
        if isinstance(value, str):
            cell.data_type = "s"  # filter values come from the request: never a formula
    notes.column_dimensions["A"].width = 24
    notes.column_dimensions["B"].width = 80

    buffer = io.BytesIO()
    workbook.save(buffer)
    return buffer.getvalue()
