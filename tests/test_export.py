import csv
import io
from datetime import date, timedelta

import pytest
from django.utils import timezone

from apps.alerts.export import export_filename, safe_text, to_csv, to_xlsx
from apps.alerts.reports import REPORT_COLUMNS, ReportRow, monday_of, weekly_report

WEEK = date(2026, 2, 2)


def make_row(**overrides) -> ReportRow:
    values = dict(
        group_by="field",
        key="7",
        label="Nowdapara plot 1 (Abdul Karim)",
        week_start=WEEK,
        week_end=date(2026, 2, 8),
        fields=1,
        area_ha=1.0,
        readings=7,
        avg_level_cm=-9.3,
        min_level_cm=-16.0,
        field_days_below_threshold=2,
        irrigation_events=2,
        irrigation_per_field=2.0,
        estimated_water_saving_pct=14.2,
        visits=1,
        alerts_opened=1,
        alerts_open_now=1,
        field_ids=[7],
    )
    values.update(overrides)
    return ReportRow(**values)


def read_csv(data: bytes) -> list[list[str]]:
    assert data.startswith(b"\xef\xbb\xbf")  # BOM so Excel picks UTF-8
    return list(csv.reader(io.StringIO(data.decode("utf-8-sig"))))


def test_csv_has_headers_and_one_line_per_row():
    rows = read_csv(to_csv([make_row(), make_row(key="8", field_ids=[8, 9], avg_level_cm=None)]))
    assert rows[0] == [header for _, header in REPORT_COLUMNS]
    assert len(rows) == 3
    first = dict(zip(rows[0], rows[1], strict=True))
    assert first["Week start"] == "2026-02-02"
    assert first["Average level (cm)"] == "-9.3"  # numbers are not escaped
    assert first["Minimum level (cm)"] == "-16.0"
    second = dict(zip(rows[0], rows[2], strict=True))
    assert second["Average level (cm)"] == ""
    assert second["Field IDs"] == "8,9"


def test_csv_keeps_bangla_text():
    rows = read_csv(to_csv([make_row(label="নওদাপাড়া প্লট ১ (আব্দুল করিম)")]))
    assert rows[1][2] == "নওদাপাড়া প্লট ১ (আব্দুল করিম)"


def test_csv_neutralises_formula_injection():
    rows = read_csv(to_csv([make_row(label='=HYPERLINK("http://x","click")', key="+1")]))
    assert rows[1][1] == "'+1"
    assert rows[1][2].startswith("'=HYPERLINK")


def test_safe_text_leaves_plain_text_alone():
    assert safe_text("Paba") == "Paba"
    assert safe_text("@cmd") == "'@cmd"
    assert safe_text("-2+3") == "'-2+3"


def test_export_filename():
    assert export_filename(WEEK, "upazila", "csv") == "awd-weekly-report-2026-02-02-by-upazila.csv"


def load_xlsx(data: bytes):
    from openpyxl import load_workbook

    return load_workbook(io.BytesIO(data))


def test_xlsx_table_is_typed_and_navigable():
    rows = [make_row(), make_row(key="8", label="Khanpur plot 1 (Rafiqul Islam)", field_ids=[8, 9])]
    book = load_xlsx(to_xlsx(rows, WEEK, "field", filters={"upazila": "Paba", "union": ""}))
    assert book.sheetnames == ["Weekly report", "Notes"]
    sheet = book["Weekly report"]
    assert [c.value for c in sheet[1]] == [header for _, header in REPORT_COLUMNS]
    assert sheet[1][0].font.bold
    assert sheet.max_row == 3
    assert sheet.freeze_panes == "A2"
    assert sheet.auto_filter.ref == "A1:R3"
    headers = [c.value for c in sheet[1]]
    first = {h: c for h, c in zip(headers, sheet[2], strict=True)}
    assert first["Week start"].value.date() == WEEK and first["Week start"].number_format == "yyyy-mm-dd"
    assert first["Average level (cm)"].value == -9.3 and first["Average level (cm)"].number_format == "0.0"
    assert first["Readings"].value == 7
    assert sheet.cell(3, headers.index("Field IDs") + 1).value == "8,9"

    notes = {row[0].value: row[1].value for row in book["Notes"].iter_rows()}
    assert notes["Week"] == "2026-02-02 to 2026-02-08"
    assert notes["Grouped by"] == "field"
    assert notes["Filter: upazila"] == "Paba"
    assert "Filter: union" not in notes  # empty filters are left out
    assert notes["Rows"] == 2


