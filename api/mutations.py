from __future__ import annotations

import datetime
import decimal
import re

import strawberry
from django.conf import settings
from django.contrib.auth import authenticate
from django.core.exceptions import ValidationError
from django.utils import timezone
from graphql import GraphQLError
from strawberry.scalars import JSON
from strawberry.types import Info

from api.permissions import IsAuthenticated, current_user
from api.types import (
    AlertType,
    AuthPayload,
    AwdCheckResultType,
    FarmerType,
    FieldType,
    IrrigationEventType,
    ReadingType,
    VisitType,
)
from apps.alerts.awd import run_awd_check
from apps.alerts.models import Alert
from apps.core.auth import create_token
from apps.farms import geo
from apps.farms.models import Farmer, Field
from apps.monitoring.models import FieldVisit, IrrigationEvent, Pipe, WaterLevelReading

BD_PHONE_RE = re.compile(r"^01[3-9]\d{8}$")
NID_RE = re.compile(r"^(\d{10}|\d{13}|\d{17})$")


@strawberry.input
class FarmerInput:
    name: str
    phone: str
    village: str
    union_name: str
    upazila: str
    district: str
    nid: str | None = None


@strawberry.input
class FieldInput:
    farmer_id: strawberry.ID
    name: str
    polygon: JSON = strawberry.field(description="List of [lat, lng] pairs")
    crop: str = Field.Crop.BORO
    awd_threshold_cm: int | None = None


@strawberry.input
class ReadingInput:
    level_cm: decimal.Decimal
    pipe_id: strawberry.ID | None = None
    pipe_code: str | None = None
    recorded_at: datetime.datetime | None = None
    source: str = WaterLevelReading.Source.MANUAL
    note: str = ""


@strawberry.input
class IrrigationInput:
    field_id: strawberry.ID
    started_at: datetime.datetime | None = None
    ended_at: datetime.datetime | None = None
    method: str = IrrigationEvent.Method.PUMP
    water_mm: decimal.Decimal | None = None
    note: str = ""


@strawberry.input
class VisitInput:
    field_id: strawberry.ID
    visited_at: datetime.datetime | None = None
    crop_stage: str = ""
    notes: str = ""
    lat: float | None = None
    lng: float | None = None


def _choice(value: str, choices, label: str) -> str:  # noqa: ANN001
    if value not in choices.values:
        raise GraphQLError(f"{label} must be one of {list(choices.values)}")
    return value


def _get_or_error(model, pk, label: str):  # noqa: ANN001
    obj = model.objects.filter(pk=pk).first()
    if obj is None:
        raise GraphQLError(f"{label} {pk} not found")
    return obj


