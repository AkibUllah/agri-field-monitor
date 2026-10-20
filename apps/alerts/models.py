from __future__ import annotations

from django.conf import settings
from django.db import models
from django.utils import timezone

from apps.farms.models import Field


class Alert(models.Model):
    class Kind(models.TextChoices):
        IRRIGATION_DUE = "irrigation_due", "Irrigation due (AWD threshold reached)"
        SENSOR_SILENT = "sensor_silent", "No readings received"
        OVERFLOW = "overflow", "Standing water too deep"

    class Severity(models.TextChoices):
        INFO = "info", "Info"
        WARNING = "warning", "Warning"
        CRITICAL = "critical", "Critical"

    field = models.ForeignKey(Field, on_delete=models.CASCADE, related_name="alerts")
    kind = models.CharField(max_length=20, choices=Kind.choices)
    severity = models.CharField(max_length=10, choices=Severity.choices, default=Severity.WARNING)
    message = models.CharField(max_length=300)
    value = models.DecimalField(max_digits=6, decimal_places=1, null=True, blank=True)
    triggered_at = models.DateTimeField(default=timezone.now, db_index=True)
    resolved_at = models.DateTimeField(null=True, blank=True)
    resolved_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="+"
    )
    resolution_note = models.CharField(max_length=200, blank=True)

    class Meta:
        ordering = ["-triggered_at"]
        constraints = [
            # At most one open alert of each kind per field.
            models.UniqueConstraint(
                fields=["field", "kind"],
                condition=models.Q(resolved_at__isnull=True),
                name="uniq_open_alert_per_field_kind",
            )
        ]

    def __str__(self) -> str:
        return f"{self.get_kind_display()} - {self.field.name}"

    @property
    def is_open(self) -> bool:
        return self.resolved_at is None

    def resolve(self, user=None, note: str = "") -> None:  # noqa: ANN001
        self.resolved_at = timezone.now()
        self.resolved_by = user
        self.resolution_note = note
        self.save(update_fields=["resolved_at", "resolved_by", "resolution_note"])
