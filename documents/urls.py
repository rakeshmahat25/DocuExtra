from django.urls import path
from . import views

app_name = "documents"

urlpatterns = [
    path("workflows/", views.workflow_list, name="workflow_list"),
    path("workflows/create/", views.workflow_create, name="workflow_create"),
    path("workflows/delete/<int:workflow_id>/", views.workflow_delete, name="workflow_delete"),
    
    path("upload/", views.document_upload, name="upload"),
    
    path("<int:document_id>/review/", views.review_detail, name="review_detail"),
    path("<int:document_id>/submit/", views.review_submit, name="review_submit"),
]
