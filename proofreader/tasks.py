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
from .prompts import (
    get_system_prompt,
    get_coherence_prompt,
    get_factcheck_prompt,
    get_thread_prompt,
    get_grading_prompt,
)

logger = logging.getLogger(__name__)

# Default words per chunk sent to the AI.
DEFAULT_CHUNK_WORD_LIMIT = 2000

# Severity → highlight color (RGB floats).
SEVERITY_COLORS = {
    "low":        (0.6, 0.9, 0.6),   # green
    "medium":     (1.0, 0.9, 0.0),   # yellow
    "high":       (1.0, 0.6, 0.2),   # orange
    "critical":   (1.0, 0.3, 0.3),   # red
    "tone":       (0.0, 0.5, 1.0),   # blue
    "thread":     (0.6, 0.2, 0.8),   # purple
    "coherence":  (0.8, 0.4, 0.0),   # dark orange
    "factcheck":  (0.7, 0.0, 0.0),   # dark red
    "grading":    (0.0, 0.8, 0.4),   # emerald green
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


def _parse_ai_response_with_summary(raw):
    """
    Parse the AI's raw text response when summary is requested.
    Returns (findings_list, summary_string).
    """
    raw = raw.strip()
    raw = re.sub(r"^```(?:json)?\s*", "", raw)
    raw = re.sub(r"\s*```$", "", raw)

    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        logger.warning("AI returned non-JSON response: %s", raw[:200])
        return [], ""

    # The response should be a dict with "findings" and "summary"
    if isinstance(data, dict):
        findings = data.get("findings", [])
        summary = data.get("summary", "")
        if not isinstance(findings, list):
            findings = []
        return findings, summary

    # Fallback: if it's just an array (no summary), handle gracefully
    if isinstance(data, list):
        return data, ""

    return [], ""


def _call_openai_compatible(client, model, chunk_text, system_prompt):
    """Call an OpenAI-compatible API (OpenAI, OpenRouter, etc.)."""
    response = client.chat.completions.create(
        model=model,
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": chunk_text},
        ],
        temperature=0.2,
    )
    return response.choices[0].message.content


def _call_anthropic(client, model, chunk_text, system_prompt):
    """Call the Anthropic API directly."""
    response = client.messages.create(
        model=model,
        max_tokens=4096,
        system=system_prompt,
        messages=[
            {"role": "user", "content": chunk_text},
        ],
        temperature=0.2,
    )
    return response.content[0].text


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


def _find_and_annotate(doc, blocks, sentence, feedback, severity="medium", suggestion=""):
    """
    Search for `sentence` in the extracted blocks and annotate the PDF
    with a color-coded highlight + sticky note on the first match found.
    """
    color = SEVERITY_COLORS.get(severity, SEVERITY_COLORS["medium"])
    note_text = f"[{severity.upper()}] {feedback}"
    if suggestion:
        note_text += f"\nSuggestion: {suggestion}"
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


def _annotate_thread_finding(doc, chunks, chunk_index, feedback):
    """
    Annotate a thread-level finding on the first page of the referenced chunk.
    Since thread findings don't reference specific sentences, we place a
    sticky note at the top of the chunk's first block.
    """
    if chunk_index < 0 or chunk_index >= len(chunks):
        return False

    chunk = chunks[chunk_index]
    if not chunk["blocks"]:
        return False

    first_block = chunk["blocks"][0]
    page = doc[first_block["page"]]
    color = SEVERITY_COLORS["thread"]
    note_text = f"[THREAD] {feedback}"

    rect = fitz.Rect(first_block["bbox"])
    top_left = fitz.Point(rect.x0, rect.y0)
    note = page.add_text_annot(top_left, note_text)
    note.set_colors(stroke=color)
    note.update()
    return True


def _annotate_grading_finding(doc, grade, feedback):
    """
    Add a single comment in the top corner of the first page with some padding.
    """
    if not doc:
        return
    
    page = doc[0]
    color = SEVERITY_COLORS["grading"]
    note_text = f"[GRADE: {grade}]\n{feedback}"
    
    # Put it in the top corner with padding, e.g. x=50, y=50
    top_left = fitz.Point(50, 50)
    note = page.add_text_annot(top_left, note_text)
    note.set_colors(stroke=color)
    note.update()
    return True

# ---------------------------------------------------------------------------
# Celery tasks — chord pattern for parallel AI calls
# ---------------------------------------------------------------------------

