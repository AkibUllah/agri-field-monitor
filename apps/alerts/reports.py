"""Weekly progress aggregation per field, union or upazila."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from dataclasses import field as dc_field
from datetime import date, datetime, time, timedelta
from decimal import Decimal

from django.db.models import Avg, Count, Min, Q
from django.utils import timezone

from apps.alerts.models import Alert
from apps.farms.models import Field
from apps.monitoring.models import FieldVisit, IrrigationEvent, WaterLevelReading

GROUP_FIELDS = {"field": "id", "union": "union_name", "upazila": "upazila"}

# Continuous flooding on Boro rice in NW Bangladesh needs a pump run roughly every
# 3 days; AWD typically cuts that to every 5-7 days. Used only for the saving estimate.
CONTINUOUS_FLOODING_IRRIGATIONS_PER_WEEK = Decimal("2.33")


@dataclass
class ReportRow:
    group_by: str
    key: str
    label: str
    week_start: date
    week_end: date
    fields: int = 0
    area_ha: float = 0.0
    readings: int = 0
    avg_level_cm: float | None = None
    min_level_cm: float | None = None
    field_days_below_threshold: int = 0
    irrigation_events: int = 0
    irrigation_per_field: float = 0.0
    estimated_water_saving_pct: float = 0.0
    visits: int = 0
    alerts_opened: int = 0
    alerts_open_now: int = 0
    field_ids: list[int] = dc_field(default_factory=list)

    def to_dict(self) -> dict:
        return asdict(self)


def week_bounds(week_start: date) -> tuple[datetime, datetime]:
    """Local-midnight bounds [start, end) for the 7 days beginning ``week_start``."""
    tz = timezone.get_default_timezone()
    start = timezone.make_aware(datetime.combine(week_start, time.min), tz)
    return start, start + timedelta(days=7)


def monday_of(day: date) -> date:
    return day - timedelta(days=day.weekday())


def weekly_report(
    week_start: date | None = None,
    group_by: str = "field",
    upazila: str | None = None,
    union_name: str | None = None,
) -> list[ReportRow]:
    if group_by not in GROUP_FIELDS:
        raise ValueError(f"group_by must be one of {sorted(GROUP_FIELDS)}")
    week_start = week_start or monday_of(timezone.localdate() - timedelta(days=7))
    start, end = week_bounds(week_start)

    fields = Field.objects.filter(is_active=True)
    if upazila:
        fields = fields.filter(upazila__iexact=upazila)
    if union_name:
        fields = fields.filter(union_name__iexact=union_name)
    fields = list(fields.select_related("farmer"))
    if not fields:
        return []
    field_ids = [f.id for f in fields]

    reading_stats = {
        row["pipe__field_id"]: row
        for row in WaterLevelReading.objects.filter(
            pipe__field_id__in=field_ids, recorded_at__gte=start, recorded_at__lt=end
        )
        .values("pipe__field_id")
        .annotate(n=Count("id"), avg=Avg("level_cm"), low=Min("level_cm"))
    }
    # Field-days below threshold: distinct local days whose min reading <= field threshold.
    days_below: dict[int, set[date]] = {fid: set() for fid in field_ids}
    thresholds = {f.id: f.awd_threshold_cm for f in fields}
    for fid, recorded_at, level in WaterLevelReading.objects.filter(
        pipe__field_id__in=field_ids, recorded_at__gte=start, recorded_at__lt=end
    ).values_list("pipe__field_id", "recorded_at", "level_cm"):
        if level <= thresholds[fid]:
            days_below[fid].add(timezone.localtime(recorded_at).date())

    irrigations = dict(
        IrrigationEvent.objects.filter(field_id__in=field_ids, started_at__gte=start, started_at__lt=end)
        .exclude(method=IrrigationEvent.Method.RAIN)
        .values_list("field_id")
        .annotate(n=Count("id"))
        .values_list("field_id", "n")
    )
    visits = dict(
        FieldVisit.objects.filter(field_id__in=field_ids, visited_at__gte=start, visited_at__lt=end)
        .values_list("field_id")
        .annotate(n=Count("id"))
        .values_list("field_id", "n")
    )
    alerts = {
        row["field_id"]: row
        for row in Alert.objects.filter(field_id__in=field_ids)
        .values("field_id")
        .annotate(
            opened=Count("id", filter=Q(triggered_at__gte=start, triggered_at__lt=end)),
            open_now=Count("id", filter=Q(resolved_at__isnull=True)),
        )
    }

    groups: dict[str, ReportRow] = {}
    sums: dict[str, dict[str, Decimal]] = {}
    for f in fields:
        key = str(getattr(f, GROUP_FIELDS[group_by]))
        label = f"{f.name} ({f.farmer.name})" if group_by == "field" else key
        row = groups.setdefault(
            key,
            ReportRow(
                group_by=group_by,
                key=key,
                label=label,
                week_start=week_start,
                week_end=week_start + timedelta(days=6),
            ),
        )
        acc = sums.setdefault(key, {"level_sum": Decimal(0), "n": Decimal(0)})
        stats = reading_stats.get(f.id)
        row.fields += 1
        row.area_ha += float(f.area_m2) / 10_000
        row.field_ids.append(f.id)
        if stats:
            row.readings += stats["n"]
            acc["level_sum"] += Decimal(stats["avg"]) * stats["n"]
            acc["n"] += stats["n"]
            low = float(stats["low"])
            row.min_level_cm = low if row.min_level_cm is None else min(row.min_level_cm, low)
        row.field_days_below_threshold += len(days_below[f.id])
        row.irrigation_events += irrigations.get(f.id, 0)
        row.visits += visits.get(f.id, 0)
        if f.id in alerts:
            row.alerts_opened += alerts[f.id]["opened"]
            row.alerts_open_now += alerts[f.id]["open_now"]

    for key, row in groups.items():
        acc = sums[key]
        if acc["n"]:
            row.avg_level_cm = round(float(acc["level_sum"] / acc["n"]), 1)
        row.area_ha = round(row.area_ha, 3)
        row.irrigation_per_field = round(row.irrigation_events / row.fields, 2)
        baseline = float(CONTINUOUS_FLOODING_IRRIGATIONS_PER_WEEK)
        saving = 1 - (row.irrigation_per_field / baseline) if row.irrigation_per_field else 1.0
        row.estimated_water_saving_pct = round(max(0.0, min(saving, 1.0)) * 100, 1)
    return sorted(groups.values(), key=lambda r: r.label)
