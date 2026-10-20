from django.contrib import admin

from apps.monitoring.models import FieldVisit, IrrigationEvent, Pipe, VisitPhoto, WaterLevelReading


@admin.register(Pipe)
class PipeAdmin(admin.ModelAdmin):
    list_display = ("code", "field", "depth_cm", "installed_on", "device_id", "is_active")
    list_filter = ("is_active", "field__upazila")
    search_fields = ("code", "field__name")


@admin.register(WaterLevelReading)
class WaterLevelReadingAdmin(admin.ModelAdmin):
    list_display = ("pipe", "level_cm", "source", "recorded_at", "recorded_by")
    list_filter = ("source", "pipe__field__upazila")
    date_hierarchy = "recorded_at"
    autocomplete_fields = ("pipe",)


@admin.register(IrrigationEvent)
class IrrigationEventAdmin(admin.ModelAdmin):
    list_display = ("field", "started_at", "ended_at", "method", "water_mm", "logged_by")
    list_filter = ("method",)
    date_hierarchy = "started_at"


class VisitPhotoInline(admin.TabularInline):
    model = VisitPhoto
    extra = 0


@admin.register(FieldVisit)
class FieldVisitAdmin(admin.ModelAdmin):
    list_display = ("field", "visitor", "visited_at", "crop_stage")
    list_filter = ("crop_stage",)
    date_hierarchy = "visited_at"
    inlines = [VisitPhotoInline]
