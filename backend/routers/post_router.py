import os
import io
import uuid
import tempfile
import base64
import asyncio
import logging
import json
from typing import AsyncGenerator

from fastapi import APIRouter, UploadFile, File, Form, HTTPException, Request
from fastapi.responses import StreamingResponse
from google import genai
from google.genai import types

from models.design_spec import DesignSpec
from services.spec_builder import build_design_spec
from services.background_gen import generate_background
from services.compositor import composite
from services.qa import check_headline_contrast

logger = logging.getLogger("post_router")

router = APIRouter(prefix="/api", tags=["Post Generation"])

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

VALID_SIZES = {"square", "story", "og"}

CANVAS_SIZES = {
    "square": (1080, 1080),
    "story":  (1080, 1920),
    "og":     (1200, 630),
}

MAX_BRIEF_BYTES = 10 * 1024 * 1024   # 10 MB
MAX_LOGO_BYTES  =  2 * 1024 * 1024   #  2 MB

# Pipeline step definitions — IDs must match INITIAL_STEPS in the frontend
STEPS = [
    (1, "Parsing prompt & extracting brand data"),
    (2, "Building cinematic scene prompt"),
    (3, "Generating background image with AI model"),
    (4, "Rendering graphic — compositing text & branding"),
    (5, "Encoding final PNG for delivery"),
]

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def get_client(request: Request) -> genai.Client:
    return request.app.state.gemini_client


def sse_event(event: str, data: dict) -> str:
    """Format a single SSE message block."""
    return f"event: {event}\ndata: {json.dumps(data)}\n\n"


def step_event(step_id: int, status: str, detail: str | None = None) -> str:
    label = next(label for sid, label in STEPS if sid == step_id)
    payload: dict = {"id": step_id, "label": label, "status": status}
    if detail:
        payload["detail"] = detail
    return sse_event("step", payload)


# ---------------------------------------------------------------------------
# SSE streaming pipeline
# ---------------------------------------------------------------------------

async def run_pipeline(
    client: genai.Client,
    contents: list,
    size: str,
    logo_bytes: bytes | None,
) -> AsyncGenerator[str, None]:
    """
    Runs all pipeline stages and yields SSE events for each transition.
    Yields: step (running -> done/error), complete (with b64 image), or error.

    NOTE: build_design_spec, generate_background, and composite must all be
    plain `def` (synchronous) functions. asyncio.to_thread() runs them in a
    thread pool so they don't block the event loop. If you convert any of
    them to `async def`, replace the corresponding to_thread() call with a
    direct await.
    """

    try:
        # ── Stage 1+2: brand extraction → DesignSpec ───────────────────────
        yield step_event(1, "running")
        yield step_event(2, "running")

        try:
            spec: DesignSpec = await asyncio.to_thread(build_design_spec, client, contents)
            spec.canvas_w, spec.canvas_h = CANVAS_SIZES[size]
        except Exception as exc:
            yield step_event(1, "error", str(exc))
            yield step_event(2, "error")
            yield sse_event("error", {"message": f"Brand extraction failed: {exc}"})
            return

        yield step_event(1, "done", f"Canvas: {spec.canvas_w}x{spec.canvas_h}")

        # FIX Bug 5 — ternary was operator-precedence broken, now parenthesised
        prompt_preview = (
            spec.background_prompt[:120] + "..."
            if len(spec.background_prompt) > 120
            else spec.background_prompt
        )
        yield step_event(2, "done", prompt_preview)

        # ── Stage 3: background image ───────────────────────────────────────
        yield step_event(3, "running", "Calling Gemini image model...")

        try:
            bg_bytes: bytes = await asyncio.to_thread(generate_background, client, spec)
        except Exception as exc:
            yield step_event(3, "error", str(exc))
            yield sse_event("error", {"message": f"Background generation failed: {exc}"})
            return

        yield step_event(3, "done", f"{len(bg_bytes) // 1024} KB generated")

        # ── Stage 4: Pillow compositor ──────────────────────────────────────
        yield step_event(4, "running", "Layering background, text, branding & CTA...")

        try:
            png_bytes: bytes = await asyncio.to_thread(composite, bg_bytes, spec, logo_bytes)

            # WCAG contrast QA — one auto-retry with darkened overlay
            if not check_headline_contrast(spec):
                logger.warning("Contrast check failed — darkening overlay, recompositing.")
                spec.overlay_color = spec.overlay_color[:7] + "CC"
                png_bytes = await asyncio.to_thread(composite, bg_bytes, spec, logo_bytes)

        except Exception as exc:
            yield step_event(4, "error", str(exc))
            yield sse_event("error", {"message": f"Compositor failed: {exc}"})
            return

        yield step_event(4, "done", f"Composite: {len(png_bytes) // 1024} KB")

        # ── Stage 5: encode and emit ────────────────────────────────────────
        yield step_event(5, "running", "Encoding PNG as base64...")

        try:
            image_b64 = base64.b64encode(png_bytes).decode("utf-8")
        except Exception as exc:
            yield step_event(5, "error", str(exc))
            yield sse_event("error", {"message": f"Encoding failed: {exc}"})
            return

        yield step_event(5, "done", "Ready for delivery")

        # ── Complete ────────────────────────────────────────────────────────
        yield sse_event("complete", {
            "image_b64": image_b64,
            "canvas_w":  spec.canvas_w,
            "canvas_h":  spec.canvas_h,
            "size":      size,
        })

    except Exception as exc:
        logger.exception("Unhandled pipeline error:")
        yield sse_event("error", {"message": f"Unexpected error: {exc}"})


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------

