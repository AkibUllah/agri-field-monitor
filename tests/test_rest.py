import io
from datetime import timedelta

import pytest
from django.core.files.uploadedfile import SimpleUploadedFile
from django.core.management import call_command
from django.utils import timezone

from apps.alerts.models import Alert
from apps.core.auth import TokenError, create_token, decode_token, user_from_token
from apps.farms.models import Farmer, Field
from apps.monitoring.models import FieldVisit, VisitPhoto, WaterLevelReading

pytestmark = pytest.mark.django_db

PNG_BYTES = b"\x89PNG\r\n\x1a\n" + b"\x00" * 64


def test_health(client):
    response = client.get("/health/")
    assert response.status_code == 200
    assert response.json() == {"status": "ok", "database": "ok"}


def test_token_endpoint(client, user):
    ok = client.post("/api/v1/auth/token/", {"username": "agent", "password": "agent1234"})
    assert ok.status_code == 200
    body = ok.json()
    assert body["token_type"] == "Bearer" and body["expires_in"] == 12 * 3600
    assert user_from_token(body["token"]) == user
    bad = client.post("/api/v1/auth/token/", {"username": "agent", "password": "wrong"})
    assert bad.status_code == 401
    missing = client.post("/api/v1/auth/token/", {"username": "agent"})
    assert missing.status_code == 400


def test_jwt_helpers_reject_expired_invalid_and_inactive(user):
    expired = create_token(user, lifetime=timedelta(seconds=-5))
    with pytest.raises(TokenError, match="expired"):
        decode_token(expired)
    with pytest.raises(TokenError, match="invalid"):
        decode_token("not.a.token")
    user.is_active = False
    user.save()
    with pytest.raises(TokenError, match="user not found"):
        user_from_token(create_token(user))


def test_middleware_falls_back_to_anonymous_on_bad_token(client, user):
    expired = create_token(user, lifetime=timedelta(seconds=-5))
    response = client.post(
        "/graphql/", data='{"query": "{ me { username } }"}', content_type="application/json",
        HTTP_AUTHORIZATION=f"Bearer {expired}",
    )  # fmt: skip
    body = response.json()
    assert body["data"] is None and "Authentication required" in body["errors"][0]["message"]
    response = client.post(
        "/graphql/", data='{"query": "{ me { username } }"}', content_type="application/json",
        HTTP_AUTHORIZATION="Basic abc",
    )  # fmt: skip
    assert response.json()["data"] is None


@pytest.fixture
def visit(field, user):
    return FieldVisit.objects.create(field=field, visitor=user, visited_at=timezone.now())


def test_photo_upload_requires_auth(client, visit):
    response = client.post(
        f"/api/v1/visits/{visit.id}/photos/", {"image": SimpleUploadedFile("a.png", PNG_BYTES, "image/png")}
    )
    assert response.status_code == 401
    assert response["WWW-Authenticate"] == "Bearer"


def test_photo_upload_and_list(client, visit, auth_headers, settings):
    upload = SimpleUploadedFile("bund.png", PNG_BYTES, content_type="image/png")
    response = client.post(
        f"/api/v1/visits/{visit.id}/photos/", {"image": upload, "caption": "weed on bund"}, **auth_headers
    )
    assert response.status_code == 201, response.content
    body = response.json()
    assert body["caption"] == "weed on bund" and body["visit"] == visit.id
    assert body["url"].startswith("http://testserver/media/visits/")
    photo = VisitPhoto.objects.get()
    assert photo.image.name.startswith(f"visits/{visit.field_id}/{visit.id}/bund")
    assert (settings.MEDIA_ROOT / photo.image.name).exists()

    listing = client.get(f"/api/v1/visits/{visit.id}/photos/", **auth_headers)
    assert listing.status_code == 200 and len(listing.json()) == 1
    assert client.get("/api/v1/visits/9999/photos/", **auth_headers).status_code == 404
    assert (
        client.post(
            "/api/v1/visits/9999/photos/", {"image": SimpleUploadedFile("x.png", PNG_BYTES)}, **auth_headers
        ).status_code
        == 404
    )


def test_photo_upload_validation(client, visit, auth_headers, settings):
    bad_ext = SimpleUploadedFile("notes.pdf", b"%PDF-1.4", content_type="application/pdf")
    response = client.post(f"/api/v1/visits/{visit.id}/photos/", {"image": bad_ext}, **auth_headers)
    assert response.status_code == 400 and "unsupported file type" in response.json()["image"][0]

    settings.PHOTO_MAX_BYTES = 10
    too_big = SimpleUploadedFile("big.jpg", PNG_BYTES, content_type="image/jpeg")
    response = client.post(f"/api/v1/visits/{visit.id}/photos/", {"image": too_big}, **auth_headers)
    assert response.status_code == 400 and "limit is 10" in response.json()["image"][0]

    settings.PHOTO_MAX_BYTES = 5_000_000
    wrong_type = SimpleUploadedFile("x.jpg", PNG_BYTES, content_type="text/plain")
    response = client.post(f"/api/v1/visits/{visit.id}/photos/", {"image": wrong_type}, **auth_headers)
    assert response.status_code == 400 and "not an image" in response.json()["image"][0]

    response = client.post(f"/api/v1/visits/{visit.id}/photos/", {"caption": "no file"}, **auth_headers)
    assert response.status_code == 400 and "image" in response.json()


def test_seed_demo_is_realistic_and_idempotent():
    out = io.StringIO()
    call_command("seed_demo", stdout=out)
    assert "seeded 10 farmers" in out.getvalue()
    assert Farmer.objects.count() == 10
    assert Field.objects.count() >= 10
    assert set(Farmer.objects.values_list("district", flat=True)) == {"Rajshahi", "Bogura"}
    assert WaterLevelReading.objects.count() > 300
    kinds = set(Alert.objects.filter(resolved_at__isnull=True).values_list("kind", flat=True))
    assert kinds == {Alert.Kind.IRRIGATION_DUE, Alert.Kind.SENSOR_SILENT, Alert.Kind.OVERFLOW}
    assert all(f.area_m2 > 1000 for f in Field.objects.all())

    fields_before = Field.objects.count()
    call_command("seed_demo", stdout=io.StringIO())
    assert Farmer.objects.count() == 10 and Field.objects.count() == fields_before

    out = io.StringIO()
    call_command("awd_check", stdout=out)
    assert "opened 0" in out.getvalue()
