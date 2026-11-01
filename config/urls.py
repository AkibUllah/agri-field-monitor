from django.conf import settings
from django.conf.urls.static import static
from django.contrib import admin
from django.urls import path
from django.views.decorators.csrf import csrf_exempt
from strawberry.django.views import GraphQLView

from api.rest import HealthView, TokenView, VisitPhotoUploadView, WeeklyReportExportView
from api.schema import schema

urlpatterns = [
    path("admin/", admin.site.urls),
    path("health/", HealthView.as_view(), name="health"),
    path(
        "graphql/",
        csrf_exempt(
            GraphQLView.as_view(schema=schema, graphql_ide="graphiql" if settings.GRAPHIQL else None)
        ),
    ),
    path("api/v1/auth/token/", TokenView.as_view(), name="token"),
    path(
        "api/v1/visits/<int:visit_id>/photos/",
        VisitPhotoUploadView.as_view(),
        name="visit-photo-upload",
    ),
    path("api/v1/reports/weekly.<str:fmt>", WeeklyReportExportView.as_view(), name="weekly-report-export"),
]

if settings.DEBUG:
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
