import csv
import io
from datetime import date

from apps.alerts.export import export_filename, safe_text, to_csv
from apps.alerts.reports import REPORT_COLUMNS, ReportRow

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
