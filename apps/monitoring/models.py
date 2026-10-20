from __future__ import annotations

from django.conf import settings
from django.core.validators import MaxValueValidator, MinValueValidator
from django.db import models

from apps.farms.models import Field


class Pipe(models.Model):
    """A perforated AWD field-water tube; readings are taken against the soil surface."""

    field = models.ForeignKey(Field, on_delete=models.CASCADE, related_name="pipes")
    code = models.CharField(max_length=40, unique=True, help_text="Label painted on the pipe")
    depth_cm = models.PositiveSmallIntegerField(default=25, help_text="Buried, perforated length")
    installed_on = models.DateField()
    device_id = models.CharField(max_length=60, blank=True, help_text="Set when a sensor is attached")
    is_active = models.BooleanField(default=True)

    class Meta:
        ordering = ["code"]

    def __str__(self) -> str:
        return self.code

    @property
    def has_device(self) -> bool:
        return bool(self.device_id)


class WaterLevelReading(models.Model):
    class Source(models.TextChoices):
        MANUAL = "manual", "Manual (field agent / farmer)"
        DEVICE = "device", "Sensor device"

    pipe = models.ForeignKey(Pipe, on_delete=models.CASCADE, related_name="readings")
    level_cm = models.DecimalField(
        max_digits=5,
        decimal_places=1,
        validators=[MinValueValidator(-60), MaxValueValidator(40)],
        help_text="Water level relative to soil surface; negative = below surface",
    )
    source = models.CharField(max_length=10, choices=Source.choices, default=Source.MANUAL)
    recorded_at = models.DateTimeField(db_index=True)
    recorded_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="+"
    )
    note = models.CharField(max_length=200, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-recorded_at"]
        indexes = [models.Index(fields=["pipe", "recorded_at"])]

    def __str__(self) -> str:
        return f"{self.pipe.code}: {self.level_cm} cm @ {self.recorded_at:%Y-%m-%d %H:%M}"


class IrrigationEvent(models.Model):
    class Method(models.TextChoices):
        PUMP = "pump", "Shallow tube well / pump"
        CANAL = "canal", "Canal / gravity"
        RAIN = "rain", "Rainfall (recorded, not applied)"

    field = models.ForeignKey(Field, on_delete=models.CASCADE, related_name="irrigation_events")
    started_at = models.DateTimeField(db_index=True)
    ended_at = models.DateTimeField(null=True, blank=True)
    method = models.CharField(max_length=10, choices=Method.choices, default=Method.PUMP)
    water_mm = models.DecimalField(
        max_digits=6, decimal_places=1, null=True, blank=True, help_text="Applied depth estimate"
    )
    note = models.CharField(max_length=200, blank=True)
    logged_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="+"
    )

    class Meta:
        ordering = ["-started_at"]

    def __str__(self) -> str:
        return f"{self.field.name} irrigated {self.started_at:%Y-%m-%d}"

    @property
    def duration_minutes(self) -> int | None:
        if self.ended_at is None:
            return None
        return int((self.ended_at - self.started_at).total_seconds() // 60)


class FieldVisit(models.Model):
    class CropStage(models.TextChoices):
        SEEDLING = "seedling", "Seedling"
        TILLERING = "tillering", "Tillering"
        PANICLE = "panicle", "Panicle initiation"
        FLOWERING = "flowering", "Flowering"
        RIPENING = "ripening", "Ripening"
        HARVESTED = "harvested", "Harvested"

    field = models.ForeignKey(Field, on_delete=models.CASCADE, related_name="visits")
    visitor = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="+"
    )
    visited_at = models.DateTimeField(db_index=True)
    crop_stage = models.CharField(max_length=12, choices=CropStage.choices, blank=True)
    notes = models.TextField(blank=True)
    lat = models.FloatField(null=True, blank=True)
    lng = models.FloatField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-visited_at"]

    def __str__(self) -> str:
        return f"Visit to {self.field.name} on {self.visited_at:%Y-%m-%d}"


def photo_upload_path(instance: VisitPhoto, filename: str) -> str:
    return f"visits/{instance.visit.field_id}/{instance.visit_id}/{filename}"


class VisitPhoto(models.Model):
    visit = models.ForeignKey(FieldVisit, on_delete=models.CASCADE, related_name="photos")
    image = models.FileField(upload_to=photo_upload_path)
    caption = models.CharField(max_length=200, blank=True)
    uploaded_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["uploaded_at"]

    def __str__(self) -> str:
        return self.image.name