@strawberry.type
class Mutation:
    @strawberry.mutation(description="Exchange username/password for a bearer JWT")
    def login(self, username: str, password: str) -> AuthPayload:
        user = authenticate(username=username, password=password)
        if user is None:
            raise GraphQLError("Invalid credentials")
        return AuthPayload(
            token=create_token(user),
            token_type="Bearer",
            expires_in_seconds=settings.JWT_LIFETIME_HOURS * 3600,
            user=user,
        )

    @strawberry.mutation(permission_classes=[IsAuthenticated])
    def create_farmer(self, input: FarmerInput) -> FarmerType:
        if not BD_PHONE_RE.match(input.phone):
            raise GraphQLError("phone must be a Bangladeshi mobile number like 017XXXXXXXX")
        if input.nid and not NID_RE.match(input.nid):
            raise GraphQLError("nid must be 10, 13 or 17 digits")
        if Farmer.objects.filter(phone=input.phone).exists():
            raise GraphQLError("a farmer with this phone already exists")
        return Farmer.objects.create(
            name=input.name.strip(),
            phone=input.phone,
            nid=input.nid or "",
            village=input.village.strip(),
            union_name=input.union_name.strip(),
            upazila=input.upazila.strip(),
            district=input.district.strip(),
        )

    @strawberry.mutation(permission_classes=[IsAuthenticated])
    def create_field(self, input: FieldInput) -> FieldType:
        farmer = _get_or_error(Farmer, input.farmer_id, "farmer")
        try:
            geo.validate_polygon(input.polygon)
        except geo.InvalidPolygonError as exc:
            raise GraphQLError(f"invalid polygon: {exc}") from exc
        field = Field(
            farmer=farmer,
            name=input.name.strip(),
            crop=_choice(input.crop, Field.Crop, "crop"),
            polygon=input.polygon,
            awd_threshold_cm=input.awd_threshold_cm
            if input.awd_threshold_cm is not None
            else settings.AWD_THRESHOLD_CM,
        )
        if not -40 <= field.awd_threshold_cm <= 0:
            raise GraphQLError("awd_threshold_cm must be between -40 and 0")
        field.save()
        return field

    @strawberry.mutation(permission_classes=[IsAuthenticated])
    def add_reading(self, info: Info, input: ReadingInput) -> ReadingType:
        if input.pipe_id is None and not input.pipe_code:
            raise GraphQLError("pipe_id or pipe_code is required")
        pipe = (
            Pipe.objects.filter(pk=input.pipe_id).first()
            if input.pipe_id is not None
            else Pipe.objects.filter(code=input.pipe_code).first()
        )
        if pipe is None:
            raise GraphQLError("pipe not found")
        if not pipe.is_active:
            raise GraphQLError(f"pipe {pipe.code} is inactive")
        recorded_at = input.recorded_at or timezone.now()
        if recorded_at > timezone.now() + datetime.timedelta(minutes=5):
            raise GraphQLError("recorded_at cannot be in the future")
        reading = WaterLevelReading(
            pipe=pipe,
            level_cm=input.level_cm,
            source=_choice(input.source, WaterLevelReading.Source, "source"),
            recorded_at=recorded_at,
            recorded_by=current_user(info),
            note=input.note[:200],
        )
        try:
            reading.full_clean()
        except ValidationError as exc:
            raise GraphQLError("; ".join(f"{k}: {' '.join(v)}" for k, v in exc.message_dict.items())) from exc
        reading.save()
        return reading

    @strawberry.mutation(permission_classes=[IsAuthenticated])
    def log_irrigation(self, info: Info, input: IrrigationInput) -> IrrigationEventType:
        field = _get_or_error(Field, input.field_id, "field")
        started = input.started_at or timezone.now()
        if input.ended_at and input.ended_at < started:
            raise GraphQLError("ended_at must be after started_at")
        if input.water_mm is not None and not 0 < input.water_mm <= 500:
            raise GraphQLError("water_mm must be between 0 and 500")
        return IrrigationEvent.objects.create(
            field=field,
            started_at=started,
            ended_at=input.ended_at,
            method=_choice(input.method, IrrigationEvent.Method, "method"),
            water_mm=input.water_mm,
            note=input.note[:200],
            logged_by=current_user(info),
        )

    @strawberry.mutation(permission_classes=[IsAuthenticated])
    def create_visit(self, info: Info, input: VisitInput) -> VisitType:
        field = _get_or_error(Field, input.field_id, "field")
        if input.crop_stage:
            _choice(input.crop_stage, FieldVisit.CropStage, "crop_stage")
        if (input.lat is None) != (input.lng is None):
            raise GraphQLError("lat and lng must be given together")
        return FieldVisit.objects.create(
            field=field,
            visitor=current_user(info),
            visited_at=input.visited_at or timezone.now(),
            crop_stage=input.crop_stage,
            notes=input.notes,
            lat=input.lat,
            lng=input.lng,
        )

    @strawberry.mutation(permission_classes=[IsAuthenticated])
    def resolve_alert(self, info: Info, id: strawberry.ID, note: str = "") -> AlertType:
        alert = _get_or_error(Alert, id, "alert")
        if alert.resolved_at is not None:
            raise GraphQLError("alert is already resolved")
        alert.resolve(current_user(info), note=note[:200])
        return alert

    @strawberry.mutation(
        permission_classes=[IsAuthenticated],
        description="Evaluate AWD rules for every active field now (also run by the scheduler)",
    )
    def run_awd_check(self) -> AwdCheckResultType:
        result = run_awd_check()
        return AwdCheckResultType(**result.__dict__)
