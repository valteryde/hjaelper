from django.urls import path
from . import views

urlpatterns = [
    path("upload/", views.upload_pdf, name="upload_pdf"),
    path("status/<uuid:job_id>/", views.job_status, name="job_status"),
    path("download/<uuid:job_id>/", views.download_pdf, name="download_pdf"),
]
