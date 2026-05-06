import json

from django.http import JsonResponse, FileResponse, Http404
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_POST, require_GET

from .models import Job
from .tasks import process_pdf


@csrf_exempt
@require_POST
def upload_pdf(request):
    """Accept a PDF upload + API key, create a Job, kick off processing."""
    pdf_file = request.FILES.get("pdf")
    api_key = request.POST.get("api_key", "").strip()
    model = request.POST.get("model", "").strip()
    provider = request.POST.get("provider", "openai").strip().lower()
    language = request.POST.get("language", "").strip()
    harshness = request.POST.get("harshness", "").strip()
    skill_level = request.POST.get("skill_level", "").strip()
    custom_prompt = request.POST.get("custom_prompt", "").strip()

    # Parse analysis pass toggles.
    enable_thread = request.POST.get("enable_thread", "").lower() in ("true", "1", "on")
    enable_coherence = request.POST.get("enable_coherence", "").lower() in ("true", "1", "on")
    enable_factcheck = request.POST.get("enable_factcheck", "").lower() in ("true", "1", "on")

    # Parse chunk size (words per chunk). Default 2000, min 200, max 50000.
    try:
        chunk_size = int(request.POST.get("chunk_size", "2000"))
        chunk_size = max(200, min(50000, chunk_size))
    except (ValueError, TypeError):
        chunk_size = 2000

    valid_providers = ("openai", "openrouter", "anthropic")

    if not pdf_file:
        return JsonResponse({"error": "No PDF file provided."}, status=400)
    if not api_key:
        return JsonResponse({"error": "No API key provided."}, status=400)
    if not model:
        return JsonResponse({"error": "No model specified."}, status=400)
    if provider not in valid_providers:
        return JsonResponse(
            {"error": f"Invalid provider. Choose from: {', '.join(valid_providers)}"},
            status=400,
        )
    if not pdf_file.name.lower().endswith(".pdf"):
        return JsonResponse({"error": "File must be a PDF."}, status=400)

    job = Job.objects.create(original_pdf=pdf_file)

    # Dispatch to Celery — the API key is passed as an argument,
    # never persisted to the database.
    process_pdf.delay(
        str(job.id), api_key, model, provider, chunk_size,
        language, harshness, skill_level, custom_prompt,
        enable_thread, enable_coherence, enable_factcheck,
    )

    return JsonResponse({"job_id": str(job.id)})


@require_GET
def job_status(request, job_id):
    """Return the current status and progress of a job."""
    try:
        job = Job.objects.get(id=job_id)
    except Job.DoesNotExist:
        raise Http404("Job not found.")

    return JsonResponse({
        "job_id": str(job.id),
        "status": job.status,
        "total_chunks": job.total_chunks,
        "completed_chunks": job.completed_chunks,
        "error_message": job.error_message,
    })


@require_GET
def download_pdf(request, job_id):
    """Stream the annotated PDF back to the client."""
    try:
        job = Job.objects.get(id=job_id)
    except Job.DoesNotExist:
        raise Http404("Job not found.")

    if job.status != Job.Status.DONE or not job.annotated_pdf:
        return JsonResponse(
            {"error": "Annotated PDF is not ready yet."},
            status=404,
        )

    return FileResponse(
        job.annotated_pdf.open("rb"),
        as_attachment=True,
        filename=f"proofread_{job_id}.pdf",
    )
