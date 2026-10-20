"""REST endpoints: health, token issuance and multipart photo upload (GraphQL stays JSON-only)."""

from __future__ import annotations

from pathlib import Path

from django.conf import settings
from django.contrib.auth import authenticate
from django.db import connection
from rest_framework import permissions, serializers, status
from rest_framework.response import Response
from rest_framework.views import APIView

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
