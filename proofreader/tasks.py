import json
import logging
import re

import anthropic
import fitz  # PyMuPDF
from celery import chord, group, shared_task
from django.core.files.base import ContentFile
from django.db.models import F
from openai import OpenAI

from .models import Job
from .prompts import get_system_prompt

logger = logging.getLogger(__name__)

# Default words per chunk sent to the AI.
DEFAULT_CHUNK_WORD_LIMIT = 2000

# Severity → highlight color (RGB floats).
SEVERITY_COLORS = {
    "low":      (0.6, 0.9, 0.6),   # green
    "medium":   (1.0, 0.9, 0.0),   # yellow
    "high":     (1.0, 0.6, 0.2),   # orange
    "critical": (1.0, 0.3, 0.3),   # red
    "tone":     (0.0, 0.5, 1.0),   # blue
}

# Provider → OpenAI-compatible base URL mapping.
# Anthropic uses its own SDK and is handled separately.
PROVIDER_BASE_URLS = {
    "openai": None,  # default
    "openrouter": "https://openrouter.ai/api/v1",
}


def _extract_blocks(doc):
    """
    Extract text blocks with page number and bounding box.
    Returns a list of dicts: { page, text, bbox: [x0, y0, x1, y1] }
    """
    blocks = []
    for page_num in range(len(doc)):
        page = doc[page_num]
        for block in page.get_text("blocks"):
            # block = (x0, y0, x1, y1, text, block_no, block_type)
            # block_type 0 = text
            if block[6] == 0:
                text = block[4].strip()
                if text:
                    blocks.append({
                        "page": page_num,
                        "text": text,
                        "bbox": list(block[:4]),  # list for JSON serialization
                    })
    return blocks


def _make_chunks(blocks, word_limit=DEFAULT_CHUNK_WORD_LIMIT):
    """
    Group blocks into chunks of roughly `word_limit` words.
    Each chunk is a dict: { text, blocks: [original block refs] }
    """
    chunks = []
    current_text_parts = []
    current_blocks = []
    current_words = 0

    for block in blocks:
        word_count = len(block["text"].split())
        if current_words + word_count > word_limit and current_blocks:
            chunks.append({
                "text": "\n\n".join(current_text_parts),
                "blocks": current_blocks,
            })
            current_text_parts = []
            current_blocks = []
            current_words = 0

        current_text_parts.append(block["text"])
        current_blocks.append(block)
        current_words += word_count

    if current_blocks:
        chunks.append({
            "text": "\n\n".join(current_text_parts),
            "blocks": current_blocks,
        })

    return chunks


def _parse_ai_response(raw):
    """
    Parse the AI's raw text response into a list of findings.
    Handles markdown code fences and invalid JSON gracefully.
    """
    raw = raw.strip()
    raw = re.sub(r"^```(?:json)?\s*", "", raw)
    raw = re.sub(r"\s*```$", "", raw)

    try:
        findings = json.loads(raw)
    except json.JSONDecodeError:
        logger.warning("AI returned non-JSON response: %s", raw[:200])
        findings = []

    if not isinstance(findings, list):
        findings = []

    return findings


def _call_openai_compatible(client, model, chunk_text, language, skill_level, custom_prompt):
    """Call an OpenAI-compatible API (OpenAI, OpenRouter, etc.)."""
    system_prompt = get_system_prompt(language, skill_level, custom_prompt)
    response = client.chat.completions.create(
        model=model,
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": chunk_text},
        ],
        temperature=0.2,
    )
    return _parse_ai_response(response.choices[0].message.content)


def _call_anthropic(client, model, chunk_text, language, skill_level, custom_prompt):
    """Call the Anthropic API directly."""
    system_prompt = get_system_prompt(language, skill_level, custom_prompt)
    response = client.messages.create(
        model=model,
        max_tokens=4096,
        system=system_prompt,
        messages=[
            {"role": "user", "content": chunk_text},
        ],
        temperature=0.2,
    )
    return _parse_ai_response(response.content[0].text)


def _make_client(provider, api_key):
    """
    Create the appropriate API client for the given provider.
    Returns (client, call_fn) tuple.
    """
    if provider == "anthropic":
        client = anthropic.Anthropic(api_key=api_key)
        return client, _call_anthropic

    # OpenAI-compatible providers (openai, openrouter, etc.)
    base_url = PROVIDER_BASE_URLS.get(provider)
    kwargs = {"api_key": api_key}
    if base_url:
        kwargs["base_url"] = base_url
    client = OpenAI(**kwargs)
    return client, _call_openai_compatible