def test_xlsx_keeps_formula_like_text_as_text():
    label = '=HYPERLINK("http://x","click")'
    book = load_xlsx(to_xlsx([make_row(label=label)], WEEK, "field", filters={"upazila": "=1+1"}))
    cell = book["Weekly report"]["C2"]
    assert cell.value == label and cell.data_type == "s"
    notes = {row[0].value: row[1] for row in book["Notes"].iter_rows()}
    assert notes["Filter: upazila"].value == "=1+1" and notes["Filter: upazila"].data_type == "s"


def test_xlsx_with_no_rows_still_has_headers():
    sheet = load_xlsx(to_xlsx([], WEEK, "upazila"))["Weekly report"]
    assert sheet.max_row == 1 and sheet.auto_filter.ref == "A1:R1"


def test_xlsx_drops_control_characters():
    sheet = load_xlsx(to_xlsx([make_row(label="plot\x07 1")], WEEK, "field"))["Weekly report"]
    assert sheet["C2"].value == "plot 1"


# -- REST download endpoint -----------------------------------------------------------------------

XLSX_TYPE = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"


@pytest.mark.django_db
def test_export_requires_auth(client):
    assert client.get("/api/v1/reports/weekly.csv").status_code in (401, 403)


@pytest.mark.django_db
def test_csv_download_matches_weekly_report(client, auth_headers, two_upazilas):
    week_start, field, other = two_upazilas
    response = client.get(
        "/api/v1/reports/weekly.csv",
        {"week_start": week_start.isoformat(), "group_by": "upazila"},
        **auth_headers,
    )
    assert response.status_code == 200
    assert response["Content-Type"] == "text/csv; charset=utf-8"
    assert response["Content-Disposition"] == (
        f'attachment; filename="awd-weekly-report-{week_start.isoformat()}-by-upazila.csv"'
    )
    assert response["Cache-Control"] == "no-store"
    rows = read_csv(response.content)
    by_key = {line[1]: dict(zip(rows[0], line, strict=True)) for line in rows[1:]}
    assert set(by_key) == {"Paba", "Sherpur"}
    expected = {r.key: r for r in weekly_report(week_start, group_by="upazila")}
    assert by_key["Paba"]["Readings"] == str(expected["Paba"].readings) == "7"
    assert by_key["Paba"]["Irrigation events"] == "2"
    assert by_key["Sherpur"]["Visits"] == "1"


@pytest.mark.django_db
def test_xlsx_download_with_filters(client, auth_headers, two_upazilas):
    week_start, field, other = two_upazilas
    response = client.get(
        "/api/v1/reports/weekly.xlsx",
        {"week_start": week_start.isoformat(), "group_by": "field", "upazila": "sherpur"},
        **auth_headers,
    )
    assert response.status_code == 200
    assert response["Content-Type"] == XLSX_TYPE
    book = load_xlsx(response.content)
    sheet = book["Weekly report"]
    assert sheet.max_row == 2 and sheet["B2"].value == str(other.id)
    notes = {row[0].value: row[1].value for row in book["Notes"].iter_rows()}
    assert notes["Filter: upazila"] == "sherpur"


@pytest.mark.django_db
def test_export_defaults_to_last_full_week(client, auth_headers, field):
    response = client.get("/api/v1/reports/weekly.csv", **auth_headers)
    assert response.status_code == 200
    last_monday = monday_of(timezone.localdate() - timedelta(days=7))
    assert f"report-{last_monday.isoformat()}-by-field.csv" in response["Content-Disposition"]
    assert len(read_csv(response.content)) == 2  # header + the one active field


@pytest.mark.django_db
@pytest.mark.parametrize(
    ("path", "params", "status", "error_key"),
    [
        ("/api/v1/reports/weekly.pdf", {}, 404, "detail"),
        ("/api/v1/reports/weekly.csv", {"group_by": "district"}, 400, "group_by"),
        ("/api/v1/reports/weekly.csv", {"week_start": "02/02/2026"}, 400, "week_start"),
        ("/api/v1/reports/weekly.xlsx", {"upazila": "x" * 101}, 400, "upazila"),
    ],
)
def test_export_rejects_bad_requests(client, auth_headers, path, params, status, error_key):
    response = client.get(path, params, **auth_headers)
    assert response.status_code == status
    assert error_key in response.json()
