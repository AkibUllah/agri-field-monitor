from __future__ import annotations

from decimal import Decimal

from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models

from apps.farms import geo


class Farmer(models.Model):
    name = models.CharField(max_length=120)
    phone = models.CharField(max_length=20, unique=True, help_text="BD mobile, e.g. 017XXXXXXXX")
    nid = models.CharField(max_length=17, blank=True, help_text="National ID (10, 13 or 17 digits)")
    village = models.CharField(max_length=120)
    union_name = models.CharField("union", max_length=120)
    upazila = models.CharField(max_length=120)
    district = models.CharField(max_length=120)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["name"]
        indexes = [models.Index(fields=["upazila", "union_name"])]

    def __str__(self) -> str:
        return f"{self.name} ({self.village}, {self.upazila})"


class Field(models.Model):
    class Crop(models.TextChoices):
        BORO = "boro", "Boro rice (dry season)"
        AMAN = "aman", "Aman rice (monsoon)"
        AUS = "aus", "Aus rice (pre-monsoon)"
        WHEAT = "wheat", "Wheat"
        MAIZE = "maize", "Maize"

    farmer = models.ForeignKey(Farmer, on_delete=models.CASCADE, related_name="fields")
    name = models.CharField(max_length=120)
    crop = models.CharField(max_length=10, choices=Crop.choices, default=Crop.BORO)
    polygon = models.JSONField(help_text="Boundary as a list of [lat, lng] pairs")
    area_m2 = models.DecimalField(max_digits=12, decimal_places=1, editable=False, default=0)
    centroid_lat = models.FloatField(editable=False, default=0.0)
    centroid_lng = models.FloatField(editable=False, default=0.0)
    union_name = models.CharField("union", max_length=120, blank=True)
    upazila = models.CharField(max_length=120, blank=True)
    district = models.CharField(max_length=120, blank=True)
    awd_threshold_cm = models.SmallIntegerField(
        default=settings.AWD_THRESHOLD_CM,
        help_text="Irrigate when the perched water level drops to this depth (negative = below surface)",
    )
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["farmer__name", "name"]
        indexes = [models.Index(fields=["upazila", "union_name"])]

    def __str__(self) -> str:
        return f"{self.name} - {self.farmer.name}"

    def save(self, *args, **kwargs) -> None:
        ring = geo.validate_polygon(self.polygon)
        self.polygon = [[lat, lng] for lat, lng in ring]
        self.area_m2 = Decimal(str(round(geo.shoelace_area(geo.project(ring)), 1)))
        self.centroid_lat, self.centroid_lng = geo.centroid(ring)
        if not self.union_name:
            self.union_name = self.farmer.union_name
        if not self.upazila:
            self.upazila = self.farmer.upazila
        if not self.district:
            self.district = self.farmer.district
        super().save(*args, **kwargs)

    def clean(self) -> None:
        try:
            geo.validate_polygon(self.polygon)
        except geo.InvalidPolygonError as exc:
            raise ValidationError({"polygon": str(exc)}) from exc

    @property
    def area_units(self) -> dict[str, float]:
        return geo.m2_to_units(float(self.area_m2))

    @property
    def active_season(self) -> Season | None:
        return self.seasons.filter(is_active=True).order_by("-transplanted_on").first()


class Season(models.Model):
    """One crop cycle on a field. AWD is practised between ``awd_start_on`` and ``awd_end_on``
    (typically from ~2 weeks after transplanting until flowering)."""

    field = models.ForeignKey(Field, on_delete=models.CASCADE, related_name="seasons")
    crop = models.CharField(max_length=10, choices=Field.Crop.choices, default=Field.Crop.BORO)
    variety = models.CharField(max_length=60, blank=True, help_text="e.g. BRRI dhan29")
    transplanted_on = models.DateField()
    awd_start_on = models.DateField()
    awd_end_on = models.DateField(null=True, blank=True)
    expected_harvest_on = models.DateField(null=True, blank=True)
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-transplanted_on"]

    def __str__(self) -> str:
        return f"{self.get_crop_display()} {self.transplanted_on:%Y} on {self.field.name}"

    def clean(self) -> None:
        if self.awd_start_on < self.transplanted_on:
            raise ValidationError({"awd_start_on": "AWD cannot start before transplanting"})
        if self.awd_end_on and self.awd_end_on < self.awd_start_on:
            raise ValidationError({"awd_end_on": "AWD end must be after AWD start"})
