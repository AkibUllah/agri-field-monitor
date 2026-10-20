from datetime import date, datetime, timedelta
from datetime import timezone as dt_tz
from decimal import Decimal

import pytest
from django.db import IntegrityError
from django.utils import timezone

from apps.alerts import awd
from apps.alerts.models import Alert
from apps.monitoring.models import IrrigationEvent
from tests.conftest import add_readings

UTC = dt_tz.utc


def ts(day: int, hour: int = 8) -> datetime:
    # Asia/Dhaka is UTC+6, so 08:00 local == 02:00 UTC.
    return datetime(2026, 1, day, hour - 6, tzinfo=UTC)


def test_daily_minimums_use_local_day_and_lowest_value():
    readings = [(ts(5, 7), Decimal("-3")), (ts(5, 17), Decimal("-6")), (ts(6, 8), Decimal("-9"))]
    mins = awd.daily_minimums(readings)
    assert mins == {date(2026, 1, 5): Decimal("-6"), date(2026, 1, 6): Decimal("-9")}
    # 23:30 local on Jan 5 is 17:30 UTC on Jan 5 -> still Jan 5 locally.
    assert awd.local_date(datetime(2026, 1, 5, 17, 30, tzinfo=UTC)) == date(2026, 1, 5)


def test_consecutive_days_below_counts_streak_and_tolerates_a_gap():
    daily = {
        date(2026, 1, 10): Decimal("-16"),
        date(2026, 1, 9): Decimal("-15"),
        # Jan 8 missing (skipped reading)
        date(2026, 1, 7): Decimal("-15.5"),
        date(2026, 1, 6): Decimal("-10"),  # breaks the streak
        date(2026, 1, 5): Decimal("-20"),
    }
    assert awd.consecutive_days_below(daily, -15, date(2026, 1, 10)) == 3
    assert awd.consecutive_days_below(daily, -15, date(2026, 1, 6)) == 0
    assert awd.consecutive_days_below(daily, -15, date(2026, 1, 5)) == 1
    assert awd.consecutive_days_below({}, -15, date(2026, 1, 10)) == 0
    # Two missing days in a row end the streak.
    sparse = {date(2026, 1, 10): Decimal("-16"), date(2026, 1, 7): Decimal("-16")}
    assert awd.consecutive_days_below(sparse, -15, date(2026, 1, 10)) == 1


def test_evaluate_field_irrigation_due_and_severity():
    as_of = ts(10, 12)
    readings = [(ts(d), Decimal("-16")) for d in range(7, 11)]  # 4 days at -16
    alerts = awd.evaluate_field(
        threshold_cm=-15, readings=readings, last_irrigation=None, has_active_pipes=True, as_of=as_of,
        days_required=2, silent_days=3, overflow_cm=10,
    )  # fmt: skip
    assert [a.kind for a in alerts] == [Alert.Kind.IRRIGATION_DUE]
    assert alerts[0].severity == Alert.Severity.CRITICAL  # 4 >= 2 + 2
    assert "4 days" in alerts[0].message

    two_days = [(ts(9), Decimal("-15")), (ts(10), Decimal("-15.5"))]
    alerts = awd.evaluate_field(
        threshold_cm=-15, readings=two_days, last_irrigation=None, has_active_pipes=True, as_of=as_of,
        days_required=2, silent_days=3, overflow_cm=10,
    )  # fmt: skip
    assert alerts[0].severity == Alert.Severity.WARNING

    one_day = [(ts(9), Decimal("-5")), (ts(10), Decimal("-15.5"))]
    assert awd.evaluate_field(
        threshold_cm=-15, readings=one_day, last_irrigation=None, has_active_pipes=True, as_of=as_of,
        days_required=2, silent_days=3, overflow_cm=10,
    ) == []  # fmt: skip


def test_evaluate_field_irrigation_resets_streak():
    as_of = ts(10, 12)
    readings = [(ts(d), Decimal("-16")) for d in range(6, 11)]
    alerts = awd.evaluate_field(
        threshold_cm=-15, readings=readings, last_irrigation=ts(9, 18), has_active_pipes=True, as_of=as_of,
        days_required=2, silent_days=3, overflow_cm=10,
    )  # fmt: skip
    assert alerts == []  # only the Jan 10 reading post-dates the irrigation


def test_evaluate_field_silent_and_overflow():
    as_of = ts(10, 12)
    silent = awd.evaluate_field(
        threshold_cm=-15, readings=[(ts(3), Decimal("-2"))], last_irrigation=None, has_active_pipes=True,
        as_of=as_of, days_required=2, silent_days=3, overflow_cm=10,
    )  # fmt: skip
    assert [a.kind for a in silent] == [Alert.Kind.SENSOR_SILENT]
    assert silent[0].severity == Alert.Severity.CRITICAL  # 7 days >= 2 x 3
    assert silent[0].value == 7

    none_ever = awd.evaluate_field(
        threshold_cm=-15, readings=[], last_irrigation=None, has_active_pipes=True, as_of=as_of
    )
    assert [a.kind for a in none_ever] == [Alert.Kind.SENSOR_SILENT]
    assert (
        awd.evaluate_field(
            threshold_cm=-15, readings=[], last_irrigation=None, has_active_pipes=False, as_of=as_of
        )
        == []
    )

    flooded = awd.evaluate_field(
        threshold_cm=-15, readings=[(ts(10), Decimal("14"))], last_irrigation=None, has_active_pipes=True,
        as_of=as_of, days_required=2, silent_days=3, overflow_cm=10,
    )  # fmt: skip
    assert [a.kind for a in flooded] == [Alert.Kind.OVERFLOW]
    assert flooded[0].severity == Alert.Severity.INFO


@pytest.mark.django_db
def test_run_awd_check_opens_keeps_and_resolves(field, pipe, user):
    add_readings(pipe, [-5, -10, -15.5, -16, -17])  # three days at/below -15
    result = awd.run_awd_check()
    assert (result.fields_checked, result.opened, result.resolved) == (1, 1, 0)
    alert = Alert.objects.get()
    assert alert.kind == Alert.Kind.IRRIGATION_DUE and alert.is_open

    again = awd.run_awd_check()
    assert (again.opened, again.unchanged, again.resolved) == (0, 1, 0)
    assert Alert.objects.count() == 1

    IrrigationEvent.objects.create(field=field, started_at=timezone.now(), logged_by=user)
    after = awd.run_awd_check(as_of=timezone.now() + timedelta(minutes=1))
    assert after.resolved == 1 and after.opened == 0
    alert.refresh_from_db()
    assert not alert.is_open and "cleared" in alert.resolution_note


@pytest.mark.django_db
def test_only_one_open_alert_per_field_and_kind(field, user):
    Alert.objects.create(field=field, kind=Alert.Kind.OVERFLOW, message="a")
    with pytest.raises(IntegrityError):
        Alert.objects.create(field=field, kind=Alert.Kind.OVERFLOW, message="b")


@pytest.mark.django_db
def test_resolved_alert_allows_new_one(field, user):
    first = Alert.objects.create(field=field, kind=Alert.Kind.OVERFLOW, message="a")
    first.resolve(user, note="pumped out")
    assert first.resolved_by == user and not first.is_open
    Alert.objects.create(field=field, kind=Alert.Kind.OVERFLOW, message="b")
    assert Alert.objects.filter(field=field).count() == 2
