from __future__ import annotations

import json
from datetime import timedelta
from decimal import Decimal

import pytest
from django.contrib.auth import get_user_model
from django.test import Client
from django.utils import timezone

from apps.alerts.models import Alert
from apps.alerts.reports import monday_of, week_bounds
from apps.core.auth import create_token
from apps.farms.models import Farmer, Field, Season
from apps.monitoring.models import FieldVisit, IrrigationEvent, Pipe

# ~100 m x 100 m square near Paba, Rajshahi (lat/lng degrees per metre at 24.4N).
SQUARE_100M = [
    [24.3950, 88.5850],
    [24.3950 + 100 / 111_320, 88.5850],
    [24.3950 + 100 / 111_320, 88.5850 + 100 / (111_320 * 0.9106)],
    [24.3950, 88.5850 + 100 / (111_320 * 0.9106)],
]


@pytest.fixture(autouse=True)
def media_tmp(settings, tmp_path):
    settings.MEDIA_ROOT = tmp_path / "media"


@pytest.fixture
def user(db):
    return get_user_model().objects.create_user(username="agent", password="agent1234", is_staff=True)


@pytest.fixture
def token(user) -> str:
    return create_token(user)


@pytest.fixture
def auth_headers(token) -> dict[str, str]:
    return {"HTTP_AUTHORIZATION": f"Bearer {token}"}


@pytest.fixture
def farmer(db) -> Farmer:
    return Farmer.objects.create(
        name="Abdul Karim",
        phone="01711000101",
        nid="1234567890",
        village="Nowdapara",
        union_name="Haripur",
        upazila="Paba",
        district="Rajshahi",
    )


@pytest.fixture
def field(farmer) -> Field:
    f = Field.objects.create(farmer=farmer, name="Nowdapara plot 1", polygon=SQUARE_100M)
    Season.objects.create(
        field=f,
        variety="BRRI dhan29",
        transplanted_on=timezone.localdate() - timedelta(days=40),
        awd_start_on=timezone.localdate() - timedelta(days=26),
    )
    return f


@pytest.fixture
def pipe(field) -> Pipe:
    return Pipe.objects.create(
        field=field, code="PAB-001-A", installed_on=timezone.localdate() - timedelta(days=30)
    )


def add_readings(pipe: Pipe, levels: list[float], *, end=None, step_days: int = 1):
    """Create one reading per day ending at ``end`` (default now), oldest first."""
    from apps.monitoring.models import WaterLevelReading

    end = end or timezone.now()
    out = []
    for i, level in enumerate(reversed(levels)):
        out.append(
            WaterLevelReading.objects.create(
                pipe=pipe, level_cm=Decimal(str(level)), recorded_at=end - timedelta(days=i * step_days)
            )
        )
    return list(reversed(out))


class GraphQLClient:
    def __init__(self, client: Client, headers: dict[str, str] | None = None) -> None:
        self.client = client
        self.headers = headers or {}

    def __call__(self, query: str, variables: dict | None = None, headers: dict | None = None) -> dict:
        response = self.client.post(
            "/graphql/",
            data=json.dumps({"query": query, "variables": variables or {}}),
            content_type="application/json",
            **(headers if headers is not None else self.headers),
        )
        assert response.status_code == 200, response.content
        return response.json()


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


@pytest.fixture
def gql(client, auth_headers) -> GraphQLClient:
    return GraphQLClient(client, auth_headers)


@pytest.fixture
def gql_anon(client) -> GraphQLClient:
    return GraphQLClient(client, {})
