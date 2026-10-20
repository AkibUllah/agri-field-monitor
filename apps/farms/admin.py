from django.contrib import admin

from apps.farms.models import Farmer, Field, Season


@admin.register(Farmer)
class FarmerAdmin(admin.ModelAdmin):
    list_display = ("name", "phone", "village", "union_name", "upazila", "district")
    search_fields = ("name", "phone", "village")
    list_filter = ("district", "upazila")


class SeasonInline(admin.TabularInline):
    model = Season
    extra = 0


@admin.register(Field)
class FieldAdmin(admin.ModelAdmin):
    list_display = (
        "name",
        "farmer",
        "crop",
        "area_m2",
        "union_name",
        "upazila",
        "awd_threshold_cm",
        "is_active",
    )
    list_filter = ("crop", "upazila", "is_active")
    search_fields = ("name", "farmer__name")
    readonly_fields = ("area_m2", "centroid_lat", "centroid_lng")
    inlines = [SeasonInline]


@admin.register(Season)
class SeasonAdmin(admin.ModelAdmin):
    list_display = ("field", "crop", "variety", "transplanted_on", "awd_start_on", "awd_end_on", "is_active")
    list_filter = ("crop", "is_active")
