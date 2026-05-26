from django.urls import path
from . import views

app_name = "api"

urlpatterns = [
    # REST API v1 Resource routes
    path("v1/documents/upload/", views.DocumentUploadAPI.as_view(), name="api_upload"),
    path("v1/documents/<int:document_id>/", views.DocumentDetailAPI.as_view(), name="api_detail"),
    path("v1/documents/<int:document_id>/verify/", views.DocumentVerifyAPI.as_view(), name="api_verify"),
    
    # HTML Integrations Guide & Webhooks Console
    path("integrations/", views.integration_guide, name="integration_guide"),
    path("integrations/webhooks/delete/<int:endpoint_id>/", views.delete_webhook, name="delete_webhook"),
]
