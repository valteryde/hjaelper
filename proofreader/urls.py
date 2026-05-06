from django.urls import path
from . import views

urlpatterns = [
    path("upload/", views.upload_pdf, name="upload_pdf"),
    path("estimate/", views.estimate_cost, name="estimate_cost"),
    path("start/", views.start_job, name="start_job"),
    path("status/<uuid:job_id>/", views.job_status, name="job_status"),
    path("download/<uuid:job_id>/", views.download_pdf, name="download_pdf"),
    path("stop/<uuid:job_id>/", views.stop_job, name="stop_job"),
]
