from datetime import timedelta

import pytest
from django.utils import timezone

from apps.alerts.models import Alert
from apps.alerts.reports import monday_of, week_bounds, weekly_report
from apps.farms.models import Farmer, Field
from apps.monitoring.models import FieldVisit, IrrigationEvent, Pipe
from tests.conftest import SQUARE_100M, add_readings


def test_week_helpers():
    monday = monday_of(timezone.localdate())
    assert monday.weekday() == 0
    start, end = week_bounds(monday)
    assert (end - start).days == 7
    assert timezone.localtime(start).hour == 0


@pytest.fixture
def two_upazilas(farmer, field, pipe, user):
    other_farmer = Farmer.objects.create(
        name="Rafiqul Islam", phone="01811000102", village="Khanpur", union_name="Khanpur",
        upazila="Sherpur", district="Bogura",
    )  # fmt: skip
    other = Field.objects.create(farmer=other_farmer, name="Khanpur plot 1", polygon=SQUARE_100M)
    other_pipe = Pipe.objects.create(field=other, code="SHE-002-A", installed_on=timezone.localdate())
    week_start = monday_of(timezone.localdate() - timedelta(days=7))
    end = week_bounds(week_start)[1] - timedelta(hours=12)  # last day of that week, 12:00
    add_readings(pipe, [-4, -8, -12, -15, -16, -3, -7], end=end)  # 2 field-days below -15
    add_readings(other_pipe, [-2, -5, -9], end=end)
    for days_ago in (1, 4):
        IrrigationEvent.objects.create(field=field, started_at=end - timedelta(days=days_ago), logged_by=user)
    IrrigationEvent.objects.create(
        field=field, started_at=end - timedelta(days=2), method=IrrigationEvent.Method.RAIN
    )
    FieldVisit.objects.create(field=other, visitor=user, visited_at=end - timedelta(days=3))
    Alert.objects.create(
        field=field, kind=Alert.Kind.IRRIGATION_DUE, message="x", triggered_at=end - timedelta(days=2)
    )
    return week_start, field, other


@pytest.mark.django_db
def test_weekly_report_by_field(two_upazilas):
    week_start, field, other = two_upazilas
    rows = {r.key: r for r in weekly_report(week_start, group_by="field")}
    mine = rows[str(field.id)]
    assert mine.label.startswith("Nowdapara plot 1")
    assert mine.readings == 7
    assert mine.avg_level_cm == pytest.approx(-9.3, abs=0.05)
    assert mine.min_level_cm == -16.0
    assert mine.field_days_below_threshold == 2
    assert mine.irrigation_events == 2  # rainfall record excluded
    assert mine.irrigation_per_field == 2.0
    assert mine.estimated_water_saving_pct == pytest.approx(14.2, abs=0.2)
    assert mine.alerts_opened == 1 and mine.alerts_open_now == 1
    theirs = rows[str(other.id)]
    assert theirs.readings == 3 and theirs.irrigation_events == 0 and theirs.visits == 1
    assert theirs.estimated_water_saving_pct == 100.0


@pytest.mark.django_db
def test_weekly_report_by_upazila_and_filters(two_upazilas):
    week_start, field, other = two_upazilas
    rows = {r.key: r for r in weekly_report(week_start, group_by="upazila")}
    assert set(rows) == {"Paba", "Sherpur"}
    assert rows["Paba"].fields == 1 and rows["Paba"].area_ha == pytest.approx(1.0, abs=0.01)
    assert rows["Paba"].field_ids == [field.id]
    assert weekly_report(week_start, group_by="union", upazila="Sherpur")[0].key == "Khanpur"
    assert weekly_report(week_start, group_by="upazila", union_name="Nowhere") == []
    assert weekly_report(week_start - timedelta(days=70), group_by="upazila")[0].readings == 0
    with pytest.raises(ValueError):
        weekly_report(week_start, group_by="district")


@pytest.mark.django_db
def test_weekly_report_defaults_to_last_full_week(field):
    rows = weekly_report()
    assert len(rows) == 1
    assert rows[0].week_start == monday_of(timezone.localdate() - timedelta(days=7))
    assert rows[0].avg_level_cm is None and rows[0].readings == 0
