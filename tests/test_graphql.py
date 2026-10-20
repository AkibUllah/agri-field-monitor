from datetime import timedelta

import pytest
from django.utils import timezone

from apps.alerts.models import Alert
from apps.farms.models import Farmer, Field
from apps.monitoring.models import IrrigationEvent, WaterLevelReading
from tests.conftest import SQUARE_100M, add_readings

pytestmark = pytest.mark.django_db


def test_queries_require_authentication(gql_anon, farmer):
    body = gql_anon("{ farmers { total } }")
    assert body["data"] is None
    assert "Authentication required" in body["errors"][0]["message"]


def test_login_mutation_issues_token_and_rejects_bad_password(gql_anon, user, client):
    body = gql_anon(
        'mutation { login(username: "agent", password: "agent1234") { token tokenType expiresInSeconds user { username } } }'
    )
    payload = body["data"]["login"]
    assert payload["tokenType"] == "Bearer" and payload["user"]["username"] == "agent"
    assert payload["expiresInSeconds"] == 12 * 3600
    me = gql_anon("{ me { username isStaff } }", headers={"HTTP_AUTHORIZATION": f"Bearer {payload['token']}"})
    assert me["data"]["me"] == {"username": "agent", "isStaff": True}
    bad = gql_anon('mutation { login(username: "agent", password: "nope") { token } }')
    assert bad["errors"][0]["message"] == "Invalid credentials"


def test_farmers_query_search_and_pagination(gql, farmer):
    Farmer.objects.create(
        name="Rafiqul Islam", phone="01811000102", village="Khanpur", union_name="Khanpur",
        upazila="Sherpur", district="Bogura",
    )  # fmt: skip
    body = gql("{ farmers(limit: 1, offset: 0) { total limit items { name upazila } } }")
    assert body["data"]["farmers"]["total"] == 2 and len(body["data"]["farmers"]["items"]) == 1
    body = gql('{ farmers(search: "rafiq") { total items { phone } } }')
    assert body["data"]["farmers"]["items"] == [{"phone": "01811000102"}]
    body = gql('{ farmers(district: "rajshahi") { total } }')
    assert body["data"]["farmers"]["total"] == 1
    body = gql(f'{{ farmer(id: "{farmer.id}") {{ name totalAreaM2 fields {{ name }} }} }}')
    assert body["data"]["farmer"]["name"] == "Abdul Karim"


def test_field_detail_with_area_latest_reading_and_alerts(gql, field, pipe):
    add_readings(pipe, [-5, -12, -16])
    Alert.objects.create(field=field, kind=Alert.Kind.IRRIGATION_DUE, message="irrigate")
    body = gql(
        f"""{{ field(id: "{field.id}") {{
            name crop areaM2 area {{ hectare bigha decimal }} perimeterM
            centroidLat polygon upazila awdThresholdCm
            farmer {{ name }}
            pipes {{ code hasDevice latestReading {{ levelCm }} }}
            activeSeason {{ variety }}
            latestReading {{ levelCm belowThreshold pipe {{ code }} }}
            openAlerts {{ kind severity isOpen }}
            readings(limit: 2) {{ levelCm }}
        }} }}"""
    )
    data = body["data"]["field"]
    assert data["crop"] == "boro" and data["farmer"]["name"] == "Abdul Karim"
    assert data["area"]["hectare"] == pytest.approx(1.0, abs=0.01)
    assert data["area"]["bigha"] == pytest.approx(7.47, abs=0.02)
    assert data["perimeterM"] == pytest.approx(400, abs=3)
    assert len(data["polygon"]) == 4
    assert data["latestReading"] == {
        "levelCm": "-16.0",
        "belowThreshold": True,
        "pipe": {"code": "PAB-001-A"},
    }
    assert data["pipes"][0]["latestReading"]["levelCm"] == "-16.0"
    assert data["openAlerts"] == [{"kind": "irrigation_due", "severity": "warning", "isOpen": True}]
    assert [r["levelCm"] for r in data["readings"]] == ["-16.0", "-12.0"]
    assert data["activeSeason"]["variety"] == "BRRI dhan29"


def test_fields_query_filters(gql, field, farmer):
    other = Farmer.objects.create(
        name="X", phone="01911000103", village="v", union_name="Khanpur", upazila="Sherpur", district="Bogura"
    )
    f2 = Field.objects.create(farmer=other, name="plot", polygon=SQUARE_100M, crop=Field.Crop.AMAN)
    Field.objects.create(farmer=other, name="old", polygon=SQUARE_100M, is_active=False)
    Alert.objects.create(field=f2, kind=Alert.Kind.OVERFLOW, message="x")
    assert gql("{ fields { total } }")["data"]["fields"]["total"] == 2
    assert gql("{ fields(includeInactive: true) { total } }")["data"]["fields"]["total"] == 3
    assert gql('{ fields(upazila: "Paba") { items { name } } }')["data"]["fields"]["items"] == [
        {"name": "Nowdapara plot 1"}
    ]
    assert gql('{ fields(crop: "aman") { total } }')["data"]["fields"]["total"] == 1
    assert gql("{ fields(withOpenAlerts: true) { items { name } } }")["data"]["fields"]["items"] == [
        {"name": "plot"}
    ]
    assert gql("{ fields(withOpenAlerts: false) { total } }")["data"]["fields"]["total"] == 1
    assert gql(f'{{ fields(farmerId: "{farmer.id}") {{ total }} }}')["data"]["fields"]["total"] == 1
    locs = gql("{ locations { district upazila unionName fields } }")["data"]["locations"]
    assert locs == [
        {"district": "Bogura", "upazila": "Sherpur", "unionName": "Khanpur", "fields": 1},
        {"district": "Rajshahi", "upazila": "Paba", "unionName": "Haripur", "fields": 1},
    ]


