import uuid
from django.db import models


class Job(models.Model):
    """Tracks a single PDF proofreading job."""

    class Status(models.TextChoices):
        PENDING = "pending", "Pending"
        PROCESSING = "processing", "Processing"
        DONE = "done", "Done"
        ERROR = "error", "Error"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    status = models.CharField(
        max_length=20,
        choices=Status.choices,
        default=Status.PENDING,
    )
    total_chunks = models.IntegerField(default=0)
    completed_chunks = models.IntegerField(default=0)
    original_pdf = models.FileField(upload_to="originals/")
    annotated_pdf = models.FileField(upload_to="annotated/", null=True, blank=True)
    error_message = models.TextField(blank=True, default="")
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"Job {self.id} [{self.status}]"