@router.post("/generate-stream")
async def generate_stream(
    request: Request,
    prompt:  str        = Form(None),
    file:    UploadFile = File(None),
    logo:    UploadFile = File(None),
    size:    str        = Form("square"),
):
    """
    SSE endpoint — streams pipeline progress events, then a complete event
    containing the final image as a base64 PNG.

    Event types emitted:
        step      { id, label, status, detail? }
        complete  { image_b64, canvas_w, canvas_h, size }
        error     { message }
    """

    if not prompt and not file:
        raise HTTPException(400, "Provide at least a prompt or a brief file.")

    if size not in VALID_SIZES:
        raise HTTPException(400, f"size must be one of {sorted(VALID_SIZES)}.")

    client = get_client(request)
    contents: list = []
    temp_files: list[str] = []

    # File upload must complete before SSE stream opens —
    # multipart body cannot be read mid-stream.
    try:
        if file:
            safe_name = os.path.basename(file.filename or "upload")
            path = os.path.join(tempfile.gettempdir(), f"{uuid.uuid4().hex}_{safe_name}")
            temp_files.append(path)

            data = await file.read(MAX_BRIEF_BYTES + 1)
            if len(data) > MAX_BRIEF_BYTES:
                raise HTTPException(413, "Brief file exceeds 10 MB limit.")

            with open(path, "wb") as fh:
                fh.write(data)

            # FIX Bug 8 — content_type can be None
            mime = file.content_type or "application/octet-stream"
            logger.info("Uploading brief: %s (%s)", safe_name, mime)
            uploaded = client.files.upload(
                file=path,
                config=types.UploadFileConfig(mime_type=mime),
            )
            contents.append(uploaded)

        contents.append(
            prompt or "Generate a high-impact marketing post from this brief."
        )

        logo_bytes: bytes | None = None
        if logo:
            logo_bytes = await logo.read(MAX_LOGO_BYTES + 1)
            if len(logo_bytes) > MAX_LOGO_BYTES:
                raise HTTPException(413, "Logo file exceeds 2 MB limit.")
            logger.info("Logo received: %d KB", len(logo_bytes) // 1024)

    except HTTPException:
        # Clean up any temp files written before the error
        for p in temp_files:
            if p and os.path.exists(p):
                try:
                    os.remove(p)
                except Exception:
                    pass
        raise

    # Open SSE stream — cleanup happens in the generator's finally block
    async def event_stream() -> AsyncGenerator[bytes, None]:
        try:
            async for chunk in run_pipeline(client, contents, size, logo_bytes):
                yield chunk.encode("utf-8")
        finally:
            for p in temp_files:
                if p and os.path.exists(p):
                    try:
                        os.remove(p)
                        logger.info("Cleaned up: %s", p)
                    except Exception as err:
                        logger.warning("Cleanup failed for %s: %s", p, err)

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={
            "Cache-Control":     "no-cache",
            "X-Accel-Buffering": "no",       # disable nginx proxy buffering
            "Connection":        "keep-alive",
        },
    )