def test_readings_query_window_and_source(gql, field, pipe):
    readings = add_readings(pipe, [-1, -2, -3, -4])
    since = (timezone.now() - timedelta(days=1, hours=1)).isoformat()
    body = gql(
        f'{{ readings(fieldId: "{field.id}", since: "{since}") {{ total items {{ levelCm source recordedAt }} }} }}'
    )
    assert body["data"]["readings"]["total"] == 2
    assert [r["levelCm"] for r in body["data"]["readings"]["items"]] == ["-4.0", "-3.0"]
    assert (
        gql(f'{{ readings(pipeId: "{pipe.id}", readingSource: "device") {{ total }} }}')["data"]["readings"][
            "total"
        ]
        == 0
    )
    assert (
        gql(f'{{ readings(pipeId: "{pipe.id}", limit: 1000) {{ limit }} }}')["data"]["readings"]["limit"]
        == 200
    )
    assert len(readings) == 4


def test_create_farmer_validation_and_success(gql):
    base = "mutation($i: FarmerInput!) { createFarmer(input: $i) { id name phone upazila } }"
    good = {
        "name": "Jahanara Khatun", "phone": "01511000105", "village": "Kalma Bazar",
        "unionName": "Kalma", "upazila": "Tanore", "district": "Rajshahi", "nid": "1234567890123",
    }  # fmt: skip
    body = gql(base, {"i": good})
    assert body["data"]["createFarmer"]["upazila"] == "Tanore"
    dup = gql(base, {"i": good})
    assert "already exists" in dup["errors"][0]["message"]
    bad_phone = gql(base, {"i": {**good, "phone": "0123"}})
    assert "Bangladeshi mobile" in bad_phone["errors"][0]["message"]
    bad_nid = gql(base, {"i": {**good, "phone": "01511000106", "nid": "12"}})
    assert "nid" in bad_nid["errors"][0]["message"]


def test_create_field_computes_area_and_validates_polygon(gql, farmer):
    mutation = "mutation($i: FieldInput!) { createField(input: $i) { id name areaM2 upazila awdThresholdCm area { bigha } } }"
    body = gql(mutation, {"i": {"farmerId": str(farmer.id), "name": "New plot", "polygon": SQUARE_100M}})
    data = body["data"]["createField"]
    assert float(data["areaM2"]) == pytest.approx(10_000, rel=0.005)
    assert data["upazila"] == "Paba" and data["awdThresholdCm"] == -15
    bad = gql(mutation, {"i": {"farmerId": str(farmer.id), "name": "x", "polygon": [[1, 2], [3, 4]]}})
    assert "invalid polygon" in bad["errors"][0]["message"]
    bad_crop = gql(
        mutation, {"i": {"farmerId": str(farmer.id), "name": "x", "polygon": SQUARE_100M, "crop": "jute"}}
    )
    assert "crop must be one of" in bad_crop["errors"][0]["message"]
    missing = gql(mutation, {"i": {"farmerId": "9999", "name": "x", "polygon": SQUARE_100M}})
    assert "not found" in missing["errors"][0]["message"]
    bad_threshold = gql(
        mutation,
        {"i": {"farmerId": str(farmer.id), "name": "x", "polygon": SQUARE_100M, "awdThresholdCm": 5}},
    )
    assert "awd_threshold_cm" in bad_threshold["errors"][0]["message"]


def test_add_reading_by_code_with_validation(gql, pipe, user):
    mutation = "mutation($i: ReadingInput!) { addReading(input: $i) { levelCm source belowThreshold recordedBy { username } pipe { code } } }"
    body = gql(mutation, {"i": {"pipeCode": "PAB-001-A", "levelCm": "-15.5", "note": "morning reading"}})
    data = body["data"]["addReading"]
    assert data == {
        "levelCm": "-15.5", "source": "manual", "belowThreshold": True,
        "recordedBy": {"username": "agent"}, "pipe": {"code": "PAB-001-A"},
    }  # fmt: skip
    assert WaterLevelReading.objects.get().recorded_by == user
    out_of_range = gql(mutation, {"i": {"pipeId": str(pipe.id), "levelCm": "-99"}})
    assert "level_cm" in out_of_range["errors"][0]["message"]
    future = (timezone.now() + timedelta(hours=2)).isoformat()
    assert (
        "future"
        in gql(mutation, {"i": {"pipeId": str(pipe.id), "levelCm": "-1", "recordedAt": future}})["errors"][0][
            "message"
        ]
    )
    assert (
        "pipe not found"
        in gql(mutation, {"i": {"pipeCode": "NOPE", "levelCm": "-1"}})["errors"][0]["message"]
    )
    assert "required" in gql(mutation, {"i": {"levelCm": "-1"}})["errors"][0]["message"]
    pipe.is_active = False
    pipe.save()
    assert (
        "inactive" in gql(mutation, {"i": {"pipeId": str(pipe.id), "levelCm": "-1"}})["errors"][0]["message"]
    )


