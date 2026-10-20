"""GraphQL object types mapped onto the Django models."""

from __future__ import annotations

import datetime
import decimal

import strawberry
import strawberry_django
from django.contrib.auth import get_user_model
from strawberry import auto
from strawberry.scalars import JSON

from apps.alerts.models import Alert
from apps.farms import geo
from apps.farms.models import Farmer, Field, Season
from apps.monitoring.models import FieldVisit, IrrigationEvent, Pipe, VisitPhoto, WaterLevelReading


@strawberry_django.type(get_user_model())
class UserType:
    id: auto
    username: auto
    first_name: auto
    last_name: auto
    is_staff: auto


@strawberry.type
class AreaType:
    m2: float
    hectare: float
    acre: float
    bigha: float
    decimal: float


@strawberry_django.type(Season)
class SeasonType:
    id: auto
    crop: auto
    variety: auto
    transplanted_on: auto
    awd_start_on: auto
    awd_end_on: auto
    expected_harvest_on: auto
    is_active: auto


@strawberry_django.type(WaterLevelReading)
class ReadingType:
    id: auto
    pipe: PipeType
    level_cm: auto
    source: auto
    recorded_at: auto
    recorded_by: UserType | None
    note: auto

    @strawberry.field(description="True when the level is at or below the field's AWD threshold")
    def below_threshold(self) -> bool:
        return self.level_cm <= self.pipe.field.awd_threshold_cm


@strawberry_django.type(Pipe)
class PipeType:
    id: auto
    field: FieldType
    code: auto
    depth_cm: auto
    installed_on: auto
    device_id: auto
    is_active: auto

    @strawberry.field
    def has_device(self) -> bool:
        return bool(self.device_id)

    @strawberry.field
    def latest_reading(self) -> ReadingType | None:
        return self.readings.order_by("-recorded_at").first()


@strawberry_django.type(IrrigationEvent)
class IrrigationEventType:
    id: auto
    field: FieldType
    started_at: auto
    ended_at: auto
    method: auto
    water_mm: auto
    note: auto
    logged_by: UserType | None

    @strawberry.field
    def duration_minutes(self) -> int | None:
        return self.duration_minutes


@strawberry_django.type(VisitPhoto)
class VisitPhotoType:
    id: auto
    caption: auto
    uploaded_at: auto

    @strawberry.field
    def url(self) -> str:
        return self.image.url


@strawberry_django.type(FieldVisit)
class VisitType:
    id: auto
    field: FieldType
    visitor: UserType | None
    visited_at: auto
    crop_stage: auto
    notes: auto
    lat: auto
    lng: auto
    photos: list[VisitPhotoType]


@strawberry_django.type(Alert)
class AlertType:
    id: auto
    field: FieldType
    kind: auto
    severity: auto
    message: auto
    value: auto
    triggered_at: auto
    resolved_at: auto
    resolved_by: UserType | None
    resolution_note: auto

    @strawberry.field
    def is_open(self) -> bool:
        return self.resolved_at is None


@strawberry_django.type(Field)
class FieldType:
    id: auto
    farmer: FarmerType
    name: auto
    crop: auto
    polygon: JSON
    area_m2: auto
    centroid_lat: auto
    centroid_lng: auto
    union_name: auto
    upazila: auto
    district: auto
    awd_threshold_cm: auto
    is_active: auto
    created_at: auto
    pipes: list[PipeType]
    seasons: list[SeasonType]

    @strawberry.field
    def area(self) -> AreaType:
        return AreaType(**geo.m2_to_units(float(self.area_m2)))

    @strawberry.field
    def perimeter_m(self) -> float:
        return round(geo.perimeter_m(self.polygon), 1)

    @strawberry.field
    def active_season(self) -> SeasonType | None:
        return self.active_season

    @strawberry.field
    def latest_reading(self) -> ReadingType | None:
        return (
            WaterLevelReading.objects.filter(pipe__field_id=self.id)
            .select_related("pipe", "pipe__field")
            .order_by("-recorded_at")
            .first()
        )

    @strawberry.field
    def open_alerts(self) -> list[AlertType]:
        return list(self.alerts.filter(resolved_at__isnull=True))

    @strawberry.field
    def last_irrigation(self) -> IrrigationEventType | None:
        return (
            self.irrigation_events.exclude(method=IrrigationEvent.Method.RAIN).order_by("-started_at").first()
        )

    @strawberry.field
    def readings(self, limit: int = 50) -> list[ReadingType]:
        return list(
            WaterLevelReading.objects.filter(pipe__field_id=self.id)
            .select_related("pipe", "pipe__field")
            .order_by("-recorded_at")[: max(1, min(limit, 500))]
        )


@strawberry_django.type(Farmer)
class FarmerType:
    id: auto
    name: auto
    phone: auto
    nid: auto
    village: auto
    union_name: auto
    upazila: auto
    district: auto
    created_at: auto
    fields: list[FieldType]

    @strawberry.field
    def total_area_m2(self) -> decimal.Decimal:
        return sum((f.area_m2 for f in self.fields.all()), decimal.Decimal(0))


# -- pagination wrappers ------------------------------------------------------


@strawberry.type
class FarmerPage:
    items: list[FarmerType]
    total: int
    offset: int
    limit: int


@strawberry.type
class FieldPage:
    items: list[FieldType]
    total: int
    offset: int
    limit: int


@strawberry.type
class ReadingPage:
    items: list[ReadingType]
    total: int
    offset: int
    limit: int


@strawberry.type
class AlertPage:
    items: list[AlertType]
    total: int
    offset: int
    limit: int


@strawberry.type
class LocationType:
    district: str
    upazila: str
    union_name: str
    fields: int


@strawberry.type
class ReportRowType:
    group_by: str
    key: str
    label: str
    week_start: datetime.date
    week_end: datetime.date
    fields: int
    area_ha: float
    readings: int
    avg_level_cm: float | None
    min_level_cm: float | None
    field_days_below_threshold: int
    irrigation_events: int
    irrigation_per_field: float
    estimated_water_saving_pct: float
    visits: int
    alerts_opened: int
    alerts_open_now: int
    field_ids: list[int]


@strawberry.type
class AwdCheckResultType:
    fields_checked: int
    opened: int
    resolved: int
    unchanged: int


@strawberry.type
class AuthPayload:
    token: str
    token_type: str
    expires_in_seconds: int
    user: UserType