# ---------------------------------------------------------------------------
# Non-streaming endpoint — for server-to-server / CLI use
# ---------------------------------------------------------------------------

@router.post("/generate-post")
async def generate_post(
    request: Request,
    prompt:  str        = Form(None),
    file:    UploadFile = File(None),
    logo:    UploadFile = File(None),
    size:    str        = Form("square"),
):
    """
    Returns the final PNG directly (no SSE).
    Suitable for server-to-server or CLI usage.
    """

    if not prompt and not file:
        raise HTTPException(400, "Provide at least a prompt or a brief file.")
    if size not in VALID_SIZES:
        raise HTTPException(400, f"size must be one of {sorted(VALID_SIZES)}.")

    client = get_client(request)
    contents: list = []
    temp_files: list[str] = []

    try:
        if file:
            safe_name = os.path.basename(file.filename or "upload")
            path = os.path.join(tempfile.gettempdir(), f"{uuid.uuid4().hex}_{safe_name}")
            temp_files.append(path)

            data = await file.read(MAX_BRIEF_BYTES + 1)
            if len(data) > MAX_BRIEF_BYTES:
                raise HTTPException(413, "Brief file exceeds 10 MB limit.")

            with open(path, "wb") as fh:
                fh.write(data)

            # FIX Bug 8 — content_type can be None
            mime = file.content_type or "application/octet-stream"
            uploaded = client.files.upload(
                file=path,
                config=types.UploadFileConfig(mime_type=mime),
            )
            contents.append(uploaded)

        contents.append(prompt or "Generate a high-impact marketing post from this brief.")

        spec: DesignSpec = await asyncio.to_thread(build_design_spec, client, contents)
        spec.canvas_w, spec.canvas_h = CANVAS_SIZES[size]

        bg_bytes: bytes = await asyncio.to_thread(generate_background, client, spec)

        logo_bytes: bytes | None = None
        if logo:
            logo_bytes = await logo.read(MAX_LOGO_BYTES + 1)
            if len(logo_bytes) > MAX_LOGO_BYTES:
                raise HTTPException(413, "Logo file exceeds 2 MB limit.")

        png_bytes: bytes = await asyncio.to_thread(composite, bg_bytes, spec, logo_bytes)

        # WCAG contrast QA — one auto-retry
        if not check_headline_contrast(spec):
            spec.overlay_color = spec.overlay_color[:7] + "CC"
            png_bytes = await asyncio.to_thread(composite, bg_bytes, spec, logo_bytes)

        # FIX Bug 4 — io was missing from imports; now present at top of file
        return StreamingResponse(
            io.BytesIO(png_bytes),
            media_type="image/png",
            headers={
                "Content-Disposition": f'inline; filename="post_{size}.png"',
                "X-Canvas-Size":       f"{spec.canvas_w}x{spec.canvas_h}",
            },
        )

    except HTTPException:
        raise
    except Exception as exc:
        logger.exception("Pipeline failure:")
        raise HTTPException(500, str(exc)) from exc
    finally:
        for p in temp_files:
            if p and os.path.exists(p):
                try:
                    os.remove(p)
                except Exception as err:
                    logger.warning("Cleanup failed: %s", err)