def test_irrigation_awd_check_and_resolve_alert_flow(gql, field, pipe):
    add_readings(pipe, [-15, -16, -17])
    run = gql("mutation { runAwdCheck { fieldsChecked opened resolved } }")["data"]["runAwdCheck"]
    assert run == {"fieldsChecked": 1, "opened": 1, "resolved": 0}
    alerts = gql('{ alerts(kind: "irrigation_due") { total items { id severity field { name } } } }')["data"][
        "alerts"
    ]
    assert alerts["total"] == 1 and alerts["items"][0]["severity"] == "warning"
    alert_id = alerts["items"][0]["id"]

    irrigation = gql(
        'mutation($i: IrrigationInput!) { logIrrigation(input: $i) { method waterMm durationMinutes loggedBy { username } } }',
        {"i": {"fieldId": str(field.id), "startedAt": (timezone.now() - timedelta(hours=3)).isoformat(),
               "endedAt": (timezone.now() - timedelta(hours=1)).isoformat(), "waterMm": "50"}},
    )["data"]["logIrrigation"]  # fmt: skip
    assert irrigation == {
        "method": "pump",
        "waterMm": "50",
        "durationMinutes": 120,
        "loggedBy": {"username": "agent"},
    }
    bad = gql(
        "mutation($i: IrrigationInput!) { logIrrigation(input: $i) { id } }",
        {
            "i": {
                "fieldId": str(field.id),
                "startedAt": timezone.now().isoformat(),
                "endedAt": (timezone.now() - timedelta(hours=1)).isoformat(),
            }
        },
    )
    assert "ended_at" in bad["errors"][0]["message"]

    resolved = gql(
        f'mutation {{ resolveAlert(id: "{alert_id}", note: "pumped 2h") {{ isOpen resolutionNote resolvedBy {{ username }} }} }}'
    )
    assert resolved["data"]["resolveAlert"] == {
        "isOpen": False,
        "resolutionNote": "pumped 2h",
        "resolvedBy": {"username": "agent"},
    }
    again = gql(f'mutation {{ resolveAlert(id: "{alert_id}") {{ id }} }}')
    assert "already resolved" in again["errors"][0]["message"]
    assert gql("{ alerts { total } }")["data"]["alerts"]["total"] == 0
    assert gql("{ alerts(openOnly: false) { total } }")["data"]["alerts"]["total"] == 1
    assert IrrigationEvent.objects.count() == 1


def test_create_visit_and_weekly_report_query(gql, field, pipe):
    visit = gql(
        "mutation($i: VisitInput!) { createVisit(input: $i) { id cropStage visitor { username } photos { id } field { name } } }",
        {
            "i": {
                "fieldId": str(field.id),
                "cropStage": "tillering",
                "notes": "all good",
                "lat": 24.395,
                "lng": 88.585,
            }
        },
    )["data"]["createVisit"]
    assert (
        visit["cropStage"] == "tillering"
        and visit["photos"] == []
        and visit["visitor"]["username"] == "agent"
    )
    half = gql(
        "mutation($i: VisitInput!) { createVisit(input: $i) { id } }",
        {"i": {"fieldId": str(field.id), "lat": 1.0}},
    )
    assert "lat and lng" in half["errors"][0]["message"]
    bad_stage = gql(
        "mutation($i: VisitInput!) { createVisit(input: $i) { id } }",
        {"i": {"fieldId": str(field.id), "cropStage": "ripe"}},
    )
    assert "crop_stage" in bad_stage["errors"][0]["message"]

    add_readings(pipe, [-3, -6, -9])
    week = (timezone.localdate() - timedelta(days=timezone.localdate().weekday())).isoformat()
    report = gql(
        f'{{ weeklyReport(weekStart: "{week}", groupBy: "upazila") {{ key fields readings avgLevelCm visits irrigationEvents estimatedWaterSavingPct weekStart }} }}'
    )["data"]["weeklyReport"]
    assert report[0]["key"] == "Paba" and report[0]["fields"] == 1
    assert report[0]["visits"] == 1 and report[0]["weekStart"] == week
    assert report[0]["readings"] >= 1
    bad_group = gql('{ weeklyReport(groupBy: "district") { key } }')
    assert "group_by" in bad_group["errors"][0]["message"]
