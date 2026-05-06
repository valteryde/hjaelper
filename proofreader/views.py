import json
import math
import fitz

from django.http import JsonResponse, FileResponse, Http404
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_POST, require_GET

from .models import Job
from .tasks import process_pdf, _extract_blocks, _make_chunks


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
    enable_grading = request.POST.get("enable_grading", "").lower() in ("true", "1", "on")

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
        enable_thread, enable_coherence, enable_factcheck, enable_grading,
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

@csrf_exempt
@require_POST
def stop_job(request, job_id):
    """Stop an ongoing job."""
    try:
        job = Job.objects.get(id=job_id)
    except Job.DoesNotExist:
        raise Http404("Job not found.")

    if job.status in [Job.Status.PENDING, Job.Status.PROCESSING]:
        job.status = Job.Status.ERROR
        job.error_message = "Cancelled by user."
        job.save(update_fields=["status", "error_message"])
    
    return JsonResponse({"status": job.status})


@csrf_exempt
@require_POST
def estimate_cost(request):
    """Save the PDF, calculate word count, chunks, and estimate costs."""
    pdf_file = request.FILES.get("pdf")
    model = request.POST.get("model", "gpt-4o").strip()
    
    enable_thread = request.POST.get("enable_thread", "").lower() in ("true", "1", "on")
    enable_coherence = request.POST.get("enable_coherence", "").lower() in ("true", "1", "on")
    enable_factcheck = request.POST.get("enable_factcheck", "").lower() in ("true", "1", "on")
    enable_grading = request.POST.get("enable_grading", "").lower() in ("true", "1", "on")
    
    try:
        chunk_size = int(request.POST.get("chunk_size", "2000"))
        chunk_size = max(200, min(50000, chunk_size))
    except (ValueError, TypeError):
        chunk_size = 2000

    if not pdf_file:
        return JsonResponse({"error": "No PDF file provided."}, status=400)
    if not pdf_file.name.lower().endswith(".pdf"):
        return JsonResponse({"error": "File must be a PDF."}, status=400)

    job = Job.objects.create(original_pdf=pdf_file, status=Job.Status.PENDING)

    try:
        doc = fitz.open(job.original_pdf.path)
        blocks = _extract_blocks(doc)
        doc.close()
    except Exception as e:
        job.status = Job.Status.ERROR
        job.error_message = f"Failed to parse PDF: {str(e)}"
        job.save()
        return JsonResponse({"error": "Could not read PDF file."}, status=400)
        
    words = sum(len(b["text"].split()) for b in blocks)
    chunks = _make_chunks(blocks, word_limit=chunk_size)
    num_chunks = len(chunks)
    
    passes_per_chunk = 1
    
    total_chunk_passes = num_chunks * passes_per_chunk
    
    extra_passes = 0
    if enable_thread: extra_passes += 1
    if enable_grading: extra_passes += 1
    if enable_coherence: extra_passes += 1
    if enable_factcheck: extra_passes += 1
    
    input_tokens_per_pass = (chunk_size * 1.33) + 300
    total_input_tokens = int((num_chunks * input_tokens_per_pass * passes_per_chunk) + (extra_passes * num_chunks * 200))
    
    total_output_tokens = int(total_input_tokens * 0.15)
    
    pricing = {
        "gpt-4o": {"in": 5.0, "out": 15.0},
        "gpt-4o-mini": {"in": 0.15, "out": 0.60},
        "claude-3-5-sonnet-20240620": {"in": 3.0, "out": 15.0},
        "claude-3-opus-20240229": {"in": 15.0, "out": 75.0},
        "claude-3-haiku-20240307": {"in": 0.25, "out": 1.25},
    }
    
    cost_estimate = None
    if model in pricing:
        rates = pricing[model]
        cost = (total_input_tokens / 1_000_000 * rates["in"]) + (total_output_tokens / 1_000_000 * rates["out"])
        cost_estimate = round(cost, 3)
        
    time_estimate_sec = 15 + math.ceil(total_chunk_passes / 5) * 5 + (extra_passes * 10)
    
    return JsonResponse({
        "job_id": str(job.id),
        "words": words,
        "num_chunks": num_chunks,
        "num_tasks": total_chunk_passes,
        "estimated_input_tokens": total_input_tokens,
        "estimated_output_tokens": total_output_tokens,
        "cost_estimate": cost_estimate,
        "time_estimate_sec": time_estimate_sec
    })

@csrf_exempt
@require_POST
def start_job(request):
    """Start the Celery processing for a previously estimated job."""
    job_id = request.POST.get("job_id")
    api_key = request.POST.get("api_key", "").strip()
    model = request.POST.get("model", "").strip()
    provider = request.POST.get("provider", "openai").strip().lower()
    language = request.POST.get("language", "").strip()
    harshness = request.POST.get("harshness", "").strip()
    skill_level = request.POST.get("skill_level", "").strip()
    custom_prompt = request.POST.get("custom_prompt", "").strip()

    enable_thread = request.POST.get("enable_thread", "").lower() in ("true", "1", "on")
    enable_coherence = request.POST.get("enable_coherence", "").lower() in ("true", "1", "on")
    enable_factcheck = request.POST.get("enable_factcheck", "").lower() in ("true", "1", "on")
    enable_grading = request.POST.get("enable_grading", "").lower() in ("true", "1", "on")

    try:
        chunk_size = int(request.POST.get("chunk_size", "2000"))
        chunk_size = max(200, min(50000, chunk_size))
    except (ValueError, TypeError):
        chunk_size = 2000

    valid_providers = ("openai", "openrouter", "anthropic")

    if not job_id:
        return JsonResponse({"error": "No job ID provided."}, status=400)
    if not api_key:
        return JsonResponse({"error": "No API key provided."}, status=400)
    if not model:
        return JsonResponse({"error": "No model specified."}, status=400)
    if provider not in valid_providers:
        return JsonResponse({"error": "Invalid provider."}, status=400)

    try:
        job = Job.objects.get(id=job_id)
    except Job.DoesNotExist:
        return JsonResponse({"error": "Job not found."}, status=404)

    if job.status != Job.Status.PENDING:
        return JsonResponse({"error": "Job has already been started or cancelled."}, status=400)

    process_pdf.delay(
        str(job.id), api_key, model, provider, chunk_size,
        language, harshness, skill_level, custom_prompt,
        enable_thread, enable_coherence, enable_factcheck, enable_grading,
    )

    return JsonResponse({"job_id": str(job.id)})
