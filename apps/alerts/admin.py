from django.contrib import admin

from apps.alerts.models import Alert


@admin.register(Alert)
class AlertAdmin(admin.ModelAdmin):
    list_display = ("field", "kind", "severity", "value", "triggered_at", "resolved_at")
    list_filter = ("kind", "severity", "field__upazila")
    date_hierarchy = "triggered_at"
    actions = ["resolve_selected"]

    @admin.action(description="Mark selected alerts resolved")
    def resolve_selected(self, request, queryset):  # noqa: ANN001
        for alert in queryset.filter(resolved_at__isnull=True):
            alert.resolve(request.user, note="resolved from admin")
