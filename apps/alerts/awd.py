"""Alternate Wetting and Drying (AWD) rules.

Safe AWD: let the perched water table fall to ~15 cm below the soil surface
(the bottom of a 25 cm field tube), then re-flood to ~5 cm. The rules here turn
pipe readings and irrigation logs into alerts:

* ``IRRIGATION_DUE``  - the field's daily minimum level has been at or below its
  threshold for ``days_required`` consecutive days with no irrigation since.
* ``OVERFLOW``        - the latest reading is above ``overflow_cm`` (water wasted).
* ``SENSOR_SILENT``   - a field has active pipes but no reading for ``silent_days``.

The pure functions take plain data so they are easy to test; ``run_awd_check``
wires them to the ORM and opens/closes ``Alert`` rows idempotently.
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from decimal import Decimal

from django.conf import settings
from django.db import transaction
from django.utils import timezone

from apps.alerts.models import Alert
from apps.farms.models import Field
from apps.monitoring.models import IrrigationEvent, WaterLevelReading

LOCAL_TZ = timezone.get_default_timezone()


@dataclass(frozen=True)
class AlertCandidate:
    kind: str
    severity: str
    message: str
    value: Decimal | None = None


def local_date(dt: datetime) -> date:
    return timezone.localtime(dt, LOCAL_TZ).date()


def daily_minimums(readings: list[tuple[datetime, Decimal]]) -> dict[date, Decimal]:
    """Lowest level per local calendar day (the day's driest moment decides AWD state)."""
    mins: dict[date, Decimal] = {}
    for recorded_at, level in readings:
        day = local_date(recorded_at)
        if day not in mins or level < mins[day]:
            mins[day] = Decimal(level)
    return mins


def consecutive_days_below(
    daily: dict[date, Decimal],
    threshold: Decimal | int,
    as_of: date,
    max_gap_days: int = 1,
) -> int:
    """Count consecutive days ending at ``as_of`` whose minimum is <= ``threshold``.

    Missing days (nobody read the pipe) are tolerated up to ``max_gap_days`` in a
    row so a skipped Friday does not reset the streak, but they do not count.
    """
    threshold = Decimal(threshold)
    streak = 0
    gap = 0
    day = as_of
    while True:
        level = daily.get(day)
        if level is None:
            gap += 1
            if gap > max_gap_days or streak == 0 and gap > max_gap_days:
                break
        elif level <= threshold:
            streak += 1
            gap = 0
        else:
            break
        day -= timedelta(days=1)
        if (as_of - day).days > 60:
            break
    return streak


def evaluate_field(
    *,
    threshold_cm: int,
    readings: list[tuple[datetime, Decimal]],
    last_irrigation: datetime | None,
    has_active_pipes: bool,
    as_of: datetime,
    days_required: int | None = None,
    silent_days: int | None = None,
    overflow_cm: int | None = None,
) -> list[AlertCandidate]:
    """Pure evaluation of one field's state. Returns the alerts that should be open."""
    days_required = days_required or settings.AWD_DAYS_BELOW_THRESHOLD
    silent_days = silent_days or settings.SENSOR_SILENT_DAYS
    overflow_cm = overflow_cm if overflow_cm is not None else settings.OVERFLOW_LEVEL_CM
    out: list[AlertCandidate] = []

    if not readings:
        if has_active_pipes:
            out.append(
                AlertCandidate(
                    Alert.Kind.SENSOR_SILENT,
                    Alert.Severity.WARNING,
                    "No water level readings have ever been recorded for this field",
                )
            )
        return out

    readings = sorted(readings)
    latest_at, latest_level = readings[-1]
    if (as_of - latest_at) >= timedelta(days=silent_days):
        days = (as_of - latest_at).days
        out.append(
            AlertCandidate(
                Alert.Kind.SENSOR_SILENT,
                Alert.Severity.WARNING if days < silent_days * 2 else Alert.Severity.CRITICAL,
                f"No reading for {days} days (last {latest_level} cm)",
                Decimal(days),
            )
        )

    if latest_level > overflow_cm:
        out.append(
            AlertCandidate(
                Alert.Kind.OVERFLOW,
                Alert.Severity.INFO,
                f"Standing water at +{latest_level} cm exceeds {overflow_cm} cm; pumping is wasted",
                Decimal(latest_level),
            )
        )

    # Only readings after the last irrigation count toward the drying streak.
    relevant = [r for r in readings if last_irrigation is None or r[0] > last_irrigation]
    daily = daily_minimums(relevant)
    streak = consecutive_days_below(daily, threshold_cm, local_date(as_of))
    if streak >= days_required:
        severity = Alert.Severity.CRITICAL if streak >= days_required + 2 else Alert.Severity.WARNING
        out.append(
            AlertCandidate(
                Alert.Kind.IRRIGATION_DUE,
                severity,
                f"Water level at or below {threshold_cm} cm for {streak} days "
                f"(latest {latest_level} cm); irrigate to +5 cm",
                Decimal(latest_level),
            )
        )
    return out


@dataclass
class AwdCheckResult:
    fields_checked: int = 0
    opened: int = 0
    resolved: int = 0
    unchanged: int = 0


@transaction.atomic
def run_awd_check(as_of: datetime | None = None, lookback_days: int = 21) -> AwdCheckResult:
    """Evaluate every active field and reconcile its open alerts with the rules."""
    as_of = as_of or timezone.now()
    since = as_of - timedelta(days=lookback_days)
    result = AwdCheckResult()

    readings_by_field: dict[int, list[tuple[datetime, Decimal]]] = defaultdict(list)
    for field_id, recorded_at, level in WaterLevelReading.objects.filter(
        recorded_at__gte=since, recorded_at__lte=as_of, pipe__is_active=True
    ).values_list("pipe__field_id", "recorded_at", "level_cm"):
        readings_by_field[field_id].append((recorded_at, level))

    last_irrigation: dict[int, datetime] = {}
    for field_id, started_at in (
        IrrigationEvent.objects.filter(started_at__lte=as_of)
        .exclude(method=IrrigationEvent.Method.RAIN)
        .order_by("field_id", "-started_at")
        .values_list("field_id", "started_at")
    ):
        last_irrigation.setdefault(field_id, started_at)

    fields = Field.objects.filter(is_active=True).prefetch_related("pipes", "alerts")
    for field in fields:
        result.fields_checked += 1
        wanted = {
            c.kind: c
            for c in evaluate_field(
                threshold_cm=field.awd_threshold_cm,
                readings=readings_by_field.get(field.id, []),
                last_irrigation=last_irrigation.get(field.id),
                has_active_pipes=any(p.is_active for p in field.pipes.all()),
                as_of=as_of,
            )
        }
        open_alerts = {a.kind: a for a in field.alerts.all() if a.resolved_at is None}
        for kind, alert in open_alerts.items():
            if kind not in wanted:
                alert.resolved_at = as_of
                alert.resolution_note = "condition cleared by scheduled check"
                alert.save(update_fields=["resolved_at", "resolution_note"])
                result.resolved += 1
            else:
                result.unchanged += 1
        for kind, cand in wanted.items():
            if kind not in open_alerts:
                Alert.objects.create(
                    field=field,
                    kind=cand.kind,
                    severity=cand.severity,
                    message=cand.message,
                    value=cand.value,
                    triggered_at=as_of,
                )
                result.opened += 1
    return result
