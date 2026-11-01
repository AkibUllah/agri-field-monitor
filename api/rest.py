"""REST endpoints: health, token issuance, photo upload and report downloads (GraphQL stays JSON-only)."""

from __future__ import annotations

from datetime import timedelta
from pathlib import Path

from django.conf import settings
from django.contrib.auth import authenticate
from django.db import connection
from django.http import HttpResponse
from django.utils import timezone
from rest_framework import permissions, serializers, status
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.alerts.export import export_filename, to_csv, to_xlsx
from apps.alerts.reports import GROUP_FIELDS, monday_of, weekly_report
from apps.core.auth import create_token
from apps.monitoring.models import FieldVisit, VisitPhoto


class HealthView(APIView):
    permission_classes = [permissions.AllowAny]
    authentication_classes: list = []

    def get(self, request):  # noqa: ANN001
        try:
            with connection.cursor() as cur:
                cur.execute("SELECT 1")
            db = "ok"
        except Exception:  # noqa: BLE001
            db = "error"
        code = status.HTTP_200_OK if db == "ok" else status.HTTP_503_SERVICE_UNAVAILABLE
        return Response({"status": "ok" if db == "ok" else "degraded", "database": db}, status=code)


class TokenSerializer(serializers.Serializer):
    username = serializers.CharField()
    password = serializers.CharField(trim_whitespace=False)


class TokenView(APIView):
    permission_classes = [permissions.AllowAny]
    authentication_classes: list = []

    def post(self, request):  # noqa: ANN001
        serializer = TokenSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        user = authenticate(request, **serializer.validated_data)
        if user is None:
            return Response({"detail": "Invalid credentials"}, status=status.HTTP_401_UNAUTHORIZED)
        return Response(
            {
                "token": create_token(user),
                "token_type": "Bearer",
                "expires_in": settings.JWT_LIFETIME_HOURS * 3600,
            }
        )


class PhotoUploadSerializer(serializers.Serializer):
    image = serializers.FileField()
    caption = serializers.CharField(max_length=200, required=False, allow_blank=True, default="")

    def validate_image(self, file):  # noqa: ANN001
        ext = Path(file.name).suffix.lower().lstrip(".")
        if ext not in settings.PHOTO_ALLOWED_EXTENSIONS:
            raise serializers.ValidationError(
                f"unsupported file type '.{ext}'; allowed: {', '.join(settings.PHOTO_ALLOWED_EXTENSIONS)}"
            )
        if file.size > settings.PHOTO_MAX_BYTES:
            raise serializers.ValidationError(
                f"file is {file.size} bytes; limit is {settings.PHOTO_MAX_BYTES}"
            )
        content_type = getattr(file, "content_type", "") or ""
        if content_type and not content_type.startswith("image/"):
            raise serializers.ValidationError(f"content type {content_type} is not an image")
        return file


class VisitPhotoSerializer(serializers.ModelSerializer):
    url = serializers.SerializerMethodField()

    class Meta:
        model = VisitPhoto
        fields = ("id", "visit", "url", "caption", "uploaded_at")

    def get_url(self, obj: VisitPhoto) -> str:
        request = self.context.get("request")
        return request.build_absolute_uri(obj.image.url) if request else obj.image.url


class VisitPhotoUploadView(APIView):
    """``POST multipart/form-data`` with ``image`` (+ optional ``caption``); ``GET`` lists photos."""

    permission_classes = [permissions.IsAuthenticated]

    def get(self, request, visit_id: int):  # noqa: ANN001
        visit = FieldVisit.objects.filter(pk=visit_id).first()
        if visit is None:
            return Response({"detail": "visit not found"}, status=status.HTTP_404_NOT_FOUND)
        data = VisitPhotoSerializer(visit.photos.all(), many=True, context={"request": request}).data
        return Response(data)

    def post(self, request, visit_id: int):  # noqa: ANN001
        visit = FieldVisit.objects.filter(pk=visit_id).first()
        if visit is None:
            return Response({"detail": "visit not found"}, status=status.HTTP_404_NOT_FOUND)
        serializer = PhotoUploadSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        photo = VisitPhoto.objects.create(
            visit=visit,
            image=serializer.validated_data["image"],
            caption=serializer.validated_data.get("caption", ""),
        )
        return Response(
            VisitPhotoSerializer(photo, context={"request": request}).data, status=status.HTTP_201_CREATED
        )


EXPORT_CONTENT_TYPES = {
    "csv": "text/csv; charset=utf-8",
    "xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
}


class WeeklyReportQuerySerializer(serializers.Serializer):
    week_start = serializers.DateField(required=False)
    group_by = serializers.ChoiceField(choices=sorted(GROUP_FIELDS), default="field")
    upazila = serializers.CharField(max_length=100, required=False, allow_blank=True, default="")
    union_name = serializers.CharField(max_length=100, required=False, allow_blank=True, default="")


class WeeklyReportExportView(APIView):
    """``GET /api/v1/reports/weekly.csv`` or ``.xlsx``: the ``weeklyReport`` rows as a file.

    Same filters as the GraphQL query; ``week_start`` defaults to the last full week.
    """

    permission_classes = [permissions.IsAuthenticated]

    def get(self, request, fmt: str):  # noqa: ANN001
        if fmt not in EXPORT_CONTENT_TYPES:
            return Response(
                {"detail": f"unsupported format '{fmt}'; use csv or xlsx"}, status=status.HTTP_404_NOT_FOUND
            )
        query = WeeklyReportQuerySerializer(data=request.query_params)
        query.is_valid(raise_exception=True)
        params = query.validated_data
        week_start = params.get("week_start") or monday_of(timezone.localdate() - timedelta(days=7))
        rows = weekly_report(
            week_start=week_start,
            group_by=params["group_by"],
            upazila=params["upazila"] or None,
            union_name=params["union_name"] or None,
        )
        if fmt == "csv":
            body = to_csv(rows)
        else:
            filters = {"upazila": params["upazila"], "union": params["union_name"]}
            body = to_xlsx(rows, week_start, params["group_by"], filters=filters)
        response = HttpResponse(body, content_type=EXPORT_CONTENT_TYPES[fmt])
        filename = export_filename(week_start, params["group_by"], fmt)
        response["Content-Disposition"] = f'attachment; filename="{filename}"'
        response["Cache-Control"] = "no-store"  # farmer names and phone-linked data stay off shared caches
        return response
