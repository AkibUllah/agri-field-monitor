from __future__ import annotations

import datetime

import strawberry
from django.db.models import Count, Exists, OuterRef, Q
from strawberry.types import Info

from api.permissions import IsAuthenticated, current_user
from api.types import (
    AlertPage,
    AlertType,
    FarmerPage,
    FarmerType,
    FieldPage,
    FieldType,
    LocationType,
    ReadingPage,
    ReportRowType,
    UserType,
)
from apps.alerts.models import Alert
from apps.alerts.reports import weekly_report
from apps.farms.models import Farmer, Field
from apps.monitoring.models import WaterLevelReading

MAX_LIMIT = 200


def clamp(offset: int, limit: int) -> tuple[int, int]:
    return max(0, offset), max(1, min(limit, MAX_LIMIT))


@strawberry.type
class Query:
    @strawberry.field(permission_classes=[IsAuthenticated])
    def me(self, info: Info) -> UserType:
        return current_user(info)

    @strawberry.field(permission_classes=[IsAuthenticated])
    def farmers(
        self,
        search: str | None = None,
        district: str | None = None,
        upazila: str | None = None,
        union_name: str | None = None,
        offset: int = 0,
        limit: int = 20,
    ) -> FarmerPage:
        offset, limit = clamp(offset, limit)
        qs = Farmer.objects.all()
        if search:
            qs = qs.filter(
                Q(name__icontains=search) | Q(phone__icontains=search) | Q(village__icontains=search)
            )
        if district:
            qs = qs.filter(district__iexact=district)
        if upazila:
            qs = qs.filter(upazila__iexact=upazila)
        if union_name:
            qs = qs.filter(union_name__iexact=union_name)
        return FarmerPage(
            items=list(qs[offset : offset + limit]), total=qs.count(), offset=offset, limit=limit
        )

    @strawberry.field(permission_classes=[IsAuthenticated])
    def farmer(self, id: strawberry.ID) -> FarmerType | None:
        return Farmer.objects.filter(pk=id).first()

    @strawberry.field(permission_classes=[IsAuthenticated])
    def fields(
        self,
        farmer_id: strawberry.ID | None = None,
        district: str | None = None,
        upazila: str | None = None,
        union_name: str | None = None,
        crop: str | None = None,
        with_open_alerts: bool | None = None,
        include_inactive: bool = False,
        offset: int = 0,
        limit: int = 20,
    ) -> FieldPage:
        offset, limit = clamp(offset, limit)
        qs = Field.objects.select_related("farmer")
        if not include_inactive:
            qs = qs.filter(is_active=True)
        if farmer_id:
            qs = qs.filter(farmer_id=farmer_id)
        if district:
            qs = qs.filter(district__iexact=district)
        if upazila:
            qs = qs.filter(upazila__iexact=upazila)
        if union_name:
            qs = qs.filter(union_name__iexact=union_name)
        if crop:
            qs = qs.filter(crop=crop)
        if with_open_alerts is not None:
            has_open = Exists(Alert.objects.filter(field_id=OuterRef("pk"), resolved_at__isnull=True))
            qs = qs.filter(has_open) if with_open_alerts else qs.filter(~has_open)
        return FieldPage(
            items=list(qs[offset : offset + limit]), total=qs.count(), offset=offset, limit=limit
        )

    @strawberry.field(permission_classes=[IsAuthenticated])
    def field(self, id: strawberry.ID) -> FieldType | None:
        return Field.objects.select_related("farmer").filter(pk=id).first()

    @strawberry.field(permission_classes=[IsAuthenticated])
    def readings(
        self,
        field_id: strawberry.ID | None = None,
        pipe_id: strawberry.ID | None = None,
        since: datetime.datetime | None = None,
        until: datetime.datetime | None = None,
        reading_source: str | None = None,
        offset: int = 0,
        limit: int = 50,
    ) -> ReadingPage:
        offset, limit = clamp(offset, limit)
        qs = WaterLevelReading.objects.select_related("pipe", "pipe__field", "recorded_by")
        if field_id:
            qs = qs.filter(pipe__field_id=field_id)
        if pipe_id:
            qs = qs.filter(pipe_id=pipe_id)
        if since:
            qs = qs.filter(recorded_at__gte=since)
        if until:
            qs = qs.filter(recorded_at__lt=until)
        if reading_source:
            qs = qs.filter(source=reading_source)
        return ReadingPage(
            items=list(qs[offset : offset + limit]), total=qs.count(), offset=offset, limit=limit
        )

    @strawberry.field(permission_classes=[IsAuthenticated])
    def alerts(
        self,
        field_id: strawberry.ID | None = None,
        kind: str | None = None,
        severity: str | None = None,
        upazila: str | None = None,
        open_only: bool = True,
        offset: int = 0,
        limit: int = 50,
    ) -> AlertPage:
        offset, limit = clamp(offset, limit)
        qs = Alert.objects.select_related("field", "field__farmer")
        if open_only:
            qs = qs.filter(resolved_at__isnull=True)
        if field_id:
            qs = qs.filter(field_id=field_id)
        if kind:
            qs = qs.filter(kind=kind)
        if severity:
            qs = qs.filter(severity=severity)
        if upazila:
            qs = qs.filter(field__upazila__iexact=upazila)
        return AlertPage(
            items=list(qs[offset : offset + limit]), total=qs.count(), offset=offset, limit=limit
        )

    @strawberry.field(permission_classes=[IsAuthenticated])
    def alert(self, id: strawberry.ID) -> AlertType | None:
        return Alert.objects.filter(pk=id).first()

    @strawberry.field(permission_classes=[IsAuthenticated])
    def locations(self) -> list[LocationType]:
        rows = (
            Field.objects.filter(is_active=True)
            .values("district", "upazila", "union_name")
            .annotate(n=Count("id"))
            .order_by("district", "upazila", "union_name")
        )
        return [
            LocationType(
                district=r["district"], upazila=r["upazila"], union_name=r["union_name"], fields=r["n"]
            )
            for r in rows
        ]

    @strawberry.field(
        permission_classes=[IsAuthenticated],
        description="Weekly AWD progress. group_by: field | union | upazila. Defaults to last full week.",
    )
    def weekly_report(
        self,
        week_start: datetime.date | None = None,
        group_by: str = "field",
        upazila: str | None = None,
        union_name: str | None = None,
    ) -> list[ReportRowType]:
        rows = weekly_report(week_start=week_start, group_by=group_by, upazila=upazila, union_name=union_name)
        return [ReportRowType(**row.to_dict()) for row in rows]