@shared_task(bind=True, max_retries=2, default_retry_delay=5)
def proofread_chunk(self, chunk_data, api_key, model, provider, job_id,
                    language="", harshness="", skill_level="", custom_prompt="",
                    include_summary=False):
    """
    Process a single chunk through the AI.
    Returns { chunk, findings, summary? } for the annotation callback.
    """
    try:
        client, call_fn = _make_client(provider, api_key)
        system_prompt = get_system_prompt(language, harshness, skill_level, custom_prompt,
                                          include_summary=include_summary)
        raw = call_fn(client, model, chunk_data["text"], system_prompt)

        if include_summary:
            findings, summary = _parse_ai_response_with_summary(raw)
        else:
            findings = _parse_ai_response(raw)
            summary = ""
    except Exception as exc:
        logger.warning("Chunk failed: %s", exc)
        findings = []
        summary = ""

    # Atomically increment progress counter.
    Job.objects.filter(id=job_id).update(
        completed_chunks=F("completed_chunks") + 1
    )

    result = {
        "chunk": chunk_data,
        "findings": findings,
        "task_type": "proofread",
    }
    if include_summary:
        result["summary"] = summary
    return result


@shared_task(bind=True, max_retries=2, default_retry_delay=5)
def coherence_check_chunk(self, chunk_data, api_key, model, provider, job_id,
                          language="", harshness="", skill_level=""):
    """
    Check a single chunk for logical coherence.
    Returns { chunk, findings } for the annotation callback.
    """
    try:
        client, call_fn = _make_client(provider, api_key)
        system_prompt = get_coherence_prompt(language, harshness, skill_level)
        raw = call_fn(client, model, chunk_data["text"], system_prompt)
        findings = _parse_ai_response(raw)
    except Exception as exc:
        logger.warning("Coherence check failed: %s", exc)
        findings = []

    Job.objects.filter(id=job_id).update(
        completed_chunks=F("completed_chunks") + 1
    )

    return {
        "chunk": chunk_data,
        "findings": findings,
        "task_type": "coherence",
    }


@shared_task(bind=True, max_retries=2, default_retry_delay=5)
def factcheck_chunk(self, chunk_data, api_key, model, provider, job_id,
                    language="", harshness="", skill_level=""):
    """
    Fact-check a single chunk.
    Returns { chunk, findings } for the annotation callback.
    """
    try:
        client, call_fn = _make_client(provider, api_key)
        system_prompt = get_factcheck_prompt(language, harshness, skill_level)
        raw = call_fn(client, model, chunk_data["text"], system_prompt)
        findings = _parse_ai_response(raw)
    except Exception as exc:
        logger.warning("Fact-check failed: %s", exc)
        findings = []

    Job.objects.filter(id=job_id).update(
        completed_chunks=F("completed_chunks") + 1
    )

    return {
        "chunk": chunk_data,
        "findings": findings,
        "task_type": "factcheck",
    }