def _find_and_annotate(doc, blocks, sentence, feedback, severity="medium"):
    """
    Search for `sentence` in the extracted blocks and annotate the PDF
    with a color-coded highlight + sticky note on the first match found.
    """
    color = SEVERITY_COLORS.get(severity, SEVERITY_COLORS["medium"])
    note_text = f"[{severity.upper()}] {feedback}"
    sentence_lower = sentence.lower().strip()

    for block in blocks:
        if sentence_lower in block["text"].lower():
            page = doc[block["page"]]

            # Try to get precise quads for the sentence on this page.
            quads = page.search_for(sentence, quads=True)

            if quads:
                highlight = page.add_highlight_annot(quads=quads)
                highlight.set_colors(stroke=color)
                highlight.update()

                top_left = fitz.Point(quads[0].ul)
                note = page.add_text_annot(top_left, note_text)
                note.update()
            else:
                # Fallback: highlight the entire block bbox.
                rect = fitz.Rect(block["bbox"])
                highlight = page.add_highlight_annot(rect)
                highlight.set_colors(stroke=color)
                highlight.update()

                top_left = fitz.Point(rect.x0, rect.y0)
                note = page.add_text_annot(top_left, note_text)
                note.update()
            return True
            
    return False


# ---------------------------------------------------------------------------
# Celery tasks — chord pattern for parallel AI calls
# ---------------------------------------------------------------------------

@shared_task(bind=True, max_retries=2, default_retry_delay=5)
def proofread_chunk(self, chunk_data, api_key, model, provider, job_id, language="", skill_level="", custom_prompt=""):
    """
    Process a single chunk through the AI.
    Returns { chunk, findings } for the annotation callback.
    """
    try:
        client, call_fn = _make_client(provider, api_key)
        findings = call_fn(client, model, chunk_data["text"], language, skill_level, custom_prompt)
    except Exception as exc:
        logger.warning("Chunk failed: %s", exc)
        findings = []

    # Atomically increment progress counter.
    Job.objects.filter(id=job_id).update(
        completed_chunks=F("completed_chunks") + 1
    )

    return {
        "chunk": chunk_data,
        "findings": findings,
    }


@shared_task
def annotate_and_save(results, job_id):
    """
    Chord callback: receives all proofread results, annotates the PDF,
    and saves the final output.
    """
    try:
        job = Job.objects.get(id=job_id)
    except Job.DoesNotExist:
        logger.error("Job %s not found in callback", job_id)
        return

    try:
        doc = fitz.open(job.original_pdf.path)

        for result in results:
            blocks = result["chunk"]["blocks"]
            for finding in result["findings"]:
                sentence = finding.get("sentence", "")
                feedback = finding.get("feedback", "")
                severity = finding.get("severity", "medium")
                if sentence and feedback:
                    _find_and_annotate(doc, blocks, sentence, feedback, severity)

        annotated_bytes = doc.tobytes()
        doc.close()

        filename = f"proofread_{job_id}.pdf"
        job.annotated_pdf.save(filename, ContentFile(annotated_bytes), save=False)
        job.status = Job.Status.DONE
        job.save(update_fields=["status", "annotated_pdf"])

    except Exception as exc:
        logger.exception("Annotation failed for job %s: %s", job_id, exc)
        job.status = Job.Status.ERROR
        job.error_message = str(exc)
        job.save(update_fields=["status", "error_message"])


@shared_task
def mark_job_error(request, exc, traceback, job_id):
    """Chord error callback — marks the job as failed."""
    logger.error("Job %s chord failed: %s", job_id, exc)
    Job.objects.filter(id=job_id).update(
        status=Job.Status.ERROR,
        error_message=str(exc),
    )


@shared_task
def process_pdf(job_id, api_key, model, provider="openai", chunk_size=DEFAULT_CHUNK_WORD_LIMIT, language="", skill_level="", custom_prompt=""):
    """
    Entry point: extract paragraph blocks, chunk them, then dispatch parallel AI calls
    via a Celery chord. The annotation callback runs once all chunks finish.
    """
    try:
        job = Job.objects.get(id=job_id)
    except Job.DoesNotExist:
        logger.error("Job %s not found", job_id)
        return

    try:
        job.status = Job.Status.PROCESSING
        job.save(update_fields=["status"])

        doc = fitz.open(job.original_pdf.path)
        blocks = _extract_blocks(doc)
        doc.close()

        if not blocks:
            job.status = Job.Status.DONE
            job.save(update_fields=["status"])
            return

        chunks = _make_chunks(blocks, word_limit=chunk_size)
        job.total_chunks = len(chunks)
        job.save(update_fields=["total_chunks"])

        # Dispatch parallel chunk processing.
        # Worker concurrency (-c flag) throttles how many run simultaneously.
        workflow = chord(
            group(
                proofread_chunk.s(chunk, api_key, model, provider, str(job_id), language, skill_level, custom_prompt)
                for chunk in chunks
            ),
            annotate_and_save.s(str(job_id)),
        )
        workflow.on_error(mark_job_error.s(str(job_id)))
        workflow.apply_async()

    except Exception as exc:
        logger.exception("Job %s failed during setup: %s", job_id, exc)
        job.status = Job.Status.ERROR
        job.error_message = str(exc)
        job.save(update_fields=["status", "error_message"])