@shared_task
def annotate_and_save(results, job_id, enable_thread=False, enable_grading=False,
                      api_key="", model="", provider="openai",
                      language="", harshness="", skill_level=""):
    """
    Chord callback: receives all proofread results, annotates the PDF,
    and saves the final output.

    If enable_thread is True, collects summaries from proofread results
    and runs one additional API call for common thread analysis.
    """
    try:
        job = Job.objects.get(id=job_id)
    except Job.DoesNotExist:
        logger.error("Job %s not found in callback", job_id)
        return

    try:
        doc = fitz.open(job.original_pdf.path)

        # Collect chunks in order for thread annotation mapping.
        # We need to rebuild the chunk list to map thread findings back.
        chunk_list = []
        summaries = []

        for result in results:
            blocks = result["chunk"]["blocks"]

            # Track chunks for thread analysis mapping.
            if result.get("task_type") == "proofread":
                chunk_list.append(result["chunk"])
                if result.get("summary"):
                    summaries.append(result["summary"])

            # Annotate standard findings (proofread, coherence, factcheck).
            for finding in result["findings"]:
                sentence = finding.get("sentence", "")
                feedback = finding.get("feedback", "")
                severity = finding.get("severity", "medium")
                suggestion = finding.get("suggestion", "")
                if sentence and feedback:
                    _find_and_annotate(doc, blocks, sentence, feedback, severity, suggestion)

        # Common thread analysis — one extra API call using collected summaries.
        if enable_thread and summaries and api_key:
            try:
                thread_input = "\n\n".join(
                    f"CHUNK {i + 1}:\n{s}" for i, s in enumerate(summaries)
                )
                client, call_fn = _make_client(provider, api_key)
                system_prompt = get_thread_prompt(language, harshness, skill_level)
                raw = call_fn(client, model, thread_input, system_prompt)
                thread_findings = _parse_ai_response(raw)

                for finding in thread_findings:
                    chunk_idx = finding.get("chunk_index")
                    feedback = finding.get("feedback", "")
                    if chunk_idx is not None and feedback:
                        # Convert 1-based chunk index from AI to 0-based.
                        idx = int(chunk_idx) - 1
                        _annotate_thread_finding(doc, chunk_list, idx, feedback)
            except Exception as exc:
                logger.warning("Thread analysis failed for job %s: %s", job_id, exc)

        # Document grading analysis
        if enable_grading and summaries and api_key:
            try:
                grading_input = "\n\n".join(
                    f"CHUNK {i + 1}:\n{s}" for i, s in enumerate(summaries)
                )
                client, call_fn = _make_client(provider, api_key)
                system_prompt = get_grading_prompt(language, harshness, skill_level)
                raw = call_fn(client, model, grading_input, system_prompt)
                
                # Grading prompt returns a JSON object, so parse it
                try:
                    raw_clean = raw.strip()
                    raw_clean = re.sub(r"^```(?:json)?\s*", "", raw_clean)
                    raw_clean = re.sub(r"\s*```$", "", raw_clean)
                    grading_data = json.loads(raw_clean)
                except json.JSONDecodeError:
                    logger.warning("Grading returned non-JSON response: %s", raw[:200])
                    grading_data = {}
                
                grade = grading_data.get("grade")
                feedback = grading_data.get("feedback")
                if grade and feedback:
                    _annotate_grading_finding(doc, grade, feedback)
            except Exception as exc:
                logger.warning("Grading analysis failed for job %s: %s", job_id, exc)

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
def process_pdf(job_id, api_key, model, provider="openai",
                chunk_size=DEFAULT_CHUNK_WORD_LIMIT,
                language="", harshness="", skill_level="", custom_prompt="",
                enable_thread=False, enable_coherence=False,
                enable_factcheck=False, enable_grading=False):
    """
    Entry point: extract paragraph blocks, chunk them, then dispatch parallel AI calls
    via a Celery chord. The annotation callback runs once all chunks finish.

    Optional analysis passes:
    - enable_thread: adds summary to proofreading + one thread analysis call in callback
    - enable_coherence: adds parallel coherence check tasks per chunk
    - enable_factcheck: adds parallel fact-check tasks per chunk
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

        # Build the list of parallel tasks.
        tasks = []

        # Always: proofread each chunk.
        for chunk in chunks:
            tasks.append(
                proofread_chunk.s(
                    chunk, api_key, model, provider, str(job_id),
                    language, harshness, skill_level, custom_prompt,
                    include_summary=(enable_thread or enable_grading),
                )
            )

        # Optional: coherence check each chunk.
        if enable_coherence:
            for chunk in chunks:
                tasks.append(
                    coherence_check_chunk.s(
                        chunk, api_key, model, provider, str(job_id),
                        language, harshness, skill_level,
                    )
                )

        # Optional: fact-check each chunk.
        if enable_factcheck:
            for chunk in chunks:
                tasks.append(
                    factcheck_chunk.s(
                        chunk, api_key, model, provider, str(job_id),
                        language, harshness, skill_level,
                    )
                )

        job.total_chunks = len(tasks)
        job.save(update_fields=["total_chunks"])

        # Dispatch parallel processing.
        # The callback receives all results and annotates the PDF.
        callback = annotate_and_save.s(
            str(job_id),
            enable_thread=enable_thread,
            enable_grading=enable_grading,
            api_key=api_key if (enable_thread or enable_grading) else "",
            model=model if (enable_thread or enable_grading) else "",
            provider=provider if (enable_thread or enable_grading) else "openai",
            language=language,
            harshness=harshness,
            skill_level=skill_level,
        )

        workflow = chord(group(tasks), callback)
        workflow.on_error(mark_job_error.s(str(job_id)))
        workflow.apply_async()

    except Exception as exc:
        logger.exception("Job %s failed during setup: %s", job_id, exc)
        job.status = Job.Status.ERROR
        job.error_message = str(exc)
        job.save(update_fields=["status", "error_message"])
